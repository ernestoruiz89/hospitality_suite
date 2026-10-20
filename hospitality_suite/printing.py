import frappe

from hospitality_suite.security import document,require
from hospitality_suite.service import current_all


def hs_json(value):
    return frappe.parse_json(value)


def hs_close_groups():
    from hospitality_suite.close_financials import display_groups
    return display_groups()


def hs_shift_pos(name):
    shift=document("HS Shift",name)
    from hospitality_suite.native_pos import movements
    return movements(shift.property,shift.name)


VALUE_LABELS={"Scheduled":"Programado","Arrival":"Al ingresar","Nightly":"Por noche","Confirmed":"Confirmada","Checked In":"Entrada registrada","Completed":"Completada","Cancelled":"Cancelada","No Show":"No presentada",
            "Hold":"Retención temporal","Active":"Alojado","Checked Out":"Salida registrada","Pending":"Pendiente","In Progress":"En proceso",
            "Inspection":"Pendiente de inspección","Open":"Abierto","Closed":"Cerrado","Review":"Por revisar","Posted":"Contabilizado","Resolved":"Resuelto",
            "Payment":"Cobro","Advance":"Anticipo","Guarantee":"Garantía","Guarantee Refund":"Devolución de garantía",
            "Guarantee Applied":"Aplicación de garantía","Refund":"Devolución","Withdrawal":"Retiro / entrega","Invoiced":"Facturado",
            "Expense":"Egreso","Supplier Payment":"Pago a proveedor","Settlement":"Liquidación de tarjeta",
            "Settlement net":"Depósito neto","Settlement fee":"Comisión","Settlement withholding":"Retención","Settlement clearing":"Compensación histórica",
            "Receive":"Ingreso bancario","Pay":"Débito bancario",
            "Transfer":"Traslado","Cleaning":"Consumo de limpieza","Waste":"Merma / pérdida","Linen Replacement":"Reposición de ropa","Maintenance":"Mantenimiento","Laundry":"Lavandería","Purchase":"Compra","Sale":"Venta","Adjustment":"Ajuste",
            "Merchandise":"Mercancía","Linen":"Ropa de cama","Parts":"Repuestos","Asset":"Activo fijo","Stock":"Movimiento estándar sin clasificar",
            "Corrective":"Correctivo","Preventive":"Preventivo","Departure":"Salida","Stay":"Estancia","Deep":"Profunda",
            "Normal":"Normal","High":"Alta","Urgent":"Urgente","Charge":"Cargo","Closed shift":"Turno cerrado",
            "Principal":"Principal","Acompañante":"Acompañante"}
VALUE_LABELS.update(Unclassified="Sin clasificar",Discount="Descuento",Courtesy="Cortesía",Surcharge="Recargo",Reversed="Revertido",Delivered="Entregado",Returned="Devuelto",Requested="Solicitado")
VALUE_LABELS.update(Service="Servicio",Lodging="Alojamiento",Difference="Diferencia")
from hospitality_suite.display_labels import MODE_LABELS
VALUE_LABELS.update(MODE_LABELS)


def hs_label(value):
    if value == 'Draft':
        return frappe._('Borrador')
    return frappe._(VALUE_LABELS.get(value,value or "—"))


def hs_money(value,currency):
    return frappe.utils.fmt_money(value,currency=currency)


def hs_date(value,property_name):
    if not value:
        return "—"
    from hospitality_suite.time import local
    return local(value,require(property_name)).strftime("%d/%m/%Y %H:%M")


def hs_account_context(name):
    from hospitality_suite.accounting import folios_for_stay,folio_balance
    stay=document("HS Stay",name)
    folios=folios_for_stay(stay)
    for folio in folios:
        folio["balance"]=folio_balance(folio.name)
    invoices=current_all("Sales Invoice",filters={"hs_folio":["in",[f.name for f in folios]],"docstatus":1},
                         fields=["name","customer","currency","net_total","total_taxes_and_charges","grand_total","outstanding_amount","hs_folio","is_return"])
    payments=current_all("HS Payment",filters={"property":stay.property,"status":"Posted"},
                         fields=["name","stay","booking","folio","kind","amount","currency","payment_entry","journal_entry"])
    payments=[p for p in payments if p.stay==stay.name or (p.folio and p.folio in [f.name for f in folios]) or (stay.booking and p.booking==stay.booking and not p.stay)]
    charges=current_all('HS Charge',filters={'property':stay.property,'stay':stay.name},fields=['*'],order_by='creation asc,name asc')
    for row in charges:
        from hospitality_suite.display_labels import generated_label
        row['description_label']=generated_label(row.description)
    return dict(folios=folios,invoices=invoices,payments=payments,charges=charges)


def hs_maintenance_context(name):
    from hospitality_suite.security import ACTIONS,is_system
    order=document("HS Maintenance Order",name)
    allowed=is_system() or set(frappe.get_roles()).intersection(ACTIONS["maintain"]+ACTIONS["report"])
    return dict(parts=[r.as_dict() for r in order.parts] if allowed else [],cost=order.cost if allowed else None,
                currency=frappe.db.get_value("Company",order.company,"default_currency"))
