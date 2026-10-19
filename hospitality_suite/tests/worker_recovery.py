"""Explicit real-RQ recovery probe; never called by scheduler or production paths."""
from datetime import timedelta
import time
import uuid

import frappe
from frappe.utils import now_datetime


def guard():
    if not frappe.local.site.endswith(".localhost") or not frappe.conf.get("allow_tests") or frappe.session.user!="Administrator":
        frappe.throw("Esta prueba requiere Administrator en un sitio localhost con allow_tests",frappe.PermissionError)


def expire_then_fail(property_name):
    guard()
    from hospitality_suite.jobs import expire_property
    expire_property(property_name)
    raise RuntimeError("HS: fallo sintético después de expirar; la transacción debe revertirse")


def verify():
    guard()
    from hospitality_suite import api
    from hospitality_suite.service import operation
    prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
    room=frappe.get_all("HS Room",filters={"property":prop.name},fields=["name","category"])[-1]
    guest=frappe.get_doc("HS Guest",{"property":prop.name})
    start=now_datetime()+timedelta(days=50)
    values=dict(starts_at=str(start),ends_at=str(start+timedelta(days=1)),guest=guest.name,customer=guest.customer,hold=1,
                rooms=[dict(category=room.category,room=room.name,people=1)])
    values["acceptance"]=api.preview(prop.name,values)["acceptance"]
    booking=api.execute(prop.name,"reserve",uuid.uuid4().hex,values)["booking"]
    with operation():
        doc=frappe.get_doc("HS Booking",booking)
        doc.hold_until=now_datetime()-timedelta(minutes=1)
        doc.save()
    frappe.db.commit()

    def wait(job):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            status=str(job.get_status(refresh=True)).lower()
            if "failed" in status or "finished" in status:
                frappe.db.rollback()
                return status
            time.sleep(.25)
        raise AssertionError("El worker no finalizó en 45 segundos: "+job.id)

    failed=frappe.enqueue("hospitality_suite.tests.worker_recovery.expire_then_fail",property_name=prop.name,queue="short",job_id="hs-recovery-fail-"+uuid.uuid4().hex)
    failed_status=wait(failed)
    assert "failed" in failed_status,failed_status
    assert frappe.db.get_value("HS Booking",booking,"status")=="Hold"
    assert frappe.db.count("HS Allocation",{"booking":booking,"status":"Active"})==1
    recovered=frappe.enqueue("hospitality_suite.jobs.expire_property",property_name=prop.name,queue="short",job_id="hs-recovery-ok-"+uuid.uuid4().hex)
    recovered_status=wait(recovered)
    assert "finished" in recovered_status,recovered_status
    assert frappe.db.get_value("HS Booking",booking,"status")!="Hold"
    assert frappe.db.count("HS Allocation",{"booking":booking,"status":"Active"})==0
    return dict(failed_job=failed.id,failed_status=failed_status,rollback_preserved_hold=True,recovered_job=recovered.id,
                recovered_status=recovered_status,booking=booking,final_booking_status=frappe.db.get_value("HS Booking",booking,"status"),active_allocations=0)
