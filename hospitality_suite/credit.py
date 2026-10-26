"""Corporate exposure based on ERPNext receivables and uninvoiced PMS charges."""
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import getdate, nowdate

from hospitality_suite.pricing import decimal
from hospitality_suite.security import property_document, require
from hospitality_suite.service import assert_version, audit


def grant(prop, customer):
    rows = frappe.get_all("HS Billing Party", filters={"property": prop.name, "company": prop.company,
                                                      "customer": customer},
                          fields=["name", "kind", "credit_authorized", "credit_limit", "credit_days", "valid_until", "reason"],
                          limit=2)
    if len(rows) != 1:
        return None
    return rows[0]


def invoice_due_date(prop, customer, posting_date=None):
    base_date = max(getdate(nowdate()), getdate(posting_date or nowdate()))
    row = grant(prop, customer)
    if prop.allow_credit and row and row.credit_authorized and (not row.valid_until or getdate(row.valid_until) >= base_date):
        return base_date + timedelta(days=int(row.credit_days or 0))
    return base_date


def snapshot(prop, customer, *, details=False, offset=0, page_length=100):
    row = grant(prop, customer)
    today = getdate(nowdate())
    invoices = frappe.db.sql("""SELECT COALESCE(NULLIF(party_account_currency,''),currency) AS account_currency,
        SUM(outstanding_amount) AS receivable,
        SUM(CASE WHEN due_date < %s THEN outstanding_amount ELSE 0 END) AS overdue,
        MIN(CASE WHEN due_date < %s THEN due_date ELSE NULL END) AS oldest_due
        FROM `tabSales Invoice`
        WHERE company=%s AND customer=%s AND docstatus=1 AND outstanding_amount>0
        GROUP BY account_currency""", (today, today, prop.company, customer), as_dict=True)
    balances = defaultdict(lambda: {"receivable": decimal(0), "unbilled": decimal(0), "overdue": decimal(0), "oldest_due": None})
    for inv in invoices:
        current = balances[inv.account_currency]
        current["receivable"] += decimal(inv.receivable)
        current["overdue"] += decimal(inv.overdue)
        current["oldest_due"] = getdate(inv.oldest_due) if inv.oldest_due else None
    # Query company-wide folios because a customer can owe another property.
    # Pending charges have not entered Sales Invoice and therefore cannot be
    # counted in receivables. Scheduled future nights are intentionally excluded.
    pending = frappe.db.sql("""SELECT f.currency, SUM(c.amount) AS amount
        FROM `tabHS Folio` f JOIN `tabHS Charge` c ON c.folio=f.name
        WHERE f.company=%s AND f.customer=%s AND c.status='Pending'
        GROUP BY f.currency""", (prop.company, customer), as_dict=True)
    for item in pending:
        balances[item.currency]["unbilled"] += decimal(item.amount)
    groups = {currency: {"receivable": str(v["receivable"]), "unbilled": str(v["unbilled"]),
                         "overdue": str(v["overdue"]), "oldest_due": str(v["oldest_due"]) if v["oldest_due"] else None,
                         "exposure": str(v["receivable"] + v["unbilled"])} for currency, v in sorted(balances.items())}
    local = balances[prop.currency]
    limit = decimal(row.credit_limit) if row else decimal(0)
    exposure = local["receivable"] + local["unbilled"]
    other = {currency: value for currency, value in groups.items() if currency != prop.currency and decimal(value["exposure"]) != 0}
    active = bool(prop.allow_credit and row and row.credit_authorized and
                  (not row.valid_until or getdate(row.valid_until) >= today))
    status = ("Not Authorized" if not active else "Currency Review" if other else
              "Overdue" if local["overdue"] > 0 else "Over Limit" if exposure > limit else "Available")
    result = dict(customer=customer, property=prop.name, currency=prop.currency, status=status,
                  credit_authorized=active, grant_authorized=bool(row and row.credit_authorized),
                  limit=str(limit), receivable=str(local["receivable"]),
                  unbilled=str(local["unbilled"]), overdue=str(local["overdue"]),
                  exposure=str(exposure), available=str(max(decimal(0), limit-exposure)),
                  credit_days=int(row.credit_days or 0) if row else 0,
                  valid_until=str(row.valid_until) if row and row.valid_until else None,
                  by_currency=groups, other_currencies=other)
    if details:
        filters = {"company": prop.company, "customer": customer, "hs_property": prop.name,
                   "docstatus": 1, "outstanding_amount": [">", 0]}
        total = frappe.db.count("Sales Invoice", filters)
        visible = frappe.get_all("Sales Invoice", filters=filters,
                                 fields=["name", "currency", "party_account_currency", "outstanding_amount", "due_date"],
                                 order_by="due_date asc, name asc", start=offset, limit=page_length)
        result["invoices"] = [dict(name=i.name, currency=i.party_account_currency or i.currency,
                                   outstanding=str(i.outstanding_amount), due_date=str(i.due_date),
                                   overdue=bool(i.due_date and getdate(i.due_date) < today)) for i in visible]
        result.update(invoice_total=total, invoice_offset=offset, invoice_page_length=page_length,
                      invoice_has_more=offset+len(visible)<total)
    return result


def enforce(prop, customer, override_reason=None):
    result = snapshot(prop, customer)
    if result["status"] != "Available":
        if result["status"] in ("Over Limit", "Overdue") and override_reason:
            from hospitality_suite.service import audit
            reason = str(override_reason).strip()
            if len(reason) < 8 or len(reason) > 500:
                frappe.throw(frappe._("Explique la excepción de crédito en 8 a 500 caracteres"))
            require(prop.name, "approve")
            party = frappe.get_doc("HS Billing Party", grant(prop, customer).name)
            audit(prop, "Credit override", party, reason, details={"status": result["status"],
                  "customer": customer, "currency": result["currency"], "limit": result["limit"],
                  "exposure": result["exposure"], "overdue": result["overdue"]})
            return result
        messages = {"Not Authorized": "El cliente no tiene autorización de crédito vigente",
                    "Over Limit": "El saldo del cliente supera su límite de crédito autorizado",
                    "Overdue": "El cliente tiene facturas vencidas; revise cartera antes de registrar la salida",
                    "Currency Review": "El cliente tiene exposición en otra moneda; revise la cartera antes de autorizar crédito"}
        frappe.throw(frappe._(messages[result["status"]]))
    return result


def overview(property_name, offset=0, page_length=50):
    prop = require(property_name, "finance")
    offset, page_length = int(offset), int(page_length)
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(frappe._("Paginación inválida"))
    filters = {"property": prop.name, "company": prop.company}
    parties = frappe.get_all("HS Billing Party", filters={"property": prop.name, "company": prop.company},
                             fields=["name", "customer", "kind", "credit_authorized", "credit_limit", "credit_days", "valid_until", "modified"],
                             order_by="customer asc", start=offset, limit=page_length)
    return dict(property=prop.name, currency=prop.currency,
                property_credit_enabled=bool(prop.allow_credit),
                total=frappe.db.count("HS Billing Party", filters), offset=offset, page_length=page_length,
                rows=[dict(**snapshot(prop, p.customer), party=p.name,
                           customer_name=frappe.db.get_value("Customer", p.customer, "customer_name"),
                           kind=p.kind, modified=str(p.modified)) for p in parties])


def customer_search(property_name, search):
    """Small, explicit ERPNext customer lookup for granting hotel credit."""
    require(property_name, "setup")
    if not isinstance(search, str) or not 2 <= len(search.strip()) <= 100:
        frappe.throw(frappe._("Busque un cliente con 2 a 100 caracteres"))
    query = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = frappe.get_all("Customer", filters={"disabled": 0},
        or_filters=[["name", "like", "%" + query + "%"],
                    ["customer_name", "like", "%" + query + "%"]],
        fields=["name", "customer_name"],
        order_by="customer_name asc, name asc", limit=31)
    return {"rows": rows[:30], "has_more": len(rows) > 30}


def update(prop, data):
    allowed = {"credit_authorized", "credit_limit", "credit_days", "valid_until", "kind", "reason"}
    if any(key not in allowed | {"party", "modified"} for key in data):
        frappe.throw(frappe._("Campo de crédito no admitido"))
    party = property_document(prop, "HS Billing Party", data.get("party"), "setup")
    assert_version(party, data.get("modified"))
    reason = str(data.get("reason") or "").strip()
    if len(reason) < 8 or len(reason) > 500:
        frappe.throw(frappe._("Indique un motivo de 8 a 500 caracteres"))
    for key in allowed - {"reason"}:
        if key in data:
            party.set(key, data[key] or None if key == "valid_until" else data[key])
    party.reason = reason
    party.save()
    audit(prop, "Credit terms changed", party, reason)
    return dict(party=party.name, modified=str(party.modified))


def status(property_name, customer, offset=0, page_length=100):
    prop = require(property_name, "finance")
    offset, page_length = int(offset), int(page_length)
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(frappe._("Paginación inválida"))
    party = frappe.db.get_value("HS Billing Party", {"property": prop.name,
        "company": prop.company, "customer": customer},
        ["name", "kind", "modified", "reason"], as_dict=True)
    if not party:
        frappe.throw(frappe._("El cliente no está registrado como pagador de este establecimiento"), frappe.PermissionError)
    result = snapshot(prop, customer, details=True, offset=offset, page_length=page_length)
    result.update(party=party.name, kind=party.kind, modified=str(party.modified),
        reason=party.reason or "",
        customer_name=frappe.db.get_value("Customer", customer, "customer_name"))
    return result
