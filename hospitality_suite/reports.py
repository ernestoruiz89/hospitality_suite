"""Scoped operational projections; no mixing of advances, revenue or occupancy units."""
from datetime import timedelta
import json

import frappe
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.mode import is_time_mode
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
    "Cobros": ("HS Payment", ["name", "business_date", "stay", "booking", "shift", "method", "kind", "amount", "currency", "base_amount", "status", "payment_entry", "journal_entry"]),
    "Liquidaciones":("HS Payment",["name", "business_date","source_payment","shift","method","settlement_direction","amount","fee_amount","withholding_amount","net_amount","currency","status","journal_entry","reference"]),
    "Egresos":("HS Payment",["name", "business_date","shift","method","kind","expense_category","supplier","purchase_invoice","amount","currency","status","journal_entry","payment_entry","reason"]),
    "Turnos": ("HS Shift", ["name", "cashier", "opened_at", "closed_at", "status", "currency", "expected_amount", "counted_amount", "difference"]),
    "Limpieza": ("HS Cleaning Task", ["name", "room", "status", "kind", "assigned_to", "started_at", "completed_at"]),
    "Mantenimiento": ("HS Maintenance Order", ["name", "room","equipment","blocks_room","until_reopened", "title", "status", "starts_at", "ends_at", "cost", "stock_entry"]),
    "Inventario": ("HS Service Request", ["name", "item", "quantity", "status", "stock_entry", "return_stock_entry", "charge", "amount", "currency"]),
    "Movimientos de inventario":(None,[]),
    "Auditoría": ("HS Audit Event", ["name", "action", "actor", "occurred_at", "source_doctype", "source_name", "reason"]),
}

from hospitality_suite.report_queries import ALIASES
for _name, _base in ALIASES.items():
    REPORTS[_name] = REPORTS[_base]


def rows(prop, report, filters=None):
    require(prop.name, "report")
    from hospitality_suite.report_queries import projected_rows
    return projected_rows(prop,report,filters or {})


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
        date_filters=[]
        if filters.get("from_date"):
            date_filters.append(["posting_date",">=",filters["from_date"]])
        if filters.get("to_date"):
            date_filters.append(["posting_date","<=",filters["to_date"]])
        if date_filters:
            selected=[[key,"=",value] if not isinstance(value,list) else [key,*value] for key,value in selected.items()]+date_filters
        entries=frappe.get_all("Stock Ledger Entry",filters=selected,fields=["name","posting_date","posting_time","item_code","warehouse","actual_qty","qty_after_transaction","stock_value_difference","voucher_no","voucher_detail_no"],order_by="posting_date desc,posting_time desc,creation desc")
        meta=frappe.get_meta(child)
        details={r.name:r for r in current_all(child,filters={"name":["in",[e.voucher_detail_no for e in entries]]},fields=["name"]+[k for k in ("cost_center","expense_account") if meta.has_field(k)])} if entries else {}
        for row in entries:
            origin=origins[row.voucher_no]
            usage=origin.get("hs_stock_purpose") or purpose
            if filters.get("purpose") and filters["purpose"]!=usage:
                continue
            detail=details.get(row.voucher_detail_no,{})
            result.append(dict(name=row.name,posting_date=row.posting_date,posting_time=row.posting_time,item=row.item_code,warehouse=row.warehouse,
                               purpose=usage,classification=policies.get((row.item_code,row.warehouse),"Unclassified"),quantity=row.actual_qty,
                               balance_quantity=row.qty_after_transaction,cost=row.stock_value_difference,currency=base_currency,
                               cost_center=detail.get("cost_center"),expense_account=detail.get("expense_account"),source_doctype=dt,source_name=row.voucher_no,actor=origin.owner))
    return sorted(result,key=lambda r:(str(r["posting_date"]),str(r["posting_time"]),r["name"]),reverse=True)


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
    from hospitality_suite.time import to_site, local, business_window
    window=business_window(prop) if not starts_at or not ends_at else {}
    start=to_site(starts_at,prop) if starts_at else window["starts_at"]
    end=to_site(ends_at,prop) if ends_at else window["ends_at"]
    if end<=start or (end-start).days>366:
        frappe.throw(frappe._("Consulte un período positivo de hasta un año"))
    room_names=current_all("HS Room",filters={"property":prop.name,"active":1},pluck="name")
    stays={r.name:r for r in current_all("HS Stay",filters={"property":prop.name},fields=["*"])}
    allocations=current_all("HS Allocation",filters={"property":prop.name},fields=["*"])
    blocked,occupied={},{}
    for row in allocations:
        if not row.room or row.kind not in ("Stay","Maintenance"):
            continue
        a,b=get_datetime(row.starts_at),get_datetime(row.ends_at) if row.ends_at else end
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
            if not is_time_mode(mode):
                continue
        else:
            if row.status=="Released":
                order=locked_doc("HS Maintenance Order",row.maintenance) if row.maintenance else None
                if order and order.status=="Completed":
                    from hospitality_suite.housekeeping import maintenance_finished_at
                    b=min(b,maintenance_finished_at(order))
        a,b=max(start,a),min(end,b)
        if a<b:
            (blocked if row.kind=="Maintenance" else occupied).setdefault(row.room,[]).append((a,b))
    seconds=sum(union_seconds(v) for v in occupied.values())
    available=max(0,len(room_names)*(end-start).total_seconds()-sum(union_seconds(v) for v in blocked.values()))
    commercial_rooms=sum(union_seconds(blocked.get(room,[]))<(end-start).total_seconds() for room in room_names)
    charges=current_all("HS Charge",filters={"property":prop.name,"status":["!=","Reversed"]},fields=["*"])
    lodging_net=decimal(0)
    time_net=decimal(0)
    day_pass_net=decimal(0)
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
                timed_net=net*decimal(overlap)/decimal((b-a).total_seconds())
                time_net+=timed_net
                if snapshot["rules"].get("day_pass"):
                    day_pass_net+=timed_net
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
    time_stays=[r for r in stays.values() if is_time_mode(json.loads(r.quote_snapshot)["rules"]["mode"]) and start<=get_datetime(r.actual_check_in)<end]
    day_pass_stays=[r for r in time_stays if json.loads(r.quote_snapshot)["rules"].get("day_pass")]
    no_room_passes=[r for r in current_all("HS Day Pass",filters={"property":prop.name,"status":"Issued"},fields=["starts_at","sales_invoice"])
                    if start<=get_datetime(r.starts_at)<end]
    no_room_pass_net=decimal(0)
    for record in no_room_passes:
        invoice=locked_doc("Sales Invoice",record.sales_invoice)
        if invoice.docstatus==1 and invoice.currency==prop.currency:
            no_room_pass_net+=decimal(invoice.net_total)
    served=[r for r in stays.values() if is_time_mode(json.loads(r.quote_snapshot)["rules"]["mode"]) and get_datetime(r.actual_check_in)<end and get_datetime(r.actual_check_out or now_datetime())>start]
    durations=[max(0,(get_datetime(r.actual_check_out or now_datetime())-get_datetime(r.actual_check_in)).total_seconds()/3600) for r in served]
    from hospitality_suite.report_queries import direct_sales,native_invoice_lines
    production_by_currency={}
    for row in charges+direct_sales(prop)+native_invoice_lines(prop):
        if row.get('status')=='Scheduled':
            continue
        if local_start.date()<=row.business_date<local_end.date():
            production_by_currency[row.currency]=production_by_currency.get(row.currency,decimal(0))+decimal(row.amount)
    production=production_by_currency.get(prop.currency,decimal(0))
    safe=lambda a,b:str(money(decimal(a)/decimal(b))) if b else "0.00"
    return dict(currency=prop.currency,production=str(money(production,currency=prop.currency)),
                production_by_currency={c:str(money(value,currency=c)) for c,value in sorted(production_by_currency.items())},lodging_production=str(money(lodging_net+time_net)),
                hotel_lodging_net=str(money(lodging_net)),motel_lodging_net=str(money(time_net)),
                day_pass_lodging_net=str(money(day_pass_net)),day_passes=len(day_pass_stays),
                day_pass_no_room_count=len(no_room_passes),day_pass_no_room_net=str(money(no_room_pass_net)),
                occupied_hours=round(seconds/3600,2),available_hours=round(available/3600,2),
                utilization=round(seconds/available*100,2) if available else 0,
                rotations=len(time_stays),commercial_rooms=commercial_rooms,rotations_per_room=round(len(time_stays)/commercial_rooms,2) if commercial_rooms else 0,
                average_stay_hours=round(sum(durations)/len(durations),2) if durations else 0,
                room_nights=len(sold_nights),available_room_nights=available_nights,
                occupancy_percent=round(len(sold_nights)/available_nights*100,2) if available_nights else 0,
                ADR=safe(lodging_net,len(sold_nights)),RevPAR=safe(lodging_net,available_nights),
                revenue_per_available_hour=safe(time_net,decimal(available)/3600),average_ticket=safe(time_net,len(served)),
                starts_at=str(start),ends_at=str(end),mode=prop.mode,time_zone=prop.time_zone,
                local_starts_at=local(start,prop).isoformat(),local_ends_at=local(end,prop).isoformat(),
                close_time=window["close_time"] if not starts_at and not ends_at else None,
                definitions=frappe._("Hotel: noches comercializadas de estancias con entrada registrada, únicas por habitación y fecha; ADR=alojamiento neto facturado/noches, RevPAR=neto/noches disponibles. Por tiempo: horas reales unidas por habitación; rotaciones/habitación=entradas/habitaciones con alguna hora comercializable; ingreso neto/hora disponible. Ingreso de líneas de facturas presentadas, distribuido al período de servicio; excluye impuestos, otros servicios, anticipos y garantías. Cortesías ocupan con ingreso cero; bloqueos restan capacidad; denominador cero=0. Producción operativa se muestra separada por moneda."))
