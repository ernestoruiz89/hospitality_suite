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
        if self.doctype=="HS Allocation" and self.kind=="Room Block":
            if not self.room or not self.room_block or not self.ends_at or self.booking or self.stay or self.maintenance:
                frappe.throw(_("La asignación de bloqueo necesita habitación, origen e intervalo finito"))
            block=frappe.db.get_value("HS Room Block",self.room_block,["property","company","room","starts_at","ends_at"],as_dict=True)
            if (not block or (block.property,block.company,block.room)!=(self.property,self.company,self.room)
                    or get_datetime(self.starts_at)!=get_datetime(block.starts_at)
                    or get_datetime(self.ends_at)!=get_datetime(block.ends_at)):
                frappe.throw(_("La asignación no coincide con el bloqueo de habitación"))
        if self.doctype == "HS Property":
            currencies = [row.currency for row in self.accepted_currencies]
            if len(currencies) != len(set(currencies)) or len(currencies) > 12 or any(
                not frappe.db.exists("Currency", currency) for currency in currencies):
                frappe.throw(_("Revise las monedas habilitadas del establecimiento"))
            old_currencies = {row.currency for row in self.get_doc_before_save().accepted_currencies} if self.get_doc_before_save() else set()
            removed = old_currencies - set(currencies) - {self.currency}
            for currency in removed:
                if any(frappe.db.exists(doctype, {"property": self.name, field: currency}) for doctype, field in
                       (("HS Account", "account_currency"), ("HS Payment Method", "currency"),
                        ("HS Payment", "currency"), ("HS Shift", "currency"), ("HS Rate", "currency"),
                        ("HS Exchange Rate", "from_currency"))):
                    frappe.throw(_("No quite una moneda utilizada por cuentas u operaciones"))
                for shift in frappe.get_all("HS Shift", filters={"property": self.name, "status": "Open"},
                                            fields=["opening_by_currency"]):
                    if currency in frappe.parse_json(shift.opening_by_currency or "{}"):
                        frappe.throw(_("No quite una moneda utilizada por un turno abierto"))
            from hospitality_suite.standalone_accounting import provider
            if provider() == "erpnext":
                from hospitality_suite.financial_movements import validate_property
                validate_property(self, check_history=True)
                from hospitality_suite.service_accounting import validate_configuration
                validate_configuration(self)
            elif not self.organization or self.company != self.organization:
                frappe.throw(_("Seleccione la entidad legal propia del establecimiento"))
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
            from hospitality_suite.standalone_accounting import provider
            if provider() == "pms":
                from hospitality_suite.standalone_cash import validate_method
                validate_method(self)
                return
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
            from hospitality_suite.standalone_accounting import provider
            if provider() == "pms":
                from hospitality_suite.standalone_cash import validate_category
                validate_category(self)
                return
            account=frappe.get_doc("Account",self.account)
            self.currency=frappe.db.get_value("Company",self.company,"default_currency")
            if account.company!=self.company or account.is_group or account.root_type!="Expense" or account.account_currency!=self.currency or self.max_amount<0:
                frappe.throw(frappe._("Configure una cuenta de gasto de la compañía en moneda base y un límite no negativo"))
        if self.doctype=="HS Treasury Concept":
            from hospitality_suite.standalone_accounting import provider
            if provider() == "pms":
                from hospitality_suite.standalone_cash import validate_concept
                validate_concept(self)
                return
            from hospitality_suite.financial_movements import validate_concept
            validate_concept(self)
        if self.doctype=="HS Equipment":
            from hospitality_suite.equipment import validate_equipment
            validate_equipment(self)
        if self.doctype=="HS Payment" and self.is_new() and self.kind in ("Payment","Advance","Guarantee","Refund","Guarantee Refund"):
            from hospitality_suite.standalone_accounting import provider
            if provider() != "pms":
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


class OrganizationDocument(Document):
    """Legal entity master shared by properties in a single owner's site."""

    def validate(self):
        from hospitality_suite.security import is_system

        if not is_system():
            frappe.throw(_("Solo administración del sistema puede modificar entidades legales"), frappe.PermissionError)
        old = self.get_doc_before_save()
        if old and old.base_currency != self.base_currency and frappe.db.exists("HS Property", {"organization": self.name}):
            frappe.throw(_("La moneda de una entidad con establecimientos exige migración contable"))

    def on_trash(self):
        if frappe.db.exists("HS Property", {"organization": self.name}):
            frappe.throw(_("No puede borrar una entidad con establecimientos"))


class PMSModeDocument(Document):
    """Changing the ledger authority requires the migration service."""

    def validate(self):
        from hospitality_suite.security import is_system

        if not is_system():
            frappe.throw(_("Solo administración del sistema puede consultar el modo financiero"), frappe.PermissionError)
        previous = frappe.db.get_single_value("HS Site Mode", "provider")
        if previous and previous != self.provider and not getattr(frappe.local, "hs_provider_cutover", False):
            frappe.throw(_("El cambio de libro contable requiere una migración verificada"))


class PMSMasterDocument(ScopedDocument):
    """Scope standalone masters to their legal entity and property."""

    def validate(self):
        super().validate()
        prop = frappe.get_doc("HS Property", self.property)
        if not prop.organization or self.organization != prop.organization:
            frappe.throw(_("La entidad legal no coincide con el establecimiento"))
        for field in ("income_account", "expense_account", "inventory_account"):
            account_name = self.get(field)
            if account_name:
                account = frappe.db.get_value("HS Account", account_name,
                    ["property", "organization", "root_type", "is_group"], as_dict=True)
                expected = {"income_account": "Income", "expense_account": "Expense",
                            "inventory_account": "Asset"}[field]
                if not account or (account.property, account.organization) != (self.property, self.organization) or account.root_type != expected or account.is_group:
                    frappe.throw(_("La cuenta {0} debe corresponder al establecimiento y naturaleza contable").format(field))
        if self.doctype in ("HS Product", "HS Warehouse"):
            field = "product_code" if self.doctype == "HS Product" else "warehouse_code"
            code = (self.get(field) or "").strip()
            if not code or len(code) > 40:
                frappe.throw(_("Indique un código de hasta 40 caracteres"))
            if frappe.db.exists(self.doctype, {"property": self.property, field: code, "name": ["!=", self.name]}):
                frappe.throw(_("El código ya existe en este establecimiento"))
            self.set(field, code)
        if self.doctype == "HS Product" and (self.sales_rate or 0) < 0:
            frappe.throw(_("El precio no puede ser negativo"))


class PMSAccountDocument(PMSMasterDocument):
    def validate(self):
        super().validate()
        prop = frappe.get_doc("HS Property", self.property)
        if not self.account_currency:
            self.account_currency = prop.currency
        if not frappe.db.exists("Currency", self.account_currency):
            frappe.throw(_("Seleccione una moneda válida para la cuenta"))
        from hospitality_suite.standalone_currency import enabled
        if not enabled(prop, self.account_currency):
            frappe.throw(_("La moneda de la cuenta no está habilitada en el establecimiento"))
        if self.is_cash and self.is_bank:
            frappe.throw(_("Caja y banco requieren cuentas distintas"))
        if self.is_cash:
            self.account_type = "Cash"
        elif self.is_bank:
            self.account_type = "Bank"
        self.account_type = self.account_type or "General"
        expected_root = {"Cash": "Asset", "Bank": "Asset", "Receivable": "Asset",
                         "Stock": "Asset", "Fixed Asset": "Asset", "Accumulated Depreciation": "Asset",
                         "Asset Received But Not Billed": "Asset", "Capital Work in Progress": "Asset",
                         "Current Asset": "Asset", "Payable": "Liability", "Current Liability": "Liability",
                         "Liability": "Liability", "Stock Received But Not Billed": "Liability",
                         "Service Received But Not Billed": "Liability", "Equity": "Equity",
                         "Income Account": "Income", "Direct Income": "Income", "Indirect Income": "Income",
                         "Expense Account": "Expense", "Direct Expense": "Expense", "Indirect Expense": "Expense",
                         "Cost of Goods Sold": "Expense", "Depreciation": "Expense",
                         "Stock Adjustment": "Expense", "Expenses Included In Asset Valuation": "Expense",
                         "Expenses Included In Valuation": "Expense"}.get(self.account_type)
        if expected_root and self.root_type != expected_root:
            frappe.throw(_("El tipo de cuenta no coincide con su naturaleza contable"))
        self.is_cash = int(self.account_type == "Cash" and not self.is_group)
        self.is_bank = int(self.account_type == "Bank" and not self.is_group)
        code = (self.account_code or "").strip()
        if not code or len(code) > 40:
            frappe.throw(_("Indique un código contable de hasta 40 caracteres"))
        self.account_code = code
        if self.account_number and (not self.account_number.strip() or len(self.account_number.strip()) > 40):
            frappe.throw(_("El número de cuenta debe tener hasta 40 caracteres"))
        self.account_number = (self.account_number or "").strip()
        if self.account_number and frappe.db.exists("HS Account", {"property": self.property,
                                      "account_number": self.account_number, "name": ["!=", self.name]}):
            frappe.throw(_("El número de cuenta ERPNext ya existe en este establecimiento"))
        if frappe.db.exists("HS Account", {"property": self.property, "account_code": code, "name": ["!=", self.name]}):
            frappe.throw(_("El código contable ya existe en este establecimiento"))
        if self.is_cash and self.is_bank or (self.is_cash or self.is_bank) and self.root_type != "Asset":
            frappe.throw(_("Caja y banco requieren cuentas de activo distintas"))
        if self.parent_account:
            seen = {self.name}
            parent = self.parent_account
            while parent:
                if parent in seen:
                    frappe.throw(_("La jerarquía de cuentas contiene un ciclo"))
                seen.add(parent)
                row = frappe.db.get_value("HS Account", parent,
                    ["property", "organization", "root_type", "parent_account", "is_group"], as_dict=True)
                if not row or (row.property, row.organization, row.root_type) != (self.property, self.organization, self.root_type) or not row.is_group:
                    frappe.throw(_("La cuenta padre debe ser agrupadora de la misma entidad y naturaleza"))
                parent = row.parent_account
        old = self.get_doc_before_save()
        if old and old.active and not self.active and (
            frappe.db.exists("HS PMS Receivable", {"receivable_account": self.name}) or
            frappe.db.exists("HS Payment", {"pms_counter_account": self.name, "kind": "Advance",
                                            "status": "Posted"})):
            frappe.throw(_("La cuenta respalda saldos de clientes; configure otra cuenta para movimientos nuevos"))
        if old and old.is_group and not self.is_group and frappe.db.exists("HS Account", {"parent_account": self.name}):
            frappe.throw(_("No puede convertir en cuenta de movimiento una agrupadora con subcuentas"))
        if old and any(old.get(field) != self.get(field) for field in
                       ("property", "organization", "company", "account_code", "account_number", "root_type", "parent_account", "is_group", "account_type", "account_currency", "is_cash", "is_bank")):
            if frappe.db.exists("HS Journal Line", {"account": self.name}):
                frappe.throw(_("No cambie la identidad de una cuenta con movimientos"))


class PMSReceivableDocument(ScopedDocument):
    """An internal receivable is an immutable, posted business event."""

    def validate(self):
        super().validate()
        if not self.is_new():
            old = self.get_doc_before_save()
            if (not getattr(frappe.local, "hs_operation", False) or not old or
                    old.status != "Posted" or self.status != "Cancelled" or
                    any(old.get(field) != self.get(field) for field in
                        ("property", "company", "organization", "party", "reference", "description",
                         "business_date", "currency", "amount", "receivable_account",
                         "income_account", "journal")) or
                    frappe.db.exists("HS PMS Allocation", {"receivable": self.name})):
                frappe.throw(_("La cuenta por cobrar registrada es inmutable"))
            reversal = frappe.db.get_value("HS Journal", self.reversal_journal,
                ["property", "reversal_of"], as_dict=True)
            if not reversal or reversal.property != self.property or reversal.reversal_of != self.journal:
                frappe.throw(_("Se requiere el asiento inverso del cargo original"))
            return
        prop = frappe.get_doc("HS Property", self.property)
        if self.status != "Posted" or self.reversal_journal:
            frappe.throw(_("Un cargo nuevo debe quedar publicado sin reversión"))
        if (self.organization != prop.organization or self.currency != prop.currency or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("La entidad, moneda o fecha operativa no coincide"))
        party = frappe.db.get_value("HS Party", self.party,
            ["property", "active", "party_type"], as_dict=True)
        if not party or party.property != prop.name or not party.active or party.party_type not in ("Customer", "Both"):
            frappe.throw(_("Seleccione un cliente activo del establecimiento"))
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        try:
            if amount(self.amount) <= 0:
                frappe.throw(_("El cargo debe ser mayor que cero"))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        from hospitality_suite.standalone_accounting import account
        receivable = account(prop, self.receivable_account)
        income = account(prop, self.income_account)
        if (receivable.root_type != "Asset" or receivable.account_type != "Receivable" or
                income.root_type != "Income" or
                receivable.account_currency != prop.currency or income.account_currency != prop.currency or
                receivable.is_cash or receivable.is_bank):
            frappe.throw(_("Seleccione cuentas por cobrar e ingreso en moneda base"))
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "source_doctype", "source_name", "purpose"], as_dict=True)
        if not journal or (journal.property, journal.source_doctype, journal.source_name, journal.purpose) != (
                prop.name, "HS PMS Receivable", self.reference, "Receivable"):
            frappe.throw(_("El asiento del cargo no coincide"))

    def on_trash(self):
        frappe.throw(_("La cuenta por cobrar registrada no se borra"))


class PMSAllocationDocument(ScopedDocument):
    """A payment application is append only and cannot outlive its source."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("La aplicación de pago es inmutable"))
        prop = frappe.get_doc("HS Property", self.property)
        receivable = frappe.db.get_value("HS PMS Receivable", self.receivable,
            ["property", "organization", "party", "currency"], as_dict=True)
        payment = frappe.db.get_value("HS Payment", self.payment,
            ["property", "pms_party", "kind", "status", "pms_receivable", "pms_journal"], as_dict=True)
        if (not receivable or not payment or receivable.property != prop.name or
                payment.property != prop.name or receivable.organization != prop.organization or
                self.organization != prop.organization or self.currency != prop.currency or
                receivable.currency != prop.currency or receivable.party != payment.pms_party or
                payment.status != "Posted" or
                (self.kind == "Direct" and (payment.kind != "Payment" or
                                             payment.pms_receivable != self.receivable or
                                             self.journal != payment.pms_journal)) or
                (self.kind == "Advance Applied" and (payment.kind != "Advance" or not self.journal)) or
                self.kind not in ("Direct", "Advance Applied") or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("La aplicación no coincide con el cobro y la cuenta por cobrar"))
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        try:
            if amount(self.amount) <= 0:
                frappe.throw(_("La aplicación debe ser mayor que cero"))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if self.journal and frappe.db.get_value("HS Journal", self.journal, "property") != prop.name:
            frappe.throw(_("El asiento de aplicación pertenece a otro establecimiento"))

    def on_trash(self):
        frappe.throw(_("La aplicación de pago no se borra"))


class PMSJournalDocument(ScopedDocument):
    """Posted journals are append only; corrections are linked inverse journals."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("Un asiento publicado es inmutable; registre una reversión"))
        prop = frappe.get_doc("HS Property", self.property)
        if not prop.organization or self.organization != prop.organization:
            frappe.throw(_("La entidad legal no coincide con el establecimiento"))
        from hospitality_suite.ledger_rules import LedgerValidationError, currency_line, normalize_lines
        try:
            normalized, total = normalize_lines([{"account": row.account, "debit": row.debit,
                                                     "credit": row.credit} for row in self.lines],
                                                    frappe.utils.get_currency_precision() or 2)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        for row, line in zip(self.lines, normalized):
            account = frappe.db.get_value("HS Account", row.account,
                ["property", "organization", "account_currency", "active", "is_group"], as_dict=True)
            if not account or (account.property, account.organization) != (self.property, self.organization) or not account.active or account.is_group:
                frappe.throw(_("Cada línea requiere una cuenta activa del establecimiento"))
            if row.party and frappe.db.get_value("HS Party", row.party, "property") != self.property:
                frappe.throw(_("El tercero pertenece a otro establecimiento"))
            try:
                converted = currency_line({**line,
                    "account_currency": row.account_currency,
                    "exchange_rate": row.exchange_rate,
                    "debit_in_account_currency": row.debit_in_account_currency,
                    "credit_in_account_currency": row.credit_in_account_currency},
                    account.account_currency or prop.currency, prop.currency,
                    frappe.utils.get_currency_precision() or 2)
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
            row.debit, row.credit = line["debit"], line["credit"]
            row.account_currency = converted["account_currency"]
            row.exchange_rate = converted["exchange_rate"]
            row.debit_in_account_currency = converted["debit_in_account_currency"]
            row.credit_in_account_currency = converted["credit_in_account_currency"]
        self.total_debit = self.total_credit = total
        if self.reversal_of:
            original = frappe.db.get_value("HS Journal", self.reversal_of,
                ["property", "organization", "reversal_of"], as_dict=True)
            if not original or (original.property, original.organization) != (self.property, self.organization) or original.reversal_of:
                frappe.throw(_("El asiento original no es reversible en este establecimiento"))
            if frappe.db.exists("HS Journal", {"reversal_of": self.reversal_of}):
                frappe.throw(_("El asiento ya fue revertido"))

    def on_trash(self):
        frappe.throw(_("Los asientos publicados no se borran"))


class PMSExchangeRateDocument(ScopedDocument):
    """Approved rates are append only; posted movements freeze their chosen rate."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("Registre un nuevo tipo de cambio vigente en lugar de modificar el anterior"))
        prop = frappe.get_doc("HS Property", self.property)
        if self.organization != prop.organization or self.to_currency != prop.currency:
            frappe.throw(_("El tipo de cambio debe convertir a la moneda base del establecimiento"))
        from hospitality_suite.standalone_currency import enabled
        if not enabled(prop, self.from_currency) or self.from_currency == prop.currency:
            frappe.throw(_("Seleccione una moneda adicional habilitada"))
        from decimal import Decimal, InvalidOperation
        try:
            rate = Decimal(str(self.rate))
        except (InvalidOperation, TypeError, ValueError):
            rate = Decimal(0)
        if not rate.is_finite() or rate <= 0 or rate >= Decimal("1000000000"):
            frappe.throw(_("El tipo de cambio debe ser positivo y finito"))
        self.source = (self.source or "").strip()
        if not self.source or len(self.source) > 140:
            frappe.throw(_("Indique la fuente del tipo de cambio"))

    def on_trash(self):
        frappe.throw(_("Los tipos de cambio históricos no se borran"))


class PMSStockMovementDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("Un movimiento de inventario es inmutable; registre un movimiento compensador"))
        prop = frappe.get_doc("HS Property", self.property)
        if not prop.organization or self.organization != prop.organization:
            frappe.throw(_("La entidad legal no coincide con el establecimiento"))
        for doctype, field in (("HS Product", "product"), ("HS Warehouse", "warehouse")):
            row = frappe.db.get_value(doctype, self.get(field),
                ["property", "organization", "active"], as_dict=True)
            if not row or (row.property, row.organization) != (self.property, self.organization) or not row.active:
                frappe.throw(_("Producto o almacén fuera del establecimiento"))
        from decimal import Decimal
        quantity_delta = Decimal(str(self.quantity_delta))
        value_delta = Decimal(str(self.value_delta))
        if self.direction == "Receipt" and (quantity_delta <= 0 or value_delta <= 0):
            frappe.throw(_("La recepción requiere cantidad y costo positivos"))
        if self.direction == "Issue" and (quantity_delta >= 0 or value_delta >= 0):
            frappe.throw(_("La salida requiere cantidad y costo negativos"))
        if Decimal(str(self.balance_quantity)) < 0 or Decimal(str(self.balance_value)) < 0:
            frappe.throw(_("El inventario no puede quedar negativo"))
        from hospitality_suite.standalone_inventory import current_balance
        before_qty, before_value = current_balance(prop, self.product, self.warehouse)
        if (before_qty + Decimal(str(self.quantity_delta)) != Decimal(str(self.balance_quantity)) or
                before_value + Decimal(str(self.value_delta)) != Decimal(str(self.balance_value))):
            frappe.throw(_("El movimiento no concilia con el saldo de inventario"))
        if self.journal and frappe.db.get_value("HS Journal", self.journal, "property") != self.property:
            frappe.throw(_("El asiento pertenece a otro establecimiento"))

    def on_trash(self):
        frappe.throw(_("Los movimientos de inventario no se borran"))
