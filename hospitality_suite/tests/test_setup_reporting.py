from datetime import timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api,reports,reconciliation
from hospitality_suite.schema import ROLES
from hospitality_suite.service import operation


class TestSetupReporting(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["*"],order_by="room_number")[0]
        self.guest=frappe.get_all("HS Guest",filters={"property":self.prop.name},fields=["*"])[0]

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def call(self,action,data,key=None):
        return api.execute(self.prop.name,action,key or uuid.uuid4().hex,data)

    def test_penalty_settings_reject_invalid_values_without_request_or_property_changes(self):
        frappe.set_user('manager@hospitality.example.invalid')
        for prefix in ('cancellation','no_show'):
            for mode,value in [('Percent',125),('Percent',-1),('Fixed',-1)]:
                with self.subTest(prefix=prefix,mode=mode,value=value):
                    self.prop.reload()
                    before=(str(self.prop.modified),self.prop.get(prefix+'_fee_mode'),self.prop.get(prefix+'_fee_value'))
                    count=frappe.db.count('HS Request')
                    with self.assertRaises(frappe.ValidationError):
                        api.save_setup(self.prop.name,'property',{prefix+'_fee_mode':mode,prefix+'_fee_value':value},
                            uuid.uuid4().hex,str(self.prop.modified))
                    self.prop.reload()
                    self.assertEqual((str(self.prop.modified),self.prop.get(prefix+'_fee_mode'),self.prop.get(prefix+'_fee_value')),before)
                    self.assertEqual(frappe.db.count('HS Request'),count)

    def test_penalty_settings_accept_percent_endpoints_fractional_rates_and_fixed_amounts(self):
        frappe.set_user('manager@hospitality.example.invalid')
        for prefix in ('cancellation','no_show'):
            for mode,value in [('Percent',0),('Percent',25.5),('Percent',100),('Fixed',125),('Fixed',0)]:
                with self.subTest(prefix=prefix,mode=mode,value=value):
                    self.prop.reload()
                    api.save_setup(self.prop.name,'property',{prefix+'_fee_mode':mode,prefix+'_fee_value':value},
                        uuid.uuid4().hex,str(self.prop.modified))
                    self.prop.reload()
                    self.assertEqual(self.prop.get(prefix+'_fee_mode'),mode)
                    self.assertEqual(self.prop.get(prefix+'_fee_value'),value)

    def values(self,beds=0):
        start=now_datetime().replace(microsecond=0)
        return dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=2,extra_beds=beds)])

    def test_extra_bed_and_historic_rate(self):
        with operation():
            cat=frappe.get_doc("HS Category",self.room.category)
            cat.max_extra_beds=1
            cat.save()
            rate=frappe.get_doc("HS Rate",{"property":self.prop.name,"category":cat.name})
            rate.extra_bed_rate=200
            rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        values=self.values(1)
        quote=api.preview(self.prop.name,values)
        self.assertEqual(quote["amount"],"1700.00")
        values["acceptance"]=quote["acceptance"]
        booking=self.call("reserve",values)
        with operation():
            rate.extra_bed_rate=400
            rate.change_reason='Preparación de tarifa sintética para la prueba';rate.save()
        book=frappe.get_doc("HS Booking",booking["booking"])
        self.assertEqual(book.rooms[0].extra_beds,1)
        entered=self.call("check_in",dict(booking=book.name,modified=str(book.modified),guest=self.guest.name,room=self.room.name))
        self.assertEqual(frappe.db.get_value("HS Stay",entered["stay"],"amount"),1700)

    def test_guest_uses_standard_contact_address_and_is_idempotent(self):
        key=uuid.uuid4().hex
        values=dict(full_name="Persona ficticia contacto "+key[:6],email="fictional-"+key[:6]+"@example.invalid",phone="00000000",
                    address_line1="Dirección ficticia",city="Ciudad de prueba",country="Nicaragua")
        one=api.create_guest(self.prop.name,values,key)
        self.assertEqual(one,api.create_guest(self.prop.name,values,key))
        guest=frappe.get_doc("HS Guest",one["guest"])
        self.assertEqual(frappe.db.get_value("Contact",guest.contact,"email_id"),values["email"])
        self.assertEqual(frappe.db.get_value("Address",guest.address,"city"),values["city"])
        self.assertTrue(frappe.db.exists("Dynamic Link",{"parent":guest.contact,"link_doctype":"Customer","link_name":one["customer"]}))

    def test_user_wizard_restricted_and_series_validated(self):
        email="wizard-"+uuid.uuid4().hex[:8]+"@example.invalid"
        values=dict(email=email,first_name="Usuario ficticio",roles=["HS Housekeeping"],reason="Prueba de configuración")
        result=self.call("assign_user",values)
        self.assertEqual(result["user"],email)
        self.assertTrue(frappe.db.exists("HS Access",{"user":email,"property":self.prop.name}))
        frappe.set_user("manager@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            self.call("assign_user",{**values,"roles":["HS Administrator"]})
        frappe.set_user("Administrator")
        settings = api.setup_options(self.prop.name)
        self.assertNotIn("Standard", settings["formats"]["Sales Invoice"])
        self.assertNotIn("Standard", settings["formats"]["HS Payment"])
        with self.assertRaises(frappe.ValidationError):
            api.save_setup(self.prop.name,"property",dict(invoice_series="NO-EXISTE-.YYYY.-"),uuid.uuid4().hex,str(self.prop.modified))

    def test_user_grant_serializes_across_properties(self):
        user = "cashier@hospitality.example.invalid"
        other = frappe.db.get_value("HS Property", {"name": ["!=", self.prop.name]}, "name")
        self.assertTrue(other)
        roles = [role for role in ROLES if role in frappe.get_roles(user)]
        self.assertTrue(roles)
        site, sites_path = frappe.local.site, frappe.local.sites_path
        acquired, attempting, release, completed = (
            threading.Event() for _ in range(4))

        def lock_identity():
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                frappe.db.sql("SELECT name FROM `tabUser` WHERE name=%s FOR UPDATE", (user,))
                acquired.set()
                if not release.wait(10):
                    raise AssertionError("No se liberó la identidad de prueba")
                frappe.db.rollback()
            finally:
                frappe.destroy()

        def grant_other_hotel():
            frappe.init(site=site, sites_path=sites_path)
            frappe.connect()
            frappe.set_user("Administrator")
            try:
                if not acquired.wait(10):
                    raise AssertionError("No se tomó el bloqueo inicial")
                attempting.set()
                api.execute(other, "assign_user", uuid.uuid4().hex,
                    dict(email=user, roles=roles, reason="Prueba de acceso concurrente"))
                completed.set()
                frappe.db.rollback()
            finally:
                frappe.destroy()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(lock_identity)
            second = pool.submit(grant_other_hotel)
            try:
                self.assertTrue(acquired.wait(10))
                self.assertTrue(attempting.wait(10))
                self.assertFalse(completed.wait(0.2))
            finally:
                release.set()
            first.result(timeout=15)
            second.result(timeout=15)
        self.assertTrue(completed.is_set())

    def test_erp_credit_react_contract_separates_lookup_creation_and_terms(self):
        suffix = uuid.uuid4().hex[:8]
        customer = frappe.get_doc(dict(doctype="Customer",
            customer_name="React Credit " + suffix,
            customer_type="Company",
            customer_group=frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            territory=frappe.db.get_value("Territory", {"is_group": 0}, "name"))).insert()
        frappe.set_user("manager@hospitality.example.invalid")
        search = api.erp_credit_customer_search(self.prop.name, suffix)
        self.assertIn(customer.name, [row.name for row in search["rows"]])
        values = dict(customer=customer.name, kind="Company", credit_authorized=1,
            credit_limit=500, credit_days=20, valid_until=None,
            reason="Autorización de prueba React")
        key = uuid.uuid4().hex
        created = api.save_setup(self.prop.name, "billing_party", values, key)
        self.assertEqual(created, api.save_setup(self.prop.name, "billing_party", values, key))
        detail = api.credit_status(self.prop.name, customer.name)
        self.assertEqual((detail["party"], detail["kind"],
            detail["credit_days"]), (created["name"], "Company", 20))
        self.assertEqual(Decimal(str(detail["limit"])), Decimal(500))
        changed = self.call("billing_party", dict(party=created["name"],
            modified=detail["modified"], credit_limit=600,
            reason="Actualización de prueba React"))
        self.assertEqual(changed["party"], created["name"])
        self.assertEqual(Decimal(str(api.credit_status(self.prop.name,
            customer.name)["limit"])), Decimal(600))
        self.assertTrue(any(row["party"] == created["name"] for row in
            api.credit_overview(self.prop.name)["rows"]))
        other = frappe.get_all("HS Property", filters={"name": ["!=", self.prop.name]},
            pluck="name", limit=1)
        if other:
            with self.assertRaises(frappe.PermissionError):
                api.credit_status(other[0], customer.name)
        frappe.set_user("cashier@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            api.erp_credit_customer_search(self.prop.name, suffix)

    def test_tax_inclusive_net_kpi_and_document_reconciliation(self):
        company=frappe.get_doc("Company",self.prop.company)
        parent=frappe.db.get_value("Account",{"company":company.name,"root_type":"Liability","is_group":1})
        account=frappe.get_doc(dict(doctype="Account",company=company.name,account_name="Impuesto ficticio "+uuid.uuid4().hex[:6],
                                  parent_account=parent,account_type="Tax",account_currency="NIO")).insert()
        template=frappe.get_doc(dict(doctype="Sales Taxes and Charges Template",title="Impuesto ficticio incluido "+uuid.uuid4().hex[:6],company=company.name,
                                     taxes=[dict(charge_type="On Net Total",account_head=account.name,description="Impuesto sintético 15%",rate=15,included_in_print_rate=1,cost_center=self.prop.cost_center)])).insert()
        with operation():
            self.prop.tax_template=template.name
            self.prop.save()
        values=self.values()
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        stay=self.call("walk_in",values)
        invoice=self.call("invoice",dict(folio=stay["folio"]))
        inv=frappe.get_doc("Sales Invoice",invoice["invoice"])
        self.assertEqual(inv.grand_total,1500)
        self.assertAlmostEqual(inv.net_total,1304.35,places=2)
        day=str(now_datetime().date())
        summary=reports.summary(self.prop,day+" 00:00:00",str(now_datetime().date()+timedelta(days=1))+" 00:00:00")
        self.assertEqual(summary["hotel_lodging_net"],"1304.35")
        self.assertEqual(summary["ADR"],"1304.35")
        self.assertEqual(summary["RevPAR"],"130.44")
        self.assertEqual(summary["occupancy_percent"],10)
        self.assertFalse(reconciliation.differences(self.prop))
        # A damaged operational link must be surfaced, rather than hidden in a total.
        with operation():
            charge=frappe.get_doc("HS Charge",{"stay":stay["stay"],"kind":"Lodging"})
            charge.invoice_item="missing-line"
            charge.save()
        differences=reconciliation.differences(self.prop)
        self.assertEqual(differences[0]["source"],charge.name)
        self.assertEqual(differences[0]["difference"],"-1500.00")
        before=str(self.prop.business_date)
        with self.assertRaises(frappe.ValidationError):
            self.call("daily_close",dict(confirm=True))
        self.assertEqual(str(frappe.db.get_value("HS Property",self.prop.name,"business_date")),before)

    def test_export_numeric_types_and_auditor_permission(self):
        import io
        import zipfile
        from xml.etree import ElementTree as ET
        values=self.values()
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        stay=self.call("walk_in",values)
        self.call("invoice",dict(folio=stay["folio"]))
        frappe.local.response=frappe._dict()
        api.export_report(self.prop.name,"Conciliación",{},"xlsx")
        with zipfile.ZipFile(io.BytesIO(frappe.local.response.filecontent)) as archive:
            xml=ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        ns={"x":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        expected=xml.find(".//x:c[@r='D2']",ns)
        self.assertNotIn(expected.get("t"),("s","inlineStr"))
        self.assertEqual(float(expected.find("x:v",ns).text),1500)
        self.assertFalse(xml.findall(".//x:f",ns))
        frappe.set_user("auditor@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            api.export_report(self.prop.name,"Conciliación",{},"xlsx")
