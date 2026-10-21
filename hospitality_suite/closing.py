from hospitality_suite.service import current_all, locked_doc
import frappe
from frappe.utils import add_days, now_datetime

from hospitality_suite.security import document, require
from hospitality_suite.service import insert, audit, canonical


def blockers(prop):
    from hospitality_suite.reconciliation import differences
    filters = {"property": prop.name}
    result = []
    for dt, extra, label in [
        ("HS Stay", {"status": "Active", "ends_at": ["<", now_datetime()]}, "Estancias vencidas"),
        ("HS Booking", {"status": "Confirmed", "starts_at": ["<", now_datetime()]}, "Llegadas pendientes"),
        ("HS Shift", {"status": ["in", ["Open", "Review"]]}, "Turnos sin cerrar"),
        ("HS Charge", {"status": "Pending", "business_date": ["<=", prop.business_date]}, "Cargos sin facturar"),
        ("HS Charge", {"status": "Scheduled", "service_date": ["<=", prop.business_date]}, "Cargos nocturnos sin generar"),
    ]:
        names = current_all(dt, filters={**filters, **extra}, pluck="name")
        if names:
            result.append(dict(type=label, documents=names))
    mismatches=differences(prop)
    if mismatches:
        result.append(dict(type="Diferencias entre PMS y ERPNext",documents=[r["source"] for r in mismatches]))
    return result


def daily_close(prop, data):
    from hospitality_suite.reports import summary
    reason=data.get('reason')
    if reason is not None and (not isinstance(reason,str) or len(reason)>1000):
        frappe.throw(frappe._('Escriba una observación de cierre de hasta 1000 caracteres'))
    name = frappe.db.get_value("HS Daily Close", {"property": prop.name, "business_date": prop.business_date})
    doc = locked_doc("HS Daily Close", name) if name else None
    from hospitality_suite.audit_trail import values as audit_values
    before=audit_values(doc)
    if doc and doc.status == "Closed":
        return dict(close=doc.name, status=doc.status)
    from hospitality_suite.security import ACTIONS,is_system
    if is_system() or set(ACTIONS['finance']).intersection(frappe.get_roles()):
        from hospitality_suite.periodic import generate
        generate(prop)
    problems = blockers(prop)
    captured=summary(prop)
    captured['presentation']=dict(property_name=prop.property_name,time_zone=prop.time_zone,reason=reason or '')
    from hospitality_suite.close_financials import snapshot
    captured["financial"]=snapshot(prop,captured)
    from hospitality_suite.audit_trail import review
    captured['audit_review']=review(prop)
    import hashlib
    stable={k:v for k,v in captured["financial"].items() if k!="captured_at"}
    fixed={k:v for k,v in captured.items() if k not in {"financial","occupied_hours","utilization","average_stay_hours"}}
    acceptance=hashlib.sha256(canonical(dict(operational=fixed,financial=stable,blockers=problems)).encode()).hexdigest()
    if data.get("confirm") and data.get("review_acceptance") and data["review_acceptance"]!=acceptance:
        frappe.throw(frappe._("El resumen del cierre cambió. Actualice la revisión antes de confirmar"))
    values = dict(business_date=prop.business_date, status="Review", summary=canonical(captured), blockers=canonical(problems),reason=reason)
    if doc:
        doc.update(values)
        doc.save()
    else:
        doc = insert("HS Daily Close", prop, **values)
    if data.get("confirm"):
        require(prop.name, "approve")
        if problems:
            frappe.throw(frappe._("Resuelva los pendientes antes de confirmar el cierre"))
        doc.status, doc.closed_at = "Closed", now_datetime()
        from hospitality_suite.time import local
        captured['presentation']['closed_at']=local(doc.closed_at,prop).strftime('%d/%m/%Y %H:%M:%S')
        doc.summary=canonical(captured)
        doc.save()
        prop.business_date = add_days(prop.business_date, 1)
        prop.save()
    audit(prop, "Daily close " + doc.status, doc,data.get('reason') or frappe._('Confirmación autorizada del cierre' if doc.status=='Closed' else 'Preparación de la auditoría del día'),before=before,business_date=doc.business_date)
    return dict(close=doc.name, status=doc.status, blockers=problems,period=frappe.parse_json(doc.summary),review_acceptance=acceptance)


def reopen(prop, data):
    require(prop.name, "approve")
    doc = document("HS Daily Close", data["close"], "approve")
    if doc.status != "Closed" or not data.get("reason"):
        frappe.throw(frappe._("Seleccione un cierre confirmado e indique el motivo"))
    if str(add_days(doc.business_date, 1)) != str(prop.business_date):
        frappe.throw(frappe._("Solo puede reabrir el último día cerrado"))
    doc.status, doc.reason = "Reopened", data["reason"]
    doc.save()
    prop.business_date = doc.business_date
    prop.save()
    audit(prop, "Reopen day", doc, data["reason"])
    return dict(close=doc.name, status=doc.status)
