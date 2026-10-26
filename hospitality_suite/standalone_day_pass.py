"""Roomless Day Pass sales for sites whose book is the standalone PMS."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.availability_search import positive_integer
from hospitality_suite.item_configuration import _pms_service
from hospitality_suite.security import ACTIONS, is_system, require
from hospitality_suite.service import audit, canonical, insert, locked_doc
from hospitality_suite.standalone_accounting import account, require_pms
from hospitality_suite.standalone_receivables import _create, allocated, credited, outstanding
from hospitality_suite.standalone_tax import tax_for_amount
from hospitality_suite.time import local, to_site


FIELDS = {"customer", "guest", "people", "starts_at", "ends_at", "notes"}


def opening_sale(prop, doc):
    """Verify a migrated paid sale against its archived invoice and mapped GL."""
    archive = frappe.db.get_value("HS Historical Fiscal Document",
        doc.opening_historical_invoice,
        ["name", "property", "organization", "source_doctype", "source_name",
         "document_type", "document_number", "buyer_name", "currency",
         "total_amount", "status", "snapshot_sha256"], as_dict=True)
    try:
        financial = frappe.parse_json(doc.opening_financial)
        if not isinstance(financial, dict):
            raise ValueError("invalid financial snapshot")
        if sha256(canonical(financial).encode()).hexdigest() != doc.opening_financial_sha256:
            raise ValueError("financial snapshot changed")
        total = Decimal(str(financial["invoice_total"]))
        net = Decimal(str(financial["invoice_net"]))
        tax = Decimal(str(financial["invoice_tax"]))
        lines = financial["invoice_gl"]
        receivable_account = financial["receivable_account"]
        if (not archive or archive.property != prop.name or
                archive.organization != prop.organization or
                archive.source_doctype != "Sales Invoice" or
                archive.source_name != doc.sales_invoice or
                archive.document_type != "Invoice" or
                archive.status != "Posted" or
                archive.currency != prop.currency or
                financial.get("invoice") != doc.sales_invoice or
                financial.get("invoice_currency") != prop.currency or
                financial.get("customer") != doc.customer or
                Decimal(str(archive.total_amount)) != total or
                Decimal(str(financial["payment_base_amount"])) != total or
                not all(value.is_finite() for value in (net, tax, total)) or
                net < 0 or tax < 0 or total <= 0 or net + tax != total or
                not isinstance(lines, list) or not 2 <= len(lines) <= 100 or
                not isinstance(receivable_account, str) or
                not receivable_account):
            raise ValueError("invoice and opening snapshot differ")
        debit = credit = ar = income = liability = Decimal(0)
        for line in lines:
            if not isinstance(line, dict) or not isinstance(line.get("account"), str):
                raise ValueError("invalid invoice GL line")
            selected = frappe.db.get_value("HS Account", line["account"],
                ["property", "organization", "root_type", "account_type",
                 "account_currency", "is_group"], as_dict=True)
            value_debit = Decimal(str(line["debit"]))
            value_credit = Decimal(str(line["credit"]))
            if (not selected or selected.property != prop.name or
                    selected.organization != prop.organization or
                    selected.is_group or
                    selected.account_currency != prop.currency or
                    selected.root_type != line.get("root_type") or
                    selected.account_type != line.get("account_type") or
                    not value_debit.is_finite() or not value_credit.is_finite() or
                    min(value_debit, value_credit) < 0 or
                    (value_debit > 0 and value_credit > 0) or
                    (value_debit == 0 and value_credit == 0) or
                    Decimal(str(line["debit_in_account_currency"])) != value_debit or
                    Decimal(str(line["credit_in_account_currency"])) != value_credit):
                raise ValueError("invoice GL line does not match account")
            debit += value_debit
            credit += value_credit
            if line["account"] == receivable_account:
                if (selected.root_type != "Asset" or
                        selected.account_type != "Receivable" or
                        line.get("party_type") != "Customer" or
                        line.get("party") != doc.customer):
                    raise ValueError("wrong historical customer receivable")
                ar += value_debit - value_credit
            elif (line.get("party_type") or line.get("party")):
                raise ValueError("unexpected invoice GL party")
            elif selected.root_type == "Income":
                income += value_credit - value_debit
            elif selected.root_type == "Liability":
                liability += value_credit - value_debit
            else:
                raise ValueError("unsupported invoice GL account")
        if debit != credit or ar != total or income != net or liability != tax:
            raise ValueError("historical sale is not balanced")
        return financial, archive
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError) as exc:
        frappe.throw(_("El Day Pass histórico no conserva su factura y saldo: {0}").format(exc))


def _receivable_account(prop):
    if not prop.receivable_account:
        frappe.throw(_("Configure la cuenta por cobrar del establecimiento"))
    row = account(prop, prop.receivable_account)
    if (row.root_type != "Asset" or row.account_type != "Receivable" or
            row.is_cash or row.is_bank or row.account_currency != prop.currency):
        frappe.throw(_("Seleccione una cuenta por cobrar PMS en moneda base"))
    return row


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - FIELDS - {"acceptance"}:
        frappe.throw(_("Revise los datos del Day Pass"))
    if not prop.day_pass_item:
        frappe.throw(_("Configure el producto Day Pass sin habitación"))
    from hospitality_suite.standalone_reception import party
    party(prop, data.get("customer"))
    people = positive_integer(data.get("people"), _("Personas del Day Pass"))
    if people > 100:
        frappe.throw(_("Day Pass admite hasta cien personas"))
    try:
        start, end = to_site(data.get("starts_at"), prop), to_site(data.get("ends_at"), prop)
    except (TypeError, ValueError, OverflowError):
        frappe.throw(_("Indique entrada y salida válidas para Day Pass"))
    if end <= start or local(start, prop).date() != local(end, prop).date():
        frappe.throw(_("Day Pass requiere entrada y salida en el mismo día local"))
    if end <= now_datetime():
        frappe.throw(_("No puede emitir un Day Pass cuyo período ya terminó"))
    guest = data.get("guest") or None
    if guest and frappe.db.get_value("HS Guest", guest, "property") != prop.name:
        frappe.throw(_("El huésped no pertenece al establecimiento"), frappe.PermissionError)
    notes = data.get("notes") or ""
    if not isinstance(notes, str) or len(notes.strip()) > 500:
        frappe.throw(_("Las notas admiten hasta 500 caracteres"))
    product = _pms_service(prop, prop.day_pass_item, _("Day Pass sin habitación"))
    details = frappe.db.get_value("HS Product", product.name,
        ["product_name", "sales_rate", "tax_profile", "modified"], as_dict=True)
    if not details.tax_profile or Decimal(str(details.sales_rate or 0)) <= 0:
        frappe.throw(_("Configure precio positivo y perfil tributario del producto Day Pass"))
    receivable = _receivable_account(prop)
    value = Decimal(str(details.sales_rate)) * people
    tax = tax_for_amount(prop, details.tax_profile, value)
    signature = {"property": prop.name, "customer": data["customer"], "guest": guest,
        "people": people, "starts_at": str(start), "ends_at": str(end),
        "notes": notes.strip(), "product": product.name,
        "product_modified": str(details.modified), "unit_rate": str(details.sales_rate),
        "income_account": product.income_account,
        "receivable_account": receivable.name,
        "tax_profile": tax["profile"], "tax_profile_modified": tax["profile_modified"],
        "net_amount": tax["net"], "tax_amount": tax["tax"], "total_amount": tax["total"]}
    return {"customer": data["customer"], "guest": guest, "people": people,
        "starts_at": local(start, prop).isoformat(),
        "ends_at": local(end, prop).isoformat(), "notes": notes.strip(),
        "product": product.name, "product_name": details.product_name,
        "unit_rate": str(details.sales_rate), "currency": prop.currency,
        "receivable_account": receivable.name, "income_account": product.income_account,
        "tax_profile": tax["profile"], "net_amount": tax["net"],
        "tax_amount": tax["tax"], "total_amount": tax["total"],
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def issue(prop, data):
    accepted = quote(prop, data)
    if data.get("acceptance") != accepted["acceptance"]:
        frappe.throw(_("Revise y acepte la cotización vigente de Day Pass"))
    reference = "Day Pass " + uuid4().hex
    description = _("Day Pass sin habitación: {0} persona(s), {1}").format(
        accepted["people"], local(to_site(data["starts_at"], prop), prop).strftime("%Y-%m-%d"))
    posted = _create(prop, party=accepted["customer"], reference=reference,
        description=description, value=Decimal(accepted["unit_rate"]) * accepted["people"],
        receivable=account(prop, accepted["receivable_account"]),
        income=account(prop, accepted["income_account"]),
        tax_profile=accepted["tax_profile"])
    if posted["amount"] != accepted["total_amount"]:
        frappe.throw(_("El importe del Day Pass cambió; revise nuevamente"))
    doc = insert("HS Day Pass", prop, customer=accepted["customer"], guest=accepted["guest"],
        people=accepted["people"], starts_at=to_site(data["starts_at"], prop),
        ends_at=to_site(data["ends_at"], prop), status="Issued",
        pms_receivable=posted["receivable"], quote_snapshot=canonical(accepted),
        notes=accepted["notes"])
    audit(prop, "pms_day_pass_issued", doc,
        details={"receivable": posted["receivable"], "journal": posted["journal"],
                 "total": posted["amount"]})
    return {"day_pass": doc.name, "receivable": posted["receivable"],
            "amount": posted["amount"], "currency": prop.currency,
            "status": doc.status}


def cancel(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) != {"day_pass", "modified", "reason"}:
        frappe.throw(_("Revise la cancelación del Day Pass"))
    from hospitality_suite.service import assert_version
    doc = locked_doc("HS Day Pass", data["day_pass"])
    assert_version(doc, data["modified"])
    if doc.property != prop.name or doc.status != "Issued" or not doc.pms_receivable:
        frappe.throw(_("Seleccione un Day Pass vigente del establecimiento"))
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        frappe.throw(_("Indique el motivo de cancelación"))
    receivable = locked_doc("HS PMS Receivable", doc.pms_receivable)
    if receivable.property != prop.name or allocated(prop, receivable.name) != 0:
        frappe.throw(_("Devuelva primero los cobros aplicados al Day Pass"))
    from hospitality_suite.standalone_fiscal import _already_invoiced
    invoice = _already_invoiced(prop, receivable.name)
    if invoice:
        if credited(prop, receivable.name) != Decimal(str(receivable.amount)):
            frappe.throw(_("Acredite íntegramente la factura antes de cancelar el Day Pass"))
    else:
        from hospitality_suite.standalone_receivables import cancel as cancel_receivable
        cancel_receivable(prop, {"receivable": receivable.name, "reason": reason.strip()},
                          allow_day_pass=True)
    doc.status = "Cancelled"
    doc.save()
    audit(prop, "pms_day_pass_cancelled", doc, reason=reason.strip(),
        details={"receivable": receivable.name, "invoice": invoice})
    return {"day_pass": doc.name, "status": doc.status,
            "receivable": receivable.name}


def historical_return_quote(prop, data):
    """Quote a full fiscal reversal and payment for a migrated paid pass."""
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) != {
            "day_pass", "modified", "series", "method", "shift",
            "amount", "reference", "reason"}:
        frappe.throw(_("Revise la devolución del Day Pass histórico"))
    from hospitality_suite.service import assert_version
    from hospitality_suite.standalone_accounting import account_currency_balance
    from hospitality_suite.standalone_cash import expected
    from hospitality_suite.standalone_currency import enabled, latest_rate
    from hospitality_suite.standalone_fiscal import _series
    from hospitality_suite.ledger_rules import LedgerValidationError, amount

    doc = locked_doc("HS Day Pass", data["day_pass"])
    assert_version(doc, data["modified"])
    if (doc.property != prop.name or doc.status != "Issued" or
            not doc.opening_historical_invoice or doc.opening_credit_note or
            doc.opening_refund or frappe.db.exists("HS PMS Fiscal Document",
                {"historical_day_pass": doc.name}) or
            frappe.db.exists("HS Payment", {"pms_historical_day_pass": doc.name})):
        frappe.throw(_("Seleccione un Day Pass histórico vigente sin devolución"))
    financial, archive = opening_sale(prop, doc)
    series = _series(prop, data["series"], "Credit Note")
    method = locked_doc("HS Payment Method", data["method"])
    if method.property != prop.name or not enabled(prop, method.currency):
        frappe.throw(_("Seleccione un medio de devolución del establecimiento"))
    cash = account(prop, method.account)
    counter = account(prop, financial["receivable_account"],
        allow_inactive=True)
    if (cash.account_currency != method.currency or
            not (cash.is_cash or cash.is_bank) or
            bool(cash.is_cash) != bool(method.is_cash) or
            counter.root_type != "Asset" or
            counter.account_type != "Receivable" or
            counter.account_currency != prop.currency):
        frappe.throw(_("Las cuentas de devolución no coinciden con la venta histórica"))
    try:
        value = amount(data["amount"])
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if value <= 0:
        frappe.throw(_("La devolución debe ser mayor que cero"))
    market_rate, rate_record = latest_rate(prop, method.currency)
    base = Decimal(str(financial["invoice_total"])).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    suggested = (base / market_rate).quantize(Decimal("0.01"),
        rounding=ROUND_HALF_UP)
    if suggested <= 0 or value != suggested:
        frappe.throw(_("Para devolver la factura íntegra entregue {0} {1} al cambio vigente").format(
            suggested, method.currency))
    rate = (base / value).quantize(Decimal("0.000000001"),
        rounding=ROUND_HALF_UP)
    if (value * rate).quantize(Decimal("0.01"),
            rounding=ROUND_HALF_UP) != base:
        frappe.throw(_("El redondeo impide devolver en esta moneda; elija otro medio"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data["shift"])
        if (shift.property != prop.name or shift.status != "Open" or
                shift.cashier != frappe.session.user):
            frappe.throw(_("La devolución en efectivo requiere turno propio abierto"),
                         frappe.PermissionError)
        if value > Decimal(expected(shift).get(method.currency, "0")):
            frappe.throw(_("El turno no tiene efectivo suficiente"))
    elif data["shift"]:
        frappe.throw(_("La devolución bancaria no se asigna a turno"))
    if value > Decimal(account_currency_balance(prop, cash.name)["balance"]):
        frappe.throw(_("Caja o banco no tiene saldo contable suficiente"))
    reference = data["reference"]
    reason = data["reason"]
    if (not isinstance(reference, str) or not reference.strip() or
            len(reference.strip()) > 140 or not isinstance(reason, str) or
            not reason.strip() or len(reason.strip()) > 500):
        frappe.throw(_("Indique referencia y motivo de la devolución"))
    reference, reason = reference.strip(), reason.strip()
    signature = {"property": prop.name, "day_pass": doc.name,
        "modified": str(doc.modified),
        "opening_financial_sha256": doc.opening_financial_sha256,
        "archive_sha256": archive.snapshot_sha256,
        "series": series.name, "series_modified": str(series.modified),
        "sequence": series.next_number,
        "method": method.name, "method_modified": str(method.modified),
        "cash_account": cash.name, "shift": shift.name if shift else None,
        "amount": str(value), "currency": method.currency,
        "market_rate": str(market_rate), "rate": str(rate),
        "rate_record": rate_record,
        "reference": reference, "reason": reason}
    return {"day_pass": doc.name, "modified": str(doc.modified),
        "historical_invoice": archive.name,
        "historical_invoice_number": archive.document_number,
        "series": series.name,
        "document_number": f"{series.series_code}{series.next_number:0{series.padding}d}",
        "method": method.name, "shift": shift.name if shift else None,
        "amount": str(value), "currency": method.currency,
        "exchange_rate": str(rate), "rate_record": rate_record,
        "market_rate": str(market_rate),
        "base_amount": str(base), "base_currency": prop.currency,
        "net_amount": financial["invoice_net"],
        "tax_amount": financial["invoice_tax"],
        "debit": counter.name, "credit": cash.name,
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def historical_return(prop, data):
    if not isinstance(data, dict) or set(data) != {
            "day_pass", "modified", "series", "method", "shift",
            "amount", "reference", "reason", "acceptance"}:
        frappe.throw(_("Revise la devolución del Day Pass histórico"))
    quote = historical_return_quote(prop, {key: value for key, value in
        data.items() if key != "acceptance"})
    if data["acceptance"] != quote["acceptance"]:
        frappe.throw(_("El acceso, la serie o el tipo de cambio cambió; revise la devolución"))
    from hospitality_suite.standalone_accounting import post
    from hospitality_suite.standalone_fiscal import _consume_series, _seller, _series

    doc = locked_doc("HS Day Pass", quote["day_pass"])
    financial, archive = opening_sale(prop, doc)
    series = _series(prop, quote["series"], "Credit Note")
    seller = _seller(prop)
    buyer = locked_doc("HS Party", doc.customer)
    if buyer.property != prop.name or buyer.organization != prop.organization:
        frappe.throw(_("El pagador histórico pertenece a otro establecimiento"))
    credit_entries = [{"account": row["account"],
        "party": row["party"] if row["party_type"] == "Customer" else None,
        "debit": row["credit"], "credit": row["debit"]}
        for row in financial["invoice_gl"]]
    before = getattr(frappe.local, "hs_historical_day_pass_return", False)
    frappe.local.hs_historical_day_pass_return = True
    try:
        credit_journal = post(prop, source_doctype="HS PMS Fiscal Document",
            source_name=quote["document_number"],
            purpose="Historical Day Pass Credit", lines=credit_entries,
            memo=quote["reason"])
    finally:
        frappe.local.hs_historical_day_pass_return = before
    number, formatted = _consume_series(series)
    frappe.local.hs_historical_day_pass_return = True
    try:
        credit = insert("HS PMS Fiscal Document", prop,
            organization=prop.organization, document_type="Credit Note",
            series=series.name, sequence_number=number,
            document_number=formatted,
            authorization_reference=series.authorization_reference,
            business_date=prop.business_date, issued_at=now_datetime(),
            seller_name=seller.legal_name, seller_tax_id=seller.tax_id,
            tax_regime=seller.tax_regime, party=doc.customer,
            buyer_name=archive.buyer_name or buyer.party_name,
            buyer_tax_id=buyer.tax_id, currency=prop.currency,
            net_amount=quote["net_amount"], tax_amount=quote["tax_amount"],
            total_amount=quote["base_amount"], status="Posted",
            historical_source_invoice=archive.name,
            historical_day_pass=doc.name, journal=credit_journal.name,
            lines=[{"description": _("Devolución Day Pass {0}").format(doc.name),
                "tax_treatment": "Factura histórica ERPNext",
                "net_amount": quote["net_amount"],
                "tax_amount": quote["tax_amount"],
                "total_amount": quote["base_amount"]}])
        payment = insert("HS Payment", prop, shift=quote["shift"],
            method=quote["method"], currency=quote["currency"],
            amount=quote["amount"], exchange_rate=quote["exchange_rate"],
            base_amount=quote["base_amount"], kind="Refund", status="Posted",
            reference=quote["reference"], reason=quote["reason"],
            pms_party=doc.customer, pms_counter_account=quote["debit"],
            pms_historical_day_pass=doc.name)
        refund_journal = post(prop, source_doctype="HS Payment",
            source_name=payment.name, purpose="Historical Day Pass Refund",
            memo=quote["reason"], lines=[
                {"account": quote["debit"], "party": doc.customer,
                 "debit": quote["base_amount"], "credit": "0"},
                {"account": quote["credit"], "debit": "0",
                 "credit": quote["base_amount"],
                 "account_currency": quote["currency"],
                 "exchange_rate": quote["exchange_rate"],
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": quote["amount"]}])
        payment.pms_journal = refund_journal.name
        payment.save()
        doc.opening_credit_note = credit.name
        doc.opening_refund = payment.name
        doc.status = "Cancelled"
        doc.save()
    finally:
        frappe.local.hs_historical_day_pass_return = before
    audit(prop, "pms_historical_day_pass_returned", doc,
        reason=quote["reason"], details={"invoice": archive.name,
            "credit_note": credit.name, "credit_journal": credit_journal.name,
            "refund": payment.name, "refund_journal": refund_journal.name,
            "amount": quote["amount"], "currency": quote["currency"]})
    return {"day_pass": doc.name, "status": doc.status,
        "credit_note": credit.name, "document_number": formatted,
        "credit_journal": credit_journal.name,
        "refund": payment.name, "refund_journal": refund_journal.name,
        "amount": quote["amount"], "currency": quote["currency"]}


def snapshot(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    roles = set(frappe.get_roles())
    can_setup = is_system() or bool(roles.intersection(ACTIONS["setup"]))
    can_approve = is_system() or bool(roles.intersection(ACTIONS["approve"]))
    rows = frappe.get_all("HS Day Pass", filters={"property": prop.name,
        "company": prop.company}, fields=["name", "customer", "guest", "people",
        "starts_at", "ends_at", "status", "pms_receivable",
        "opening_historical_invoice", "opening_credit_note", "opening_refund",
        "modified"],
        order_by="creation desc", limit_page_length=100)
    from hospitality_suite.standalone_fiscal import _already_invoiced
    for row in rows:
        source = frappe.db.get_value("HS PMS Receivable", row.pms_receivable,
            ["amount", "currency", "status"], as_dict=True) if row.pms_receivable else None
        historical = frappe.db.get_value("HS Historical Fiscal Document",
            row.opening_historical_invoice,
            ["property", "currency", "total_amount", "document_number"],
            as_dict=True) if row.opening_historical_invoice else None
        if historical and historical.property != prop.name:
            frappe.throw(_("El Day Pass histórico pertenece a otro establecimiento"))
        invoiced = _already_invoiced(prop, row.pms_receivable) if source else None
        row["invoiced"] = bool(invoiced or historical)
        row["amount"] = (str(source.amount) if source else
            str(historical.total_amount) if historical else None)
        row["currency"] = (source.currency if source else
            historical.currency if historical else None)
        row["historical_invoice_number"] = (historical.document_number
            if historical else None)
        row["outstanding"] = str(outstanding(prop, row.pms_receivable)) if source and source.status == "Posted" else "0.00"
        row["can_cancel"] = bool(row.status == "Issued" and source and source.status == "Posted" and
            allocated(prop, row.pms_receivable) == 0 and
            (not invoiced or credited(prop, row.pms_receivable) == Decimal(str(source.amount))))
        row["can_return"] = bool(can_approve and row.status == "Issued" and
            historical and not row.opening_credit_note and not row.opening_refund)
        row["effective_status"] = ("Cancelled" if row.status == "Cancelled" else
            "Upcoming" if get_datetime(row.starts_at) > now_datetime() else
            "Expired" if get_datetime(row.ends_at) <= now_datetime() else "Active")
        row["starts_at"] = local(row.starts_at, prop).isoformat()
        row["ends_at"] = local(row.ends_at, prop).isoformat()
    product = frappe.db.get_value("HS Product", prop.day_pass_item,
        ["name", "product_name", "sales_rate", "tax_profile"], as_dict=True) if prop.day_pass_item else None
    accounts = frappe.get_all("HS Account", filters={"property": prop.name,
        "organization": prop.organization, "root_type": "Asset",
        "account_type": "Receivable", "account_currency": prop.currency,
        "is_group": 0, "active": 1},
        fields=["name", "account_code", "account_name"],
        order_by="account_code asc") if can_setup else []
    series = frappe.get_all("HS PMS Fiscal Series", filters={
        "property": prop.name, "organization": prop.organization,
        "document_type": "Credit Note", "active": 1},
        fields=["name", "series_code", "next_number", "end_number"],
        order_by="series_code asc") if can_approve else []
    methods = frappe.get_all("HS Payment Method", filters={
        "property": prop.name}, fields=["name", "mode_of_payment", "currency",
            "is_cash"], order_by="mode_of_payment asc") if can_approve else []
    from hospitality_suite.standalone_cash import expected
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
        "cashier": frappe.session.user, "status": "Open"},
        fields=["name", "opened_at"], order_by="opened_at desc") if can_approve else []
    return {"property": prop.name, "currency": prop.currency,
        "time_zone": prop.time_zone, "property_modified": str(prop.modified),
        "receivable_account": prop.receivable_account,
        "receivable_accounts": accounts,
        "product": product, "day_passes": rows,
        "return_series": [row for row in series
            if row.next_number <= row.end_number],
        "return_methods": methods,
        "return_shifts": [{**row, "expected": expected(
            frappe.get_doc("HS Shift", row.name))} for row in shifts],
        "customers": frappe.get_all("HS Party", filters={"property": prop.name,
            "organization": prop.organization, "active": 1,
            "party_type": ["in", ["Customer", "Both"]]},
            fields=["name", "party_name"], order_by="party_name asc",
            limit_page_length=1000),
        "guests": frappe.get_all("HS Guest", filters={"property": prop.name,
            "company": prop.company}, fields=["name", "full_name"],
            order_by="full_name asc", limit_page_length=1000)}
