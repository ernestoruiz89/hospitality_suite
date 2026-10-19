"""Scoped operational projections; no mixing of advances, revenue or occupancy units."""
from datetime import timedelta
import json

import frappe
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import require
from hospitality_suite.service import current_all, locked_doc

REPORTS = {
    "Conciliación": (None, []),
    "Disponibilidad": ("HS Room", ["name", "room_number", "category", "floor", "zone", "cleaning_status", "active"]),
    "Facturas": ("Sales Invoice", ["name", "customer", "posting_date", "grand_total", "outstanding_amount", "currency", "docstatus", "hs_stay", "hs_folio", "is_return", "return_against"]),
    "Cuentas pendientes": ("HS Folio", ["name", "stay", "customer", "currency", "status"]),
    "Reservas": ("HS Booking", ["name", "starts_at", "ends_at", "status", "channel", "customer", "amount", "currency"]),
    "Estancias": ("HS Stay", ["name", "room", "starts_at", "ends_at", "actual_check_in", "actual_check_out", "status", "customer"]),
    "Producción": ("HS Charge", ["name", "stay", "folio", "item", "kind", "amount", "currency", "status", "sales_invoice", "business_date"]),
    "Cobros": ("HS Payment", ["name", "stay", "booking", "shift", "method", "kind", "amount", "currency", "base_amount", "status", "payment_entry", "journal_entry"]),
    "Liquidaciones":("HS Payment",["name","source_payment","shift","method","settlement_direction","amount","fee_amount","withholding_amount","net_amount","currency","status","journal_entry","reference"]),
    "Egresos":("HS Payment",["name","shift","method","kind","expense_category","supplier","purchase_invoice","amount","currency","status","journal_entry","payment_entry","reason"]),
    "Turnos": ("HS Shift", ["name", "cashier", "opened_at", "closed_at", "status", "currency", "expected_amount", "counted_amount", "difference"]),
    "Limpieza": ("HS Cleaning Task", ["name", "room", "status", "kind", "assigned_to", "started_at", "completed_at"]),
    "Mantenimiento": ("HS Maintenance Order", ["name", "room", "title", "status", "starts_at", "ends_at", "cost", "stock_entry"]),
    "Inventario": ("HS Service Request", ["name", "item", "quantity", "status", "stock_entry", "return_stock_entry", "charge", "amount", "currency"]),
    "Movimientos de inventario":(None,[]),
    "Auditoría": ("HS Audit Event", ["name", "action", "actor", "occurred_at", "source_doctype", "source_name", "reason"]),
}


def rows(prop, report, filters=None):
    require(prop.name, "report")
    if report not in REPORTS:
        frappe.throw("Reporte desconocido")
    if report=="Conciliación":
        from hospitality_suite.reconciliation import rows as reconcile
        return reconcile(prop,filters)
    if report=="Movimientos de inventario":
        return inventory_movements(prop,filters or {})
    dt, fields = REPORTS[report]
    selected = {"hs_property" if dt == "Sales Invoice" else "property": prop.name}
    allowed = {"room", "status", "category", "channel", "cashier", "shift", "kind", "assigned_to"}
    for key, value in (filters or {}).items():
        if key in allowed and frappe.get_meta(dt).has_field(key) and isinstance(value, str) and value:
            selected[key] = value
    filters=filters or {}
    kinds={"Liquidaciones":["Settlement"],"Egresos":["Expense","Supplier Payment","Withdrawal"],"Cobros":["Payment","Advance","Guarantee","Refund","Guarantee Refund","Guarantee Applied"]}.get(report)
    if kinds:
        if selected.get("kind") and selected["kind"] not in kinds:
            frappe.throw("El concepto no corresponde a este reporte")
        selected["kind"]=selected.get("kind") or ["in",kinds]
    date_field="posting_date" if dt=="Sales Invoice" else "business_date" if frappe.get_meta(dt).has_field("business_date") else "creation"
    if filters.get("from_date") and filters.get("to_date"):
        selected[date_field]=["between",[filters["from_date"],filters["to_date"]+" 23:59:59" if date_field=="creation" else filters["to_date"]]]
    result=frappe.get_list(dt, filters=selected, fields=fields, order_by="creation desc", limit_page_length=1000)
    if report=="Cuentas pendientes":
        from hospitality_suite.accounting import folio_balance
        for row in result:
            row.update(folio_balance(row.name))
    return result


def inventory_movements(prop,filters):
    """Project the native ledger; operational records never supply valuation."""
    from hospitality_suite.procurement import warehouses,warehouse
    permitted=warehouses(prop)
    if filters.get("warehouse"):
        permitted=[warehouse(prop,filters["warehouse"])]
    policies={(r.item,r.warehouse):r.purpose for r in current_all("HS Stock Policy",filters={"property":prop.name},fields=["item","warehouse","purpose"])}
    base_currency=frappe.db.get_value("Company",prop.company,"default_currency")
    result=[]
    for dt,child,purpose in (("Stock Entry","Stock Entry Detail","Stock"),("Purchase Receipt","Purchase Receipt Item","Purchase"),
                              ("Stock Reconciliation","Stock Reconciliation Item","Adjustment"),("Sales Invoice","Sales Invoice Item","Sale"),
                              ("Purchase Invoice","Purchase Invoice Item","Purchase"),("Delivery Note","Delivery Note Item","Sale")):
        fields=["name","owner"]+(["hs_stock_purpose"] if dt=="Stock Entry" else [])
        origins={r.name:r for r in current_all(dt,filters={"hs_property":prop.name,"company":prop.company,"docstatus":1},fields=fields)}
        if not origins:
            continue
        selected=dict(company=prop.company,voucher_type=dt,voucher_no=["in",list(origins)],warehouse=["in",permitted],is_cancelled=0)
        if filters.get("item"):
            selected["item_code"]=filters["item"]
        if filters.get("from_date") and filters.get("to_date"):
            selected["posting_date"]=["between",[filters["from_date"],filters["to_date"]]]
        entries=frappe.get_all("Stock Ledger Entry",filters=selected,fields=["name","posting_date","posting_time","item_code","warehouse","actual_qty","qty_after_transaction","stock_value_difference","voucher_no","voucher_detail_no"],order_by="posting_date desc,posting_time desc,creation desc",limit_page_length=1000)
        meta=frappe.get_meta(child)
        details={r.name:r for r in current_all(child,filters={"name":["in",[e.voucher_detail_no for e in entries]]},fields=["name"]+[k for k in ("cost_center","expense_account") if meta.has_field(k)])} if entries else {}
        for row in entries:
            origin=origins[row.voucher_no]
            usage=origin.get("hs_stock_purpose") or purpose
            if filters.get("purpose") and filters["purpose"]!=usage:
                continue
            detail=details.get(row.voucher_detail_no,{})
            result.append(dict(name=row.name,posting_date=row.posting_date,posting_time=row.posting_time,item=row.item_code,warehouse=row.warehouse,
                               purpose=usage,classification=policies.get((row.item_code,row.warehouse),"Merchandise"),quantity=row.actual_qty,
                               balance_quantity=row.qty_after_transaction,cost=row.stock_value_difference,currency=base_currency,
                               cost_center=detail.get("cost_center"),expense_account=detail.get("expense_account"),source_doctype=dt,source_name=row.voucher_no,actor=origin.owner))
    return sorted(result,key=lambda r:(str(r["posting_date"]),str(r["posting_time"]),r["name"]),reverse=True)[:1000]


def union_seconds(spans):
    merged = []
    for start, end in sorted(spans):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum((b - a).total_seconds() for a, b in merged)


def summary(prop, starts_at=None, ends_at=None):
    from hospitality_suite.time import to_site, local
    start=to_site(starts_at or str(prop.business_date)+" 00:00:00",prop)
    end=to_site(ends_at,prop) if ends_at else to_site(str(get_datetime(str(prop.business_date)).date()+timedelta(days=1))+" 00:00:00",prop)
    if end<=start or (end-start).days>366:
        frappe.throw("Consulte un período positivo de hasta un año")
    room_names=current_all("HS Room",filters={"property":prop.name,"active":1},pluck="name")
    stays={r.name:r for r in current_all("HS Stay",filters={"property":prop.name},fields=["*"])}
    allocations=current_all("HS Allocation",filters={"property":prop.name},fields=["*"])
    blocked,occupied={},{}
    for row in allocations:
        if not row.room or row.kind not in ("Stay","Maintenance"):
            continue
        a,b=get_datetime(row.starts_at),get_datetime(row.ends_at)
        if row.kind=="Stay":
            stay=stays.get(row.stay)
            if not stay:
                continue
            a=max(a,get_datetime(stay.actual_check_in))
            if stay.status=="Active" and stay.room==row.room:
                b=now_datetime()  # actual occupation survives its planned deadline
            elif stay.actual_check_out:
                b=min(b,get_datetime(stay.actual_check_out))
            mode=json.loads(row.quote_snapshot or stay.quote_snapshot)["rules"]["mode"]
            if mode!="Motel":
                continue
        else:
            if row.status=="Released":
                order=locked_doc("HS Maintenance Order",row.maintenance) if row.maintenance else None
                if order and order.status=="Completed":
                    b=min(b,get_datetime(order.modified))
        a,b=max(start,a),min(end,b)
        if a<b:
            (blocked if row.kind=="Maintenance" else occupied).setdefault(row.room,[]).append((a,b))
    seconds=sum(union_seconds(v) for v in occupied.values())
    available=max(0,len(room_names)*(end-start).total_seconds()-sum(union_seconds(v) for v in blocked.values()))
    charges=current_all("HS Charge",filters={"property":prop.name,"status":["!=","Reversed"]},fields=["*"])
    lodging_net=decimal(0)
    motel_net=decimal(0)
    sold_nights=set()
    local_start,local_end=local(start,prop),local(end,prop)
    for charge in charges:
        if charge.kind!="Lodging" or charge.currency!=prop.currency:
            continue
        stay=stays.get(charge.stay)
        if not stay:
            continue
        snapshot=json.loads(charge.quote_snapshot or "{}")
        if not snapshot.get("rules"):
            snapshot=json.loads(stay.quote_snapshot)
        mode=snapshot["rules"]["mode"]
        net=decimal(0)
        if charge.status=="Invoiced" and charge.invoice_item and charge.sales_invoice:
            inv=locked_doc("Sales Invoice",charge.sales_invoice)
            if inv.docstatus==1:
                item=next((r for r in inv.items if r.name==charge.invoice_item),None)
                if item:
                    peers=[r for r in charges if r.sales_invoice==charge.sales_invoice and r.invoice_item==charge.invoice_item]
                    denominator=sum(decimal(r.amount) for r in peers)
                    net=decimal(item.net_amount)*decimal(charge.amount)/denominator if denominator else decimal(0)
        if mode=="Hotel":
            nightly=snapshot.get("nightly") or []
            if not nightly:
                begin=get_datetime(snapshot.get("service_start") or snapshot.get("start") or stay.starts_at).date()
                finish=get_datetime(snapshot.get("service_end") or snapshot.get("end") or stay.ends_at).date()
                nightly=[dict(date=str(begin+timedelta(days=i))) for i in range(max(1,(finish-begin).days))]
            relevant=[r for r in nightly if local_start.date()<=get_datetime(r["date"]).date()<local_end.date()]
            total_weight=sum(decimal(r.get("amount") or 1) for r in nightly)
            selected_weight=sum(decimal(r.get("amount") or 1) for r in relevant)
            lodging_net+=net*selected_weight/total_weight if total_weight else decimal(0)
            if decimal(charge.amount)>=0:
                for night in relevant:
                    a=to_site(night["date"]+" 00:00:00",prop)
                    b=to_site(str(get_datetime(night["date"]).date()+timedelta(days=1))+" 00:00:00",prop)
                    segments=sorted([r for r in allocations if r.stay==stay.name and r.room and get_datetime(r.starts_at)<b and get_datetime(r.ends_at)>a],key=lambda r:r.starts_at)
                    sold_nights.add((segments[0].room if segments else stay.room,night["date"]))
        else:
            a=get_datetime(snapshot.get("service_start") or stay.starts_at)
            b=get_datetime(snapshot.get("service_end") or stay.ends_at)
            # Snapshot ISO times carry an offset; normalize them before comparing.
            if a.tzinfo:
                a=to_site(a,prop)
            if b.tzinfo:
                b=to_site(b,prop)
            overlap=max(0,(min(end,b)-max(start,a)).total_seconds())
            if b>a:
                motel_net+=net*decimal(overlap)/decimal((b-a).total_seconds())
    dates=[]
    day=local_start.date()
    while day<local_end.date():
        dates.append(day)
        day+=timedelta(days=1)
    blocked_nights=0
    for room in room_names:
        for day in dates:
            a=to_site(str(day)+" 00:00:00",prop)
            b=to_site(str(day+timedelta(days=1))+" 00:00:00",prop)
            if any(x<b and y>a for x,y in blocked.get(room,[])):
                blocked_nights+=1
    available_nights=max(0,len(room_names)*len(dates)-blocked_nights)
    motel_stays=[r for r in stays.values() if json.loads(r.quote_snapshot)["rules"]["mode"]=="Motel" and start<=get_datetime(r.actual_check_in)<end]
    served=[r for r in stays.values() if json.loads(r.quote_snapshot)["rules"]["mode"]=="Motel" and get_datetime(r.actual_check_in)<end and get_datetime(r.actual_check_out or now_datetime())>start]
    durations=[max(0,(get_datetime(r.actual_check_out or now_datetime())-get_datetime(r.actual_check_in)).total_seconds()/3600) for r in served]
    production=sum(decimal(r.amount) for r in charges if local_start.date()<=r.business_date<local_end.date())
    safe=lambda a,b:str(money(decimal(a)/decimal(b))) if b else "0.00"
    return dict(currency=prop.currency,production=str(money(production)),lodging_production=str(money(lodging_net+motel_net)),
                hotel_lodging_net=str(money(lodging_net)),motel_lodging_net=str(money(motel_net)),
                occupied_hours=round(seconds/3600,2),available_hours=round(available/3600,2),
                utilization=round(seconds/available*100,2) if available else 0,
                rotations=len(motel_stays),average_stay_hours=round(sum(durations)/len(durations),2) if durations else 0,
                room_nights=len(sold_nights),available_room_nights=available_nights,
                occupancy_percent=round(len(sold_nights)/available_nights*100,2) if available_nights else 0,
                ADR=safe(lodging_net,len(sold_nights)),RevPAR=safe(lodging_net,available_nights),
                revenue_per_available_hour=safe(motel_net,decimal(available)/3600),average_ticket=safe(motel_net,len(served)),
                starts_at=str(start),ends_at=str(end),mode=prop.mode,
                definitions="Hotel: noches comercializadas de estancias con entrada registrada, únicas por habitación y fecha; ADR=alojamiento neto facturado/noches, RevPAR=neto/noches disponibles. Motel: horas reales unidas por habitación, rotaciones=entradas; ingreso neto/hora disponible. Ingreso de líneas de facturas presentadas, distribuido al período de servicio; excluye impuestos, otros servicios, anticipos y garantías. Cortesías ocupan con ingreso cero; bloqueos restan capacidad; denominador cero=0. Producción operativa se muestra separadamente.")
