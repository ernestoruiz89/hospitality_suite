"""Numbered, printable PMS sale records backed by posted receivables.

The operator is responsible for registration and authorization requirements.
The system preserves the series, tax split and accounting trace of each document.
"""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import now_datetime

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import require
from hospitality_suite.service import audit, canonical, insert, locked_doc
from hospitality_suite.standalone_accounting import post, require_pms
from hospitality_suite.standalone_receivables import outstanding


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def _series(prop, name, kind):
    doc = locked_doc("HS PMS Fiscal Series", name)
    if (doc.property != prop.name or doc.organization != prop.organization or
            doc.document_type != kind or not doc.active or
            doc.next_number > doc.end_number):
        frappe.throw(_("Seleccione una serie vigente del tipo de documento"))
    return doc


def create_series(prop, data):
    require_pms(prop)
    require(prop.name, "setup")
    if not isinstance(data, dict) or set(data) - {"series_code", "document_type",
            "start_number", "end_number", "padding", "authorization_reference"}:
        frappe.throw(_("Revise la serie fiscal"))
    code = data.get("series_code")
    auth = data.get("authorization_reference") or ""
    if (not isinstance(code, str) or not code.strip() or len(code.strip()) > 30 or
            not isinstance(auth, str) or len(auth.strip()) > 140):
        frappe.throw(_("Indique una serie válida"))
    if data.get("document_type") not in ("Invoice", "Credit Note"):
        frappe.throw(_("Seleccione factura o nota de crédito"))
    try:
        start, end, padding = (int(data.get("start_number")), int(data.get("end_number")),
                               int(data.get("padding", 6)))
    except (TypeError, ValueError):
        frappe.throw(_("El rango de numeración no es válido"))
    if start < 1 or end < start or end > 999999999 or padding < 1 or padding > 9 or len(str(end)) > padding:
        frappe.throw(_("Revise el rango y la longitud del número"))
    if frappe.db.exists("HS PMS Fiscal Series", {"property": prop.name,
            "series_code": code.strip()}):
        frappe.throw(_("La serie ya existe en este establecimiento"))
    doc = insert("HS PMS Fiscal Series", prop, organization=prop.organization,
        series_code=code.strip(), document_type=data["document_type"],
        start_number=start, end_number=end, next_number=start, padding=padding,
        authorization_reference=auth.strip(), active=1)
    audit(prop, "pms_fiscal_series_created", doc,
          details={"range": [start, end], "authorization_reference": auth.strip()})
    return {"series": doc.name}


def _seller(prop):
    organization = frappe.get_doc("HS Organization", prop.organization)
    return organization


def _already_invoiced(prop, receivable):
    rows = frappe.db.sql(
        "SELECT d.name FROM `tabHS PMS Fiscal Line` l "
        "JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
        "WHERE d.property=%s AND d.document_type='Invoice' AND l.receivable=%s LIMIT 1",
        (prop.name, receivable), as_list=True)
    return rows[0][0] if rows else None


def invoice_quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"series", "receivables"}:
        frappe.throw(_("Revise la factura"))
    names = data.get("receivables")
    if not isinstance(names, list) or not names or len(names) > 100 or any(
            not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        frappe.throw(_("Seleccione de una a cien cuentas por cobrar distintas"))
    series = _series(prop, data.get("series"), "Invoice")
    organization = _seller(prop)
    rows = [locked_doc("HS PMS Receivable", name) for name in names]
    party = locked_doc("HS Party", rows[0].party)
    folio = rows[0].folio
    if party.property != prop.name or not party.party_name:
        frappe.throw(_("El cliente pertenece a otro establecimiento"))
    lines = []
    for row in rows:
        if (row.property != prop.name or row.organization != prop.organization or
                row.status != "Posted" or row.party != party.name or row.folio != folio or
                row.currency != prop.currency or not row.tax_profile or
                row.tax_treatment == "Unclassified" or row.opening_source_name or
                _already_invoiced(prop, row.name)):
            frappe.throw(_("Cada cargo debe estar vigente, clasificado y sin factura previa"))
        if not frappe.db.exists("HS Journal", {"name": row.journal, "property": prop.name,
                                                   "status": "Posted"}):
            frappe.throw(_("El cargo no conserva un asiento publicado"))
        product = (frappe.db.get_value("HS Charge", row.source_charge, "item")
                   if row.source_charge else frappe.db.get_value(
                       "HS Service Request", row.source_service, "item")
                   if row.source_service else frappe.db.get_value(
                       "HS Experience Order", row.experience_order, "pms_product")
                   if row.experience_order else None)
        lines.append({"receivable": row.name, "product": product,
            "description": row.description, "tax_treatment": row.tax_treatment,
            "tax_rate": str(row.tax_rate), "income_account": row.income_account,
            "tax_account": row.tax_account, "net_amount": _money(row.net_amount),
            "tax_amount": _money(row.tax_amount), "total_amount": _money(row.amount),
            "modified": str(row.modified)})
    lines.sort(key=lambda line: line["receivable"])
    total = sum((Decimal(line["total_amount"]) for line in lines), Decimal(0))
    net = sum((Decimal(line["net_amount"]) for line in lines), Decimal(0))
    tax = sum((Decimal(line["tax_amount"]) for line in lines), Decimal(0))
    signature = {"property": prop.name, "series": series.name,
        "series_modified": str(series.modified), "sequence": series.next_number,
        "seller": [organization.legal_name, organization.tax_id, organization.tax_regime],
        "buyer": [party.name, party.party_name, party.tax_id], "folio": folio, "lines": lines}
    return {"series": series.name, "document_number": f"{series.series_code}{series.next_number:0{series.padding}d}",
        "party": party.name, "buyer_name": party.party_name, "buyer_tax_id": party.tax_id,
        "seller_name": organization.legal_name, "seller_tax_id": organization.tax_id,
        "tax_regime": organization.tax_regime, "folio": folio, "currency": prop.currency,
        "net_amount": _money(net), "tax_amount": _money(tax), "total_amount": _money(total),
        "lines": lines, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def _consume_series(series):
    number = series.next_number
    formatted = f"{series.series_code}{number:0{series.padding}d}"
    series.next_number = number + 1
    series.save()
    return number, formatted


def issue_invoice(prop, data):
    if not isinstance(data, dict) or set(data) - {"series", "receivables", "acceptance"}:
        frappe.throw(_("Revise la emisión de la factura"))
    quote = invoice_quote(prop, {"series": data.get("series"),
                                  "receivables": data.get("receivables")})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("La serie, cliente o importes cambiaron; revise la factura"))
    series = _series(prop, quote["series"], "Invoice")
    number, formatted = _consume_series(series)
    doc = insert("HS PMS Fiscal Document", prop, organization=prop.organization,
        document_type="Invoice", series=series.name, sequence_number=number,
        document_number=formatted, authorization_reference=series.authorization_reference,
        business_date=prop.business_date, issued_at=now_datetime(),
        seller_name=quote["seller_name"], seller_tax_id=quote["seller_tax_id"],
        tax_regime=quote["tax_regime"], party=quote["party"],
        buyer_name=quote["buyer_name"], buyer_tax_id=quote["buyer_tax_id"],
        folio=quote["folio"], currency=prop.currency,
        net_amount=quote["net_amount"], tax_amount=quote["tax_amount"],
        total_amount=quote["total_amount"], status="Posted",
        lines=[{key: line[key] for key in ("receivable", "product", "description",
            "tax_treatment", "tax_rate", "income_account", "tax_account",
            "net_amount", "tax_amount", "total_amount")} for line in quote["lines"]])
    audit(prop, "pms_fiscal_invoice_recorded", doc,
          details={"document_number": formatted, "receivables": data["receivables"]})
    return {"document": doc.name, "document_number": formatted,
            "total_amount": quote["total_amount"], "currency": prop.currency}


def _credit_options(prop, original):
    if (original.property != prop.name or original.organization != prop.organization or
            original.document_type != "Invoice" or original.status != "Posted"):
        frappe.throw(_("Seleccione una factura emitida del establecimiento"))
    options = []
    for line in original.lines:
        row = locked_doc("HS PMS Receivable", line.receivable)
        if row.property != prop.name or row.party != original.party or row.folio != original.folio:
            frappe.throw(_("La factura contiene un cargo de otro establecimiento o cliente"))
        prior = frappe.db.sql(
            "SELECT COALESCE(SUM(l.net_amount),0) AS net, "
            "COALESCE(SUM(l.tax_amount),0) AS tax, COALESCE(SUM(l.total_amount),0) AS total "
            "FROM `tabHS PMS Fiscal Line` l JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
            "WHERE d.property=%s AND d.document_type='Credit Note' AND d.status='Posted' "
            "AND d.source_invoice=%s AND l.receivable=%s",
            (prop.name, original.name, row.name), as_dict=True)[0]
        remaining_net = Decimal(str(line.net_amount)) - Decimal(str(prior.net))
        remaining_tax = Decimal(str(line.tax_amount)) - Decimal(str(prior.tax))
        remaining_total = Decimal(str(line.total_amount)) - Decimal(str(prior.total))
        if min(remaining_net, remaining_tax, remaining_total) < 0 or remaining_net + remaining_tax != remaining_total:
            frappe.throw(_("Las notas previas exceden la línea de factura"))
        available = (min(remaining_total, outstanding(prop, row.name))
                     if row.status == "Posted" else Decimal(0))
        options.append({"receivable": row.name, "description": line.description,
            "net_amount": _money(line.net_amount), "tax_amount": _money(line.tax_amount),
            "total_amount": _money(line.total_amount), "remaining_net": _money(remaining_net),
            "remaining_tax": _money(remaining_tax), "remaining_total": _money(remaining_total),
            "available": _money(max(available, Decimal(0))), "modified": str(row.modified),
            "product": line.product, "tax_treatment": line.tax_treatment,
            "tax_rate": str(line.tax_rate), "income_account": line.income_account,
            "tax_account": line.tax_account, "receivable_account": row.receivable_account})
    return options


def credit_options(property_name, invoice):
    prop = require(property_name, "approve")
    require_pms(prop)
    original = locked_doc("HS PMS Fiscal Document", invoice)
    return {"invoice": original.name, "currency": original.currency,
            "lines": _credit_options(prop, original)}


def _split_credit(source, value):
    if value == Decimal(source["remaining_total"]):
        return Decimal(source["remaining_net"]), Decimal(source["remaining_tax"])
    tax = (Decimal(source["tax_amount"]) * value /
           Decimal(source["total_amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax = min(max(tax, value - Decimal(source["remaining_net"]), Decimal(0)),
              Decimal(source["remaining_tax"]), value)
    return value - tax, tax


def credit_quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"invoice", "series", "lines"}:
        frappe.throw(_("Revise la nota de crédito"))
    original = locked_doc("HS PMS Fiscal Document", data.get("invoice"))
    series = _series(prop, data.get("series"), "Credit Note")
    options = _credit_options(prop, original)
    requested = data.get("lines")
    if requested is None:
        if any(Decimal(row["available"]) != Decimal(row["remaining_total"])
               for row in options if Decimal(row["remaining_total"]) > 0):
            frappe.throw(_("Devuelva cobros o seleccione importes parciales antes de acreditar"))
        selected = {row["receivable"]: Decimal(row["remaining_total"])
                    for row in options if Decimal(row["remaining_total"]) > 0}
    else:
        if (not isinstance(requested, list) or not 1 <= len(requested) <= 100 or
                any(not isinstance(row, dict) or set(row) != {"receivable", "amount"}
                    for row in requested)):
            frappe.throw(_("Seleccione líneas e importes de la factura"))
        selected = {}
        for row in requested:
            name = row["receivable"]
            if not isinstance(name, str) or name in selected:
                frappe.throw(_("No repita líneas de factura"))
            try:
                value = amount(row["amount"])
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
            if value <= 0:
                frappe.throw(_("El importe de cada línea debe ser positivo"))
            selected[name] = value
    by_name = {row["receivable"]: row for row in options}
    if not selected or set(selected) - set(by_name):
        frappe.throw(_("Seleccione cargos de esta factura con saldo acreditable"))
    lines = []
    for name, value in selected.items():
        source = by_name[name]
        if value > Decimal(source["available"]):
            frappe.throw(_("La nota supera el saldo pendiente del cargo"))
        net, tax = _split_credit(source, value)
        lines.append({"receivable": name, "product": source["product"],
            "description": source["description"], "tax_treatment": source["tax_treatment"],
            "tax_rate": source["tax_rate"], "income_account": source["income_account"],
            "tax_account": source["tax_account"], "receivable_account": source["receivable_account"],
            "net_amount": _money(net), "tax_amount": _money(tax),
            "total_amount": _money(value)})
    lines.sort(key=lambda row: row["receivable"])
    net = sum((Decimal(row["net_amount"]) for row in lines), Decimal(0))
    tax = sum((Decimal(row["tax_amount"]) for row in lines), Decimal(0))
    total = sum((Decimal(row["total_amount"]) for row in lines), Decimal(0))
    signature = {"property": prop.name, "invoice": original.name,
        "invoice_modified": str(original.modified), "series": series.name,
        "series_modified": str(series.modified), "sequence": series.next_number,
        "options": options, "lines": lines}
    return {"invoice": original.name, "series": series.name,
        "document_number": f"{series.series_code}{series.next_number:0{series.padding}d}",
        "net_amount": _money(net), "tax_amount": _money(tax),
        "total_amount": _money(total), "currency": original.currency,
        "lines": lines, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def issue_credit(prop, data):
    if not isinstance(data, dict) or set(data) - {"invoice", "series", "lines", "acceptance", "reason"}:
        frappe.throw(_("Revise la nota de crédito"))
    quote = credit_quote(prop, {"invoice": data.get("invoice"), "series": data.get("series"),
                                "lines": data.get("lines")})
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(_("La factura, sus saldos o la serie cambiaron; revise nuevamente"))
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        frappe.throw(_("Explique el motivo de la nota de crédito"))
    original = locked_doc("HS PMS Fiscal Document", quote["invoice"])
    series = _series(prop, quote["series"], "Credit Note")
    entries = []
    for line in quote["lines"]:
        if Decimal(line["net_amount"]) > 0:
            entries.append({"account": line["income_account"], "debit": line["net_amount"],
                            "credit": "0", "party": original.party})
        if Decimal(line["tax_amount"]) > 0:
            entries.append({"account": line["tax_account"], "debit": line["tax_amount"],
                            "credit": "0", "party": original.party})
        entries.append({"account": line["receivable_account"], "debit": "0",
                        "credit": line["total_amount"], "party": original.party})
    journal = post(prop, source_doctype="HS PMS Fiscal Document",
        source_name=quote["document_number"], purpose="Credit Note",
        lines=entries, memo=reason.strip())
    number, formatted = _consume_series(series)
    doc = insert("HS PMS Fiscal Document", prop, organization=prop.organization,
        document_type="Credit Note", series=series.name, sequence_number=number,
        document_number=formatted, authorization_reference=series.authorization_reference,
        business_date=prop.business_date, issued_at=now_datetime(),
        seller_name=original.seller_name, seller_tax_id=original.seller_tax_id,
        tax_regime=original.tax_regime, party=original.party,
        buyer_name=original.buyer_name, buyer_tax_id=original.buyer_tax_id,
        folio=original.folio, currency=original.currency,
        net_amount=quote["net_amount"], tax_amount=quote["tax_amount"],
        total_amount=quote["total_amount"], status="Posted", source_invoice=original.name,
        journal=journal.name,
        lines=[{key: line[key] for key in ("receivable", "product", "description",
            "tax_treatment", "tax_rate", "income_account", "tax_account",
            "net_amount", "tax_amount", "total_amount")} for line in quote["lines"]])
    audit(prop, "pms_fiscal_credit_recorded", doc, reason=reason.strip(),
          details={"source_invoice": original.name, "document_number": formatted,
                   "journal": journal.name, "lines": [row["receivable"] for row in quote["lines"]]})
    return {"document": doc.name, "document_number": formatted, "journal": journal.name,
            "source_invoice": original.name, "total_amount": quote["total_amount"]}


def snapshot(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    org = frappe.get_doc("HS Organization", prop.organization)
    return {"currency": prop.currency, "tax_policy_confirmed": bool(prop.tax_policy_confirmed),
        "property_modified": str(prop.modified),
        "seller_name": org.legal_name, "seller_tax_id": org.tax_id,
        "tax_regime": org.tax_regime,
        "tax_profiles": frappe.get_all("HS PMS Tax Profile", filters={"property": prop.name},
            fields=["name", "label", "treatment", "rate", "included_in_price",
                    "liability_account", "active"], order_by="label asc"),
        "liability_accounts": frappe.get_all("HS Account", filters={"property": prop.name,
            "root_type": "Liability", "account_currency": prop.currency,
            "is_group": 0, "active": 1}, fields=["name", "account_code", "account_name"],
            order_by="account_code asc"),
        "series": frappe.get_all("HS PMS Fiscal Series", filters={"property": prop.name,
            "active": 1}, fields=["name", "series_code", "document_type", "next_number",
            "end_number", "authorization_reference"], order_by="creation desc"),
        "documents": frappe.get_all("HS PMS Fiscal Document", filters={"property": prop.name},
            fields=["name", "document_type", "document_number", "party", "buyer_name", "folio",
                    "net_amount", "tax_amount", "total_amount", "currency", "source_invoice",
                    "historical_source_invoice", "historical_day_pass",
                    "business_date"], order_by="creation desc", limit_page_length=100)}


def candidates(property_name, kind="ready", search="", offset=0, page_length=50):
    """Page unbilled charges and original invoices independently of the recent snapshot."""
    prop = require(property_name, "finance" if kind == "ready" else "approve")
    require_pms(prop)
    if kind not in ("ready", "invoices") or not isinstance(search, str) or len(search) > 100:
        frappe.throw(_("Revise la búsqueda de facturación"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación de facturación"))
    if offset < 0 or page_length < 1 or page_length > 100:
        frappe.throw(_("Revise la paginación de facturación"))
    search = search.strip()
    pattern = "%" + search + "%"
    if kind == "ready":
        rows = frappe.db.sql(
            "SELECT rec.name, rec.party, party.party_name, rec.folio, "
            "rec.description, rec.amount, rec.net_amount, rec.tax_amount, "
            "rec.tax_treatment, rec.business_date "
            "FROM `tabHS PMS Receivable` rec "
            "JOIN `tabHS Party` party ON party.name=rec.party "
            "WHERE rec.property=%s AND rec.organization=%s AND rec.status='Posted' "
            "AND rec.currency=%s AND COALESCE(rec.tax_profile,'')<>'' "
            "AND party.property=%s AND party.organization=%s "
            "AND NOT EXISTS (SELECT 1 FROM `tabHS PMS Fiscal Line` line "
            "JOIN `tabHS PMS Fiscal Document` doc ON doc.name=line.parent "
            "WHERE line.receivable=rec.name AND doc.property=%s "
            "AND doc.document_type='Invoice') "
            "AND (%s='' OR rec.name LIKE %s OR rec.description LIKE %s "
            "OR rec.party LIKE %s OR party.party_name LIKE %s OR rec.folio LIKE %s) "
            "ORDER BY rec.creation DESC, rec.name DESC LIMIT %s OFFSET %s",
            (prop.name, prop.organization, prop.currency, prop.name,
             prop.organization, prop.name, search, *([pattern] * 5),
             page_length + 1, offset), as_dict=True)
        return {"rows": [dict(row) for row in rows[:page_length]],
                "offset": offset, "has_more": len(rows) > page_length}
    rows = frappe.db.sql(
        "SELECT doc.name, doc.document_number, doc.party, doc.buyer_name, "
        "doc.total_amount, doc.business_date "
        "FROM `tabHS PMS Fiscal Document` doc "
        "WHERE doc.property=%s AND doc.organization=%s "
        "AND doc.document_type='Invoice' AND doc.status='Posted' "
        "AND (%s='' OR doc.name LIKE %s OR doc.document_number LIKE %s "
        "OR doc.party LIKE %s OR doc.buyer_name LIKE %s) "
        "ORDER BY doc.creation DESC, doc.name DESC LIMIT %s OFFSET %s",
        (prop.name, prop.organization, search, *([pattern] * 4),
         page_length + 1, offset), as_dict=True)
    return {"rows": [dict(row) for row in rows[:page_length]],
            "offset": offset, "has_more": len(rows) > page_length}


def archive(property_name, offset=0, page_length=50, search=""):
    """Keep numbered PMS documents discoverable and printable after ERPNext cutover."""
    prop = require(property_name, "finance")
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación del archivo fiscal"))
    if offset < 0 or page_length < 1 or page_length > 100:
        frappe.throw(_("Revise la paginación del archivo fiscal"))
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(_("Revise la búsqueda del archivo fiscal"))
    filters = {"property": prop.name}
    if search.strip():
        filters["document_number"] = ["like", "%" + search.strip() + "%"]
    return {"property": prop.name, "total": frappe.db.count(
                "HS PMS Fiscal Document", filters),
            "offset": offset, "page_length": page_length,
            "documents": frappe.get_all("HS PMS Fiscal Document", filters=filters,
                fields=["name", "document_type", "document_number", "business_date",
                        "buyer_name", "buyer_tax_id", "currency", "net_amount",
                        "tax_amount", "total_amount", "source_invoice",
                        "historical_source_invoice", "historical_day_pass", "status"],
                order_by="creation desc, name desc", limit_start=offset,
                limit_page_length=page_length)}
