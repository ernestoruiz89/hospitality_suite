"""Requirement-level supply checks against real native ledgers and scoped services."""
from datetime import timedelta
from unittest.mock import patch
import hashlib
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.service import canonical,operation


class TestInventoryAudit(IntegrationTestCase):
    def setUp(self):
        super().setUp();self.addCleanup(frappe.db.rollback);frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.other=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})

    def tearDown(self):frappe.set_user('Administrator');super().tearDown()

    def call(self,action,data,key=None):return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def stock(self,item='HS-DEMO-WATER',warehouse=None):
        return frappe.db.get_value('Bin',{'item_code':item,'warehouse':warehouse or self.prop.warehouse},'actual_qty') or 0

    def fingerprint(self):
        names=('HS Service Request','HS Charge','HS Audit Event','HS Request','Sales Invoice','Sales Invoice Item','Stock Entry','Stock Entry Detail','Stock Ledger Entry','GL Entry','Bin','Item Reorder','HS Stock Policy','Version')
        return {dt:hashlib.sha256(canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True)).encode()).hexdigest() for dt in names}

    def stay(self):
        room=frappe.get_doc('HS Room',{'property':self.prop.name});guest=frappe.get_doc('HS Guest',{'property':self.prop.name});start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,rooms=[dict(room=room.name,category=room.category,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        return self.call('walk_in',values)

    def request(self,stay,item='HS-DEMO-WATER',quantity=1):
        return self.call('request_service',dict(stay=stay['stay'],folio=stay['folio'],item=item,quantity=quantity))['service']

    def status(self,name,target,**extra):
        doc=frappe.get_doc('HS Service Request',name)
        return self.call('update_service',dict(service=name,status=target,modified=str(doc.modified),**extra))

    def item(self,label,asset=False):
        name='INV-AUD-'+uuid.uuid4().hex[:9]
        item=frappe.get_doc(dict(doctype='Item',item_code=name,item_name=label,item_group='All Item Groups',stock_uom='Nos',is_stock_item=0,is_sales_item=not asset,is_fixed_asset=asset,is_purchase_item=1))
        if asset:item.asset_category=frappe.db.get_value('Asset Category',{},'name')
        item.insert()
        if not asset:frappe.get_doc(dict(doctype='Item Price',item_code=name,price_list='HS Demo NIO',currency=self.prop.currency,price_list_rate=25)).insert()
        return name

    def test_all_seven_service_families_use_native_items_and_preserve_the_requested_price(self):
        stay=self.stay();services=[];initial=self.stock()
        for label in ('Minibar','Bebidas','Alimentos','Room service','Lavandería','Estacionamiento','Otro servicio'):
            item='HS-DEMO-WATER' if label=='Minibar' else self.item(label+' de prueba')
            name=self.request(stay,item);self.status(name,'In Progress')
            self.assertEqual(frappe.db.get_value('HS Service Request',name,'status'),'In Progress')
            self.status(name,'Delivered');doc=frappe.get_doc('HS Service Request',name)
            self.assertEqual(bool(doc.stock_entry),label=='Minibar');self.assertTrue(doc.charge);services.append(doc)
        invoice=frappe.get_doc('Sales Invoice',self.call('invoice',dict(folio=stay['folio']))['invoice'])
        self.assertEqual(invoice.update_stock,0);self.assertEqual(invoice.grand_total,1500+30+6*25)
        self.assertEqual(self.stock(),initial-1)
        self.assertTrue(all(frappe.db.get_value('HS Charge',s.charge,'sales_invoice')==invoice.name for s in services))

    def test_service_states_cancel_without_stock_and_forbid_skips_or_repeated_delivery(self):
        stay=self.stay();name=self.request(stay,quantity=2);initial=self.stock();self.status(name,'In Progress')
        before=self.fingerprint()
        with self.assertRaises(frappe.ValidationError):self.status(name,'Requested')
        self.assertEqual(self.fingerprint(),before)
        self.status(name,'Cancelled',reason='Cliente canceló antes de la entrega')
        self.assertEqual(self.stock(),initial);self.assertFalse(frappe.db.get_value('HS Service Request',name,'charge'))
        before=self.fingerprint()
        with self.assertRaises(frappe.ValidationError):self.status(name,'Delivered')
        self.assertEqual(self.fingerprint(),before)
        delivered=self.request(stay);self.status(delivered,'Delivered');before=self.fingerprint()
        with self.assertRaises(frappe.ValidationError):self.status(delivered,'Delivered')
        self.assertEqual(self.fingerprint(),before)

    def test_unbilled_return_reverses_related_adjustments_and_keeps_the_folio_reconciled(self):
        stay=self.stay();name=self.request(stay,quantity=2);initial=self.stock();self.status(name,'Delivered')
        service=frappe.get_doc('HS Service Request',name)
        adjustment=self.call('adjustment',dict(charge=service.charge,adjustment_type='Discount',amount=10,reason='Descuento previo a devolver'))['charge']
        courtesy=self.call('adjustment',dict(charge=service.charge,adjustment_type='Courtesy',reason='Cortesía del resto antes de devolver'))['charge']
        self.status(name,'Returned',reason='Dos unidades sin consumir devueltas')
        self.assertEqual(self.stock(),initial)
        self.assertEqual(frappe.db.get_value('HS Charge',service.charge,'status'),'Reversed')
        self.assertEqual(frappe.db.get_value('HS Charge',adjustment,'status'),'Reversed')
        self.assertEqual(frappe.db.get_value('HS Charge',courtesy,'status'),'Reversed')
        invoice=frappe.get_doc('Sales Invoice',self.call('invoice',dict(folio=stay['folio']))['invoice'])
        self.assertEqual(invoice.grand_total,1500)
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])

    def test_zero_quantity_is_rejected_and_failure_after_stock_posting_rolls_back_every_movement(self):
        stay=self.stay();before=self.fingerprint()
        for quantity in (0,-1):
            with self.assertRaises(frappe.ValidationError):self.request(stay,quantity=quantity)
            self.assertEqual(self.fingerprint(),before)
        name=self.request(stay);before=self.fingerprint()
        with patch('hospitality_suite.operations.charge',side_effect=RuntimeError('Failure after stock submission')):
            with self.assertRaises(RuntimeError):self.status(name,'Delivered')
        self.assertEqual(self.fingerprint(),before)
        self.status(name,'Delivered');self.assertEqual(frappe.db.get_value('HS Service Request',name,'status'),'Delivered')

    def test_invoiced_return_requires_native_credit_and_returns_stock_once(self):
        stay=self.stay();initial=self.stock();name=self.request(stay,quantity=2);self.status(name,'Delivered')
        invoice=self.call('invoice',dict(folio=stay['folio']))['invoice'];before=self.fingerprint()
        with self.assertRaises(frappe.ValidationError):self.status(name,'Returned',reason='Aún no existe nota de crédito')
        self.assertEqual(self.fingerprint(),before)
        note=self.call('credit_note',dict(invoice=invoice,reason='Devolución autorizada completa'))['credit_note']
        self.assertEqual(frappe.db.get_value('Sales Invoice',note,'return_against'),invoice)
        self.status(name,'Returned',reason='Mercancía devuelta después de la nota')
        self.assertEqual(self.stock(),initial);before=self.fingerprint()
        with self.assertRaises(frappe.ValidationError):self.status(name,'Returned',reason='No se devuelve otra vez')
        self.assertEqual(self.fingerprint(),before)
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])

    def test_minimums_include_zero_stock_are_local_to_each_warehouse_and_read_only(self):
        dest=self.call('create_warehouse',dict(warehouse_name='Ubicación auditoría '+uuid.uuid4().hex[:6]))['warehouse']
        for location,minimum in ((self.prop.warehouse,120),(dest,4)):
            self.call('stock_policy',dict(item='HS-DEMO-WATER',warehouse=location,purpose='Cleaning',minimum=minimum,reorder_quantity=8))
        before=self.fingerprint();primary=api.inventory_status(self.prop.name);secondary=api.inventory_status(self.prop.name,dest)
        row=lambda data:next(r for r in data['items'] if r.item_code=='HS-DEMO-WATER')
        self.assertEqual(row(primary)['minimum'],120);self.assertEqual(row(secondary)['minimum'],4)
        self.assertEqual(row(secondary)['actual_qty'],0);self.assertTrue(row(secondary)['needs_restock'])
        self.assertEqual(self.fingerprint(),before)
        foreign=api.execute(self.other.name,'create_warehouse',uuid.uuid4().hex,dict(warehouse_name='Ubicación ajena '+uuid.uuid4().hex[:6]))['warehouse']
        before=self.fingerprint()
        with self.assertRaises(frappe.PermissionError):api.inventory_status(self.prop.name,foreign)
        self.assertEqual(self.fingerprint(),before)
        self.assertFalse(any(r.minimum for r in api.inventory_status(self.other.name,foreign)['items']))

    def test_asset_policy_uses_native_registry_and_does_not_create_stock_minimums(self):
        fixed=frappe.db.get_value('Account',{'company':self.prop.company,'account_type':'Fixed Asset','is_group':0},'name')
        if not fixed:
            parent=frappe.db.get_value('Account',{'company':self.prop.company,'root_type':'Asset','is_group':1},'name')
            fixed=frappe.get_doc(dict(doctype='Account',company=self.prop.company,parent_account=parent,account_name='Activo de auditoría '+uuid.uuid4().hex[:6],account_currency=self.prop.currency,account_type='Fixed Asset')).insert().name
        frappe.get_doc(dict(doctype='Asset Category',asset_category_name='Auditoría de activos',non_depreciable_category=1,enable_cwip_accounting=0,accounts=[dict(company_name=self.prop.company,fixed_asset_account=fixed)])).insert()
        item=self.item('Activo estándar de prueba',asset=True)
        self.call('stock_policy',dict(item=item,purpose='Asset',minimum=0,reorder_quantity=0))
        row=next(r for r in api.inventory_status(self.prop.name)['items'] if r.item_code==item)
        self.assertFalse(row.stock_managed);self.assertIsNone(row.actual_qty);self.assertIsNone(row.minimum)
        self.assertFalse(row.needs_restock);self.assertFalse(frappe.db.exists('Item Reorder',{'parent':item,'warehouse':self.prop.warehouse}))
        before=self.fingerprint()
        with self.assertRaises(frappe.ValidationError):self.call('stock_policy',dict(item=item,purpose='Asset',minimum=1,reorder_quantity=2))
        self.assertEqual(self.fingerprint(),before)

    def test_native_pos_can_settle_room_charges_without_another_stock_issue_or_cash_projection(self):
        stay=self.stay();initial=self.stock();service=self.request(stay,quantity=2);self.status(service,'Delivered')
        shift=self.call('open_shift',dict(opening_amount=0))['shift']
        method=frappe.get_doc('HS Payment Method',{'property':self.prop.name,'currency':'NIO','is_cash':1})
        folio=frappe.get_doc('HS Folio',stay['folio'])
        invoice=frappe.get_doc(dict(doctype='Sales Invoice',company=self.prop.company,hs_property=self.prop.name,hs_stay=stay['stay'],hs_folio=folio.name,hs_shift=shift,
            customer=folio.customer,currency=folio.currency,debit_to=self.prop.receivable_account,cost_center=self.prop.cost_center,is_pos=1,update_stock=0,account_for_change_amount=method.account,disable_rounded_total=1))
        charges=frappe.get_all('HS Charge',filters={'folio':folio.name,'status':'Pending'},fields=['name','item','quantity','rate','amount'])
        for row in charges:invoice.append('items',dict(item_code=row.item,qty=row.quantity,rate=row.rate,cost_center=self.prop.cost_center,warehouse=self.prop.warehouse,hs_charge=row.name))
        invoice.append('payments',dict(mode_of_payment=method.mode_of_payment,account=method.account,amount=sum(row.amount for row in charges)))
        invoice.set_missing_values();invoice.insert().submit()
        self.assertEqual(invoice.outstanding_amount,0);self.assertEqual(self.stock(),initial-2)
        self.assertTrue(all(frappe.db.get_value('HS Charge',row.name,'sales_invoice')==invoice.name for row in charges))
        self.assertEqual(api.stay_detail(stay['stay'])['folios'][0]['balance']['outstanding'],'0.00')
        self.assertFalse(frappe.db.exists('HS Payment',{'sales_invoice':invoice.name}))
        from hospitality_suite.cashier import expected
        self.assertEqual(expected(frappe.get_doc('HS Shift',shift))['NIO'],'1560.00')
        from hospitality_suite.reconciliation import differences
        self.assertEqual(differences(self.prop),[])
