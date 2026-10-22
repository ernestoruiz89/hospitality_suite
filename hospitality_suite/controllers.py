import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from hospitality_suite.schema import WRITABLE


class DeferredRetentionFile:
    def _delete_file_on_disk(self):
        # Native File removes the metadata in the request transaction. Bytes are
        # removed only by the persisted retention job, after that transaction.
        if getattr(frappe.local,"hs_retention_run",None):
            return
        return super()._delete_file_on_disk()


class ScopedERPNotifications:
    def remove_items_with_no_change(self):
        if not (self.doctype=='Stock Reconciliation' and self.flags.get('hs_count_reviewed') and getattr(frappe.local,'hs_operation',False)
                and getattr(frappe.local,'hs_posting',False)):
            return super().remove_items_with_no_change()
        from hospitality_suite.security import require
        if getattr(frappe.local,'hs_selected_property',None)!=(self.hs_property,self.company):
            frappe.throw(_('El conteo no pertenece al establecimiento seleccionado'),frappe.PermissionError)
        require(self.hs_property,'approve')
        # ERPNext's native difference calculation calls a whitelisted balance
        # reader that checks general Stock Reconciliation write access even for
        # this delegated command. Delegate only this read/calculation; insert,
        # submit, ledger writes and audit still run as the approving actor.
        # Do not call set_user: it also replaces the request SID/data/form_dict.
        actor=frappe.session.user
        try:
            frappe.session.user='Administrator'
            return super().remove_items_with_no_change()
        finally:
            frappe.session.user=actor

    def validate_against_voucher_outstanding(self):
        if not (self.doctype=='Sales Invoice' and self.is_return and self.flags.get('hs_credit_reviewed') and getattr(frappe.local,'hs_operation',False) and getattr(frappe.local,'hs_posting',False)):
            return super().validate_against_voucher_outstanding()
        # Keep ERPNext's validation/state updates. This method only advises on
        # manual reconciliation, already explained by the accepted PMS review.
        # Frappe 16's mute_messages still raises validation exceptions.
        before=frappe.flags.mute_messages
        frappe.flags.mute_messages=True
        try:
            return super().validate_against_voucher_outstanding()
        finally:
            frappe.flags.mute_messages=before

    def notify_update(self):
        prop=self.get("hs_property")
        if any(frappe.flags.get(k) for k in ("in_import","in_patch","in_migrate","in_install")):
            return
        # Document subscriptions are authorized by Frappe for this exact document.
        # A global list_update would disclose its name/user to other properties.
        frappe.publish_realtime("doc_update",{"modified":self.modified,"doctype":self.doctype,"name":self.name},
                                doctype=self.doctype,docname=self.name,after_commit=True)
        from hospitality_suite.security import realtime
        if prop:
            realtime(prop)
        from frappe.permissions import has_permission
        for user in frappe.get_all("User",filters={"enabled":1,"user_type":"System User"},pluck="name"):
            if has_permission(self.doctype,"read",doc=self,user=user,print_logs=False):
                frappe.publish_realtime("list_update",{"doctype":self.doctype,"name":self.name,"user":frappe.session.user},user=user,after_commit=True)


class ScopedDocument(Document):
    def notify_update(self):
        from hospitality_suite.security import realtime
        prop=self.name if self.doctype=="HS Property" else self.get("property")
        if prop:
            realtime(prop)

    def validate(self):
        if self.meta.istable:
            return
        from hospitality_suite.security import check_selected_document
        check_selected_document(self)
        internal = bool(getattr(frappe.local, "hs_operation", False))
        if self.doctype not in WRITABLE and not internal:
            frappe.throw(_("Use las acciones de Hospitality Suite para modificar este documento"))
        if self.doctype == "HS Access":
            from hospitality_suite.security import is_system
            if not is_system():
                frappe.throw(_("Solamente administración del sistema puede conceder acceso"), frappe.PermissionError)
        if self.get("property"):
            prop = frappe.get_doc("HS Property", self.property,for_update=internal)
            if self.doctype=="HS Payment" and self.is_new():
                self.business_date=prop.business_date
                self.business_date_source="Recorded"
            if self.company != prop.company:
                frappe.throw(_("La compañía no coincide con el establecimiento"))
            if not internal:
                from hospitality_suite.security import require
                require(self.property, "setup")
                frappe.db.sql("SELECT name FROM `tabHS Property` WHERE name=%s FOR UPDATE",(self.property,))
            for field in ("room", "category", "booking", "stay", "folio", "rate", "shift", "method", "guest", "ticket"):
                value = self.get(field)
                df = self.meta.get_field(field)
                if value and df and df.fieldtype == "Link" and df.options.startswith("HS "):
                    other = frappe.db.get_value(df.options, value, "property")
                    if other != self.property:
                        frappe.throw(_("La referencia {0} pertenece a otro establecimiento").format(df.label))
        if self.doctype == 'HS Booking':
            partial = self.status == 'Draft' or (self.status == 'Cancelled' and self.get('draft_data') and not self.quote_snapshot)
            if not partial and any(not self.get(field) for field in ('customer','starts_at','ends_at','rooms')):
                frappe.throw(frappe._('Una reserva confirmada requiere pagador, entrada, salida y habitaciones'))
        if self.get("starts_at") and self.get("ends_at"):
            if get_datetime(self.starts_at) >= get_datetime(self.ends_at):
                frappe.throw(_("La fecha final debe ser posterior a la inicial"))
        if self.doctype=="HS Maintenance Order":
            if bool(self.until_reopened)==bool(self.ends_at):
                frappe.throw(_("Indique fin previsto o mantenimiento hasta reapertura autorizada"))
        if self.doctype=="HS Allocation" and not self.ends_at:
            order=frappe.db.get_value("HS Maintenance Order",self.maintenance,["property","until_reopened"],as_dict=True) if self.maintenance else None
            if self.kind!="Maintenance" or not order or order.property!=self.property or not order.until_reopened:
                frappe.throw(_("Solo un bloqueo de mantenimiento hasta reapertura puede omitir la fecha final"))
        if self.doctype == "HS Property":
            from hospitality_suite.financial_movements import validate_property
            validate_property(self, check_history=True)
            from hospitality_suite.service_accounting import validate_configuration
            validate_configuration(self)
            from hospitality_suite.time import cutoff_time
            cutoff_time(self.close_time)
            from hospitality_suite.pricing import decimal
            for prefix,label in [('cancellation',_('cancelación')),('no_show',_('no presentación'))]:
                value=decimal(self.get(prefix+'_fee_value'))
                if not value.is_finite() or value<0:
                    frappe.throw(_('La penalización por {0} debe ser un importe de cero o más.').format(label))
                if self.get(prefix+'_fee_mode')=='Percent' and value>100:
                    frappe.throw(_('El porcentaje de penalización por {0} debe estar entre 0 y 100.').format(label))
            if not 0<=(self.retention_days or 0)<=36500:
                frappe.throw(frappe._("La retención admite de 0 a 36500 días; cero desactiva el proceso"))
            from hospitality_suite.setup import validate_document_settings
            validate_document_settings(self)
            from zoneinfo import ZoneInfo
            try:
                ZoneInfo(self.time_zone)
            except (KeyError,ValueError):
                frappe.throw(frappe._("Seleccione una zona horaria IANA válida"))
            if self.cleaning_minutes<0 or not 1<=self.hold_minutes<=1440:
                frappe.throw(frappe._("Revise el margen de limpieza y la duración de las retenciones"))
            if (self.schedule_grace_minutes or 0)<0 or (self.schedule_rounding_minutes or 0)<=0 or (self.early_hour_rate or 0)<0 or (self.late_hour_rate or 0)<0 or not 1<=(self.checkout_quote_minutes or 0)<=60:
                frappe.throw(frappe._("Revise tolerancias, fracciones y cargos por horario"))
            if self.cash_denominations:
                from hospitality_suite.pricing import decimal
                values=frappe.parse_json(self.cash_denominations)
                if not isinstance(values,dict):
                    frappe.throw(frappe._("Revise las denominaciones de caja"))
                for currency,denominations in values.items():
                    if not frappe.db.exists("Currency",currency) or not isinstance(denominations,list) or not 1<=len(denominations)<=50 or any(decimal(v)<=0 for v in denominations):
                        frappe.throw(frappe._("Moneda o denominación inválida"))
            old=self.get_doc_before_save()
            if old and any(old.get(field)!=self.get(field) for field in ("advance_policy","guarantee_policy","lodging_charge_policy")):
                from hospitality_suite.security import require
                require(self.name,"approve")
            if old and frappe.utils.getdate(old.business_date)!=frappe.utils.getdate(self.business_date) and not internal:
                frappe.throw(frappe._("Cambie la fecha operativa mediante el cierre o la reapertura autorizada"))
            if old and (old.company!=self.company or old.currency!=self.currency):
                if frappe.db.exists("HS Room",{"property":self.name}) or frappe.db.exists("HS Booking",{"property":self.name}):
                    frappe.throw(frappe._("No cambie compañía o moneda de un establecimiento con datos; requiere una migración contable explícita"))
            if not internal:
                from hospitality_suite.security import require, is_system
                if self.is_new() and not is_system():
                    frappe.throw(_("La creación de establecimientos requiere administración del sistema"), frappe.PermissionError)
                if not self.is_new():
                    require(self.name, "setup")
            if self.financial_enabled:
                from hospitality_suite.install import validate_financial_configuration
                validate_financial_configuration(self)
            if self.portal_enabled:
                from frappe.utils.password import get_encryption_key
                get_encryption_key()
        if self.doctype == "HS Rate":
            from hospitality_suite.audit_trail import values
            previous=self.get_doc_before_save()
            reason=self.get('change_reason')
            if reason is not None and (not isinstance(reason,str) or len(reason)>1000):
                frappe.throw(_("Escriba un motivo de tarifa de hasta 1000 caracteres"))
            if previous and values(previous)!=values(self) and not (reason or '').strip():
                frappe.throw(_("Indique el motivo del cambio de tarifa"))
            if self.day_pass and self.mode!="Por tiempo":
                frappe.throw(frappe._("Day Pass requiere una tarifa por tiempo"))
            if self.day_pass and self.block_hours>24:
                frappe.throw(frappe._("El bloque Day Pass no puede superar 24 horas"))
            if self.get("property") and prop.financial_enabled and self.mode=="Por tiempo" and self.active and self.extra_hour_rate>0 and not prop.get("extra_hour_item"):
                frappe.throw(frappe._("Configure el artículo para horas adicionales por tiempo"))
            if self.amount < 0 or self.block_hours <= 0 or self.rounding_minutes <= 0 or (self.grace_minutes or 0)<0 or any((self.get(field) or 0)<0 for field in ("extra_hour_rate","extra_bed_rate","additional_person_rate")) or self.included_people<1:
                frappe.throw(_("Revise el precio, bloque y redondeo de la tarifa"))
            if self.valid_from and self.valid_to and self.valid_to<self.valid_from:
                frappe.throw(frappe._("El período de vigencia de la tarifa es inválido"))
            if bool(self.night_start)!=bool(self.night_end):
                frappe.throw(frappe._("Indique ambos límites del paquete nocturno"))
            if self.weekdays and any(day.strip() not in tuple(str(i) for i in range(7)) for day in self.weekdays.split(",")):
                frappe.throw(frappe._("Los días admitidos son 0 a 6"))
            from hospitality_suite.pricing import decimal
            keys=set()
            for row in self.included_services:
                if decimal(row.quantity)<=0 or (self.mode!="Hotel" and row.basis=="Night") or (row.item,row.basis) in keys:
                    frappe.throw(frappe._("Revise las cantidades de servicios incluidos; por noche solo aplica a hotel y no admite duplicados"))
                item=frappe.get_doc("Item",row.item)
                if item.disabled or not item.is_sales_item or item.is_fixed_asset:
                    frappe.throw(frappe._("El servicio incluido debe ser un artículo de venta habilitado"))
                keys.add((row.item,row.basis))
        if self.doctype=="HS Category":
            if self.capacity<1 or (self.max_extra_beds or 0)<0:
                frappe.throw(frappe._("Revise la capacidad y las camas extra de la categoría"))
            previous=self.get_doc_before_save()
            if not internal and any((previous.get(field) if previous else None)!=self.get(field) for field in ("portal_description","portal_image")):
                from hospitality_suite.security import require
                require(self.property,"setup")
            if len(self.portal_description or "")>500:
                frappe.throw(frappe._("La descripción pública admite hasta 500 caracteres"))
            image=self.portal_image
            if image and (not isinstance(image,str) or not re.fullmatch(r"/files/[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.(?:png|jpg|jpeg|webp|gif)",image,re.I)
                          or not frappe.db.exists("File",{"file_url":image,"is_private":0})):
                frappe.throw(frappe._("Seleccione una imagen pública existente en /files/"))
        if self.doctype == "HS Room" and not self.is_new():
            old = self.get_doc_before_save()
            if old and old.cleaning_status!=self.cleaning_status and not internal:
                frappe.throw(frappe._("Cambie el estado de limpieza desde la página de Limpieza"))
            if old and (old.category != self.category or old.active != self.active):
                if frappe.db.sql("SELECT name FROM `tabHS Allocation` WHERE room=%s AND status='Active' FOR UPDATE",(self.name,)):
                    frappe.throw(_("No puede cambiar categoría o disponibilidad con asignaciones activas"))
        if self.doctype == "HS Payment Method":
            from hospitality_suite.service import lock_property,current_all,operation
            lock_property(self.property)
            account = frappe.get_doc("Account", self.account)
            if account.company != self.company or account.is_group or account.account_currency != self.currency:
                frappe.throw(_("La cuenta de cobro no coincide con compañía/moneda o es una cuenta agrupadora"))
            old=self.get_doc_before_save()
            if old and any(old.get(k)!=self.get(k) for k in ("property","company","account","currency","is_cash","mode_of_payment")):
                from hospitality_suite.native_pos import method_used
                if frappe.db.exists("HS Payment",{"method":self.name}) or method_used(old):
                    frappe.throw(frappe._("Conserve el medio utilizado para la trazabilidad; cree otro para cambiar su cuenta, moneda o clasificación"))
            from hospitality_suite.treasury import validate_method
            validate_method(self)
            with operation():
                peers=current_all("HS Payment Method",filters={"property":self.property,"account":self.account,"name":["!=",self.name]},fields=["is_cash"])
            if any(bool(row.is_cash)!=bool(self.is_cash) for row in peers):
                frappe.throw(frappe._("Los medios que comparten una cuenta deben conservar la misma clasificación de efectivo"))
        if self.doctype=="HS Expense Category":
            account=frappe.get_doc("Account",self.account)
            self.currency=frappe.db.get_value("Company",self.company,"default_currency")
            if account.company!=self.company or account.is_group or account.root_type!="Expense" or account.account_currency!=self.currency or self.max_amount<0:
                frappe.throw(frappe._("Configure una cuenta de gasto de la compañía en moneda base y un límite no negativo"))
        if self.doctype=="HS Treasury Concept":
            from hospitality_suite.financial_movements import validate_concept
            validate_concept(self)
        if self.doctype=="HS Equipment":
            from hospitality_suite.equipment import validate_equipment
            validate_equipment(self)
        if self.doctype=="HS Payment" and self.is_new() and self.kind in ("Payment","Advance","Guarantee","Refund","Guarantee Refund"):
            from hospitality_suite.treasury import method_snapshot
            self.fee_snapshot=frappe.as_json(method_snapshot(frappe.get_doc("HS Payment Method",self.method),refund=self.kind in ("Refund","Guarantee Refund")))
        if self.doctype=="HS Billing Party" and (self.credit_limit<0 or not 0 <= (self.credit_days or 0) <= 365):
            frappe.throw(frappe._("Revise el límite y el plazo de crédito"))
        if self.doctype=="HS Folio":
            if not self.stay and not self.booking:
                frappe.throw(frappe._("Una cuenta debe pertenecer a una estancia o reserva grupal"))
            if self.stay and self.booking and frappe.db.get_value("HS Stay",self.stay,"booking")!=self.booking:
                frappe.throw(frappe._("La cuenta y la reserva no corresponden a la misma estancia"))

    def on_update(self):
        if self.doctype=='HS Rate':
            from hospitality_suite.audit_trail import rate_changed
            rate_changed(self)
        if self.doctype=='HS Room':
            from hospitality_suite.audit_trail import room_changed
            room_changed(self)

    def on_trash(self):
        if self.doctype=="HS Payment Method":
            from hospitality_suite.native_pos import method_used
            if method_used(self):
                frappe.throw(frappe._("Conserve el medio utilizado en facturas POS para la trazabilidad"))
        if self.doctype not in WRITABLE:
            frappe.throw(_("Conserve la trazabilidad: use una reversión autorizada"))
