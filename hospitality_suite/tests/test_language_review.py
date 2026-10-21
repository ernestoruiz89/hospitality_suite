"""Literal master data, scoped metadata translations and translatable UI surfaces."""
import uuid

import frappe
from frappe.tests import IntegrationTestCase

from hospitality_suite import api
from hospitality_suite.schema import SCHEMA
from hospitality_suite.schema_labels import FIELD_LABELS
from hospitality_suite.service import canonical,operation


class TestLanguageReview(IntegrationTestCase):
    def setUp(self):
        super().setUp();frappe.set_user('Administrator');self.previous_lang=frappe.local.lang
        self.prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})

    def tearDown(self):
        from frappe.core.doctype.translation.translation import clear_user_translation_cache
        frappe.db.rollback();clear_user_translation_cache('fr');frappe.local.lang=self.previous_lang;frappe.set_user('Administrator');super().tearDown()

    def translate(self,source,target,context=None):
        from frappe.core.doctype.translation.translation import clear_user_translation_cache
        frappe.get_doc(dict(doctype='Translation',language='fr',source_text=source,translated_text=target,context=context)).insert()
        clear_user_translation_cache('fr')

    def test_catalogue_uses_alias_without_changing_original_item_or_code_and_searches_visible_name(self):
        before=canonical(frappe.db.sql('SELECT * FROM tabItem ORDER BY name',as_dict=True))
        result=api.catalog_search(self.prop.name,'por tiempo','sale')
        row=next(row for row in result['items'] if row.name=='HS-DEMO-EXTRA-HOUR')
        self.assertEqual(row.item_name,'Hora adicional de motel');self.assertEqual(row.display_name,'Hora adicional por tiempo')
        boot=api.bootstrap(self.prop.name);self.assertEqual(next(r.display_name for r in boot['items'] if r.name==row.name),row.display_name)
        with operation():self.prop.extra_hour_item=row.name;self.prop.save()
        config=api.service_configuration(self.prop.name,row.name)
        self.assertEqual(config['service']['item_name'],row.item_name)
        self.assertEqual(config['service']['display_name'],row.display_name)
        self.assertEqual(next(r['display_name'] for r in config['mappings'] if r['field']=='extra_hour_item'),row.display_name)
        self.assertEqual(canonical(frappe.db.sql('SELECT * FROM tabItem ORDER BY name',as_dict=True)),before)
        self.assertNotIn(row.name,{r.name for r in api.catalog_search(self.prop.name,'por tiempo','stock')['items']})

    def test_alias_is_limited_to_original_fixture_and_other_master_names_remain_literal(self):
        code='LANG-'+uuid.uuid4().hex[:8]
        frappe.get_doc(dict(doctype='Item',item_code=code,item_name='Hora adicional de motel',item_group='Services',stock_uom='Nos',is_stock_item=0,is_sales_item=1)).insert()
        self.translate('Hora adicional por tiempo','Heure supplémentaire');self.translate('Hora adicional de motel','NEVER TRANSLATE DATA')
        frappe.local.lang='fr';rows=api.catalog_search(self.prop.name,'motel','sale')['items']
        self.assertEqual(next(r.display_name for r in rows if r.name==code),'Hora adicional de motel')
        self.assertEqual(next(r.display_name for r in rows if r.name=='HS-DEMO-EXTRA-HOUR'),'Heure supplémentaire')
        frappe.db.set_value('Item','HS-DEMO-EXTRA-HOUR','item_name','Nombre elegido por el usuario')
        row=next(r for r in api.catalog_search(self.prop.name,'HS-DEMO-EXTRA-HOUR','sale')['items'])
        self.assertEqual(row.display_name,'Nombre elegido por el usuario')

    def test_generated_metadata_has_complete_labels_and_wire_options_unchanged(self):
        names={df['fieldname'] for spec in SCHEMA.values() for df in spec['fields']}
        self.assertFalse(names-set(FIELD_LABELS))
        for dt,spec in SCHEMA.items():
            meta=frappe.get_meta(dt)
            for df in spec['fields']:
                field=meta.get_field(df['fieldname']);self.assertEqual(field.label,df['label'],(dt,df['fieldname']))
                if df['fieldtype']=='Select':self.assertEqual(field.options,df['options'])
        self.assertEqual(frappe.get_meta('HS Room').get_field('room_number').label,'Número de habitación')

    def test_native_contexts_localize_stay_and_allocation_without_changing_unrelated_erp_context(self):
        frappe.local.lang='es'
        self.assertEqual(frappe._('Active',context='HS Stay'),'Alojado')
        self.assertEqual(frappe._('Active',context='HS Allocation'),'Activa')
        self.assertEqual(frappe._('Cleaning',context='HS Room'),'En limpieza')
        self.assertEqual(frappe._('Cleaning',context='Stock Entry'),'Consumo de limpieza')
        self.assertEqual(frappe._('Laundry',context='Stock Entry'),'Lavandería')
        self.assertNotEqual(frappe._('Active',context='Account'),'Alojado')
        self.translate('Active','Hébergé',context='HS Stay');frappe.local.lang='fr'
        self.assertEqual(frappe._('Active',context='HS Stay'),'Hébergé')
        self.assertEqual(frappe.get_meta('HS Stay').get_field('status').options,'Active\nChecked Out')

    def test_native_accounting_links_have_spanish_labels_and_keep_the_same_targets_and_privacy(self):
        expected={'hs_property':('HS Property','Establecimiento de alojamiento'),'hs_stay':('HS Stay','Estancia de alojamiento'),
                  'hs_shift':('HS Shift','Turno de caja'),'hs_folio':('HS Folio','Cuenta de estancia'),'hs_booking':('HS Booking','Reserva de alojamiento')}
        for dt in ('Sales Invoice','Payment Entry','Journal Entry','Stock Entry','Purchase Invoice'):
            for key,(target,label) in expected.items():
                field=frappe.get_meta(dt).get_field(key);self.assertEqual(field.label,label);self.assertEqual(field.options,target);self.assertTrue(field.no_copy and field.print_hide)

    def test_native_extractor_finds_secondary_dialog_labels_and_website_titles(self):
        from frappe.translate import get_server_messages
        messages={row[1] for row in get_server_messages('hospitality_suite')}
        required={'Baño revisado','Cama y ropa revisadas','Superficies y equipo revisados','Administrador de Hospitality','Devolver {0}',
                  'Extracto bancario','Factura','Vuelto','Hora adicional por tiempo','Confirmación de alojamiento','Solicitar una reserva','Reapertura autorizada por'}
        self.assertFalse(required-messages,required-messages)
        self.translate('Confirmación de alojamiento','Confirmation de séjour');self.translate('Solicitar una reserva','Demander une réservation');frappe.local.lang='fr'
        from hospitality_suite.www import hospitality,hospitality_confirmation
        context=frappe._dict();hospitality.get_context(context);self.assertEqual(context.title,'Demander une réservation')
        # The title is evaluated independently of guest token validation.
        from unittest.mock import patch
        with patch.object(hospitality_confirmation,'confirmation',return_value={}):hospitality_confirmation.get_context(context)
        self.assertEqual(context.title,'Confirmation de séjour')
