"""Atomic PMS counter sales using numbered invoices, cash and valued stock."""

from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
from hospitality_suite.security import ACTIONS, is_system, require
from hospitality_suite.service import audit, canonical, insert, locked_doc
from hospitality_suite.standalone_accounting import account, post, require_pms
from hospitality_suite.standalone_currency import latest_rate
from hospitality_suite.standalone_fiscal import (
    _series, credit_quote, invoice_quote, issue_credit, issue_invoice)
from hospitality_suite.standalone_folio_services import _quantity
from hospitality_suite.standalone_inventory import consume, receive
from hospitality_suite.standalone_receivables import _create
from hospitality_suite.standalone_services import _product
from hospitality_suite.standalone_tax import tax_for_amount


FIELDS = {"customer", "item", "warehouse", "quantity", "method", "shift",
          "series", "reference", "tendered", "notes"}


def _page(search, offset, page_length):
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(_("Revise la búsqueda"))
    try:
        start, length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación"))
    if start < 0 or start > 1000000 or not 1 <= length <= 50:
        frappe.throw(_("Revise la paginación"))
    escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%")
    escaped = escaped.replace("_", "\\_")
    return start, length, "%" + escaped + "%"


def options(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    can_approve = is_system() or bool(set(frappe.get_roles()).intersection(ACTIONS["approve"]))
    return {"property": prop.name, "currency": prop.currency,
        "can_approve": can_approve,
        "methods": frappe.get_all("HS Payment Method", filters={
            "property": prop.name, "company": prop.company},
            fields=["name", "mode_of_payment", "currency", "is_cash",
                    "reference_required"], order_by="mode_of_payment asc",
            limit_page_length=200),
        "shifts": frappe.get_all("HS Shift", filters={
            "property": prop.name, "company": prop.company, "status": "Open",
            "cashier": frappe.session.user},
            fields=["name", "cashier", "currency"], order_by="creation desc",
            limit_page_length=100),
        "series": frappe.get_all("HS PMS Fiscal Series", filters={
            "property": prop.name, "organization": prop.organization, "active": 1},
            fields=["name", "series_code", "document_type", "next_number",
                    "end_number"], order_by="series_code asc",
            limit_page_length=200),
        "warehouses": frappe.get_all("HS Warehouse", filters={
            "property": prop.name, "organization": prop.organization, "active": 1},
            fields=["name", "warehouse_name"], order_by="warehouse_name asc",
            limit_page_length=200)}


def customer_page(property_name, search="", offset=0, page_length=25):
    prop = require(property_name, "finance")
    require_pms(prop)
    start, length, pattern = _page(search, offset, page_length)
    rows = frappe.db.sql(
        "SELECT name, party_name AS customer_name FROM `tabHS Party` "
        "WHERE property=%s AND organization=%s AND active=1 "
        "AND party_type IN ('Customer','Both') "
        "AND (name LIKE %s OR party_name LIKE %s) "
        "ORDER BY party_name ASC, name ASC LIMIT %s OFFSET %s",
        (prop.name, prop.organization, pattern, pattern, length + 1, start),
        as_dict=True)
    return {"rows": rows[:length], "offset": start, "has_more": len(rows) > length}


def product_page(property_name, search="", offset=0, page_length=25):
    prop = require(property_name, "finance")
    require_pms(prop)
    start, length, pattern = _page(search, offset, page_length)
    rows = frappe.db.sql(
        "SELECT name, product_code, product_name, product_type, sales_rate "
        "FROM `tabHS Product` WHERE property=%s AND organization=%s "
        "AND active=1 AND product_type IN ('Service','Stock') "
        "AND sales_rate>0 AND COALESCE(income_account,'')<>'' "
        "AND COALESCE(tax_profile,'')<>'' "
        "AND (name LIKE %s OR product_code LIKE %s OR product_name LIKE %s) "
        "ORDER BY product_name ASC, name ASC LIMIT %s OFFSET %s",
        (prop.name, prop.organization, pattern, pattern, pattern, length + 1, start),
        as_dict=True)
    return {"rows": rows[:length], "offset": start, "has_more": len(rows) > length}


def history(property_name, search="", offset=0, page_length=25, returnable=0):
    prop = require(property_name, "finance")
    from hospitality_suite.standalone_accounting import provider

    active_provider = provider()
    if active_provider not in ("pms", "erpnext"):
        frappe.throw(_("El historial de ventas PMS no está disponible"))
    start, length, pattern = _page(search, offset, page_length)
    if str(returnable) not in ("0", "1"):
        frappe.throw(_("Revise el filtro de devoluciones"))
    rows = frappe.db.sql(
        "SELECT s.name, s.creation, s.modified, s.pms_party AS customer, "
        "p.party_name AS customer_name, s.pms_product AS item, "
        "product.product_name AS item_name, product.product_type, "
        "s.quantity, s.amount, s.currency, s.status, "
        "s.pms_fiscal_invoice AS sales_invoice, "
        "s.pms_fiscal_credit AS credit_note, "
        "s.pms_receivable, s.stock_entry, s.credit_note AS native_credit_note, "
        "s.erp_return_refund, s.return_stock_entry, "
        "s.erp_return_corrections, "
        "invoice.document_number, credit.document_number AS credit_number "
        "FROM `tabHS Service Request` s "
        "JOIN `tabHS PMS Receivable` r ON r.name=s.pms_receivable "
        "JOIN `tabHS Party` p ON p.name=s.pms_party "
        "JOIN `tabHS Product` product ON product.name=s.pms_product "
        "JOIN `tabHS PMS Fiscal Document` invoice ON invoice.name=s.pms_fiscal_invoice "
        "LEFT JOIN `tabHS PMS Fiscal Document` credit ON credit.name=s.pms_fiscal_credit "
        "WHERE s.property=%s AND s.company=%s AND r.property=s.property "
        "AND r.source_service=s.name AND r.status='Posted' "
        "AND p.property=s.property AND product.property=s.property "
        "AND invoice.property=s.property AND invoice.document_type='Invoice' "
        "AND (s.stay IS NULL OR s.stay='') "
        "AND (%s=0 OR (s.status='Delivered' AND "
        "(%s='pms' OR (COALESCE(s.erp_cutover_snapshot,'')<>'' "
        "AND COALESCE(s.erp_cutover_sha256,'')<>'' "
        "AND COALESCE(s.pms_fiscal_credit,'')='' "
        "AND COALESCE(s.credit_note,'')='' "
        "AND COALESCE(s.erp_return_refund,'')='')))) "
        "AND (s.name LIKE %s OR invoice.document_number LIKE %s OR "
        "p.party_name LIKE %s OR product.product_name LIKE %s) "
        "ORDER BY s.creation DESC, s.name DESC LIMIT %s OFFSET %s",
        (prop.name, prop.company, int(str(returnable)), active_provider,
         pattern, pattern,
         pattern, pattern, length + 1, start), as_dict=True)
    visible = rows[:length]
    names = [row.name for row in visible]
    payments = frappe.get_all("HS Payment", filters={"property": prop.name,
        "service": ["in", names], "kind": "Payment", "status": "Posted"},
        fields=["service", "method", "amount", "currency", "shift"],
        limit_page_length=50
    ) if names else []
    by_service = {row.service: row for row in payments}
    for row in visible:
        history = row.pop("erp_return_corrections")
        row.correction_count = len(frappe.parse_json(history)) if history else 0
        row.payment = by_service.get(row.name)
    return {"rows": visible, "offset": start, "has_more": len(rows) > length}


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01"),
        rounding=ROUND_HALF_UP), "f")


def _text(value, label, limit, *, required=False):
    if not isinstance(value, str) or len(value.strip()) > limit or (
            required and not value.strip()):
        frappe.throw(_("Revise {0}; admite hasta {1} caracteres").format(label, limit))
    return value.strip()


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - FIELDS - {"acceptance"}:
        frappe.throw(_("Revise la venta directa PMS"))
    customer = locked_doc("HS Party", data.get("customer"))
    if ((customer.property, customer.organization) !=
            (prop.name, prop.organization) or not customer.active or
            customer.party_type not in ("Customer", "Both")):
        frappe.throw(_("Seleccione un pagador activo del establecimiento"))
    product = _product(prop, data.get("item"), False)
    quantity = _quantity(data.get("quantity"))
    warehouse = None
    if product.product_type == "Stock":
        warehouse = locked_doc("HS Warehouse", data.get("warehouse"))
        if ((warehouse.property, warehouse.organization) !=
                (prop.name, prop.organization) or not warehouse.active):
            frappe.throw(_("Seleccione un almacén activo del establecimiento"))
    elif data.get("warehouse"):
        frappe.throw(_("Un servicio no requiere almacén"))
    receivable = account(prop, prop.receivable_account)
    if (receivable.root_type != "Asset" or
            receivable.account_type != "Receivable" or
            receivable.account_currency != prop.currency or
            receivable.is_cash or receivable.is_bank):
        frappe.throw(_("Configure la cuenta por cobrar PMS en moneda base"))
    series = _series(prop, data.get("series"), "Invoice")
    method = locked_doc("HS Payment Method", data.get("method"))
    cash = account(prop, method.account)
    if ((method.property, method.company) != (prop.name, prop.company) or
            method.currency != cash.account_currency or
            bool(method.is_cash) != bool(cash.is_cash) or
            not (cash.is_cash or cash.is_bank)):
        frappe.throw(_("El medio de pago o su cuenta no pertenece al establecimiento"))
    shift = None
    if method.is_cash:
        shift = locked_doc("HS Shift", data.get("shift"))
        if (shift.property != prop.name or shift.status != "Open" or
                shift.cashier != frappe.session.user):
            frappe.throw(_("Abra un turno propio para cobrar en efectivo"),
                         frappe.PermissionError)
    elif data.get("shift"):
        frappe.throw(_("El cobro bancario no requiere turno de Caja"))
    reference = _text(data.get("reference") or "", "la referencia", 140,
                      required=bool(method.reference_required))
    notes = _text(data.get("notes") or "", "las observaciones", 500)
    price = (Decimal(str(product.sales_rate)) * quantity).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax = tax_for_amount(prop, product.tax_profile, price)
    total = Decimal(tax["total"])
    if total <= 0:
        frappe.throw(_("La venta directa requiere un importe positivo"))
    market_rate, rate_record = latest_rate(prop, method.currency)
    paid = (total / market_rate).quantize(Decimal("0.01"),
        rounding=ROUND_HALF_UP)
    try:
        effective_rate = rate_for_base(paid, total)
    except LedgerValidationError as exc:
        frappe.throw(_("El importe no puede cobrarse exactamente en esta moneda: {0}").format(exc))
    raw_tendered = data.get("tendered")
    try:
        tendered = amount(raw_tendered) if raw_tendered not in (None, "") else paid
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if tendered < paid or (not method.is_cash and tendered != paid):
        frappe.throw(_("Revise lo recibido y el vuelto en la moneda del medio"))
    product_modified = str(product.modified)
    signature = {"property": prop.name, "customer": customer.name,
        "item": product.name, "product_modified": product_modified,
        "warehouse": warehouse.name if warehouse else None,
        "quantity": str(quantity), "price": _money(price),
        "tax_profile": tax["profile"],
        "tax_profile_modified": tax["profile_modified"],
        "tax_treatment": tax["treatment"], "tax_rate": tax["rate"],
        "tax_account": tax["liability_account"], "net": tax["net"],
        "tax": tax["tax"], "total": tax["total"],
        "income_account": product.income_account,
        "receivable_account": receivable.name,
        "series": series.name, "series_modified": str(series.modified),
        "series_next": series.next_number,
        "method": method.name, "method_modified": str(method.modified),
        "cash_account": cash.name, "shift": shift.name if shift else None,
        "payment_currency": method.currency, "payment_amount": _money(paid),
        "market_rate": str(market_rate), "rate_record": rate_record,
        "effective_rate": effective_rate, "tendered": _money(tendered),
        "reference": reference, "notes": notes}
    return {"customer": customer.name, "customer_name": customer.party_name,
        "item": product.name, "product_name": product.product_name,
        "product_type": product.product_type,
        "warehouse": warehouse.name if warehouse else None,
        "quantity": str(quantity), "unit_rate": str(product.sales_rate),
        "price": _money(price), "net_amount": tax["net"],
        "tax_amount": tax["tax"], "total": tax["total"],
        "currency": prop.currency, "tax_profile": tax["profile"],
        "income_account": product.income_account,
        "receivable_account": receivable.name,
        "method": method.name, "shift": shift.name if shift else None,
        "series": series.name,
        "document_number": f"{series.series_code}{series.next_number:0{series.padding}d}",
        "payment_currency": method.currency, "payment_amount": _money(paid),
        "market_rate": str(market_rate), "rate_record": rate_record,
        "exchange_rate": effective_rate, "tendered": _money(tendered),
        "change": _money(tendered - paid), "reference": reference,
        "notes": notes, "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def sell(prop, data):
    q = quote(prop, data)
    if data.get("acceptance") != q["acceptance"]:
        frappe.throw(_("El precio, impuesto, cambio o serie cambió; revise la venta"))
    product = locked_doc("HS Product", q["item"])
    service = insert("HS Service Request", prop, customer=q["customer"],
        pms_party=q["customer"], item=product.name, pms_product=product.name,
        warehouse=q["warehouse"], quantity=q["quantity"],
        amount=q["total"], currency=prop.currency, status="Requested",
        notes=q["notes"])
    stock = None
    if product.product_type == "Stock":
        stock = consume(prop, product=product.name, warehouse=q["warehouse"],
            quantity=q["quantity"], counter_account=product.expense_account,
            source_doctype=service.doctype, source_name=service.name,
            purpose="Direct Sale", memo="Venta directa " + service.name)
    posted = _create(prop, party=q["customer"],
        reference="Venta directa " + service.name,
        description=product.product_name, value=Decimal(q["price"]),
        receivable=account(prop, q["receivable_account"]),
        income=account(prop, q["income_account"]),
        tax_profile=q["tax_profile"], source_service=service.name)
    if posted["amount"] != q["total"]:
        frappe.throw(_("La venta cambió al contabilizarla; revise de nuevo"))
    fiscal_quote = invoice_quote(prop, {"series": q["series"],
        "receivables": [posted["receivable"]]})
    fiscal = issue_invoice(prop, {"series": q["series"],
        "receivables": [posted["receivable"]],
        "acceptance": fiscal_quote["acceptance"]})
    payment = insert("HS Payment", prop, customer=q["customer"],
        pms_party=q["customer"], pms_receivable=posted["receivable"],
        pms_counter_account=q["receivable_account"], service=service.name,
        shift=q["shift"], method=q["method"],
        currency=q["payment_currency"], amount=q["payment_amount"],
        exchange_rate=q["exchange_rate"], base_amount=q["total"],
        kind="Payment", status="Posted", reference=q["reference"] or
        fiscal["document_number"], tendered=q["tendered"],
        change_amount=q["change"])
    cash = account(prop, locked_doc("HS Payment Method", q["method"]).account)
    journal = post(prop, source_doctype="HS Payment", source_name=payment.name,
        purpose="Payment", lines=[
            {"account": cash.name, "debit": q["total"], "credit": "0",
             "account_currency": q["payment_currency"],
             "exchange_rate": q["exchange_rate"],
             "debit_in_account_currency": q["payment_amount"],
             "credit_in_account_currency": "0"},
            {"account": q["receivable_account"], "debit": "0",
             "credit": q["total"], "party": q["customer"]}],
        memo="Cobro de venta directa " + service.name)
    payment.pms_journal = journal.name
    payment.save()
    allocation = insert("HS PMS Allocation", prop, organization=prop.organization,
        receivable=posted["receivable"], payment=payment.name, kind="Direct",
        business_date=prop.business_date, currency=prop.currency,
        amount=q["total"], journal=journal.name)
    service.status = "Delivered"
    service.pms_receivable = posted["receivable"]
    service.stock_entry = stock["movement"] if stock else None
    service.pms_fiscal_invoice = fiscal["document"]
    service.save()
    audit(prop, "pms_direct_sale", service, details={
        "receivable": posted["receivable"], "invoice": fiscal["document"],
        "payment": payment.name, "allocation": allocation.name,
        "stock_movement": service.stock_entry, "total": q["total"],
        "payment_amount": q["payment_amount"],
        "payment_currency": q["payment_currency"]})
    return {"service": service.name, "receivable": posted["receivable"],
        "invoice": fiscal["document"],
        "document_number": fiscal["document_number"],
        "payment": payment.name, "stock_movement": service.stock_entry,
        "amount": q["payment_amount"], "currency": q["payment_currency"],
        "total": q["total"], "base_currency": prop.currency,
        "change": q["change"]}


def return_quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {
            "service", "series", "shift", "reference", "reason", "acceptance"}:
        frappe.throw(_("Revise la devolución de la venta directa"))
    service = locked_doc("HS Service Request", data.get("service"))
    if (service.property != prop.name or service.company != prop.company or
            service.status != "Delivered" or service.stay or service.folio or
            not service.pms_receivable or not service.pms_fiscal_invoice or
            service.pms_fiscal_credit or service.return_stock_entry):
        frappe.throw(_("Seleccione una venta directa PMS vigente del establecimiento"))
    receivable = locked_doc("HS PMS Receivable", service.pms_receivable)
    if (receivable.property != prop.name or receivable.source_service != service.name or
            receivable.status != "Posted"):
        frappe.throw(_("La venta directa no conserva su cuenta por cobrar"))
    invoice = locked_doc("HS PMS Fiscal Document", service.pms_fiscal_invoice)
    if (invoice.property != prop.name or invoice.document_type != "Invoice" or
            invoice.status != "Posted" or invoice.party != service.pms_party or
            Decimal(str(invoice.total_amount)) != Decimal(str(service.amount))):
        frappe.throw(_("La factura original de la venta no concilia"))
    payments = frappe.get_all("HS Payment", filters={"property": prop.name,
        "service": service.name, "pms_receivable": receivable.name,
        "kind": "Payment", "status": "Posted"},
        fields=["name", "amount", "currency", "pms_journal"],
        limit_page_length=2)
    if len(payments) != 1 or not payments[0].pms_journal:
        frappe.throw(_("La venta directa requiere un cobro original único"))
    payment = payments[0]
    reason = _text(data.get("reason") or "", "el motivo", 500, required=True)
    reference = _text(data.get("reference") or "", "la referencia", 140,
                      required=True)
    series = _series(prop, data.get("series"), "Credit Note")
    from hospitality_suite.standalone_cash import refund_quote

    refund_data = {"source_payment": payment.name, "amount": str(payment.amount),
        "shift": data.get("shift") or None, "reference": reference,
        "reason": reason}
    refund = refund_quote(prop, refund_data)
    movement = None
    if service.stock_entry:
        movement = locked_doc("HS Stock Movement", service.stock_entry)
        if (movement.property != prop.name or movement.product != service.pms_product or
                movement.warehouse != service.warehouse or
                movement.source_doctype != service.doctype or
                movement.source_name != service.name or
                movement.direction != "Issue" or
                movement.purpose != "Direct Sale" or
                Decimal(str(movement.value_delta)) >= 0):
            frappe.throw(_("La salida original de inventario no concilia"))
    signature = {"property": prop.name, "service": service.name,
        "service_modified": str(service.modified),
        "receivable": receivable.name, "invoice": invoice.name,
        "payment": payment.name, "refund": refund,
        "series": series.name, "series_modified": str(series.modified),
        "series_next": series.next_number,
        "stock_movement": movement.name if movement else None,
        "stock_value": str(movement.value_delta) if movement else None,
        "reason": reason, "reference": reference}
    return {"service": service.name, "invoice": invoice.name,
        "original_document_number": invoice.document_number,
        "series": series.name,
        "document_number": f"{series.series_code}{series.next_number:0{series.padding}d}",
        "receivable": receivable.name, "refund": refund,
        "stock_movement": movement.name if movement else None,
        "stock_value": _money(-Decimal(str(movement.value_delta))) if movement else None,
        "total": _money(service.amount), "currency": prop.currency,
        "reference": reference, "reason": reason,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def return_sale(prop, data):
    q = return_quote(prop, data)
    if data.get("acceptance") != q["acceptance"]:
        frappe.throw(_("La venta, reembolso o serie cambió; revise la devolución"))
    service = locked_doc("HS Service Request", q["service"])
    from hospitality_suite.standalone_cash import refund

    refund_data = {"source_payment": q["refund"]["source_payment"],
        "amount": q["refund"]["amount"], "shift": q["refund"]["shift"],
        "reference": q["reference"], "reason": q["reason"]}
    refunded = refund(prop, refund_data)
    credit_data = {"invoice": q["invoice"], "series": q["series"],
        "lines": [{"receivable": q["receivable"], "amount": q["total"]}]}
    reviewed = credit_quote(prop, credit_data)
    credited = issue_credit(prop, {**credit_data,
        "acceptance": reviewed["acceptance"], "reason": q["reason"]})
    movement = None
    if q["stock_movement"]:
        original = locked_doc("HS Stock Movement", q["stock_movement"])
        journal = locked_doc("HS Journal", original.journal)
        expense = next((row.account for row in journal.lines
            if Decimal(str(row.debit)) > 0), None)
        inventory = next((row.account for row in journal.lines
            if Decimal(str(row.credit)) > 0), None)
        if (journal.property != prop.name or not expense or not inventory or
                Decimal(str(original.value_delta)) != -Decimal(q["stock_value"])):
            frappe.throw(_("El costo original del artículo ya no concilia"))
        movement = receive(prop, product=service.pms_product,
            warehouse=service.warehouse, quantity=service.quantity,
            value=q["stock_value"], counter_account=expense,
            inventory_account_name=inventory, historical_return=True,
            source_doctype=service.doctype, source_name=service.name,
            purpose="Direct Sale Return", memo=q["reason"])
    service.status = "Returned"
    service.pms_fiscal_credit = credited["document"]
    service.return_stock_entry = movement["movement"] if movement else None
    service.save()
    audit(prop, "pms_direct_sale_return", service, reason=q["reason"],
        details={"credit_note": credited["document"],
                 "refund": refunded["payment"],
                 "return_stock_movement": service.return_stock_entry})
    return {"service": service.name, "status": service.status,
        "credit_note": credited["document"],
        "document_number": credited["document_number"],
        "refund": refunded["payment"],
        "return_stock_movement": service.return_stock_entry}
