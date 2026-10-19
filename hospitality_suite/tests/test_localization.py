"""Native language changes affect presentation, never master names or commands."""
from datetime import timedelta
import json
from pathlib import Path
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from hospitality_suite import api
from hospitality_suite.report_formatting import xlsx_data
from hospitality_suite.service import operation


class TestLocalization(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.previous_lang=frappe.local.lang
        self.addCleanup(self.clean_language)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.room=frappe.get_all("HS Room",filters={"property":self.prop.name},fields=["name","category"],order_by="room_number")[0]
        self.guest=frappe.get_doc("HS Guest",{"property":self.prop.name})

    def clean_language(self):
        from frappe.core.doctype.translation.translation import clear_user_translation_cache
        frappe.set_user("Administrator")
        frappe.db.rollback()
        clear_user_translation_cache("fr")
        frappe.local.lang=self.previous_lang

    def translate(self,source,target):
        existing=frappe.db.get_value("Translation",dict(language="fr",source_text=source),"name")
        doc=frappe.get_doc("Translation",existing) if existing else frappe.new_doc("Translation")
        doc.update(dict(language="fr",source_text=source,translated_text=target))
        doc.save(ignore_permissions=True)

    def call(self,action,data):
        return api.execute(self.prop.name,action,uuid.uuid4().hex,data)

    def values(self,days=1):
        start=now_datetime().replace(microsecond=0)
        return dict(starts_at=str(start),ends_at=str(start+timedelta(days=days)),guest=self.guest.name,customer=self.guest.customer,
                    rooms=[dict(category=self.room.category,room=self.room.name,people=1)])

    def test_native_dictionary_translates_reports_and_print_but_preserves_names_and_types(self):
        for source,target in {"Estado":"État","Importe":"Montant","Cantidad":"=1+1","Confirmada":"Confirmée",
                              "CONFIRMACIÓN DE RESERVA":"CONFIRMATION DE RÉSERVATION","Cliente pagador":"Client payeur"}.items():
            self.translate(source,target)
        # A real master name that happens to equal a translation key is still data.
        frappe.db.set_value("Item","HS-DEMO-LODGING","item_name","Estado")
        frappe.db.set_value("HS Guest",self.guest.name,"full_name","Estado")
        frappe.local.lang="fr"
        values=self.values()
        values["acceptance"]=api.preview(self.prop.name,values)["acceptance"]
        entered=self.call("walk_in",values)
        boot=api.bootstrap(self.prop.name)
        self.assertEqual(boot["report_labels"]["status"],"État")
        self.assertEqual(boot["report_labels"]["amount"],"Montant")
        self.assertEqual(next(g.full_name for g in boot["guests"] if g.name==self.guest.name),"Estado")
        row=next(r for r in api.report(self.prop.name,"Producción") if r.stay==entered["stay"])
        self.assertEqual(row.item,"HS-DEMO-LODGING")
        shown=next(r for r in api.report_page(self.prop.name,"Producción")["rows"] if r.name==row.name)
        self.assertEqual(shown._display["item"],"Estado")
        self.assertEqual(row.currency,"NIO")
        rows,_,_=xlsx_data([dict(item="HS-DEMO-LODGING",quantity=2,amount=1500,currency="NIO",_display={"item":"Estado"})],["item","quantity","amount"])
        self.assertEqual(rows[0][1],"'=1+1")
        self.assertEqual(rows[0][2],"Montant")
        self.assertEqual(rows[1],["Estado",2.0,1500.0])
        # Render the source through Frappe's actual Jinja environment and hooks.
        source=Path(frappe.get_app_path("hospitality_suite","templates","print","reservation.html")).read_text()
        doc=frappe._dict(name="booking-opaque-key",property=self.prop.name,status="Confirmed",customer="Estado",starts_at=values["starts_at"],
                         ends_at=values["ends_at"],channel="Estado",rooms=[],currency="NIO",instructions="",get_formatted=lambda key:"1 500")
        rendered=frappe.render_template(source,dict(doc=doc))
        self.assertIn("CONFIRMATION DE RÉSERVATION",rendered)
        self.assertIn("Client payeur",rendered)
        self.assertIn("Confirmée",rendered)
        self.assertIn("booking-opaque-key",rendered)
        self.assertIn(">Estado<",rendered)
        self.translate("baño","salle de bain")
        self.translate("Revisado","Vérifié")
        source=Path(frappe.get_app_path("hospitality_suite","templates","print","cleaning.html")).read_text()
        task=frappe._dict(name="cleaning-opaque-key",property=self.prop.name,room=self.room.name,kind="Departure",priority="Normal",status="Completed",
                          assigned_to="Estado",started_at=None,completed_at=None,inspected_by="",notes="",checklist=json.dumps({"baño":True}))
        rendered=frappe.render_template(source,dict(doc=task))
        self.assertEqual(rendered.count(">Vérifié<"),1)
        self.assertIn(">Estado<",rendered)

    def test_extension_entitlements_are_independent_of_translated_explanation(self):
        self.translate("Incluido: {0} × {1}","Compris : {0} × {1}")
        self.translate("Incluido en extensión: {0} × {1}","Compris dans la prolongation : {0} × {1}")
        rate=frappe.get_doc("HS Rate",{"property":self.prop.name,"category":self.room.category})
        with operation():
            rate.priority=1000
            rate.valid_from=None
            rate.valid_to=None
            rate.weekdays=None
            rate.amount=1500
            rate.set("included_services",[dict(item="HS-DEMO-WATER",quantity=1,basis="Night"),dict(item="HS-DEMO-WATER",quantity=1,basis="Stay")])
            rate.save()
        frappe.local.lang="fr"
        values=self.values(2)
        quote=api.preview(self.prop.name,values)
        self.assertTrue(any("Compris :" in line for line in quote["lines"][0]["explanation"]))
        values["acceptance"]=quote["acceptance"]
        entered=self.call("walk_in",values)
        stay=frappe.get_doc("HS Stay",entered["stay"])
        self.assertEqual(json.loads(stay.service_entitlements),[dict(item="HS-DEMO-WATER",quantity="3.0")])
        extension=dict(stay=stay.name,folio=entered["folio"],modified=str(stay.modified),ends_at=str(stay.ends_at+timedelta(days=1)))
        quote=api.preview(self.prop.name,extension,"extend")
        self.assertEqual(quote["included_services"],[dict(item="HS-DEMO-WATER",quantity="1.0")])
        self.assertTrue(any("Compris dans la prolongation :" in line for line in quote["explanation"]))
        self.call("extend",dict(**extension,acceptance=quote["acceptance"]))
        stay.reload()
        self.assertEqual(json.loads(stay.service_entitlements),[dict(item="HS-DEMO-WATER",quantity="4.0")])
