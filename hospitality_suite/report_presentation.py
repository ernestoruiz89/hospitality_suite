"""Human descriptions for operators; original document keys remain in the API."""
from functools import cached_property

import frappe

from hospitality_suite.paging import permitted_all
from hospitality_suite.time import local


PROFILES={
    "Cancelaciones y no presentaciones":["status_changed_at","starts_at","guest","room","status","reason","penalty_amount","fee_status","fee_invoice","currency"],
    "Producción":["business_date","room","item","quantity","amount","currency","status","revenue_net"],
    "Reservas":["starts_at","ends_at","guest","customer","room","category","status","channel","amount","currency"],
    "Estancias":["room","guest","relationship","actual_check_in","ends_at","actual_check_out","status","customer"],
    "Historial de estancias":["room","actual_check_in","actual_check_out","starts_at","ends_at","status","relationship"],
    "Cuentas pendientes":["account_label","room","customer","pending","outstanding","currency","status"],
    "Facturas":["invoice_number","customer","posting_date","grand_total","outstanding_amount","currency","docstatus","is_return"],
    "Cobros":["business_date","recorded_at","method","kind","amount","currency","status","stay","booking"],
    "Liquidaciones":["business_date","recorded_at","method","settlement_direction","amount","fee_amount","withholding_amount","net_amount","currency","status"],
    "Egresos":["business_date","recorded_at","kind","expense_category","supplier","amount","currency","status","reason"],
    "Turnos":["cashier","opened_at","closed_at","status","currency","expected_amount","counted_amount","difference"],
    "Limpieza":["room","kind","assigned_to","started_at","completed_at","duration_minutes","status"],
    "Productividad de limpieza":["assigned_to","tasks","pending_tasks","completed_tasks","timed_tasks","duration_minutes","average_minutes","tasks_per_recorded_hour"],
    "Mantenimiento":["room","equipment","title","status","starts_at","ends_at","cost","blocks_room"],
    "Inventario":["room","item","quantity","amount","currency","status"],
    "Movimientos de inventario":["posting_date","item","warehouse","purpose","classification","quantity","cost","currency","cost_center"],
    "Auditoría":["occurred_at","action","actor","source_doctype","source_name","reason"],
    "Conciliación":["type","source","erp_document","expected","actual","difference","currency","status","detail"],
}
DATES={"starts_at","ends_at","actual_check_in","actual_check_out","opened_at","closed_at","started_at","completed_at","occurred_at","recorded_at","status_changed_at"}
TITLES={"HS Booking":"Reserva","HS Stay":"Estancia","HS Folio":"Cuenta","HS Charge":"Cargo","HS Payment":"Movimiento de caja",
        "HS Service Request":"Consumo","HS Shift":"Turno","HS Cleaning Task":"Limpieza","HS Maintenance Order":"Mantenimiento",
        "HS Daily Close":"Cierre diario","HS Guest":"Huésped","HS Rate":"Tarifa","HS Room":"Habitación","HS Category":"Categoría",
        "HS Property":"Establecimiento","HS Incident":"Incidencia","HS Equipment":"Equipo","HS Portal Request":"Solicitud web",
        "HS Retention Run":"Retención de datos","Sales Invoice":"Factura de venta","Payment Entry":"Comprobante de pago",
        "Journal Entry":"Asiento contable","Stock Entry":"Movimiento de inventario","Purchase Order":"Orden de compra",
        "Purchase Receipt":"Recepción de compra","Purchase Invoice":"Factura de proveedor","Stock Reconciliation":"Conteo de inventario"}
TITLES.update({"User":"Usuario","File":"Archivo privado","HS Payment Method":"Medio de pago","HS Stock Policy":"Política de inventario","HS Expense Category":"Categoría de gasto","HS Supplier":"Proveedor autorizado"})
ACTIONS={
    "Room changed":"Datos de habitación actualizados","Setup room":"Habitación registrada",
    "Create property":"Establecimiento creado",
    "Reserve":"Reserva creada","Modify reservation":"Reserva modificada","Check in":"Entrada registrada","Check out":"Salida registrada",
    "Extend":"Estancia extendida","Change room":"Cambio de habitación","Create folio":"Cuenta creada","Move charge":"Cargo trasladado de cuenta",
    "Invoice":"Factura emitida","Credit note":"Nota de crédito emitida","Reconcile advances":"Anticipos conciliados","Apply guarantee":"Garantía aplicada",
    "Open shift":"Turno abierto","Close shift":"Turno cerrado","Cash withdrawal":"Retiro de caja","Cash expense":"Egreso de caja",
    "Card settlement":"Liquidación de tarjeta","Direct sale":"Venta directa","Return direct sale":"Devolución de venta directa",
    "Register guest":"Huésped registrado","Update companions":"Acompañantes actualizados","Request service":"Consumo solicitado",
    "Prepare departure":"Salida preparada","Inspect departure":"Salida inspeccionada","Schedule cleaning":"Limpieza programada",
    "Record incident":"Incidencia registrada","Hold expired":"Retención temporal vencida","Portal hold expired":"Solicitud web vencida",
    "Portal request":"Solicitud web recibida","Convert portal request":"Solicitud web convertida en reserva","Create confirmation link":"Confirmación de reserva preparada",
    "Purchase order":"Compra solicitada","Receive purchase":"Compra recibida","Purchase invoice":"Factura de proveedor registrada",
    "Supplier payment":"Pago a proveedor","Supplier payment outside front-desk accounts":"Pago a proveedor fuera de caja de recepción",
    "Register supplier":"Proveedor registrado","Create property warehouse":"Almacén creado","Stock count adjustment":"Conteo de inventario ajustado",
    "Stock policy":"Política de inventario configurada","Reopen day":"Fecha operativa reabierta","Grant operational access":"Acceso operativo concedido",
    "Approve data retention":"Retención de datos aprobada","Retire sensitive fields":"Datos sensibles retirados","Dispose retained files":"Archivos vencidos procesados",
    "Retry file disposal":"Reintento de eliminación de archivos","Verified integration event":"Evento de integración verificado",
    "Rate created":"Tarifa creada","Rate changed":"Tarifa modificada",
    "Cancelled":"Reserva cancelada","No Show":"Reserva sin presentación",
    "Daily close Review":"Cierre revisado","Daily close Closed":"Día cerrado","Daily close Reopened":"Día reabierto",
    "on_submit":"Documento presentado","on_cancel":"Documento anulado","on_update_after_submit":"Documento presentado actualizado","ERP update":"Documento actualizado",
}


def action_label(value):
    if value in ACTIONS:
        return frappe._(ACTIONS[value])
    from hospitality_suite.printing import hs_label
    for prefix,title in (("Setup ","Configuración"),("Cleaning ","Limpieza"),("Maintenance ","Mantenimiento"),("Service ","Servicio"),("Adjustment ","Ajuste"),("Payment ","Caja"),("Booking ","Reserva")):
        if value and value.startswith(prefix):
            return frappe._(title)+": "+hs_label(value[len(prefix):])
    return frappe._(value) if value else ""


class Descriptions:
    def __init__(self,props):
        self.props={p.name:p for p in props}
        self._cache={}
        self._fields={}

    def scoped(self,dt,fields):
        if dt not in self._cache or not set(fields).issubset(self._fields.get(dt,set())):
            self._fields[dt]=self._fields.get(dt,set())|set(fields)
            self._cache[dt]={r.name:r for r in permitted_all(dt,filters={"property":["in",list(self.props)]},fields=["name",*sorted(self._fields[dt])])}
        return self._cache[dt]

    @cached_property
    def rooms(self):
        return self.scoped("HS Room",["room_number"])

    @cached_property
    def guests(self):
        return self.scoped("HS Guest",["full_name"])

    @cached_property
    def stays(self):
        return self.scoped("HS Stay",["room","guest","actual_check_in","property"])

    @cached_property
    def bookings(self):
        return self.scoped("HS Booking",["guest","customer","starts_at","property"])

    @cached_property
    def folios(self):
        return self.scoped("HS Folio",["label","stay","booking","customer"])

    def master(self,dt,name,field):
        key=(dt,name,field)
        if not name:
            return ""
        if key not in self._cache:
            # Values come exclusively from already authorized report records.
            self._cache[key]=frappe.db.get_value(dt,name,field) or frappe._("Sin descripción")
        return self._cache[key]

    def room(self,name):
        return ", ".join(self.rooms[n].room_number if n in self.rooms else frappe._("Sin habitación") for n in str(name or "").split(", ") if n)

    def stay(self,name,include_time=False):
        row=self.stays.get(name)
        if not row:
            return frappe._("Estancia") if name else ""
        guest=self.guests.get(row.guest)
        parts=[frappe._("Habitación {0}").format(self.room(row.room))]
        if guest:
            parts.append(guest.full_name)
        if row.actual_check_in:
            parts.append(local(row.actual_check_in,self.props[row.property]).strftime("%d/%m/%Y %H:%M" if include_time else "%d/%m/%Y"))
        return " · ".join(parts)

    def booking(self,name):
        row=self.bookings.get(name)
        if not row:
            return frappe._("Reserva") if name else ""
        guest=self.guests.get(row.guest)
        who=guest.full_name if guest else self.master("Customer",row.customer,"customer_name")
        return " · ".join([frappe._("Reserva de {0}").format(who),local(row.starts_at,self.props[row.property]).strftime("%d/%m/%Y %H:%M")])

    def folio(self,name):
        row=self.folios.get(name)
        return row.label if row else frappe._("Cuenta") if name else ""

    def origin(self,dt,name):
        if dt=="HS Stay":
            return self.stay(name)
        if dt=="HS Booking":
            return self.booking(name)
        if dt=="HS Folio":
            return self.folio(name)
        if dt=="HS Room":
            return self.room(name)
        if dt=="HS Guest":
            return self.guests[name].full_name if name in self.guests else frappe._("Huésped")
        if dt=="User":
            return self.master("User",name,"full_name")
        if dt in {"HS Charge","HS Service Request"}:
            row=self.scoped(dt,["item","amount","currency","creation","property"]).get(name)
            if row:
                item=self.master("Item",row.item,"item_name")
                stamp=local(row.creation,self.props[row.property]).strftime("%d/%m/%Y %H:%M")
                return f"{item} · {row.amount:.2f} {row.currency} · {stamp}"
        if dt=="HS Payment":
            row=self.scoped(dt,["kind","amount","currency","creation","property"]).get(name)
            if row:
                from hospitality_suite.printing import hs_label
                return f"{hs_label(row.kind)} · {row.amount:.2f} {row.currency} · {local(row.creation,self.props[row.property]).strftime('%d/%m/%Y %H:%M')}"
        if dt=="HS Shift":
            row=self.scoped(dt,["cashier","opened_at","property"]).get(name)
            if row:
                return frappe._("Caja de {0}").format(self.master("User",row.cashier,"full_name"))+" · "+local(row.opened_at,self.props[row.property]).strftime("%d/%m/%Y %H:%M")
        config={"HS Rate":["title"],"HS Category":["category_name"],"HS Equipment":["label"],
                "HS Maintenance Order":["title"],"HS Daily Close":["business_date"],"HS Expense Category":["label"]}
        if dt in config:
            row=self.scoped(dt,config[dt]).get(name)
            return str(row[config[dt][0]]) if row else frappe._(TITLES.get(dt,"Documento"))
        if dt in TITLES and not dt.startswith("HS "):
            return name  # Standard ERPNext voucher numbers are business references.
        return frappe._(TITLES.get(dt,"Documento de la operación"))


def prepare(report,records,props,level="operational"):
    from hospitality_suite.report_queries import ALIASES
    base=ALIASES.get(report,report)
    if level not in {"operational","technical"}:
        frappe.throw(frappe._("Presentación de reporte no admitida"))
    if not records:
        return [],[]
    data=Descriptions(props)
    result=[]
    original_columns=[k for k in records[0] if not k.startswith("_")]
    for record in records:
        row=frappe._dict(record.copy())
        hints=dict(row.get("_display",{}))
        prop=data.props.get(row.get("property")) or props[0]
        if level=="operational":
            if row.get("docstatus") is not None:
                hints["docstatus"]=frappe._({0:"Borrador",1:"Confirmada",2:"Anulada"}.get(row.docstatus,str(row.docstatus)))
            for key in ("is_return","blocks_room","active"):
                if row.get(key) is not None:
                    hints[key]=frappe._("Sí") if row[key] else frappe._("No")
            if row.get("room"):
                hints["room"]=hints.get("room") or data.room(row.room)
            elif base in {"Reservas","Estancias","Inventario"}:
                hints["room"]=frappe._("Por asignar") if base=="Reservas" else frappe._("Sin habitación")
            if base=="Reservas" and not row.get("guest"):
                hints["guest"]=frappe._("Por registrar")
            for key,dt,field in (("item","Item","item_name"),("customer","Customer","customer_name"),("supplier","Supplier","supplier_name"),
                                 ("actor","User","full_name"),("cashier","User","full_name"),("assigned_to","User","full_name"),
                                 ("warehouse","Warehouse","warehouse_name"),("cost_center","Cost Center","cost_center_name")):
                if row.get(key):
                    hints[key]=data.master(dt,row[key],field)
            for key,dt in (("stay","HS Stay"),("hs_stay","HS Stay"),("booking","HS Booking"),("folio","HS Folio"),("hs_folio","HS Folio")):
                if row.get(key):
                    hints[key]=data.origin(dt,row[key])
            if row.get("equipment"):
                hints["equipment"]=data.origin("HS Equipment",row.equipment)
            if row.get("method"):
                method=data.scoped("HS Payment Method",["mode_of_payment","currency"]).get(row.method)
                hints["method"]=f"{method.mode_of_payment} · {method.currency}" if method else frappe._("Medio de pago")
            if row.get("expense_category"):
                hints["expense_category"]=data.origin("HS Expense Category",row.expense_category)
            if row.get("source_doctype"):
                hints["source_doctype"]=frappe._(TITLES.get(row.source_doctype,row.source_doctype))
                hints["source_name"]=data.origin(row.source_doctype,row.get("source_name"))
            if base=="Auditoría":
                hints["action"]=action_label(row.get("action"))
            if base=="Mantenimiento" and row.get("until_reopened"):
                hints["ends_at"]=frappe._("Hasta reapertura autorizada")
            if base=="Conciliación":
                source_type={"Charge":"HS Charge","Payment":"HS Payment","Closed shift":"HS Shift"}.get(row.get("type"))
                if source_type:
                    hints["source"]="; ".join(data.origin(source_type,n) for n in row.get("source","").split(", "))
                if row.get("type")=="Payment" and row.get("kind"):
                    from hospitality_suite.printing import hs_label
                    hints["type"]=hs_label(row.kind)
            if base=="Producción" and row.get("source_type"):
                if row.source_type in {"Nota de crédito","Devolución de venta directa"}:
                    hints["item"]=frappe._("Devolución")+" · "+hints.get("item","")
                elif row.get("adjustment_type"):
                    from hospitality_suite.printing import hs_label
                    hints["item"]=hs_label(row.adjustment_type)+" · "+hints.get("item","")
                elif "Penalización" in row.source_type:
                    prefix=(frappe._("Devolución")+" · "+frappe._(row.source_type.removeprefix("Devolución · "))) if row.source_type.startswith("Devolución · ") else frappe._(row.source_type)
                    hints["item"]=prefix+" · "+hints.get("item","")
                elif row.source_type.startswith("Devolución · "):
                    hints["item"]=frappe._("Devolución")+" · "+hints.get("item","")
                if not row.get("room"):
                    hints["room"]=frappe._("Venta directa") if "venta directa" in row.source_type.lower() else frappe._("Sin habitación")
            if base=="Cuentas pendientes":
                row.account_label=data.folio(row.name)
            if base=="Facturas":
                row.invoice_number=row.name
            if base in {"Cobros","Liquidaciones","Egresos"}:
                payment=data.scoped("HS Payment",["creation"]).get(row.name)
                row.recorded_at=payment.creation if payment else None
        for key in DATES:
            if row.get(key):
                hints[key]=local(row[key],prop).strftime("%d/%m/%Y %H:%M")
        row["_display"]=hints
        result.append(row)
    if level=="technical":
        return result,original_columns
    # Grouped production already has a compact, meaningful set of dimensions.
    if base=="Producción" and "name" not in original_columns:
        columns=original_columns
    else:
        available=set().union(*(r.keys() for r in result))
        columns=[k for k in PROFILES.get(report,PROFILES.get(base,original_columns)) if k in available]
    for field in ("property","time_zone"):
        if field in original_columns and field not in columns:
            columns.append(field)
    return result,columns
