"""Historical explanation scope, immutable rates and the native account print."""
from datetime import timedelta
import json
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.printing import hs_account_context
from hospitality_suite.service import canonical,operation
from hospitality_suite.tariff_explanations import describe_charge


class TestTariffExplanations(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H101'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})
        self.now=now_datetime().replace(microsecond=0)

    def tearDown(self):
        frappe.set_user('Administrator')
        super().tearDown()

    def command(self,action,data):
        return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def enter(self,nights=1,hours=None,people=1,extra_beds=0):
        values=dict(starts_at=str(self.now),ends_at=str(self.now+(timedelta(hours=hours) if hours else timedelta(days=nights))),
                    customer=self.guest.customer,guest=self.guest.name,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=people,extra_beds=extra_beds)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        return self.command('walk_in',values)

    def rows(self,stay):
        return api.stay_detail(stay)['charges']

    def rate(self):
        return frappe.get_doc('HS Rate',{'property':self.prop.name,'category':self.room.category,'mode':self.prop.mode})

    def motel(self):
        self.prop=frappe.get_doc('HS Property',{'property_name':'Luna Demo · Por tiempo'})
        self.room=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'M101'})
        self.guest=frappe.get_doc('HS Guest',{'property':self.prop.name})

    def supplement_rate(self):
        with operation():
            category=frappe.get_doc('HS Category',self.room.category)
            category.capacity=4;category.max_extra_beds=1;category.save()
            rate=self.rate();rate.included_people=2;rate.additional_person_rate=50;rate.extra_bed_rate=100;rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        return rate

    def separate_hours(self):
        item=frappe.get_doc(dict(doctype='Item',item_code='HS-TARIFF-'+uuid.uuid4().hex[:9],item_name='Horas adicionales aceptadas',
                                item_group='Services',stock_uom='Hour',is_stock_item=0,is_sales_item=1)).insert()
        with operation():
            self.prop.extra_hour_item=item.name;self.prop.save()

    def fingerprints(self):
        return {dt:canonical(frappe.db.sql('SELECT * FROM `tab'+dt+'` ORDER BY name',as_dict=True))
                for dt in ('HS Stay','HS Booking','HS Allocation','HS Folio','HS Charge','HS Payment','Sales Invoice','Payment Entry','Journal Entry','GL Entry','Stock Ledger Entry','HS Audit Event','Version')}

    def test_seasonal_nights_and_supplements_survive_master_price_and_title_changes_without_writes(self):
        rate=self.supplement_rate()
        with operation():
            seasonal=frappe.copy_doc(rate)
            seasonal.title='Temporada aceptada';seasonal.amount=2000;seasonal.priority=rate.priority+1
            seasonal.valid_from=(self.now+timedelta(days=1)).date();seasonal.valid_to=seasonal.valid_from
            seasonal.insert()
        stay=self.enter(nights=2,people=3,extra_beds=1)['stay']
        before=self.rows(stay)[0]['pricing']
        self.assertEqual([r['amount'] for r in before['entries']],['1650.00','2150.00'])
        self.assertIn('Temporada aceptada',before['entries'][1]['label'])
        self.assertIn('Personas adicionales: 1 × 50.0 = 50.0 NIO',before['entries'][0]['details'])
        self.assertTrue(any('Camas adicionales' in text for text in before['entries'][0]['details']))
        with operation():
            for target in (rate,seasonal):
                target.title='Tarifa nueva que no debe aparecer';target.amount=9999;target.additional_person_rate=999;target.change_reason='Preparación de tarifa sintética para la prueba';target.save()
        fingerprints=self.fingerprints()
        self.assertEqual(self.rows(stay)[0]['pricing'],before)
        printed=hs_account_context(stay)['charges'][0]
        self.assertNotIn('pricing',printed)
        self.assertEqual(printed.amount,3800)
        self.assertEqual(self.fingerprints(),fingerprints)

    def test_scheduled_nightly_charges_explain_only_their_own_night(self):
        with operation():
            self.prop.lodging_charge_policy='Nightly';self.prop.save()
        stay=self.enter(nights=3)['stay']
        rows=self.rows(stay)
        self.assertEqual(len(rows),3)
        self.assertEqual({r.status for r in rows},{'Scheduled'})
        labels=[]
        for row in rows:
            self.assertEqual(len(row.pricing['entries']),1)
            self.assertEqual(row.pricing['entries'][0]['amount'],'1500.00')
            self.assertIn('Desglose del cargo',row.pricing['scope'])
            labels.append(row.pricing['entries'][0]['label'])
        self.assertEqual(len(set(labels)),3)

    def test_motel_base_and_overtime_are_separate_and_keep_accepted_grace_rounding_and_occupancy(self):
        self.motel();self.separate_hours();rate=self.supplement_rate()
        with operation():
            rate.grace_minutes=10;rate.rounding_minutes=30;rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        stay=self.enter(hours=3+41/60,people=3,extra_beds=1)['stay']
        rows=self.rows(stay)
        base=next(r for r in rows if r.item==self.prop.lodging_item)
        hours=next(r for r in rows if r.item==self.prop.extra_hour_item)
        self.assertEqual(base.pricing['recorded_amount'],'600.0')
        self.assertEqual(len(base.pricing['entries']),1)
        self.assertEqual(base.pricing['entries'][0]['amount'],'600.00')
        self.assertEqual(hours.pricing['entries'][0]['amount'],'150.00')
        self.assertTrue(any('10 min' in line and '30 min' in line for line in hours.pricing['entries'][0]['details']))
        self.assertIn('Fracciones aceptadas: 2 de 30 min.',hours.pricing['entries'][0]['details'])
        previous={r.name:r.pricing for r in rows}
        with operation():
            rate.amount=9000;rate.grace_minutes=0;rate.rounding_minutes=15;rate.title='Nuevo precio';rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        self.assertEqual({r.name:r.pricing for r in self.rows(stay)},previous)

    def test_second_motel_extension_distinguishes_a_new_difference_from_total_overtime_reference(self):
        self.motel();self.separate_hours();entered=self.enter(hours=3)
        for hours in (4,5):
            stay=frappe.get_doc('HS Stay',entered['stay'])
            data=dict(stay=stay.name,modified=str(stay.modified),folio=entered['folio'],ends_at=str(self.now+timedelta(hours=hours)))
            data['acceptance']=api.preview(self.prop.name,data,'extend')['acceptance']
            self.command('extend',data)
        rows=[r for r in self.rows(stay.name) if r.description=='Extensión de estancia']
        last=next(r for r in rows if json.loads(r.quote_snapshot)['extra_hours_quantity']=='2')
        self.assertEqual(last.pricing['recorded_amount'],'150.0')
        self.assertEqual(last.pricing['entries'][0]['amount'],'300.00')
        self.assertIn('solamente una diferencia',last.pricing['scope'])

    def test_legacy_shared_article_shows_quote_components_as_reference_for_each_recorded_part(self):
        self.motel()
        # This is an old shared-article contract, not a dependency on demo history.
        with operation():
            self.prop.extra_hour_item=self.prop.lodging_item;self.prop.save()
        entered=self.enter(hours=5)
        rows=self.rows(entered['stay'])
        self.assertEqual(len(rows),2)
        self.assertEqual(self.prop.lodging_item,self.prop.extra_hour_item)
        for row in rows:
            self.assertEqual([r['amount'] for r in row.pricing['entries']],['450.00','300.00'])
            self.assertEqual(row.pricing['recorded_amount'],str(row.amount))
            self.assertIn('solamente una diferencia o parte',row.pricing['scope'])
            self.assertTrue(any('no son nuevos cargos' in note for note in row.pricing['notes']))

    def test_hotel_extension_explains_new_nights_without_claiming_the_whole_stay_is_a_new_charge(self):
        entered=self.enter()
        stay=frappe.get_doc('HS Stay',entered['stay'])
        values=dict(stay=stay.name,modified=str(stay.modified),folio=entered['folio'],ends_at=str(self.now+timedelta(days=2)))
        values['acceptance']=api.preview(self.prop.name,values,'extend')['acceptance']
        self.command('extend',values)
        extended=next(r for r in self.rows(stay.name) if r.description=='Extensión de estancia')
        self.assertEqual(extended.pricing['recorded_amount'],'1500.0')
        self.assertEqual(len(extended.pricing['entries']),1)
        self.assertEqual(extended.pricing['entries'][0]['amount'],'1500.00')
        self.assertEqual(json.loads(extended.quote_snapshot)['amount'],'3000.00')

    def test_room_change_difference_does_not_present_destination_quote_as_an_additional_charge(self):
        entered=self.enter(nights=2)
        with operation():
            category=frappe.get_doc(dict(doctype='HS Category',property=self.prop.name,company=self.prop.company,category_name='Destino histórico',capacity=2)).insert()
            room=frappe.get_doc(dict(doctype='HS Room',property=self.prop.name,company=self.prop.company,room_number='UX-TARIFF-TARGET',category=category.name,active=1,cleaning_status='Clean')).insert()
            rate=frappe.get_doc(dict(doctype='HS Rate',property=self.prop.name,company=self.prop.company,category=category.name,title='Destino aceptado',mode='Hotel',currency='NIO',amount=2000,priority=10,active=1)).insert()
        stay=frappe.get_doc('HS Stay',entered['stay'])
        values=dict(stay=stay.name,modified=str(stay.modified),folio=entered['folio'],room=room.name,reason='Cambio sintético')
        values['acceptance']=api.preview(self.prop.name,values,'change_room')['acceptance']
        self.command('change_room',values)
        change=next(r for r in self.rows(stay.name) if r.description=='Cambio de habitación y tarifa')
        self.assertEqual(change.amount,1000)
        self.assertIn('solamente una diferencia',change.pricing['scope'])
        self.assertEqual([r['amount'] for r in change.pricing['entries']],['2000.00','2000.00'])

    def test_discount_courtesy_and_surcharge_label_the_signed_adjustment_and_original_reference(self):
        stay=self.enter()['stay'];source=self.rows(stay)[0]
        for kind,amount in (('Discount',100),('Courtesy',None),('Surcharge',25)):
            self.command('adjustment',dict(charge=source.name,adjustment_type=kind,amount=amount,reason='Ajuste sintético '+kind))
        rows={r.adjustment_type:r for r in self.rows(stay) if r.adjustment_type}
        self.assertEqual({k:r.pricing['recorded_amount'] for k,r in rows.items()},{'Discount':'-100.0','Courtesy':'-1400.0','Surcharge':'25.0'})
        self.assertEqual(rows['Courtesy'].pricing['title'],'Cortesía autorizada')
        for row in rows.values():
            self.assertIn('no otro cobro',row.pricing['scope'])
            self.assertIn('Motivo: Ajuste sintético '+row.adjustment_type,row.pricing['notes'])

    def test_shared_account_preserves_per_stay_explanation_scope(self):
        room2=frappe.get_doc('HS Room',{'property':self.prop.name,'room_number':'H102'})
        values=dict(starts_at=str(self.now),ends_at=str(self.now+timedelta(days=1)),customer=self.guest.customer,guest=self.guest.name,
                    rooms=[dict(category=r.category,room=r.name,people=1) for r in (self.room,room2)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        booking=self.command('reserve',values)['booking'];stays=[]
        for allocation in api.booking_detail(booking)['allocations']:
            current=frappe.get_doc('HS Booking',booking)
            stays.append(self.command('check_in',dict(booking=booking,modified=str(current.modified),allocation=allocation.name,guest=self.guest.name))['stay'])
        folio=self.command('create_folio',dict(stay=stays[0],customer=self.guest.customer,label='Empresa compartida',group=True))['folio']
        for stay in stays:
            charge=self.rows(stay)[0]
            self.command('move_charge',dict(charge=charge.name,folio=folio,reason='Agrupación sintética'))
        for stay in stays:
            rows=self.rows(stay)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0].stay,stay)
            context=hs_account_context(stay)
            self.assertEqual([r.name for r in context['charges']],[rows[0].name])
            shared=next(f for f in context['folios'] if f.name==folio)
            self.assertEqual(shared.balance['pending'],'3000.00')

    def test_compact_print_escapes_descriptions_and_keeps_historical_calculation_on_screen_only(self):
        stay=self.enter()['stay'];row=self.rows(stay)[0]
        snapshot=json.loads(row.quote_snapshot)
        snapshot['nightly'][0]['rules']['title']='<script>histórico</script>'
        with operation():
            doc=frappe.get_doc('HS Charge',row.name);doc.quote_snapshot=canonical(snapshot);doc.description='Concepto <b>visible</b>';doc.save()
        before=self.fingerprints()
        html=frappe.get_print('HS Stay',stay,print_format='HS Cuenta de estancia',as_pdf=False)
        self.assertNotIn('Cálculo histórico del precio',html)
        self.assertNotIn('Importe histórico de referencia',html)
        self.assertNotIn('histórico',html)
        self.assertIn('Concepto &lt;b&gt;visible&lt;/b&gt;',html)
        self.assertIn('<script>histórico</script>',canonical(api.stay_detail(stay)['charges'][0].pricing))
        self.assertNotIn('Facturas y notas de crédito',html)
        self.assertNotIn('Cobros, anticipos y garantías',html)
        self.assertNotIn('<script>histórico</script>',html)
        self.assertEqual(self.fingerprints(),before)
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):
            api.stay_detail(stay)

    def test_compact_print_retains_discount_invoice_tax_payment_and_outstanding_amount(self):
        entered=self.enter();row=self.rows(entered['stay'])[0]
        self.command('adjustment',dict(charge=row.name,adjustment_type='Discount',amount=100,reason='Descuento autorizado'))
        invoice=self.command('invoice',dict(folio=entered['folio']))['invoice']
        shift=self.command('open_shift',dict(opening_amount=0))['shift']
        method=frappe.db.get_value('HS Payment Method',{'property':self.prop.name})
        payment=self.command('payment',dict(stay=entered['stay'],folio=entered['folio'],shift=shift,method=method,kind='Payment',amount=500))
        before=self.fingerprints()
        html=frappe.get_print('HS Stay',entered['stay'],print_format='HS Cuenta de estancia',as_pdf=False)
        from bs4 import BeautifulSoup
        text=BeautifulSoup(html,'html.parser').get_text(' ',strip=True)
        for value in ('Descuento autorizado','Facturas y notas de crédito','Impuestos','Total','Cobros, anticipos y garantías',invoice,payment['payment_entry'],'1,400.00','500.00','900.00'):
            self.assertIn(value,text)
        self.assertNotIn('Cálculo histórico del precio',text)
        self.assertEqual(self.fingerprints(),before)

    def test_legacy_invalid_and_rounding_snapshots_never_invent_current_prices(self):
        for raw in ('', '[]','{invalid',canonical(dict(rules=dict(mode='Hotel'),nightly=['bad'])),canonical(dict(rules=dict(mode='Hotel'),nightly=[dict(date='bad',amount='NaN')]))):
            result=describe_charge(dict(amount=17,currency='NIO',kind='Lodging',quote_snapshot=raw))
            self.assertEqual(result['recorded_amount'],'17')
            self.assertFalse(result['entries']);self.assertTrue(result['notes'])
        snapshot=dict(rules=dict(mode='Hotel'),precision=2,people=3,extra_beds=0,nightly=[dict(date='2026-10-20',amount='1.01',rules=dict(title='Precisión aceptada',amount='1.005',included_people=2,additional_person_rate='0.005'))])
        result=describe_charge(dict(amount='1.01',currency='NIO',kind='Lodging',quote_snapshot=canonical(snapshot)))
        self.assertEqual(result['entries'][0]['amount'],'1.01')
        self.assertIn('Precio base: 1.005 NIO',result['entries'][0]['details'])
        self.assertTrue(any('0.005' in text for text in result['entries'][0]['details']))
        for precision,amount in ((0,'1'),(3,'1.010')):
            snapshot.update(precision=precision)
            snapshot['nightly'][0]['amount']=amount
            projection=describe_charge(dict(amount=amount,currency='NIO',kind='Lodging',quote_snapshot=canonical(snapshot),status='Reversed'))
            self.assertEqual(projection['entries'][0]['amount'],amount)
            self.assertIn('no forma parte del saldo actual',projection['scope'])
            self.assertTrue(any(f'a {precision} decimales' in text for text in projection['notes']))

    def test_timed_modality_changes_labels_without_changing_codes_prices_or_report_contracts(self):
        from hospitality_suite.printing import hs_label
        from hospitality_suite.report_formatting import display,label
        from frappe.translate import get_translations_from_apps
        self.motel();entered=self.enter(hours=4)
        before=self.fingerprints()
        self.assertEqual(self.prop.mode,'Por tiempo')
        detail=api.stay_detail(entered['stay'])
        self.assertEqual(json.loads(detail['stay'].quote_snapshot)['rules']['mode'],'Por tiempo')
        self.assertEqual(detail['stay'].amount,600)
        for row in detail['charges']:
            self.assertEqual(row.pricing['mode_label'],'Por tiempo')
            if row.description=='Horas adicionales de motel':
                self.assertEqual(row.description_label,'Horas adicionales por tiempo')
        self.assertEqual(hs_label('Por tiempo'),'Por tiempo');self.assertEqual(hs_label('Mixed'),'Hotel y por tiempo')
        self.assertEqual(display('mode','Por tiempo'),'Por tiempo');self.assertEqual(label('motel_lodging_net'),'Alojamiento por tiempo neto facturado')
        self.assertIn('Por tiempo',frappe.get_meta('HS Property').get_field('mode').options.split('\n'))
        self.assertNotIn('Motel',frappe.get_meta('HS Property').get_field('mode').options.split('\n'))
        self.assertEqual(get_translations_from_apps('es',['hospitality_suite'])['Por tiempo'],'Por tiempo')
        from hospitality_suite.reports import summary
        metrics=summary(self.prop)
        self.assertEqual(metrics['mode'],'Por tiempo')
        self.assertIn('motel_lodging_net',metrics);self.assertIn('occupied_hours',metrics)
        self.assertIn('Por tiempo:',metrics['definitions'])
        self.assertEqual(self.fingerprints(),before)

    def test_booking_summary_keeps_names_rooms_and_stay_links_after_entry_without_writes(self):
        entered=self.enter(people=2)
        stay=frappe.get_doc('HS Stay',entered['stay'])
        before=self.fingerprints()
        info=api.booking_detail(stay.booking)
        self.assertEqual(info['booking'].status,'Checked In')
        self.assertEqual(info['allocations'],[])
        self.assertEqual(info['summary']['guest_label'],self.guest.full_name)
        self.assertEqual(info['summary']['customer_label'],frappe.db.get_value('Customer',self.guest.customer,'customer_name'))
        self.assertEqual(info['summary']['mode_label'],'Hotel')
        room=info['summary']['rooms'][0]
        self.assertEqual(room['room_label'],'H101');self.assertEqual(room['people'],2)
        self.assertEqual(room['stays'][0]['name'],stay.name)
        self.assertEqual(room['stays'][0]['room_label'],'H101')
        self.assertEqual(self.fingerprints(),before)
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):api.booking_detail(stay.booking)

    def test_booking_summary_preserves_group_rows_unassigned_rooms_and_discreet_names(self):
        self.motel()
        values=dict(starts_at=str(self.now),ends_at=str(self.now+timedelta(hours=3)),customer=self.guest.customer,guest=self.guest.name,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=2),dict(category=self.room.category,people=1)])
        values['acceptance']=api.preview(self.prop.name,values)['acceptance']
        result=self.command('reserve',values)
        before=self.fingerprints();info=api.booking_detail(result['booking'])
        self.assertEqual(info['summary']['guest_label'],'Huésped registrado')
        self.assertEqual(info['summary']['mode_label'],'Por tiempo')
        self.assertEqual(len(info['summary']['rooms']),2)
        self.assertEqual(info['summary']['rooms'][1]['room_label'],'Por asignar')
        self.assertEqual([r['people'] for r in info['summary']['rooms']],[2,1])
        self.assertEqual(self.fingerprints(),before)
