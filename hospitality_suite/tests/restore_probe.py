"""Compare the exact native and operational records of an isolated backup."""
import hashlib
import json
from pathlib import Path

import frappe

from hospitality_suite.schema import SCHEMA
from hospitality_suite.service import canonical

BASELINE=Path("/home/frappe/benches/hospitality-bench/.hospitality-restore-baseline.json")


def snapshot():
    if frappe.local.site not in ("hospitality.localhost","hospitality-restore.localhost") or not frappe.conf.get("allow_tests"):
        frappe.throw("Sonda limitada a los sitios aislados de alojamiento")
    result={dt:frappe.get_all(dt,fields=["*"],order_by="name") for dt in SCHEMA}
    native=("Sales Invoice","Payment Entry","Journal Entry","Stock Entry")
    for dt in native:
        result[dt]=frappe.get_all(dt,filters={"hs_property":["is","set"]},fields=["*"],order_by="name")
        parents=[r.name for r in result[dt]]
        meta=frappe.get_meta(dt)
        for field in meta.get_table_fields():
            result[field.options+":"+field.fieldname]=frappe.get_all(field.options,filters={"parent":["in",parents],"parenttype":dt,"parentfield":field.fieldname},fields=["*"],order_by="name")
    vouchers=[r.name for dt in native for r in result[dt]]
    for dt in ("GL Entry","Payment Ledger Entry","Stock Ledger Entry"):
        result[dt]=frappe.get_all(dt,filters={"voucher_no":["in",vouchers]},fields=["*"],order_by="name")
    return json.loads(canonical(result))


def baseline():
    if frappe.local.site!="hospitality.localhost":
        frappe.throw("Solo el sitio origen crea la referencia")
    data=snapshot()
    BASELINE.write_text(canonical(data),encoding="utf-8")
    BASELINE.chmod(0o600)
    return dict(site=frappe.local.site,rows={dt:len(rows) for dt,rows in data.items()},sha256=hashlib.sha256(canonical(data).encode()).hexdigest())


def verify():
    if frappe.local.site!="hospitality-restore.localhost":
        frappe.throw("Solo el tercer sitio verifica la restauración")
    expected=json.loads(BASELINE.read_text(encoding="utf-8"))
    restored=snapshot()
    changed=[dt for dt in expected if expected[dt]!=restored.get(dt)]
    if changed:
        raise AssertionError("La restauración difiere de la referencia: "+", ".join(changed))
    return dict(site=frappe.local.site,identical=True,tables=len(expected),rows=sum(len(r) for r in restored.values()),sha256=hashlib.sha256(canonical(restored).encode()).hexdigest())
