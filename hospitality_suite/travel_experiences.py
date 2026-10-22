"""Property-scoped agency attribution and bookable experiences."""

from decimal import Decimal
import hashlib
import re

import frappe
from frappe.utils import nowdate

from hospitality_suite.accounting import post_standard, ready
from hospitality_suite.item_configuration import selling_price
from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import assert_version, audit, canonical, current_all, insert, locked_doc


def _count(value, label):
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        frappe.throw(frappe._("Indique {0} válido").format(label))
    if not number.is_finite() or number != int(number) or not 1 <= number <= 1000:
        frappe.throw(frappe._("Indique {0} entre 1 y 1000").format(label))
    return int(number)


def _percent(value):
    try:
        number = decimal(value or 0)
    except (ValueError, TypeError, ArithmeticError):
        frappe.throw(frappe._("La comisión debe estar entre 0 y 100 %"))
    if not number.is_finite() or number < 0 or number > 100:
        frappe.throw(frappe._("La comisión debe estar entre 0 y 100 %"))
    return number


def agent(prop, name, *, active=True, action="reserve"):
    if not name:
        return None
    doc = document("HS Travel Agent", name, action)
    if doc.property != prop.name or doc.company != prop.company or (active and not doc.active):
        frappe.throw(frappe._("Seleccione una agencia activa del establecimiento"))
    return doc


def attribution(prop, name, amount, previous=None):
    doc = agent(prop, name)
    if not doc:
        return dict(travel_agent=None, agent_commission_pct=0, agent_commission_estimate=0)
    pct = _percent(previous if previous is not None else doc.commission_pct)
    return dict(travel_agent=doc.name, agent_commission_pct=float(pct),
                agent_commission_estimate=money(decimal(amount) * pct / 100, currency=prop.currency))


def save_agent(prop, data):
    require(prop.name, "setup")
    name = str(data.get("agent_name") or "").strip()
    if not name or len(name) > 140:
        frappe.throw(frappe._("Indique el nombre de la agencia"))
    kind = data.get("agent_type") or "Travel Agent"
    if kind not in ("Travel Agent", "OTA", "Tour Operator", "Corporate Desk"):
        frappe.throw(frappe._("Seleccione un tipo de agencia válido"))
    pct = _percent(data.get("commission_pct"))
    supplier = data.get("supplier") or None
    if supplier:
        vendor = locked_doc("Supplier", supplier)
        if vendor.disabled or not current_all("HS Supplier", {"property": prop.name, "company": prop.company,
                                                              "supplier": vendor.name, "active": 1}):
            frappe.throw(frappe._("Registre primero el proveedor activo en este establecimiento"))
    values = dict(agent_name=name, agent_type=kind, commission_pct=float(pct), supplier=supplier,
                  contact_name=str(data.get("contact_name") or "")[:140],
                  contact_phone=str(data.get("contact_phone") or "")[:140],
                  contact_email=str(data.get("contact_email") or "")[:140],
                  active=int(data.get("active", 1) in (True, 1, "1")))
    if data.get("agent"):
        doc = document("HS Travel Agent", data["agent"], "setup")
        assert_version(doc, data.get("modified"))
        doc.update(values)
        doc.save()
    else:
        doc = insert("HS Travel Agent", prop, **values)
    audit(prop, "Save travel agent", doc)
    return dict(agent=doc.name, modified=str(doc.modified))


def save_experience(prop, data):
    require(prop.name, "setup")
    name = str(data.get("experience_name") or "").strip()
    if not name or len(name) > 140:
        frappe.throw(frappe._("Indique el nombre de la experiencia"))
    category = data.get("experience_category") or "Other"
    if category not in ("Spa", "Tour", "Dining", "Activity", "Transport", "Other"):
        frappe.throw(frappe._("Seleccione una categoría válida"))
    item = locked_doc("Item", data.get("item"))
    if item.disabled or not item.is_sales_item or item.is_stock_item or item.is_fixed_asset:
        frappe.throw(frappe._("La experiencia requiere un artículo de venta sin inventario"))
    selling_price(prop, item.name, prop.currency)
    image_url=str(data.get("image_url") or "")
    if image_url and (not re.fullmatch(r"/files/[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.(?:png|jpg|jpeg|webp|gif)",image_url,re.I)
                      or not frappe.db.exists("File",{"file_url":image_url,"is_private":0})):
        frappe.throw(frappe._("Seleccione una imagen pública existente en /files/"))
    values = dict(experience_name=name, experience_category=category, item=item.name,
                  duration=str(data.get("duration") or "")[:140],
                  description=str(data.get("description") or "")[:500],
                  image_url=image_url,
                  show_on_booking_page=int(data.get("show_on_booking_page") in (True, 1, "1")),
                  active=int(data.get("active", 1) in (True, 1, "1")))
    if data.get("experience"):
        doc = document("HS Experience", data["experience"], "setup")
        assert_version(doc, data.get("modified"))
        doc.update(values)
        doc.save()
    else:
        doc = insert("HS Experience", prop, **values)
    audit(prop, "Save experience", doc)
    return dict(experience=doc.name, modified=str(doc.modified))


def quote_experiences(prop, rows, customer=None, *, public=False):
    if rows in (None, ""):
        return []
    if not isinstance(rows, list) or len(rows) > 20 or any(not isinstance(row, dict) for row in rows):
        frappe.throw(frappe._("Revise las experiencias seleccionadas"))
    quoted, seen = [], set()
    for row in rows:
        name = row.get("experience")
        if name in seen:
            frappe.throw(frappe._("Seleccione cada experiencia una sola vez"))
        seen.add(name)
        exp = locked_doc("HS Experience", name)
        if (exp.property != prop.name or exp.company != prop.company or not exp.active
                or (public and not exp.show_on_booking_page)):
            frappe.throw(frappe._("La experiencia no está disponible en este establecimiento"))
        quantity = _count(row.get("quantity"), frappe._("una cantidad"))
        item = locked_doc("Item", exp.item)
        if item.disabled or not item.is_sales_item or item.is_stock_item:
            frappe.throw(frappe._("El artículo de la experiencia no está habilitado"))
        price = selling_price(prop, item.name, prop.currency, customer)
        rate = money(price.price_list_rate, currency=prop.currency)
        quoted.append(dict(experience=exp.name, name=exp.experience_name, item=item.name,
                           item_price=price.name, quantity=quantity, rate=str(rate),
                           amount=str(money(rate * quantity, currency=prop.currency))))
    return quoted


def book_experiences(prop, booking, quoted):
    created=[]
    for row in quoted:
        order = insert("HS Experience Order", prop, experience=row["experience"], booking=booking.name,
                       customer=booking.customer, item=row["item"], quantity=row["quantity"],
                       participants=row["quantity"], unit_rate=row["rate"], amount=row["amount"],
                       currency=prop.currency, status="Reserved")
        audit(prop, "Book experience", order, details=dict(item_price=row["item_price"]))
        created.append(order.name)
    return created


def order_quote(prop, data):
    booking = document("HS Booking", data["booking"], "reserve")
    if booking.status not in ("Confirmed", "Checked In"):
        frappe.throw(frappe._("Seleccione una reserva confirmada o una estancia activa"))
    quoted = quote_experiences(prop, [{"experience": data.get("experience"),
                                       "quantity": data.get("quantity")}], booking.customer)
    result=dict(booking=booking.name,modified=str(booking.modified),line=quoted[0],currency=prop.currency)
    result["acceptance"]=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def order_experience(prop, data):
    """Reception may also book an accepted experience after the room reservation."""
    q=order_quote(prop,data)
    if data.get("acceptance")!=q["acceptance"]:
        frappe.throw(frappe._("Revise y acepte el precio vigente de la experiencia"))
    booking=document("HS Booking",q["booking"],"reserve")
    return dict(order=book_experiences(prop, booking, [q["line"]])[0])


def update_order(prop, data):
    doc = document("HS Experience Order", data["order"], "service")
    assert_version(doc, data.get("modified"))
    target = data.get("status")
    if target not in {"Reserved": ("Confirmed", "Cancelled"),
                      "Confirmed": ("Delivered", "Cancelled")}.get(doc.status, ()):
        frappe.throw(frappe._("Transición de experiencia inválida"))
    if target == "Cancelled":
        note = str(data.get("reason") or "").strip()
        if not note:
            frappe.throw(frappe._("Indique el motivo de cancelación"))
        doc.cancel_reason = note[:500]
    if target == "Confirmed":
        from hospitality_suite.time import to_site
        date = data.get("scheduled_at")
        if not date:
            frappe.throw(frappe._("Indique la fecha y hora de la experiencia"))
        doc.scheduled_at = to_site(date, prop)
        doc.participants = _count(data.get("participants") or doc.quantity, frappe._("participantes"))
        doc.notes = str(data.get("notes") or "")[:500]
    if target == "Delivered":
        from hospitality_suite.operations import charge
        stay_name = data.get("stay")
        if not stay_name:
            active = current_all("HS Stay", {"property": prop.name, "booking": doc.booking,
                                             "status": "Active"}, pluck="name")
            if len(active) != 1:
                frappe.throw(frappe._("Seleccione la estancia que recibe la experiencia"))
            stay_name = active[0]
        stay = document("HS Stay", stay_name, "service")
        if stay.booking != doc.booking or stay.status != "Active":
            frappe.throw(frappe._("La estancia no corresponde a la reserva o ya terminó"))
        folio_name = data.get("folio")
        if not folio_name:
            folios = current_all("HS Folio", {"property": prop.name, "stay": stay.name,
                                              "status": "Open"}, pluck="name")
            if len(folios) != 1:
                frappe.throw(frappe._("Seleccione la cuenta que recibe el cargo"))
            folio_name = folios[0]
        folio = document("HS Folio", folio_name, "service")
        if folio.status != "Open" or not (folio.stay == stay.name or folio.booking == doc.booking):
            frappe.throw(frappe._("La cuenta no corresponde a la estancia o está cerrada"))
        if folio.currency != doc.currency or folio.customer != doc.customer:
            frappe.throw(frappe._("Revise pagador y moneda antes de cargar la experiencia"))
        entry = charge(prop, stay, folio, doc.item, doc.amount, "Service",
                       frappe.db.get_value("HS Experience", doc.experience, "experience_name"),
                       snapshot=dict(experience=doc.experience, unit_rate=str(doc.unit_rate)),
                       quantity=doc.quantity)
        doc.stay, doc.folio, doc.charge = stay.name, folio.name, entry.name
    doc.status = target
    doc.save()
    audit(prop, "Experience " + target, doc, data.get("reason"))
    return dict(order=doc.name, status=doc.status, charge=doc.charge, modified=str(doc.modified))


def commission_quote(prop, data):
    require(prop.name, "commission")
    booking = document("HS Booking", data["booking"], "commission")
    if not booking.travel_agent or booking.status != "Completed" or booking.agent_commission_invoice:
        frappe.throw(frappe._("La reserva no tiene una comisión pendiente de liquidar"))
    agent_doc = agent(prop, booking.travel_agent, active=False, action="commission")
    if not agent_doc.supplier or not current_all("HS Supplier", {"property": prop.name,
            "supplier": agent_doc.supplier, "active": 1}):
        frappe.throw(frappe._("Vincule la agencia a un proveedor activo del establecimiento"))
    if not prop.agent_commission_item or not prop.expense_account:
        frappe.throw(frappe._("Configure artículo y cuenta de gasto para comisiones"))
    expense_account=locked_doc("Account",prop.expense_account)
    if expense_account.company!=prop.company or expense_account.root_type!="Expense" or expense_account.is_group:
        frappe.throw(frappe._("La cuenta de comisión debe ser un gasto imputable de la compañía"))
    item = locked_doc("Item", prop.agent_commission_item)
    if item.disabled or item.is_stock_item or not item.is_purchase_item:
        frappe.throw(frappe._("El artículo de comisión debe ser comprable y sin inventario"))
    stays = current_all("HS Stay", {"property": prop.name, "booking": booking.name}, pluck="name")
    if not stays or current_all("HS Stay", {"property": prop.name, "booking": booking.name,
                                "status": "Active"}, pluck="name"):
        frappe.throw(frappe._("Todas las estancias deben estar finalizadas"))
    charges = current_all("HS Charge", {"property": prop.name, "stay": ["in", stays]},
                          fields=["name", "kind", "amount", "status", "applies_to_charge", "sales_invoice"])
    lodging = {row.name for row in charges if row.kind == "Lodging" and not row.applies_to_charge}
    relevant = [row for row in charges if row.name in lodging or row.applies_to_charge in lodging]
    if not relevant or any(row.status != "Invoiced" or not row.sales_invoice or
                           frappe.db.get_value("Sales Invoice", row.sales_invoice, "docstatus") != 1 for row in relevant):
        frappe.throw(frappe._("Facture todos los cargos de alojamiento antes de liquidar la comisión"))
    source_invoices={row.sales_invoice for row in relevant}
    if frappe.db.exists("Sales Invoice", {"return_against": ["in", list(source_invoices)], "docstatus": 1}):
        frappe.throw(frappe._("Revise las notas de crédito del alojamiento antes de liquidar la comisión en ERPNext"))
    base = money(sum(decimal(row.amount) for row in relevant), currency=prop.currency)
    if base <= 0:
        frappe.throw(frappe._("No hay alojamiento facturado con base positiva"))
    amount = money(base * _percent(booking.agent_commission_pct) / 100, currency=prop.currency)
    if amount <= 0:
        frappe.throw(frappe._("La comisión acordada no genera importe a pagar"))
    return dict(booking=booking.name, modified=str(booking.modified), agent=agent_doc.name,
                supplier=agent_doc.supplier, item=item.name, expense_account=prop.expense_account,
                base=str(base), percent=str(booking.agent_commission_pct), amount=str(amount), currency=prop.currency)


def settle_commission(prop, data):
    require(prop.name, "commission")
    ready(prop)
    q = commission_quote(prop, data)
    booking = document("HS Booking", q["booking"], "commission")
    assert_version(booking, data.get("modified"))
    inv = frappe.new_doc("Purchase Invoice")
    inv.update(dict(company=prop.company, supplier=q["supplier"], posting_date=nowdate(),
                    due_date=nowdate(), currency=prop.currency, cost_center=prop.cost_center,
                    update_stock=0, remarks=f"Comisión de agencia · {booking.name}"))
    inv.append("items", dict(item_code=q["item"], qty=1, rate=float(decimal(q["amount"])),
                              expense_account=q["expense_account"], cost_center=prop.cost_center,
                              description=f"{q['agent']} · {booking.name} · {q['percent']} % sobre {q['base']}"))
    inv.set_missing_values()
    inv.calculate_taxes_and_totals()
    post_standard(inv, prop)
    booking.agent_commission_invoice = inv.name
    booking.save()
    audit(prop, "Settle agent commission", booking, details=dict(purchase_invoice=inv.name, **q))
    return dict(booking=booking.name, invoice=inv.name, amount=q["amount"], currency=q["currency"])


def board(prop):
    require(prop.name)
    agents = frappe.get_all("HS Travel Agent", filters={"property": prop.name, "company": prop.company},
                            fields=["name", "agent_name", "agent_type", "contact_name", "contact_phone",
                                    "contact_email", "commission_pct", "supplier", "active", "modified"], limit=500)
    experiences = frappe.get_all("HS Experience", filters={"property": prop.name, "company": prop.company},
                                 fields=["name", "experience_name", "experience_category", "item", "duration",
                                         "description", "image_url", "show_on_booking_page", "active", "modified"], limit=500)
    orders = frappe.get_all("HS Experience Order", filters={"property": prop.name, "company": prop.company},
                            fields=["name", "experience", "booking", "stay", "folio", "customer", "quantity",
                                    "participants", "scheduled_at", "unit_rate", "amount", "currency", "status",
                                    "charge", "notes", "cancel_reason", "modified"], limit=500, order_by="creation desc")
    contribution=frappe.db.sql("""SELECT travel_agent, COUNT(*) AS bookings,
        COALESCE(SUM(amount),0) AS accepted_lodging,
        COALESCE(SUM(agent_commission_estimate),0) AS estimated_commission
        FROM `tabHS Booking` WHERE property=%s AND company=%s AND travel_agent IS NOT NULL
        AND status IN ('Confirmed','Checked In','Completed') GROUP BY travel_agent""",
        (prop.name,prop.company),as_dict=True)
    order_totals=frappe.db.sql("""SELECT status, COUNT(*) AS orders,
        COALESCE(SUM(amount),0) AS amount FROM `tabHS Experience Order`
        WHERE property=%s AND company=%s GROUP BY status""",(prop.name,prop.company),as_dict=True)
    return dict(agents=agents, experiences=experiences, orders=orders,
                contribution=contribution, order_totals=order_totals)
