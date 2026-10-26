"""Native partial-payment fixture on the isolated ERPNext reverse-cutover clone."""

from decimal import Decimal
from pathlib import Path

import frappe

from hospitality_suite import (erp_fiscal_history, erp_to_pms_freeze,
                               erp_to_pms_preflight, pms_cutover_cli)
from hospitality_suite.pms_cutover_writer import _migration_posting


SITE = "hs-erp-smoke-reverse-partial.local"
DATABASE = "hs_erp_reverse_partial"
COMPANY = "HS Reverse Source 2026"
INVOICE_MARKER = "HS reverse real source lodging 2026"
REFERENCE = "HS-REVERSE-PARTIAL-20261026"
SOURCE_SHA256 = "1c72c8dc676ebe06ece4f42d34ce2cd1e560c4642826c935a983039d6a706264"
BACKUP_FILE = "reverse-partial-source-backup-20261026.json"
PREVIEW_BUNDLE = "hs-erp-fiscal-974827c3aad94e1ca7aca9ac4de433b1.zip"
PREVIEW_MANIFEST_SHA256 = "db9d30147c0adc22296ba9e097cb836bfbc6f31aaa74f978d3088890538d2cc3"


def _source():
    if (frappe.local.site != SITE or frappe.conf.db_name != DATABASE or
            "erpnext" not in frappe.get_installed_apps()):
        frappe.throw("Use únicamente el clon ERPNext de pago parcial")
    frappe.set_user("Administrator")
    invoice_name = frappe.db.get_value("Sales Invoice", {
        "company": COMPANY, "remarks": INVOICE_MARKER, "docstatus": 1}, "name")
    if not invoice_name or frappe.db.count("HS Property") != 1:
        frappe.throw("Falta la factura nativa en la fuente aislada")
    return frappe.get_doc("Sales Invoice", invoice_name)


def seed_payment():
    invoice = _source()
    existing = frappe.db.get_value("Payment Entry", {
        "company": COMPANY, "reference_no": REFERENCE, "docstatus": 1}, "name")
    if not existing:
        if Decimal(str(invoice.outstanding_amount)) != Decimal("100"):
            frappe.throw("El saldo inicial de la factura ya cambió")
        bank = frappe.db.get_value("Account", {
            "company": COMPANY, "account_type": "Bank", "is_group": 0,
            "account_currency": "NIO"}, "name")
        if not bank:
            parent = frappe.db.get_value("Account", {
                "company": COMPANY, "account_name": "Bank Accounts",
                "is_group": 1}, "name") or frappe.db.get_value("Account", {
                "company": COMPANY, "account_name": "Current Assets",
                "is_group": 1}, "name")
            if not parent:
                frappe.throw("La compañía no tiene grupo de activos bancarios")
            bank = frappe.get_doc({"doctype": "Account",
                "account_name": "HS Reverse Partial Bank",
                "parent_account": parent, "company": COMPANY,
                "account_type": "Bank", "account_currency": "NIO",
                "is_group": 0}).insert(ignore_permissions=True).name
        with _migration_posting():
            payment = frappe.get_doc({"doctype": "Payment Entry",
                "company": COMPANY, "hs_property": invoice.hs_property,
                "posting_date": frappe.utils.today(),
                "payment_type": "Receive", "party_type": "Customer",
                "party": invoice.customer, "paid_from": invoice.debit_to,
                "paid_to": bank, "paid_amount": 40, "received_amount": 40,
                "reference_no": REFERENCE,
                "reference_date": frappe.utils.today(),
                "references": [{"reference_doctype": "Sales Invoice",
                    "reference_name": invoice.name,
                    "allocated_amount": 40}]})
            payment.set_missing_values()
            payment.insert(ignore_permissions=True)
            payment.submit()
        existing = payment.name
    invoice.reload()
    if Decimal(str(invoice.outstanding_amount)) != Decimal("60"):
        frappe.throw("El pago nativo no dejó C$60 pendientes")
    source = erp_to_pms_preflight.preflight()
    if source["blockers"]:
        frappe.throw("El preflight bloqueó el pago parcial: " +
            frappe.as_json(source["blockers"]))
    hotel = source["properties"][0]
    receivables = [row for row in hotel["open_receivables"]
                   if row.get("name") == invoice.name]
    if len(receivables) != 1:
        frappe.throw("La factura no aparece una sola vez en cartera abierta")
    frappe.db.commit()
    return {"site": SITE, "invoice": invoice.name, "payment": existing,
        "invoice_outstanding": str(invoice.outstanding_amount),
        "open_receivable": receivables[0],
        "payment_gl_entries": frappe.db.count("GL Entry", {
            "voucher_type": "Payment Entry", "voucher_no": existing,
            "is_cancelled": 0}),
        "source_sha256": source["source_sha256"],
        "blockers": source["blockers"]}


def export_bundle():
    invoice = _source()
    source = erp_to_pms_preflight.preflight()
    if source["blockers"] or Decimal(str(invoice.outstanding_amount)) != 60:
        frappe.throw("La fuente con pago parcial no está lista")
    result = erp_fiscal_history.export_bundle(source["source_sha256"])
    return {"source_sha256": source["source_sha256"], **result}


def prepare_backup_and_freeze():
    invoice = _source()
    source = erp_to_pms_preflight.preflight()
    if (source["source_sha256"] != SOURCE_SHA256 or source["blockers"] or
            Decimal(str(invoice.outstanding_amount)) != 60):
        frappe.throw("La fuente congelada no coincide con el caso revisado")
    backup = pms_cutover_cli.prepare_backup_file(BACKUP_FILE)
    frozen = erp_to_pms_freeze.export_frozen_file(BACKUP_FILE,
        SOURCE_SHA256)
    return {"backup": backup, "freeze": frozen}


def seal_reviewed_bundle():
    invoice = _source()
    source = erp_to_pms_preflight.preflight()
    if (source["source_sha256"] != SOURCE_SHA256 or source["blockers"] or
            Decimal(str(invoice.outstanding_amount)) != 60):
        frappe.throw("La fuente cambió desde la revisión del ZIP")
    return erp_to_pms_freeze.export_frozen_file(BACKUP_FILE, SOURCE_SHA256,
        PREVIEW_BUNDLE, PREVIEW_MANIFEST_SHA256)


def verify_invalid_preview():
    _source()
    root = Path(frappe.get_site_path("private", "files")).resolve()
    before = set(root.glob("hs-erp-freeze-*.json"))
    try:
        erp_to_pms_freeze.export_frozen_file(BACKUP_FILE, SOURCE_SHA256,
            PREVIEW_BUNDLE, "0" * 64)
    except frappe.ValidationError:
        frappe.clear_messages()
    else:
        frappe.throw("La congelación aceptó un manifiesto equivocado")
    if (set(root.glob("hs-erp-freeze-*.json")) != before or
            not (root / PREVIEW_BUNDLE).is_file()):
        frappe.throw("La congelación fallida alteró el ZIP revisado")
    return {"invalid_manifest_rejected": True,
        "preview_preserved": True, "receipt_count": len(before)}
