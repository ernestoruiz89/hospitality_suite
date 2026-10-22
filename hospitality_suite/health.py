"""Read-only operational checks for authorized administrators."""
import shutil
from pathlib import Path

import frappe
from frappe.utils import now_datetime

from hospitality_suite.security import is_system, require


def snapshot(property_name):
    prop = require(property_name, "setup")
    if not is_system() and "HS Administrator" not in frappe.get_roles():
        frappe.throw(frappe._("La salud del sistema requiere administración"), frappe.PermissionError)
    checks = []

    def add(key, title, status, detail):
        checks.append(dict(key=key, title=title, status=status, detail=detail))

    try:
        frappe.db.sql("SELECT 1")
        add("database", "Base de datos", "OK", "Consulta de lectura correcta")
    except Exception:
        add("database", "Base de datos", "Error", "No respondió la consulta de lectura")
    try:
        from frappe.utils.scheduler import is_scheduler_inactive
        inactive = is_scheduler_inactive()
        add("scheduler", "Programador", "Warning" if inactive else "OK",
            "Inactivo: revise workers y programación" if inactive else "Activo")
    except Exception:
        add("scheduler", "Programador", "Unknown", "No se pudo verificar el estado desde esta versión")
    try:
        site = Path(frappe.get_site_path()).resolve()
        disk = shutil.disk_usage(site)
        free_percent = disk.free / disk.total * 100 if disk.total else 0
        add("disk", "Disco del sitio", "Warning" if free_percent < 10 else "OK",
            f"{free_percent:.1f}% libre")
    except Exception:
        add("disk", "Disco del sitio", "Unknown", "No se pudo medir espacio libre")
    required = {
        "company": "Compañía", "currency": "Moneda", "time_zone": "Zona horaria",
        "warehouse": "Almacén", "cost_center": "Centro de costo",
        "receivable_account": "Cuenta por cobrar", "guarantee_account": "Cuenta de garantías",
        "lodging_item": "Artículo de alojamiento", "tax_policy_confirmed": "Política tributaria confirmada",
    }
    missing = [label for field, label in required.items() if not prop.get(field)]
    add("configuration", "Configuración financiera", "Warning" if missing else "OK",
        "Falta: " + ", ".join(missing) if missing else "Campos básicos configurados")
    for key, title, dt, filters in (
        ("rooms", "Habitaciones", "HS Room", {"property": prop.name, "active": 1}),
        ("rates", "Tarifas", "HS Rate", {"property": prop.name, "active": 1}),
        ("payment_methods", "Medios de pago", "HS Payment Method", {"property": prop.name}),
    ):
        count = frappe.db.count(dt, filters)
        add(key, title, "OK" if count else "Warning", f"{count} configurados")
    return dict(property=prop.name, checked_at=str(now_datetime()),
                status="Error" if any(c["status"] == "Error" for c in checks) else
                       "Warning" if any(c["status"] == "Warning" for c in checks) else
                       "Unknown" if any(c["status"] == "Unknown" for c in checks) else "OK",
                checks=checks)
