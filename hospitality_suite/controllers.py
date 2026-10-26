import re
from hashlib import sha256
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime

from hospitality_suite.schema import WRITABLE


class DeferredRetentionFile:
    def on_trash(self):
        if self.attached_to_doctype == "HS Historical Fiscal Document":
            frappe.throw(_("El PDF fiscal histórico no admite eliminación"),
                         frappe.PermissionError)
        return super().on_trash()

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
        if self.doctype == "HS Guest":
            linked = frappe.db.get_value("HS Guest", self.name, "portal_user") if not self.is_new() else None
            if (self.portal_user or None) != (linked or None):
                frappe.throw(_("El acceso del huésped al portal se vincula con su enlace de reserva"),
                             frappe.PermissionError)
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
            if (self.doctype == 'HS Payment' and not self.is_new() and
                    frappe.db.exists('HS Day Pass', {
                        'erp_return_refund': self.name})):
                previous = self.get_doc_before_save()
                if (not previous or any(previous.get(field) != self.get(field)
                        for field in ('property', 'company', 'customer', 'shift',
                            'method', 'currency', 'amount', 'exchange_rate',
                            'base_amount', 'kind', 'status', 'payment_entry',
                            'sales_invoice', 'reference', 'reason'))):
                    frappe.throw(_('El reembolso histórico vinculado es inmutable'))
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
            if self.get('fee_receivable'):
                fee = frappe.db.get_value('HS PMS Receivable', self.fee_receivable,
                    ['property', 'booking', 'party', 'status'], as_dict=True)
                if (self.fee_invoice or not fee or fee.property != self.property or
                        fee.booking != self.name or fee.party != self.customer or
                        fee.status != 'Posted'):
                    frappe.throw(_('La penalización no coincide con la reserva y su cargo PMS'))
            if self.get('pms_agent_commission'):
                commission = frappe.db.get_value('HS PMS Agency Commission',
                    self.pms_agent_commission,
                    ['property', 'booking', 'agent', 'status'], as_dict=True)
                if (not commission or commission.property != self.property or
                        commission.booking != self.name or
                        commission.agent != self.travel_agent or
                        commission.status != 'Posted'):
                    frappe.throw(_('La comisión PMS no coincide con la reserva'))
        if self.doctype == 'HS Experience Order' and not self.booking:
            from hospitality_suite.standalone_accounting import provider
            if self.stay or self.folio or self.charge:
                frappe.throw(_('Una experiencia directa no pertenece a una estancia'))
            old = self.get_doc_before_save()
            core_fields = ('experience', 'customer', 'pms_product', 'item',
                           'quantity', 'unit_rate', 'amount', 'currency')
            accepted_fields = ('accepted_net', 'accepted_tax', 'accepted_total',
                               'accepted_tax_profile', 'income_account', 'tax_account')
            changed_accepted = bool(old and any(
                str(old.get(field) or '') != str(self.get(field) or '')
                for field in accepted_fields))
            legacy_freeze = bool(changed_accepted and provider() == 'pms' and
                getattr(frappe.local, 'hs_operation', False) and
                getattr(frappe.local, 'hs_legacy_direct_freeze', None) == self.name and
                not any(old.get(field) for field in accepted_fields) and
                old.status in ('Reserved', 'Confirmed') and
                self.status == old.status and not old.pms_receivable and
                not old.sales_invoice)
            if old and (any(str(old.get(field) or '') != str(self.get(field) or '')
                    for field in core_fields) or (changed_accepted and not legacy_freeze)):
                frappe.throw(_('No cambie el precio, impuesto o cuentas de una experiencia aceptada'))
            if provider() == 'pms':
                if self.item or self.sales_invoice:
                    frappe.throw(_('La experiencia PMS no debe tener factura ERPNext'))
                product = frappe.db.get_value('HS Product', self.pms_product,
                    ['property', 'organization', 'product_type', 'tax_profile'], as_dict=True)
                party = frappe.db.get_value('HS Party', self.customer,
                    ['property', 'organization', 'party_type'], as_dict=True)
                if (not product or not party or product.property != self.property or
                        party.property != self.property or product.organization != self.company or
                        party.organization != self.company or product.product_type != 'Service'):
                    frappe.throw(_('Revise el producto y cliente de la experiencia directa'))
                if self.is_new() or legacy_freeze:
                    from hospitality_suite.standalone_tax import tax_for_amount

                    net = Decimal(str(self.accepted_net or 0))
                    tax = Decimal(str(self.accepted_tax or 0))
                    total = Decimal(str(self.accepted_total or 0))
                    expected = tax_for_amount(
                        frappe.get_doc('HS Property', self.property),
                        self.accepted_tax_profile, self.amount)
                    income = frappe.db.get_value('HS Account', self.income_account,
                        ['property', 'organization', 'root_type'], as_dict=True)
                    tax_account = frappe.db.get_value('HS Account', self.tax_account,
                        ['property', 'organization', 'root_type'], as_dict=True) if self.tax_account else None
                    if (not self.accepted_tax_profile or
                            (self.is_new() and
                             self.accepted_tax_profile != product.tax_profile) or
                            net != Decimal(expected['net']) or
                            tax != Decimal(expected['tax']) or
                            total != Decimal(expected['total']) or
                            self.tax_account != expected['liability_account'] or
                            net <= 0 or tax < 0 or net + tax != total or
                            Decimal(str(self.amount or 0)) not in (net, total) or
                            not income or (income.property, income.organization,
                                income.root_type) != (self.property, self.company, 'Income') or
                            bool(tax) != bool(tax_account) or
                            (tax_account and (tax_account.property,
                                tax_account.organization, tax_account.root_type) !=
                                (self.property, self.company, 'Liability'))):
                        frappe.throw(_('Revise base, impuesto y cuentas de la experiencia'))
                if self.status == 'Delivered':
                    receivable = frappe.db.get_value('HS PMS Receivable', self.pms_receivable,
                        ['property', 'party', 'experience_order', 'status',
                         'amount', 'net_amount', 'tax_amount', 'income_account',
                         'tax_account', 'tax_profile'], as_dict=True)
                    if (not receivable or receivable.property != self.property or
                            receivable.party != self.customer or
                            receivable.experience_order != self.name or receivable.status != 'Posted'):
                        frappe.throw(_('La experiencia entregada requiere su cuenta por cobrar'))
                    if (self.accepted_total and
                            (Decimal(str(receivable.amount)) !=
                                Decimal(str(self.accepted_total)) or
                             Decimal(str(receivable.net_amount)) !=
                                Decimal(str(self.accepted_net or 0)) or
                             Decimal(str(receivable.tax_amount)) !=
                                Decimal(str(self.accepted_tax or 0)) or
                             receivable.income_account != self.income_account or
                             receivable.tax_account != self.tax_account or
                             (self.accepted_tax_profile and
                              receivable.tax_profile != self.accepted_tax_profile))):
                        frappe.throw(_('El cargo no conserva el precio e impuesto aceptados'))
                elif self.pms_receivable:
                    if self.status != 'Cancelled' or frappe.db.get_value('HS PMS Receivable',
                            self.pms_receivable, 'status') != 'Cancelled':
                        frappe.throw(_('La cuenta por cobrar no coincide con la experiencia'))
            else:
                if self.is_new():
                    frappe.throw(_('Las órdenes directas nuevas usan el flujo ERPNext'))
                if self.status in ('Reserved', 'Confirmed') and (
                        not self.item or not frappe.db.exists('Customer', self.customer)):
                    frappe.throw(_('La experiencia pendiente perdió cliente o artículo ERPNext'))
                if self.status == 'Delivered' and not self.pms_receivable:
                    invoice = frappe.db.get_value('Sales Invoice', self.sales_invoice,
                        ['docstatus', 'hs_property', 'customer', 'currency',
                         'grand_total', 'is_return'], as_dict=True)
                    if (not invoice or invoice.docstatus != 1 or invoice.is_return or
                            invoice.hs_property != self.property or
                            invoice.customer != self.customer or
                            invoice.currency != self.currency or
                            Decimal(str(invoice.grand_total)) !=
                                Decimal(str(self.accepted_total or 0))):
                        frappe.throw(_('La experiencia entregada requiere su factura ERPNext'))
                elif self.sales_invoice:
                    frappe.throw(_('La factura no corresponde al estado de la experiencia'))
        if self.doctype == 'HS Day Pass':
            from hospitality_suite.standalone_accounting import provider
            if not 1 <= (self.people or 0) <= 100:
                frappe.throw(_('Day Pass admite de una a cien personas'))
            if provider() == 'pms':
                prop = frappe.get_doc('HS Property', self.property)
                if (self.erp_opening_invoice or self.erp_opening_snapshot or
                        self.erp_opening_sha256 or self.erp_return_credit_note or
                        self.erp_return_refund):
                    frappe.throw(_('La continuación ERPNext no pertenece a un Day Pass PMS'))
                if self.opening_historical_invoice:
                    from hospitality_suite.standalone_day_pass import opening_sale
                    financial, historical_archive = opening_sale(prop, self)
                    if self.is_new():
                        if (not getattr(frappe.local, 'hs_reverse_opening', False) or
                                self.status != 'Issued' or self.opening_credit_note or
                                self.opening_refund or self.service or self.payment or
                                self.pms_receivable or self.quote_snapshot or
                                not self.sales_invoice or
                                frappe.db.exists('HS Day Pass', {
                                    'opening_historical_invoice':
                                        self.opening_historical_invoice})):
                            frappe.throw(_('El Day Pass histórico no conserva su factura y saldo'))
                    else:
                        old = self.get_doc_before_save()
                        credit = frappe.db.get_value('HS PMS Fiscal Document',
                            self.opening_credit_note,
                            ['property', 'historical_source_invoice',
                             'historical_day_pass', 'document_type', 'status',
                             'party', 'total_amount', 'journal'], as_dict=True)
                        refund = frappe.db.get_value('HS Payment',
                            self.opening_refund,
                            ['property', 'pms_historical_day_pass', 'kind',
                             'status', 'pms_party', 'base_amount', 'pms_journal'],
                            as_dict=True)
                        fixed = ('property', 'company', 'customer', 'guest', 'people',
                                 'starts_at', 'ends_at', 'service', 'sales_invoice',
                                 'payment', 'pms_receivable', 'quote_snapshot',
                                 'opening_historical_invoice', 'opening_financial',
                                 'opening_financial_sha256', 'notes')
                        if (not getattr(frappe.local,
                                        'hs_historical_day_pass_return', False) or
                                not old or old.status != 'Issued' or
                                self.status != 'Cancelled' or
                                old.opening_credit_note or old.opening_refund or
                                any(old.get(field) != self.get(field)
                                    for field in fixed) or not credit or not refund or
                                credit.property != prop.name or
                                credit.historical_source_invoice !=
                                    self.opening_historical_invoice or
                                credit.historical_day_pass != self.name or
                                credit.document_type != 'Credit Note' or
                                credit.status != 'Posted' or
                                credit.party != self.customer or
                                Decimal(str(credit.total_amount)) !=
                                    Decimal(str(financial['invoice_total'])) or
                                not credit.journal or refund.property != prop.name or
                                refund.pms_historical_day_pass != self.name or
                                refund.kind != 'Refund' or
                                refund.status != 'Posted' or
                                refund.pms_party != self.customer or
                                Decimal(str(refund.base_amount)) !=
                                    Decimal(str(financial['invoice_total'])) or
                                not refund.pms_journal):
                            frappe.throw(_('La cancelación histórica requiere nota y reembolso íntegros'))
                else:
                    receivable = frappe.db.get_value('HS PMS Receivable', self.pms_receivable,
                        ['property', 'organization', 'party', 'status', 'amount'], as_dict=True)
                    if (self.service or self.sales_invoice or self.payment or not receivable or
                            receivable.property != prop.name or
                            receivable.organization != prop.organization or
                            receivable.party != self.customer or not self.quote_snapshot or
                            self.opening_financial or self.opening_financial_sha256 or
                            self.opening_credit_note or self.opening_refund):
                        frappe.throw(_('El Day Pass PMS no coincide con su cargo contable'))
                    if self.status == 'Issued' and receivable.status != 'Posted':
                        frappe.throw(_('Un Day Pass vigente requiere un cargo publicado'))
                    if self.status == 'Cancelled':
                        from hospitality_suite.standalone_receivables import credited
                        if receivable.status != 'Cancelled' and not (
                                receivable.status == 'Posted' and
                                credited(prop, self.pms_receivable) == Decimal(str(receivable.amount))):
                            frappe.throw(_('Cancele o acredite íntegramente el cargo antes del Day Pass'))
                    elif self.status != 'Issued':
                        frappe.throw(_('Estado de Day Pass inválido'))
                    if self.is_new():
                        if frappe.db.exists('HS Day Pass', {'pms_receivable': self.pms_receivable}):
                            frappe.throw(_('El cargo ya pertenece a otro Day Pass'))
                    else:
                        old = self.get_doc_before_save()
                        if (not old or old.status != 'Issued' or self.status != 'Cancelled' or
                                any(old.get(field) != self.get(field) for field in
                                    ('property', 'company', 'customer', 'guest', 'people',
                                     'starts_at', 'ends_at', 'service', 'sales_invoice',
                                     'payment', 'pms_receivable', 'quote_snapshot', 'notes'))):
                            frappe.throw(_('El Day Pass emitido solo admite cancelación autorizada'))
            elif self.pms_receivable and self.quote_snapshot:
                old = self.get_doc_before_save()
                origin = ('property', 'company', 'customer', 'guest', 'people',
                         'starts_at', 'ends_at', 'service', 'sales_invoice',
                         'payment', 'pms_receivable', 'quote_snapshot',
                         'erp_opening_invoice', 'erp_opening_snapshot',
                         'erp_opening_sha256', 'notes')
                if (self.is_new() or not old or not self.erp_opening_snapshot or
                        not self.erp_opening_sha256 or
                        sha256(self.erp_opening_snapshot.encode()).hexdigest() !=
                            self.erp_opening_sha256 or
                        self.service or self.sales_invoice or self.payment or
                        self.opening_historical_invoice or self.opening_financial or
                        self.opening_financial_sha256 or self.opening_credit_note or
                        self.opening_refund or
                        any(old.get(field) != self.get(field) for field in origin)):
                    frappe.throw(_('El Day Pass trasladado conserva su origen y saldo inmutables'))
                if getattr(frappe.local,
                           'hs_erp_historical_day_pass_return', False):
                    from hospitality_suite.erp_historical_day_pass import _remaining
                    proof = frappe.parse_json(self.erp_opening_snapshot)
                    remaining = _remaining(proof)[2]
                    credit = frappe.db.get_value('Sales Invoice',
                        self.erp_return_credit_note,
                        ['name', 'company', 'hs_property', 'customer', 'docstatus',
                         'is_return', 'return_against', 'currency', 'grand_total',
                         'outstanding_amount'], as_dict=True)
                    refund = (frappe.db.get_value('HS Payment',
                        self.erp_return_refund,
                        ['property', 'company', 'customer', 'kind', 'status',
                         'sales_invoice', 'payment_entry', 'base_amount'],
                        as_dict=True) if self.erp_return_refund else None)
                    opening_due = Decimal(str(frappe.db.get_value(
                        'Sales Invoice', self.erp_opening_invoice,
                        'outstanding_amount') or 0))
                    if (old.status != 'Issued' or self.status != 'Cancelled' or
                            old.erp_return_credit_note or old.erp_return_refund or
                            not credit or credit.company != self.company or
                            credit.hs_property != self.property or
                            credit.customer != self.customer or
                            credit.docstatus != 1 or not credit.is_return or
                            credit.return_against or
                            credit.currency != frappe.db.get_value(
                                'HS Property', self.property, 'currency') or
                            Decimal(str(credit.grand_total)) != -remaining or
                            Decimal(str(credit.outstanding_amount)) != 0 or
                            opening_due != 0 or
                            bool(refund) != bool(self.erp_return_refund) or
                            (refund and (refund.property != self.property or
                                refund.company != self.company or
                                refund.customer != self.customer or
                                refund.kind != 'Refund' or
                                refund.status != 'Posted' or
                                refund.sales_invoice != credit.name or
                                not refund.payment_entry))):
                        frappe.throw(_('La cancelación histórica requiere nota y reembolso conciliados'))
                elif (old.status != self.status or
                        old.erp_return_credit_note != self.erp_return_credit_note or
                        old.erp_return_refund != self.erp_return_refund):
                    frappe.throw(_('El Day Pass trasladado solo admite devolución autorizada'))
            elif (not self.service or not self.sales_invoice or not self.payment or
                    self.pms_receivable or self.quote_snapshot or
                    self.erp_opening_invoice or self.erp_opening_snapshot or
                    self.erp_opening_sha256 or self.erp_return_credit_note or
                    self.erp_return_refund or self.opening_historical_invoice or
                    self.opening_financial or self.opening_financial_sha256 or
                    self.opening_credit_note or self.opening_refund):
                frappe.throw(_('El Day Pass ERPNext requiere venta, factura y cobro'))
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
            else:
                from hospitality_suite.item_configuration import validate_bindings
                validate_bindings(self)
                from hospitality_suite.standalone_petty_cash import validate_property as validate_petty_property
                validate_petty_property(self)
                from hospitality_suite.standalone_agency_commissions import validate_property as validate_agency_property
                validate_agency_property(self)
                from hospitality_suite.standalone_linen import validate_configuration as validate_linen_configuration
                validate_linen_configuration(self)
                from hospitality_suite.standalone_currency import validate_variance_account
                validate_variance_account(self)
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
            from hospitality_suite.standalone_accounting import provider
            keys=set()
            for row in self.included_services:
                if decimal(row.quantity)<=0 or (self.mode!="Hotel" and row.basis=="Night") or (row.item,row.basis) in keys:
                    frappe.throw(frappe._("Revise las cantidades de servicios incluidos; por noche solo aplica a hotel y no admite duplicados"))
                if provider() == "pms":
                    item = frappe.db.get_value("HS Product", row.item,
                        ["property", "organization", "active", "product_type"], as_dict=True)
                    if (not item or (item.property, item.organization) !=
                            (self.property, prop.organization) or not item.active or
                            item.product_type not in ("Service", "Stock")):
                        frappe.throw(frappe._("El servicio incluido debe ser un producto PMS activo del establecimiento"))
                else:
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
            if account.company!=self.company or account.is_group or account.disabled or account.root_type!="Expense" or account.account_currency!=self.currency or self.max_amount<0:
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
            from hospitality_suite.standalone_accounting import provider
            if provider() == "pms":
                party = frappe.db.get_value("HS Party", self.customer,
                    ["property", "organization", "party_type", "active"], as_dict=True)
                prop = frappe.get_doc("HS Property", self.property)
                if (not party or party.property != prop.name or
                        party.organization != prop.organization or not party.active or
                        party.party_type not in ("Customer", "Both") or
                        self.currency != prop.currency):
                    frappe.throw(frappe._("La cuenta de estancia PMS requiere un cliente activo y moneda base"))
        if self.doctype == "HS Charge" and self.pms_receivable:
            from hospitality_suite.standalone_accounting import provider
            if provider() != "pms" or self.status != "Posted" or self.sales_invoice:
                frappe.throw(frappe._("El cargo no conserva un estado PMS válido"))
            source = frappe.db.get_value("HS PMS Receivable", self.pms_receivable,
                ["property", "folio", "source_charge", "status"], as_dict=True)
            if (not source or source.property != self.property or source.folio != self.folio or
                    source.status != "Posted" or
                    (self.name != source.source_charge and
                     self.applies_to_charge != source.source_charge)):
                frappe.throw(frappe._("El cargo no coincide con su cuenta por cobrar PMS"))
        if (self.doctype == "HS Payment" and self.pms_opening_payable and
                self.kind != "Supplier Payment"):
            frappe.throw(_("El saldo inicial del proveedor solo admite pagos"))
        if self.doctype == "HS Payment" and self.kind == "Payment" and self.pms_receivable:
            receivable = frappe.db.get_value("HS PMS Receivable", self.pms_receivable,
                ["property", "organization", "party", "currency", "opening_source_name",
                 "receivable_account", "status"], as_dict=True)
            prop = frappe.get_doc("HS Property", self.property)
            if (not receivable or receivable.property != prop.name or
                    receivable.organization != prop.organization or
                    receivable.status != "Posted" or
                    receivable.party != self.pms_party or
                    receivable.receivable_account != self.pms_counter_account):
                frappe.throw(_("El cobro no coincide con la cuenta por cobrar"))
            if receivable.currency != prop.currency:
                if (not getattr(frappe.local, "hs_operation", False) or
                        not receivable.opening_source_name):
                    frappe.throw(_("El cobro extranjero requiere la operación de Suite"),
                                 frappe.PermissionError)
                settled = Decimal(str(self.pms_settled_amount or 0))
                released = Decimal(str(self.pms_released_base_amount or 0))
                cash_base = Decimal(str(self.base_amount or 0))
                if (self.pms_settlement_currency != receivable.currency or
                        settled <= 0 or released <= 0 or cash_base <= 0 or
                        bool(self.pms_exchange_variance_account) !=
                        bool(cash_base != released)):
                    frappe.throw(_("El cobro extranjero no conserva su liquidación"))
                prior = self.get_doc_before_save() if not self.is_new() else None
                if prior and prior.pms_journal and any(
                        str(prior.get(field) or "") != str(self.get(field) or "")
                        for field in ("pms_receivable", "pms_settlement_currency",
                            "pms_settled_amount", "pms_released_base_amount",
                            "pms_exchange_variance_account", "base_amount", "amount",
                            "currency", "exchange_rate", "method", "pms_counter_account",
                            "pms_party", "pms_journal", "status")):
                    frappe.throw(_("Un cobro extranjero contabilizado es inmutable"))
                if self.pms_journal:
                    journal = frappe.db.get_value("HS Journal", self.pms_journal,
                        ["property", "source_doctype", "source_name", "purpose",
                         "status"], as_dict=True)
                    method = frappe.db.get_value("HS Payment Method", self.method,
                        ["property", "account", "currency"], as_dict=True)
                    if (not journal or not method or
                            (journal.property, journal.source_doctype,
                             journal.source_name, journal.purpose, journal.status) !=
                            (prop.name, "HS Payment", self.name, "Payment", "Posted") or
                            method.property != prop.name or method.currency != self.currency):
                        frappe.throw(_("El asiento del cobro extranjero no coincide"))
                    expected = {
                        (method.account, None, cash_base, Decimal(0),
                         Decimal(str(self.amount)), Decimal(0)),
                        (receivable.receivable_account, receivable.party,
                         Decimal(0), released, Decimal(0), settled)}
                    difference = cash_base - released
                    if difference:
                        expected.add((self.pms_exchange_variance_account, None,
                            max(-difference, Decimal(0)), max(difference, Decimal(0)),
                            max(-difference, Decimal(0)), max(difference, Decimal(0))))
                    entries = frappe.get_all("HS Journal Line",
                        filters={"parent": self.pms_journal},
                        fields=["account", "party", "debit", "credit",
                                "debit_in_account_currency",
                                "credit_in_account_currency"])
                    actual = {(row.account, row.party,
                        Decimal(str(row.debit)), Decimal(str(row.credit)),
                        Decimal(str(row.debit_in_account_currency)),
                        Decimal(str(row.credit_in_account_currency)))
                        for row in entries}
                    if len(entries) != len(expected) or actual != expected:
                        frappe.throw(_("El asiento del cobro extranjero no concilia"))
            elif any(self.get(field) for field in ("pms_settlement_currency",
                    "pms_settled_amount", "pms_released_base_amount",
                    "pms_exchange_variance_account")):
                frappe.throw(_("El cobro en moneda base no usa liquidación extranjera"))
        if (self.doctype == "HS Payment" and self.kind == "Refund" and
                self.pms_settlement_currency and self.pms_receivable):
            source = frappe.db.get_value("HS Payment", self.source_payment,
                ["property", "kind", "status", "pms_journal", "pms_receivable",
                 "pms_party", "pms_counter_account", "pms_settlement_currency",
                 "pms_exchange_variance_account"], as_dict=True)
            receivable = frappe.db.get_value("HS PMS Receivable", self.pms_receivable,
                ["property", "organization", "party", "currency", "receivable_account",
                 "status"], as_dict=True)
            prop = frappe.get_doc("HS Property", self.property)
            method = frappe.db.get_value("HS Payment Method", self.method,
                ["property", "account", "currency", "is_cash"], as_dict=True)
            settled = Decimal(str(self.pms_settled_amount or 0))
            released = Decimal(str(self.pms_released_base_amount or 0))
            cash_base = Decimal(str(self.base_amount or 0))
            if (not getattr(frappe.local, "hs_operation", False) or
                    not source or not receivable or not method or
                    source.property != prop.name or source.kind != "Payment" or
                    source.status != "Posted" or not source.pms_journal or
                    source.pms_receivable != self.pms_receivable or
                    source.pms_party != self.pms_party or
                    source.pms_counter_account != self.pms_counter_account or
                    source.pms_settlement_currency != self.pms_settlement_currency or
                    source.pms_exchange_variance_account !=
                        self.pms_exchange_variance_account or
                    receivable.property != prop.name or
                    receivable.organization != prop.organization or
                    receivable.status != "Posted" or
                    receivable.party != self.pms_party or
                    receivable.currency != self.pms_settlement_currency or
                    receivable.receivable_account != self.pms_counter_account or
                    method.property != prop.name or method.currency != self.currency or
                    bool(self.shift) != bool(method.is_cash) or
                    settled <= 0 or released <= 0 or cash_base <= 0 or
                    (cash_base != released and not self.pms_exchange_variance_account)):
                frappe.throw(_("La devolución extranjera no coincide con el cobro original"))
            prior = self.get_doc_before_save() if not self.is_new() else None
            if prior and prior.pms_journal and any(
                    str(prior.get(field) or "") != str(self.get(field) or "")
                    for field in ("source_payment", "pms_receivable",
                        "pms_settlement_currency", "pms_settled_amount",
                        "pms_released_base_amount", "pms_exchange_variance_account",
                        "base_amount", "amount", "currency", "exchange_rate", "method",
                        "pms_counter_account", "pms_party", "pms_journal", "status")):
                frappe.throw(_("Una devolución extranjera contabilizada es inmutable"))
            if self.pms_journal:
                journal = frappe.db.get_value("HS Journal", self.pms_journal,
                    ["property", "source_doctype", "source_name", "purpose", "status"],
                    as_dict=True)
                if (not journal or (journal.property, journal.source_doctype,
                        journal.source_name, journal.purpose, journal.status) !=
                        (prop.name, "HS Payment", self.name, "Refund", "Posted")):
                    frappe.throw(_("El asiento de devolución extranjera no coincide"))
                difference = cash_base - released
                expected = {
                    (receivable.receivable_account, receivable.party, released,
                     Decimal(0), settled, Decimal(0)),
                    (method.account, None, Decimal(0), cash_base,
                     Decimal(0), Decimal(str(self.amount)))}
                if difference:
                    expected.add((self.pms_exchange_variance_account, None,
                        max(difference, Decimal(0)), max(-difference, Decimal(0)),
                        max(difference, Decimal(0)), max(-difference, Decimal(0))))
                entries = frappe.get_all("HS Journal Line",
                    filters={"parent": self.pms_journal},
                    fields=["account", "party", "debit", "credit",
                            "debit_in_account_currency", "credit_in_account_currency"])
                actual = {(row.account, row.party,
                    Decimal(str(row.debit)), Decimal(str(row.credit)),
                    Decimal(str(row.debit_in_account_currency)),
                    Decimal(str(row.credit_in_account_currency)))
                    for row in entries}
                if len(entries) != len(expected) or actual != expected:
                    frappe.throw(_("El asiento de devolución extranjera no concilia"))
        if (self.doctype == "HS Payment" and self.pms_opening_supplier_credit and
                self.kind != "Supplier Refund"):
            frappe.throw(_("El crédito inicial del proveedor solo admite reintegros"))
        if self.doctype == "HS Payment" and self.pms_opening_guarantee:
            opening = frappe.db.get_value("HS PMS Opening Guarantee",
                self.pms_opening_guarantee,
                ["property", "customer", "liability_account", "status"], as_dict=True)
            if (not getattr(frappe.local, "hs_opening_guarantee_refund", False) or
                    self.kind != "Guarantee Refund" or self.status != "Posted" or
                    self.source_payment or self.pms_opening_credit or
                    self.pms_opening_payable or self.pms_opening_supplier_credit or
                    self.pms_receivable or self.pms_purchase or self.pms_party or
                    self.folio or self.booking or not opening or
                    opening.property != self.property or opening.status != "Posted" or
                    opening.liability_account != self.pms_counter_account):
                frappe.throw(_("La devolución no coincide con la garantía inicial"))
        if self.doctype == "HS Payment" and self.pms_opening_credit:
            opening = frappe.db.get_value("HS PMS Opening Credit",
                self.pms_opening_credit,
                ["property", "customer", "receivable_account", "currency",
                 "status"], as_dict=True)
            if (not getattr(frappe.local, "hs_opening_credit_refund", False) or
                    self.kind != "Refund" or self.status != "Posted" or
                    self.source_payment or self.pms_receivable or self.pms_purchase or
                    self.pms_opening_payable or self.pms_opening_supplier_credit or
                    self.pms_agent_commission or
                    not opening or opening.property != self.property or
                    opening.status != "Posted" or
                    opening.customer != self.pms_party or
                    opening.receivable_account != self.pms_counter_account):
                frappe.throw(_("La devolución no coincide con el crédito inicial"))
            prop = frappe.get_doc("HS Property", self.property)
            if opening.currency != prop.currency:
                method = frappe.db.get_value("HS Payment Method", self.method,
                    ["property", "account", "currency", "is_cash"], as_dict=True)
                settled = Decimal(str(self.pms_settled_amount or 0))
                released = Decimal(str(self.pms_released_base_amount or 0))
                cash_base = Decimal(str(self.base_amount or 0))
                if (not method or method.property != prop.name or
                        method.currency != self.currency or
                        bool(self.shift) != bool(method.is_cash) or
                        self.pms_settlement_currency != opening.currency or
                        settled <= 0 or released <= 0 or cash_base <= 0 or
                        (cash_base != released and not
                         self.pms_exchange_variance_account)):
                    frappe.throw(_("La devolución extranjera del crédito no concilia"))
                prior = self.get_doc_before_save() if not self.is_new() else None
                if prior and prior.pms_journal and any(
                        str(prior.get(field) or "") != str(self.get(field) or "")
                        for field in ("pms_opening_credit", "pms_settlement_currency",
                            "pms_settled_amount", "pms_released_base_amount",
                            "pms_exchange_variance_account", "base_amount", "amount",
                            "currency", "exchange_rate", "method", "pms_counter_account",
                            "pms_party", "pms_journal", "status")):
                    frappe.throw(_("La devolución extranjera contabilizada es inmutable"))
                if self.pms_journal:
                    journal = frappe.db.get_value("HS Journal", self.pms_journal,
                        ["property", "source_doctype", "source_name", "purpose",
                         "status"], as_dict=True)
                    if (not journal or (journal.property, journal.source_doctype,
                            journal.source_name, journal.purpose, journal.status) !=
                            (prop.name, "HS Payment", self.name,
                             "Opening Credit Refund", "Posted")):
                        frappe.throw(_("El asiento de devolución del crédito no coincide"))
                    difference = cash_base - released
                    expected = {
                        (opening.receivable_account, opening.customer, released,
                         Decimal(0), settled, Decimal(0)),
                        (method.account, None, Decimal(0), cash_base,
                         Decimal(0), Decimal(str(self.amount)))}
                    if difference:
                        expected.add((self.pms_exchange_variance_account, None,
                            max(difference, Decimal(0)),
                            max(-difference, Decimal(0)),
                            max(difference, Decimal(0)),
                            max(-difference, Decimal(0))))
                    entries = frappe.get_all("HS Journal Line",
                        filters={"parent": self.pms_journal},
                        fields=["account", "party", "debit", "credit",
                                "debit_in_account_currency",
                                "credit_in_account_currency"])
                    actual = {(row.account, row.party,
                        Decimal(str(row.debit)), Decimal(str(row.credit)),
                        Decimal(str(row.debit_in_account_currency)),
                        Decimal(str(row.credit_in_account_currency)))
                        for row in entries}
                    if len(entries) != len(expected) or actual != expected:
                        frappe.throw(_("El asiento del crédito extranjero no concilia"))
            elif any(self.get(field) for field in ("pms_settlement_currency",
                    "pms_settled_amount", "pms_released_base_amount",
                    "pms_exchange_variance_account")):
                frappe.throw(_("La devolución en moneda base no usa principal extranjero"))
        if self.doctype == "HS Payment" and self.pms_historical_day_pass:
            from hospitality_suite.standalone_day_pass import opening_sale
            prop = frappe.get_doc("HS Property", self.property)
            day_pass = frappe.db.get_value("HS Day Pass",
                self.pms_historical_day_pass,
                ["name", "property", "customer", "status", "sales_invoice",
                 "opening_historical_invoice", "opening_financial",
                 "opening_financial_sha256"], as_dict=True)
            if (not getattr(frappe.local, "hs_historical_day_pass_return", False) or
                    not day_pass or day_pass.property != prop.name or
                    day_pass.status != "Issued" or self.kind != "Refund" or
                    self.status != "Posted" or self.pms_party != day_pass.customer or
                    self.source_payment or self.pms_receivable or self.pms_purchase or
                    self.pms_opening_credit or self.pms_opening_guarantee or
                    self.pms_opening_payable or self.pms_opening_supplier_credit or
                    self.folio or self.booking):
                frappe.throw(_("El reembolso no corresponde al Day Pass histórico"))
            financial, historical_archive = opening_sale(prop, day_pass)
            method = frappe.db.get_value("HS Payment Method", self.method,
                ["property", "account", "currency", "is_cash"], as_dict=True)
            if (not method or method.property != prop.name or
                    method.currency != self.currency or
                    self.pms_counter_account != financial["receivable_account"] or
                    Decimal(str(self.base_amount)) !=
                        Decimal(str(financial["invoice_total"])) or
                    bool(self.shift) != bool(method.is_cash)):
                frappe.throw(_("El reembolso altera el importe o las cuentas históricas"))
            if self.pms_journal:
                journal = frappe.db.get_value("HS Journal", self.pms_journal,
                    ["property", "organization", "status", "purpose",
                     "source_doctype", "source_name", "total_debit",
                     "total_credit"], as_dict=True)
                if (not journal or journal.property != prop.name or
                        journal.organization != prop.organization or
                        journal.status != "Posted" or
                        journal.purpose != "Historical Day Pass Refund" or
                        journal.source_doctype != "HS Payment" or
                        journal.source_name != self.name or
                        Decimal(str(journal.total_debit)) !=
                            Decimal(str(self.base_amount)) or
                        Decimal(str(journal.total_credit)) !=
                            Decimal(str(self.base_amount))):
                    frappe.throw(_("El reembolso no conserva su asiento"))
                entries = sorted((row.account, row.party or "",
                    Decimal(str(row.debit)), Decimal(str(row.credit)))
                    for row in frappe.get_doc("HS Journal", self.pms_journal).lines)
                expected = sorted([
                    (self.pms_counter_account, self.pms_party,
                     Decimal(str(self.base_amount)), Decimal(0)),
                    (method.account, "", Decimal(0),
                     Decimal(str(self.base_amount)))])
                if entries != expected:
                    frappe.throw(_("El asiento no coincide con la devolución histórica"))
        if self.doctype == "HS Payment" and self.kind in ("Supplier Payment", "Supplier Refund"):
            from hospitality_suite.standalone_accounting import provider
            if provider() == "pms":
                if self.pms_opening_supplier_credit:
                    opening = frappe.db.get_value("HS PMS Opening Supplier Credit",
                        self.pms_opening_supplier_credit,
                        ["property", "supplier", "payable_account", "currency",
                         "status"], as_dict=True)
                    if (not getattr(frappe.local, "hs_opening_supplier_credit_refund", False) or
                            self.kind != "Supplier Refund" or self.status != "Posted" or
                            self.pms_purchase or self.pms_purchase_return or
                            self.pms_opening_payable or self.pms_agent_commission or
                            self.source_payment or not opening or
                            opening.property != self.property or opening.status != "Posted" or
                            opening.supplier != self.pms_party or
                            opening.payable_account != self.pms_counter_account):
                        frappe.throw(_("El reintegro no coincide con el crédito inicial del proveedor"))
                    prop = frappe.get_doc("HS Property", self.property)
                    if opening.currency != prop.currency:
                        if not getattr(frappe.local, "hs_operation", False):
                            frappe.throw(_("El reintegro extranjero requiere la operación de Suite"),
                                         frappe.PermissionError)
                        settled = Decimal(str(self.pms_settled_amount or 0))
                        released = Decimal(str(self.pms_released_base_amount or 0))
                        cash_base = Decimal(str(self.base_amount or 0))
                        if (self.pms_settlement_currency != opening.currency or
                                settled <= 0 or released <= 0 or cash_base <= 0 or
                                bool(self.pms_exchange_variance_account) !=
                                bool(cash_base != released)):
                            frappe.throw(_("El reintegro extranjero no conserva su liquidación"))
                        prior = self.get_doc_before_save() if not self.is_new() else None
                        if prior and prior.pms_journal and any(
                                str(prior.get(field) or "") != str(self.get(field) or "")
                                for field in ("pms_opening_supplier_credit",
                                    "pms_settlement_currency", "pms_settled_amount",
                                    "pms_released_base_amount",
                                    "pms_exchange_variance_account", "base_amount",
                                    "amount", "currency", "exchange_rate", "method",
                                    "pms_counter_account", "pms_party", "pms_journal",
                                    "status")):
                            frappe.throw(_("Un reintegro extranjero contabilizado es inmutable"))
                        if self.pms_journal:
                            journal = frappe.db.get_value("HS Journal", self.pms_journal,
                                ["property", "source_doctype", "source_name",
                                 "purpose", "status"], as_dict=True)
                            method = frappe.db.get_value("HS Payment Method", self.method,
                                ["property", "account", "currency"], as_dict=True)
                            if (not journal or not method or
                                    (journal.property, journal.source_doctype,
                                     journal.source_name, journal.purpose,
                                     journal.status) !=
                                    (prop.name, "HS Payment", self.name,
                                     "Opening Supplier Credit Refund", "Posted") or
                                    method.property != prop.name or
                                    method.currency != self.currency):
                                frappe.throw(_("El asiento del reintegro extranjero no coincide"))
                            difference = cash_base - released
                            expected = {
                                (method.account, None, cash_base, Decimal(0),
                                 Decimal(str(self.amount)), Decimal(0)),
                                (opening.payable_account, opening.supplier,
                                 Decimal(0), released, Decimal(0), settled)}
                            if difference:
                                expected.add((self.pms_exchange_variance_account,
                                    None, max(-difference, Decimal(0)),
                                    max(difference, Decimal(0)),
                                    max(-difference, Decimal(0)),
                                    max(difference, Decimal(0))))
                            entries = frappe.get_all("HS Journal Line",
                                filters={"parent": self.pms_journal},
                                fields=["account", "party", "debit", "credit",
                                    "debit_in_account_currency",
                                    "credit_in_account_currency"])
                            actual = {(row.account, row.party,
                                Decimal(str(row.debit)), Decimal(str(row.credit)),
                                Decimal(str(row.debit_in_account_currency)),
                                Decimal(str(row.credit_in_account_currency)))
                                for row in entries}
                            if len(entries) != len(expected) or actual != expected:
                                frappe.throw(_("El asiento del reintegro extranjero no concilia"))
                    elif any(self.get(field) for field in (
                            "pms_settlement_currency", "pms_settled_amount",
                            "pms_released_base_amount",
                            "pms_exchange_variance_account")):
                        frappe.throw(_("El reintegro en moneda base no usa conversión"))
                elif self.pms_opening_payable:
                    opening = frappe.db.get_value("HS PMS Opening Payable",
                        self.pms_opening_payable,
                        ["property", "supplier", "payable_account", "currency",
                         "status"], as_dict=True)
                    if (self.kind != "Supplier Payment" or self.pms_purchase or
                            self.pms_purchase_return or self.pms_agent_commission or
                            self.pms_opening_supplier_credit or
                            not opening or opening.property != self.property or
                            opening.status != "Posted" or
                            opening.supplier != self.pms_party or
                            opening.payable_account != self.pms_counter_account):
                        frappe.throw(_("El pago no coincide con la deuda inicial del proveedor"))
                    prop = frappe.get_doc("HS Property", self.property)
                    if opening.currency != prop.currency:
                        if not getattr(frappe.local, "hs_operation", False):
                            frappe.throw(_("El pago extranjero requiere la operación de Suite"),
                                         frappe.PermissionError)
                        settled = Decimal(str(self.pms_settled_amount or 0))
                        released = Decimal(str(self.pms_released_base_amount or 0))
                        cash_base = Decimal(str(self.base_amount or 0))
                        if (self.pms_settlement_currency != opening.currency or
                                settled <= 0 or released <= 0 or cash_base <= 0 or
                                bool(self.pms_exchange_variance_account) !=
                                bool(cash_base != released)):
                            frappe.throw(_("El pago extranjero no conserva su liquidación"))
                        prior = self.get_doc_before_save() if not self.is_new() else None
                        if prior and prior.pms_journal:
                            frozen = ("pms_opening_payable", "pms_settlement_currency",
                                      "pms_settled_amount", "pms_released_base_amount",
                                      "pms_exchange_variance_account", "base_amount",
                                      "amount", "currency", "exchange_rate", "method",
                                      "pms_counter_account", "pms_party", "pms_journal",
                                      "status")
                            if any(str(prior.get(field) or "") !=
                                    str(self.get(field) or "") for field in frozen):
                                frappe.throw(_("Un pago extranjero contabilizado es inmutable"))
                        if self.pms_journal:
                            journal = frappe.db.get_value("HS Journal", self.pms_journal,
                                ["property", "source_doctype", "source_name", "purpose",
                                 "status"], as_dict=True)
                            method = frappe.db.get_value("HS Payment Method", self.method,
                                ["property", "account", "currency"], as_dict=True)
                            if (not journal or not method or
                                    (journal.property, journal.source_doctype,
                                     journal.source_name, journal.purpose,
                                     journal.status) !=
                                    (prop.name, "HS Payment", self.name,
                                     "Supplier Payment", "Posted") or
                                    method.property != prop.name or
                                    method.currency != self.currency):
                                frappe.throw(_("El asiento del pago extranjero no coincide"))
                            entries = frappe.get_all("HS Journal Line",
                                filters={"parent": self.pms_journal},
                                fields=["account", "party", "debit", "credit",
                                        "debit_in_account_currency",
                                        "credit_in_account_currency"])
                            difference = cash_base - released
                            expected = {
                                (opening.payable_account, opening.supplier,
                                 released, Decimal(0), settled, Decimal(0)),
                                (method.account, None, Decimal(0), cash_base,
                                 Decimal(0), Decimal(str(self.amount)))}
                            if difference:
                                expected.add((self.pms_exchange_variance_account,
                                    None, max(difference, Decimal(0)),
                                    max(-difference, Decimal(0)),
                                    max(difference, Decimal(0)),
                                    max(-difference, Decimal(0))))
                            actual = {(row.account, row.party,
                                Decimal(str(row.debit)), Decimal(str(row.credit)),
                                Decimal(str(row.debit_in_account_currency)),
                                Decimal(str(row.credit_in_account_currency)))
                                for row in entries}
                            if len(entries) != len(expected) or actual != expected:
                                frappe.throw(_("El asiento del pago extranjero no concilia"))
                elif self.pms_agent_commission:
                    commission = frappe.db.get_value("HS PMS Agency Commission",
                        self.pms_agent_commission,
                        ["property", "supplier", "payable_account", "status"], as_dict=True)
                    if (self.kind != "Supplier Payment" or self.pms_purchase or
                            self.pms_purchase_return or not commission or
                            commission.property != self.property or
                            commission.status != "Posted" or
                            commission.supplier != self.pms_party or
                            commission.payable_account != self.pms_counter_account):
                        frappe.throw(frappe._("El pago no coincide con la comisión de agencia PMS"))
                else:
                    purchase = frappe.db.get_value("HS PMS Purchase", self.pms_purchase,
                        ["property", "supplier", "payable_account", "status"], as_dict=True)
                    if (not purchase or purchase.property != self.property or
                            purchase.status != "Posted" or purchase.supplier != self.pms_party or
                            purchase.payable_account != self.pms_counter_account):
                        frappe.throw(frappe._("El pago no coincide con la compra y el proveedor PMS"))
                    if self.kind == "Supplier Refund":
                        returned = frappe.db.get_value("HS PMS Purchase Return",
                            self.pms_purchase_return,
                            ["property", "purchase", "supplier", "status"], as_dict=True)
                        if (not returned or returned.property != self.property or
                                returned.purchase != self.pms_purchase or
                                returned.supplier != self.pms_party or returned.status != "Posted"):
                            frappe.throw(frappe._("El reintegro no coincide con la devolución del proveedor"))
                    elif self.pms_purchase_return:
                        frappe.throw(frappe._("Un pago al proveedor no usa una devolución"))

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


class MaintenanceOrderDocument(ScopedDocument):
    def validate(self):
        super().validate()
        previous = self.get_doc_before_save()
        old_parts = {part.name: part for part in previous.parts} if previous else {}
        current_parts = {part.name: part for part in self.parts}
        for part in self.parts:
            if (part.opening_stock_issue and part.name not in old_parts and
                    not getattr(frappe.local, "hs_reverse_opening", False)):
                frappe.throw(_("Una salida histórica solo se incorpora durante la apertura verificada"),
                             frappe.PermissionError)
        for old in old_parts.values():
            if not old.opening_stock_issue:
                continue
            current = current_parts.get(old.name)
            if not current or any(str(current.get(field) or "") !=
                    str(old.get(field) or "") for field in
                    ("item", "quantity", "cost", "stock_entry",
                     "opening_stock_issue")):
                frappe.throw(_("El costo y origen del repuesto histórico son inmutables"))
            if current.status != old.status and not (
                    old.status == "Issued" and current.status == "Returned" and
                    getattr(frappe.local, "hs_historical_maintenance_return", False)):
                frappe.throw(_("La devolución del repuesto histórico requiere su asiento"))


class ServiceRequestDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if self.pms_receivable:
            from hospitality_suite.standalone_accounting import provider
            property_scope = frappe.db.get_value("HS Property", self.property,
                ["organization", "company"], as_dict=True)
            source = frappe.db.get_value("HS PMS Receivable", self.pms_receivable,
                ["property", "organization", "party", "source_service", "amount",
                 "status"], as_dict=True)
            fiscal = frappe.db.get_value("HS PMS Fiscal Document", self.pms_fiscal_invoice,
                ["property", "document_type", "party", "total_amount", "status"],
                as_dict=True) if self.pms_fiscal_invoice else None
            proof = None
            if self.erp_cutover_snapshot:
                if (provider() != "erpnext" or not self.erp_cutover_sha256 or
                        sha256(self.erp_cutover_snapshot.encode()).hexdigest() !=
                            self.erp_cutover_sha256):
                    frappe.throw(_("La prueba histórica de la venta no concilia"))
                proof = frappe.parse_json(self.erp_cutover_snapshot)
                if (not isinstance(proof, dict) or
                        proof.get("source") != self.name or
                        proof.get("property") != self.property or
                        proof.get("company") != self.company or
                        proof.get("customer") != self.customer or
                        proof.get("item_code") != self.item or
                        proof.get("source_receivable") != self.pms_receivable or
                        proof.get("source_invoice") != self.pms_fiscal_invoice or
                        Decimal(proof.get("total_amount") or "0") !=
                            Decimal(str(self.amount))):
                    frappe.throw(_("La venta no coincide con su prueba de corte"))
            if (provider() not in ("pms", "erpnext") or not property_scope or
                    not source or not fiscal or
                    self.stay or self.folio or self.charge or self.included or
                    self.opening_stock_issue or self.status not in ("Delivered", "Returned") or
                    self.sales_invoice or (self.credit_note and not proof) or
                    not self.pms_party or not self.pms_product or
                    source.property != self.property or
                    source.organization != property_scope.organization or
                    source.party != self.pms_party or source.source_service != self.name or
                    source.status != "Posted" or
                    Decimal(str(source.amount)) != Decimal(str(self.amount)) or
                    fiscal.property != self.property or fiscal.document_type != "Invoice" or
                    fiscal.party != self.pms_party or fiscal.status != "Posted" or
                    Decimal(str(fiscal.total_amount)) != Decimal(str(self.amount)) or
                    not frappe.db.exists("HS PMS Fiscal Line", {
                        "parent": self.pms_fiscal_invoice,
                        "receivable": self.pms_receivable})):
                frappe.throw(_("La venta directa PMS no conserva su cargo y factura"))
            payment = frappe.db.get_value("HS Payment", {
                "property": self.property, "service": self.name,
                "pms_receivable": self.pms_receivable, "kind": "Payment",
                "status": "Posted"}, ["name", "pms_journal"], as_dict=True)
            if not payment or not payment.pms_journal:
                frappe.throw(_("La venta directa PMS requiere su cobro publicado"))
            if self.status == "Delivered" and (
                    self.pms_fiscal_credit or self.return_stock_entry or
                    self.credit_note or self.erp_return_refund):
                frappe.throw(_("La venta vigente no puede tener devolución"))
            if self.status == "Returned":
                if self.pms_fiscal_credit:
                    credit = frappe.db.get_value("HS PMS Fiscal Document", self.pms_fiscal_credit,
                        ["property", "document_type", "source_invoice", "total_amount",
                         "status"], as_dict=True)
                    refunded = frappe.db.exists("HS Payment", {
                        "property": self.property, "source_payment": payment.name,
                        "pms_receivable": self.pms_receivable,
                        "kind": "Refund", "status": "Posted"})
                    if (not credit or credit.property != self.property or
                            credit.document_type != "Credit Note" or
                            credit.source_invoice != self.pms_fiscal_invoice or
                            credit.status != "Posted" or
                            Decimal(str(credit.total_amount)) != Decimal(str(self.amount)) or
                            not refunded or self.credit_note or self.erp_return_refund or
                            bool(self.stock_entry) != bool(self.return_stock_entry)):
                        frappe.throw(_("La devolución no conserva nota, reembolso e inventario"))
                else:
                    native = frappe.db.get_value("Sales Invoice", self.credit_note,
                        ["name", "company", "hs_property", "customer", "docstatus",
                         "is_return", "grand_total"], as_dict=True) if self.credit_note else None
                    refund = frappe.db.get_value("HS Payment", self.erp_return_refund,
                        ["property", "company", "kind", "status", "source_payment",
                         "payment_entry", "sales_invoice"], as_dict=True) if self.erp_return_refund else None
                    stock = frappe.db.get_value("Stock Entry", self.return_stock_entry,
                        ["company", "hs_property", "docstatus", "stock_entry_type"],
                        as_dict=True) if self.return_stock_entry else None
                    if (not proof or not native or not refund or
                            native.company != self.company or
                            native.hs_property != self.property or
                            native.customer != self.customer or native.docstatus != 1 or
                            not native.is_return or
                            Decimal(str(native.grand_total)) !=
                                -Decimal(str(self.amount)) or
                            refund.property != self.property or
                            refund.company != self.company or
                            refund.kind != "Refund" or refund.status != "Posted" or
                            refund.source_payment != payment.name or
                            not refund.payment_entry or
                            refund.sales_invoice != native.name or
                            bool(stock) != bool(proof.get("stock")) or
                            (stock and (stock.company != self.company or
                                stock.hs_property != self.property or
                                stock.docstatus != 1 or
                                stock.stock_entry_type != "Material Receipt"))):
                        frappe.throw(_("La devolución ERPNext no conserva nota, reembolso e inventario"))
        previous = self.get_doc_before_save()
        if previous and previous.pms_receivable:
            from hospitality_suite.service import canonical

            immutable = ("pms_receivable", "pms_party", "pms_product",
                "pms_fiscal_invoice", "sales_invoice", "stock_entry",
                "customer", "item", "warehouse", "quantity", "amount",
                "currency", "stay", "folio", "charge", "included",
                "opening_stock_issue", "erp_cutover_snapshot",
                "erp_cutover_sha256")
            native_transition = (previous.status == "Delivered" and
                self.status == "Returned" and
                getattr(frappe.local, "hs_erp_historical_direct_return", False))
            native_reversal = (previous.status == "Returned" and
                self.status == "Delivered" and not previous.pms_fiscal_credit and
                getattr(frappe.local, "hs_erp_historical_direct_reversal", None)
                    == self.name)
            old_history = (frappe.parse_json(previous.erp_return_corrections)
                if previous.erp_return_corrections else [])
            new_history = (frappe.parse_json(self.erp_return_corrections)
                if self.erp_return_corrections else [])
            if (not isinstance(old_history, list) or
                    not isinstance(new_history, list) or
                    bool(self.erp_return_corrections) !=
                        bool(self.erp_return_corrections_sha256) or
                    (self.erp_return_corrections and
                     sha256(self.erp_return_corrections.encode()).hexdigest() !=
                        self.erp_return_corrections_sha256)):
                frappe.throw(_("El historial de correcciones no concilia"))
            if native_reversal:
                last = new_history[-1] if new_history else None
                if (new_history[:-1] != old_history or not isinstance(last, dict) or
                        last.get("credit_note") != previous.credit_note or
                        last.get("refund") != previous.erp_return_refund or
                        last.get("stock_entry") != previous.return_stock_entry or
                        not last.get("reason") or
                        last.get("actor") != frappe.session.user or
                        any(frappe.db.get_value(dt, name, "docstatus") != 2
                            for dt, name in (("Sales Invoice", previous.credit_note),
                                             ("Payment Entry", last.get("payment_entry")),
                                             ("Stock Entry", previous.return_stock_entry))
                            if name) or
                        frappe.db.get_value("HS Payment",
                            previous.erp_return_refund, "status") != "Cancelled"):
                    frappe.throw(_("La corrección no conserva sus documentos cancelados"))
            elif new_history != old_history or (
                    self.erp_return_corrections_sha256 or "") != (
                        previous.erp_return_corrections_sha256 or ""):
                frappe.throw(_("El historial de correcciones es inmutable"))
            if (any(str(previous.get(field) or "") != str(self.get(field) or "")
                    for field in immutable) or
                    (previous.credit_note != self.credit_note or
                     previous.erp_return_refund != self.erp_return_refund or
                     previous.return_stock_entry != self.return_stock_entry)
                        and not native_transition and not native_reversal and
                        (previous.credit_note or self.credit_note or
                         previous.erp_return_refund or self.erp_return_refund) or
                    previous.status == "Returned" and (
                        (self.status != "Returned" and not native_reversal) or
                        previous.pms_fiscal_credit != self.pms_fiscal_credit or
                        (previous.return_stock_entry != self.return_stock_entry and
                         not native_reversal)) or
                    previous.status == "Delivered" and
                        self.status not in ("Delivered", "Returned")):
                frappe.throw(_("Los términos contabilizados de la venta directa son inmutables"))
        if previous and (previous.opening_stock_issue or "") != (
                self.opening_stock_issue or ""):
            frappe.throw(_("La salida histórica del servicio es inmutable"))
        if previous and previous.opening_stock_issue and any(
                str(previous.get(field) or "") != str(self.get(field) or "")
                for field in ("stay", "folio", "customer", "item", "warehouse",
                              "quantity", "included", "amount", "currency",
                              "stock_entry")):
            frappe.throw(_("Los términos de la salida histórica son inmutables"))
        if (self.is_new() and self.opening_stock_issue and
                not getattr(frappe.local, "hs_reverse_opening", False)):
            frappe.throw(_("La salida histórica solo se crea durante la apertura verificada"),
                         frappe.PermissionError)


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


class PMSCutoverRunDocument(Document):
    """An opening transfer is an immutable sitewide transaction receipt."""

    def validate(self):
        from hospitality_suite.security import is_system

        if (not self.is_new() or not is_system() or
                not getattr(frappe.local, "hs_provider_cutover", False)):
            frappe.throw(_("El acta del corte solo se crea durante la migración verificada"),
                         frappe.PermissionError)

    def on_trash(self):
        frappe.throw(_("El acta de un corte contable no se borra"), frappe.PermissionError)


class PMSModeDocument(Document):
    """Changing the ledger authority requires the migration service."""

    def validate(self):
        from hospitality_suite.security import is_system

        if not is_system():
            frappe.throw(_("Solo administración del sistema puede consultar el modo financiero"), frappe.PermissionError)
        previous = frappe.db.get_single_value("HS Site Mode", "provider")
        if not getattr(frappe.local, "hs_provider_cutover", False):
            if previous and previous != self.provider:
                frappe.throw(_("El cambio de libro contable requiere una migración verificada"))
            if str(frappe.db.get_single_value("HS Site Mode", "migration_reference") or "") != str(self.migration_reference or "") or (
                    str(frappe.db.get_single_value("HS Site Mode", "cutover_date") or "") != str(self.cutover_date or "")):
                frappe.throw(_("El acta del corte solo se registra durante una migración verificada"))


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
        if self.doctype == "HS Product":
            from hospitality_suite.ledger_rules import LedgerValidationError, amount
            try:
                self.sales_rate = float(amount(self.sales_rate or 0))
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
            old = self.get_doc_before_save()
            if old and (old.product_type != self.product_type or
                        old.inventory_account != self.inventory_account) and frappe.db.exists(
                    "HS Stock Movement", {"property": self.property, "product": self.name}):
                frappe.throw(_("El tipo y la cuenta de inventario con movimientos son inmutables"))
        if self.doctype == "HS Warehouse":
            old = self.get_doc_before_save()
            if old and old.active and not self.active:
                stock = frappe.db.sql(
                    "SELECT product, SUM(quantity_delta) AS quantity FROM `tabHS Stock Movement` "
                    "WHERE property=%s AND warehouse=%s GROUP BY product HAVING quantity>0 LIMIT 1",
                    (self.property, self.name), as_dict=True)
                if stock:
                    frappe.throw(_("Traslade o consuma las existencias antes de desactivar el almacén"))
        if self.doctype == "HS Product" and self.tax_profile:
            tax = frappe.db.get_value("HS PMS Tax Profile", self.tax_profile,
                ["property", "organization", "active"], as_dict=True)
            if not tax or (tax.property, tax.organization) != (self.property, self.organization) or not tax.active:
                frappe.throw(_("El producto requiere un perfil tributario activo del establecimiento"))


class PMSPartyDocument(PMSMasterDocument):
    def validate(self):
        super().validate()
        from hospitality_suite.standalone_credit import validate_party_terms
        validate_party_terms(self)


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
            frappe.db.exists("HS PMS Opening Credit", {"receivable_account": self.name}) or
            frappe.db.exists("HS PMS Opening Guarantee", {"liability_account": self.name}) or
            frappe.db.exists("HS Payment", {"pms_counter_account": self.name,
                                            "kind": ["in", ["Advance", "Guarantee"]],
                                            "status": "Posted"})):
            frappe.throw(_("La cuenta respalda saldos de clientes; configure otra cuenta para movimientos nuevos"))
        if old and old.active and not self.active and (
            frappe.db.exists("HS PMS Opening Payable", {"payable_account": self.name}) or
            frappe.db.exists("HS PMS Opening Supplier Credit", {"payable_account": self.name})):
            frappe.throw(_("La cuenta respalda saldos de proveedores; conserve la cuenta activa"))
        if old and old.active and not self.active:
            from hospitality_suite.standalone_opening_credits import remaining_application

            prop = frappe.get_doc("HS Property", self.property)
            for applied in frappe.get_all("HS PMS Allocation", filters={
                    "property": self.property, "kind": "Opening Credit Applied",
                    "opening_credit_exchange_account": self.name}, fields=["name"]):
                if remaining_application(prop, applied.name) > 0:
                    frappe.throw(_("La cuenta respalda una aplicación de crédito extranjero reversible"))
            from hospitality_suite.standalone_opening_supplier_credits import (
                remaining_application as supplier_credit_remaining)

            for applied in frappe.get_all("HS PMS Supplier Credit Allocation",
                    filters={"property": self.property, "kind": "Applied",
                             "exchange_variance_account": self.name},
                    fields=["name"]):
                if supplier_credit_remaining(prop, applied.name) > 0:
                    frappe.throw(_("La cuenta respalda un crédito extranjero de proveedor reversible"))
        if old and old.active and not self.active:
            from hospitality_suite.standalone_financing import remaining
            prop = frappe.get_doc("HS Property", self.property)
            if frappe.db.exists("HS Treasury Movement", {"property": self.property,
                    "counter_account": self.name,
                    "status": ["in", ["Pending Approval", "Approved"]],
                    "kind": ["in", ["Loan Received", "Loan Repayment",
                                    "Capital Contribution", "Capital Withdrawal"]]}):
                frappe.throw(_("La cuenta respalda solicitudes financieras abiertas"))
            for source in frappe.get_all("HS Treasury Movement", filters={
                    "property": self.property, "counter_account": self.name,
                    "status": "Posted",
                    "kind": ["in", ["Loan Received", "Capital Contribution"]]},
                    fields=["name", "kind", "base_amount"]):
                if remaining(prop, source, reserve=False) > 0:
                    frappe.throw(_("La cuenta respalda principal financiero pendiente"))
        if old and old.is_group and not self.is_group and frappe.db.exists("HS Account", {"parent_account": self.name}):
            frappe.throw(_("No puede convertir en cuenta de movimiento una agrupadora con subcuentas"))
        if old and any(old.get(field) != self.get(field) for field in
                       ("property", "organization", "company", "account_code", "account_number", "root_type", "parent_account", "is_group", "account_type", "account_currency", "is_cash", "is_bank")):
            if frappe.db.exists("HS Journal Line", {"account": self.name}):
                frappe.throw(_("No cambie la identidad de una cuenta con movimientos"))


class PMSTaxProfileDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("El perfil tributario es inmutable; cree uno nuevo para futuros cargos"))
        prop = frappe.get_doc("HS Property", self.property)
        if self.organization != prop.organization:
            frappe.throw(_("La entidad del perfil tributario no coincide"))
        from hospitality_suite.standalone_tax import _rate
        rate = _rate(self.rate)
        if (self.treatment == "Taxable") != (rate > 0):
            frappe.throw(_("El tratamiento y la tasa tributaria no coinciden"))
        if rate:
            from hospitality_suite.standalone_accounting import account
            selected = account(prop, self.liability_account)
            if selected.root_type != "Liability" or selected.account_currency != prop.currency:
                frappe.throw(_("El impuesto requiere una cuenta de pasivo en moneda base"))
        elif self.liability_account:
            frappe.throw(_("Un perfil sin impuesto no debe tener cuenta de pasivo"))


class PMSAgencyCommissionDocument(ScopedDocument):
    def validate(self):
        super().validate()
        from hospitality_suite.standalone_accounting import account, require_pms
        prop = frappe.get_doc("HS Property", self.property)
        require_pms(prop)
        booking = frappe.db.get_value("HS Booking", self.booking,
            ["property", "company", "travel_agent", "status"], as_dict=True)
        agent = frappe.db.get_value("HS Travel Agent", self.agent,
            ["property", "company"], as_dict=True)
        supplier = frappe.db.get_value("HS Party", self.supplier,
            ["property", "organization", "party_type"], as_dict=True)
        if (self.organization != prop.organization or not booking or not agent or
                not supplier or booking.property != prop.name or
                booking.company != prop.company or booking.travel_agent != self.agent or
                booking.status != "Completed" or agent.property != prop.name or
                agent.company != prop.company or supplier.property != prop.name or
                supplier.organization != prop.organization or
                supplier.party_type not in ("Supplier", "Both") or
                self.currency != prop.currency or (self.is_new() and
                    str(self.business_date) != str(prop.business_date))):
            frappe.throw(_("La comisión no corresponde a la reserva, agencia o proveedor"))
        expense, payable = account(prop, self.expense_account), account(prop, self.payable_account)
        if (expense.root_type != "Expense" or expense.account_currency != prop.currency or
                payable.root_type != "Liability" or payable.account_type != "Payable" or
                payable.account_currency != prop.currency):
            frappe.throw(_("La comisión requiere gasto y cuenta por pagar en moneda base"))
        base, pct, value = (Decimal(str(self.base_amount or 0)),
                            Decimal(str(self.percent or 0)), Decimal(str(self.amount or 0)))
        if (base <= 0 or pct <= 0 or pct > 100 or
                (base * pct / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != value):
            frappe.throw(_("La base, porcentaje e importe de comisión no coinciden"))
        if frappe.db.exists(self.doctype, {"property": prop.name, "booking": self.booking,
                "status": ["in", ["Pending", "Posted"]], "name": ["!=", self.name]}):
            frappe.throw(_("La reserva ya tiene una comisión vigente"))
        old = self.get_doc_before_save()
        if old:
            fixed = ("property", "company", "organization", "booking", "agent",
                     "supplier", "agent_name", "business_date", "currency",
                     "expense_account", "payable_account")
            if (any(str(old.get(field)) != str(self.get(field)) for field in fixed) or
                    any(Decimal(str(old.get(field) or 0)) !=
                        Decimal(str(self.get(field) or 0)) for field in
                        ("base_amount", "percent", "amount"))):
                frappe.throw(_("La liquidación de agencia es inmutable"))
            if not ((old.status, self.status) == ("Pending", "Posted") and
                    not old.journal and self.journal and not self.reversal_journal and
                    not self.cancelled_business_date) and not (
                    (old.status, self.status) == ("Posted", "Cancelled") and
                    old.journal == self.journal and self.reversal_journal and
                    self.cancel_reason and not old.reversal_journal and
                    str(self.cancelled_business_date) == str(prop.business_date)):
                frappe.throw(_("Use el flujo contable de liquidación o anulación de agencia"))
        elif (self.status != "Pending" or self.journal or self.reversal_journal or
              self.cancelled_business_date):
            frappe.throw(_("La comisión debe iniciar pendiente de asiento"))
        if self.status in ("Posted", "Cancelled"):
            journal = frappe.db.get_value("HS Journal", self.journal,
                ["property", "source_doctype", "source_name", "purpose", "status"], as_dict=True)
            if not journal or (journal.property, journal.source_doctype,
                    journal.source_name, journal.purpose, journal.status) != (
                    prop.name, self.doctype, self.name, "Agency Commission", "Posted"):
                frappe.throw(_("La comisión no conserva su asiento de devengo"))
            lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
                fields=["account", "debit", "credit", "party"])
            expected = {(self.expense_account, value, Decimal(0), self.supplier),
                        (self.payable_account, Decimal(0), value, self.supplier)}
            if {(row.account, Decimal(str(row.debit)), Decimal(str(row.credit)), row.party)
                    for row in lines} != expected or len(lines) != 2:
                frappe.throw(_("El asiento de comisión no coincide con sus cuentas e importe"))
        if self.status == "Cancelled":
            reversal = frappe.db.get_value("HS Journal", self.reversal_journal,
                ["property", "source_doctype", "source_name", "purpose",
                 "reversal_of", "status"], as_dict=True)
            if (not reversal or (reversal.property, reversal.source_doctype,
                    reversal.source_name, reversal.purpose, reversal.reversal_of,
                    reversal.status) != (prop.name, self.doctype, self.name,
                    "Agency Commission Cancellation", self.journal, "Posted") or
                    frappe.db.exists("HS Payment", {"property": prop.name,
                        "pms_agent_commission": self.name, "status": "Posted"})):
                frappe.throw(_("La anulación requiere asiento inverso y ningún pago vigente"))
            lines = frappe.get_all("HS Journal Line", filters={"parent": self.reversal_journal},
                fields=["account", "debit", "credit", "party"])
            expected = {(self.payable_account, value, Decimal(0), self.supplier),
                        (self.expense_account, Decimal(0), value, self.supplier)}
            if {(row.account, Decimal(str(row.debit)), Decimal(str(row.credit)), row.party)
                    for row in lines} != expected or len(lines) != 2:
                frappe.throw(_("El asiento inverso de comisión no coincide"))


class PMSFiscalSeriesDocument(ScopedDocument):
    def validate(self):
        super().validate()
        prop = frappe.get_doc("HS Property", self.property)
        if (self.organization != prop.organization or not self.series_code or
                self.start_number < 1 or
                self.end_number < self.start_number or self.next_number < self.start_number or
                self.next_number > self.end_number + 1 or self.padding < 1 or self.padding > 9 or
                len(str(self.end_number)) > self.padding):
            frappe.throw(_("La serie y su rango no son válidos"))
        if frappe.db.exists("HS PMS Fiscal Series", {"property": self.property,
                "series_code": self.series_code, "name": ["!=", self.name]}):
            frappe.throw(_("La serie ya existe en este establecimiento"))
        if not self.is_new():
            old = self.get_doc_before_save()
            if (not old or not getattr(frappe.local, "hs_operation", False) or
                    self.next_number != old.next_number + 1 or
                    any(old.get(field) != self.get(field) for field in
                        ("property", "company", "organization", "series_code", "document_type",
                         "start_number", "end_number", "padding", "authorization_reference", "active"))):
                frappe.throw(_("La serie solo avanza al emitir un documento"))


class HistoricalFiscalDocument(ScopedDocument):
    def validate(self):
        super().validate()
        from hashlib import sha256

        if not self.is_new() or not getattr(frappe.local, "hs_fiscal_archive_import", False):
            frappe.throw(_("El archivo fiscal histórico solo se crea mediante la importación verificada"))
        prop = frappe.get_doc("HS Property", self.property)
        expected_key = sha256((self.source_site + "|" + self.source_doctype + "|" +
                               self.source_name).encode()).hexdigest()
        hashes = (self.source_key, self.snapshot_sha256, self.pdf_sha256,
                  self.package_sha256)
        if (self.organization != prop.organization or
                self.source_doctype not in ("Sales Invoice", "HS PMS Fiscal Document") or
                self.document_type not in ("Invoice", "Credit Note") or
                self.status not in ("Posted", "Cancelled") or
                self.source_key != expected_key or
                any(not re.fullmatch(r"[0-9a-f]{64}", value or "") for value in hashes) or
                self.pdf_file):
            frappe.throw(_("El documento fiscal histórico no coincide con el paquete verificado"))

    def on_trash(self):
        frappe.throw(_("El archivo fiscal histórico es inmutable"))


class PMSFiscalDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("El documento numerado es inmutable"))
        from decimal import Decimal
        prop = frappe.get_doc("HS Property", self.property)
        series = frappe.db.get_value("HS PMS Fiscal Series", self.series,
            ["property", "organization", "document_type", "series_code", "padding",
             "next_number", "authorization_reference"], as_dict=True)
        party = frappe.db.get_value("HS Party", self.party,
            ["property", "organization", "party_name", "tax_id"], as_dict=True)
        if (not series or not party or self.organization != prop.organization or
                series.property != prop.name or series.organization != prop.organization or
                series.document_type != self.document_type or
                series.next_number != self.sequence_number + 1 or
                self.document_number != f"{series.series_code}{self.sequence_number:0{series.padding}d}" or
                (self.authorization_reference or "") != (series.authorization_reference or "") or
                party.property != prop.name or party.organization != prop.organization or
                self.currency != prop.currency or self.status != "Posted" or
                str(self.business_date) != str(prop.business_date) or
                not self.lines or len(self.lines) > 100):
            frappe.throw(_("El documento no coincide con la serie, entidad o fecha operativa"))
        if frappe.db.exists("HS PMS Fiscal Document", {"property": prop.name,
                "document_number": self.document_number}):
            frappe.throw(_("El número fiscal ya está registrado en este establecimiento"))
        if self.historical_day_pass:
            from hospitality_suite.standalone_day_pass import opening_sale
            day_pass = frappe.db.get_value("HS Day Pass", self.historical_day_pass,
                ["name", "property", "company", "customer", "status",
                 "sales_invoice", "opening_historical_invoice",
                 "opening_financial", "opening_financial_sha256",
                 "opening_credit_note", "opening_refund"], as_dict=True)
            if (not getattr(frappe.local, "hs_historical_day_pass_return", False) or
                    self.document_type != "Credit Note" or self.source_invoice or
                    not day_pass or day_pass.property != prop.name or
                    day_pass.company != prop.company or day_pass.status != "Issued" or
                    day_pass.opening_credit_note or day_pass.opening_refund or
                    self.historical_source_invoice !=
                        day_pass.opening_historical_invoice or
                    self.party != day_pass.customer or self.folio or
                    frappe.db.exists("HS PMS Fiscal Document", {
                        "historical_day_pass": day_pass.name})):
                frappe.throw(_("La nota histórica no coincide con el Day Pass vigente"))
            financial, archive = opening_sale(prop, day_pass)
            expected_buyer = archive.buyer_name or frappe.db.get_value(
                "HS Party", day_pass.customer, "party_name")
            source_debit = sum((Decimal(str(row["debit"]))
                for row in financial["invoice_gl"]), Decimal(0))
            if (self.buyer_name != expected_buyer or
                    len(self.lines) != 1 or self.lines[0].receivable or
                    self.lines[0].product or self.lines[0].income_account or
                    self.lines[0].tax_account or not self.lines[0].description or
                    Decimal(str(self.net_amount)) !=
                        Decimal(str(financial["invoice_net"])) or
                    Decimal(str(self.tax_amount)) !=
                        Decimal(str(financial["invoice_tax"])) or
                    Decimal(str(self.total_amount)) !=
                        Decimal(str(financial["invoice_total"])) or
                    Decimal(str(self.lines[0].net_amount)) !=
                        Decimal(str(self.net_amount)) or
                    Decimal(str(self.lines[0].tax_amount)) !=
                        Decimal(str(self.tax_amount)) or
                    Decimal(str(self.lines[0].total_amount)) !=
                        Decimal(str(self.total_amount))):
                frappe.throw(_("La nota histórica altera los importes de la factura"))
            journal = frappe.db.get_value("HS Journal", self.journal,
                ["name", "property", "organization", "status", "purpose",
                 "source_doctype", "source_name", "reversal_of",
                 "total_debit", "total_credit"], as_dict=True)
            if (not journal or journal.property != prop.name or
                    journal.organization != prop.organization or
                    journal.status != "Posted" or
                    journal.purpose != "Historical Day Pass Credit" or
                    journal.source_doctype != "HS PMS Fiscal Document" or
                    journal.source_name != self.document_number or
                    journal.reversal_of or
                    Decimal(str(journal.total_debit)) != source_debit or
                    Decimal(str(journal.total_credit)) != source_debit):
                frappe.throw(_("La nota histórica no conserva su asiento de reversión"))
            expected = sorted((row["account"], row.get("party") or "",
                Decimal(str(row["credit"])), Decimal(str(row["debit"])))
                for row in financial["invoice_gl"])
            actual = sorted((row.account, row.party or "",
                Decimal(str(row.debit)), Decimal(str(row.credit)))
                for row in frappe.get_doc("HS Journal", self.journal).lines)
            if actual != expected:
                frappe.throw(_("La nota histórica no revierte el asiento original"))
            return
        if self.historical_source_invoice:
            frappe.throw(_("La factura histórica requiere un Day Pass vinculado"))
        from hospitality_suite.standalone_fiscal import _credit_options, _split_credit
        if self.document_type == "Invoice":
            if self.source_invoice or self.journal:
                frappe.throw(_("Una factura no debe enlazar otra factura ni otro asiento"))
            source_lines = options = {}
            journal = None
        elif self.document_type == "Credit Note":
            original = frappe.get_doc("HS PMS Fiscal Document", self.source_invoice)
            if (original.property != prop.name or original.organization != prop.organization or
                    original.document_type != "Invoice" or original.status != "Posted" or
                    original.party != self.party or original.currency != self.currency or
                    original.folio != self.folio or original.seller_name != self.seller_name or
                    (original.seller_tax_id or "") != (self.seller_tax_id or "") or
                    original.buyer_name != self.buyer_name or
                    (original.buyer_tax_id or "") != (self.buyer_tax_id or "")):
                frappe.throw(_("La nota de crédito no corresponde a la factura original"))
            source_lines = {line.receivable: line for line in original.lines}
            options = {line["receivable"]: line for line in _credit_options(prop, original)}
            journal = frappe.get_doc("HS Journal", self.journal)
            if (journal.property != prop.name or journal.organization != prop.organization or
                    journal.status != "Posted" or journal.source_doctype != "HS PMS Fiscal Document" or
                    journal.source_name != self.document_number or journal.purpose != "Credit Note" or
                    journal.reversal_of or frappe.db.exists("HS Journal", {"reversal_of": journal.name})):
                frappe.throw(_("La nota de crédito no conserva un asiento vigente de reversión"))
        else:
            frappe.throw(_("Seleccione un tipo de documento válido"))
        total_net = total_tax = total = Decimal(0)
        seen = set()
        expected_entries = {}

        def entry(account_name, debit=Decimal(0), credit=Decimal(0)):
            key = (account_name, self.party)
            old_debit, old_credit = expected_entries.get(key, (Decimal(0), Decimal(0)))
            expected_entries[key] = (old_debit + debit, old_credit + credit)

        for line in self.lines:
            receivable = frappe.db.get_value("HS PMS Receivable", line.receivable,
                ["property", "party", "folio", "status", "currency", "description",
                 "net_amount", "tax_amount", "amount", "tax_rate", "tax_treatment",
                 "income_account", "tax_account", "receivable_account"], as_dict=True)
            if (not receivable or line.receivable in seen or
                    receivable.property != prop.name or receivable.party != self.party or
                    receivable.folio != self.folio or receivable.status != "Posted" or
                    receivable.currency != self.currency or
                    any(str(receivable.get(field) or "") != str(line.get(field) or "") for field in
                        ("description", "tax_treatment", "income_account", "tax_account")) or
                    Decimal(str(receivable.tax_rate or 0)) != Decimal(str(line.tax_rate or 0))):
                frappe.throw(_("Una línea fiscal no coincide con su cargo contable"))
            if self.document_type == "Invoice":
                if any(Decimal(str(receivable.get(left) or 0)) != Decimal(str(line.get(right) or 0))
                       for left, right in (("net_amount", "net_amount"), ("tax_amount", "tax_amount"),
                                           ("amount", "total_amount"))):
                    frappe.throw(_("La factura no conserva los importes del cargo"))
                from hospitality_suite.standalone_fiscal import _already_invoiced
                if _already_invoiced(prop, line.receivable):
                    frappe.throw(_("El cargo ya tiene factura"))
            else:
                source = source_lines.get(line.receivable)
                option = options.get(line.receivable)
                line_net = Decimal(str(line.net_amount or 0))
                line_tax = Decimal(str(line.tax_amount or 0))
                line_total = Decimal(str(line.total_amount or 0))
                if (not source or not option or line.product != source.product or
                        line_total <= 0 or line_total > Decimal(option["available"]) or
                        line_net < 0 or line_tax < 0 or line_net + line_tax != line_total or
                        (line_net, line_tax) != _split_credit(option, line_total)):
                    frappe.throw(_("La nota supera el saldo o altera los impuestos del cargo"))
                if line_net:
                    entry(line.income_account, debit=line_net)
                if line_tax:
                    entry(line.tax_account, debit=line_tax)
                entry(receivable.receivable_account, credit=line_total)
            seen.add(line.receivable)
            total_net += Decimal(str(line.net_amount))
            total_tax += Decimal(str(line.tax_amount))
            total += Decimal(str(line.total_amount))
        if (total_net != Decimal(str(self.net_amount)) or
                total_tax != Decimal(str(self.tax_amount)) or
                total != Decimal(str(self.total_amount)) or total != total_net + total_tax):
            frappe.throw(_("Los importes del documento no cuadran con sus líneas"))
        if journal:
            actual_entries = {}
            for row in journal.lines:
                key = (row.account, row.party)
                old_debit, old_credit = actual_entries.get(key, (Decimal(0), Decimal(0)))
                actual_entries[key] = (old_debit + Decimal(str(row.debit)),
                                       old_credit + Decimal(str(row.credit)))
            if (actual_entries != expected_entries or
                    Decimal(str(journal.total_debit)) != total or
                    Decimal(str(journal.total_credit)) != total):
                frappe.throw(_("El asiento de la nota no coincide con sus líneas"))

    def on_trash(self):
        frappe.throw(_("El documento numerado no se borra"))


class PMSReceivableDocument(ScopedDocument):
    """An internal receivable is an immutable, posted business event."""

    def _validate_opening(self):
        from decimal import Decimal
        from hospitality_suite.standalone_accounting import account

        prop = frappe.get_doc("HS Property", self.property)
        if (getattr(frappe.local, "hs_reverse_opening", None) !=
                self.opening_source_sha256 or
                not re.fullmatch(r"[0-9a-f]{64}", self.opening_source_sha256 or "") or
                not self.opening_source_site or not self.opening_source_name or
                self.reference != self.opening_source_name or
                self.organization != prop.organization or
                self.base_currency != prop.currency or
                str(self.business_date) != str(prop.business_date) or
                not self.due_date or self.status != "Posted" or
                self.reversal_journal or self.income_account or self.tax_account or
                self.tax_profile or self.source_charge or self.source_service or
                self.booking or self.experience_order or
                self.tax_treatment != "Unclassified" or
                Decimal(str(self.amount or 0)) <= 0 or
                Decimal(str(self.base_amount or 0)) <= 0 or
                (self.currency == prop.currency and
                 Decimal(str(self.base_amount)) != Decimal(str(self.amount))) or
                Decimal(str(self.net_amount or 0)) != Decimal(str(self.amount)) or
                Decimal(str(self.tax_amount or 0)) != 0):
            frappe.throw(_("El saldo inicial de cartera no coincide con el paquete verificado"))
        party = frappe.db.get_value("HS Party", self.party,
            ["property", "organization", "party_type", "active"], as_dict=True)
        receivable = account(prop, self.receivable_account)
        temporary = account(prop, self.opening_temporary_account)
        if (not party or (party.property, party.organization) !=
                (prop.name, prop.organization) or
                party.party_type not in ("Customer", "Both") or not party.active or
                receivable.root_type != "Asset" or
                receivable.account_type != "Receivable" or
                receivable.account_currency != self.currency or
                temporary.root_type != "Asset" or
                temporary.account_type != "Temporary" or
                temporary.account_currency != prop.currency or
                temporary.name == receivable.name):
            frappe.throw(_("La apertura requiere cliente, cartera y cuenta temporal válidos"))
        if self.folio:
            folio = frappe.db.get_value("HS Folio", self.folio,
                ["property", "company", "customer", "currency", "status"],
                as_dict=True)
            if (not folio or folio.property != prop.name or
                    folio.company != prop.company or
                    folio.customer != self.party or
                    folio.currency != prop.currency or folio.status != "Open"):
                frappe.throw(_("La factura de apertura no coincide con la cuenta de estancia restaurada"))
        archive = frappe.db.exists("HS Historical Fiscal Document", {
            "property": prop.name, "source_site": self.opening_source_site,
            "source_doctype": "Sales Invoice",
            "source_name": self.opening_source_name,
            "status": "Posted"})
        if (not archive or frappe.db.exists("HS PMS Receivable", {
                "property": prop.name,
                "opening_source_site": self.opening_source_site,
                "opening_source_name": self.opening_source_name})):
            frappe.throw(_("La factura de apertura falta del archivo o ya fue trasladada"))
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "organization", "source_doctype", "source_name",
             "purpose", "status", "business_date"], as_dict=True)
        if (not journal or (journal.property, journal.organization,
                journal.source_doctype, journal.source_name, journal.purpose,
                journal.status, str(journal.business_date)) !=
                (prop.name, prop.organization, "HS PMS Receivable",
                 self.opening_source_name, "Opening Receivable", "Posted",
                 str(prop.business_date))):
            frappe.throw(_("El asiento de apertura de cartera no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "account_currency", "debit", "credit",
                    "debit_in_account_currency", "credit_in_account_currency"])
        value = Decimal(str(self.base_amount))
        original = Decimal(str(self.amount))
        expected = {(receivable.name, self.party, self.currency, value,
                     Decimal(0), original, Decimal(0)),
                    (temporary.name, None, prop.currency, Decimal(0), value,
                     Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party, row.account_currency,
                Decimal(str(row.debit)), Decimal(str(row.credit)),
                Decimal(str(row.debit_in_account_currency)),
                Decimal(str(row.credit_in_account_currency)))
                for row in lines} != expected):
            frappe.throw(_("Las partidas de apertura de cartera no concilian"))

    def validate(self):
        super().validate()
        if self.opening_source_name:
            if not self.is_new():
                frappe.throw(_("El saldo inicial de cartera es inmutable"))
            self._validate_opening()
            return
        if any(self.get(field) for field in ("opening_source_site",
                "opening_source_sha256", "opening_temporary_account")):
            frappe.throw(_("Los datos de apertura requieren una factura de origen"))
        if self.base_currency or Decimal(str(self.base_amount or 0)) != 0:
            frappe.throw(_("El valor base inicial solo corresponde a cartera trasladada"))
        if not self.due_date or frappe.utils.getdate(self.due_date) < frappe.utils.getdate(self.business_date):
            frappe.throw(_("El vencimiento del cargo no puede preceder su fecha operativa"))
        if not self.is_new():
            from hospitality_suite.standalone_receivables import allocated
            old = self.get_doc_before_save()
            if (not getattr(frappe.local, "hs_operation", False) or not old or
                    old.status != "Posted" or self.status != "Cancelled" or
                    any(old.get(field) != self.get(field) for field in
                        ("property", "company", "organization", "party", "reference", "description",
                         "business_date", "due_date", "currency", "amount", "base_currency",
                         "base_amount", "net_amount", "tax_amount",
                         "tax_profile", "tax_rate", "tax_treatment", "price_includes_tax",
                         "tax_account", "receivable_account",
                         "income_account", "folio", "source_charge", "source_service", "booking",
                         "experience_order", "journal", "opening_source_site",
                         "opening_source_name", "opening_source_sha256",
                         "opening_temporary_account")) or
                    allocated(frappe.get_doc("HS Property", self.property), self.name) != 0):
                frappe.throw(_("La cuenta por cobrar registrada es inmutable"))
            reversal = frappe.db.get_value("HS Journal", self.reversal_journal,
                ["property", "reversal_of"], as_dict=True)
            if not reversal or reversal.property != self.property or reversal.reversal_of != self.journal:
                frappe.throw(_("Se requiere el asiento inverso del cargo original"))
            return
        prop = frappe.get_doc("HS Property", self.property)
        if self.status != "Posted" or self.reversal_journal:
            frappe.throw(_("Un cargo nuevo debe quedar publicado sin reversión"))
        from hospitality_suite.standalone_credit import due_date as pms_due_date
        if frappe.utils.getdate(self.due_date) != pms_due_date(prop, self.party):
            frappe.throw(_("El vencimiento del cargo no coincide con las condiciones de crédito vigentes"))
        if (self.organization != prop.organization or self.currency != prop.currency or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("La entidad, moneda o fecha operativa no coincide"))
        party = frappe.db.get_value("HS Party", self.party,
            ["property", "active", "party_type"], as_dict=True)
        if not party or party.property != prop.name or not party.active or party.party_type not in ("Customer", "Both"):
            frappe.throw(_("Seleccione un cliente activo del establecimiento"))
        if bool(self.folio) != bool(self.source_charge):
            frappe.throw(_("El cargo de estancia requiere una cuenta de estancia y un cargo de origen"))
        if self.source_service:
            service = frappe.db.get_value("HS Service Request", self.source_service,
                ["property", "company", "customer", "item", "pms_party",
                 "pms_product", "stay", "folio",
                 "charge", "status", "amount", "currency"], as_dict=True)
            product = frappe.db.get_value("HS Product", service.pms_product,
                ["property", "organization", "income_account", "tax_profile"],
                as_dict=True) if service else None
            if (self.folio or self.source_charge or self.booking or
                    self.experience_order or not service or not product or
                    service.property != prop.name or service.company != prop.company or
                    service.customer != self.party or service.pms_party != self.party or
                    service.item != service.pms_product or
                    service.stay or service.folio or
                    service.charge or service.status != "Requested" or
                    service.currency != prop.currency or
                    Decimal(str(service.amount or 0)) != Decimal(str(self.amount or 0)) or
                    product.property != prop.name or
                    product.organization != prop.organization or
                    self.income_account != product.income_account or
                    self.tax_profile != product.tax_profile or
                    frappe.db.exists("HS PMS Receivable", {
                        "source_service": self.source_service, "status": "Posted"})):
                frappe.throw(_("La venta directa no conserva un servicio nuevo válido"))
        if self.experience_order:
            order = frappe.db.get_value('HS Experience Order', self.experience_order,
                ['property', 'company', 'customer', 'booking', 'status',
                 'pms_product', 'income_account', 'tax_account',
                 'accepted_tax_profile', 'accepted_net', 'accepted_tax',
                 'accepted_total'], as_dict=True)
            product = frappe.db.get_value('HS Product', order.pms_product,
                ['income_account', 'tax_profile'], as_dict=True) if order else None
            frozen = bool(order and order.accepted_total)
            if (self.folio or self.source_charge or self.booking or not order or not product or
                    order.property != prop.name or order.company != prop.company or
                    order.customer != self.party or order.booking or order.status != 'Confirmed' or
                    self.income_account != (order.income_account if frozen else product.income_account) or
                    self.tax_profile != (order.accepted_tax_profile or product.tax_profile
                                         if frozen else product.tax_profile) or
                    (frozen and (
                        Decimal(str(self.amount or 0)) != Decimal(str(order.accepted_total)) or
                        Decimal(str(self.net_amount or 0)) != Decimal(str(order.accepted_net or 0)) or
                        Decimal(str(self.tax_amount or 0)) != Decimal(str(order.accepted_tax or 0)) or
                        self.tax_account != order.tax_account)) or
                    frappe.db.exists('HS PMS Receivable',
                        {'experience_order': self.experience_order, 'status': 'Posted'})):
                frappe.throw(_("La experiencia directa no conserva una orden pendiente válida"))
        if self.booking:
            booking = frappe.db.get_value("HS Booking", self.booking,
                ["property", "company", "customer", "status"], as_dict=True)
            if (self.folio or self.source_charge or not booking or
                    booking.property != prop.name or booking.company != prop.company or
                    booking.customer != self.party or booking.status not in ("Hold", "Confirmed") or
                    frappe.db.exists("HS PMS Receivable", {"booking": self.booking, "status": "Posted"})):
                frappe.throw(_("La penalización requiere una reserva vigente sin otro cargo"))
        if self.folio:
            folio = frappe.db.get_value("HS Folio", self.folio,
                ["property", "customer", "currency", "status"], as_dict=True)
            charge = frappe.db.get_value("HS Charge", self.source_charge,
                ["property", "folio", "status", "applies_to_charge"], as_dict=True)
            if (not folio or not charge or folio.property != prop.name or
                    folio.customer != self.party or folio.currency != prop.currency or
                    folio.status != "Open" or charge.property != prop.name or
                    charge.folio != self.folio or charge.status != "Pending" or
                    charge.applies_to_charge or frappe.db.exists("HS PMS Receivable",
                        {"source_charge": self.source_charge, "status": "Posted"})):
                frappe.throw(_("La cuenta de estancia o el cargo de origen ya cambió"))
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        try:
            if amount(self.amount) <= 0:
                frappe.throw(_("El cargo debe ser mayor que cero"))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if (amount(self.net_amount or 0) <= 0 or amount(self.tax_amount or 0) < 0 or
                amount(self.net_amount or 0) + amount(self.tax_amount or 0) != amount(self.amount)):
            frappe.throw(_("El total del cargo debe coincidir con base e impuesto"))
        if self.tax_treatment not in ("Unclassified", "Taxable", "Exempt", "Zero Rate", "Outside Scope"):
            frappe.throw(_("Conserve el tratamiento tributario del cargo"))
        if self.tax_profile and frappe.db.get_value("HS PMS Tax Profile", self.tax_profile, "property") != prop.name:
            frappe.throw(_("El perfil tributario pertenece a otro establecimiento"))
        if self.tax_treatment == "Taxable":
            if not self.tax_profile or Decimal(str(self.tax_rate)) <= 0 or amount(self.tax_amount or 0) <= 0:
                frappe.throw(_("El cargo gravado requiere impuesto y perfil vigentes"))
        elif amount(self.tax_amount or 0) != 0 or self.tax_account:
            frappe.throw(_("Un cargo no gravado no debe incluir impuesto"))
        from hospitality_suite.standalone_accounting import account
        receivable = account(prop, self.receivable_account)
        income = account(prop, self.income_account)
        if self.tax_account:
            tax_account = account(prop, self.tax_account)
            if tax_account.root_type != "Liability" or tax_account.account_currency != prop.currency:
                frappe.throw(_("La cuenta tributaria debe ser un pasivo en moneda base"))
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


class PMSOpeningPayableDocument(ScopedDocument):
    """One imported supplier balance, settled without repeating its expense."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("El saldo inicial del proveedor es inmutable"))
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
        from hospitality_suite.standalone_accounting import account
        from hospitality_suite.standalone_currency import enabled

        prop = frappe.get_doc("HS Property", self.property)
        if (getattr(frappe.local, "hs_reverse_opening", None) !=
                self.opening_source_sha256 or
                not re.fullmatch(r"[0-9a-f]{64}", self.opening_source_sha256 or "") or
                not self.opening_source_site or not self.opening_source_name or
                self.organization != prop.organization or
                not enabled(prop, self.currency) or self.status != "Posted" or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("El saldo inicial del proveedor no coincide con el paquete verificado"))
        try:
            value = amount(self.amount)
            base_value = amount(self.base_amount)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0 or base_value <= 0 or not self.due_date or (
                self.currency == prop.currency and value != base_value):
            frappe.throw(_("La factura del proveedor requiere saldo y vencimiento"))
        try:
            historical_rate = (rate_for_base(value, base_value)
                if self.currency != prop.currency else "1")
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        supplier = frappe.db.get_value("HS Party", self.supplier,
            ["property", "organization", "party_type", "active"], as_dict=True)
        payable = account(prop, self.payable_account)
        temporary = account(prop, self.opening_temporary_account)
        if (not supplier or (supplier.property, supplier.organization) !=
                (prop.name, prop.organization) or not supplier.active or
                supplier.party_type not in ("Supplier", "Both") or
                payable.root_type != "Liability" or
                payable.account_type != "Payable" or
                payable.account_currency != self.currency or
                temporary.root_type != "Asset" or
                temporary.account_type != "Temporary" or
                temporary.account_currency != prop.currency or
                temporary.name == payable.name):
            frappe.throw(_("La apertura requiere proveedor, pasivo y cuenta temporal válidos"))
        if frappe.db.exists("HS PMS Opening Payable", {
                "property": prop.name,
                "opening_source_site": self.opening_source_site,
                "opening_source_name": self.opening_source_name}):
            frappe.throw(_("La factura del proveedor ya fue trasladada"))
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "organization", "source_doctype", "source_name",
             "purpose", "status", "business_date"], as_dict=True)
        if (not journal or (journal.property, journal.organization,
                journal.source_doctype, journal.source_name, journal.purpose,
                journal.status, str(journal.business_date)) !=
                (prop.name, prop.organization, "HS PMS Opening Payable",
                 self.opening_source_name, "Opening Payable", "Posted",
                 str(prop.business_date))):
            frappe.throw(_("El asiento de apertura del proveedor no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit", "account_currency",
                    "exchange_rate", "debit_in_account_currency",
                    "credit_in_account_currency"])
        expected = {
            (temporary.name, None, base_value, Decimal(0), prop.currency,
             Decimal(1), base_value, Decimal(0)),
            (payable.name, self.supplier, Decimal(0), base_value, self.currency,
             Decimal(historical_rate), Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit)),
                row.account_currency, Decimal(str(row.exchange_rate)),
                Decimal(str(row.debit_in_account_currency)),
                Decimal(str(row.credit_in_account_currency)))
                for row in lines} != expected):
            frappe.throw(_("Las partidas de apertura del proveedor no concilian"))

    def on_trash(self):
        frappe.throw(_("El saldo inicial del proveedor no se borra"))


class PMSOpeningCreditDocument(ScopedDocument):
    """An imported customer credit, never a new cash receipt or sale."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("El crédito inicial es inmutable"))
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
        from hospitality_suite.standalone_accounting import account

        prop = frappe.get_doc("HS Property", self.property)
        if (getattr(frappe.local, "hs_reverse_opening", None) !=
                self.opening_source_sha256 or
                not re.fullmatch(r"[0-9a-f]{64}", self.opening_source_sha256 or "") or
                not self.opening_source_site or not self.opening_source_name or
                self.organization != prop.organization or
                self.status != "Posted" or
                str(self.business_date) != str(prop.business_date) or
                (self.credit_kind == "Credit Note" and
                 self.opening_source_doctype != "Sales Invoice") or
                (self.credit_kind == "Advance" and
                 self.opening_source_doctype not in ("Payment Entry", "Journal Entry")) or
                self.credit_kind not in ("Credit Note", "Advance")):
            frappe.throw(_("El crédito inicial no coincide con el paquete verificado"))
        try:
            value = amount(self.amount)
            if self.currency == prop.currency:
                if self.base_currency and self.base_currency != prop.currency:
                    raise LedgerValidationError("La moneda base del crédito no coincide")
                if self.base_amount and amount(self.base_amount) != value:
                    raise LedgerValidationError("El crédito en moneda base no concilia")
                self.base_currency = prop.currency
                self.base_amount = str(value)
            else:
                if self.base_currency != prop.currency:
                    raise LedgerValidationError("El crédito extranjero requiere valor base")
                base_value = amount(self.base_amount)
                historical_rate = rate_for_base(value, base_value)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0 or (self.currency != prop.currency and base_value <= 0):
            frappe.throw(_("El crédito inicial debe ser positivo"))
        if self.currency == prop.currency:
            base_value, historical_rate = value, "1"
        customer = frappe.db.get_value("HS Party", self.customer,
            ["property", "organization", "party_type", "active"], as_dict=True)
        receivable = account(prop, self.receivable_account)
        temporary = account(prop, self.opening_temporary_account)
        if (not customer or (customer.property, customer.organization) !=
                (prop.name, prop.organization) or not customer.active or
                customer.party_type not in ("Customer", "Both") or
                receivable.root_type != "Asset" or
                receivable.account_type != "Receivable" or
                receivable.account_currency != self.currency or
                temporary.root_type != "Asset" or
                temporary.account_type != "Temporary" or
                temporary.account_currency != prop.currency or
                temporary.name == receivable.name):
            frappe.throw(_("La apertura requiere cliente, cartera y cuenta temporal válidos"))
        if frappe.db.exists("HS PMS Opening Credit", {
                "property": prop.name,
                "opening_source_site": self.opening_source_site,
                "opening_source_doctype": self.opening_source_doctype,
                "opening_source_name": self.opening_source_name}):
            frappe.throw(_("El crédito del cliente ya fue trasladado"))
        source_name = self.opening_source_doctype + "|" + self.opening_source_name
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "organization", "source_doctype", "source_name",
             "purpose", "status", "business_date"], as_dict=True)
        if (not journal or (journal.property, journal.organization,
                journal.source_doctype, journal.source_name, journal.purpose,
                journal.status, str(journal.business_date)) !=
                (prop.name, prop.organization, "HS PMS Opening Credit",
                 source_name, "Opening Credit", "Posted",
                 str(prop.business_date))):
            frappe.throw(_("El asiento de apertura del crédito no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit", "account_currency",
                "exchange_rate", "debit_in_account_currency",
                "credit_in_account_currency"])
        expected = {
            (temporary.name, None, base_value, Decimal(0), prop.currency,
             Decimal(1), base_value, Decimal(0)),
            (receivable.name, self.customer, Decimal(0), base_value,
             self.currency, Decimal(historical_rate), Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit)),
                row.account_currency, Decimal(str(row.exchange_rate)),
                Decimal(str(row.debit_in_account_currency)),
                Decimal(str(row.credit_in_account_currency)))
                for row in lines} != expected):
            frappe.throw(_("Las partidas de apertura del crédito no concilian"))

    def on_trash(self):
        frappe.throw(_("El crédito inicial no se borra"))


class PMSOpeningGuaranteeDocument(ScopedDocument):
    """Opening liability for a guest guarantee; no new cash receipt is created."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("La garantía inicial es inmutable"))
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
        from hospitality_suite.standalone_accounting import account

        prop = frappe.get_doc("HS Property", self.property)
        if (getattr(frappe.local, "hs_reverse_opening", None) !=
                self.opening_source_sha256 or
                not re.fullmatch(r"[0-9a-f]{64}", self.opening_source_sha256 or "") or
                not self.opening_source_site or not self.opening_source_name or
                not (self.source_booking or self.source_folio) or
                self.organization != prop.organization or
                self.currency != prop.currency or self.status != "Posted" or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("La garantía inicial no coincide con el paquete verificado"))
        try:
            value = amount(self.amount)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0:
            frappe.throw(_("La garantía inicial debe ser positiva"))
        customer = frappe.db.get_value("HS Party", self.customer,
            ["property", "organization", "party_type", "active"], as_dict=True)
        liability = account(prop, self.liability_account)
        temporary = account(prop, self.opening_temporary_account)
        if (not customer or (customer.property, customer.organization) !=
                (prop.name, prop.organization) or not customer.active or
                customer.party_type not in ("Customer", "Both") or
                liability.root_type != "Liability" or
                liability.account_currency != prop.currency or
                temporary.root_type != "Asset" or
                temporary.account_type != "Temporary" or
                temporary.account_currency != prop.currency or
                temporary.name == liability.name):
            frappe.throw(_("La apertura requiere cliente, pasivo y cuenta temporal válidos"))
        if frappe.db.exists("HS PMS Opening Guarantee", {
                "property": prop.name,
                "opening_source_site": self.opening_source_site,
                "opening_source_name": self.opening_source_name}):
            frappe.throw(_("La garantía ya fue trasladada"))
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "organization", "source_doctype", "source_name",
             "purpose", "status", "business_date"], as_dict=True)
        if (not journal or (journal.property, journal.organization,
                journal.source_doctype, journal.source_name, journal.purpose,
                journal.status, str(journal.business_date)) !=
                (prop.name, prop.organization, "HS PMS Opening Guarantee",
                 self.opening_source_name, "Opening Guarantee", "Posted",
                 str(prop.business_date))):
            frappe.throw(_("El asiento de apertura de la garantía no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit"])
        expected = {(temporary.name, None, value, Decimal(0)),
                    (liability.name, None, Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit)))
                for row in lines} != expected):
            frappe.throw(_("Las partidas de la garantía no concilian"))

    def on_trash(self):
        frappe.throw(_("La garantía inicial no se borra"))


class PMSOpeningSupplierCreditDocument(ScopedDocument):
    """A verified vendor credit in opening AP, without a stock return."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("El crédito inicial del proveedor es inmutable"))
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
        from hospitality_suite.standalone_accounting import account
        from hospitality_suite.standalone_currency import enabled

        prop = frappe.get_doc("HS Property", self.property)
        if (getattr(frappe.local, "hs_reverse_opening", None) !=
                self.opening_source_sha256 or
                not re.fullmatch(r"[0-9a-f]{64}", self.opening_source_sha256 or "") or
                not self.opening_source_site or not self.opening_source_name or
                self.organization != prop.organization or
                not enabled(prop, self.currency) or self.status != "Posted" or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("El crédito del proveedor no coincide con el paquete verificado"))
        try:
            value = amount(self.amount)
            if self.currency != prop.currency and (
                    self.base_currency != prop.currency or not self.base_amount):
                raise LedgerValidationError("El crédito extranjero requiere valor base")
            base_value = amount(self.base_amount) if self.base_amount else value
            if self.currency == prop.currency and base_value != value:
                raise LedgerValidationError("El crédito base no concilia")
            historical_rate = (rate_for_base(value, base_value)
                if self.currency != prop.currency else "1")
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0 or base_value <= 0 or (self.base_currency and
                self.base_currency != prop.currency):
            frappe.throw(_("El crédito del proveedor debe ser positivo"))
        self.base_currency = prop.currency
        self.base_amount = str(base_value)
        supplier = frappe.db.get_value("HS Party", self.supplier,
            ["property", "organization", "party_type", "active"], as_dict=True)
        payable = account(prop, self.payable_account)
        temporary = account(prop, self.opening_temporary_account)
        if (not supplier or (supplier.property, supplier.organization) !=
                (prop.name, prop.organization) or not supplier.active or
                supplier.party_type not in ("Supplier", "Both") or
                payable.root_type != "Liability" or
                payable.account_type != "Payable" or
                payable.account_currency != self.currency or
                temporary.root_type != "Asset" or
                temporary.account_type != "Temporary" or
                temporary.account_currency != prop.currency or
                temporary.name == payable.name):
            frappe.throw(_("La apertura requiere proveedor, pasivo y cuenta temporal válidos"))
        if frappe.db.exists("HS PMS Opening Supplier Credit", {
                "property": prop.name, "opening_source_site": self.opening_source_site,
                "opening_source_name": self.opening_source_name}):
            frappe.throw(_("El crédito del proveedor ya fue trasladado"))
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "organization", "source_doctype", "source_name",
             "purpose", "status", "business_date"], as_dict=True)
        if (not journal or (journal.property, journal.organization,
                journal.source_doctype, journal.source_name, journal.purpose,
                journal.status, str(journal.business_date)) !=
                (prop.name, prop.organization, "HS PMS Opening Supplier Credit",
                 self.opening_source_name, "Opening Supplier Credit", "Posted",
                 str(prop.business_date))):
            frappe.throw(_("El asiento de apertura del crédito no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit", "account_currency",
                    "exchange_rate", "debit_in_account_currency",
                    "credit_in_account_currency"])
        expected = {
            (payable.name, self.supplier, base_value, Decimal(0), self.currency,
             Decimal(historical_rate), value, Decimal(0)),
            (temporary.name, None, Decimal(0), base_value, prop.currency,
             Decimal(1), Decimal(0), base_value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit)),
                row.account_currency, Decimal(str(row.exchange_rate)),
                Decimal(str(row.debit_in_account_currency)),
                Decimal(str(row.credit_in_account_currency)))
                for row in lines} != expected):
            frappe.throw(_("Las partidas del crédito del proveedor no concilian"))

    def on_trash(self):
        frappe.throw(_("El crédito inicial del proveedor no se borra"))


class PMSSupplierCreditAllocationDocument(ScopedDocument):
    """Append-only application of an opening vendor credit to a payable."""

    def validate(self):
        super().validate()
        if not self.is_new() or not getattr(frappe.local, "hs_supplier_credit_allocation", False):
            frappe.throw(_("La aplicación del crédito solo se crea mediante su operación"))
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount, rate_for_base
        from hospitality_suite.standalone_accounting import account
        from hospitality_suite import standalone_opening_supplier_credits as credits

        prop = frappe.get_doc("HS Property", self.property)
        credit = frappe.db.get_value("HS PMS Opening Supplier Credit", self.opening_credit,
            ["name", "property", "organization", "supplier", "payable_account",
             "currency", "status"],
            as_dict=True)
        if (not credit or credit.property != prop.name or
                credit.organization != prop.organization or credit.status != "Posted" or
                self.organization != prop.organization or
                self.currency != credit.currency or
                str(self.business_date) != str(prop.business_date) or
                self.kind not in ("Applied", "Reversed") or
                self.target_type not in ("Opening Payable", "Purchase") or
                bool(self.opening_payable) == bool(self.purchase)):
            frappe.throw(_("La aplicación del proveedor no conserva su origen"))
        target_doctype = ("HS PMS Opening Payable" if self.target_type == "Opening Payable"
                          else "HS PMS Purchase")
        target_name = self.opening_payable or self.purchase
        target = frappe.db.get_value(target_doctype, target_name,
            ["property", "organization", "supplier", "payable_account", "status"],
            as_dict=True)
        if (not target or target.property != prop.name or
                target.organization != prop.organization or
                target.supplier != credit.supplier or target.status != "Posted"):
            frappe.throw(_("El crédito y la deuda deben ser del mismo proveedor"))
        try:
            value = amount(self.amount)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0 or not self.reason or len(self.reason) > 500:
            frappe.throw(_("Indique importe positivo y motivo de la aplicación"))
        foreign = credit.currency != prop.currency
        if foreign:
            if self.target_type != "Opening Payable" or self.base_currency != prop.currency:
                frappe.throw(_("El crédito extranjero requiere deuda inicial en su moneda"))
            target_currency = frappe.db.get_value(target_doctype, target_name, "currency")
            if target_currency != credit.currency:
                frappe.throw(_("La deuda extranjera no tiene la moneda del crédito"))
            try:
                source_base = amount(self.source_base_amount)
                target_base = amount(self.target_base_amount)
                rate_for_base(value, source_base)
                rate_for_base(value, target_base)
            except LedgerValidationError as exc:
                frappe.throw(str(exc))
            if source_base <= 0 or target_base <= 0:
                frappe.throw(_("La aplicación extranjera requiere valores base positivos"))
            difference = source_base - target_base
            if (difference and not self.exchange_variance_account) or (
                    self.kind == "Applied" and not difference and
                    self.exchange_variance_account):
                frappe.throw(_("La diferencia cambiaria de la aplicación no coincide"))
            if self.exchange_variance_account:
                variance = account(prop, self.exchange_variance_account)
                if (variance.root_type not in ("Income", "Expense") or
                        variance.account_currency != prop.currency or
                        variance.is_cash or variance.is_bank):
                    frappe.throw(_("La cuenta de diferencia cambiaria no es válida"))
        elif (self.base_currency or self.source_base_amount or
                self.target_base_amount or self.exchange_variance_account):
            frappe.throw(_("La aplicación en moneda base no requiere conversión"))
        if self.kind == "Applied":
            if (self.reverses or value > credits.available(prop, credit.name) or
                    value > credits.target_outstanding(prop, self.target_type, target_name)):
                frappe.throw(_("La aplicación supera el crédito o la deuda pendiente"))
            if foreign:
                from hospitality_suite.standalone_opening_payables import _balances
                if (source_base > credits.balances(prop, credit.name)[1] or
                        target_base > _balances(prop, frappe.get_doc(
                            target_doctype, target_name))[1]):
                    frappe.throw(_("La aplicación supera el valor base disponible"))
        else:
            original = frappe.db.get_value("HS PMS Supplier Credit Allocation", self.reverses,
                ["property", "opening_credit", "opening_payable", "purchase", "kind"],
                as_dict=True)
            if (not original or original.property != prop.name or
                    original.kind != "Applied" or original.opening_credit != credit.name or
                    original.opening_payable != self.opening_payable or
                    original.purchase != self.purchase or
                    value > credits.remaining_application(prop, self.reverses)):
                frappe.throw(_("La reversión supera la aplicación original"))
            if foreign:
                _, source_left, target_left = credits.application_balances(
                    prop, self.reverses)
                if (source_base > source_left or target_base > target_left or
                        self.exchange_variance_account != frappe.db.get_value(
                            "HS PMS Supplier Credit Allocation", self.reverses,
                            "exchange_variance_account")):
                    frappe.throw(_("La reversión altera el valor base original"))
        source_account = account(prop, credit.payable_account)
        target_account = account(prop, target.payable_account)
        if any(row.root_type != "Liability" or row.account_type != "Payable" or
               row.account_currency != credit.currency for row in
               (source_account, target_account)):
            frappe.throw(_("Las cuentas por pagar de la aplicación no son válidas"))
        if source_account.name == target_account.name and not (foreign and difference):
            if self.journal:
                frappe.throw(_("La aplicación en la misma cuenta no requiere asiento"))
            return
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "organization", "source_doctype", "purpose", "status",
             "business_date"], as_dict=True)
        purpose = "Supplier Credit Applied" if self.kind == "Applied" else "Supplier Credit Reversed"
        if (not journal or journal.property != prop.name or
                journal.organization != prop.organization or
                journal.source_doctype != "HS PMS Supplier Credit Allocation" or
                journal.purpose != purpose or journal.status != "Posted" or
                str(journal.business_date) != str(prop.business_date) or
                frappe.db.exists("HS PMS Supplier Credit Allocation", {"journal": self.journal})):
            frappe.throw(_("El asiento de la aplicación no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit", "account_currency",
                    "exchange_rate", "debit_in_account_currency",
                    "credit_in_account_currency"])
        debit = target_account.name if self.kind == "Applied" else source_account.name
        credit_account = source_account.name if self.kind == "Applied" else target_account.name
        if foreign:
            debit_base = target_base if self.kind == "Applied" else source_base
            credit_base = source_base if self.kind == "Applied" else target_base
            expected = {
                (debit, credit.supplier, debit_base, Decimal(0), credit.currency,
                 Decimal(rate_for_base(value, debit_base)), value, Decimal(0)),
                (credit_account, credit.supplier, Decimal(0), credit_base,
                 credit.currency, Decimal(rate_for_base(value, credit_base)),
                 Decimal(0), value)}
            signed_variance = (difference if self.kind == "Applied" else -difference)
            if signed_variance:
                expected.add((self.exchange_variance_account, None,
                    max(signed_variance, Decimal(0)),
                    max(-signed_variance, Decimal(0)), prop.currency,
                    Decimal(1), max(signed_variance, Decimal(0)),
                    max(-signed_variance, Decimal(0))))
            found = {(row.account, row.party, Decimal(str(row.debit)),
                Decimal(str(row.credit)), row.account_currency,
                Decimal(str(row.exchange_rate)),
                Decimal(str(row.debit_in_account_currency)),
                Decimal(str(row.credit_in_account_currency))) for row in lines}
            if len(lines) != len(expected) or found != expected:
                frappe.throw(_("Las partidas extranjeras de la aplicación no concilian"))
            return
        expected = {(debit, credit.supplier, value, Decimal(0)),
                    (credit_account, credit.supplier, Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit))) for row in lines} != expected):
            frappe.throw(_("Las partidas de la aplicación no concilian"))

    def on_trash(self):
        frappe.throw(_("La aplicación del crédito del proveedor no se borra"))


class PMSAllocationDocument(ScopedDocument):
    """A payment application is append only and cannot outlive its source."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("La aplicación de pago es inmutable"))
        if self.kind in ("Opening Credit Applied", "Opening Credit Reversed"):
            self._validate_opening_credit()
            return
        if self.kind in ("Opening Guarantee Applied", "Opening Guarantee Reversed"):
            self._validate_opening_guarantee()
            return
        prop = frappe.get_doc("HS Property", self.property)
        receivable = frappe.db.get_value("HS PMS Receivable", self.receivable,
            ["property", "organization", "party", "currency", "folio"], as_dict=True)
        payment = frappe.db.get_value("HS Payment", self.payment,
            ["name", "property", "pms_party", "kind", "status", "pms_receivable", "pms_journal",
             "source_payment", "folio", "booking", "pms_settlement_currency",
             "pms_settled_amount", "pms_released_base_amount"], as_dict=True)
        if receivable and receivable.currency != prop.currency:
            from hospitality_suite.standalone_receivables import opening_balances

            if self.kind == "Direct Reversed":
                original = frappe.db.get_value("HS PMS Allocation", self.reverses,
                    ["name", "property", "receivable", "payment", "kind", "amount",
                     "settlement_currency", "settled_amount"], as_dict=True)
                prior_reversals = frappe.get_all("HS PMS Allocation",
                    filters={"property": prop.name, "reverses": self.reverses},
                    fields=["amount", "settled_amount"])
                if (not getattr(frappe.local, "hs_operation", False) or
                        not payment or not original or
                        receivable.property != prop.name or
                        receivable.organization != prop.organization or
                        payment.property != prop.name or payment.kind != "Refund" or
                        payment.status != "Posted" or
                        payment.source_payment != original.payment or
                        payment.pms_journal != self.journal or
                        payment.pms_receivable != self.receivable or
                        payment.pms_party != receivable.party or
                        self.organization != prop.organization or
                        self.currency != prop.currency or
                        self.settlement_currency != receivable.currency or
                        payment.pms_settlement_currency != receivable.currency or
                        self.opening_credit or self.opening_guarantee or
                        str(self.business_date) != str(prop.business_date) or
                        original.property != prop.name or
                        original.receivable != self.receivable or
                        original.kind != "Direct" or
                        original.settlement_currency != receivable.currency or
                        Decimal(str(self.amount or 0)) !=
                            Decimal(str(payment.pms_released_base_amount or 0)) or
                        Decimal(str(self.settled_amount or 0)) !=
                            Decimal(str(payment.pms_settled_amount or 0)) or
                        Decimal(str(self.amount or 0)) <= 0 or
                        Decimal(str(self.settled_amount or 0)) <= 0 or
                        Decimal(str(self.amount)) + sum((Decimal(str(row.amount))
                            for row in prior_reversals), Decimal(0)) >
                            Decimal(str(original.amount)) or
                        Decimal(str(self.settled_amount)) + sum(
                            (Decimal(str(row.settled_amount or 0))
                             for row in prior_reversals), Decimal(0)) >
                            Decimal(str(original.settled_amount)) or
                        frappe.db.exists("HS PMS Allocation", {
                            "property": prop.name, "payment": payment.name,
                            "kind": "Direct Reversed"})):
                    frappe.throw(_("La reversión extranjera no coincide con el cobro"))
                return
            if (not getattr(frappe.local, "hs_operation", False) or
                    not payment or self.kind != "Direct" or self.reverses or
                    self.opening_credit or self.opening_guarantee or
                    receivable.property != prop.name or
                    receivable.organization != prop.organization or
                    payment.property != prop.name or payment.kind != "Payment" or
                    payment.status != "Posted" or payment.pms_journal != self.journal or
                    payment.pms_receivable != self.receivable or
                    payment.pms_party != receivable.party or
                    self.organization != prop.organization or
                    self.currency != prop.currency or
                    self.settlement_currency != receivable.currency or
                    payment.pms_settlement_currency != receivable.currency or
                    Decimal(str(self.amount or 0)) !=
                        Decimal(str(payment.pms_released_base_amount or 0)) or
                    Decimal(str(self.settled_amount or 0)) !=
                        Decimal(str(payment.pms_settled_amount or 0)) or
                    frappe.db.exists("HS PMS Allocation", {
                        "property": prop.name, "payment": payment.name,
                        "kind": "Direct"})):
                frappe.throw(_("La aplicación extranjera no coincide con el cobro"))
            remaining, base_remaining = opening_balances(prop, self.receivable)
            if (Decimal(str(self.settled_amount)) <= 0 or
                    Decimal(str(self.amount)) <= 0 or
                    Decimal(str(self.settled_amount)) > remaining or
                    Decimal(str(self.amount)) > base_remaining):
                frappe.throw(_("La aplicación supera la cartera extranjera"))
            return
        if self.settlement_currency or Decimal(str(self.settled_amount or 0)) != 0:
            frappe.throw(_("La aplicación en moneda base no usa principal extranjero"))
        reverse_kind = self.kind in ("Direct Reversed", "Advance Reversed", "Guarantee Reversed")
        from hospitality_suite.standalone_receivables import guarantee_matches
        if (not receivable or not payment or receivable.property != prop.name or
                payment.property != prop.name or receivable.organization != prop.organization or
                self.organization != prop.organization or self.currency != prop.currency or
                receivable.currency != prop.currency or receivable.party != payment.pms_party or
                payment.status != "Posted" or
                (self.kind in ("Guarantee Applied", "Guarantee Reversed") and
                 not guarantee_matches(prop, payment, receivable)) or
                (self.kind == "Direct" and (payment.kind != "Payment" or
                                             payment.pms_receivable != self.receivable or
                                             self.journal != payment.pms_journal)) or
                (self.kind == "Advance Applied" and (payment.kind != "Advance" or not self.journal)) or
                (self.kind == "Guarantee Applied" and (payment.kind != "Guarantee" or not self.journal)) or
                (self.kind == "Direct Reversed" and (payment.kind != "Refund" or
                    payment.pms_receivable != self.receivable or self.journal != payment.pms_journal)) or
                (self.kind == "Advance Reversed" and (payment.kind != "Advance" or not self.journal)) or
                (self.kind == "Guarantee Reversed" and (payment.kind != "Guarantee" or not self.journal)) or
                self.kind not in ("Direct", "Advance Applied", "Guarantee Applied",
                                  "Direct Reversed", "Advance Reversed", "Guarantee Reversed") or
                bool(self.reverses) != reverse_kind or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("La aplicación no coincide con el cobro y la cuenta por cobrar"))
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        try:
            if amount(self.amount) <= 0:
                frappe.throw(_("La aplicación debe ser mayor que cero"))
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if reverse_kind:
            original = frappe.db.get_value("HS PMS Allocation", self.reverses,
                ["name", "property", "receivable", "payment", "kind", "amount"], as_dict=True)
            expected_kind = {"Direct Reversed": "Direct", "Advance Reversed": "Advance Applied",
                             "Guarantee Reversed": "Guarantee Applied"}[self.kind]
            if (not original or original.property != prop.name or
                    original.receivable != self.receivable or original.kind != expected_kind or
                    (self.kind in ("Advance Reversed", "Guarantee Reversed") and
                     original.payment != self.payment) or
                    (self.kind == "Direct Reversed" and payment.source_payment != original.payment)):
                frappe.throw(_("La reversión no corresponde a la aplicación original"))
            from hospitality_suite.standalone_receivables import remaining_allocation
            if amount(self.amount) > remaining_allocation(prop, original.name):
                frappe.throw(_("La reversión supera el importe aplicado pendiente"))
        if self.journal and frappe.db.get_value("HS Journal", self.journal, "property") != prop.name:
            frappe.throw(_("El asiento de aplicación pertenece a otro establecimiento"))

    def _validate_opening_credit(self):
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        from hospitality_suite import standalone_opening_credits

        if not getattr(frappe.local, "hs_opening_credit_application", False):
            frappe.throw(_("Use el flujo de aplicación del crédito inicial"))
        prop = frappe.get_doc("HS Property", self.property)
        credit = frappe.db.get_value("HS PMS Opening Credit", self.opening_credit,
            ["name", "property", "organization", "customer", "receivable_account",
             "currency", "status"], as_dict=True)
        receivable = frappe.db.get_value("HS PMS Receivable", self.receivable,
            ["name", "property", "organization", "party", "receivable_account",
             "currency", "status"], as_dict=True)
        if credit and credit.currency != prop.currency:
            self._validate_opening_credit_foreign(prop, credit, receivable,
                standalone_opening_credits)
            return
        if (not credit or not receivable or self.payment or
                credit.property != prop.name or receivable.property != prop.name or
                credit.organization != prop.organization or
                receivable.organization != prop.organization or
                self.organization != prop.organization or
                credit.customer != receivable.party or
                credit.currency != prop.currency or receivable.currency != prop.currency or
                self.currency != prop.currency or credit.status != "Posted" or
                receivable.status != "Posted" or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("El crédito y la cuenta por cobrar no coinciden"))
        try:
            value = amount(self.amount)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0:
            frappe.throw(_("La aplicación debe ser positiva"))
        if self.kind == "Opening Credit Applied":
            if self.reverses or value > standalone_opening_credits.available(
                    prop, credit.name) or value > standalone_opening_credits.receivable_due(
                    prop, receivable.name):
                frappe.throw(_("La aplicación supera el crédito o la cuenta pendiente"))
            debit_account, credit_account = (credit.receivable_account,
                                             receivable.receivable_account)
        else:
            original = frappe.db.get_value("HS PMS Allocation", self.reverses,
                ["property", "kind", "opening_credit", "receivable",
                 "opening_credit_exchange_account"], as_dict=True)
            if (not original or original.property != prop.name or
                    original.kind != "Opening Credit Applied" or
                    original.opening_credit != credit.name or
                    original.receivable != receivable.name or
                    value > standalone_opening_credits.remaining_application(
                        prop, self.reverses)):
                frappe.throw(_("La reversión supera la aplicación original"))
            debit_account, credit_account = (receivable.receivable_account,
                                             credit.receivable_account)
        if debit_account == credit_account:
            if self.journal:
                frappe.throw(_("La aplicación en la misma cuenta no necesita asiento"))
            return
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "source_doctype", "purpose", "status"], as_dict=True)
        if (not journal or journal.property != prop.name or
                journal.source_doctype != "HS PMS Allocation" or
                journal.purpose != self.kind or journal.status != "Posted"):
            frappe.throw(_("El traspaso contable del crédito no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit"])
        expected = {(debit_account, credit.customer, value, Decimal(0)),
                    (credit_account, credit.customer, Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit)))
                for row in lines} != expected):
            frappe.throw(_("El asiento de aplicación del crédito no concilia"))

    def _validate_opening_credit_foreign(self, prop, credit, receivable, credits):
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        from hospitality_suite.standalone_receivables import opening_balances

        if (not self.is_new() or not receivable or self.payment or
                self.kind not in ("Opening Credit Applied", "Opening Credit Reversed") or
                credit.property != prop.name or receivable.property != prop.name or
                credit.organization != prop.organization or
                receivable.organization != prop.organization or
                self.organization != prop.organization or
                credit.customer != receivable.party or
                credit.currency != receivable.currency or
                credit.status != "Posted" or receivable.status != "Posted" or
                self.currency != prop.currency or
                self.settlement_currency != credit.currency or
                str(self.business_date) != str(prop.business_date)):
            frappe.throw(_("La aplicación extranjera no coincide con el crédito"))
        try:
            original_value = amount(self.settled_amount)
            target_base = amount(self.amount)
            source_base = amount(self.opening_credit_base_amount)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if min(original_value, target_base, source_base) <= 0:
            frappe.throw(_("La aplicación extranjera requiere importes positivos"))
        if self.kind == "Opening Credit Applied":
            available, source_left = credits.balances(prop, credit.name)
            due, target_left = opening_balances(prop, receivable.name)
            if (self.reverses or original_value > available or
                    source_base > source_left or original_value > due or
                    target_base > target_left):
                frappe.throw(_("La aplicación supera el crédito o la cartera extranjera"))
            debit_account, credit_account = (credit.receivable_account,
                receivable.receivable_account)
            difference = source_base - target_base
            debit_base, credit_base = source_base, target_base
        else:
            original = frappe.db.get_value("HS PMS Allocation", self.reverses,
                ["property", "kind", "opening_credit", "receivable",
                 "opening_credit_exchange_account"], as_dict=True)
            if (not original or original.property != prop.name or
                    original.kind != "Opening Credit Applied" or
                    original.opening_credit != credit.name or
                    original.receivable != receivable.name):
                frappe.throw(_("La reversión extranjera no corresponde a la aplicación"))
            nominal_left, source_left, target_left = credits.application_balances(
                prop, self.reverses)
            if (original_value > nominal_left or source_base > source_left or
                    target_base > target_left or
                    self.opening_credit_exchange_account !=
                        original.opening_credit_exchange_account):
                frappe.throw(_("La reversión supera la aplicación extranjera"))
            debit_account, credit_account = (receivable.receivable_account,
                credit.receivable_account)
            difference = target_base - source_base
            debit_base, credit_base = target_base, source_base
        if debit_account == credit_account and difference == 0:
            if self.journal:
                frappe.throw(_("La aplicación extranjera no necesita asiento"))
            return
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "source_doctype", "purpose", "status"], as_dict=True)
        if (not journal or journal.property != prop.name or
                journal.source_doctype != "HS PMS Allocation" or
                journal.purpose != self.kind or journal.status != "Posted"):
            frappe.throw(_("El asiento de aplicación extranjera no coincide"))
        expected = {
            (debit_account, credit.customer, debit_base, Decimal(0),
             original_value, Decimal(0)),
            (credit_account, credit.customer, Decimal(0), credit_base,
             Decimal(0), original_value)}
        if difference:
            if not self.opening_credit_exchange_account:
                frappe.throw(_("La diferencia cambiaria no conserva su cuenta"))
            expected.add((self.opening_credit_exchange_account, None,
                max(-difference, Decimal(0)), max(difference, Decimal(0)),
                max(-difference, Decimal(0)), max(difference, Decimal(0))))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit",
                "debit_in_account_currency", "credit_in_account_currency"])
        actual = {(row.account, row.party, Decimal(str(row.debit)),
            Decimal(str(row.credit)), Decimal(str(row.debit_in_account_currency)),
            Decimal(str(row.credit_in_account_currency))) for row in lines}
        if len(lines) != len(expected) or actual != expected:
            frappe.throw(_("El asiento del crédito extranjero no concilia"))

    def _validate_opening_guarantee(self):
        from decimal import Decimal
        from hospitality_suite.ledger_rules import LedgerValidationError, amount
        from hospitality_suite import standalone_opening_guarantees

        if not getattr(frappe.local, "hs_opening_guarantee_application", False):
            frappe.throw(_("Use el flujo de aplicación de la garantía inicial"))
        prop = frappe.get_doc("HS Property", self.property)
        guarantee = frappe.db.get_value("HS PMS Opening Guarantee",
            self.opening_guarantee, ["name", "property", "organization", "customer",
                "liability_account", "currency", "status", "source_folio",
                "source_booking", "source_stay"], as_dict=True)
        receivable = frappe.db.get_value("HS PMS Receivable", self.receivable,
            ["name", "property", "organization", "party", "receivable_account",
                "currency", "status", "folio"], as_dict=True)
        if (not guarantee or not receivable or self.payment or self.opening_credit or
                guarantee.property != prop.name or receivable.property != prop.name or
                guarantee.organization != prop.organization or
                receivable.organization != prop.organization or
                self.organization != prop.organization or
                guarantee.customer != receivable.party or
                guarantee.currency != prop.currency or
                receivable.currency != prop.currency or
                self.currency != prop.currency or guarantee.status != "Posted" or
                receivable.status != "Posted" or
                str(self.business_date) != str(prop.business_date) or
                not standalone_opening_guarantees.matches(prop, guarantee, receivable)):
            frappe.throw(_("La garantía inicial no corresponde al cliente y la cuenta de estancia"))
        try:
            value = amount(self.amount)
        except LedgerValidationError as exc:
            frappe.throw(str(exc))
        if value <= 0:
            frappe.throw(_("La aplicación debe ser positiva"))
        if self.kind == "Opening Guarantee Applied":
            if (self.reverses or value > standalone_opening_guarantees.available(
                    prop, guarantee.name) or value >
                    standalone_opening_guarantees.receivable_due(prop, receivable.name)):
                frappe.throw(_("La aplicación supera la garantía o la cuenta pendiente"))
            debit_account, debit_party = guarantee.liability_account, None
            credit_account, credit_party = receivable.receivable_account, guarantee.customer
        else:
            original = frappe.db.get_value("HS PMS Allocation", self.reverses,
                ["property", "kind", "opening_guarantee", "receivable"], as_dict=True)
            if (not original or original.property != prop.name or
                    original.kind != "Opening Guarantee Applied" or
                    original.opening_guarantee != guarantee.name or
                    original.receivable != receivable.name or
                    value > standalone_opening_guarantees.remaining_application(
                        prop, self.reverses)):
                frappe.throw(_("La reversión supera la aplicación original"))
            debit_account, debit_party = receivable.receivable_account, guarantee.customer
            credit_account, credit_party = guarantee.liability_account, None
        journal = frappe.db.get_value("HS Journal", self.journal,
            ["property", "source_doctype", "purpose", "status"], as_dict=True)
        if (not journal or journal.property != prop.name or
                journal.source_doctype != "HS PMS Allocation" or
                journal.purpose != self.kind or journal.status != "Posted"):
            frappe.throw(_("El asiento de la garantía inicial no coincide"))
        lines = frappe.get_all("HS Journal Line", filters={"parent": self.journal},
            fields=["account", "party", "debit", "credit"])
        expected = {(debit_account, debit_party, value, Decimal(0)),
                    (credit_account, credit_party, Decimal(0), value)}
        if (len(lines) != 2 or {(row.account, row.party,
                Decimal(str(row.debit)), Decimal(str(row.credit)))
                for row in lines} != expected):
            frappe.throw(_("El asiento de aplicación de la garantía no concilia"))

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
            historical_return = (getattr(frappe.local,
                "hs_historical_day_pass_return", False) and self.purpose in
                ("Historical Day Pass Credit", "Historical Day Pass Refund") or
                getattr(frappe.local, "hs_historical_maintenance_return", False)
                and self.source_doctype == "HS Stock Movement" and
                self.purpose == "Receipt")
            if not account or (account.property, account.organization) != (self.property, self.organization) or (not account.active and not historical_return) or account.is_group:
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
            historical_return = (self.direction == "Receipt" and
                self.source_doctype == "HS Service Request" and
                self.purpose == "Guest Service Return" or
                self.direction == "Receipt" and
                self.source_doctype == "HS Maintenance Order" and
                getattr(frappe.local, "hs_historical_maintenance_return", False))
            supplier_return = (self.direction == "Issue" and
                self.source_doctype == "HS PMS Purchase Return" and
                self.purpose == "Supplier Return" and
                frappe.db.exists("HS PMS Purchase Return", {"name": self.source_name,
                    "property": self.property, "status": "Posted"}))
            if (not row or (row.property, row.organization) != (self.property, self.organization)
                    or (not row.active and not (historical_return or supplier_return))):
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


class PMSInventoryRecordDocument(ScopedDocument):
    """Immutable source documents for stock transfers and physical counts."""

    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("El registro de inventario es inmutable; documente otro ajuste"))
        prop = frappe.get_doc("HS Property", self.property)
        if self.organization != prop.organization or self.status not in ("Posted", "Completed"):
            frappe.throw(_("El registro de inventario no coincide con la entidad"))
        for field in ("product", "warehouse", "source_warehouse", "target_warehouse"):
            name = self.get(field)
            if not name:
                continue
            doctype = "HS Product" if field == "product" else "HS Warehouse"
            row = frappe.db.get_value(doctype, name,
                ["property", "organization"], as_dict=True)
            if not row or (row.property, row.organization) != (prop.name, prop.organization):
                frappe.throw(_("El producto o almacén pertenece a otro establecimiento"))
        if frappe.db.exists(self.doctype, {"property": prop.name,
                "reference": self.reference, "name": ["!=", self.name]}):
            frappe.throw(_("La referencia ya se usó en este establecimiento"))

    def on_trash(self):
        frappe.throw(_("Los conteos y traslados publicados no se borran"))


class PMSPurchaseDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            old = self.get_doc_before_save()
            fixed = ("property", "company", "organization", "supplier",
                "supplier_reference", "purchase_order", "product", "warehouse", "quantity",
                "invoice_currency", "invoice_amount", "recoverable_tax",
                "exchange_rate", "rate_record", "base_amount", "base_cost",
                "base_tax", "payable_account", "inventory_account",
                "tax_account", "stock_movement", "tax_journal", "business_date",
                "notes")
            line_fields = ("product", "warehouse", "order_line", "quantity", "invoice_currency",
                "base_currency", "invoice_amount", "recoverable_tax",
                "base_amount", "base_cost", "base_tax", "inventory_account",
                "stock_movement")
            source_lines = [tuple(row.get(field) for field in line_fields)
                for row in old.lines] if old else []
            current_lines = [tuple(row.get(field) for field in line_fields)
                for row in self.lines]
            returned = frappe.db.get_value("HS PMS Purchase Return",
                self.cancellation_return,
                ["property", "purchase", "kind", "status", "base_credit",
                 "supplier_credit"], as_dict=True)
            if (not old or old.status != "Posted" or self.status != "Cancelled" or
                    any(old.get(field) != self.get(field) for field in fixed) or
                    source_lines != current_lines or not self.cancellation_reason or
                    not self.cancellation_reason.strip() or
                    len(self.cancellation_reason.strip()) > 500 or
                    not self.cancelled_at or not returned or
                    returned.property != self.property or returned.purchase != self.name or
                    returned.kind != "Full Cancellation" or returned.status != "Posted" or
                    Decimal(str(returned.base_credit)) != Decimal(str(self.base_amount)) or
                    Decimal(str(returned.supplier_credit)) != 0 or
                    frappe.db.count("HS PMS Purchase Return", {"property": self.property,
                        "purchase": self.name}) != 1 or
                    frappe.db.exists("HS Payment", {"property": self.property,
                        "pms_purchase": self.name, "kind": "Supplier Payment",
                        "status": "Posted"})):
                frappe.throw(_("La compra publicada solo admite cancelación íntegra sin pagos"))
            return
        if self.cancellation_return or self.cancellation_reason or self.cancelled_at:
            frappe.throw(_("La cancelación se registra después de publicar la compra"))
        from hospitality_suite.standalone_accounting import account
        from hospitality_suite.standalone_currency import enabled
        prop = frappe.get_doc("HS Property", self.property)
        supplier = frappe.db.get_value("HS Party", self.supplier,
            ["property", "organization", "party_type", "active"], as_dict=True)
        product = frappe.db.get_value("HS Product", self.product,
            ["property", "organization", "product_type", "inventory_account", "active"], as_dict=True)
        warehouse = frappe.db.get_value("HS Warehouse", self.warehouse,
            ["property", "organization", "active"], as_dict=True)
        if (self.organization != prop.organization or self.status != "Posted" or
                not enabled(prop, self.invoice_currency) or
                not supplier or (supplier.property, supplier.organization) !=
                    (prop.name, prop.organization) or supplier.party_type not in ("Supplier", "Both") or
                not supplier.active or not product or
                (product.property, product.organization) != (prop.name, prop.organization) or
                product.product_type != "Stock" or not product.active or
                not warehouse or (warehouse.property, warehouse.organization) !=
                    (prop.name, prop.organization) or not warehouse.active or
                self.inventory_account != product.inventory_account):
            frappe.throw(_("La compra requiere proveedor, producto y almacén activos del establecimiento"))
        if (not self.supplier_reference or len(self.supplier_reference.strip()) > 140 or
                frappe.db.exists("HS PMS Purchase", {"property": prop.name,
                    "supplier": self.supplier, "supplier_reference": self.supplier_reference,
                    "name": ["!=", self.name]})):
            frappe.throw(_("La referencia del proveedor ya existe o no es válida"))
        payable = account(prop, self.payable_account)
        inventory = account(prop, self.inventory_account)
        if (payable.root_type != "Liability" or payable.account_type != "Payable" or
                payable.account_currency != prop.currency or inventory.root_type != "Asset" or
                inventory.account_currency != prop.currency):
            frappe.throw(_("La compra requiere cuentas de inventario y por pagar en moneda base"))
        if self.tax_account:
            tax = account(prop, self.tax_account)
            if (tax.root_type != "Asset" or tax.account_type != "Tax" or
                    tax.account_currency != prop.currency):
                frappe.throw(_("El impuesto recuperable requiere una cuenta de activo en moneda base"))
        try:
            invoice = Decimal(str(self.invoice_amount))
            recoverable = Decimal(str(self.recoverable_tax or 0))
            base = Decimal(str(self.base_amount))
            cost = Decimal(str(self.base_cost))
            tax = Decimal(str(self.base_tax or 0))
            rate = Decimal(str(self.exchange_rate))
            quantity = Decimal(str(self.quantity))
        except (InvalidOperation, ValueError, TypeError):
            frappe.throw(_("Los importes de la compra no son válidos"))
        if (not all(value.is_finite() for value in (invoice, recoverable, base, cost, tax, rate, quantity)) or
                min(invoice, base, cost, rate, quantity) <= 0 or recoverable < 0 or tax < 0 or
                recoverable >= invoice or base != cost + tax or
                base != (invoice * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) or
                tax != (recoverable * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) or
                bool(recoverable) != bool(self.tax_account)):
            frappe.throw(_("Base, impuesto, costo y cambio de la compra no concilian"))
        if self.lines:
            if not 1 <= len(self.lines) <= 50:
                frappe.throw(_("La compra admite de una a cincuenta líneas"))
            first = self.lines[0]
            if (first.product, first.warehouse, Decimal(str(first.quantity)),
                    first.inventory_account) != (self.product, self.warehouse, quantity,
                                               self.inventory_account):
                frappe.throw(_("El encabezado no coincide con la primera línea de compra"))
            seen = set()
            totals = [Decimal(0)] * 5
            for line in self.lines:
                pair = (line.product, line.warehouse)
                if pair in seen or line.stock_movement:
                    frappe.throw(_("Repita cada producto y almacén una sola vez y sin movimiento previo"))
                seen.add(pair)
                if (line.invoice_currency != self.invoice_currency or
                        line.base_currency != prop.currency):
                    frappe.throw(_("Las monedas de cada línea deben coincidir con la factura"))
                item = frappe.db.get_value("HS Product", line.product,
                    ["property", "organization", "product_type", "inventory_account", "active"],
                    as_dict=True)
                store = frappe.db.get_value("HS Warehouse", line.warehouse,
                    ["property", "organization", "active"], as_dict=True)
                if (not item or not store or
                        (item.property, item.organization, item.product_type,
                         item.inventory_account, item.active) !=
                        (prop.name, prop.organization, "Stock", line.inventory_account, 1) or
                        (store.property, store.organization, store.active) !=
                        (prop.name, prop.organization, 1)):
                    frappe.throw(_("Cada línea requiere producto y almacén activos del establecimiento"))
                inventory_line = account(prop, line.inventory_account)
                if (inventory_line.root_type != "Asset" or
                        inventory_line.account_currency != prop.currency or
                        inventory_line.name == self.tax_account):
                    frappe.throw(_("La cuenta de inventario de una línea no es válida"))
                try:
                    values = [Decimal(str(line.get(field) or 0)) for field in
                        ("invoice_amount", "recoverable_tax", "base_amount", "base_cost", "base_tax")]
                    line_quantity = Decimal(str(line.quantity))
                except (InvalidOperation, ValueError, TypeError):
                    frappe.throw(_("Revise cantidad e importes de las líneas"))
                if (not line_quantity.is_finite() or line_quantity <= 0 or
                        not all(value.is_finite() for value in values) or
                        min(values[0], values[2], values[3]) <= 0 or
                        values[1] < 0 or values[4] < 0 or values[1] >= values[0] or
                        values[2] != values[3] + values[4]):
                    frappe.throw(_("La línea de compra no concilia"))
                totals = [total + value for total, value in zip(totals, values)]
            if totals != [invoice, recoverable, base, cost, tax]:
                frappe.throw(_("Las líneas no concilian con el total de la factura"))
        if self.purchase_order:
            from hospitality_suite.standalone_purchase_orders import allocation, progress
            order = frappe.get_doc("HS PMS Purchase Order", self.purchase_order)
            if (not self.lines or order.property != prop.name or
                    order.organization != prop.organization or order.status != "Approved" or
                    order.supplier != self.supplier or order.currency != self.invoice_currency or
                    order.payable_account != self.payable_account or
                    (order.tax_account or None) != (self.tax_account or None)):
                frappe.throw(_("La compra no coincide con una orden aprobada"))
            ordered_lines = {row.name: row for row in order.lines}
            for line in self.lines:
                source = ordered_lines.get(line.order_line)
                if (not source or source.product != line.product or
                        source.warehouse != line.warehouse or
                        source.inventory_account != line.inventory_account):
                    frappe.throw(_("La línea de compra no pertenece a la orden"))
                expected_amount, expected_tax = allocation(
                    source, progress(prop, source.name), Decimal(str(line.quantity)))
                if (Decimal(str(line.invoice_amount)) != expected_amount or
                        Decimal(str(line.recoverable_tax or 0)) != expected_tax):
                    frappe.throw(_("Cantidad o precio de la recepción supera la orden"))
        elif any(line.order_line for line in self.lines):
            frappe.throw(_("Una línea de orden requiere el vínculo en la compra"))

    def on_trash(self):
        frappe.throw(_("Las compras publicadas no se borran"))


class PMSPurchaseOrderDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            old = self.get_doc_before_save()
            fixed = ("property", "company", "organization", "supplier", "reference",
                "currency", "payable_account", "tax_account", "amount",
                "recoverable_tax", "business_date", "expected_date", "notes",
                "requested_by")
            line_fields = ("product", "warehouse", "quantity", "currency",
                "amount", "recoverable_tax", "inventory_account")
            if (not old or any(old.get(field) != self.get(field) for field in fixed) or
                    [tuple(row.get(field) for field in line_fields) for row in old.lines] !=
                    [tuple(row.get(field) for field in line_fields) for row in self.lines]):
                frappe.throw(_("La orden solicitada conserva sus líneas e importes"))
            transition = (old.status, self.status)
            if transition == ("Pending", "Approved"):
                if (not self.approved_by or self.approved_by != frappe.session.user or
                        self.approved_by == self.requested_by or not self.approved_at or
                        self.close_reason or self.closed_at):
                    frappe.throw(_("Otra persona de Gerencia debe aprobar la orden"))
            elif transition in (("Pending", "Cancelled"), ("Approved", "Closed"),
                                ("Approved", "Cancelled")):
                if (not self.close_reason or not self.close_reason.strip() or
                        len(self.close_reason.strip()) > 500 or not self.closed_at or
                        (transition[0] == "Pending" and
                         (self.approved_by or self.approved_at)) or
                        (transition[0] == "Approved" and
                         (self.approved_by != old.approved_by or
                          self.approved_at != old.approved_at))):
                    frappe.throw(_("Explique el cierre de la orden sin cambiar su aprobación"))
            else:
                frappe.throw(_("Estado de orden de compra inválido"))
            return
        from hospitality_suite.standalone_accounting import account
        from hospitality_suite.standalone_currency import enabled
        prop = frappe.get_doc("HS Property", self.property)
        supplier = frappe.db.get_value("HS Party", self.supplier,
            ["property", "organization", "party_type", "active"], as_dict=True)
        if (self.organization != prop.organization or self.status != "Pending" or
                self.requested_by != frappe.session.user or self.approved_by or
                self.approved_at or self.close_reason or self.closed_at or
                not supplier or (supplier.property, supplier.organization) !=
                (prop.name, prop.organization) or not supplier.active or
                supplier.party_type not in ("Supplier", "Both") or
                not enabled(prop, self.currency) or not 1 <= len(self.lines) <= 50 or
                not self.reference or len(self.reference.strip()) > 140 or
                frappe.db.exists("HS PMS Purchase Order", {"property": prop.name,
                    "reference": self.reference})):
            frappe.throw(_("Revise proveedor, moneda, referencia y líneas de la orden"))
        payable = account(prop, self.payable_account)
        if (payable.root_type != "Liability" or payable.account_type != "Payable" or
                payable.account_currency != prop.currency):
            frappe.throw(_("La orden requiere cuenta por pagar en moneda base"))
        if self.tax_account:
            tax_account = account(prop, self.tax_account)
            if (tax_account.root_type != "Asset" or tax_account.account_type != "Tax" or
                    tax_account.account_currency != prop.currency):
                frappe.throw(_("La cuenta de impuesto recuperable de la orden no es válida"))
        amounts = taxes = Decimal(0)
        seen = set()
        for line in self.lines:
            product = frappe.db.get_value("HS Product", line.product,
                ["property", "organization", "product_type", "active",
                 "inventory_account"], as_dict=True)
            warehouse = frappe.db.get_value("HS Warehouse", line.warehouse,
                ["property", "organization", "active"], as_dict=True)
            if (not product or not warehouse or
                    (line.product, line.warehouse) in seen or
                    (product.property, product.organization, product.product_type,
                     product.active, product.inventory_account) !=
                    (prop.name, prop.organization, "Stock", 1, line.inventory_account) or
                    (warehouse.property, warehouse.organization, warehouse.active) !=
                    (prop.name, prop.organization, 1) or line.currency != self.currency):
                frappe.throw(_("Cada línea necesita producto y almacén activos y únicos"))
            seen.add((line.product, line.warehouse))
            inventory = account(prop, line.inventory_account)
            if inventory.root_type != "Asset" or inventory.account_currency != prop.currency:
                frappe.throw(_("La cuenta de inventario de una línea no es válida"))
            try:
                qty = Decimal(str(line.quantity))
                value = Decimal(str(line.amount))
                tax = Decimal(str(line.recoverable_tax or 0))
            except (InvalidOperation, ValueError, TypeError):
                frappe.throw(_("Los importes de la orden no son válidos"))
            if (not all(number.is_finite() for number in (qty, value, tax)) or
                    qty <= 0 or value <= 0 or tax < 0 or tax >= value):
                frappe.throw(_("La línea de orden requiere cantidad y costo positivos"))
            amounts += value
            taxes += tax
        if (Decimal(str(self.amount)) != amounts or
                Decimal(str(self.recoverable_tax or 0)) != taxes or
                bool(taxes) != bool(self.tax_account)):
            frappe.throw(_("El total de la orden no concilia con sus líneas"))

    def on_trash(self):
        frappe.throw(_("Las órdenes de compra se cierran, no se borran"))


class PMSPurchaseReturnDocument(ScopedDocument):
    def validate(self):
        super().validate()
        if not self.is_new():
            frappe.throw(_("La devolución publicada es inmutable"))
        prop = frappe.get_doc("HS Property", self.property)
        purchase = frappe.db.get_value("HS PMS Purchase", self.purchase,
            ["property", "organization", "supplier", "invoice_currency",
             "payable_account", "tax_account", "status"], as_dict=True)
        if (not purchase or purchase.property != prop.name or
                purchase.organization != prop.organization or purchase.status != "Posted" or
                self.organization != prop.organization or self.supplier != purchase.supplier or
                self.invoice_currency != purchase.invoice_currency or
                self.base_currency != prop.currency or
                self.payable_account != purchase.payable_account or
                self.tax_account != purchase.tax_account or self.status != "Posted" or
                self.kind not in ("Return", "Full Cancellation") or
                not self.reason or not self.reason.strip() or
                not self.reference or not self.reference.strip() or
                not 1 <= len(self.lines) <= 50):
            frappe.throw(_("La devolución no coincide con la factura del proveedor"))
        if frappe.db.exists("HS PMS Purchase Return", {"property": prop.name,
                "purchase": self.purchase, "reference": self.reference}):
            frappe.throw(_("La referencia de devolución ya se utilizó"))
        try:
            credit, tax, stock, variance, payable, supplier_credit = (
                Decimal(str(self.get(field) or 0)) for field in
                ("base_credit", "base_tax", "stock_value", "variance",
                 "payable_applied", "supplier_credit"))
            original_credit = Decimal(str(self.credit_amount))
            row_totals = [sum((Decimal(str(row.get(field) or 0)) for row in self.lines), Decimal(0))
                for field in ("credit_amount", "base_credit", "base_tax", "stock_value")]
        except (InvalidOperation, ValueError, TypeError):
            frappe.throw(_("Los importes de devolución no son válidos"))
        if (not all(value.is_finite() for value in
                    (credit, tax, stock, variance, payable, supplier_credit,
                     original_credit, *row_totals)) or
                min(credit, stock, original_credit) <= 0 or
                tax < 0 or payable < 0 or supplier_credit < 0 or
                variance != credit - tax - stock or
                payable + supplier_credit != credit or
                (self.kind == "Full Cancellation" and supplier_credit != 0) or
                row_totals != [original_credit, credit, tax, stock] or
                bool(variance) != bool(self.variance_account)):
            frappe.throw(_("Costo, impuesto y crédito de la devolución no concilian"))
        seen = set()
        for row in self.lines:
            source = frappe.db.get_value("HS Stock Movement", row.source_movement,
                ["property", "source_doctype", "source_name", "direction",
                 "product", "warehouse"], as_dict=True)
            if (row.source_movement in seen or row.return_movement or
                    not source or source.property != prop.name or
                    source.source_doctype != "HS PMS Purchase" or
                    source.source_name != self.purchase or source.direction != "Receipt" or
                    (row.product, row.warehouse) != (source.product, source.warehouse) or
                    row.invoice_currency != self.invoice_currency or
                    row.base_currency != prop.currency):
                frappe.throw(_("La línea devuelta no pertenece a la recepción original"))
            seen.add(row.source_movement)
            try:
                quantity_returned = Decimal(str(row.quantity))
                line_credit = Decimal(str(row.credit_amount))
                line_tax = Decimal(str(row.tax_amount or 0))
                line_base = Decimal(str(row.base_credit))
                line_base_tax = Decimal(str(row.base_tax or 0))
                line_stock = Decimal(str(row.stock_value))
            except (InvalidOperation, ValueError, TypeError):
                frappe.throw(_("La línea de devolución tiene importes inválidos"))
            if (not all(value.is_finite() for value in (quantity_returned,
                    line_credit, line_tax, line_base, line_base_tax, line_stock)) or
                    min(quantity_returned, line_stock) <= 0 or
                    line_credit <= line_tax or line_base <= line_base_tax or
                    line_tax < 0 or line_base_tax < 0):
                frappe.throw(_("La línea de devolución no conserva costo y crédito positivos"))

    def on_trash(self):
        frappe.throw(_("Las devoluciones publicadas no se borran"))


class PMSTreasuryMovementDocument(ScopedDocument):
    def validate(self):
        super().validate()
        from hospitality_suite.standalone_accounting import provider
        if provider() != "pms":
            return
        from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
        from hospitality_suite.standalone_currency import enabled
        prop = frappe.get_doc("HS Property", self.property)
        if self.kind in ("Initial Fund", "Replenishment"):
            if self.status not in ("Approved", "Posted", "Cancelled") or not self.requested_by or (
                    self.kind == "Initial Fund" and self.rendition) or (
                    self.kind == "Replenishment" and not self.rendition) or self.concept or (
                    self.currency != prop.currency) or self.counter_account != prop.petty_cash_account:
                frappe.throw(_("La entrega de Caja Chica no coincide con el establecimiento"))
            try:
                fund_amount = Decimal(str(self.amount))
                fund_base = Decimal(str(self.base_amount))
                fund_rate = Decimal(str(self.exchange_rate or 0))
            except (InvalidOperation, ValueError, TypeError):
                frappe.throw(_("El importe del fondo no es válido"))
            if (not fund_amount.is_finite() or fund_amount <= 0 or
                    fund_base != fund_amount or fund_rate not in (0, 1)):
                frappe.throw(_("La entrega de Caja Chica usa moneda base"))
            old_fund = self.get_doc_before_save()
            if old_fund:
                if (old_fund.status, self.status) not in (("Approved", "Posted"),
                        ("Posted", "Cancelled")) or any(old_fund.get(field) != self.get(field)
                        for field in ("property", "company", "kind", "rendition",
                                      "counter_account", "currency", "requested_by")) or (
                        Decimal(str(old_fund.amount)) != fund_amount):
                    frappe.throw(_("La entrega de Caja Chica es inmutable"))
            elif self.status != "Approved" or self.pms_journal:
                frappe.throw(_("Primero registre la entrega dentro de la operación"))
            if self.status in ("Posted", "Cancelled"):
                journal = frappe.db.get_value("HS Journal", self.pms_journal,
                    ["property", "source_doctype", "source_name", "purpose", "status"], as_dict=True)
                if (not journal or journal.property != prop.name or
                        journal.source_doctype != self.doctype or journal.source_name != self.name or
                        journal.purpose != self.kind or journal.status != "Posted" or
                        not self.method or not self.shift or not self.cash_account):
                    frappe.throw(_("La entrega no conserva un asiento PMS válido"))
                if self.status == "Cancelled" and not frappe.db.exists("HS Journal", {
                        "name": self.pms_reversal_journal,
                        "reversal_of": self.pms_journal, "property": prop.name}):
                    frappe.throw(_("La cancelación requiere asiento inverso"))
            return
        if self.kind not in ("Other Income", "Loan Received", "Loan Repayment",
                             "Capital Contribution", "Capital Withdrawal"):
            frappe.throw(_("Seleccione un movimiento financiero PMS válido"))
        if self.status not in ("Pending Approval", "Approved", "Posted", "Cancelled"):
            frappe.throw(_("El estado financiero no es válido"))
        if not self.requested_by or not self.counter_account or not self.concept or not self.concept_label:
            frappe.throw(_("Conserve solicitante, concepto y cuenta del movimiento"))
        if not enabled(prop, self.currency):
            frappe.throw(_("La moneda del movimiento no está habilitada"))
        try:
            value = Decimal(str(self.amount))
            base = Decimal(str(self.base_amount))
            rate = Decimal(str(self.exchange_rate or 0))
        except (InvalidOperation, ValueError, TypeError):
            frappe.throw(_("Los importes del movimiento no son válidos"))
        if not value.is_finite() or not base.is_finite() or min(value, base) <= 0:
            frappe.throw(_("Los importes del movimiento deben ser positivos"))
        if self.status == "Posted":
            journal = frappe.db.get_value("HS Journal", self.pms_journal,
                ["property", "source_doctype", "source_name", "purpose", "status"], as_dict=True)
            if (not journal or journal.property != prop.name or
                    journal.source_doctype != self.doctype or journal.source_name != self.name or
                    journal.purpose != self.kind or journal.status != "Posted" or
                    not self.method or not self.cash_account or not self.reference or
                    rate <= 0 or not rate.is_finite() or
                    (value * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != base):
                frappe.throw(_("El movimiento no conserva un asiento y cambio válidos"))
        elif self.pms_journal:
            frappe.throw(_("Una solicitud sin publicar no debe enlazar un asiento"))
        old = self.get_doc_before_save()
        if old:
            if old.status in ("Posted", "Cancelled"):
                frappe.throw(_("El movimiento publicado o cancelado es inmutable"))
            if (old.status, self.status) not in (("Pending Approval", "Approved"),
                    ("Pending Approval", "Cancelled"), ("Approved", "Posted"),
                    ("Approved", "Cancelled")):
                frappe.throw(_("La transición financiera no es válida"))
            immutable = ("property", "company", "kind", "concept", "concept_label",
                         "source_movement", "counter_account", "requested_by")
            if (any(old.get(field) != self.get(field) for field in immutable) or
                    Decimal(str(old.base_amount)) != base):
                frappe.throw(_("Conserve el principal y las cuentas aprobadas"))
            if self.status == "Approved" and (not self.approved_by or
                    self.approved_by == self.requested_by or not self.approved_at):
                frappe.throw(_("La aprobación requiere otro usuario"))
            if self.status == "Posted" and self.kind != "Other Income" and (
                    not old.approved_by or old.approved_by == old.requested_by):
                frappe.throw(_("El movimiento no conserva aprobación independiente"))
        elif self.status not in ("Pending Approval", "Approved") or (
                self.status == "Approved" and self.kind != "Other Income"):
            frappe.throw(_("Primero registre una solicitud financiera"))

    def on_trash(self):
        from hospitality_suite.standalone_accounting import provider
        if provider() == "pms":
            frappe.throw(_("Conserve la trazabilidad del movimiento financiero PMS"))
