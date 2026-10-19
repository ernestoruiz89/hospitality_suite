import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from hospitality_suite.schema import WRITABLE


class ScopedDocument(Document):
    def validate(self):
        if self.meta.istable:
            return
        internal = bool(getattr(frappe.local, "hs_operation", False))
        if self.doctype not in WRITABLE and not internal:
            frappe.throw(_("Use las acciones de Hospitality Suite para modificar este documento"))
        if self.doctype == "HS Access":
            from hospitality_suite.security import is_system
            if not is_system():
                frappe.throw(_("Solamente administración del sistema puede conceder acceso"), frappe.PermissionError)
        if self.get("property"):
            prop = frappe.get_doc("HS Property", self.property)
            if self.company != prop.company:
                frappe.throw(_("La compañía no coincide con el establecimiento"))
            if not internal:
                from hospitality_suite.security import require
                require(self.property, "setup")
            for field in ("room", "category", "booking", "stay", "folio", "rate", "shift", "method", "guest"):
                value = self.get(field)
                df = self.meta.get_field(field)
                if value and df and df.fieldtype == "Link" and df.options.startswith("HS "):
                    other = frappe.db.get_value(df.options, value, "property")
                    if other != self.property:
                        frappe.throw(_("La referencia {0} pertenece a otro establecimiento").format(df.label))
        if self.get("starts_at") and self.get("ends_at"):
            if get_datetime(self.starts_at) >= get_datetime(self.ends_at):
                frappe.throw(_("La fecha final debe ser posterior a la inicial"))
        if self.doctype == "HS Property":
            from zoneinfo import ZoneInfo
            ZoneInfo(self.time_zone)
            if not internal:
                from hospitality_suite.security import require, is_system
                if self.is_new() and not is_system():
                    frappe.throw(_("La creación de establecimientos requiere administración del sistema"), frappe.PermissionError)
                if not self.is_new():
                    require(self.name, "setup")
            if self.financial_enabled:
                from hospitality_suite.install import validate_financial_configuration
                validate_financial_configuration(self)
        if self.doctype == "HS Rate":
            if self.amount < 0 or self.block_hours <= 0 or self.rounding_minutes <= 0:
                frappe.throw(_("Revise el precio, bloque y redondeo de la tarifa"))
        if self.doctype == "HS Room" and not self.is_new():
            old = self.get_doc_before_save()
            if old and (old.category != self.category or old.active != self.active):
                if frappe.db.exists("HS Allocation", {"room": self.name, "status": "Active"}):
                    frappe.throw(_("No puede cambiar categoría o disponibilidad con asignaciones activas"))
        if self.doctype == "HS Payment Method":
            account = frappe.get_doc("Account", self.account)
            if account.company != self.company or account.is_group or account.account_currency != self.currency:
                frappe.throw(_("La cuenta de cobro no coincide con compañía/moneda o es una cuenta agrupadora"))

    def on_trash(self):
        if self.doctype not in WRITABLE:
            frappe.throw(_("Conserve la trazabilidad: use una reversión autorizada"))
