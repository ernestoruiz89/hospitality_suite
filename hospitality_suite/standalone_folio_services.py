"""Property-scoped service charges for a PMS folio, without ERPNext Items."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256

import frappe
from frappe import _

from hospitality_suite.ledger_rules import LedgerValidationError, amount
from hospitality_suite.security import document, require
from hospitality_suite.service import audit, canonical, current_all, insert, locked_doc
from hospitality_suite.standalone_accounting import account, require_pms
from hospitality_suite.standalone_tax import tax_for_amount


def _stays(prop, folio):
    if folio.stay:
        rows = [locked_doc("HS Stay", folio.stay)]
    elif folio.booking:
        rows = current_all("HS Stay", filters={"property": prop.name,
            "booking": folio.booking, "status": "Active"},
            fields=["name", "property", "company", "booking", "status", "modified"],
            order_by="creation asc")
    else:
        rows = []
    return [row for row in rows if row and row.property == prop.name and
            row.company == prop.company and row.status == "Active" and
            (folio.stay == row.name if folio.stay else folio.booking == row.booking)]


def options(property_name, folio_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    folio = document("HS Folio", folio_name, "finance")
    if folio.property != prop.name or folio.company != prop.company:
        frappe.throw(_("La cuenta de estancia pertenece a otro establecimiento"), frappe.PermissionError)
    products = frappe.get_all("HS Product", filters={"property": prop.name,
        "organization": prop.organization, "product_type": "Service", "active": 1},
        fields=["name", "product_code", "product_name", "sales_rate", "tax_profile",
                "income_account"], order_by="product_name asc", limit_page_length=500)
    return {"stays": [{"name": row.name} for row in _stays(prop, folio)],
            "products": [row for row in products if row.income_account and row.tax_profile and
                         Decimal(str(row.sales_rate or 0)) > 0]}


def _quantity(value):
    if isinstance(value, bool):
        frappe.throw(_("Indique una cantidad válida"))
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        frappe.throw(_("Indique una cantidad válida"))
    if (not result.is_finite() or result <= 0 or result > 10000 or
            result != result.quantize(Decimal("0.001"))):
        frappe.throw(_("La cantidad debe ser positiva y tener hasta tres decimales"))
    return result


def quote(prop, data):
    require_pms(prop)
    require(prop.name, "finance")
    if not isinstance(data, dict) or set(data) - {"folio", "stay", "product", "quantity"}:
        frappe.throw(_("Revise el servicio de la cuenta de estancia"))
    folio = document("HS Folio", data.get("folio"), "finance")
    if (folio.property != prop.name or folio.company != prop.company or
            folio.status != "Open" or folio.currency != prop.currency):
        frappe.throw(_("Seleccione una cuenta de estancia abierta en la moneda base"))
    from hospitality_suite.standalone_receivables import _customer
    _customer(prop, folio.customer)
    stays = _stays(prop, folio)
    stay_name = data.get("stay") or (stays[0].name if len(stays) == 1 else None)
    stay = next((row for row in stays if row.name == stay_name), None)
    if not stay:
        frappe.throw(_("Seleccione una estancia activa de esta cuenta"))
    product = locked_doc("HS Product", data.get("product"))
    if (product.property != prop.name or product.organization != prop.organization or
            not product.active or product.product_type != "Service" or
            not product.income_account or not product.tax_profile):
        frappe.throw(_("Seleccione un servicio PMS activo con cuenta e impuesto configurados"))
    income = account(prop, product.income_account)
    if income.root_type != "Income" or income.account_currency != prop.currency:
        frappe.throw(_("La cuenta de ingreso del servicio no usa la moneda base"))
    try:
        rate = amount(product.sales_rate)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if rate <= 0:
        frappe.throw(_("Configure un precio positivo para el servicio"))
    quantity = _quantity(data.get("quantity"))
    price = (rate * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        amount(price)
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    if price <= 0:
        frappe.throw(_("El importe del servicio debe ser positivo"))
    tax = tax_for_amount(prop, product.tax_profile, price)
    try:
        amount(tax["total"])
    except LedgerValidationError as exc:
        frappe.throw(str(exc))
    signature = {"property": prop.name, "folio": folio.name,
        "folio_modified": str(folio.modified), "stay": stay.name,
        "stay_modified": str(stay.modified), "product": product.name,
        "product_modified": str(product.modified), "quantity": str(quantity),
        "rate": str(rate), "tax": tax, "income_account": income.name}
    return {"folio": folio.name, "stay": stay.name, "product": product.name,
        "product_name": product.product_name, "quantity": str(quantity),
        "rate": str(rate), "currency": prop.currency, "price": tax["price"],
        "net_amount": tax["net"], "tax_amount": tax["tax"],
        "total_amount": tax["total"], "tax_treatment": tax["treatment"],
        "income_account": income.name,
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def add_charge(prop, data):
    if not isinstance(data, dict) or set(data) - {"folio", "stay", "product", "quantity", "acceptance"}:
        frappe.throw(_("Revise el servicio de la cuenta de estancia"))
    current = quote(prop, {key: data.get(key) for key in ("folio", "stay", "product", "quantity")})
    if data.get("acceptance") != current["acceptance"]:
        frappe.throw(_("La estancia, el precio o el impuesto cambiaron; revise el servicio"))
    doc = insert("HS Charge", prop, stay=current["stay"], folio=current["folio"],
        item=current["product"], description=current["product_name"],
        quantity=current["quantity"], rate=current["rate"], amount=current["price"],
        currency=prop.currency, business_date=prop.business_date,
        kind="Service", status="Pending", quote_snapshot=canonical(current))
    audit(prop, "pms_folio_service_added", doc,
        details={"product": current["product"], "quantity": current["quantity"],
                 "price": current["price"], "tax_preview": current["tax_amount"]})
    return {"charge": doc.name, "folio": doc.folio, "amount": current["price"],
            "currency": prop.currency}


def adjustment_options(property_name, folio_name):
    prop = require(property_name, "approve")
    require_pms(prop)
    folio = document("HS Folio", folio_name, "approve")
    if folio.property != prop.name or folio.company != prop.company:
        frappe.throw(_("La cuenta de estancia pertenece a otro establecimiento"), frappe.PermissionError)
    from hospitality_suite.standalone_receivables import _pending_groups
    result = []
    for source, group in _pending_groups(prop, folio.name).items():
        current = sum((Decimal(str(row.amount)) for row in group), Decimal(0))
        if current > 0:
            result.append({"source_charge": source, "description": group[0].description,
                           "current_price": str(current.quantize(Decimal("0.01"))),
                           "adjustments": len(group) - 1})
    return result


def _signed_amount(value):
    if isinstance(value, bool):
        frappe.throw(_("Indique un ajuste válido"))
    try:
        signed = Decimal(str(value))
        magnitude = amount(abs(signed))
    except (InvalidOperation, ValueError, TypeError, LedgerValidationError):
        frappe.throw(_("El ajuste debe ser un importe válido con dos decimales"))
    if not signed.is_finite() or not magnitude:
        frappe.throw(_("El ajuste debe ser distinto de cero"))
    return signed


def adjustment_quote(prop, data):
    require_pms(prop)
    require(prop.name, "approve")
    if not isinstance(data, dict) or set(data) - {"folio", "source_charge", "amount", "reason"}:
        frappe.throw(_("Revise el ajuste de la cuenta de estancia"))
    folio = document("HS Folio", data.get("folio"), "approve")
    if (folio.property != prop.name or folio.company != prop.company or
            folio.status != "Open" or folio.currency != prop.currency):
        frappe.throw(_("Seleccione una cuenta de estancia abierta en moneda base"))
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        frappe.throw(_("Indique un motivo de hasta 500 caracteres"))
    signed = _signed_amount(data.get("amount"))
    from hospitality_suite.standalone_receivables import _pending_groups
    source_name = data.get("source_charge")
    if not isinstance(source_name, str) or not source_name:
        frappe.throw(_("Seleccione un cargo pendiente de esta cuenta"))
    group = _pending_groups(prop, folio.name).get(source_name)
    if not group:
        frappe.throw(_("Seleccione un cargo pendiente de esta cuenta"))
    source = group[0]
    if (source.applies_to_charge or source.pms_receivable or source.sales_invoice or
            source.kind not in ("Lodging", "Service") or Decimal(str(source.amount)) <= 0 or
            source.company != prop.company or source.currency != prop.currency or
            any(row.stay != source.stay or row.item != source.item or
                row.company != prop.company or row.currency != prop.currency or
                row.folio != folio.name or row.pms_receivable or row.sales_invoice
                for row in group)):
        frappe.throw(_("El cargo de origen ya cambió"))
    current_price = sum((Decimal(str(row.amount)) for row in group), Decimal(0))
    new_price = current_price + signed
    if current_price <= 0 or new_price < 0:
        frappe.throw(_("El descuento supera el cargo pendiente"))
    product = locked_doc("HS Product", source.item)
    if product.property != prop.name or product.organization != prop.organization:
        frappe.throw(_("El producto del cargo pertenece a otro establecimiento"))
    if new_price:
        from hospitality_suite.standalone_receivables import _customer
        _customer(prop, folio.customer)
        if not product.active or not product.income_account:
            frappe.throw(_("Active el producto y su cuenta de ingresos antes de ajustar"))
        income = account(prop, product.income_account)
        if income.root_type != "Income" or income.account_currency != prop.currency:
            frappe.throw(_("La cuenta de ingreso del producto no usa la moneda base"))
        try:
            amount(new_price)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        current_tax = tax_for_amount(prop, product.tax_profile, current_price)
        next_tax = tax_for_amount(prop, product.tax_profile, new_price)
        try:
            amount(next_tax["total"])
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        action = "Adjustment"
    else:
        # A complete correction removes all pending rows without posting a sale.
        try:
            current_tax = tax_for_amount(prop, product.tax_profile, current_price)
        except frappe.ValidationError:
            current_tax = {"total": str(current_price.quantize(Decimal("0.01"))),
                           "estimate_unavailable": True}
        next_tax = {"net": "0.00", "tax": "0.00", "total": "0.00"}
        action = "Void"
    signature = {"property": prop.name, "folio": folio.name,
        "folio_modified": str(folio.modified), "source_charge": source.name,
        "group": [(row.name, str(row.modified), str(row.amount)) for row in group],
        "product_modified": str(product.modified), "amount": str(signed),
        "reason": reason.strip(), "current_tax": current_tax,
        "next_tax": next_tax, "action": action}
    return {"folio": folio.name, "source_charge": source.name,
        "description": source.description, "currency": prop.currency,
        "amount": str(signed), "reason": reason.strip(), "action": action,
        "current_price": str(current_price.quantize(Decimal("0.01"))),
        "new_price": str(new_price.quantize(Decimal("0.01"))),
        "current_total": current_tax["total"], "new_net": next_tax["net"],
        "new_tax": next_tax["tax"], "new_total": next_tax["total"],
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def adjust_charge(prop, data):
    if not isinstance(data, dict) or set(data) - {
            "folio", "source_charge", "amount", "reason", "acceptance"}:
        frappe.throw(_("Revise el ajuste de la cuenta de estancia"))
    current = adjustment_quote(prop, {key: data.get(key) for key in
        ("folio", "source_charge", "amount", "reason")})
    if data.get("acceptance") != current["acceptance"]:
        frappe.throw(_("El cargo o su impuesto cambiaron; revise el ajuste"))
    from hospitality_suite.standalone_receivables import _pending_groups
    group = _pending_groups(prop, current["folio"])[current["source_charge"]]
    if current["action"] == "Void":
        for row in group:
            doc = locked_doc("HS Charge", row.name)
            doc.status = "Reversed"
            doc.reason = current["reason"]
            doc.save()
        source = locked_doc("HS Charge", current["source_charge"])
        audit(prop, "pms_folio_charge_voided", source, reason=current["reason"],
              details={"charges": [row.name for row in group],
                       "price": current["current_price"]})
        return {"source_charge": source.name, "status": "Reversed",
                "folio": current["folio"], "new_total": "0.00"}
    source = locked_doc("HS Charge", current["source_charge"])
    doc = insert("HS Charge", prop, stay=source.stay, folio=source.folio,
        item=source.item, description="Ajuste: " + (source.description or source.name),
        quantity=1, rate=current["amount"], amount=current["amount"],
        currency=prop.currency, business_date=prop.business_date,
        kind="Adjustment", status="Pending", applies_to_charge=source.name,
        reason=current["reason"], quote_snapshot=canonical(current))
    audit(prop, "pms_folio_charge_adjusted", doc, reason=current["reason"],
          details={"source_charge": source.name, "amount": current["amount"],
                   "new_total": current["new_total"]})
    return {"adjustment": doc.name, "source_charge": source.name,
            "folio": source.folio, "new_total": current["new_total"],
            "currency": prop.currency}
