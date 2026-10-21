from datetime import datetime, time as clock, timedelta, UTC
import re
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, now_datetime, getdate


def aware(value, zone):
    value = get_datetime(value)
    if value.tzinfo:
        return value.astimezone(ZoneInfo(zone))
    # Reject ambiguous and nonexistent wall times rather than silently choosing a fold.
    first = value.replace(tzinfo=ZoneInfo(zone), fold=0)
    second = value.replace(tzinfo=ZoneInfo(zone), fold=1)
    if first.utcoffset() != second.utcoffset():
        frappe.throw(frappe._("Hora ambigua o inexistente por cambio horario; indique un desplazamiento UTC explícito"))
    if first.astimezone(UTC).astimezone(ZoneInfo(zone)).replace(tzinfo=None) != value:
        frappe.throw(frappe._("Hora local inexistente"))
    return first


def to_site(value, prop):
    return aware(value, prop.time_zone).astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def local(value, prop):
    return aware(value, get_system_timezone()).astimezone(ZoneInfo(prop.time_zone))


def now_local(prop):
    return local(now_datetime(), prop)


def cutoff_time(value):
    """A wall-clock time, never a duration (Frappe get_time wraps 25:00)."""
    try:
        if value is None or value=="":
            value="06:00:00"
        if isinstance(value,timedelta):
            if not 0<=value.total_seconds()<86400:
                raise ValueError()
            result=(datetime.min+value).time()
        elif isinstance(value,clock):
            result=value
        else:
            text=str(value).removeprefix('T')
            # Python 3.14 accepts ISO 24:00 as 00:00, losing the entered hour.
            if re.match(r'^\d{2}',text) and int(text[:2])>=24:
                raise ValueError()
            result=clock.fromisoformat(re.sub(r"^(\d):",r"0\1:",text))
        if result.tzinfo:
            raise ValueError()
        return result
    except (ValueError,TypeError,OverflowError):
        frappe.throw(frappe._("Indique una hora de corte válida entre 00:00:00 y 23:59:59"))


def business_window(prop):
    """Operational date D covers [D at cutoff, D+1 at cutoff), in its zone.

    Construct each wall-time boundary independently: a DST day need not have
    24 elapsed hours. Advancing the operational date remains an explicit close.
    """
    day=getdate(prop.business_date)
    cutoff=cutoff_time(prop.get("close_time"))
    start=datetime.combine(day,cutoff)
    end=datetime.combine(day+timedelta(days=1),cutoff)
    return dict(starts_at=to_site(start,prop),ends_at=to_site(end,prop),
                local_starts_at=aware(start,prop.time_zone).isoformat(),
                local_ends_at=aware(end,prop.time_zone).isoformat(),
                close_time=cutoff.isoformat(),time_zone=prop.time_zone)
