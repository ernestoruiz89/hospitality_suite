"""Native names, compatibility and unchanged operational/financial references."""
from datetime import timedelta
import re
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.document_naming import DOCUMENT_SERIES
from hospitality_suite.schema import SCHEMA


class TestDocumentNaming(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user('Administrator')

    def test_metadata_has_unique_native_series_without_changing_technical_names_or_rename_permissions(self):
        self.assertEqual(len(DOCUMENT_SERIES),len(set(DOCUMENT_SERIES.values())))
        for dt, spec in SCHEMA.items():
            meta=frappe.get_meta(dt)
            self.assertFalse(meta.allow_rename)
            self.assertEqual(meta.autoname,DOCUMENT_SERIES.get(dt,'hash'))
            self.assertFalse(spec.get('child') and dt in DOCUMENT_SERIES)
        # Exercise Frappe's actual counter parser, not a replacement formatter.
        from frappe.model.naming import make_autoname
        for dt, series in DOCUMENT_SERIES.items():
            first=make_autoname(series,doc=frappe.new_doc(dt))
            second=make_autoname(series,doc=frappe.new_doc(dt))
            self.assertNotEqual(first,second)
            self.assertEqual(int(second.rsplit('-',1)[-1]),int(first.rsplit('-',1)[-1])+1)
            pattern=re.escape(series).replace(re.escape('.YYYY.'),r'\d{4}').replace(re.escape('.#####'),r'\d{5,}')
            self.assertRegex(first,'^'+pattern+'$')

    def test_new_booking_stay_account_and_charges_use_series_and_preserve_legacy_master_links_on_retry(self):
        prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        room=frappe.get_doc('HS Room',{'property':prop.name,'room_number':'H101'})
        guest=frappe.get_doc('HS Guest',{'property':prop.name})
        original={dt:frappe.db.sql('SELECT name FROM `tab'+dt+'` ORDER BY name')
                  for dt in ('HS Property','HS Room','HS Category','HS Guest','HS Rate')}
        start=now_datetime().replace(microsecond=0)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),customer=guest.customer,guest=guest.name,
                    rooms=[dict(category=room.category,room=room.name,people=1)])
        values['acceptance']=api.preview(prop.name,values)['acceptance']
        key=uuid.uuid4().hex
        result=api.execute(prop.name,'walk_in',key,values)
        self.assertEqual(api.execute(prop.name,'walk_in',key,values),result)
        stay=frappe.get_doc('HS Stay',result['stay'])
        self.assertRegex(stay.name,r'^EST-\d{4}-\d{5,}$')
        self.assertRegex(stay.booking,r'^RES-\d{4}-\d{5,}$')
        detail=api.stay_detail(stay.name)
        self.assertTrue(detail['folios']);self.assertTrue(detail['charges'])
        for row in detail['folios']:self.assertRegex(row.name,r'^CTA-\d{4}-\d{5,}$')
        for row in detail['charges']:
            self.assertRegex(row.name,r'^CAR-\d{4}-\d{5,}$')
            self.assertEqual(row.stay,stay.name)
        self.assertEqual(stay.room,room.name);self.assertEqual(stay.guest,guest.name)
        self.assertEqual(api.booking_detail(stay.booking)['summary']['rooms'][0]['room_label'],'H101')
        self.assertEqual(original,{dt:frappe.db.sql('SELECT name FROM `tab'+dt+'` ORDER BY name') for dt in original})
