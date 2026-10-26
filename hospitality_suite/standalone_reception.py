"""Property-scoped reception projections and standalone guest registration."""

import frappe
from frappe import _

from hospitality_suite.security import document, require
from hospitality_suite.service import assert_version, audit, insert
from hospitality_suite.standalone_accounting import provider, require_pms


def party(prop, name):
    row = frappe.db.get_value("HS Party", name,
        ["property", "organization", "party_type", "active"], as_dict=True)
    if (not row or row.property != prop.name or row.organization != prop.organization or
            not row.active or row.party_type not in ("Customer", "Both")):
        frappe.throw(_("Seleccione un pagador activo del establecimiento"), frappe.PermissionError)
    return row


def guest(prop, name):
    row = frappe.db.get_value("HS Guest", name,
        ["property", "company", "customer", "identity_number"], as_dict=True)
    if not row or row.property != prop.name or row.company != prop.company:
        frappe.throw(_("Seleccione un huésped del establecimiento"), frappe.PermissionError)
    if prop.guest_id_required and not row.identity_number:
        frappe.throw(_("La política requiere identificación del huésped principal"))
    return row


def _text(value, label, *, limit=140, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        frappe.throw(_("Revise {0}").format(label))
    value = value.strip()
    if len(value) > limit or (required and not value):
        frappe.throw(_("Indique {0} de hasta {1} caracteres").format(label, limit))
    return value


def create_guest(prop, data):
    require_pms(prop)
    require(prop.name, "guest")
    if not isinstance(data, dict) or set(data) - {"full_name", "party", "identity_type",
            "identity_number", "nationality", "email", "phone"}:
        frappe.throw(_("Revise los datos del huésped"))
    name = _text(data.get("full_name"), "el nombre del huésped", required=True)
    identity_type = _text(data.get("identity_type"), "el tipo de identificación")
    identity_number = _text(data.get("identity_number"), "la identificación")
    nationality = _text(data.get("nationality"), "la nacionalidad")
    email = _text(data.get("email"), "el correo")
    phone = _text(data.get("phone"), "el teléfono")
    if prop.guest_id_required and not identity_number:
        frappe.throw(_("Este establecimiento requiere identificación del huésped"))
    if email:
        from frappe.utils import validate_email_address
        if not validate_email_address(email):
            frappe.throw(_("Indique un correo válido"))
    payer = data.get("party")
    if payer:
        if not isinstance(payer, str):
            frappe.throw(_("Seleccione un pagador válido"))
        party(prop, payer)
    else:
        created = insert("HS Party", prop, organization=prop.organization,
            party_name=name, party_type="Customer", email=email or None,
            phone=phone or None, active=1)
        payer = created.name
        audit(prop, "pms_payer_created", created)
    doc = insert("HS Guest", prop, full_name=name, identity_type=identity_type or None,
        identity_number=identity_number or None, nationality=nationality or None,
        email=email or None, phone=phone or None, customer=payer)
    audit(prop, "pms_guest_created", doc, details={"party": payer})
    return {"guest": doc.name, "party": payer, "full_name": name}


GUEST_FIELDS = ("full_name", "email", "phone", "identity_type",
                "identity_number", "nationality")


def guest_detail(name):
    doc = document("HS Guest", name, "guest")
    prop = require(doc.property, "guest")
    require_pms(prop)
    return {"guest": doc.name, "customer": doc.customer,
        "customer_label": frappe.db.get_value("HS Party", {"name": doc.customer,
            "property": prop.name, "organization": prop.organization}, "party_name") or "",
        "property": prop.name, "modified": str(doc.modified),
        "guest_id_required": bool(prop.guest_id_required),
        "related_versions": {},
        "values": {field: doc.get(field) or "" for field in GUEST_FIELDS}}


def update_guest(prop, name, modified, data, reason, related_versions=None):
    require_pms(prop)
    require(prop.name, "guest")
    if (not isinstance(data, dict) or not data or set(data) - set(GUEST_FIELDS) or
            not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500):
        frappe.throw(_("Revise la corrección y su motivo"))
    doc = document("HS Guest", name, "guest")
    if doc.property != prop.name or doc.company != prop.company:
        frappe.throw(_("La ficha pertenece a otro establecimiento"), frappe.PermissionError)
    assert_version(doc, modified)
    cleaned = {field: _text(data.get(field, doc.get(field)), field,
        required=field == "full_name") for field in GUEST_FIELDS}
    if prop.guest_id_required and not cleaned["identity_number"]:
        frappe.throw(_("Este establecimiento requiere identificación del huésped"))
    if cleaned["email"]:
        from frappe.utils import validate_email_address
        if not validate_email_address(cleaned["email"]):
            frappe.throw(_("Indique un correo válido"))
    changed = [field for field in GUEST_FIELDS if (doc.get(field) or "") != cleaned[field]]
    if not changed:
        frappe.throw(_("No hay cambios en la ficha del huésped"))
    doc.update({field: cleaned[field] or None for field in GUEST_FIELDS})
    doc.save()
    audit(prop, "pms_guest_updated", doc, reason=reason.strip(),
        details={"fields": changed})
    return {"guest": doc.name, "customer": doc.customer,
        "modified": str(doc.modified), "related_versions": {}}


def pending_folio_charges(property_name, folio_name, offset=0, page_length=25):
    """Bounded source list for assigning unposted charges to a different folio."""
    prop = require(property_name, "stay")
    folio = document("HS Folio", folio_name, "stay")
    if folio.property != prop.name or folio.company != prop.company or folio.status != "Open":
        frappe.throw(_("Seleccione una cuenta de estancia abierta del establecimiento"), frappe.PermissionError)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("Revise la paginación de cargos"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(_("Revise la paginación de cargos"))
    where = ("property=%s AND company=%s AND folio=%s "
        "AND status IN ('Pending','Scheduled') "
        "AND (applies_to_charge IS NULL OR applies_to_charge='')")
    scope = [prop.name, prop.company, folio.name]
    total = frappe.db.sql("SELECT COUNT(*) FROM `tabHS Charge` WHERE " + where,
        scope, as_list=True)[0][0]
    rows = frappe.db.sql("SELECT name,stay,description,amount,currency,status,modified "
        "FROM `tabHS Charge` WHERE " + where +
        " ORDER BY creation DESC,name DESC LIMIT %s OFFSET %s",
        [*scope, page_length, offset], as_dict=True)
    return {"folio": folio.name, "total": int(total), "offset": offset,
        "has_more": offset + len(rows) < total, "rows": rows}


def charge_transfer_targets(property_name, charge_name):
    prop = require(property_name, "stay")
    charge = document("HS Charge", charge_name, "stay")
    if (charge.property != prop.name or charge.company != prop.company or
            charge.status not in ("Pending", "Scheduled") or charge.applies_to_charge):
        frappe.throw(_("Seleccione un cargo pendiente principal del establecimiento"),
            frappe.PermissionError)
    stay = frappe.db.get_value("HS Stay", {"name": charge.stay,
        "property": prop.name, "company": prop.company}, ["name", "booking"], as_dict=True)
    if not stay:
        frappe.throw(_("La estancia del cargo no pertenece al establecimiento"),
            frappe.PermissionError)
    rows = frappe.db.sql(
        "SELECT name,label,customer,stay,booking FROM `tabHS Folio` "
        "WHERE property=%s AND company=%s AND status='Open' AND name!=%s "
        "AND (stay=%s OR ((stay IS NULL OR stay='') AND booking=%s)) "
        "ORDER BY creation ASC,name ASC",
        (prop.name, prop.company, charge.folio, stay.name, stay.booking or ""), as_dict=True)
    return {"charge": charge.name, "source_folio": charge.folio, "targets": rows}


def snapshot(property_name, accounting_provider="pms"):
    prop = require(property_name, "reserve")
    if provider() != accounting_provider:
        frappe.throw(_("La recepción solicitada no corresponde al modo contable activo"))
    parties = frappe.get_all("HS Party", filters={"property": prop.name,
        "organization": prop.organization, "active": 1,
        "party_type": ["in", ["Customer", "Both"]]},
        fields=["name", "party_name"], order_by="party_name asc",
        limit_page_length=1000) if accounting_provider == "pms" else []
    if accounting_provider == "pms":
        require_pms(prop)
    guests = frappe.get_all("HS Guest", filters={"property": prop.name, "company": prop.company},
        fields=["name", "full_name", "customer"], order_by="modified desc",
        limit_page_length=1000)
    categories = frappe.get_all("HS Category", filters={"property": prop.name},
        fields=["name", "category_name", "capacity", "max_extra_beds"], order_by="category_name asc",
        limit_page_length=500)
    rooms = frappe.get_all("HS Room", filters={"property": prop.name, "active": 1},
        fields=["name", "room_number", "category", "cleaning_status"],
        order_by="room_number asc", limit_page_length=1000)
    rates = frappe.get_all("HS Rate", filters={"property": prop.name, "active": 1},
        fields=["name", "title", "category", "mode", "day_pass", "amount", "currency", "customer"],
        order_by="title asc", limit_page_length=1000)
    agents = frappe.get_all("HS Travel Agent", filters={"property": prop.name, "active": 1},
        fields=["name", "agent_name", "commission_pct"],
        order_by="agent_name asc", limit_page_length=500)
    experiences = frappe.get_all("HS Experience", filters={"property": prop.name, "active": 1},
        fields=["name", "experience_name", "pms_product"],
        order_by="experience_name asc", limit_page_length=500)
    bookings = frappe.get_all("HS Booking", filters={"property": prop.name,
        "status": ["in", ["Confirmed", "Checked In", "Hold"]]},
        fields=["name", "status", "customer", "guest", "starts_at", "ends_at",
                "currency", "amount", "travel_agent", "agent_commission_pct",
                "agent_commission_estimate", "modified", "quote_snapshot"],
        order_by="starts_at asc", limit_page_length=1000)
    if accounting_provider == "erpnext":
        # Only offer customers already linked to this property. Customer is
        # global in ERPNext, so listing it directly would leak other hotels.
        customers = {row.customer for row in guests if row.customer}
        customers.update(row.customer for row in bookings if row.customer)
        customers.update(row.customer for row in frappe.get_all(
            "HS Billing Party", filters={"property": prop.name, "company": prop.company},
            fields=["customer"], limit_page_length=1000) if row.customer)
        parties = [{"name": row.name, "party_name": row.customer_name}
            for row in frappe.get_all("Customer",
                filters={"name": ["in", sorted(customers)]},
                fields=["name", "customer_name"], order_by="customer_name asc",
                limit_page_length=1000)] if customers else []
    booking_names = [row.name for row in bookings]
    booking_lines = frappe.get_all("HS Booking Room", filters={"parent": ["in", booking_names],
        "parenttype": "HS Booking"}, fields=["parent", "category", "room", "people",
        "extra_beds", "rate", "idx"], order_by="parent asc,idx asc",
        limit_page_length=20000) if booking_names else []
    started_bookings = {row.booking for row in frappe.get_all("HS Stay",
        filters={"property": prop.name, "booking": ["in", booking_names]},
        fields=["booking"], limit_page_length=20000)} if booking_names else set()
    allocations = frappe.get_all("HS Allocation", filters={"property": prop.name,
        "kind": "Reservation", "status": "Active", "booking": ["in", booking_names]},
        fields=["name", "booking", "category", "room"], limit_page_length=1000) if booking_names else []
    stays = frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"},
        fields=["name", "booking", "guest", "customer", "room", "starts_at", "ends_at", "modified"],
        order_by="starts_at desc", limit_page_length=1000)
    folio_fields = ["name", "stay", "booking", "customer", "label"]
    stay_names = [row.name for row in stays]
    stay_bookings = list({row.booking for row in stays if row.booking})
    folios = frappe.get_all("HS Folio", filters={"property": prop.name, "status": "Open",
        "stay": ["in", stay_names]}, fields=folio_fields,
        order_by="creation asc", limit_page_length=1000) if stay_names else []
    if stay_bookings:
        names = {row.name for row in folios}
        folios.extend(row for row in frappe.get_all("HS Folio",
            filters={"property": prop.name, "status": "Open", "booking": ["in", stay_bookings]},
            fields=folio_fields, order_by="creation asc", limit_page_length=1000)
            if row.name not in names)
    from hospitality_suite.time import local
    for row in [*bookings, *stays]:
        row["starts_at_local"] = local(row.starts_at, prop).strftime("%Y-%m-%d %H:%M")
        row["ends_at_local"] = local(row.ends_at, prop).strftime("%Y-%m-%d %H:%M")
    for row in bookings:
        accepted = frappe.parse_json(row.pop("quote_snapshot") or "{}")
        first = (accepted.get("lines") or [{}])[0]
        row["mode"] = first.get("stay_type") or (
            "Day Pass" if first.get("rules", {}).get("day_pass")
            else first.get("rules", {}).get("mode") or prop.mode)
        row["modifiable"] = row.status in ("Hold", "Confirmed") and row.name not in started_bookings
    return {"property": prop.name, "currency": prop.currency, "mode": prop.mode,
        "portal_enabled": bool(prop.portal_enabled),
        "guest_id_required": bool(prop.guest_id_required),
        "parties": parties, "guests": guests, "categories": categories,
        "rooms": rooms, "rates": rates, "agents": agents,
        "experiences": experiences, "bookings": bookings,
        "allocations": allocations, "booking_lines": booking_lines,
        "stays": stays, "folios": folios}
