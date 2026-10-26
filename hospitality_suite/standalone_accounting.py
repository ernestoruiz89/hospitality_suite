"""Double-entry book for Frappe-only Hospitality Suite sites.

Every posting runs inside ``service.command``'s property lock and request
transaction. Installing ERPNext for a future cutover does not change the PMS
authority; native hotel vouchers remain blocked until the verified switch.
"""

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import getdate

from hospitality_suite.ledger_rules import LedgerValidationError, currency_line, inverse_lines, normalize_lines
from hospitality_suite.security import is_system, require
from hospitality_suite.service import assert_version, audit, insert, locked_doc


def _money_text(value):
    quantum = Decimal(1).scaleb(-(frappe.utils.get_currency_precision() or 2))
    return format(Decimal(str(value)).quantize(quantum), "f")


def provider():
    """A site's persisted authority never changes merely by installing an app."""
    if frappe.db.exists("DocType", "HS Site Mode"):
        selected = frappe.db.get_single_value("HS Site Mode", "provider")
        if selected in ("PMS", "ERPNext"):
            return selected.lower()
    return "erpnext" if "erpnext" in frappe.get_installed_apps() else "pms"


def require_pms(prop):
    if provider() != "pms":
        frappe.throw(_("El libro PMS no está activo en este sitio"))
    if not prop.organization:
        frappe.throw(_("Configure la entidad legal del establecimiento"))
    organization = frappe.get_doc("HS Organization", prop.organization)
    if not organization.active or organization.base_currency != prop.currency:
        frappe.throw(_("La entidad legal debe estar activa y usar la moneda base del establecimiento"))
    return organization


def account(prop, name, *, allow_inactive=False):
    row = frappe.db.get_value("HS Account", name,
        ["name", "property", "organization", "root_type", "account_type", "account_currency", "is_group", "active", "is_cash", "is_bank"], as_dict=True)
    if not row or (row.property, row.organization) != (prop.name, prop.organization):
        frappe.throw(_("La cuenta no pertenece al establecimiento"), frappe.PermissionError)
    if (not row.active and not allow_inactive) or row.is_group:
        frappe.throw(_("Seleccione una cuenta activa que admita movimientos"))
    return row


def save_account(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    fields = ("account_code", "account_number", "account_name", "root_type", "account_type", "account_currency",
              "parent_account", "is_group", "active")
    if not isinstance(data, dict) or set(data) - set(fields) - {"name", "modified", "is_cash", "is_bank"}:
        frappe.throw(_("La cuenta contiene campos desconocidos"))
    if data.get("name"):
        doc = locked_doc("HS Account", data["name"])
        assert_version(doc, data.get("modified"))
        before = {field: doc.get(field) for field in fields}
        for field in fields:
            if field in data:
                doc.set(field, data[field])
        if "account_type" in data:
            doc.is_cash = int(data["account_type"] == "Cash" and not doc.is_group)
            doc.is_bank = int(data["account_type"] == "Bank" and not doc.is_group)
        doc.save()
        audit(prop, "pms_account_updated", doc, before=before)
    else:
        values = {field: data.get(field) for field in fields if field in data}
        values["organization"] = prop.organization
        if "account_number" not in values:
            values["account_number"] = values.get("account_code")
        values["account_currency"] = values.get("account_currency") or prop.currency
        values["active"] = values.get("active", 1)
        if "account_type" not in values:
            values["account_type"] = "Cash" if data.get("is_cash") else "Bank" if data.get("is_bank") else "General"
        doc = insert("HS Account", prop, **values)
        audit(prop, "pms_account_created", doc)
    return {"account": doc.name, "account_code": doc.account_code,
            "root_type": doc.root_type, "modified": str(doc.modified)}


create_account = save_account


def chart(property_name):
    prop = require(property_name, "chart")
    require_pms(prop)
    return frappe.get_all("HS Account", filters={"property": prop.name, "organization": prop.organization},
        fields=["name", "modified", "account_code", "account_number", "account_name", "root_type", "account_type",
                "account_currency", "parent_account", "is_group", "active", "is_cash", "is_bank"],
        order_by="account_code asc")


def list_accounts(property_name):
    prop = require(property_name, "journal")
    require_pms(prop)
    accounts = frappe.get_all("HS Account", filters={"property": prop.name, "organization": prop.organization,
                    "active": 1, "is_group": 0},
                    fields=["name", "account_code", "account_name", "root_type", "account_currency", "is_cash", "is_bank"],
                    order_by="account_code asc")
    inventory_accounts = set(frappe.get_all("HS Product", filters={"property": prop.name,
                              "active": 1, "inventory_account": ["is", "set"]},
                              pluck="inventory_account"))
    for row in accounts:
        row["manual_enabled"] = not (row.is_cash or row.is_bank or
            row.name in inventory_accounts or row.name == prop.petty_cash_account)
    return accounts


def opening_status(property_name):
    prop = require(property_name, "setup")
    require_pms(prop)
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede registrar saldos iniciales"),
            frappe.PermissionError)
    existing = frappe.db.get_value("HS Journal", {"property": prop.name},
        "name", order_by="creation asc")
    return {"available": not bool(existing), "existing_journal": existing,
        "business_date": str(prop.business_date)}


def reversible_journals(property_name, search="", offset=0, page_length=25):
    prop = require(property_name, "approve")
    require_pms(prop)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación de asientos"))
    if (offset < 0 or not 1 <= page_length <= 100 or
            not isinstance(search, str) or len(search) > 100):
        frappe.throw(_("Revise la búsqueda de asientos"))
    pattern = "%" + search.strip() + "%"
    where = (
        "j.property=%s AND j.organization=%s AND j.company=%s "
        "AND j.status='Posted' "
        "AND j.source_doctype IN ('HS Manual Journal','HS Opening Balance') "
        "AND NOT EXISTS (SELECT 1 FROM `tabHS Journal` reversal "
        "WHERE reversal.reversal_of=j.name) "
        "AND (j.name LIKE %s OR j.source_name LIKE %s OR j.memo LIKE %s)")
    values = (prop.name, prop.organization, prop.company,
        pattern, pattern, pattern)
    total = frappe.db.sql("SELECT COUNT(*) FROM `tabHS Journal` j WHERE " +
        where, values, as_list=True)[0][0]
    rows = frappe.db.sql(
        "SELECT j.name,j.posting_date,j.source_doctype,j.source_name,j.memo,"
        "j.total_debit,j.total_credit FROM `tabHS Journal` j WHERE " + where +
        " ORDER BY j.posting_date DESC,j.creation DESC,j.name DESC "
        "LIMIT %s OFFSET %s", values + (page_length, offset), as_dict=True)
    if rows:
        names = [row.name for row in rows]
        placeholders = ",".join(["%s"] * len(names))
        lines = frappe.db.sql(
            "SELECT l.parent,l.account,a.account_code,a.account_name,"
            "l.account_currency,l.debit,l.credit,l.debit_in_account_currency,"
            "l.credit_in_account_currency FROM `tabHS Journal Line` l "
            "JOIN `tabHS Account` a ON a.name=l.account AND a.property=%s "
            "AND a.organization=%s "
            "WHERE l.parent IN (" + placeholders + ") ORDER BY l.parent,l.idx",
            tuple([prop.name, prop.organization, *names]), as_dict=True)
        by_journal = {name: [] for name in names}
        for line in lines:
            by_journal[line.parent].append({key: str(line[key])
                if key in ("debit", "credit", "debit_in_account_currency",
                           "credit_in_account_currency") else line[key]
                for key in ("account", "account_code", "account_name",
                            "account_currency", "debit", "credit",
                            "debit_in_account_currency",
                            "credit_in_account_currency")})
        for row in rows:
            row["lines"] = by_journal[row.name]
            row["posting_date"] = str(row.posting_date)
            row["total_debit"] = str(row.total_debit)
            row["total_credit"] = str(row.total_credit)
    return {"rows": rows, "total": total, "offset": offset,
        "page_length": page_length}


def manual_journal(prop, data):
    """Post a documented general-ledger adjustment on the open business day."""
    require_pms(prop)
    require(prop.name, "journal")
    if not isinstance(data, dict) or set(data) - {"reference", "reason", "lines"}:
        frappe.throw(_("El asiento manual contiene campos desconocidos"))
    reference = data.get("reference")
    reason = data.get("reason")
    if not isinstance(reference, str) or not reference.strip() or len(reference.strip()) > 140:
        frappe.throw(_("Indique una referencia única de hasta 140 caracteres"))
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        frappe.throw(_("Explique el motivo del asiento en hasta 500 caracteres"))
    if frappe.db.exists("HS Daily Close", {"property": prop.name,
                        "business_date": prop.business_date, "status": "Closed"}):
        frappe.throw(_("La fecha operativa está cerrada"))
    lines = data.get("lines")
    if not isinstance(lines, list) or any(not isinstance(line, dict) or
           set(line) - {"account", "debit", "credit", "memo", "account_currency", "exchange_rate",
                        "debit_in_account_currency", "credit_in_account_currency"} for line in lines):
        frappe.throw(_("Las líneas del asiento contienen campos desconocidos"))
    for line in lines:
        if line.get("memo") is not None and (not isinstance(line["memo"], str) or len(line["memo"]) > 140):
            frappe.throw(_("El detalle de cada partida debe tener hasta 140 caracteres"))
        selected = account(prop, line.get("account"))
        if selected.is_cash or selected.is_bank:
            frappe.throw(_("Use los movimientos de Caja o banco para sus cuentas de control"))
        if selected.name == prop.petty_cash_account:
            frappe.throw(_("Use el flujo de Caja Chica para su cuenta de control"))
        if frappe.db.exists("HS Product", {"property": prop.name,
                             "inventory_account": selected.name, "active": 1}):
            frappe.throw(_("Use movimientos de inventario para la cuenta de existencias"))
    doc = post(prop, source_doctype="HS Manual Journal", source_name=reference.strip(),
               purpose="Manual Journal", lines=lines, memo=reason.strip())
    audit(prop, "pms_manual_journal", doc, reason=reason.strip(),
          details={"reference": reference.strip(), "amount": doc.total_debit})
    return {"journal": doc.name, "posting_date": str(doc.posting_date),
            "reference": reference.strip(), "total": str(doc.total_debit)}


def opening_balance(prop, data):
    """A verified migration or first setup records one opening entry per property."""
    require_pms(prop)
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede registrar saldos iniciales"), frappe.PermissionError)
    if frappe.db.exists("HS Journal", {"property": prop.name}):
        frappe.throw(_("El establecimiento ya tiene asientos; concilie antes de migrar"))
    reference = (data.get("reference") or "").strip()
    if not reference or len(reference) > 140:
        frappe.throw(_("Identifique la conciliación que sustenta los saldos iniciales"))
    doc = post(prop, source_doctype="HS Opening Balance", source_name=reference,
               purpose="Opening Balance", lines=data.get("lines"),
               memo=data.get("memo"), posting_date=data.get("posting_date") or prop.business_date)
    return {"journal": doc.name, "total": str(doc.total_debit)}


def post(prop, *, source_doctype, source_name, purpose, lines, memo=None,
         posting_date=None, reversal_of=None):
    """Post one balanced journal in the current property transaction."""
    require_pms(prop)
    if not getattr(frappe.local, "hs_operation", False):
        frappe.throw(_("El asiento requiere una operación transaccional de Suite"))
    if frappe.db.exists("HS Daily Close", {"property": prop.name,
                        "business_date": prop.business_date, "status": "Closed"}):
        frappe.throw(_("La fecha operativa está cerrada"))
    if not all(isinstance(value, str) and value.strip() for value in (source_doctype, source_name, purpose)):
        frappe.throw(_("El asiento requiere origen y concepto"))
    if frappe.db.exists("HS Journal", {"property": prop.name, "source_doctype": source_doctype,
                                         "source_name": source_name, "purpose": purpose}):
        frappe.throw(_("El origen ya tiene un asiento para este concepto"))
    if posting_date and getdate(posting_date) != getdate(prop.business_date):
        if purpose != "Opening Balance" or not is_system():
            frappe.throw(_("Solo un saldo inicial autorizado puede usar otra fecha contable"))
    try:
        normalized, _totals = normalize_lines(lines, frappe.utils.get_currency_precision() or 2)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    enriched = []
    for line in normalized:
        historical_return = (getattr(frappe.local,
            "hs_historical_day_pass_return", False) and purpose in
            ("Historical Day Pass Credit", "Historical Day Pass Refund") or
            getattr(frappe.local, "hs_historical_maintenance_return", False)
            and source_doctype == "HS Stock Movement" and purpose == "Receipt")
        selected = account(prop, line["account"],
            allow_inactive=historical_return)
        try:
            enriched.append(currency_line(line, selected.account_currency or prop.currency,
                                          prop.currency, frappe.utils.get_currency_precision() or 2))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if line.get("party") and frappe.db.get_value("HS Party", line["party"], "property") != prop.name:
            frappe.throw(_("El tercero no pertenece al establecimiento"))
    doc = insert("HS Journal", prop, organization=prop.organization,
        posting_date=posting_date or prop.business_date, business_date=prop.business_date,
        source_doctype=source_doctype, source_name=source_name, purpose=purpose,
        reversal_of=reversal_of, memo=memo, status="Posted", lines=enriched)
    audit(prop, "pms_journal_posted", doc, details={"source": source_doctype, "source_name": source_name,
                                                     "purpose": purpose, "amount": doc.total_debit})
    return doc


def reverse(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    name = data.get("journal")
    reason = (data.get("reason") or "").strip()
    if not name or not reason or len(reason) > 500:
        frappe.throw(_("Seleccione el asiento y explique la reversión"))
    original = frappe.get_doc("HS Journal", name, for_update=True)
    if original.property != prop.name or original.organization != prop.organization:
        frappe.throw(_("El asiento pertenece a otro establecimiento"), frappe.PermissionError)
    if original.reversal_of or frappe.db.exists("HS Journal", {"reversal_of": original.name}):
        frappe.throw(_("Este asiento ya fue revertido o es una reversión"))
    if original.source_doctype in ("HS PMS Receivable", "HS Payment", "HS PMS Cash Movement",
                                   "HS PMS Allocation", "HS PMS Fiscal Document",
                                   "HS Stock Movement", "HS PMS Purchase",
                                   "HS PMS Opening Payable", "HS PMS Opening Credit",
                                   "HS PMS Opening Guarantee",
                                   "HS PMS Opening Supplier Credit",
                                   "HS PMS Supplier Credit Allocation",
                                   "ERPNext Opening Balance",
                                   "HS PMS Agency Commission",
                                   "HS Treasury Movement", "HS Petty Cash Expense",
                                   "HS Petty Cash Rendition"):
        frappe.throw(_("Este asiento pertenece a una operación con saldos vinculados; use su flujo de cancelación"))
    lines = inverse_lines([{"account": row.account, "debit": str(row.debit),
                            "credit": str(row.credit), "party": row.party, "memo": row.memo,
                            "account_currency": row.account_currency, "exchange_rate": str(row.exchange_rate),
                            "debit_in_account_currency": str(row.debit_in_account_currency),
                            "credit_in_account_currency": str(row.credit_in_account_currency)}
                           for row in original.lines])
    doc = post(prop, source_doctype="HS Journal", source_name=original.name,
               purpose="Reversal", lines=lines, memo=reason, reversal_of=original.name)
    audit(prop, "pms_journal_reversed", doc, reason=reason)
    return {"journal": doc.name, "reversed": original.name}


def balance(prop, account_name, through_date=None):
    require_pms(prop)
    account(prop, account_name, allow_inactive=True)
    date_filter = " AND j.posting_date<=%s" if through_date else ""
    values = [prop.name, account_name]
    if through_date:
        values.append(getdate(through_date))
    result = frappe.db.sql(
        "SELECT COALESCE(SUM(l.debit-l.credit),0) FROM `tabHS Journal Line` l "
        "JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' AND l.account=%s" + date_filter,
        tuple(values), as_list=True)
    return _money_text(result[0][0])


def account_currency_balance(prop, account_name, through_date=None):
    """Balance in the account's fixed currency, alongside the base balance."""
    require_pms(prop)
    selected = account(prop, account_name, allow_inactive=True)
    date_filter = " AND j.posting_date<=%s" if through_date else ""
    values = [prop.name, account_name]
    if through_date:
        values.append(getdate(through_date))
    result = frappe.db.sql(
        "SELECT COALESCE(SUM(l.debit_in_account_currency-l.credit_in_account_currency),0) "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' AND l.account=%s" + date_filter,
        tuple(values), as_list=True)
    return {"currency": selected.account_currency or prop.currency,
            "balance": _money_text(result[0][0]), "base_currency": prop.currency,
            "base_balance": balance(prop, account_name, through_date)}


def trial_balance(property_name, through_date=None):
    prop = require(property_name, "report")
    require_pms(prop)
    date_filter = " AND j.posting_date<=%s" if through_date else ""
    values = [prop.name]
    if through_date:
        values.append(getdate(through_date))
    rows = frappe.db.sql(
        "SELECT a.name AS account, a.account_code, a.account_name, a.root_type, a.account_currency, "
        "COALESCE(t.debit,0) AS debit, COALESCE(t.credit,0) AS credit, "
        "COALESCE(t.account_debit,0) AS account_debit, COALESCE(t.account_credit,0) AS account_credit "
        "FROM `tabHS Account` a LEFT JOIN ("
        "SELECT l.account, SUM(l.debit) AS debit, SUM(l.credit) AS credit, "
        "SUM(l.debit_in_account_currency) AS account_debit, "
        "SUM(l.credit_in_account_currency) AS account_credit "
        "FROM `tabHS Journal` j JOIN `tabHS Journal Line` l ON l.parent=j.name "
        "WHERE j.property=%s AND j.status='Posted'" + date_filter +
        " GROUP BY l.account) t ON t.account=a.name "
        "WHERE a.property=%s ORDER BY a.account_code",
        tuple(values + [prop.name]), as_dict=True)
    return {"property": prop.name, "currency": prop.currency,
            "rows": [{**row, "debit": _money_text(row.debit), "credit": _money_text(row.credit),
                      "balance": _money_text(Decimal(str(row.debit)) - Decimal(str(row.credit))),
                      "account_debit": _money_text(row.account_debit),
                      "account_credit": _money_text(row.account_credit),
                      "account_balance": _money_text(Decimal(str(row.account_debit)) - Decimal(str(row.account_credit)))}
                     for row in rows]}
