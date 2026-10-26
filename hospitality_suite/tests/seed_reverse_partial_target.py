"""Inspect a native ERPNext partial payment against an isolated PMS opening."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import frappe

from hospitality_suite import (api, erp_fiscal_history,
                               erp_to_pms_activation, erp_to_pms_cli,
                               pms_cutover_backup)
from hospitality_suite.pms_cutover_cli import _json_file
from hospitality_suite.service import canonical, insert, operation


SITE = "hs-pms-smoke-reverse-partial.local"
DATABASE = "hs_pms_reverse_partial"
SOURCE_SITE = "hs-erp-smoke-reverse-partial.local"
PROPERTY = "Hotel PMS destino inverso parcial"
BUNDLE = "hs-erp-fiscal-974827c3aad94e1ca7aca9ac4de433b1.zip"
SOURCE_SHA256 = "1c72c8dc676ebe06ece4f42d34ce2cd1e560c4642826c935a983039d6a706264"
MANIFEST_SHA256 = "db9d30147c0adc22296ba9e097cb836bfbc6f31aaa74f978d3088890538d2cc3"
SOURCE_INVOICE = "ACC-SINV-2026-00001"
RECEIPT = "hs-erp-freeze-bfd4639e633b4b6d991db61422b0cf39.json"
RECEIPT_SHA256 = "dac1a63267f768d8dea48a2f3eab7756fd0ac4746d7ccea922352a88b12d8f2b"
SOURCE_BACKUP_SHA256 = "6ed7af740f683a46cfd12c1fba973e707cc7c164e84c0eb9584bcd0fc97241ab"
MAPPING_FILE = "reverse-partial-target-mapping-20261026.json"
TARGET_BACKUP_FILE = "reverse-partial-target-backup-20261026.json"
MIGRATION_REFERENCE = "reverse-partial-native-invoice-20261026"
MAPPING_SHA256 = "28b86b289277568cc032ab3d3eba319e73de8c88e84e67758e1ed4d70e4d68ae"
PLAN_SHA256 = "73e2bdc3ddab8a280e9f40fab844fc1472cdc46b2a9bb07d1e3352c66b4cc124"


def _fixture():
    if (frappe.local.site != SITE or frappe.conf.db_name != DATABASE or
            "erpnext" in frappe.get_installed_apps()):
        frappe.throw("Use únicamente el clon PMS de pago parcial")
    from hospitality_suite.tests import seed_reverse_real_target as fixture
    fixture.SITE = SITE
    fixture.PROPERTY = PROPERTY
    fixture.BUNDLE = BUNDLE
    fixture.SOURCE_SHA256 = SOURCE_SHA256
    fixture.MANIFEST_SHA256 = MANIFEST_SHA256
    return fixture


def seed():
    fixture = _fixture()
    result = fixture.seed()
    prop = frappe.get_doc("HS Property", result["property"])
    from hospitality_suite.service import operation
    with operation(prop):
        bank = fixture._one("HS Account", prop, {"account_code": "1110"},
            organization=prop.organization, account_code="1110",
            account_name="Banco migrado", root_type="Asset",
            account_type="Bank", account_currency="NIO",
            active=1, is_group=0)
    frappe.db.commit()
    return {**result, "bank": bank.name}


def review_and_rehearse():
    fixture = _fixture()
    target = frappe.db.get_value("HS Property", {"property_name": PROPERTY}, "name")
    if not target or not frappe.db.exists("HS Account", {
            "property": target, "account_code": "1110"}):
        frappe.throw("Prepare primero el banco PMS aislado")
    prepared = fixture.import_and_review()
    plan = prepared["plan"]
    if (not prepared["review"]["mapping_ready"] or
            not plan["ready_for_transfer"] or len(plan["properties"]) != 1):
        frappe.throw("El plan de pago parcial no está listo")
    rows = plan["properties"][0]["opening_receivables"]
    if (len(rows) != 1 or rows[0]["source"] != SOURCE_INVOICE or
            Decimal(rows[0]["signed_base_balance"]) != 60 or
            Decimal(rows[0]["signed_account_balance"]) != 60):
        frappe.throw("La apertura no conserva únicamente C$60 pendientes")
    bank = frappe.db.get_value("HS Account", {"property": target,
        "account_code": "1110"}, "name")
    bank_balance = sum((Decimal(line["debit"]) - Decimal(line["credit"])
        for line in plan["properties"][0]["residual_journal"]
        if line["account"] == bank), Decimal(0))
    if bank_balance != 40:
        frappe.throw("El pago previo de C$40 no aparece en el banco de apertura")
    rehearsal = fixture.rehearse()
    if (not rehearsal["reconciled"] or not rehearsal["rolled_back"] or
            frappe.db.exists("HS PMS Receivable", {"property": target}) or
            frappe.db.exists("HS Journal", {"property": target})):
        frappe.throw("El ensayo no reconcilió o no revirtió los registros")
    return {"source_sha256": SOURCE_SHA256, "manifest_sha256": MANIFEST_SHA256,
        "source_invoice": SOURCE_INVOICE,
        "opening_receivable": rows[0],
        "opening_bank_balance": str(bank_balance),
        "plan_sha256": plan["plan_sha256"],
        "rehearsal_reconciled": rehearsal["reconciled"],
        "rehearsal_rolled_back": rehearsal["rolled_back"],
        "property": target}


def review_frozen():
    fixture = _fixture()
    prepared = fixture.import_and_review()
    if (not prepared["review"]["mapping_ready"] or
            not prepared["plan"]["ready_for_transfer"]):
        frappe.throw("El mapa de la factura parcial dejó de estar listo")
    root = Path(frappe.get_site_path("private", "files")).resolve()
    path = root / MAPPING_FILE
    encoded = canonical(prepared["mapping"]) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text(encoding="utf-8") != encoded:
            frappe.throw("El mapa guardado cambió")
    else:
        path.write_text(encoded, encoding="utf-8")
    result = erp_to_pms_cli.review_file(MAPPING_FILE, RECEIPT, BUNDLE,
        source_sha256=SOURCE_SHA256,
        manifest_sha256=MANIFEST_SHA256,
        receipt_sha256=RECEIPT_SHA256,
        source_backup_sha256=SOURCE_BACKUP_SHA256)
    if (not result["ready"] or result["blockers"] or
            result["plan_sha256"] != prepared["plan"]["plan_sha256"]):
        frappe.throw("El paquete congelado no conserva el plan revisado")
    return {"mapping_file": MAPPING_FILE, **result}


def rehearse_frozen():
    _fixture()
    reviewed = review_frozen()
    result = erp_to_pms_activation.rehearse_activation(BUNDLE, RECEIPT,
        _json_file(MAPPING_FILE), source_sha256=SOURCE_SHA256,
        manifest_sha256=MANIFEST_SHA256,
        receipt_sha256=RECEIPT_SHA256,
        source_backup_sha256=SOURCE_BACKUP_SHA256,
        mapping_sha256=reviewed["mapping_sha256"],
        plan_sha256=reviewed["plan_sha256"],
        migration_reference=MIGRATION_REFERENCE + "-rehearsal")
    target = frappe.db.get_value("HS Property", {"property_name": PROPERTY}, "name")
    if (not result["reconciled"] or not result["rolled_back"] or
            frappe.db.exists("HS ERP to PMS Cutover Run", {
                "migration_reference": MIGRATION_REFERENCE + "-rehearsal"}) or
            frappe.db.exists("HS PMS Receivable", {"property": target}) or
            frappe.db.exists("HS Journal", {"property": target})):
        frappe.throw("El ensayo congelado no revirtió el corte")
    return {"reconciled": result["reconciled"],
        "rolled_back": result["rolled_back"],
        "source_sha256": SOURCE_SHA256,
        "plan_sha256": reviewed["plan_sha256"]}


def prepare_target_backup():
    _fixture()
    frappe.set_user("Administrator")
    return erp_to_pms_cli.prepare_backup_file(TARGET_BACKUP_FILE)


def activate():
    _fixture()
    frappe.set_user("Administrator")
    manifest = _json_file(TARGET_BACKUP_FILE)
    backup_sha256 = pms_cutover_backup.verify(manifest)["sha256"]
    result = erp_to_pms_cli.activate_file(MAPPING_FILE, RECEIPT, BUNDLE,
        TARGET_BACKUP_FILE, source_sha256=SOURCE_SHA256,
        manifest_sha256=MANIFEST_SHA256,
        receipt_sha256=RECEIPT_SHA256,
        source_backup_sha256=SOURCE_BACKUP_SHA256,
        mapping_sha256=MAPPING_SHA256, plan_sha256=PLAN_SHA256,
        target_backup_sha256=backup_sha256,
        migration_reference=MIGRATION_REFERENCE)
    return {"activation": result, "target_backup_sha256": backup_sha256}


def verify_activation():
    _fixture()
    frappe.set_user("Administrator")
    property_name = frappe.db.get_value("HS Property",
        {"property_name": PROPERTY}, "name")
    if (not property_name or
            frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
            frappe.db.get_single_value("HS Site Mode", "migration_reference") !=
                MIGRATION_REFERENCE):
        frappe.throw("El corte parcial no conserva el proveedor y referencia")
    runs = frappe.get_all("HS ERP to PMS Cutover Run", fields=["name",
        "migration_reference", "source_site", "source_sha256"])
    receivables = frappe.get_all("HS PMS Receivable",
        filters={"property": property_name}, fields=["name", "amount",
            "base_amount", "currency", "status", "journal",
            "opening_source_name", "opening_source_site",
            "opening_source_sha256"])
    journals = frappe.get_all("HS Journal", filters={"property": property_name},
        fields=["name", "total_debit", "total_credit", "status"])
    documents = frappe.get_all("HS Historical Fiscal Document",
        filters={"property": property_name}, fields=["name", "source_name",
            "source_site", "pdf_sha256"])
    if (len(runs) != 1 or runs[0].migration_reference != MIGRATION_REFERENCE or
            runs[0].source_site != SOURCE_SITE or
            runs[0].source_sha256 != SOURCE_SHA256 or
            len(receivables) != 1 or
            receivables[0].opening_source_name != SOURCE_INVOICE or
            receivables[0].opening_source_site != runs[0].source_site or
            receivables[0].opening_source_sha256 != SOURCE_SHA256 or
            Decimal(str(receivables[0].amount)) != 60 or
            Decimal(str(receivables[0].base_amount)) != 60 or
            receivables[0].currency != "NIO" or
            receivables[0].status != "Posted" or
            len(journals) != 2 or any(row.status != "Posted" or
                Decimal(str(row.total_debit)) != Decimal(str(row.total_credit))
                for row in journals) or
            len(documents) != 1 or
            documents[0].source_name != SOURCE_INVOICE or
            documents[0].source_site != runs[0].source_site or
            frappe.db.count("HS Payment", {"property": property_name}) != 0):
        frappe.throw("El corte parcial no conserva su cartera, banco o archivo")
    bank = frappe.db.get_value("HS Account", {"property": property_name,
        "account_code": "1110"}, "name")
    ar = frappe.db.get_value("HS Account", {"property": property_name,
        "account_code": "1210"}, "name")
    temporary = frappe.db.get_value("HS Account", {"property": property_name,
        "account_code": "1990"}, "name")
    balances = frappe.db.sql(
        "SELECT l.account,SUM(l.debit-l.credit) AS balance "
        "FROM `tabHS Journal Line` l JOIN `tabHS Journal` j ON j.name=l.parent "
        "WHERE j.property=%s AND j.status='Posted' "
        "GROUP BY l.account", property_name, as_dict=True)
    by_account = {row.account: Decimal(str(row.balance)) for row in balances}
    if (by_account.get(bank) != 40 or by_account.get(ar) != 60 or
            by_account.get(temporary, Decimal(0)) != 0):
        frappe.throw("El mayor PMS no conserva C$40 de banco y C$60 de cartera")
    board = api.pms_receivables(property_name)
    visible = [row for row in board["receivables"]
               if row["name"] == receivables[0].name]
    if len(visible) != 1 or Decimal(str(visible[0]["outstanding"])) != 60:
        frappe.throw("La cartera parcial no aparece en la API PMS")
    fiscal = frappe.get_doc("HS Historical Fiscal Document", documents[0].name)
    pdf = erp_fiscal_history._verified_content(fiscal)
    if not pdf.startswith(b"%PDF"):
        frappe.throw("El documento fiscal migrado no es imprimible")
    return {"cutover_run": runs[0].name, "receivable": receivables[0].name,
        "outstanding": "60", "opening_bank_balance": "40",
        "journals": [row.name for row in journals],
        "fiscal_document": fiscal.name, "pdf_sha256": fiscal.pdf_sha256,
        "pdf_bytes": len(pdf), "provider": "PMS"}


def verify_payment_continuity():
    """Collect only the C$60 still due after the ERPNext payment; undo the trial."""
    baseline = verify_activation()
    prop = frappe.get_doc("HS Property", frappe.db.get_value("HS Property",
        {"property_name": PROPERTY}, "name"))
    from hospitality_suite.standalone_receivables import outstanding

    receivable = baseline["receivable"]
    if outstanding(prop, receivable) != 60:
        frappe.throw("La cartera parcial ya no conserva C$60 pendientes")
    counts = {doctype: frappe.db.count(doctype, {"property": prop.name})
        for doctype in ("HS Account", "HS Payment Method", "HS Payment",
                        "HS PMS Allocation", "HS Journal")}
    suffix = uuid4().hex
    frappe.db.savepoint("hs_reverse_partial_payment_continuity")
    try:
        with operation(prop):
            bank = insert("HS Account", prop, organization=prop.organization,
                account_code="1111-" + suffix[:8],
                account_name="Banco para saldo parcial migrado",
                root_type="Asset", account_type="Bank",
                account_currency="NIO", is_bank=1, active=1, is_group=0)
        method = api.execute(prop.name, "pms_payment_method",
            "reverse-partial-bank-method-" + suffix,
            {"label": "Banco de saldo parcial", "account": bank.name})["method"]
        data = {"kind": "Payment", "amount": "60.00", "method": method,
            "receivable": receivable,
            "reference": "REVERSE-PARTIAL-PAY-" + suffix[:8],
            "reason": "Ensayo reversible del saldo tras cobro ERPNext"}
        quote = api.pms_cash_preview(prop.name, data)
        if (quote["debit"] != bank.name or
                quote["credit"] != frappe.db.get_value("HS PMS Receivable",
                    receivable, "receivable_account")):
            frappe.throw("El cobro PMS no usa las cuentas previstas")
        payload = {**data, "expected_debit": quote["debit"],
            "expected_credit": quote["credit"],
            "expected_exchange_rate": quote["exchange_rate"],
            "expected_rate_record": quote["exchange_rate_record"]}
        key = "reverse-partial-payment-" + suffix
        posted = api.execute(prop.name, "pms_cash_movement", key, payload)
        if (api.execute(prop.name, "pms_cash_movement", key, payload) != posted or
                outstanding(prop, receivable) != 0 or
                frappe.db.count("HS PMS Allocation", {
                    "property": prop.name, "receivable": receivable}) != 1):
            frappe.throw("El cobro de C$60 no fue único ni liquidó la cartera")
        try:
            api.pms_cash_preview(prop.name, {**data, "amount": "1.00",
                "reference": "REVERSE-PARTIAL-EXCESS-" + suffix[:8]})
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("El PMS permitió cobrar sobre el saldo migrado")
    finally:
        frappe.db.rollback(save_point="hs_reverse_partial_payment_continuity")
    if (outstanding(prop, receivable) != 60 or
            any(frappe.db.count(doctype, {"property": prop.name}) != total
                for doctype, total in counts.items()) or
            verify_activation()["cutover_run"] != baseline["cutover_run"]):
        frappe.throw("El ensayo de cobro parcial dejó movimientos")
    return {"original_erp_payment": "40.00", "pms_payment": "60.00",
        "settled_in_trial": True, "idempotent": True,
        "excess_rejected": True, "rolled_back": True,
        "cutover_run": baseline["cutover_run"]}


def verify_daily_close_continuity():
    """Keep the remaining C$60 as opening debt, never as new production."""
    baseline = verify_activation()
    prop = frappe.get_doc("HS Property", frappe.db.get_value("HS Property",
        {"property_name": PROPERTY}, "name"))
    day = str(prop.business_date)
    existing = frappe.db.count("HS Daily Close", {"property": prop.name})
    review = api.pms_close_preview(prop.name)
    snapshot = review["snapshot"]
    opening = snapshot["breakdown"]["opening_receivables"]
    if (review["blockers"] or len(opening) != 1 or
            Decimal(opening[0]["amount"]) != 60 or
            snapshot["breakdown"]["production"] or
            snapshot["breakdown"]["fiscal_documents"] or
            Decimal(snapshot["ledger"]["day_debit"]) !=
                Decimal(snapshot["ledger"]["day_credit"])):
        frappe.throw("El cierre confundió el saldo inicial con producción")
    frappe.db.savepoint("hs_reverse_partial_close_continuity")
    try:
        posted = api.execute(prop.name, "pms_daily_close",
            "reverse-partial-close-" + uuid4().hex,
            {"review_acceptance": review["review_acceptance"],
             "reason": "Ensayo reversible del cierre de factura parcial"})
        detail = api.pms_close_detail(prop.name, posted["close"])
        if (detail["snapshot"] != snapshot or
                str(detail["business_date"]) != day or
                str(frappe.db.get_value("HS Property", prop.name,
                    "business_date")) == day):
            frappe.throw("El cierre no congeló el snapshot revisado")
    finally:
        frappe.db.rollback(save_point="hs_reverse_partial_close_continuity")
    if (frappe.db.count("HS Daily Close", {"property": prop.name}) != existing or
            str(frappe.db.get_value("HS Property", prop.name,
                "business_date")) != day or
            verify_activation()["cutover_run"] != baseline["cutover_run"]):
        frappe.throw("El ensayo de cierre parcial dejó cambios")
    return {"opening_receivable": "60", "prior_bank_balance": "40",
        "new_production": "0", "snapshot_immutable": True,
        "rolled_back": True, "cutover_run": baseline["cutover_run"]}
