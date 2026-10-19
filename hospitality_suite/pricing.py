"""Pure decimal pricing kernel; persisted snapshots preserve accepted calculations."""
from datetime import timedelta, UTC
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING


def decimal(value):
    return Decimal(str(value or 0))


def money(value, precision=2):
    return decimal(value).quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)


def calculate(rate, start, end, people=1, extra_beds=0, precision=2):
    if end.astimezone(UTC) <= start.astimezone(UTC):
        raise ValueError("El fin debe ser posterior al inicio")
    if people < 1 or extra_beds < 0:
        raise ValueError("Ocupación inválida")
    details = []
    extra_people = max(0, int(people) - int(rate.get("included_people") or 2))
    extras = decimal(rate.get("additional_person_rate")) * extra_people + decimal(rate.get("extra_bed_rate")) * extra_beds
    if rate["mode"] == "Hotel":
        units = max(1, (end.date() - start.date()).days)
        subtotal = (decimal(rate["amount"]) + extras) * units
        details.append(f"{units} noche(s) × {decimal(rate['amount']) + extras}")
    else:
        elapsed = decimal((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()) / 60
        block = decimal(rate.get("block_hours") or 3) * 60
        beyond = max(Decimal(0), elapsed - block - decimal(rate.get("grace_minutes")))
        rounding = decimal(rate.get("rounding_minutes") or 60)
        extra_units = (beyond / rounding).to_integral_value(rounding=ROUND_CEILING)
        extra_amount = extra_units * rounding / 60 * decimal(rate.get("extra_hour_rate"))
        units = 1
        subtotal = decimal(rate["amount"]) + extras + extra_amount
        details.append(f"Bloque {block / 60} h: {rate['amount']}; {extra_units} fracción(es) de {rounding} min: {extra_amount}; personas/camas: {extras}")
    return dict(currency=rate["currency"], amount=str(money(subtotal, precision)), units=units,
                explanation=details, rules=dict(rate), start=start.isoformat(), end=end.isoformat(), precision=precision)


def quote(prop, category, starts_at, ends_at, people=1, rate_name=None, customer=None, mode=None,extra_beds=0):
    import frappe
    from hospitality_suite.service import current_all
    from hospitality_suite.time import local
    start, end = local(starts_at, prop), local(ends_at, prop)
    rates = current_all("HS Rate", filters={"property": prop.name, "category": category, "active": 1}, fields=["*"])
    if rate_name:
        rates = [r for r in rates if r.name == rate_name]
    selected_mode=mode or (prop.mode if prop.mode!="Mixed" else "Hotel")
    if prop.mode!="Mixed" and selected_mode!=prop.mode:
        frappe.throw("El establecimiento no permite esa modalidad")
    rates=[r for r in rates if r.mode==selected_mode and (not r.customer or r.customer==customer)]

    def choose(day):
        matches=[r for r in rates if (not r.valid_from or r.valid_from<=day) and (not r.valid_to or r.valid_to>=day)
                 and (not r.weekdays or str(day.weekday()) in [d.strip() for d in r.weekdays.split(",")])]
        if selected_mode=="Motel":
            from frappe.utils import get_time
            def in_window(r):
                if not r.night_start or not r.night_end:
                    return True
                a,b,t=get_time(r.night_start),get_time(r.night_end),start.time().replace(tzinfo=None)
                return (a<=t<b) if a<b else (t>=a or t<b)
            matches=[r for r in matches if in_window(r)]
        matches.sort(key=lambda r:(-r.priority,-bool(r.customer),r.name))
        if not matches:
            frappe.throw("No existe una tarifa aplicable a la fecha y al pagador")
        if len(matches)>1 and (matches[0].priority,bool(matches[0].customer))==(matches[1].priority,bool(matches[1].customer)):
            frappe.throw("Hay tarifas con la misma prioridad; defina una prioridad inequívoca")
        return matches[0]
    precision = frappe.db.get_single_value("System Settings", "currency_precision") or 2
    if selected_mode=="Motel":
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
            frappe.throw("Las tarifas por noche deben usar una sola moneda")
        result=dict(currency=nightly[0]["rules"]["currency"],amount=str(money(sum(decimal(r["amount"]) for r in nightly),int(precision))),
                    units=len(nightly),explanation=[f"{r['date']}: {r['amount']} ({r['rules']['title']})" for r in nightly],
                    nightly=nightly,rules=nightly[0]["rules"],start=start.isoformat(),end=end.isoformat(),precision=int(precision))
    result["people"]=int(people)
    result["extra_beds"]=int(extra_beds)
    return result
