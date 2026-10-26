"""Prepare one isolated PMS target for the native ERPNext reverse-cutover trial."""

from pathlib import Path
from decimal import Decimal
from uuid import uuid4

import frappe

from hospitality_suite import (api, erp_fiscal_history, erp_to_pms_activation,
                               erp_to_pms_cli, pms_cutover_backup, setup)
from hospitality_suite.pms_cutover_cli import _json_file
from hospitality_suite.service import canonical, insert, operation


SITE = "hs-pms-smoke-real-reverse.local"
PROPERTY = "Hotel PMS destino inverso"
BUNDLE = "hs-erp-fiscal-f339ae275b034eaab6debb8688d820f1.zip"
SOURCE_SHA256 = "353af63207a65463d548db641489fd29e50f5ae357f3fc805f23a023e6e25f97"
MANIFEST_SHA256 = "9afe9d1e92d4dab827a6fa09f23304823299f28e4c93582471e98578bc856c6a"
FROZEN_BUNDLE = "hs-erp-fiscal-ae1dbfc012314dccb9d444e30393ec23.zip"
RECEIPT = "hs-erp-freeze-a25ee39f0d26475b82daca3d44c0fc43.json"
RECEIPT_SHA256 = "567a99ce4e10b02199e857bcbfdf2f816663069948dc416b8f0c07525f2943d2"
SOURCE_BACKUP_SHA256 = "43e020f744cb2b733185b0f688a27d9d6a126181f61fcf41f168e24ef615f430"
MAPPING_FILE = "reverse-real-target-mapping-20261026.json"
MAPPING_SHA256 = "7f91fe9eb43a5f2e4a61861144d074c19e4409c1081b170afd86168abcf2684b"
PLAN_SHA256 = "d7d87e168b4328abaeacf50240ea275134d45effbc7b41026ed0e0a21da1d1eb"
TARGET_BACKUP_FILE = "reverse-real-target-backup-20261026.json"
MIGRATION_REFERENCE = "reverse-real-native-invoice-20261026"


def _guard():
    if frappe.local.site != SITE or "erpnext" in frappe.get_installed_apps():
        frappe.throw("Use únicamente el clon PMS aislado para el corte inverso")
    frappe.set_user("Administrator")


def _one(doctype, prop, lookup, **values):
    name = frappe.db.get_value(doctype, {"property": prop.name, **lookup}, "name")
    return frappe.get_doc(doctype, name) if name else insert(doctype, prop, **values)


def seed():
    _guard()
    existing = frappe.db.get_value("HS Property", {"property_name": PROPERTY}, "name")
    if existing:
        prop = frappe.get_doc("HS Property", existing)
    else:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "HS Reverse Target 2026", "base_currency": "NIO",
            "tax_regime": "General", "active": 1}).insert()
        created = setup.create_property({"property_name": PROPERTY,
            "organization": org.name, "currency": "NIO", "mode": "Hotel",
            "time_zone": "America/Managua", "close_time": "06:00",
            "business_date": "2026-10-25"}, "reverse-real-target-property")
        prop = frappe.get_doc("HS Property", created["property"])
    if frappe.db.count("HS Property") != 1 or prop.currency != "NIO":
        frappe.throw("El clon PMS no está aislado a un hotel NIO")
    with operation(prop):
        receivable = _one("HS Account", prop, {"account_code": "1210"},
            organization=prop.organization, account_code="1210",
            account_name="Clientes migrados", root_type="Asset",
            account_type="Receivable", account_currency="NIO",
            active=1, is_group=0)
        income = _one("HS Account", prop, {"account_code": "4110"},
            organization=prop.organization, account_code="4110",
            account_name="Ingresos migrados", root_type="Income",
            account_type="General", account_currency="NIO",
            active=1, is_group=0)
        temporary = _one("HS Account", prop, {"account_code": "1990"},
            organization=prop.organization, account_code="1990",
            account_name="Puente de apertura", root_type="Asset",
            account_type="Temporary", account_currency="NIO",
            active=1, is_group=0)
        party = _one("HS Party", prop, {"party_name": "Cliente ERP migrado"},
            organization=prop.organization, party_name="Cliente ERP migrado",
            party_type="Customer", active=1)
        tax = _one("HS PMS Tax Profile", prop, {"label": "Servicio exento migrado"},
            organization=prop.organization, label="Servicio exento migrado",
            treatment="Exempt", rate=0, active=1)
        product = _one("HS Product", prop, {"product_code": "HS-REVERSE-LODGING-2026"},
            organization=prop.organization,
            product_code="HS-REVERSE-LODGING-2026",
            product_name="Alojamiento ERP migrado", product_type="Service",
            income_account=income.name, tax_profile=tax.name,
            sales_rate="100.00", active=1)
    frappe.db.commit()
    return {"property": prop.name, "organization": prop.organization,
        "receivable": receivable.name, "income": income.name,
        "temporary": temporary.name, "customer": party.name,
        "product": product.name}


def import_and_review():
    _guard()
    prop_name = frappe.db.get_value("HS Property", {"property_name": PROPERTY}, "name")
    if not prop_name or frappe.db.count("HS Property") != 1:
        frappe.throw("Prepare primero el destino PMS aislado")
    prop = frappe.get_doc("HS Property", prop_name)
    manifest, inventory = erp_fiscal_history.load_source_inventory(
        BUNDLE, SOURCE_SHA256, MANIFEST_SHA256)
    if len(inventory["properties"]) != 1:
        frappe.throw("El paquete debe contener exactamente un establecimiento")
    source = inventory["properties"][0]
    if str(prop.business_date) != str(source["business_date"]):
        frappe.throw("La fecha operativa PMS no coincide con el origen")
    imported = erp_fiscal_history.import_bundle(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, {source["property"]: prop.name})
    mapping = api.erp_to_pms_mapping_template(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256)
    target = mapping["properties"][source["property"]]
    target["property"] = prop.name
    target["temporary_opening_account"] = frappe.db.get_value("HS Account",
        {"property": prop.name, "account_code": "1990"}, "name")
    for row in source["mapping_requirements"]["accounts"]:
        code = ("1110" if row["account_type"] == "Bank" else
                "1210" if row["root_type"] == "Asset" else "4110")
        target["accounts"][row["name"]] = frappe.db.get_value("HS Account",
            {"property": prop.name, "account_code": code}, "name")
    for row in source["mapping_requirements"]["products"]:
        target["products"][row["name"]] = frappe.db.get_value("HS Product",
            {"property": prop.name, "product_code": "HS-REVERSE-LODGING-2026"},
            "name")
    for row in source["mapping_requirements"]["parties"]["Customer"]:
        target["customers"][row["name"]] = frappe.db.get_value("HS Party",
            {"property": prop.name, "party_name": "Cliente ERP migrado"}, "name")
    reviewed = api.erp_to_pms_mapping_review(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)
    preview = api.erp_to_pms_balance_preview(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)
    plan = api.erp_to_pms_transfer_plan(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)
    frappe.db.commit()
    return {"archive": imported, "manifest_documents": len(manifest["documents"]),
        "mapping": mapping, "review": reviewed, "preview": preview, "plan": plan}


def rehearse():
    _guard()
    prepared = import_and_review()
    if (not prepared["review"]["mapping_ready"] or
            not prepared["plan"]["ready_for_transfer"] or
            not prepared["plan"]["arithmetically_balanced"]):
        frappe.throw("El destino no está listo para ensayar")
    result = api.erp_to_pms_transfer_rehearsal(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, prepared["mapping"],
        prepared["plan"]["plan_sha256"])
    if (not result["reconciled"] or not result["rolled_back"] or
            frappe.db.exists("HS PMS Receivable", {
                "property": prepared["mapping"]["properties"]["ESTAB-00001"]["property"]}) or
            frappe.db.exists("HS Journal", {
                "property": prepared["mapping"]["properties"]["ESTAB-00001"]["property"]})):
        frappe.throw("El ensayo no revirtió la apertura contable")
    return {"reconciled": result["reconciled"],
        "rolled_back": result["rolled_back"],
        "provider_changed": result["provider_changed"],
        "properties": result["properties"],
        "plan_sha256": prepared["plan"]["plan_sha256"]}


def review_frozen():
    _guard()
    prepared = import_and_review()
    if not prepared["review"]["mapping_ready"]:
        frappe.throw("El mapa PMS no está listo")
    root = Path(frappe.get_site_path("private", "files")).resolve()
    path = root / MAPPING_FILE
    encoded = canonical(prepared["mapping"]) + "\n"
    if path.exists():
        if path.is_symlink() or path.read_text(encoding="utf-8") != encoded:
            frappe.throw("El mapa guardado difiere del mapa revisado")
    else:
        path.write_text(encoded, encoding="utf-8")
    reviewed = erp_to_pms_cli.review_file(MAPPING_FILE, RECEIPT,
        FROZEN_BUNDLE, source_sha256=SOURCE_SHA256,
        manifest_sha256=MANIFEST_SHA256, receipt_sha256=RECEIPT_SHA256,
        source_backup_sha256=SOURCE_BACKUP_SHA256)
    return {"mapping_file": MAPPING_FILE, **reviewed}


def rehearse_frozen():
    _guard()
    reviewed = review_frozen()
    if not reviewed["ready"] or reviewed["blockers"]:
        frappe.throw("La revisión congelada no está lista")
    result = erp_to_pms_activation.rehearse_activation(FROZEN_BUNDLE,
        RECEIPT, _json_file(MAPPING_FILE),
        source_sha256=SOURCE_SHA256, manifest_sha256=MANIFEST_SHA256,
        receipt_sha256=RECEIPT_SHA256,
        source_backup_sha256=SOURCE_BACKUP_SHA256,
        mapping_sha256=reviewed["mapping_sha256"],
        plan_sha256=reviewed["plan_sha256"],
        migration_reference="reverse-real-rehearsal-20261026")
    target = frappe.db.get_value("HS Property", {"property_name": PROPERTY}, "name")
    if (not result["reconciled"] or not result["rolled_back"] or
            frappe.db.exists("HS ERP to PMS Cutover Run", {
                "migration_reference": "reverse-real-rehearsal-20261026"}) or
            frappe.db.exists("HS PMS Receivable", {"property": target}) or
            frappe.db.exists("HS Journal", {"property": target}) or
            frappe.db.get_single_value("HS Site Mode", "provider") != "PMS"):
        frappe.throw("El ensayo congelado no revirtió todos los registros")
    return {"reconciled": result["reconciled"],
        "rolled_back": result["rolled_back"],
        "provider_changed": result["provider_changed"],
        "property_count": len(result["properties"])}


def activate():
    _guard()
    root = Path(frappe.get_site_path("private", "files")).resolve()
    if (root / TARGET_BACKUP_FILE).exists():
        manifest = _json_file(TARGET_BACKUP_FILE)
        backup_sha256 = pms_cutover_backup.verify(manifest)["sha256"]
    else:
        backup_sha256 = erp_to_pms_cli.prepare_backup_file(
            TARGET_BACKUP_FILE)["backup_sha256"]
    result = erp_to_pms_cli.activate_file(MAPPING_FILE, RECEIPT,
        FROZEN_BUNDLE, TARGET_BACKUP_FILE,
        source_sha256=SOURCE_SHA256, manifest_sha256=MANIFEST_SHA256,
        receipt_sha256=RECEIPT_SHA256,
        source_backup_sha256=SOURCE_BACKUP_SHA256,
        mapping_sha256=MAPPING_SHA256, plan_sha256=PLAN_SHA256,
        target_backup_sha256=backup_sha256,
        migration_reference=MIGRATION_REFERENCE)
    return {"activation": result, "target_backup_sha256": backup_sha256}


def verify_activation():
    _guard()
    prop = frappe.db.get_value("HS Property", {"property_name": PROPERTY}, "name")
    if (not prop or frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
            frappe.db.get_single_value("HS Site Mode", "migration_reference") !=
                MIGRATION_REFERENCE):
        frappe.throw("El libro PMS no conserva la referencia del corte")
    runs = frappe.get_all("HS ERP to PMS Cutover Run", fields=["name",
        "migration_reference", "source_site", "source_sha256"])
    receivables = frappe.get_all("HS PMS Receivable",
        filters={"property": prop}, fields=["name", "opening_source_site",
            "opening_source_name", "opening_source_sha256", "amount",
            "base_amount", "currency", "status", "journal"])
    journals = frappe.get_all("HS Journal", filters={"property": prop},
        fields=["name", "total_debit", "total_credit", "status"])
    fiscal = frappe.get_all("HS Historical Fiscal Document",
        filters={"property": prop}, fields=["name", "source_name",
            "source_site", "snapshot_sha256", "pdf_sha256", "pdf_file"])
    if (len(runs) != 1 or runs[0].migration_reference != MIGRATION_REFERENCE or
            runs[0].source_site != "hs-erp-smoke-reverse.local" or
            runs[0].source_sha256 != SOURCE_SHA256 or
            len(receivables) != 1 or
            receivables[0].opening_source_name != "ACC-SINV-2026-00001" or
            receivables[0].opening_source_site != "hs-erp-smoke-reverse.local" or
            receivables[0].opening_source_sha256 != SOURCE_SHA256 or
            Decimal(str(receivables[0].amount)) != 100 or
            Decimal(str(receivables[0].base_amount)) != 100 or
            receivables[0].currency != "NIO" or
            receivables[0].status != "Posted" or
            not frappe.db.exists("HS Journal", receivables[0].journal) or
            len(journals) != 2 or
            any(row.status != "Posted" or
                Decimal(str(row.total_debit)) != Decimal(str(row.total_credit))
                for row in journals) or
            len(fiscal) != 1 or
            fiscal[0].source_name != "ACC-SINV-2026-00001" or
            fiscal[0].source_site != "hs-erp-smoke-reverse.local"):
        frappe.throw("El corte persistente no conserva sus saldos y archivo")
    pdf = erp_fiscal_history._verified_content(
        frappe.get_doc("HS Historical Fiscal Document", fiscal[0].name))
    if not pdf.startswith(b"%PDF"):
        frappe.throw("El PDF fiscal histórico no es imprimible")
    board = api.pms_receivables(prop)
    visible = [row for row in board["receivables"]
        if row["name"] == receivables[0].name]
    archive = api.historical_fiscal_archive(prop)
    if (len(visible) != 1 or
            Decimal(str(visible[0]["outstanding"])) != 100 or
            archive["total"] != 1 or
            archive["documents"][0]["name"] != fiscal[0].name):
        frappe.throw("La cartera o el archivo no aparecen en las API PMS")
    api.historical_fiscal_pdf(fiscal[0].name)
    if frappe.response.get("filecontent") != pdf:
        frappe.throw("La API no entrega el PDF fiscal verificado")
    return {"cutover_run": runs[0].name,
        "receivable": receivables[0].name, "amount": str(receivables[0].amount),
        "currency": receivables[0].currency,
        "journals": [row.name for row in journals],
        "historical_invoice": fiscal[0].name, "pdf_bytes": len(pdf),
        "provider": "PMS"}


def verify_payment_continuity():
    """Collect a migrated ERPNext receivable through normal PMS commands, then undo."""
    _guard()
    baseline = verify_activation()
    prop = frappe.get_doc("HS Property", frappe.db.get_value("HS Property",
        {"property_name": PROPERTY}, "name"))
    receivable = baseline["receivable"]
    from hospitality_suite.standalone_receivables import outstanding

    if outstanding(prop, receivable) != 100:
        frappe.throw("La cartera migrada ya no conserva C$100 abiertos")
    counts = {doctype: frappe.db.count(doctype, {"property": prop.name})
        for doctype in ("HS Account", "HS Payment Method", "HS Payment",
                        "HS PMS Allocation", "HS Journal")}
    suffix = uuid4().hex
    frappe.db.savepoint("hs_reverse_real_payment_continuity")
    try:
        with operation(prop):
            bank = insert("HS Account", prop, organization=prop.organization,
                account_code="1110-" + suffix[:8],
                account_name="Banco para cobrar cartera migrada",
                root_type="Asset", account_type="Bank",
                account_currency="NIO", is_bank=1, active=1, is_group=0)
        method = api.execute(prop.name, "pms_payment_method",
            "reverse-real-bank-method-" + suffix,
            {"label": "Banco de continuidad", "account": bank.name})["method"]
        payments = []
        for index, value in enumerate(("40.00", "60.00"), start=1):
            data = {"kind": "Payment", "amount": value, "method": method,
                "receivable": receivable,
                "reference": f"REVERSE-REAL-PAY-{index}-{suffix[:8]}",
                "reason": "Ensayo reversible de cobro de cartera migrada"}
            quote = api.pms_cash_preview(prop.name, data)
            if (quote["debit"] != bank.name or
                    quote["credit"] != frappe.db.get_value(
                        "HS PMS Receivable", receivable, "receivable_account")):
                frappe.throw("La vista previa del cobro no usa las cuentas migradas")
            payload = {**data, "expected_debit": quote["debit"],
                "expected_credit": quote["credit"],
                "expected_exchange_rate": quote["exchange_rate"],
                "expected_rate_record": quote["exchange_rate_record"]}
            key = f"reverse-real-payment-{index}-{suffix}"
            posted = api.execute(prop.name, "pms_cash_movement", key, payload)
            if api.execute(prop.name, "pms_cash_movement", key, payload) != posted:
                frappe.throw("El reintento duplicó el cobro migrado")
            payments.append(posted["payment"])
            if outstanding(prop, receivable) != (60 if index == 1 else 0):
                frappe.throw("Los abonos no liquidaron la cartera progresivamente")
        if (len(set(payments)) != 2 or
                frappe.db.count("HS PMS Allocation", {
                    "property": prop.name, "receivable": receivable}) != 2):
            frappe.throw("El cobro PMS no conservó dos aplicaciones únicas")
        try:
            api.pms_cash_preview(prop.name, {"kind": "Payment", "amount": "1.00",
                "method": method, "receivable": receivable,
                "reference": "REVERSE-REAL-EXCESS-" + suffix[:8],
                "reason": "Comprobar exceso de cobro"})
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("El PMS permitió cobrar sobre la cartera migrada")
        result = {"partial_payment": "40.00", "final_payment": "60.00",
            "outstanding_after_second": "0.00", "idempotent": True,
            "excess_rejected": True}
    finally:
        frappe.db.rollback(save_point="hs_reverse_real_payment_continuity")
    if (outstanding(prop, receivable) != 100 or
            any(frappe.db.count(doctype, {"property": prop.name}) != total
                for doctype, total in counts.items()) or
            verify_activation()["cutover_run"] != baseline["cutover_run"]):
        frappe.throw("El ensayo de cobro dejó movimientos en el corte")
    return {**result, "rolled_back": True,
        "cutover_run": baseline["cutover_run"]}


def verify_daily_close_continuity():
    """Keep the imported balance in opening, never in new production."""
    _guard()
    baseline = verify_activation()
    prop = frappe.get_doc("HS Property", frappe.db.get_value("HS Property",
        {"property_name": PROPERTY}, "name"))
    day = str(prop.business_date)
    existing = frappe.db.count("HS Daily Close", {"property": prop.name})
    review = api.pms_close_preview(prop.name)
    snapshot = review["snapshot"]
    opening = snapshot["breakdown"]["opening_receivables"]
    if (review["blockers"] or len(opening) != 1 or
            Decimal(opening[0]["amount"]) != 100 or
            snapshot["breakdown"]["production"] or
            snapshot["breakdown"]["fiscal_documents"] or
            Decimal(snapshot["ledger"]["day_debit"]) !=
                Decimal(snapshot["ledger"]["day_credit"])):
        frappe.throw("El cierre incluye incorrectamente la apertura como venta")
    frappe.db.savepoint("hs_reverse_real_close_continuity")
    try:
        posted = api.execute(prop.name, "pms_daily_close",
            "reverse-real-close-" + uuid4().hex,
            {"review_acceptance": review["review_acceptance"],
             "reason": "Ensayo reversible del cierre posterior al corte"})
        detail = api.pms_close_detail(prop.name, posted["close"])
        if (detail["snapshot"] != snapshot or
                str(detail["business_date"]) != day or
                str(frappe.db.get_value("HS Property", prop.name,
                    "business_date")) == day):
            frappe.throw("El cierre no congeló el snapshot revisado")
        result = {"opening_receivable": opening[0]["amount"],
            "production": "0.00", "snapshot_immutable": True,
            "closed_date": day}
    finally:
        frappe.db.rollback(save_point="hs_reverse_real_close_continuity")
    if (frappe.db.count("HS Daily Close", {"property": prop.name}) != existing or
            str(frappe.db.get_value("HS Property", prop.name,
                "business_date")) != day or
            verify_activation()["cutover_run"] != baseline["cutover_run"]):
        frappe.throw("El ensayo de cierre dejó cambios persistentes")
    return {**result, "rolled_back": True,
        "cutover_run": baseline["cutover_run"]}
