from datetime import datetime, UTC
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, now_datetime


def aware(value, zone):
    value = get_datetime(value)
    if value.tzinfo:
        return value.astimezone(ZoneInfo(zone))
    # Reject ambiguous and nonexistent wall times rather than silently choosing a fold.
    first = value.replace(tzinfo=ZoneInfo(zone), fold=0)
    second = value.replace(tzinfo=ZoneInfo(zone), fold=1)
    if first.utcoffset() != second.utcoffset():
        frappe.throw("Hora ambigua o inexistente por cambio horario; indique un desplazamiento UTC explícito")
    if first.astimezone(UTC).astimezone(ZoneInfo(zone)).replace(tzinfo=None) != value:
        frappe.throw("Hora local inexistente")
    return first


def to_site(value, prop):
    return aware(value, prop.time_zone).astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def local(value, prop):
    return aware(value, get_system_timezone()).astimezone(ZoneInfo(prop.time_zone))


def now_local(prop):
    return local(now_datetime(), prop)
