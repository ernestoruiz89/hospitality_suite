"""Configured native articles, accepted overtime and effective service prices."""
from datetime import timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime,nowdate,getdate

from hospitality_suite import api,timing
from hospitality_suite.pricing import decimal
from hospitality_suite.service import operation


class TestServiceItems(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Motel Luna Demo'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'M110'})
        self.hour=self.item('Hora adicional aceptada',uom='Hour')
        self.configure(extra_hour_item=self.hour)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def item(self,label,stock=False,uom='Nos'):
        return frappe.get_doc(dict(doctype='Item',item_code='HS-SERVICE-'+uuid.uuid4().hex[:9],item_name=label,item_group='Products' if stock else 'Services',
                                   stock_uom=uom,is_stock_item=int(stock),is_sales_item=1,valuation_rate=10 if stock else 0)).insert().name

    def configure(self,**values):
        self.prop.reload()
        api.save_setup(self.prop.name,'property',values,uuid.uuid4().hex,str(self.prop.modified))
        self.prop.reload()

    def enter(self,hours=3.5):
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(hours=hours)),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        quote=api.preview(self.prop.name,values)
        return self.call('walk_in',dict(values,acceptance=quote['acceptance']))

    def test_overtime_is_separate_and_keeps_accepted_article_through_extension_and_departure(self):
        with operation():
            rate=frappe.get_doc('HS Rate',{'property':self.prop.name,'mode':'Motel'})
            rate.rounding_minutes=15
            rate.grace_minutes=0
            rate.save()
        stay=self.enter(hours=3.25)
        records=frappe.get_all('HS Charge',filters={'stay':stay['stay']},fields=['item','amount','quantity'])
        self.assertEqual(sum(decimal(r.amount) for r in records if r.item==self.hour),decimal('37.50'))
        self.assertEqual(sum(decimal(r.amount) for r in records if r.item==self.prop.lodging_item),450)
        replacement=self.item('Hora adicional nueva configuración',uom='Hour')
        self.configure(extra_hour_item=replacement)
        doc=frappe.get_doc('HS Stay',stay['stay'])
        values=dict(stay=doc.name,folio=stay['folio'],ends_at=str(doc.ends_at+timedelta(minutes=30)),modified=str(doc.modified))
        quote=api.preview(self.prop.name,values,'extend')
        self.assertEqual(quote['charge_items']['extra_hour_item'],self.hour)
        key=uuid.uuid4().hex
        result=self.call('extend',dict(values,acceptance=quote['acceptance']),key)
        self.assertEqual(result,self.call('extend',dict(values,acceptance=quote['acceptance']),key))
        doc.reload()
        with patch('hospitality_suite.timing.now_datetime',return_value=doc.ends_at+timedelta(minutes=15)):
            quote=timing.departure(self.prop,dict(stay=doc.name))
            self.assertEqual(quote['amount'],'37.50')
            self.call('prepare_departure',dict(stay=doc.name,folio=stay['folio'],acceptance=quote['acceptance']))
            self.assertEqual(timing.departure(self.prop,dict(stay=doc.name))['amount'],'0.00')
        self.assertEqual(doc.reload().amount,600)
        records=frappe.get_all('HS Charge',filters={'stay':doc.name,'item':self.hour},fields=['amount','quantity'])
        self.assertEqual(len(records),3)
        self.assertEqual(sum(decimal(r.amount) for r in records),150)
        self.assertEqual(sum(decimal(r.quantity) for r in records),1)
        self.assertFalse(frappe.db.exists('HS Charge',{'stay':doc.name,'item':replacement}))
        invoice=self.call('invoice',dict(folio=stay['folio']))['invoice']
        inv=frappe.get_doc('Sales Invoice',invoice)
        self.assertEqual(inv.grand_total,600)
        self.assertEqual(sum(decimal(row.amount) for row in inv.items if row.item_code==self.hour),150)
        self.assertTrue(all(row.uom=='Hour' for row in inv.items if row.item_code==self.hour))
        self.assertFalse(frappe.db.exists('Stock Ledger Entry',{'voucher_no':invoice,'voucher_type':'Sales Invoice'}))

    def test_mapping_validates_type_before_finance_and_patch_preserves_explicit_choice(self):
        with self.assertRaises(frappe.MandatoryError):
            frappe.get_doc(dict(doctype='HS Rate',title='Tarifa sin establecimiento',category=self.room.category,mode='Motel',currency='NIO',amount=450,block_hours=3,included_people=1,rounding_minutes=60)).insert()
        for name in ('HS-DEMO-WATER',):
            with self.assertRaisesRegex(frappe.ValidationError,'sin inventario'):
                self.configure(extra_hour_item=name)
        with self.assertRaisesRegex(frappe.ValidationError,'horas adicionales'):
            self.configure(extra_hour_item=None)
        with self.assertRaisesRegex(frappe.ValidationError,'fracciones'):
            self.configure(extra_hour_item=self.item('Cargo con unidad entera'))
        from hospitality_suite.patches.v0_4.default_extra_hour_item import execute
        modified=self.prop.reload().modified
        execute();execute()
        self.assertEqual(self.prop.reload().extra_hour_item,self.hour)
        self.assertEqual(self.prop.modified,modified)
        self.configure(extra_hour_item=self.prop.lodging_item)
        with operation():
            rate=frappe.get_doc('HS Rate',{'property':self.prop.name,'mode':'Motel'})
            rate.rounding_minutes=15
            rate.grace_minutes=0
            rate.save()
        stay=self.enter(hours=3.25)
        invoice=self.call('invoice',dict(folio=stay['folio']))['invoice']
        inv=frappe.get_doc('Sales Invoice',invoice)
        self.assertEqual(inv.grand_total,487.5)
        self.assertTrue(all(row.qty==1 for row in inv.items),'The legacy whole-unit article still bills one charge')
        frappe.set_user('receptionist@hospitality.example.invalid')
        with self.assertRaises(frappe.PermissionError):
            api.service_configuration(self.prop.name,'HS-DEMO-WATER')

    def test_food_minibar_laundry_and_other_services_use_native_prices_and_stock_once(self):
        stay=self.enter(hours=3)
        labels=['Alimentación de prueba','Minibar de prueba','Lavandería de huésped de prueba','Otro servicio de prueba']
        services=[]
        for index,label in enumerate(labels):
            item='HS-DEMO-WATER' if index==1 else self.item(label)
            if index!=1:
                frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=40+index,valid_from=nowdate(),valid_upto=nowdate())).insert()
            info=api.service_configuration(self.prop.name,item)['service']
            self.assertEqual(info['status'],'Priced')
            created=self.call('request_service',dict(stay=stay['stay'],folio=stay['folio'],item=item,quantity=1))
            request=frappe.get_doc('HS Service Request',created['service'])
            key=uuid.uuid4().hex
            values=dict(service=request.name,status='Delivered',modified=str(request.modified))
            first=self.call('update_service',values,key)
            self.assertEqual(first,self.call('update_service',values,key))
            request.reload()
            self.assertEqual(bool(request.stock_entry),index==1)
            if index==1:
                self.assertEqual(frappe.db.get_value('Stock Entry',request.stock_entry,'docstatus'),1)
                self.assertEqual(frappe.db.count('Stock Ledger Entry',{'voucher_type':'Stock Entry','voucher_no':request.stock_entry,'is_cancelled':0}),1)
            services.append(request)
        invoice=self.call('invoice',dict(folio=stay['folio']))['invoice']
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice,'update_stock'),0)
        self.assertEqual(frappe.db.get_value('Sales Invoice',invoice,'grand_total'),450+40+30+42+43)
        self.assertTrue(all(frappe.db.get_value('HS Charge',s.charge,'sales_invoice')==invoice for s in services))

    def test_expired_future_and_overlapping_prices_are_not_silently_used(self):
        stay=self.enter(hours=3)
        item=self.item('Servicio con vigencia')
        today=getdate(nowdate())
        for start,end,amount in [(today-timedelta(days=2),today-timedelta(days=1),10),(today+timedelta(days=1),None,20)]:
            frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=amount,valid_from=start,valid_upto=end)).insert()
        def request():
            return self.call('request_service',dict(stay=stay['stay'],folio=stay['folio'],item=item,quantity=1))
        self.assertEqual(api.service_configuration(self.prop.name,item)['service']['status'],'Missing')
        with self.assertRaisesRegex(frappe.ValidationError,'vigente e inequívoco'):
            request()
        price=frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=35,valid_from=today,valid_upto=today)).insert()
        self.assertEqual(request()['amount'],'35.00')
        # An overlapping native record with a different validity interval.
        frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=36,valid_from=today-timedelta(days=1),valid_upto=today+timedelta(days=1))).insert()
        self.assertEqual(api.service_configuration(self.prop.name,item)['service']['status'],'Ambiguous')
        with self.assertRaisesRegex(frappe.ValidationError,'vigente e inequívoco'):
            request()
        self.assertEqual(frappe.db.count('HS Service Request',{'item':item}),1)

    def test_customer_prices_do_not_apply_to_another_payer_and_audit_keeps_source(self):
        stay=self.enter(hours=3)
        item=self.item('Servicio con precio por pagador')
        common=frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=25)).insert()
        specific=frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=40,customer=self.guest.customer)).insert()
        other=frappe.get_doc(dict(doctype='Customer',customer_name='Otro pagador '+uuid.uuid4().hex[:6],customer_type='Company',customer_group='Individual',territory='Nicaragua')).insert()
        frappe.get_doc(dict(doctype='Item Price',item_code=item,price_list='HS Demo NIO',currency='NIO',price_list_rate=99,customer=other.name)).insert()
        self.assertEqual(decimal(api.service_configuration(self.prop.name,item)['service']['rate']),25)
        created=self.call('request_service',dict(stay=stay['stay'],folio=stay['folio'],item=item,quantity=2))
        self.assertEqual(created['amount'],'80.00')
        event=frappe.get_doc('HS Audit Event',{'source_name':created['service'],'action':'Request service'})
        self.assertEqual(frappe.parse_json(event.details)['item_price'],specific.name)
        with operation():
            specific.valid_from=getdate(nowdate())-timedelta(days=2)
            specific.valid_upto=getdate(nowdate())-timedelta(days=1)
            specific.save()
        created=self.call('request_service',dict(stay=stay['stay'],folio=stay['folio'],item=item,quantity=1))
        self.assertEqual(created['amount'],'25.00')

    def test_legacy_booking_remains_a_single_accepted_charge(self):
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(hours=3,minutes=30)),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=1)])
        quote=api.preview(self.prop.name,values)
        booked=self.call('reserve',dict(values,acceptance=quote['acceptance']))
        booking=frappe.get_doc('HS Booking',booked['booking'])
        snapshot=frappe.parse_json(booking.quote_snapshot)
        for line in snapshot['lines']:
            for key in ('charge_items','lodging_amount','extra_hours_amount','extra_hours_quantity'):
                line.pop(key,None)
        # Explicit legacy fixture with the old accepted snapshot shape.
        frappe.db.set_value('HS Booking',booking.name,'quote_snapshot',frappe.as_json(snapshot),update_modified=False)
        for name in frappe.get_all('HS Allocation',filters={'booking':booking.name},pluck='name'):
            frappe.db.set_value('HS Allocation',name,'quote_snapshot',frappe.as_json(snapshot['lines'][0]),update_modified=False)
        entered=self.call('check_in',dict(booking=booking.name,modified=str(booking.modified)))
        rows=frappe.get_all('HS Charge',filters={'stay':entered['stay']},fields=['item','amount'])
        self.assertEqual([(row.item,decimal(row.amount)) for row in rows],[(self.prop.lodging_item,decimal(600))])

    def test_cheaper_room_credit_spans_base_and_overtime_without_negative_invoice_lines(self):
        stay=self.enter(hours=4)
        category=frappe.get_doc(dict(doctype='HS Category',property=self.prop.name,company=self.prop.company,category_name='Económica de prueba',capacity=2)).insert()
        room=frappe.get_doc(dict(doctype='HS Room',property=self.prop.name,company=self.prop.company,room_number='M201',category=category.name,active=1,cleaning_status='Clean')).insert()
        frappe.get_doc(dict(doctype='HS Rate',property=self.prop.name,company=self.prop.company,title='Bloque económico',category=category.name,
                            mode='Motel',currency='NIO',amount=100,block_hours=6,extra_hour_rate=0,rounding_minutes=60,included_people=2,priority=10,active=1)).insert()
        doc=frappe.get_doc('HS Stay',stay['stay'])
        clock=doc.starts_at+timedelta(minutes=10)
        values=dict(stay=doc.name,room=room.name,folio=stay['folio'],modified=str(doc.modified),reason='Cambio sintético a menor precio')
        with patch('hospitality_suite.operations.now_datetime',return_value=clock),patch('hospitality_suite.availability.now_datetime',return_value=clock):
            quote=api.preview(self.prop.name,values,'change_room')
            self.assertLess(decimal(quote['difference']),-450)
            key=uuid.uuid4().hex
            changed=self.call('change_room',dict(values,acceptance=quote['acceptance']),key)
            self.assertEqual(changed,self.call('change_room',dict(values,acceptance=quote['acceptance']),key))
        credits=frappe.get_all('HS Charge',filters={'stay':doc.name,'amount':['<',0]},fields=['item','amount','applies_to_charge'])
        self.assertEqual({r.item for r in credits},{self.prop.lodging_item,self.hour})
        self.assertEqual(sum(decimal(r.amount) for r in credits),decimal(quote['difference']))
        self.assertTrue(all(r.applies_to_charge for r in credits))
        invoice=self.call('invoice',dict(folio=stay['folio']))['invoice']
        inv=frappe.get_doc('Sales Invoice',invoice)
        self.assertEqual(decimal(inv.grand_total),decimal(doc.reload().amount))
        self.assertTrue(all(decimal(row.amount)>=0 for row in inv.items))
