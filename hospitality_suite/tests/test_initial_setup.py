"""Setup uses local operational dates and one result per administrative request."""
from datetime import date,timedelta
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate,now_datetime

from hospitality_suite import api
from hospitality_suite.setup import initial_business_date


class TestInitialSetup(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.company=frappe.db.get_value("HS Property",{"property_name":"Hotel Jardín Demo"},"company")
        self.values=dict(property_name="Alta ficticia "+uuid.uuid4().hex[:8],company=self.company,mode="Mixed",currency="USD",time_zone="Pacific/Kiritimati",close_time="06:00:00")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_initial_date_cutoff_retry_and_no_implicit_financial_masters(self):
        before={dt:frappe.db.count(dt) for dt in ("Account","Sales Taxes and Charges Template","GL Entry","Stock Ledger Entry")}
        values=dict(self.values,business_date="2026-01-15")
        key=uuid.uuid4().hex
        first=api.create_property(values,key)
        self.assertTrue(api.bootstrap()["can_create_property"])
        self.assertEqual(first,api.create_property(values,key))
        self.assertEqual(frappe.db.count("HS Property",{"property_name":values["property_name"]}),1)
        self.assertEqual(frappe.db.count("HS Request",{"property":first["property"],"operation":"create_property"}),1)
        prop=frappe.get_doc("HS Property",first["property"])
        self.assertEqual(getdate(prop.business_date),date(2026,1,15))
        self.assertEqual(prop.mode,"Mixed")
        self.assertEqual(prop.currency,"USD")
        self.assertEqual(prop.time_zone,"Pacific/Kiritimati")
        self.assertFalse(prop.financial_enabled)
        self.assertFalse(prop.receivable_account)
        self.assertEqual(before,{dt:frappe.db.count(dt) for dt in before})
        event=frappe.get_doc("HS Audit Event",{"property":prop.name,"action":"Create property"})
        self.assertEqual(event.actor,"Administrator")
        self.assertEqual(frappe.parse_json(event.details)["business_date"],"2026-01-15")
        with self.assertRaises(frappe.ValidationError):
            api.create_property(dict(values,business_date="2026-01-16"),key)
        # Same-date round-trips from JSON remain writable. A direct date edit
        # must use the existing close/reopen workflow instead.
        prop.business_date=str(prop.business_date)
        prop.brand_name="Marca ficticia"
        prop.save()
        prop.business_date=getdate(prop.business_date)+timedelta(days=1)
        with self.assertRaises(frappe.ValidationError):
            prop.save()

    def test_default_date_uses_selected_zone_cutoff_and_year_boundary(self):
        # Site time is converted to the chosen zone before deriving the date.
        from hospitality_suite.time import to_site
        target=frappe._dict(time_zone="Pacific/Kiritimati")
        before=to_site("2027-01-01 05:59:59",target)
        at_cutoff=to_site("2027-01-01 06:00:00",target)
        self.assertEqual(initial_business_date(target.time_zone,"06:00:00",before),date(2026,12,31))
        self.assertEqual(initial_business_date(target.time_zone,"06:00:00",at_cutoff),date(2027,1,1))
        self.assertEqual(initial_business_date(target.time_zone,"00:00:00",before),date(2027,1,1))
        key=uuid.uuid4().hex
        with patch("hospitality_suite.setup.now_datetime",return_value=before):
            first=api.create_property(self.values,key)
        with patch("hospitality_suite.setup.now_datetime",return_value=at_cutoff):
            self.assertEqual(first,api.create_property(self.values,key))
        self.assertEqual(getdate(frappe.db.get_value("HS Property",first["property"],"business_date")),date(2026,12,31))

    def test_invalid_configuration_and_operational_roles_cannot_create(self):
        count=frappe.db.count("HS Property")
        for extra in (dict(business_date="2026-02-30"),dict(business_date="15/01/2026"),dict(time_zone="Invalid/Zone"),
                      dict(close_time="25:00:00"),dict(financial_enabled=1)):
            with self.assertRaises(frappe.ValidationError):
                api.create_property(dict(self.values,**extra),uuid.uuid4().hex)
        for key in ("",[],"x"*141):
            with self.assertRaises(frappe.ValidationError):
                api.create_property(self.values,key)
        self.assertEqual(frappe.db.count("HS Property"),count)
        frappe.set_user("manager@hospitality.example.invalid")
        self.assertFalse(api.bootstrap()["can_create_property"])
        with self.assertRaises(frappe.PermissionError):
            api.create_property(self.values,uuid.uuid4().hex)

    def test_mixed_property_quotes_both_modes_and_shares_room_capacity(self):
        prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        api.save_setup(prop.name,"property",dict(mode="Mixed"),uuid.uuid4().hex,str(prop.modified))
        prop.reload()
        room=frappe.get_all("HS Room",filters={"property":prop.name},fields=["name","category"],order_by="room_number")[0]
        guest=frappe.get_doc("HS Guest",{"property":prop.name})
        api.save_setup(prop.name,"rate",dict(title="Bloque mixto ficticio",category=room.category,mode="Por tiempo",currency=prop.currency,
                       amount=450,block_hours=3,rounding_minutes=60,grace_minutes=10,extra_hour_rate=150,included_people=2,priority=100),uuid.uuid4().hex)
        start=now_datetime()+timedelta(days=30)
        values=dict(starts_at=str(start),ends_at=str(start+timedelta(hours=3)),customer=guest.customer,guest=guest.name,
                    rooms=[dict(category=room.category,room=room.name,people=1)])
        hotel=api.preview(prop.name,dict(values,mode="Hotel"))
        motel=api.preview(prop.name,dict(values,mode="Por tiempo"))
        self.assertEqual(hotel["amount"],"1500.00")
        self.assertEqual(hotel["lines"][0]["rules"]["mode"],"Hotel")
        self.assertEqual(motel["amount"],"450.00")
        self.assertEqual(motel["lines"][0]["rules"]["mode"],"Por tiempo")
        booked=api.execute(prop.name,"reserve",uuid.uuid4().hex,dict(values,mode="Por tiempo",acceptance=motel["acceptance"]))
        snapshot=frappe.parse_json(frappe.db.get_value("HS Booking",booked["booking"],"quote_snapshot"))
        self.assertEqual(snapshot["lines"][0]["rules"]["mode"],"Por tiempo")
        with self.assertRaises(frappe.ValidationError):
            api.preview(prop.name,dict(values,mode="Hotel"))
