"""Guest laundry, separate from the hotel's stock ledger for its own linen."""
import frappe
from frappe.utils import add_to_date, now_datetime

from hospitality_suite.accounting import ready
from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import require
from hospitality_suite.service import audit, insert, locked_doc


SERVICES = ("Wash & Iron", "Dry Clean", "Iron Only")
OPEN = ("Requested", "Collected", "In Process", "Ready")


def _positive(value, label):
    try:
        result = decimal(value)
    except Exception:
        frappe.throw(frappe._("Revise {0}").format(label))
    if not result.is_finite() or result <= 0:
        frappe.throw(frappe._("{0} debe ser mayor que cero").format(label))
    return result


def _stay(prop, name):
    stay = locked_doc("HS Stay", name)
    if stay.property != prop.name or stay.company != prop.company or stay.status != "Active":
        frappe.throw(frappe._("Seleccione una estancia activa del establecimiento"))
    return stay


def _folio(prop, stay, name=None):
    from hospitality_suite.accounting import folios_for_stay
    available = [row for row in folios_for_stay(stay) if row.property == prop.name and row.status == "Open"]
    chosen = next((row for row in available if row.name == name), None) if name else next(
        (row for row in available if row.stay == stay.name), available[0] if available else None)
    if not chosen or chosen.company != prop.company or chosen.currency != prop.currency:
        frappe.throw(frappe._("Seleccione una cuenta abierta en la moneda del establecimiento"))
    return locked_doc("HS Folio", chosen.name)


def save_rate(prop, data):
    require(prop.name, "setup")
    garment = str(data.get("garment") or "").strip()
    service = data.get("service_type")
    if not garment or len(garment) > 80 or service not in SERVICES:
        frappe.throw(frappe._("Indique una prenda y un tipo de servicio válidos"))
    from hospitality_suite.standalone_accounting import provider, require_pms
    item = product = None
    if provider() == "pms":
        require_pms(prop)
        product = locked_doc("HS Product", data.get("pms_product"))
        if (product.property != prop.name or product.organization != prop.organization or
                not product.active or product.product_type != "Service" or
                not product.income_account or not product.tax_profile):
            frappe.throw(frappe._("Use un producto de servicio PMS con ingreso e impuesto configurados"))
        from hospitality_suite.standalone_accounting import account
        income = account(prop, product.income_account)
        if income.root_type != "Income" or income.account_currency != prop.currency:
            frappe.throw(frappe._("La cuenta de ingresos de lavandería debe usar la moneda base"))
    else:
        item = locked_doc("Item", data.get("item"))
        if item.disabled or not item.is_sales_item or item.is_stock_item or item.is_fixed_asset:
            frappe.throw(frappe._("Use un artículo de venta sin inventario para lavandería"))
    rate = money(_positive(data.get("rate"), frappe._("La tarifa")), currency=prop.currency)
    express = data.get("express_rate")
    express = money(_positive(express, frappe._("La tarifa exprés")), currency=prop.currency) if express not in (None, "") else None
    if rate <= 0 or (express is not None and express <= 0):
        frappe.throw(frappe._("La tarifa debe superar la precisión de la moneda"))
    existing = data.get("rate_name")
    if existing:
        doc = locked_doc("HS Laundry Rate", existing)
        if doc.property != prop.name:
            frappe.throw(frappe._("La tarifa pertenece a otro establecimiento"), frappe.PermissionError)
        from hospitality_suite.service import assert_version
        assert_version(doc, data.get("modified"))
    else:
        doc = frappe.new_doc("HS Laundry Rate")
        doc.company, doc.property = prop.company, prop.name
    doc.garment, doc.service_type = garment, service
    doc.item = item.name if item else None
    doc.pms_product = product.name if product else None
    doc.currency, doc.rate, doc.express_rate = prop.currency, rate, express
    doc.active = 1 if data.get("active", 1) in (True, 1, "1") else 0
    doc.save() if existing else doc.insert()
    audit(prop, "Laundry rate", doc)
    return dict(rate=doc.name, modified=str(doc.modified))


def request_pickup(prop, data):
    stay = _stay(prop, data.get("stay"))
    folio = _folio(prop, stay, data.get("folio"))
    doc = insert("HS Laundry Order", prop, stay=stay.name, room=stay.room, folio=folio.name,
                 currency=folio.currency, status="Requested", express=int(bool(data.get("express"))),
                 notes=str(data.get("notes") or "").strip()[:500])
    audit(prop, "Laundry requested", doc)
    return dict(order=doc.name, status=doc.status)


def collect(prop, data):
    if data.get("order"):
        doc = locked_doc("HS Laundry Order", data["order"])
        if doc.property != prop.name or doc.status != "Requested":
            frappe.throw(frappe._("La solicitud ya no está pendiente de recogida"))
        from hospitality_suite.service import assert_version
        assert_version(doc, data.get("modified"))
    else:
        result = request_pickup(prop, data)
        doc = locked_doc("HS Laundry Order", result["order"])
    _stay(prop, doc.stay)
    if data.get("complimentary"):
        require(prop.name, "approve")
    rows = data.get("items")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        frappe.throw(frappe._("Cuente entre 1 y 100 tipos de prendas"))
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            frappe.throw(frappe._("Revise el detalle de prendas"))
        qty = row.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 1000:
            frappe.throw(frappe._("Indique una cantidad entera de 1 a 1000 por prenda"))
        rate = locked_doc("HS Laundry Rate", row.get("rate"))
        if rate.property != prop.name or rate.company != prop.company or not rate.active:
            frappe.throw(frappe._("La tarifa de lavandería no está activa en este establecimiento"))
        unit = decimal(rate.express_rate) if doc.express and decimal(rate.express_rate) > 0 else decimal(rate.rate)
        amount = money(unit * qty, currency=doc.currency)
        lines.append(dict(laundry_rate=rate.name, garment=rate.garment, service_type=rate.service_type,
                          item=rate.item, pms_product=rate.pms_product,
                          quantity=qty, returned_quantity=0, rate=unit, amount=amount))
    doc.set("items", lines)
    doc.total = money(sum(decimal(row["amount"]) for row in lines), currency=doc.currency)
    doc.complimentary = 1 if data.get("complimentary") else 0
    doc.status, doc.collected_by, doc.collected_at = "Collected", frappe.session.user, now_datetime()
    doc.counted_at = None
    doc.ready_by = add_to_date(now_datetime(), hours=8 if doc.express else 32)
    if data.get("notes"):
        doc.notes = str(data["notes"]).strip()[:500]
    doc.save()
    audit(prop, "Laundry collected", doc, details=dict(pieces=sum(row["quantity"] for row in lines)))
    return dict(order=doc.name, status=doc.status, total=str(doc.total))


def advance(prop, data):
    doc = locked_doc("HS Laundry Order", data.get("order"))
    from hospitality_suite.service import assert_version
    assert_version(doc, data.get("modified"))
    if doc.property != prop.name or (doc.status, data.get("status")) not in (
            ("Collected", "In Process"), ("In Process", "Ready")):
        frappe.throw(frappe._("La transición de lavandería no es válida"))
    doc.status = data["status"]
    doc.save()
    audit(prop, "Laundry " + doc.status, doc)
    return dict(order=doc.name, status=doc.status)


def return_pieces(prop, data):
    doc = locked_doc("HS Laundry Order", data.get("order"))
    from hospitality_suite.service import assert_version
    assert_version(doc, data.get("modified"))
    if doc.property != prop.name or doc.status != "Ready" or not isinstance(data.get("counts"), dict):
        frappe.throw(frappe._("La orden debe estar lista para registrar la devolución"))
    counts = data["counts"]
    if set(counts) != {row.name for row in doc.items}:
        frappe.throw(frappe._("Cuente todas las prendas de la orden"))
    for row in doc.items:
        qty = counts[row.name]
        if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= row.quantity:
            frappe.throw(frappe._("La cantidad devuelta está fuera del rango recogido"))
        row.returned_quantity = qty
    doc.counted_at = now_datetime()
    doc.save()
    audit(prop, "Laundry return count", doc)
    return dict(order=doc.name, pending=sum(row.quantity-row.returned_quantity for row in doc.items))


def deliver(prop, data):
    require(prop.name, "service")  # Folio charges are posted by Reception/Management.
    doc = locked_doc("HS Laundry Order", data.get("order"))
    from hospitality_suite.service import assert_version
    assert_version(doc, data.get("modified"))
    if doc.property != prop.name or doc.status != "Ready" or not doc.items:
        frappe.throw(frappe._("La orden debe estar lista antes de entregarla"))
    from hospitality_suite.standalone_accounting import provider
    if provider() == "pms" and not doc.counted_at:
        frappe.throw(frappe._("Registre el conteo de prendas devueltas antes de entregar"))
    pending = sum(row.quantity - row.returned_quantity for row in doc.items)
    if pending:
        require(prop.name, "approve")
        if not str(data.get("shortage_note") or "").strip():
            frappe.throw(frappe._("Explique las prendas faltantes antes de entregar"))
    stay = _stay(prop, doc.stay)
    folio = _folio(prop, stay, doc.folio)
    total = money(0, currency=doc.currency)
    if not doc.complimentary:
        pms = provider() == "pms"
        if pms:
            from hospitality_suite.standalone_accounting import require_pms
            from hospitality_suite.standalone_tax import tax_for_amount
            require_pms(prop)
        else:
            ready(prop)
            from hospitality_suite.operations import charge
        for row in doc.items:
            if row.returned_quantity:
                amount = money(decimal(row.rate) * row.returned_quantity, currency=doc.currency)
                description = f"Lavandería {doc.name}: {row.garment} · {row.service_type}"
                if pms:
                    product = locked_doc("HS Product", row.pms_product)
                    if (product.property != prop.name or product.organization != prop.organization or
                            not product.active or product.product_type != "Service" or
                            not product.income_account or not product.tax_profile):
                        frappe.throw(frappe._("El servicio PMS de la prenda ya no está disponible"))
                    from hospitality_suite.standalone_accounting import account
                    income = account(prop, product.income_account)
                    if income.root_type != "Income" or income.account_currency != prop.currency:
                        frappe.throw(frappe._("La cuenta de ingreso de la prenda ya no es válida"))
                    tax_for_amount(prop, product.tax_profile, amount)
                    posted = insert("HS Charge", prop, stay=stay.name, folio=folio.name,
                        item=product.name, description=description, quantity=row.returned_quantity,
                        rate=str(row.rate), amount=str(amount), currency=prop.currency,
                        business_date=prop.business_date, kind="Service", status="Pending")
                else:
                    posted = charge(prop, stay, folio, row.item, amount, "Service",
                                    description,
                                    snapshot=dict(laundry_order=doc.name, laundry_rate=row.laundry_rate,
                                                  quoted_quantity=row.quantity, returned_quantity=row.returned_quantity,
                                                  rate=str(row.rate)), quantity=row.returned_quantity)
                row.charge = posted.name
                total += amount
    doc.status, doc.delivered_by, doc.delivered_at = "Delivered", frappe.session.user, now_datetime()
    doc.billed_total = total
    doc.shortage_note = str(data.get("shortage_note") or "").strip()[:500] if pending else None
    doc.save()
    audit(prop, "Laundry delivered", doc, doc.shortage_note, details=dict(billed_total=str(total), missing=pending))
    return dict(order=doc.name, status=doc.status, billed_total=str(total), missing=pending)


def cancel(prop, data):
    doc = locked_doc("HS Laundry Order", data.get("order"))
    from hospitality_suite.service import assert_version
    assert_version(doc, data.get("modified"))
    if doc.property != prop.name or doc.status not in OPEN:
        frappe.throw(frappe._("La orden de lavandería ya está cerrada"))
    reason = str(data.get("reason") or "").strip()
    if not reason:
        frappe.throw(frappe._("Indique el motivo de cancelación"))
    if doc.status != "Requested":
        require(prop.name, "approve")
    doc.status, doc.cancel_reason = "Cancelled", reason[:500]
    doc.save()
    audit(prop, "Laundry cancelled", doc, reason)
    return dict(order=doc.name, status=doc.status)


def board(prop):
    require(prop.name, "laundry")
    rates = frappe.get_all("HS Laundry Rate", filters={"property": prop.name},
                           fields=["name", "garment", "service_type", "item", "pms_product", "rate", "express_rate",
                                   "currency", "active", "modified"], order_by="garment,service_type", limit=1000)
    fields = [
        "name", "stay", "room", "folio", "currency", "status", "express", "complimentary", "notes",
        "total", "billed_total", "ready_by", "collected_at", "counted_at", "delivered_at", "shortage_note", "cancel_reason",
        "modified"]
    orders = frappe.get_all("HS Laundry Order", filters={"property": prop.name, "status": ["in", OPEN]},
                            fields=fields, order_by="modified desc", limit=2000)
    orders += frappe.get_all("HS Laundry Order", filters={"property": prop.name,
                            "status": ["in", ["Delivered", "Cancelled"]]},
                            fields=fields, order_by="modified desc", limit=25)
    for order in orders:
        order["items"] = frappe.get_all("HS Laundry Order Item", filters={"parent": order.name}, fields=[
            "name", "garment", "service_type", "item", "pms_product", "quantity", "returned_quantity", "rate", "amount", "charge"],
            order_by="idx asc", limit=100)
    stays = frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"},
                           fields=["name", "room", "booking"], limit=1000)
    folios = frappe.get_all("HS Folio", filters={"property": prop.name, "status": "Open"},
                           fields=["name", "stay", "booking", "label", "currency"], limit=1000)
    from hospitality_suite.standalone_accounting import provider
    products = (frappe.get_all("HS Product", filters={"property": prop.name,
        "organization": prop.organization, "product_type": "Service", "active": 1},
        fields=["name", "product_name", "income_account", "tax_profile"],
        order_by="product_name asc", limit=500) if provider() == "pms" else [])
    products = [row for row in products if row.income_account and row.tax_profile]
    cutoff = add_to_date(now_datetime(), days=-30)
    totals = frappe.db.sql("""SELECT COUNT(*) AS orders, COALESCE(SUM(billed_total),0) AS charges
        FROM `tabHS Laundry Order` WHERE property=%s AND status='Delivered' AND delivered_at >= %s""",
        (prop.name, cutoff), as_dict=True)[0]
    services = frappe.db.sql("""SELECT line.service_type,
        COALESCE(SUM(line.returned_quantity),0) AS pieces,
        COALESCE(SUM(CASE WHEN laundry.complimentary=0 THEN line.returned_quantity*line.rate ELSE 0 END),0) AS charges
        FROM `tabHS Laundry Order` laundry
        JOIN `tabHS Laundry Order Item` line ON line.parent=laundry.name
        WHERE laundry.property=%s AND laundry.status='Delivered' AND laundry.delivered_at >= %s
        GROUP BY line.service_type ORDER BY line.service_type""", (prop.name, cutoff), as_dict=True)
    return dict(rates=rates, orders=orders, stays=stays, folios=folios, products=products,
                last_30_days=dict(orders=totals.orders, charges=totals.charges,
                                  by_service=services, currency=prop.currency))
