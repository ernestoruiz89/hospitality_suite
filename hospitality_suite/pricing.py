"""Pure decimal pricing kernel; persisted snapshots preserve accepted calculations."""
from datetime import timedelta, UTC
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from hospitality_suite.i18n import text as _


def decimal(value):
    return Decimal(str(value or 0))


def currency_precision(currency=None):
    import sys
    frappe=sys.modules.get("frappe")
    if not frappe or not getattr(frappe.local,"site",None):
        return 2  # The pure calculation kernel also runs outside a Frappe site.
    from frappe.utils import get_currency_precision
    from frappe.model.meta import get_precision_from_currency_format
    precision=get_currency_precision()
    return int(precision) if precision is not None else get_precision_from_currency_format(currency or frappe.defaults.get_global_default("currency"))


def money(value, precision=None, currency=None):
    precision=currency_precision(currency) if precision is None else int(precision)
    return decimal(value).quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)


def calculate(rate, start, end, people=1, extra_beds=0, precision=2):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise ValueError(_("El fin debe ser posterior al inicio"))
    if people < 1 or extra_beds < 0:
        raise ValueError(_("Ocupación inválida"))
    details = []
    extra_amount=decimal(0)
    extra_units=decimal(0)
    rounding=decimal(rate.get("rounding_minutes") or 60)
    extra_people = max(0, int(people) - int(rate.get("included_people") or 2))
    extras = decimal(rate.get("additional_person_rate")) * extra_people + decimal(rate.get("extra_bed_rate")) * extra_beds
    if rate["mode"] == "Hotel":
        units = max(1, (end.date() - start.date()).days)
        subtotal = (decimal(rate["amount"]) + extras) * units
        details.append(_("{0} noche(s) × {1}",[units,decimal(rate['amount']) + extras]))
    else:
        elapsed = decimal((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()) / 60
        block = decimal(rate.get("block_hours") or 3) * 60
        beyond = max(Decimal(0), elapsed - block - decimal(rate.get("grace_minutes")))
        rounding = decimal(rate.get("rounding_minutes") or 60)
        extra_units = (beyond / rounding).to_integral_value(rounding=ROUND_CEILING)
        extra_amount = extra_units * rounding / 60 * decimal(rate.get("extra_hour_rate"))
        units = 1
        subtotal = decimal(rate["amount"]) + extras + extra_amount
        details.append(_("Bloque {0} h: {1}; {2} fracción(es) de {3} min: {4}; personas/camas: {5}",[block/60,rate['amount'],extra_units,rounding,extra_amount,extras]))
    total=money(subtotal,precision)
    additional=money(extra_amount,precision)
    return dict(currency=rate["currency"], amount=str(total),lodging_amount=str(total-additional),extra_hours_amount=str(additional),
                extra_hours_quantity=str(extra_units*rounding/60),units=units,
                explanation=details, rules=dict(rate), start=start.isoformat(), end=end.isoformat(), precision=precision)


def quote(prop, category, starts_at, ends_at, people=1, rate_name=None, customer=None, mode=None,extra_beds=0):
    import frappe
    from hospitality_suite.service import current_all
    from hospitality_suite.time import local
    start, end = local(starts_at, prop), local(ends_at, prop)
    rates = current_all("HS Rate", filters={"property": prop.name, "category": category, "active": 1}, fields=["*"])
    for rate in rates:
        rate["included_services"]=current_all("HS Rate Service",filters={"parent":rate.name,"parenttype":"HS Rate"},fields=["item","quantity","basis"])
    if rate_name:
        rates = [r for r in rates if r.name == rate_name]
    from hospitality_suite.mode import normalize_mode
    requested_mode=normalize_mode(mode or (prop.mode if prop.mode!="Mixed" else "Hotel"))
    day_pass=requested_mode=="Day Pass"
    selected_mode="Por tiempo" if day_pass else requested_mode
    if requested_mode not in ("Hotel","Por tiempo","Day Pass") or (prop.mode!="Mixed" and selected_mode!=prop.mode):
        frappe.throw(frappe._("El establecimiento no permite esa modalidad"))
    if day_pass and start.date()!=end.date():
        frappe.throw(frappe._("Day Pass requiere entrada y salida en el mismo día local"))
    rates=[r for r in rates if r.mode==selected_mode and bool(r.get("day_pass"))==day_pass
           and (not r.customer or r.customer==customer)]

    def choose(day):
        matches=[r for r in rates if (not r.valid_from or r.valid_from<=day) and (not r.valid_to or r.valid_to>=day)
                 and (not r.weekdays or str(day.weekday()) in [d.strip() for d in r.weekdays.split(",")])]
        if selected_mode=="Por tiempo":
            from frappe.utils import get_time
            def in_window(r):
                if not r.night_start or not r.night_end:
                    return True
                a,b,t=get_time(r.night_start),get_time(r.night_end),start.time().replace(tzinfo=None)
                return (a<=t<b) if a<b else (t>=a or t<b)
            matches=[r for r in matches if in_window(r)]
        matches.sort(key=lambda r:(-r.priority,-bool(r.customer),r.name))
        if not matches:
            frappe.throw(frappe._("No existe una tarifa aplicable a la fecha y al pagador"))
        if len(matches)>1 and (matches[0].priority,bool(matches[0].customer))==(matches[1].priority,bool(matches[1].customer)):
            frappe.throw(frappe._("Hay tarifas con la misma prioridad; defina una prioridad inequívoca"))
        return matches[0]
    precision = currency_precision(choose(start.date()).currency)
    if selected_mode=="Por tiempo":
        result=calculate(choose(start.date()),start,end,int(people),extra_beds=int(extra_beds),precision=int(precision))
    else:
        nightly=[]
        for i in range(max(1,(end.date()-start.date()).days)):
            day=start.date()+timedelta(days=i)
            rate=choose(day)
            price=decimal(rate.amount)+max(0,int(people)-int(rate.included_people or 2))*decimal(rate.additional_person_rate)+int(extra_beds)*decimal(rate.extra_bed_rate)
            nightly.append(dict(date=str(day),amount=str(money(price,int(precision))),rules=dict(rate)))
        currencies={r["rules"]["currency"] for r in nightly}
        if len(currencies)!=1:
            frappe.throw(frappe._("Las tarifas por noche deben usar una sola moneda"))
        result=dict(currency=nightly[0]["rules"]["currency"],amount=str(money(sum(decimal(r["amount"]) for r in nightly),int(precision))),
                    units=len(nightly),explanation=[f"{r['date']}: {r['amount']} ({r['rules']['title']})" for r in nightly],
                    nightly=nightly,rules=nightly[0]["rules"],start=start.isoformat(),end=end.isoformat(),precision=int(precision))
    from hospitality_suite.item_configuration import bindings
    result["charge_items"]=bindings(prop)
    result["people"]=int(people)
    result["stay_type"]=requested_mode
    result["extra_beds"]=int(extra_beds)
    result["included_services"]=included_services(result)
    result["base_explanation"]=list(result["explanation"])
    from hospitality_suite.standalone_accounting import provider
    product_doctype, product_label = (("HS Product", "product_name") if provider() == "pms"
                                      else ("Item", "item_name"))
    for row in result["included_services"]:
        result["explanation"].append(_("Incluido: {0} × {1}",
            [frappe.db.get_value(product_doctype,row['item'],product_label) or row['item'],
             row['quantity']]))
    return result


def included_services(snapshot,night_only=False):
    """Night quantities accumulate; a stay benefit is granted once (largest plan
    allowance across its accepted nights). Room moves keep accepted benefits.
    """
    amounts={}
    once={}
    rules=[r["rules"] for r in snapshot.get("nightly",[])] or [snapshot["rules"]]
    for rule in rules:
        for service in rule.get("included_services",[]):
            item,quantity=service["item"],decimal(service["quantity"])
            if service["basis"]=="Night":
                amounts[item]=amounts.get(item,decimal(0))+quantity
            elif not night_only:
                once[item]=max(once.get(item,decimal(0)),quantity)
    return [dict(item=item,quantity=str(amounts.get(item,decimal(0))+once.get(item,decimal(0)))) for item in sorted(set(amounts)|set(once))]
