"""Authorized report dimensions and local date semantics, shared by all exports."""
from datetime import datetime, time, timedelta, date
from functools import cached_property

import frappe
from frappe.utils import get_datetime, getdate

from hospitality_suite.paging import permitted_all
from hospitality_suite.pricing import decimal
from hospitality_suite.security import allowed_properties, require
from hospitality_suite.time import to_site, local


ALIASES = {
    "Llegadas": "Reservas", "Salidas": "Estancias", "Huéspedes alojados": "Estancias",
    "Cancelaciones y no presentaciones": "Reservas", "Descuentos y cortesías": "Producción",
    "Anticipos y garantías": "Cobros",
    "Productividad de limpieza": "Limpieza", "Arqueos por moneda": "Turnos",
}
DATES = {
    "Reservas": [("starts_at", "Llegada prevista"), ("ends_at", "Salida prevista"), ("creation", "Registro")],
    "Estancias": [("actual_check_in", "Entrada real"), ("actual_check_out", "Salida real"), ("starts_at", "Llegada prevista"), ("ends_at", "Salida prevista"), ("creation", "Registro")],
    "Producción": [("business_date", "Fecha operativa"), ("creation", "Registro")],
    "Facturas": [("posting_date", "Fecha contable"), ("creation", "Registro")],
    "Cobros": [("creation","Registro"),("business_date","Fecha operativa")],
    "Liquidaciones": [("creation","Registro"),("business_date","Fecha operativa")],
    "Egresos": [("creation","Registro"),("business_date","Fecha operativa")],
    "Turnos": [("opened_at", "Apertura"), ("closed_at", "Cierre"), ("creation", "Registro")],
    "Limpieza": [("creation", "Registro"), ("started_at", "Inicio"), ("completed_at", "Finalización")],
    "Mantenimiento": [("starts_at", "Inicio previsto"), ("ends_at", "Fin previsto"), ("completed_at", "Finalización real"), ("creation", "Registro")],
    "Auditoría": [("occurred_at", "Momento")],
    "Movimientos de inventario": [("posting_date", "Fecha contable")],
    "Conciliación": [("source_date", "Fecha de origen (operativa / contable / registro)")],
}
DIMENSIONAL = {"Reservas", "Estancias", "Producción", "Facturas", "Cuentas pendientes", "Cobros", "Inventario", "Limpieza", "Mantenimiento"}
SHIFTED = {"Cobros", "Liquidaciones", "Egresos", "Facturas", "Turnos", "Conciliación"}


def metadata(report):
    from hospitality_suite.reports import REPORTS
    if report not in REPORTS:
        frappe.throw(frappe._("Reporte desconocido"))
    base = ALIASES.get(report, report)
    keys = ["user"] if base not in ("Disponibilidad", "Conciliación") else []
    if base in DIMENSIONAL or base == "Disponibilidad":
        keys += ["category", "room"]
    if base in DIMENSIONAL - {"Limpieza", "Mantenimiento"}:
        keys += ["channel"]
    if base in SHIFTED:
        keys += ["shift"]
    if base in {"Cobros", "Liquidaciones", "Egresos"}:
        keys += ["method", "kind"]
    if base == "Movimientos de inventario":
        keys += ["item", "warehouse", "purpose"]
    if base in {"Producción", "Inventario"}:
        keys += ["item"]
    if base == "Producción":
        keys += ["adjustment_type", "group_by"]
    if base in {"Limpieza", "Mantenimiento"}:
        keys += ["assigned_to"]
    if base not in {"Disponibilidad", "Movimientos de inventario"}:
        keys += ["status"]
    keys += ["detail_level"]
    dates = DATES.get(base, [("creation", "Registro")])
    if report == "Cancelaciones y no presentaciones":
        dates = [("status_changed_at", "Cancelación / no presentación"), *DATES["Reservas"]]
    default = "ends_at" if report == "Salidas" else dates[0][0]
    result=dict(base=base, filters=keys, date_fields=[dict(value=k, label=frappe._(v)) for k, v in dates], date_field=default,
                note=("Tareas por responsable. Duración de inicio a finalización, incluidas esperas de inspección. Tareas/hora usa solo finalizadas con duración positiva; no mide jornada laboral." if report == "Productividad de limpieza" else
                      "Arqueo separado por moneda original. Cerrado/revisión conserva conteo y esperado del cierre; abierto muestra esperado actual y conteo pendiente." if report == "Arqueos por moneda" else
                      "La fecha de cancelación/no presentación procede de auditoría. Penalización aceptada sin impuestos; consulte su factura y estado contable." if report == "Cancelaciones y no presentaciones" else
                      "Cupo simultáneo por categoría; las habitaciones candidatas son alternativas y no se suman al cupo. Limpieza actual se muestra por separado." if base == "Disponibilidad" else
                      "Ingreso neto facturado: importe sin impuestos. Las devoluciones se restan y los cargos pendientes se muestran sin ingreso facturado." if base == "Producción" else
                      "Los filtros seleccionan documentos completos; no prorratean facturas ni cuentas grupales."))
    result["note"]=frappe._(result["note"])
    return result


def scopes(property_name=None, company=None):
    if property_name:
        prop = require(property_name, "report")
        if company and prop.company != company:
            frappe.throw(frappe._("La compañía no corresponde al establecimiento"), frappe.PermissionError)
        return [prop]
    if not company:
        frappe.throw(frappe._("Seleccione una compañía o un establecimiento"))
    names = frappe.get_all("HS Property", filters={"name": ["in", allowed_properties()], "company": company}, pluck="name")
    if not names:
        frappe.throw(frappe._("No tiene establecimientos autorizados de esa compañía"), frappe.PermissionError)
    return [require(name, "report") for name in names]


def validate(filters, meta):
    allowed = set(meta["filters"]) | {"company", "from_date", "to_date", "date_field"}
    if meta["base"] == "Disponibilidad":
        allowed |= {"starts_at", "ends_at"}
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if key not in allowed or not isinstance(value, str):
            frappe.throw(frappe._("Filtro no aplicable a este reporte: ") + key)
    mode = filters.get("date_field") or meta["date_field"]
    if mode not in {r["value"] for r in meta["date_fields"]}:
        frappe.throw(frappe._("La fecha seleccionada no corresponde a este reporte"))
    bounds = []
    for key in ("from_date", "to_date"):
        try:
            value = filters.get(key)
            bounds.append(date.fromisoformat(value) if value else None)
        except (TypeError, ValueError):
            frappe.throw(frappe._("Indique fechas válidas en formato AAAA-MM-DD"))
    if all(bounds) and bounds[0] > bounds[1]:
        frappe.throw(frappe._("La fecha final debe ser igual o posterior a la inicial"))
    if filters.get("group_by") and filters["group_by"] not in {"room", "category", "item", "channel", "property"}:
        frappe.throw(frappe._("Agrupación de producción no admitida"))
    if filters.get("detail_level") and filters["detail_level"] not in {"operational","technical"}:
        frappe.throw(frappe._("Presentación de reporte no admitida"))
    return mode, bounds


def in_period(record, mode, bounds, prop):
    if not any(bounds):
        return True
    value = record.get(mode)
    if not value:
        return False
    if mode in ("business_date", "posting_date"):
        value = getdate(value)
        return (not bounds[0] or value >= bounds[0]) and (not bounds[1] or value <= bounds[1])
    value = get_datetime(value)
    start = to_site(datetime.combine(bounds[0], time()), prop) if bounds[0] else None
    end = to_site(datetime.combine(bounds[1]+timedelta(days=1), time()), prop) if bounds[1] else None
    return (not start or value >= start) and (not end or value < end)


def describe_filters(props, report, filters):
    from hospitality_suite.report_formatting import label,display
    meta=metadata(report)
    date_label=next(r["label"] for r in meta["date_fields"] if r["value"]==(filters.get("date_field") or meta["date_field"]))
    parts=[frappe._("Fecha: {0}").format(date_label)] if meta["base"]!="Disponibilidad" else []
    captions=dict(from_date="Desde",to_date="Hasta",starts_at="Inicio local",ends_at="Fin local",user="Registrado por",group_by="Agrupación",detail_level="Presentación")
    for key,value in filters.items():
        if not value or key in {"company","date_field"}:
            continue
        if key in {"room","category"}:
            dt,field=("HS Room","room_number") if key=="room" else ("HS Category","category_name")
            value=frappe.db.get_value(dt,{"name":value,"property":["in",[p.name for p in props]]},field) or value
        if key=="group_by":
            value=label(value)
        if key=="detail_level":
            value=frappe._("Referencias técnicas") if value=="technical" else frappe._("Vista operativa")
        parts.append((frappe._(captions[key]) if key in captions else label(key))+": "+str(display(key,value)))
    return " · ".join(parts) or frappe._("Sin filtros adicionales")


class Context:
    def __init__(self, prop):
        self.prop = prop

    def read(self, dt, fields):
        return permitted_all(dt, filters={"property": self.prop.name}, fields=fields)

    @cached_property
    def rooms(self):
        return {r.name: r for r in self.read("HS Room", ["name", "room_number", "category", "cleaning_status", "active"])}

    @cached_property
    def categories(self):
        return {r.name: r.category_name for r in self.read("HS Category", ["name", "category_name"])}

    @cached_property
    def bookings(self):
        return {r.name: r for r in self.read("HS Booking", ["name", "channel", "creation", "starts_at", "ends_at"])}

    @cached_property
    def booking_rooms(self):
        if not self.bookings:
            return []
        return frappe.get_all("HS Booking Room", filters={"parent": ["in", list(self.bookings)], "parenttype": "HS Booking"}, fields=["parent", "room", "category"])

    @cached_property
    def stays(self):
        return {r.name: r for r in self.read("HS Stay", ["name", "room", "booking", "creation"])}

    @cached_property
    def guests(self):
        return {r.name:r.full_name for r in self.read("HS Guest",["name","full_name"])}

    @cached_property
    def allocations(self):
        from hospitality_suite.service import current_all
        return current_all("HS Allocation", filters={"property": self.prop.name, "kind": "Stay"}, fields=["stay", "room", "category", "starts_at", "creation"])

    @cached_property
    def charges(self):
        return {r.name: r for r in self.read("HS Charge", ["name", "stay", "folio", "creation", "applies_to_charge", "sales_invoice", "invoice_item"])}

    @cached_property
    def folios(self):
        return {r.name: r for r in self.read("HS Folio", ["name", "stay", "booking"])}

    @cached_property
    def invoices(self):
        return {}

    def invoice(self, name):
        if name not in self.invoices:
            inv = frappe.get_doc("Sales Invoice", name)
            self.invoices[name] = inv if inv.hs_property == self.prop.name and inv.company == self.prop.company and inv.docstatus == 1 else None
        return self.invoices[name]

    def original_charge(self, source):
        if source.get("applies_to_charge"):
            return source.applies_to_charge
        inv = self.invoice(source.sales_invoice) if source.get("sales_invoice") else None
        if inv and inv.is_return:
            line = next((r for r in inv.items if r.name == source.get("invoice_item")), None)
            return frappe.db.get_value("Sales Invoice Item", line.sales_invoice_item, "hs_charge") if line and line.sales_invoice_item else None
        return None

    def net_revenue(self, source):
        if source.get("revenue_net") is not None:
            return source.revenue_net
        if source.status != "Invoiced" or not source.sales_invoice or not source.invoice_item:
            return None
        inv = self.invoice(source.sales_invoice)
        item = next((r for r in inv.items if r.name == source.invoice_item), None) if inv else None
        if not item:
            return None
        peers = [r for r in self.production_sources if r.sales_invoice == source.sales_invoice and r.invoice_item == source.invoice_item]
        denominator = sum(decimal(r.amount) for r in peers)
        return decimal(item.net_amount)*decimal(source.amount)/denominator if denominator else decimal(0)

    def dimensions(self, record, base, visited=None):
        record = frappe._dict(record)
        rooms, cats, channels = set(), set(), set()
        # Adjustments retain their original charge's attribution, not the room
        # occupied when an old invoice is later discounted or refunded.
        original = self.original_charge(record) if base == "Producción" else None
        if original:
            visited = set(visited or [])
            if original not in visited and original in self.charges:
                visited.add(original)
                return self.dimensions(self.charges[original], base, visited)
        stay = self.stays.get(record.get("hs_stay") or record.stay or (record.name if base == "Estancias" else None))
        folio = self.folios.get(record.get("hs_folio") or record.folio or (record.name if base == "Cuentas pendientes" else None))
        if not stay and folio:
            stay = self.stays.get(folio.stay)
        booking_name = record.get("hs_booking") or record.booking or (stay.booking if stay else None) or (folio.booking if folio else None) or (record.name if base == "Reservas" else None)
        booking = self.bookings.get(booking_name)
        if record.room:
            rooms.add(record.room)
        elif stay:
            if base == "Producción":
                segments = [r for r in self.allocations if r.stay == stay.name and get_datetime(r.creation) <= get_datetime(record.creation)]
                segment = max(segments, key=lambda r: (get_datetime(r.creation), get_datetime(r.starts_at))) if segments else None
                if segment:
                    rooms.add(segment.room)
                    cats.add(segment.category)
            else:
                rooms.add(stay.room)
        if booking:
            channels.add(booking.channel or "Recepción")
            if not stay and not record.room:
                for row in self.booking_rooms:
                    if row.parent == booking.name:
                        rooms.add(row.room)
                        cats.add(row.category)
        if folio and not folio.stay and base in ("Cuentas pendientes", "Facturas", "Cobros"):
            # A shared folio can contain charges from more than one room/category.
            for charge in self.charges.values():
                if charge.folio == folio.name:
                    a, b, c = self.dimensions(charge, "Producción")
                    rooms.update(a); cats.update(b); channels.update(c)
        rooms.discard(None); rooms.discard("")
        if not cats:
            cats.update(self.rooms[r].category for r in rooms if r in self.rooms)
        cats.discard(None)
        if base in ("Producción", "Inventario") and not stay and not booking and (record.get("direct_sale") or record.sales_invoice):
            channels.add("Venta directa")
        return rooms, cats, channels

    def decorate(self, row, source, base, filters):
        rooms, cats, channels = self.dimensions(source, base) if base in DIMENSIONAL else (set(), set(), set())
        for key, values in (("room", rooms), ("category", cats), ("channel", channels)):
            if filters.get(key) and filters[key] not in values:
                return None
            if base in DIMENSIONAL and (key != "channel" or base not in {"Limpieza", "Mantenimiento"}):
                row.setdefault(key, ", ".join(sorted(values)))
        hints = {}
        for key in list(row):
            if key == "room":
                hints[key] = ", ".join(sorted(self.rooms[r].room_number if r in self.rooms else r for r in rooms))
            elif key == "category":
                hints[key] = ", ".join(sorted(self.categories.get(c, c) for c in cats))
            elif key in {"creation", "starts_at", "ends_at", "actual_check_in", "actual_check_out", "opened_at", "closed_at", "started_at", "completed_at", "occurred_at"} and row[key]:
                hints[key] = local(row[key], self.prop).isoformat(sep=" ", timespec="seconds")
        if hints:
            row["_display"] = hints
        return row


def projected_rows(prop, report, filters):
    from hospitality_suite.reports import REPORTS, inventory_movements
    meta = metadata(report)
    mode, bounds = validate(filters, meta)
    base = meta["base"]
    if base == "Disponibilidad":
        return availability_rows(prop, filters)
    if base == "Conciliación":
        from hospitality_suite.reconciliation import rows
        return rows(prop, filters, limit=None)
    if base == "Movimientos de inventario":
        return [r for r in inventory_movements(prop, filters) if not filters.get("user") or r["actor"] == filters["user"]]
    dt, fields = REPORTS[base]
    requested = set(fields) | {"creation", "owner"} | {r["value"] for r in meta["date_fields"]}
    requested |= {"stay", "booking", "folio", "hs_booking", "hs_shift", "applies_to_charge", "cashier", "assigned_to", "kind", "status", "adjustment_type", "method", "quantity", "invoice_item", "guest", "fee_invoice", "fee_amount", "reason", "denominations"}
    requested = [k for k in sorted(requested) if k in {"name", "creation", "owner", "modified", "modified_by", "docstatus"} or frappe.get_meta(dt).has_field(k)]
    sources = permitted_all(dt, filters={"hs_property" if dt == "Sales Invoice" else "property": prop.name}, fields=requested)
    if base == "Producción" and report != "Descuentos y cortesías":
        sources += direct_sales(prop) + native_invoice_lines(prop)
        sources.sort(key=lambda r:(get_datetime(r.creation),r.name),reverse=True)
    context = Context(prop)
    context.production_sources = sources
    decisions = booking_decisions(prop) if report == "Cancelaciones y no presentaciones" else {}
    result = []
    kinds = {"Liquidaciones": ["Settlement"], "Egresos": ["Expense", "Supplier Payment", "Withdrawal"], "Cobros": ["Payment", "Advance", "Guarantee", "Refund", "Guarantee Refund", "Guarantee Applied"]}.get(base)
    for source in sources:
        source = frappe._dict(source)
        if report == "Cancelaciones y no presentaciones":
            decision = decisions.get((source.name, source.status))
            source.status_changed_at = decision.occurred_at if decision else None
        if base == "Mantenimiento" and mode == "completed_at":
            from hospitality_suite.housekeeping import maintenance_finished_at
            source.completed_at = maintenance_finished_at(frappe.get_doc(dt, source.name)) if source.status == "Completed" else None
        if not in_period(source, mode, bounds, prop):
            continue
        if kinds and source.kind not in kinds:
            continue
        if report == "Descuentos y cortesías" and source.adjustment_type not in ("Discount", "Courtesy"):
            continue
        if report == "Anticipos y garantías" and source.kind not in ("Advance", "Guarantee", "Guarantee Refund", "Guarantee Applied"):
            continue
        if report == "Huéspedes alojados" and source.status != "Active":
            continue
        if report == "Cancelaciones y no presentaciones" and source.status not in ("Cancelled", "No Show"):
            continue
        if report == "Llegadas" and source.status in ("Cancelled", "No Show", "Draft"):
            continue
        if base == "Producción" and not filters.get("status") and source.status in ("Reversed","Scheduled"):
            continue
        actor = source.actor or source.owner
        shift = source.name if base == "Turnos" else source.get("hs_shift") or source.shift
        matches = dict(user=actor, shift=shift, method=source.method, status=source.status, kind=source.kind, item=source.item, assigned_to=source.assigned_to, adjustment_type=source.adjustment_type)
        if any(filters.get(k) and filters[k] != v for k, v in matches.items()):
            continue
        row = frappe._dict({key: source.get(key) for key in fields})
        if base in {"Reservas","Estancias"}:
            row.guest=source.guest
        if report == "Cancelaciones y no presentaciones":
            row.update(status_changed_at=source.status_changed_at, reason=source.reason,
                       penalty_amount=source.fee_amount or 0, fee_invoice=source.fee_invoice)
            invoice = frappe.db.get_value("Sales Invoice", {"name":source.fee_invoice,"hs_property":prop.name,"company":prop.company}, "docstatus") if source.fee_invoice else None
            row.fee_status = {0:"Borrador",1:"Confirmada",2:"Anulada"}.get(invoice,"Sin penalización" if not source.fee_invoice else "Documento no disponible")
        if "user" in meta["filters"]:
            row.actor = actor
        if "base_amount" in row:
            row.base_currency=frappe.db.get_value("Company",prop.company,"default_currency")
        if base == "Cuentas pendientes":
            from hospitality_suite.accounting import folio_balance
            row.update(folio_balance(source.name))
            if decimal(row.outstanding) <= 0:
                continue
        if base == "Producción":
            row.adjustment_type = source.adjustment_type
            row.quantity = source.quantity
            row.revenue_net = context.net_revenue(source)
            inv=context.invoice(source.sales_invoice) if source.sales_invoice else None
            row.source_type = source.source_type or ("Nota de crédito" if inv and inv.is_return else "Cargo")
        if base == "Limpieza":
            row.duration_minutes = round((get_datetime(source.completed_at)-get_datetime(source.started_at)).total_seconds()/60, 2) if source.started_at and source.completed_at else None
        if base == "Mantenimiento" and mode == "completed_at":
            row.completed_at = source.completed_at
        decorated = context.decorate(row, source, base, filters)
        if decorated is not None:
            if report == "Arqueos por moneda":
                result.extend(shift_currency_rows(decorated,source))
            else:
                result.append(decorated)
    if base in {"Reservas","Estancias"}:
        for row in result:
            row.setdefault("_display",{})["guest"]=context.guests.get(row.guest,"")
    if report == "Huéspedes alojados" and result:
        members=frappe.get_all("HS Stay Guest",filters={"parent":["in",[r.name for r in result]],"parenttype":"HS Stay"},fields=["parent","guest","relationship"])
        expanded=[]
        for row in result:
            people=[r for r in members if r.parent==row.name] or [frappe._dict(guest=row.guest,relationship="Principal")]
            for member in people:
                item=frappe._dict(row.copy())
                item.update(guest=member.guest,relationship=member.relationship)
                item["_display"]={**row.get("_display",{}),"guest":context.guests.get(member.guest,"")}
                expanded.append(item)
        result=expanded
    if report == "Productividad de limpieza":
        return cleaning_productivity(result)
    return group_production(result,filters["group_by"],prop) if base == "Producción" and filters.get("group_by") else result


def shift_currency_rows(row, source):
    if source.status == "Open":
        from hospitality_suite.cashier import expected
        amounts=expected(frappe.get_doc("HS Shift",source.name))
        counts=None
    else:
        snapshot=frappe.parse_json(source.denominations or "{}")
        amounts=snapshot.get("expected") or {source.currency:source.expected_amount}
        counts=snapshot.get("counts")
    result=[]
    for currency in sorted(set(amounts)|set(counts or {})):
        item=frappe._dict(row.copy())
        counted=sum(decimal(r["value"])*int(r["count"]) for r in counts.get(currency,[])) if counts is not None else (decimal(source.counted_amount) if source.status!="Open" and currency==source.currency else None)
        amount=decimal(amounts.get(currency,0))
        item.update(currency=currency,expected_amount=amount,counted_amount=counted,difference=counted-amount if counted is not None else None)
        result.append(item)
    return result


def cleaning_productivity(records):
    groups={}
    for row in records:
        key=row.assigned_to or ""
        if key not in groups:
            groups[key]=frappe._dict(assigned_to=key,tasks=0,pending_tasks=0,completed_tasks=0,timed_tasks=0,duration_minutes=0,
                                    _display={"assigned_to":"Sin asignar"} if not key else {})
        group=groups[key]
        group.tasks+=1
        group.completed_tasks+=int(row.status=="Completed")
        group.pending_tasks+=int(row.status!="Completed")
        if row.status=="Completed" and row.duration_minutes is not None and row.duration_minutes>0:
            group.timed_tasks+=1
            group.duration_minutes+=row.duration_minutes
    for group in groups.values():
        group.average_minutes=round(group.duration_minutes/group.timed_tasks,2) if group.timed_tasks else 0
        group.tasks_per_recorded_hour=round(group.timed_tasks*60/group.duration_minutes,2) if group.duration_minutes else 0
        group.duration_minutes=round(group.duration_minutes,2)
    return [groups[key] for key in sorted(groups)]


def group_production(records, dimension, prop):
    """Never add currencies together or count one source in multiple groups."""
    groups = {}
    for row in records:
        value = prop.name if dimension == "property" else row.get(dimension) or ""
        key = (value, row.currency)
        if key not in groups:
            hint = prop.property_name if dimension == "property" else row.get("_display",{}).get(dimension, value)
            groups[key] = frappe._dict({dimension:value,"currency":row.currency,"amount":decimal(0),"revenue_net":decimal(0),"pending_amount":decimal(0),"records":0,
                                       "_display":{dimension:hint or {"room":"Sin habitación","category":"Sin categoría","channel":"Sin canal"}.get(dimension,"Sin atribución")}})
        total = groups[key]
        total.amount += decimal(row.amount)
        total.revenue_net += decimal(row.revenue_net) if row.revenue_net is not None else decimal(0)
        total.pending_amount += decimal(row.amount) if row.status == "Pending" else decimal(0)
        total.records += 1
    return sorted(groups.values(),key=lambda row:(row["_display"][dimension].casefold(),row.currency))


def direct_sales(prop):
    """Counter sales have no HS Charge: include each sale and actual return once.

    Use native line totals and separate net revenue, as with stay charges.
    Return operational dates come from their own immutable event.
    """
    from hospitality_suite.service import current_all
    events = {(r.source_name, r.action): r for r in current_all("HS Audit Event", filters={"property": prop.name, "source_doctype": "HS Service Request", "action": ["in", ["Direct sale", "Return direct sale"]]}, fields=["source_name", "action", "business_date", "occurred_at", "actor"])}
    services = permitted_all("HS Service Request", filters={"property": prop.name, "stay": ["is", "not set"], "sales_invoice": ["is", "set"]}, fields=["name", "item", "quantity", "amount", "currency", "status", "sales_invoice", "credit_note", "creation", "owner"])
    result = []
    for service in services:
        for returning, invoice, action in ((False, service.sales_invoice, "Direct sale"), (True, service.credit_note, "Return direct sale")):
            if not invoice:
                continue
            native = frappe.db.get_value("Sales Invoice", {"name": invoice, "hs_property": prop.name, "company": prop.company}, ["docstatus", "total", "net_total", "currency"], as_dict=True)
            if not native or native.docstatus != 1:
                continue
            event = events.get((service.name, action))
            if returning and not event:
                continue  # Do not invent a historical operational date.
            stamp = event.occurred_at if event else service.creation
            result.append(frappe._dict(name=service.name+(":return" if returning else ""), stay=None, folio=None, direct_sale=True,
                                      item=service.item, quantity=-service.quantity if returning else service.quantity,
                                      amount=native.total, revenue_net=native.net_total, source_type="Devolución de venta directa" if returning else "Venta directa", currency=native.currency, status="Invoiced", kind="Service", sales_invoice=invoice,
                                      business_date=event.business_date if event else local(stamp, prop).date(), creation=stamp, owner=event.actor if event else service.owner))
    return result


def booking_decisions(prop):
    events = permitted_all("HS Audit Event", filters={"property":prop.name,"source_doctype":"HS Booking","action":["in",["Cancelled","No Show","Hold expired"]]},
                           fields=["source_name","action","occurred_at"], order_by="occurred_at asc,name asc")
    return {(r.source_name,"Cancelled" if r.action=="Hold expired" else r.action):r for r in events}


def native_invoice_lines(prop):
    """Include submitted native lines absent from charges and counter sales.

    Cancellation/no-show fees have a booking but no stay/folio. Native counter
    invoices may have neither. Read their actual amounts, including returns;
    never create another accounting document or count a represented line twice.
    """
    invoices = {r.name:r for r in permitted_all("Sales Invoice", filters={"hs_property":prop.name,"company":prop.company,"docstatus":1},
                fields=["name","creation","owner","posting_date","currency","hs_booking","hs_stay","hs_folio","is_return","return_against"])}
    if not invoices:
        return []
    services = permitted_all("HS Service Request", filters={"property":prop.name,"stay":["is","not set"]}, fields=["sales_invoice","credit_note"])
    represented_invoices = {n for r in services for n in (r.sales_invoice,r.credit_note) if n}
    represented_lines = {(r.sales_invoice,r.invoice_item) for r in permitted_all("HS Charge",filters={"property":prop.name},fields=["sales_invoice","invoice_item"])}
    events = permitted_all("HS Audit Event", filters={"property":prop.name,"source_doctype":"Sales Invoice","action":"on_submit"},
                           fields=["source_name","business_date","occurred_at","actor"],order_by="occurred_at asc,name asc")
    submissions = {r.source_name:r for r in events}
    penalties = {r.fee_invoice:r for r in permitted_all("HS Booking",filters={"property":prop.name,"fee_invoice":["is","set"]},fields=["name","fee_invoice","status"])}
    items = frappe.get_all("Sales Invoice Item", filters={"parent":["in",list(invoices)],"parenttype":"Sales Invoice"},
                           fields=["name","parent","item_code","qty","amount","net_amount","hs_charge"])
    result=[]
    for item in items:
        inv=invoices[item.parent]
        if inv.name in represented_invoices or item.hs_charge or (inv.name,item.name) in represented_lines:
            continue
        original=invoices.get(inv.return_against) if inv.is_return else None
        penalty=penalties.get(inv.return_against if inv.is_return else inv.name)
        event=submissions.get(inv.name)
        kind=("Penalización por no presentación" if penalty.status=="No Show" else "Penalización por cancelación") if penalty else "Factura de venta ERPNext"
        result.append(frappe._dict(name=inv.name+":"+item.name, hs_booking=inv.hs_booking or (original.hs_booking if original else None),
                                  stay=inv.hs_stay,folio=inv.hs_folio,item=item.item_code,quantity=item.qty,amount=item.amount,revenue_net=item.net_amount,
                                  currency=inv.currency,status="Invoiced",kind="Service",sales_invoice=inv.name,invoice_item=item.name,
                                  source_type=("Devolución · " if inv.is_return else "")+kind,
                                  business_date=event.business_date if event else inv.posting_date,
                                  creation=event.occurred_at if event else inv.creation, owner=event.actor if event else inv.owner))
    return result


def availability_rows(prop, filters):
    from hospitality_suite.availability import capacity
    from hospitality_suite.report_formatting import display
    start = to_site(filters.get("starts_at") or (filters.get("from_date") or str(prop.business_date))+" 00:00:00", prop)
    end = to_site(filters.get("ends_at") or str(getdate(filters.get("to_date") or filters.get("from_date") or prop.business_date)+timedelta(days=1))+" 00:00:00", prop)
    if end <= start:
        frappe.throw(frappe._("Seleccione un intervalo de disponibilidad positivo"))
    ctx = Context(prop)
    categories = ctx.categories
    result = []
    for name, title in sorted(categories.items(), key=lambda r: r[1]):
        if filters.get("category") and filters["category"] != name:
            continue
        if filters.get("room") and (filters["room"] not in ctx.rooms or ctx.rooms[filters["room"]].category != name):
            continue
        stock = capacity(prop, name, start, end)
        candidates = stock["candidates"] if stock["available"] else []
        result.append(frappe._dict(category=name, **(dict(room=filters["room"],selected_room_available=filters["room"] in candidates,cleaning_status=ctx.rooms[filters["room"]].cleaning_status) if filters.get("room") else {}),
                                  total_rooms=len(stock["rooms"]), available_capacity=stock["available"],
                                  candidate_rooms=", ".join(sorted(ctx.rooms[r].room_number for r in candidates)),
                                  clean_candidates=sum(r.cleaning_status == "Clean" and r.name in candidates for r in stock["rooms"]),
                                  starts_at=start, ends_at=end,
                                  _display=dict(category=title, room=ctx.rooms[filters["room"]].room_number if filters.get("room") else "",
                                                cleaning_status=display("cleaning_status",ctx.rooms[filters["room"]].cleaning_status) if filters.get("room") else "",
                                                starts_at=local(start, prop).isoformat(), ends_at=local(end, prop).isoformat())))
    return result
