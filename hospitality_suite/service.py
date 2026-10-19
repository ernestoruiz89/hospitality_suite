"""One local database transaction per command; request boundary owns commit/rollback."""
from contextlib import contextmanager
import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.security import require, realtime


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


@contextmanager
def operation():
    before = getattr(frappe.local, "hs_operation", False)
    frappe.local.hs_operation = True
    try:
        yield
    finally:
        frappe.local.hs_operation = before


def lock_property(name, action=None):
    require(name, action)
    frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE", (name,))
    return frappe.get_doc("HS Property", name, for_update=True)


def locked_doc(*args, **kwargs):
    return frappe.get_doc(*args, **kwargs, for_update=bool(getattr(frappe.local, "hs_operation", False)))


def current_all(dt, filters=None, fields=None, pluck=None, order_by=None):
    """Current reads after resource lock are essential under MariaDB REPEATABLE READ.
    A prior permission query may already have established an older read snapshot.
    """
    query = frappe.qb.get_query(dt, filters=filters, fields=[pluck] if pluck else (fields or ["name"]),
                                order_by=order_by, ignore_permissions=True,
                                for_update=bool(getattr(frappe.local, "hs_operation", False)))
    rows = query.run(as_dict=True)
    return [row[pluck] for row in rows] if pluck else rows


def insert(dt, prop, **values):
    doc = frappe.get_doc(dict(doctype=dt, company=prop.company, property=prop.name, **values))
    # Only internal bookkeeping is exempt from native role grants. Operational records
    # use normal Frappe permissions, in addition to action/scope authorization.
    return doc.insert(ignore_permissions=dt in ("HS Request", "HS Audit Event", "HS Allocation"))


def audit(prop, action, doc, reason=None, details=None):
    return insert("HS Audit Event", prop, action=action, source_doctype=doc.doctype, source_name=doc.name,
                  actor=frappe.session.user, occurred_at=now_datetime(), business_date=prop.business_date,
                  reason=reason, details=canonical(details or {}))


def command(property_name, action, key, payload, handler):
    prop = lock_property(property_name, action)
    if not key or len(str(key)) > 140:
        frappe.throw(_("Se requiere una clave de idempotencia válida"))
    op = payload.get("operation", action)
    request_key = hashlib.sha256(f"{frappe.session.user}|{property_name}|{op}|{key}".encode()).hexdigest()
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
    found = frappe.db.sql("SELECT payload_hash,result FROM `tabHS Request` WHERE request_key=%s FOR UPDATE", (request_key,), as_dict=True)
    existing = found[0] if found else None
    if existing:
        if existing.payload_hash != digest:
            frappe.throw(_("La clave ya fue utilizada con otros datos"))
        return json.loads(existing.result)
    savepoint="hs_"+request_key[:24]
    frappe.db.savepoint(savepoint)
    try:
        with operation():
            result = handler(prop)
            insert("HS Request", prop, request_key=request_key, payload_hash=digest, operation=op, result=canonical(result))
            realtime(prop.name)
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
    return result


def assert_version(doc, modified):
    if not modified or str(doc.modified) != str(modified):
        frappe.throw(_("Otro usuario modificó el documento. Actualice la página y revise los cambios."), frappe.TimestampMismatchError)
