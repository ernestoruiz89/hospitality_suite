"""ERPNext is the sole accounting system. All postings use standard controllers."""
from decimal import Decimal

import frappe
from frappe.utils import nowdate, now_datetime

from hospitality_suite.pricing import decimal, money
from hospitality_suite.security import document, require
from hospitality_suite.service import insert, audit, operation


def ready(prop):
    from hospitality_suite.install import validate_financial_configuration
    if not prop.financial_enabled:
        frappe.throw("Habilite y valide la configuración financiera")
    validate_financial_configuration(prop)


def post_standard(doc, prop):
    """Delegated, narrowly scoped integration: validated PMS action may post its own
    ERP document without granting operational users general accounting privileges.
    No caller supplies arbitrary account lines or a doctype to this helper.
    """
    doc.hs_property = prop.name
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def folio_balance(name):
    folio = document("HS Folio", name)
    pending = sum(decimal(r.amount) for r in frappe.get_all("HS Charge", filters={"folio": name, "status": "Pending"}, fields=["amount"]))
    invoices = frappe.get_all("HS Charge", filters={"folio": name, "status": "Invoiced"}, pluck="sales_invoice")
    outstanding = sum(decimal(frappe.db.get_value("Sales Invoice", inv, "outstanding_amount")) for inv in set(invoices) if inv)
    return dict(pending=str(money(pending)), outstanding=str(money(outstanding + pending)), currency=folio.currency)


def invoice_folio(prop, data):
    ready(prop)
    folio = document("HS Folio", data["folio"])
    charges = frappe.get_all("HS Charge", filters={"folio": folio.name, "status": "Pending"}, fields=["*"])
    if not charges:
        return dict(invoices=list(set(frappe.get_all("HS Charge", filters={"folio": folio.name, "status": "Invoiced"}, pluck="sales_invoice"))))
    stay = frappe.get_doc("HS Stay", folio.stay)
    inv = frappe.new_doc("Sales Invoice")
    inv.update(dict(company=prop.company, customer=folio.customer, posting_date=nowdate(), due_date=nowdate(),
                    currency=folio.currency, debit_to=prop.receivable_account, cost_center=prop.cost_center,
                    hs_stay=stay.name, update_stock=0, taxes_and_charges=prop.tax_template))
    mapping = []
    for charge in charges:
        row = inv.append("items", dict(item_code=charge.item, qty=charge.quantity, rate=charge.rate,
                                       description=charge.description, cost_center=prop.cost_center))
        mapping.append((charge.name, row))
    inv.set_missing_values()
    if prop.tax_template:
        from erpnext.controllers.accounts_controller import get_taxes_and_charges
        inv.set("taxes", get_taxes_and_charges("Sales Taxes and Charges Template", prop.tax_template))
    inv.calculate_taxes_and_totals()
    remaining = decimal(inv.grand_total)
    advances = frappe.get_all("HS Payment", filters={"property": prop.name, "customer": folio.customer, "kind": "Advance", "status": "Posted"}, fields=["*"])
    for payment in advances:
        if payment.stay != stay.name and (not stay.booking or payment.booking != stay.booking):
            continue
        pe = frappe.get_doc("Payment Entry", payment.payment_entry)
        if pe.docstatus != 1 or pe.company != prop.company or pe.party != folio.customer or pe.paid_from != prop.receivable_account:
            continue
        amount = min(remaining, decimal(pe.unallocated_amount))
        if amount > 0:
            inv.append("advances", dict(reference_type="Payment Entry", reference_name=pe.name,
                                       advance_amount=pe.unallocated_amount, allocated_amount=float(amount), ref_exchange_rate=pe.source_exchange_rate))
            remaining -= amount
    post_standard(inv, prop)
    for name, row in mapping:
        doc = frappe.get_doc("HS Charge", name)
        doc.status, doc.sales_invoice, doc.invoice_item = "Invoiced", inv.name, row.name
        doc.save()
    audit(prop, "Invoice", folio, details={"sales_invoice": inv.name, "charges": [r.name for r in charges]})
    return dict(invoice=inv.name, total=inv.grand_total, outstanding=inv.outstanding_amount, currency=inv.currency)


def exchange(from_currency, to_currency, posting_date=None):
    if from_currency == to_currency:
        return Decimal(1)
    from erpnext.setup.utils import get_exchange_rate
    rate = decimal(get_exchange_rate(from_currency, to_currency, posting_date or nowdate(), for_selling=True))
    if rate <= 0:
        frappe.throw("Configure un tipo de cambio válido en ERPNext")
    return rate


def payment(prop, data):
    ready(prop)
    shift = document("HS Shift", data["shift"], "finance")
    if shift.status != "Open":
        frappe.throw("El turno no está abierto")
    if shift.cashier != frappe.session.user:
        require(prop.name, "approve")
    method = document("HS Payment Method", data["method"], "finance")
    if method.reference_required and not data.get("reference"):
        frappe.throw("La referencia bancaria es obligatoria")
    amount = money(data["amount"])
    if amount <= 0:
        frappe.throw("El importe debe ser positivo")
    kind = data.get("kind", "Payment")
    if kind not in ("Payment", "Advance", "Guarantee", "Refund", "Guarantee Refund"):
        frappe.throw("Tipo de movimiento inválido")
    source = None
    if kind in ("Refund", "Guarantee Refund"):
        require(prop.name, "approve")
        if not data.get("reason") or not data.get("source_payment"):
            frappe.throw("Indique el pago original y el motivo de devolución")
        source = document("HS Payment", data["source_payment"], "finance")
        expected = "Guarantee" if kind == "Guarantee Refund" else ("Advance", "Payment")
        if (source.kind != expected if isinstance(expected, str) else source.kind not in expected) or source.status != "Posted":
            frappe.throw("Origen de devolución inválido")
        if source.currency != method.currency:
            frappe.throw("Devuelva en la moneda del movimiento original")
        refunded = sum(decimal(p.amount) for p in frappe.get_all("HS Payment", filters={"source_payment": source.name, "status": "Posted"}, fields=["amount"]))
        if refunded + amount > decimal(source.amount):
            frappe.throw("La devolución supera el importe disponible")
        data = {**data, "stay": source.stay, "booking": source.booking, "customer": source.customer, "folio": source.folio}
    stay = document("HS Stay", data["stay"], "finance") if data.get("stay") else None
    booking = document("HS Booking", data["booking"], "finance") if data.get("booking") else None
    folio = document("HS Folio", data["folio"], "finance") if data.get("folio") else None
    if not stay and not booking:
        frappe.throw("El pago debe tener una estancia o reserva de origen")
    if folio and (not stay or folio.stay != stay.name):
        frappe.throw("La cuenta no corresponde a la estancia")
    customer = folio.customer if folio else (source.customer if source else (stay.customer if stay else booking.customer))
    company_currency = frappe.db.get_value("Company", prop.company, "default_currency")
    fx = exchange(method.currency, company_currency)
    property_fx = exchange(prop.currency, company_currency)
    party_amount = money(amount * fx / property_fx)
    is_refund = kind in ("Refund", "Guarantee Refund")
    if kind in ("Guarantee", "Guarantee Refund"):
        journal = frappe.new_doc("Journal Entry")
        journal.update(dict(company=prop.company, posting_date=nowdate(), voucher_type="Journal Entry", multi_currency=1,
                            hs_stay=stay.name if stay else None, hs_shift=shift.name, user_remark=data.get("reason") or "Garantía reembolsable"))
        for account, value, is_debit, currency, rate in [
            (method.account, amount, not is_refund, method.currency, fx),
            (prop.guarantee_account, party_amount, is_refund, prop.currency, property_fx),
        ]:
            journal.append("accounts", dict(account=account, account_currency=currency, exchange_rate=float(rate), cost_center=prop.cost_center,
                                            debit_in_account_currency=float(value) if is_debit else 0,
                                            credit_in_account_currency=0 if is_debit else float(value)))
        post_standard(journal, prop)
        pe = None
    else:
        invoice = None
        if kind == "Payment":
            if not folio:
                frappe.throw("Seleccione la cuenta de estancia a cobrar")
            invoice_folio(prop, {"folio": folio.name})
            names = set(frappe.get_all("HS Charge", filters={"folio": folio.name, "status": "Invoiced"}, pluck="sales_invoice"))
            invoices = [frappe.get_doc("Sales Invoice", n) for n in names if n]
            if party_amount > sum(decimal(inv.outstanding_amount) for inv in invoices):
                frappe.throw("El cobro supera el saldo; registre un anticipo separado si corresponde")
        elif source and source.kind == "Advance":
            unallocated = decimal(frappe.db.get_value("Payment Entry", source.payment_entry, "unallocated_amount"))
            if party_amount > unallocated:
                frappe.throw("El anticipo ya está aplicado; use nota de crédito y devolución contra factura")
        elif source and source.kind == "Payment":
            frappe.throw("Genere primero una nota de crédito para devolver pagos de facturas")
        pe = frappe.new_doc("Payment Entry")
        pe.update(dict(company=prop.company, payment_type="Pay" if is_refund else "Receive", posting_date=nowdate(),
                       party_type="Customer", party=customer, mode_of_payment=method.mode_of_payment,
                       paid_from=method.account if is_refund else prop.receivable_account,
                       paid_to=prop.receivable_account if is_refund else method.account,
                       paid_amount=float(amount if is_refund else party_amount), received_amount=float(party_amount if is_refund else amount),
                       source_exchange_rate=float(fx if is_refund else property_fx), target_exchange_rate=float(property_fx if is_refund else fx),
                       reference_no=data.get("reference") or f"HS-{shift.name}", reference_date=nowdate(), cost_center=prop.cost_center,
                       hs_stay=stay.name if stay else None, hs_shift=shift.name))
        if kind == "Payment":
            remaining = party_amount
            for invoice in invoices:
                allocation = min(remaining, decimal(invoice.outstanding_amount))
                if allocation > 0:
                    pe.append("references", dict(reference_doctype="Sales Invoice", reference_name=invoice.name, allocated_amount=float(allocation)))
                    remaining -= allocation
        post_standard(pe, prop)
        journal = None
    record = insert("HS Payment", prop, stay=stay.name if stay else None, booking=booking.name if booking else (stay.booking if stay else None),
                    folio=folio.name if folio else None, customer=customer, shift=shift.name, method=method.name, amount=amount,
                    currency=method.currency, exchange_rate=fx, base_amount=money(amount * fx), kind=kind, status="Posted",
                    payment_entry=pe.name if pe else None, journal_entry=journal.name if journal else None,
                    source_payment=source.name if source else None, reference=data.get("reference"), reason=data.get("reason"))
    audit(prop, kind, record, data.get("reason"))
    return dict(payment=record.name, payment_entry=record.payment_entry, journal_entry=record.journal_entry, amount=str(amount), currency=method.currency)


def sync_document(doc, method=None):
    """Includes external Desk postings/cancellations, without trusting a client link."""
    if not doc.get("hs_stay"):
        return
    stay = frappe.get_doc("HS Stay", doc.hs_stay)
    prop = require(stay.property)
    if doc.company != prop.company or doc.get("customer", doc.get("party")) != stay.customer:
        # Split folios may have an explicitly assigned company/agency payer.
        customers = frappe.get_all("HS Folio", filters={"stay": stay.name}, pluck="customer")
        if doc.company != prop.company or doc.get("customer", doc.get("party")) not in customers:
            frappe.throw("Compañía o pagador incompatible con la estancia")
    from hospitality_suite.service import lock_property
    lock_property(prop.name)
    with operation():
        if doc.doctype == "Sales Invoice" and doc.docstatus == 2:
            for name in frappe.get_all("HS Charge", filters={"sales_invoice": doc.name}, pluck="name"):
                charge = frappe.get_doc("HS Charge", name)
                charge.status, charge.sales_invoice, charge.invoice_item = "Pending", None, None
                charge.save(ignore_permissions=True)
        if doc.doctype == "Payment Entry" and doc.docstatus == 2:
            for name in frappe.get_all("HS Payment", filters={"payment_entry": doc.name}, pluck="name"):
                payment_doc = frappe.get_doc("HS Payment", name)
                payment_doc.status = "Cancelled"
                payment_doc.save(ignore_permissions=True)
        audit(prop, method or "ERP update", stay, details={"doctype": doc.doctype, "name": doc.name, "docstatus": doc.docstatus})
    from hospitality_suite.security import realtime
    realtime(prop.name)
