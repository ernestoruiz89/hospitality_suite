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


def quote(prop, category, starts_at, ends_at, people=1, rate_name=None, customer=None):
    import frappe
    from hospitality_suite.time import local
    start, end = local(starts_at, prop), local(ends_at, prop)
    rates = frappe.get_all("HS Rate", filters={"property": prop.name, "category": category, "active": 1}, fields=["*"])
    if rate_name:
        rates = [r for r in rates if r.name == rate_name]
    rates = [r for r in rates if (not r.customer or r.customer == customer)
             and (not r.valid_from or r.valid_from <= start.date())
             and (not r.valid_to or r.valid_to >= end.date())
             and (not r.weekdays or all(str((start.date() + timedelta(days=i)).weekday()) in r.weekdays.split(",")
                                       for i in range(max(1, (end.date() - start.date()).days))))]
    rates.sort(key=lambda r: (-r.priority, -bool(r.customer), r.name))
    if not rates:
        frappe.throw("No existe una tarifa aplicable al intervalo y pagador")
    if len(rates) > 1 and (rates[0].priority, bool(rates[0].customer)) == (rates[1].priority, bool(rates[1].customer)):
        frappe.throw("Hay tarifas con la misma prioridad; defina una prioridad inequívoca")
    precision = frappe.db.get_single_value("System Settings", "currency_precision") or 2
    return calculate(rates[0], start, end, int(people), precision=int(precision))
