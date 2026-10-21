"""Two genuinely independent DB sessions contend for a previously empty interval.

Run explicitly with bench execute; committed synthetic bookings are cancelled after
verification. This is deliberately outside rollback-only unit test transactions.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid

import frappe
from frappe.utils import now_datetime
from hospitality_suite import api


def verify_category():
    return verify("category")


def verify(case="room"):
    if (frappe.local.site not in ("hospitality-acceptance.localhost", "hospitality-release.localhost")
            or not frappe.conf.allow_tests or not frappe.conf.get("hospitality_integration_test_site")
            or not frappe.conf.get("pause_scheduler")):
        frappe.throw("Esta prueba con commits requiere un sitio de integración aislado y designado, con scheduler pausado")
    if any(frappe.db.count(dt) for dt in ("HS Stay", "HS Charge", "HS Payment", "HS Shift", "HS Daily Close")):
        frappe.throw("La prueba de concurrencia requiere un sitio sin operaciones")
    if any(row.channel != "Prueba de concurrencia" for row in frappe.get_all("HS Booking", fields=["channel"])):
        frappe.throw("El sitio contiene reservas ajenas al ensayo de concurrencia")
    site, sites = frappe.local.site, frappe.local.sites_path
    prop = frappe.get_doc("HS Property", {"property_name":"Hotel Jardín Demo"})
    for name in frappe.get_all("HS Booking", filters={"property": prop.name,"channel":"Prueba de concurrencia","status":"Confirmed"}, pluck="name"):
        old = frappe.get_doc("HS Booking",name)
        api.execute(prop.name,"booking_status",uuid.uuid4().hex,dict(booking=name,modified=str(old.modified),status="Cancelled",reason="Limpieza de una ejecución previa de prueba"))
    frappe.db.commit()
    room = frappe.get_all("HS Room", filters={"property":prop.name}, fields=["name","category"], order_by="room_number desc")[0]
    guest = frappe.get_all("HS Guest", filters={"property":prop.name}, fields=["name","customer"])[0]
    start = now_datetime().replace(microsecond=0)+timedelta(days=370)
    values = dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),customer=guest.customer,guest=guest.name,
                  rooms=[dict(category=room.category,room=room.name,people=1)],channel="Prueba de concurrencia")
    if case == "category":
        count = frappe.db.count("HS Room", {"property":prop.name,"category":room.category,"active":1})
        filler = {**values,"rooms":[dict(category=room.category,people=1) for _ in range(count-1)]}
        filler["acceptance"] = api.preview(prop.name,filler)["acceptance"]
        api.execute(prop.name,"reserve",uuid.uuid4().hex,filler)
        frappe.db.commit()
        values["rooms"] = [dict(category=room.category,people=1)]
    values["acceptance"] = api.preview(prop.name,values)["acceptance"]
    barrier = threading.Barrier(2)

    def attempt(index):
        frappe.init(site=site,sites_path=sites)
        frappe.connect()
        frappe.set_user("Administrator")
        try:
            barrier.wait(timeout=10)
            result = api.execute(prop.name,"reserve",uuid.uuid4().hex,json.loads(json.dumps(values)))
            frappe.db.commit()
            return dict(session=index,result="confirmed",booking=result["booking"])
        except frappe.ValidationError:
            frappe.db.rollback()
            return dict(session=index,result="rejected")
        finally:
            frappe.destroy()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt,[1,2]))
    confirmed = [r for r in results if r["result"]=="confirmed"]
    frappe.db.rollback()  # End the parent's read-only preview snapshot before cleanup.
    # Both sessions have ended; this cleanup is a separate, audited transaction.
    for name in frappe.get_all("HS Booking",filters={"property":prop.name,"channel":"Prueba de concurrencia","status":"Confirmed"},pluck="name"):
        doc = frappe.get_doc("HS Booking",name,for_update=True)
        api.execute(prop.name,"booking_status",uuid.uuid4().hex,dict(booking=doc.name,modified=str(doc.modified),status="Cancelled",reason="Fin de prueba de concurrencia"))
    if len(confirmed)!=1:
        frappe.db.commit()
        raise AssertionError(f"Expected exactly one winner, got {results}")
    return dict(passed=True, case=case, sessions=results, isolation=frappe.db.sql("SELECT @@tx_isolation")[0][0])
