import frappe

from hospitality_suite.security import document,require
from hospitality_suite.service import current_all


def hs_json(value):
    return frappe.parse_json(value)


def hs_label(value):
    return {"Confirmed":"Confirmada","Checked In":"Entrada registrada","Completed":"Completada","Cancelled":"Cancelada","No Show":"No presentada",
            "Hold":"Retención temporal","Active":"Alojado","Checked Out":"Salida registrada","Pending":"Pendiente","In Progress":"En proceso",
            "Inspection":"Pendiente de inspección","Open":"Abierto","Closed":"Cerrado","Review":"Por revisar","Posted":"Contabilizado",
            "Payment":"Cobro","Advance":"Anticipo","Guarantee":"Garantía","Guarantee Refund":"Devolución de garantía",
            "Guarantee Applied":"Aplicación de garantía","Refund":"Devolución","Withdrawal":"Retiro / entrega","Invoiced":"Facturado",
            "Corrective":"Correctivo","Preventive":"Preventivo","Departure":"Salida","Stay":"Estancia","Deep":"Profunda",
            "Normal":"Normal","High":"Alta","Urgent":"Urgente","Charge":"Cargo","Closed shift":"Turno cerrado",
            "Principal":"Principal","Acompañante":"Acompañante"}.get(value,value or "—")


def hs_money(value,currency):
    return frappe.utils.fmt_money(value,currency=currency)


def hs_date(value,property_name):
    if not value:
        return "—"
    from hospitality_suite.time import local
    return local(value,require(property_name)).strftime("%d/%m/%Y %H:%M")


def hs_account_context(name):
    from hospitality_suite.accounting import folios_for_stay,folio_balance
    stay=document("HS Stay",name)
    folios=folios_for_stay(stay)
    for folio in folios:
        folio["balance"]=folio_balance(folio.name)
    invoices=current_all("Sales Invoice",filters={"hs_folio":["in",[f.name for f in folios]],"docstatus":1},
                         fields=["name","customer","currency","net_total","total_taxes_and_charges","grand_total","outstanding_amount","hs_folio","is_return"])
    payments=current_all("HS Payment",filters={"property":stay.property,"status":"Posted"},
                         fields=["name","stay","booking","folio","kind","amount","currency","payment_entry","journal_entry"])
    payments=[p for p in payments if p.stay==stay.name or (p.folio and p.folio in [f.name for f in folios]) or (stay.booking and p.booking==stay.booking and not p.stay)]
    return dict(folios=folios,invoices=invoices,payments=payments)


def hs_maintenance_context(name):
    from hospitality_suite.security import ACTIONS,is_system
    order=document("HS Maintenance Order",name)
    allowed=is_system() or set(frappe.get_roles()).intersection(ACTIONS["maintain"]+ACTIONS["report"])
    return dict(parts=[r.as_dict() for r in order.parts] if allowed else [],cost=order.cost if allowed else None,
                currency=frappe.db.get_value("Company",order.company,"default_currency"))
