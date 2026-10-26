"""Rollback-only import and scoped printing check on a Frappe-only site."""

from hashlib import sha256
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import subprocess
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile
from unittest.mock import patch

import frappe

from hospitality_suite import api, erp_fiscal_history, erp_to_pms_freeze, setup
from hospitality_suite.service import canonical, insert, operation


def _foreign_credit_package_probe(*, source_inventory, source_manifest,
                                  original_bundle, source_mapping, prop,
                                  org, temporary, suffix, bundle_paths):
    """Exercise the sealed bundle, plan and rollback writer with a USD note."""
    savepoint = "hs_reverse_foreign_credit_bundle_probe"
    frappe.db.savepoint(savepoint)
    try:
        from frappe.utils.pdf import get_pdf

        source = deepcopy(source_inventory)
        source_prop = source["properties"][0]
        source_account = "AR-USD-ORIGEN"
        source_customer = "CUSTOMER-USD-ORIGEN"
        source_note = "CN-USD-" + suffix
        source_prop["mapping_requirements"]["accounts"].append({
            "name": source_account, "root_type": "Asset",
            "account_type": "Receivable", "account_currency": "USD"})
        source_prop["mapping_requirements"]["parties"]["Customer"].append({
            "name": source_customer})
        source_prop["open_receivables"].append({
            "name": source_note, "party": source_customer,
            "account": source_account, "account_currency": "USD",
            "currency": "USD", "outstanding_amount": "-50.00",
            "base_outstanding_amount": "-1800.00", "is_return": True,
            "posting_date": str(frappe.utils.today()),
            "due_date": str(frappe.utils.today())})
        source_prop["ledger"]["lines"].append({
            "account": source_account, "cost_center": "CC-ORIGEN",
            "party_type": "Customer", "party": source_customer,
            "account_currency": "USD", "debit": "0",
            "credit": "1800.00", "original_balance": "-50.00"})
        income_line = next(row for row in source_prop["ledger"]["lines"]
            if row["account"] == "INCOME-ORIGEN")
        income_line["debit"] = "1800.00"
        income_line["original_balance"] = "1771.00"
        source_prop["ledger"]["debit"] = "1871.00"
        source_prop["ledger"]["credit"] = "1871.00"
        source_prop["ledger"]["matched_entries"] += 2
        pdf = get_pdf("<html><body><h1>NOTA USD " + suffix +
                      "</h1></body></html>")
        fiscal = {"name": source_note, "document_type": "Credit Note",
            "status": "Posted", "posting_date": str(frappe.utils.today()),
            "customer_name": "Cliente USD", "currency": "USD",
            "total_amount": "50.00", "source_invoice": "",
            "snapshot_sha256": "f" * 64}
        source_prop["fiscal_history"]["native_documents"].append(fiscal)
        encoded_source = canonical(source).encode()
        source_hash = sha256(encoded_source).hexdigest()
        source_key = erp_fiscal_history._source_key(
            source_manifest["source_site"], "Sales Invoice", source_note)
        sealed = deepcopy(source_manifest)
        sealed["source_sha256"] = source_hash
        sealed["inventory_sha256"] = source_hash
        sealed["documents"].append({
            "source_key": source_key, "property": source_prop["property"],
            "source_company": source_prop["company"],
            "source_doctype": "Sales Invoice", "source_name": source_note,
            "document_type": "Credit Note", "document_number": source_note,
            "posting_date": fiscal["posting_date"], "buyer_name": "Cliente USD",
            "currency": "USD", "total_amount": "50.00",
            "source_invoice": "", "status": "Posted",
            "snapshot_sha256": fiscal["snapshot_sha256"],
            "pdf_sha256": sha256(pdf).hexdigest()})
        sealed["documents"].sort(key=lambda row: row["source_key"])
        encoded_manifest = canonical(sealed).encode()
        manifest_hash = sha256(encoded_manifest).hexdigest()
        bundle_name = "hs-erp-fiscal-" + uuid4().hex + ".zip"
        path = Path(frappe.get_site_path("private", "files", bundle_name))
        with ZipFile(original_bundle) as previous, ZipFile(
                path, "w", compression=ZIP_DEFLATED) as output:
            for member in previous.namelist():
                if member not in ("manifest.json", "inventory.json"):
                    output.writestr(member, previous.read(member))
            output.writestr("manifest.json", encoded_manifest)
            output.writestr("inventory.json", encoded_source)
            output.writestr("pdf/" + source_key + ".pdf", pdf)
        bundle_paths.append(path)

        prop.append("accepted_currencies", {"currency": "USD"})
        prop.save()
        with operation(prop):
            target_account = insert("HS Account", prop,
                organization=org.name, account_code="1211-" + suffix[:8],
                account_name="Clientes USD migrados", root_type="Asset",
                account_type="Receivable", account_currency="USD",
                active=1, is_group=0)
            target_customer = insert("HS Party", prop, organization=org.name,
                party_name="Cliente USD migrado", party_type="Customer",
                active=1)
        imported = erp_fiscal_history.import_bundle(bundle_name, source_hash,
            manifest_hash, {source_prop["property"]: prop.name})
        archived = frappe.db.get_value("HS Historical Fiscal Document", {
            "property": prop.name, "source_doctype": "Sales Invoice",
            "source_name": source_note}, ["document_type", "currency",
            "total_amount", "pdf_sha256"], as_dict=True)
        if (imported["imported"] != 1 or imported["already_present"] != 2 or
                not archived or archived.document_type != "Credit Note" or
                archived.currency != "USD" or
                Decimal(str(archived.total_amount)) != 50 or
                archived.pdf_sha256 != sha256(pdf).hexdigest()):
            frappe.throw("El paquete USD no incorporó solo la nueva nota")
        mapped = deepcopy(source_mapping)
        mapped["source_sha256"] = source_hash
        mapped["manifest_sha256"] = manifest_hash
        cfg = mapped["properties"][source_prop["property"]]
        cfg["accounts"][source_account] = target_account.name
        cfg["customers"][source_customer] = target_customer.name
        reviewed = api.erp_to_pms_mapping_review(bundle_name, source_hash,
            manifest_hash, mapped)
        if not reviewed["mapping_ready"]:
            frappe.throw("El mapa del crédito USD no pasó: " +
                         frappe.as_json(reviewed["blockers"]))
        plan = api.erp_to_pms_transfer_plan(bundle_name, source_hash,
            manifest_hash, mapped)
        credit = next((row for row in plan["properties"][0]
            ["opening_customer_credits"] if row["source"] == source_note), None)
        if (not plan["arithmetically_balanced"] or not credit or
                credit["currency"] != "USD" or
                credit["signed_account_balance"] != "-50.00" or
                credit["signed_base_balance"] != "-1800.00"):
            frappe.throw("El plan no concilió la nota USD: " +
                         frappe.as_json(plan["blockers"]))
        from hospitality_suite import erp_to_pms_transfer_rehearsal as writer

        original_verify = writer._verify_property

        def verify_foreign_credit(target, expected, stock):
            opened = frappe.db.get_value("HS PMS Opening Credit", {
                "property": target.name, "opening_source_name": source_note},
                ["name", "currency", "amount", "base_currency",
                 "base_amount", "customer", "receivable_account", "journal"],
                as_dict=True)
            if (not opened or opened.currency != "USD" or
                    Decimal(str(opened.amount)) != 50 or
                    opened.base_currency != "NIO" or
                    Decimal(str(opened.base_amount)) != 1800 or
                    opened.customer != target_customer.name or
                    opened.receivable_account != target_account.name):
                frappe.throw("La apertura perdió el principal extranjero")
            lines = frappe.get_all("HS Journal Line", filters={
                "parent": opened.journal}, fields=["account", "party",
                "debit", "credit", "debit_in_account_currency",
                "credit_in_account_currency"])
            if {(line.account, line.party, Decimal(str(line.debit)),
                    Decimal(str(line.credit)),
                    Decimal(str(line.debit_in_account_currency)),
                    Decimal(str(line.credit_in_account_currency)))
                    for line in lines} != {
                    (temporary.name, None, Decimal(1800), Decimal(0),
                     Decimal(1800), Decimal(0)),
                    (target_account.name, target_customer.name,
                     Decimal(0), Decimal(1800), Decimal(0), Decimal(50))}:
                frappe.throw("El asiento de la nota USD no conserva ambas monedas")
            original_verify(target, expected, stock)

        with patch.object(writer, "_verify_property",
                          side_effect=verify_foreign_credit):
            rehearsal = api.erp_to_pms_transfer_rehearsal(bundle_name,
                source_hash, manifest_hash, mapped, plan["plan_sha256"])
        if (not rehearsal["reconciled"] or not rehearsal["rolled_back"] or
                len(rehearsal["properties"][0]["credits"]) != 3 or
                frappe.db.exists("HS PMS Opening Credit", {
                    "property": prop.name, "opening_source_name": source_note})):
            frappe.throw("La apertura USD no concilió o dejó datos")
        return True
    finally:
        frappe.db.rollback(save_point=savepoint)


def run(persist=False):
    if ("erpnext" in frappe.get_installed_apps() or
            not frappe.local.site.startswith("hs-pms-smoke") or
            (persist and frappe.local.site != "hs-pms-smoke-reverse.local")):
        frappe.throw("Use únicamente el sitio Frappe PMS de ensayo")
    frappe.set_user("Administrator")
    suffix = uuid4().hex
    bundle_paths = []
    pdf_path = None
    persisted = False
    frappe.db.savepoint("hs_reverse_fiscal_target_probe")
    try:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "Archivo fiscal " + suffix, "base_currency": "NIO",
            "tax_regime": "General", "active": 1}).insert()
        created = setup.create_property({"property_name": "Archivo fiscal " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "reverse-fiscal-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        other = setup.create_property({"property_name": "Otro hotel fiscal " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "reverse-fiscal-other-" + suffix)
        other_prop = frappe.get_doc("HS Property", other["property"])
        with operation(prop):
            account = insert("HS Account", prop, organization=org.name,
                account_code="1210-" + suffix[:8],
                account_name="Clientes migrados", root_type="Asset",
                account_type="Receivable", account_currency="NIO",
                active=1, is_group=0)
            second_receivable_account = insert("HS Account", prop,
                organization=org.name, account_code="1220-" + suffix[:8],
                account_name="Clientes nueva cartera", root_type="Asset",
                account_type="Receivable", account_currency="NIO",
                active=1, is_group=0)
            income = insert("HS Account", prop, organization=org.name,
                account_code="4110-" + suffix[:8],
                account_name="Ingresos migrados", root_type="Income",
                account_type="General", account_currency="NIO",
                active=1, is_group=0)
            service_expense = insert("HS Account", prop, organization=org.name,
                account_code="5110-" + suffix[:8],
                account_name="Costo de servicios migrados", root_type="Expense",
                account_type="General", account_currency="NIO",
                active=1, is_group=0)
            service_tax = insert("HS PMS Tax Profile", prop,
                organization=org.name, label="Servicio exento migrado",
                treatment="Exempt", rate=0, active=1)
            temporary = insert("HS Account", prop, organization=org.name,
                account_code="1990-" + suffix[:8],
                account_name="Puente de apertura", root_type="Asset",
                account_type="Temporary", account_currency="NIO",
                active=1, is_group=0)
            stock_account = insert("HS Account", prop, organization=org.name,
                account_code="1310-" + suffix[:8],
                account_name="Existencias migradas", root_type="Asset",
                account_type="Stock", account_currency="NIO",
                active=1, is_group=0)
            bank = insert("HS Account", prop, organization=org.name,
                account_code="1110-" + suffix[:8],
                account_name="Banco migrado", root_type="Asset",
                account_type="Bank", account_currency="NIO",
                active=1, is_group=0, is_bank=1)
            payable_account = insert("HS Account", prop, organization=org.name,
                account_code="2110-" + suffix[:8],
                account_name="Proveedores migrados", root_type="Liability",
                account_type="Payable", account_currency="NIO",
                active=1, is_group=0)
            second_payable_account = insert("HS Account", prop, organization=org.name,
                account_code="2120-" + suffix[:8],
                account_name="Proveedores otra cuenta", root_type="Liability",
                account_type="Payable", account_currency="NIO",
                active=1, is_group=0)
            guarantee_account = insert("HS Account", prop, organization=org.name,
                account_code="2130-" + suffix[:8],
                account_name="Garantías migradas", root_type="Liability",
                account_type="Current Liability", account_currency="NIO",
                active=1, is_group=0)
            equity = insert("HS Account", prop, organization=org.name,
                account_code="3110-" + suffix[:8],
                account_name="Patrimonio migrado", root_type="Equity",
                account_type="Equity", account_currency="NIO",
                active=1, is_group=0)
            party = insert("HS Party", prop, organization=org.name,
                party_name="Cliente migrado", party_type="Customer", active=1)
            supplier = insert("HS Party", prop, organization=org.name,
                party_name="Proveedor migrado", party_type="Supplier", active=1)
            product = insert("HS Product", prop, organization=org.name,
                product_code="SVC-" + suffix[:8],
                product_name="Servicio migrado", product_type="Service",
                income_account=income.name, tax_profile=service_tax.name,
                sales_rate="3.00", active=1)
            experience = insert("HS Experience", prop,
                experience_name="Experiencia migrada",
                experience_category="Spa", pms_product=product.name,
                active=1)
            laundry_rate = insert("HS Laundry Rate", prop,
                garment="Camisa migrada", service_type="Wash & Iron",
                pms_product=product.name, currency="NIO", rate="3.00",
                active=1)
            stock_product = insert("HS Product", prop, organization=org.name,
                product_code="STK-" + suffix[:8],
                product_name="Artículo migrado", product_type="Stock",
                inventory_account=stock_account.name,
                expense_account=service_expense.name, active=1)
            warehouse = insert("HS Warehouse", prop, organization=org.name,
                warehouse_code="WH-" + suffix[:8],
                warehouse_name="Almacén migrado", active=1)
            category = insert("HS Category", prop,
                category_name="Categoría migrada", capacity=2)
            room = insert("HS Room", prop, room_number="R-" + suffix[:8],
                category=category.name, active=1, cleaning_status="Clean")
            rate = insert("HS Rate", prop, title="Tarifa migrada",
                category=category.name, currency="NIO", amount=25,
                mode="Hotel", active=1)
            guest = insert("HS Guest", prop, full_name="Huésped migrado",
                customer=party.name)
            agent = insert("HS Travel Agent", prop,
                agent_name="Agencia migrada", agent_type="Travel Agent",
                pms_supplier=supplier.name, active=1)
            equipment = insert("HS Equipment", prop,
                equipment_code="AC-" + suffix[:8], label="Equipo migrado",
                room=room.name, active=1)
        bank_method = api.execute(prop.name, "pms_payment_method",
            "reverse-bank-" + suffix,
            {"label": "Banco apertura", "account": bank.name})["method"]
        from frappe.utils.pdf import get_pdf

        pdf = get_pdf("<html><body><h1>FACTURA HISTÓRICA " + suffix +
                      "</h1><p>Sin RUC ni referencia de autorización</p></body></html>")
        credit_pdf = get_pdf("<html><body><h1>NOTA DE CRÉDITO HISTÓRICA " +
                             suffix + "</h1></body></html>")
        if not pdf.startswith(b"%PDF") or not credit_pdf.startswith(b"%PDF"):
            frappe.throw("No se generó un PDF imprimible")
        site = "erp-source.example.invalid"
        key = erp_fiscal_history._source_key(site, "Sales Invoice", "SINV-" + suffix)
        row = {"source_key": key, "property": "HOTEL-ORIGEN",
            "source_company": "EMPRESA-ORIGEN", "source_doctype": "Sales Invoice",
            "source_name": "SINV-" + suffix, "document_type": "Invoice",
            "document_number": "SINV-" + suffix, "posting_date": str(frappe.utils.today()),
            "buyer_name": "Cliente histórico", "currency": "NIO",
            "total_amount": "25.00", "source_invoice": "", "status": "Posted",
            "snapshot_sha256": "b" * 64, "pdf_sha256": sha256(pdf).hexdigest()}
        credit_key = erp_fiscal_history._source_key(site, "Sales Invoice", "CN-" + suffix)
        credit_row = {"source_key": credit_key, "property": "HOTEL-ORIGEN",
            "source_company": "EMPRESA-ORIGEN", "source_doctype": "Sales Invoice",
            "source_name": "CN-" + suffix, "document_type": "Credit Note",
            "document_number": "CN-" + suffix,
            "posting_date": str(frappe.utils.today()),
            "buyer_name": "Cliente histórico", "currency": "NIO",
            "total_amount": "4.00", "source_invoice": row["source_name"],
            "status": "Posted", "snapshot_sha256": "c" * 64,
            "pdf_sha256": sha256(credit_pdf).hexdigest()}
        incident_evidence = ("Evidencia privada de incidencia " + suffix).encode()
        incident_evidence_name = "evidencia-" + suffix[:8] + ".txt"
        incident_evidence_key = erp_fiscal_history._source_key(
            site, "HS Incident", "INC-EVIDENCE-ORIGEN-" + suffix)
        incident_evidence_url = "/private/files/source-" + incident_evidence_name
        maintenance_evidence = ("Evidencia privada de mantenimiento " + suffix).encode()
        maintenance_evidence_name = "mantenimiento-" + suffix[:8] + ".txt"
        maintenance_evidence_key = erp_fiscal_history._source_key(
            site, "HS Maintenance Order", "MAINT-ORIGEN-" + suffix)
        maintenance_evidence_url = "/private/files/source-" + maintenance_evidence_name
        arrival = str(frappe.utils.today()) + " 14:00:00"
        departure = str(frappe.utils.add_days(frappe.utils.today(), 1)) + " 11:00:00"
        portal_start = str(frappe.utils.add_days(
            frappe.utils.today(), 5)) + " 14:00:00"
        portal_end = str(frappe.utils.add_days(
            frappe.utils.today(), 6)) + " 11:00:00"
        block_start = str(frappe.utils.add_days(frappe.utils.today(), 1)) + " 13:00:00"
        block_end = str(frappe.utils.add_days(frappe.utils.today(), 2)) + " 13:00:00"
        maintenance_start = str(frappe.utils.add_days(
            frappe.utils.today(), 2)) + " 15:00:00"
        maintenance_end = str(frappe.utils.add_days(
            frappe.utils.today(), 3)) + " 15:00:00"
        booking_name = "RES-ORIGEN-" + suffix
        stay_name = "EST-ORIGEN-" + suffix
        closed_stay_name = "EST-CERRADA-ORIGEN-" + suffix
        folio_name = "FOL-ORIGEN-" + suffix
        line_name = "LINE-ORIGEN-" + suffix
        accepted_line = {"category": "CAT-ORIGEN", "room": "ROOM-ORIGEN",
            "currency": "NIO", "amount": "20.00",
            "rules": {"name": "RATE-ORIGEN", "category": "CAT-ORIGEN"},
            "charge_items": {"lodging_item": "SVC-ORIGEN"}}
        accepted_experience = {"experience": "EXPERIENCE-ORIGEN",
            "name": "Experiencia migrada", "item": "SVC-ORIGEN",
            "item_price": "PRICE-ORIGEN", "quantity": 1,
            "rate": "3.00", "amount": "3.00"}
        booking_quote = canonical({"currency": "NIO", "amount": "20.00",
            "lines": [accepted_line], "experiences": [accepted_experience],
            "experiences_total": "3.00", "estimated_total": "23.00"})
        portal_quote = canonical({"currency": "NIO", "amount": "20.00",
            "lines": [accepted_line], "experiences": [accepted_experience],
            "experiences_total": "3.00", "estimated_total": "23.00"})
        line_quote = canonical(accepted_line)
        entitlements = canonical([{"item": "SVC-ORIGEN", "quantity": "1"},
            {"item": "STOCK-ITEM-ORIGEN", "quantity": "2"}])
        prior_issue = {"voucher": "MAT-STE-ORIGEN-" + suffix,
            "item": "STOCK-ITEM-ORIGEN", "warehouse": "WH-ORIGEN",
            "quantity": "1", "cost": "4",
            "expense_account": "EXPENSE-ORIGEN",
            "inventory_account": "STOCK-ORIGEN"}
        portal_experiences = canonical([{"experience": "EXPERIENCE-ORIGEN",
            "quantity": 1}])
        from hospitality_suite.time import to_site
        pass_day = str(frappe.utils.add_days(frappe.utils.today(), 1))
        pass_start = str(to_site(pass_day + " 09:00:00", prop))
        pass_end = str(to_site(pass_day + " 17:00:00", prop))
        pass_financial = {"invoice": row["source_name"],
            "invoice_net": "20.00", "invoice_tax": "5.00",
            "invoice_total": "25.00", "invoice_currency": "NIO",
            "receivable_account": "AR-ORIGEN",
            "payment": "PAG-ORIGEN-" + suffix,
            "payment_entry": "PAY-ORIGEN-" + suffix,
            "payment_currency": "NIO", "payment_amount": "25.00",
            "payment_base_amount": "25.00",
            "service": "SREQ-PASS-ORIGEN-" + suffix,
            "invoice_gl": [
                {"account": "AR-ORIGEN", "party_type": "Customer",
                 "party": "CUSTOMER-ORIGEN", "debit": "25.00",
                 "credit": "0", "account_currency": "NIO",
                 "root_type": "Asset", "account_type": "Receivable",
                 "debit_in_account_currency": "25.00",
                 "credit_in_account_currency": "0"},
                {"account": "INCOME-ORIGEN", "party_type": None,
                 "party": None, "debit": "0", "credit": "20.00",
                 "account_currency": "NIO",
                 "root_type": "Income", "account_type": "General",
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": "20.00"},
                {"account": "GUAR-ORIGEN", "party_type": None,
                 "party": None, "debit": "0", "credit": "5.00",
                 "account_currency": "NIO",
                 "root_type": "Liability", "account_type": "Current Liability",
                 "debit_in_account_currency": "0",
                 "credit_in_account_currency": "5.00"}]}
        maintenance_issue = {"voucher": "SE-VIGENTE-ORIGEN",
            "detail": "SE-LINE-ORIGEN", "item": "STOCK-ITEM-ORIGEN",
            "warehouse": "WH-ORIGEN", "quantity": "1", "cost": "3.00",
            "group_count": 2, "voucher_total_cost": "6.00",
            "expense_account": "EXPENSE-ORIGEN",
            "inventory_account": "STOCK-ORIGEN"}
        maintenance_issue_second = {**maintenance_issue,
            "detail": "SE-LINE-2-ORIGEN"}
        inventory = {"schema_version": 1, "provider": "ERPNext",
            "properties": [{"property": "HOTEL-ORIGEN", "company": "EMPRESA-ORIGEN",
                "currency": "NIO", "business_date": str(prop.business_date),
                "mapping_requirements": {
                    "source_settings": {"warehouse": "WH-ORIGEN"},
                    "accounts": [{"name": "AR-ORIGEN",
                        "root_type": "Asset", "account_type": "Receivable",
                        "account_currency": "NIO"}, {"name": "INCOME-ORIGEN",
                        "root_type": "Income", "account_type": "General",
                        "account_currency": "NIO"}, {"name": "EXPENSE-ORIGEN",
                        "root_type": "Expense", "account_type": "General",
                        "account_currency": "NIO"}, {"name": "STOCK-ORIGEN",
                        "root_type": "Asset", "account_type": "Stock",
                        "account_currency": "NIO"}, {"name": "BANK-ORIGEN",
                        "root_type": "Asset", "account_type": "Bank",
                        "account_currency": "NIO"}, {"name": "AP-ORIGEN",
                        "root_type": "Liability", "account_type": "Payable",
                        "account_currency": "NIO"}, {"name": "EQUITY-ORIGEN",
                        "root_type": "Equity", "account_type": "Equity",
                        "account_currency": "NIO"}, {"name": "AP2-ORIGEN",
                        "root_type": "Liability", "account_type": "Payable",
                        "account_currency": "NIO"}, {"name": "GUAR-ORIGEN",
                        "root_type": "Liability", "account_type": "Current Liability",
                        "account_currency": "NIO"}],
                    "products": [{"name": "SVC-ORIGEN", "is_stock_item": 0,
                        "is_fixed_asset": 0}, {"name": "STOCK-ITEM-ORIGEN",
                        "is_stock_item": 1, "is_fixed_asset": 0}],
                    "parties": {"Customer": [{"name": "CUSTOMER-ORIGEN"}],
                                "Supplier": [{"name": "SUPPLIER-ORIGEN"}]},
                    "warehouses": [{"name": "WH-ORIGEN"}],
                    "categories": [{"name": "CAT-ORIGEN"}],
                    "rooms": [{"name": "ROOM-ORIGEN", "category": "CAT-ORIGEN"}],
                    "rates": [{"name": "RATE-ORIGEN", "category": "CAT-ORIGEN",
                               "currency": "NIO", "mode": "Hotel"}],
                    "guests": [{"name": "GUEST-ORIGEN",
                        "customer": "CUSTOMER-ORIGEN"}],
                    "travel_agents": [{"name": "AGENT-ORIGEN",
                        "agent_type": "Travel Agent",
                        "supplier": "SUPPLIER-ORIGEN"}],
                    "experiences": [{"name": "EXPERIENCE-ORIGEN",
                        "item": "SVC-ORIGEN",
                        "experience_category": "Spa", "active": 1}],
                    "laundry_rates": [{"name": "LAUNDRY-RATE-ORIGEN",
                        "item": "SVC-ORIGEN", "garment": "Camisa migrada",
                        "service_type": "Wash & Iron", "currency": "NIO",
                        "active": 1}],
                    "users": [{"name": "ADMIN-ORIGEN"}],
                    "equipment": [{"name": "EQUIP-ORIGEN",
                        "room": "ROOM-ORIGEN", "active": 1}]},
                "ledger": {"debit": "71.00", "credit": "71.00",
                    "matched_entries": 16, "lines": [
                        {"account": "AR-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": "Customer", "party": "CUSTOMER-ORIGEN",
                         "account_currency": "NIO", "debit": "25.00",
                         "credit": "7.00", "original_balance": "18.00"},
                        {"account": "INCOME-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": None, "party": None,
                         "account_currency": "NIO", "debit": "0",
                         "credit": "29.00", "original_balance": "-29.00"},
                        {"account": "STOCK-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": None, "party": None,
                         "account_currency": "NIO", "debit": "10.00",
                         "credit": "0", "original_balance": "10.00"},
                        {"account": "BANK-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": None, "party": None,
                         "account_currency": "NIO", "debit": "26.00",
                         "credit": "0", "original_balance": "26.00"},
                        {"account": "AP-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": "Supplier", "party": "SUPPLIER-ORIGEN",
                         "account_currency": "NIO", "debit": "4.00",
                         "credit": "12.00", "original_balance": "-8.00"},
                        {"account": "AP2-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": "Supplier", "party": "SUPPLIER-ORIGEN",
                         "account_currency": "NIO", "debit": "0",
                         "credit": "2.00", "original_balance": "-2.00"},
                        {"account": "GUAR-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": None, "party": None,
                         "account_currency": "NIO", "debit": "0",
                         "credit": "5.00", "original_balance": "-5.00"},
                        {"account": "EQUITY-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": None, "party": None,
                         "account_currency": "NIO", "debit": "0",
                         "credit": "16.00", "original_balance": "-16.00"},
                        {"account": "EXPENSE-ORIGEN", "cost_center": "CC-ORIGEN",
                         "party_type": None, "party": None,
                         "account_currency": "NIO", "debit": "6.00",
                         "credit": "0", "original_balance": "6.00"}]},
                "stock": {"warehouses": ["WH-ORIGEN"], "positions": [
                    {"item": "STOCK-ITEM-ORIGEN", "warehouse": "WH-ORIGEN",
                     "quantity": "2", "stock_value": "10.00"}]},
                "open_receivables": [{"name": "SINV-" + suffix,
                    "party": "CUSTOMER-ORIGEN", "account": "AR-ORIGEN",
                    "folio": folio_name, "stay": stay_name,
                    "booking": booking_name,
                    "folio_property": "HOTEL-ORIGEN",
                    "folio_company": "EMPRESA-ORIGEN",
                    "folio_customer": "CUSTOMER-ORIGEN",
                    "folio_currency": "NIO", "folio_status": "Open",
                    "account_currency": "NIO", "currency": "NIO",
                    "outstanding_amount": "25.00"},
                    {"name": "CN-" + suffix,
                    "party": "CUSTOMER-ORIGEN", "account": "AR-ORIGEN",
                    "account_currency": "NIO", "currency": "NIO",
                    "outstanding_amount": "-4.00"}],
                "open_payables": [{"name": "PINV-" + suffix,
                    "party": "SUPPLIER-ORIGEN", "account": "AP-ORIGEN",
                    "account_currency": "NIO", "currency": "NIO",
                    "outstanding_amount": "12.00",
                    "due_date": str(frappe.utils.today())},
                    {"name": "PCN-" + suffix,
                     "party": "SUPPLIER-ORIGEN", "account": "AP-ORIGEN",
                     "account_currency": "NIO", "currency": "NIO",
                     "outstanding_amount": "-4.00",
                     "due_date": str(frappe.utils.today())},
                    {"name": "PINV2-" + suffix,
                     "party": "SUPPLIER-ORIGEN", "account": "AP2-ORIGEN",
                     "account_currency": "NIO", "currency": "NIO",
                     "outstanding_amount": "2.00",
                     "due_date": str(frappe.utils.today())}],
                "deposits": {"guarantees": [{
                    "source": "HS-GUAR-" + suffix,
                    "customer": "CUSTOMER-ORIGEN",
                    "booking": "RES-ORIGEN-" + suffix,
                    "stay": None, "folio": "FOL-ORIGEN-" + suffix,
                    "currency": "NIO", "nominal": "5.00",
                    "base_balance": "5.00",
                    "journal_entry": "JV-GUAR-" + suffix,
                    "liability_account": "GUAR-ORIGEN"}], "customer_credits": [{
                    "voucher_type": "Payment Entry", "voucher": "PE-" + suffix,
                    "customer": "CUSTOMER-ORIGEN",
                    "receivable_account": "AR-ORIGEN",
                    "cash_account": "BANK-ORIGEN", "account_currency": "NIO",
                    "paid_currency": "NIO", "original_amount": "3.00",
                    "available": "3.00", "exchange_rate": "1",
                    "posting_date": str(frappe.utils.today()),
                    "sources": []}]},
                "open_operations": {
                    "bookings": [{"name": booking_name, "status": "Checked In",
                        "customer": "CUSTOMER-ORIGEN", "guest": "GUEST-ORIGEN",
                        "travel_agent": "AGENT-ORIGEN",
                        "agent_commission_pct": 5,
                        "agent_commission_estimate": "1.00",
                        "starts_at": arrival,
                        "ends_at": departure, "currency": "NIO", "amount": "20.00",
                        "quote_snapshot": booking_quote,
                        "quote_snapshot_sha256": sha256(booking_quote.encode()).hexdigest()}],
                    "booking_rooms": [{"name": line_name, "parent": booking_name,
                        "idx": 1, "category": "CAT-ORIGEN", "room": "ROOM-ORIGEN",
                        "rate": "RATE-ORIGEN", "people": 1, "extra_beds": 0}],
                    "stays": [{"name": stay_name, "status": "Active",
                        "booking": booking_name, "guest": "GUEST-ORIGEN",
                        "customer": "CUSTOMER-ORIGEN", "room": "ROOM-ORIGEN",
                        "rate": "RATE-ORIGEN", "starts_at": arrival,
                        "ends_at": departure, "currency": "NIO", "amount": "20.00",
                        "quote_snapshot": line_quote,
                        "quote_snapshot_sha256": sha256(line_quote.encode()).hexdigest(),
                        "service_entitlements": entitlements,
                        "service_entitlements_sha256": sha256(
                            entitlements.encode()).hexdigest()}],
                    "stay_guests": [{"name": "SG-ORIGEN-" + suffix,
                        "parent": stay_name, "idx": 1, "guest": "GUEST-ORIGEN",
                        "relationship": "Principal"}],
                    "folios": [{"name": folio_name, "status": "Open",
                        "booking": booking_name, "stay": stay_name,
                        "customer": "CUSTOMER-ORIGEN", "currency": "NIO",
                        "label": "Cuenta principal"}],
                    "charges": [{"name": "CHG-ORIGEN-" + suffix,
                        "status": "Pending", "stay": stay_name, "folio": folio_name,
                        "item": "SVC-ORIGEN", "description": "Servicio pendiente",
                        "quantity": 1, "rate": "2.00", "amount": "2.00",
                        "currency": "NIO", "business_date": str(frappe.utils.today()),
                        "kind": "Service", "quote_snapshot": line_quote,
                        "quote_snapshot_sha256": sha256(line_quote.encode()).hexdigest()}],
                    "service_requests": [{"name": "SREQ-ORIGEN-" + suffix,
                        "status": "In Progress", "stay": stay_name,
                        "folio": folio_name, "customer": "CUSTOMER-ORIGEN",
                        "item": "SVC-ORIGEN", "quantity": 1,
                        "included": 0, "amount": "3.00", "currency": "NIO",
                        "notes": "Entregar servicio aceptado"},
                        {"name": "SREQ-STOCK-ORIGEN-" + suffix,
                        "status": "Requested", "stay": stay_name,
                        "folio": folio_name, "customer": "CUSTOMER-ORIGEN",
                        "item": "STOCK-ITEM-ORIGEN", "quantity": 1,
                        "included": 1, "amount": "0", "currency": "NIO",
                        "notes": "Entregar artículo incluido"},
                        {"name": "SREQ-DELIVERED-ORIGEN-" + suffix,
                        "status": "Delivered", "stay": stay_name,
                        "folio": folio_name, "customer": "CUSTOMER-ORIGEN",
                        "item": "STOCK-ITEM-ORIGEN", "quantity": 1,
                        "included": 1, "amount": "0", "currency": "NIO",
                        "stock_entry": prior_issue["voucher"],
                        "source_stock_issue": prior_issue,
                        "source_stock_issue_sha256": sha256(
                            canonical(prior_issue).encode()).hexdigest(),
                        "notes": "Incluido y entregado antes del corte"},
                        {"name": "SREQ-CHARGED-ORIGEN-" + suffix,
                        "status": "Delivered", "stay": stay_name,
                        "folio": folio_name, "customer": "CUSTOMER-ORIGEN",
                        "item": "SVC-ORIGEN", "quantity": 1,
                        "included": 0, "amount": "2.00", "currency": "NIO",
                        "charge": "CHG-ORIGEN-" + suffix,
                        "notes": "Entregado con cargo pendiente"}],
                    "cleaning_tasks": [{"name": "CLEAN-ORIGEN-" + suffix,
                        "status": "Pending", "room": "ROOM-ORIGEN",
                        "stay": closed_stay_name, "kind": "Departure",
                        "source_closed_stay": {"name": closed_stay_name,
                            "room": "ROOM-ORIGEN", "status": "Checked Out",
                            "modified": "2026-10-19 09:07:44"},
                        "priority": "High",
                        "assigned_to": "ADMIN-ORIGEN",
                        "checklist": canonical({"baño": False, "cama": False,
                            "minibar": False, "superficies": False}),
                        "checklist_sha256": sha256(canonical({"baño": False,
                            "cama": False, "minibar": False,
                            "superficies": False}).encode()).hexdigest(),
                        "notes": "Limpieza pendiente del turno",
                        "room_cleaning_status": "Dirty"}],
                    "guest_tickets": [{"name": "TICKET-ORIGEN-" + suffix,
                        "room": "ROOM-ORIGEN", "stay": stay_name,
                        "subject": "Toallas adicionales",
                        "description": "Solicitud pendiente del huésped",
                        "category": "Guest Request", "priority": "High",
                        "status": "In Progress", "assigned_to": "ADMIN-ORIGEN",
                        "due_at": departure, "first_response_at": arrival,
                        "reopened_count": 0}],
                    "ticket_events": [{"name": "EVENT-CREATED-" + suffix,
                        "ticket": "TICKET-ORIGEN-" + suffix,
                        "kind": "Created", "actor": "ADMIN-ORIGEN",
                        "occurred_at": arrival,
                        "note": "Solicitud pendiente del huésped"},
                        {"name": "EVENT-STARTED-" + suffix,
                        "ticket": "TICKET-ORIGEN-" + suffix,
                        "kind": "Started", "actor": "ADMIN-ORIGEN",
                        "occurred_at": arrival,
                        "before_value": "Open",
                        "after_value": "In Progress"}],
                    "incidents": [{"name": "INC-ORIGEN-" + suffix,
                        "status": "Open", "room": "ROOM-ORIGEN",
                        "kind": "Lost Property",
                        "description": "Objeto pendiente de devolución",
                        "item": "Mochila negra", "quantity": 1},
                        {"name": "INC-EVIDENCE-ORIGEN-" + suffix,
                         "status": "Open", "room": "ROOM-ORIGEN",
                         "kind": "Damage",
                         "description": "Daño con evidencia privada",
                         "evidence": incident_evidence_url,
                         "evidence_file_name": incident_evidence_name,
                         "evidence_size": len(incident_evidence),
                         "evidence_sha256": sha256(
                             incident_evidence).hexdigest()}],
                    "day_passes": [{"name": "PASS-ORIGEN-" + suffix,
                        "status": "Issued", "customer": "CUSTOMER-ORIGEN",
                        "guest": "GUEST-ORIGEN", "people": 1,
                        "starts_at": pass_start, "ends_at": pass_end,
                        "service": pass_financial["service"],
                        "sales_invoice": pass_financial["invoice"],
                        "payment": pass_financial["payment"],
                        "source_financial": pass_financial,
                        "source_financial_sha256": sha256(
                            canonical(pass_financial).encode()).hexdigest(),
                        "notes": "Acceso ya cobrado antes del corte"}],
                    "experience_orders": [{"name": "EXPO-BOOKED-" + suffix,
                        "experience": "EXPERIENCE-ORIGEN",
                        "booking": booking_name,
                        "customer": "CUSTOMER-ORIGEN",
                        "item": "SVC-ORIGEN", "quantity": 1,
                        "participants": 1, "scheduled_at": departure,
                        "unit_rate": "3.00", "currency": "NIO",
                        "amount": "3.00", "status": "Confirmed",
                        "notes": "Reserva confirmada antes del corte"},
                        {"name": "EXPO-DIRECT-" + suffix,
                        "experience": "EXPERIENCE-ORIGEN",
                        "customer": "CUSTOMER-ORIGEN",
                        "item": "SVC-ORIGEN", "quantity": 1,
                        "participants": 1, "scheduled_at": departure,
                        "unit_rate": "3.00", "currency": "NIO",
                        "amount": "3.00", "accepted_net": "3.00",
                        "accepted_tax": "0.00", "accepted_total": "3.00",
                        "accepted_tax_profile": "TAX-ORIGEN",
                        "income_account": "INCOME-ORIGEN",
                        "status": "Confirmed",
                        "notes": "Venta directa pendiente antes del corte"}],
                    "laundry_orders": [{"name": "LAUNDRY-ORIGEN-" + suffix,
                        "status": "Ready", "stay": stay_name,
                        "room": "ROOM-ORIGEN", "folio": folio_name,
                        "currency": "NIO", "express": 0,
                        "complimentary": 0, "notes": "Prendas listas",
                        "total": "3.00", "billed_total": "0.00",
                        "ready_by": departure,
                        "collected_by": "ADMIN-ORIGEN",
                        "collected_at": arrival, "counted_at": arrival},
                        {"name": "LAUNDRY-REQUESTED-" + suffix,
                         "status": "Requested", "stay": stay_name,
                         "room": "ROOM-ORIGEN", "folio": folio_name,
                         "currency": "NIO", "express": 0,
                         "complimentary": 0,
                         "notes": "Recogida pendiente", "total": "0.00",
                         "billed_total": "0.00"}],
                    "laundry_items": [{"name": "LAUNDRY-LINE-ORIGEN-" + suffix,
                        "parent": "LAUNDRY-ORIGEN-" + suffix,
                        "idx": 1, "laundry_rate": "LAUNDRY-RATE-ORIGEN",
                        "garment": "Camisa migrada",
                        "service_type": "Wash & Iron",
                        "item": "SVC-ORIGEN", "quantity": 1,
                        "returned_quantity": 1,
                        "rate": "3.00", "amount": "3.00"}],
                    "portal_requests": [{"name": "WEB-ORIGEN-" + suffix,
                        "status": "Hold", "full_name": "Huésped web",
                        "category": "CAT-ORIGEN", "rooms": 1, "people": 1,
                        "mode": "Hotel", "starts_at": portal_start,
                        "ends_at": portal_end,
                        "hold_until": str(frappe.utils.add_to_date(
                            frappe.utils.now_datetime(), hours=1)),
                        "currency": "NIO", "amount": "20.00",
                        "quote_snapshot": portal_quote,
                        "quote_snapshot_sha256": sha256(
                            portal_quote.encode()).hexdigest(),
                        "experiences": portal_experiences,
                        "experiences_sha256": sha256(
                            portal_experiences.encode()).hexdigest(),
                        "request_key": "WEB-KEY-" + suffix,
                        "payload_hash": "e" * 64}],
                    "room_blocks": [{"name": "BLOCK-ORIGEN-" + suffix,
                        "status": "Active", "room": "ROOM-ORIGEN",
                        "reason": "VIP Hold", "starts_at": block_start,
                        "ends_at": block_end, "note": "Bloqueo migrado",
                        "created_by": "ADMIN-ORIGEN"}],
                    "maintenance_orders": [{"name": "MAINT-ORIGEN-" + suffix,
                        "status": "Open", "room": "ROOM-ORIGEN",
                        "equipment": "EQUIP-ORIGEN", "blocks_room": 1,
                        "title": "Revisar aire acondicionado",
                        "starts_at": maintenance_start,
                        "ends_at": maintenance_end, "kind": "Corrective",
                        "assigned_to": "ADMIN-ORIGEN", "cost": "6.00",
                        "stock_entry": "SE-VIGENTE-ORIGEN",
                        "evidence": maintenance_evidence_url,
                        "evidence_file_name": maintenance_evidence_name,
                        "evidence_size": len(maintenance_evidence),
                        "evidence_sha256": sha256(
                            maintenance_evidence).hexdigest()}],
                    "maintenance_parts": [{
                        "name": "PART-DEVUELTA-ORIGEN-" + suffix,
                        "parent": "MAINT-ORIGEN-" + suffix, "idx": 1,
                        "item": "STOCK-ITEM-ORIGEN", "quantity": 1,
                        "cost": "3.00", "status": "Returned",
                        "stock_entry": "SE-DEVUELTA-ORIGEN",
                        "source_returned_entry": {
                            "voucher": "SE-DEVUELTA-ORIGEN",
                            "company": "EMPRESA-ORIGEN",
                            "property": "HOTEL-ORIGEN", "docstatus": 2,
                            "stock_entry_type": "Material Issue"}},
                        {"name": "PART-VIGENTE-ORIGEN-" + suffix,
                         "parent": "MAINT-ORIGEN-" + suffix, "idx": 2,
                         "item": "STOCK-ITEM-ORIGEN", "quantity": 1,
                         "cost": "3.00", "status": "Issued",
                         "stock_entry": maintenance_issue["voucher"],
                         "source_stock_issue": maintenance_issue,
                         "source_stock_issue_sha256": sha256(
                             canonical(maintenance_issue).encode()).hexdigest()},
                        {"name": "PART-VIGENTE-2-ORIGEN-" + suffix,
                         "parent": "MAINT-ORIGEN-" + suffix, "idx": 3,
                         "item": "STOCK-ITEM-ORIGEN", "quantity": 1,
                         "cost": "3.00", "status": "Issued",
                         "stock_entry": maintenance_issue_second["voucher"],
                         "source_stock_issue": maintenance_issue_second,
                         "source_stock_issue_sha256": sha256(
                             canonical(maintenance_issue_second).encode()).hexdigest()}],
                    "allocations": [{"name": "ALLOC-ORIGEN-" + suffix,
                        "status": "Active", "booking": booking_name,
                        "booking_room": line_name, "stay": stay_name,
                        "category": "CAT-ORIGEN", "room": "ROOM-ORIGEN",
                        "rate": "RATE-ORIGEN", "kind": "Stay",
                        "starts_at": arrival, "ends_at": departure,
                        "currency": "NIO", "accepted_amount": "20.00",
                        "quote_snapshot": line_quote,
                        "quote_sha256": sha256(line_quote.encode()).hexdigest()},
                        {"name": "BLOCK-ALLOC-ORIGEN-" + suffix,
                        "status": "Active", "room_block": "BLOCK-ORIGEN-" + suffix,
                        "category": "CAT-ORIGEN", "room": "ROOM-ORIGEN",
                        "kind": "Room Block", "starts_at": block_start,
                        "ends_at": block_end},
                        {"name": "MAINT-ALLOC-ORIGEN-" + suffix,
                        "status": "Active",
                        "maintenance": "MAINT-ORIGEN-" + suffix,
                        "category": "CAT-ORIGEN", "room": "ROOM-ORIGEN",
                        "kind": "Maintenance", "starts_at": maintenance_start,
                        "ends_at": maintenance_end}]},
                "fiscal_history": {"native_documents": [{
                    "name": row["source_name"],
                    "document_type": row["document_type"], "status": row["status"],
                    "posting_date": row["posting_date"],
                    "customer_name": row["buyer_name"], "currency": row["currency"],
                    "total_amount": row["total_amount"], "source_invoice": "",
                    "snapshot_sha256": row["snapshot_sha256"]}, {
                    "name": credit_row["source_name"],
                    "document_type": credit_row["document_type"],
                    "status": credit_row["status"],
                    "posting_date": credit_row["posting_date"],
                    "customer_name": credit_row["buyer_name"],
                    "currency": credit_row["currency"],
                    "total_amount": credit_row["total_amount"],
                    "source_invoice": credit_row["source_invoice"],
                    "snapshot_sha256": credit_row["snapshot_sha256"]}],
                    "pms_documents": []}}],
            "gl_coverage": [],
            "blockers": [{"code": "reverse_transfer_not_implemented"}]}
        inventory_data = canonical(inventory).encode()
        source_hash = sha256(inventory_data).hexdigest()
        manifest_evidence = {"source_key": incident_evidence_key,
            "property": "HOTEL-ORIGEN", "source_company": "EMPRESA-ORIGEN",
            "source_doctype": "HS Incident",
            "source_name": "INC-EVIDENCE-ORIGEN-" + suffix,
            "source_url": incident_evidence_url,
            "file_name": incident_evidence_name,
            "size": len(incident_evidence),
            "sha256": sha256(incident_evidence).hexdigest()}
        manifest_maintenance_evidence = {"source_key": maintenance_evidence_key,
            "property": "HOTEL-ORIGEN", "source_company": "EMPRESA-ORIGEN",
            "source_doctype": "HS Maintenance Order",
            "source_name": "MAINT-ORIGEN-" + suffix,
            "source_url": maintenance_evidence_url,
            "file_name": maintenance_evidence_name,
            "size": len(maintenance_evidence),
            "sha256": sha256(maintenance_evidence).hexdigest()}
        manifest = {"schema_version": 4, "source_site": site,
                    "source_sha256": source_hash,
                    "inventory_sha256": source_hash,
                    "documents": [row, credit_row],
                    "evidence": sorted([manifest_evidence,
                        manifest_maintenance_evidence], key=lambda row: row["source_key"])}
        manifest_data = canonical(manifest).encode()
        manifest_hash = sha256(manifest_data).hexdigest()

        def package(content, evidence_content=incident_evidence,
                maintenance_content=maintenance_evidence):
            name = "hs-erp-fiscal-" + uuid4().hex + ".zip"
            path = Path(frappe.get_site_path("private", "files", name))
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as output:
                output.writestr("manifest.json", manifest_data)
                output.writestr("inventory.json", inventory_data)
                output.writestr("pdf/" + key + ".pdf", content)
                output.writestr("pdf/" + credit_key + ".pdf", credit_pdf)
                output.writestr("evidence/" + incident_evidence_key,
                                evidence_content)
                output.writestr("evidence/" + maintenance_evidence_key,
                                maintenance_content)
            bundle_paths.append(path)
            return name

        name = package(pdf)
        receipt = {"schema_version": 1, "source_site": site,
            "source_sha256": source_hash,
            "manifest_sha256": manifest_hash,
            "bundle_file": name,
            "bundle_sha256": sha256(bundle_paths[-1].read_bytes()).hexdigest(),
            "backup_sha256": "d" * 64}
        receipt_data = canonical(receipt).encode()
        receipt_name = "hs-erp-freeze-" + uuid4().hex + ".json"
        receipt_path = Path(frappe.get_site_path("private", "files",
            receipt_name))
        receipt_path.write_bytes(receipt_data)
        bundle_paths.append(receipt_path)
        receipt_hash = sha256(receipt_data).hexdigest()
        receipt_args = (receipt_name, receipt_hash, name, source_hash,
            manifest_hash, receipt["backup_sha256"])
        if not erp_to_pms_freeze.verify_on_target(*receipt_args)["verified"]:
            frappe.throw("El recibo congelado no verificó el paquete completo")
        try:
            erp_to_pms_freeze.verify_on_target(*receipt_args[:-1], "0" * 64)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("El recibo aceptó otro respaldo de origen")
        original_bundle = bundle_paths[-2].read_bytes()
        try:
            bundle_paths[-2].write_bytes(original_bundle + b"altered")
            try:
                erp_to_pms_freeze.verify_on_target(*receipt_args)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El recibo aceptó un ZIP alterado")
        finally:
            bundle_paths[-2].write_bytes(original_bundle)
        mapping = {"HOTEL-ORIGEN": prop.name}
        result = erp_fiscal_history.import_bundle(name, source_hash,
            manifest_hash, mapping)
        if (result["imported"] != 2 or result["provider_changed"] or
                result["verified_evidence"] != 2):
            frappe.throw("La importación del archivo fiscal no fue aislada")
        again = erp_fiscal_history.import_bundle(name, source_hash,
            manifest_hash, mapping)
        if again["already_present"] != 2 or again["imported"]:
            frappe.throw("El reintento duplicó un documento fiscal")
        mapping = api.erp_to_pms_mapping_template(name, source_hash,
            manifest_hash)
        mapped = mapping["properties"]["HOTEL-ORIGEN"]
        mapped["property"] = prop.name
        mapped["temporary_opening_account"] = temporary.name
        mapped["accounts"]["AR-ORIGEN"] = account.name
        mapped["accounts"]["INCOME-ORIGEN"] = income.name
        mapped["accounts"]["EXPENSE-ORIGEN"] = service_expense.name
        mapped["accounts"]["STOCK-ORIGEN"] = stock_account.name
        mapped["accounts"]["BANK-ORIGEN"] = bank.name
        mapped["accounts"]["AP-ORIGEN"] = payable_account.name
        mapped["accounts"]["AP2-ORIGEN"] = second_payable_account.name
        mapped["accounts"]["GUAR-ORIGEN"] = guarantee_account.name
        mapped["accounts"]["EQUITY-ORIGEN"] = equity.name
        mapped["products"]["SVC-ORIGEN"] = product.name
        mapped["products"]["STOCK-ITEM-ORIGEN"] = stock_product.name
        mapped["customers"]["CUSTOMER-ORIGEN"] = party.name
        mapped["suppliers"]["SUPPLIER-ORIGEN"] = supplier.name
        mapped["warehouses"]["WH-ORIGEN"] = warehouse.name
        mapped["categories"]["CAT-ORIGEN"] = category.name
        mapped["rooms"]["ROOM-ORIGEN"] = room.name
        mapped["rates"]["RATE-ORIGEN"] = rate.name
        mapped["guests"]["GUEST-ORIGEN"] = guest.name
        mapped["travel_agents"]["AGENT-ORIGEN"] = agent.name
        mapped["experiences"]["EXPERIENCE-ORIGEN"] = experience.name
        mapped["laundry_rates"]["LAUNDRY-RATE-ORIGEN"] = laundry_rate.name
        mapped["users"]["ADMIN-ORIGEN"] = "Administrator"
        mapped["equipment"]["EQUIP-ORIGEN"] = equipment.name
        mapping_review = api.erp_to_pms_mapping_review(name, source_hash,
            manifest_hash, mapping)
        if (not mapping_review["mapping_ready"] or
                mapping_review["ready_for_transfer"] or
                mapping_review["fiscal_archive"] !=
                    {"expected": 2, "verified": 2}):
            frappe.throw("El mapa PMS no verificó el archivo importado")
        balance_preview = api.erp_to_pms_balance_preview(name, source_hash,
            manifest_hash, mapping)
        preview_property = balance_preview["properties"][0]
        balances = preview_property["net_balances"]
        if (balance_preview["ready_for_transfer"] or balance_preview["posted"] or
                balance_preview["blockers"] or len(balances) != 9 or
                {(line["account"], line["party"], line["debit"], line["credit"])
                    for line in balances} != {
                    (account.name, party.name, "18.00", "0"),
                    (income.name, None, "0", "29.00"),
                    (stock_account.name, None, "10.00", "0"),
                    (bank.name, None, "26.00", "0"),
                    (payable_account.name, supplier.name, "0", "8.00"),
                    (second_payable_account.name, supplier.name, "0", "2.00"),
                    (guarantee_account.name, None, "0", "5.00"),
                    (equity.name, None, "0", "16.00"),
                    (service_expense.name, None, "6.00", "0")} or
                preview_property["open_receivables"] != 2 or
                preview_property["open_payables"] != 3 or
                preview_property["customer_credits"] != 1 or
                preview_property["stock_positions"][0]["stock_value"] != "10.00" or
                frappe.db.exists("HS Journal", {"property": prop.name})):
            frappe.throw("La vista previa de saldos no conservó importes y tercero")
        transfer_plan = api.erp_to_pms_transfer_plan(name, source_hash,
            manifest_hash, mapping)
        opening = transfer_plan["properties"][0]
        projected_booking_experience = frappe.parse_json(
            opening["operational_rows"]["bookings"][0]["quote_snapshot"])[
                "experiences"][0]
        projected_portal = opening["operational_rows"]["portal_requests"][0]
        projected_portal_experience = frappe.parse_json(
            projected_portal["experiences"])[0]
        projected_portal_quote_experience = frappe.parse_json(
            projected_portal["quote_snapshot"])["experiences"][0]
        if (not transfer_plan["arithmetically_balanced"] or
                not transfer_plan["ready_for_transfer"] or transfer_plan["posted"] or
                opening["temporary_opening_account"] != temporary.name or
                opening["control_total"] != "13.00" or
                opening["temporary_net"] != "0.00" or
                len(opening["opening_receivables"]) != 1 or
                len(opening["opening_customer_credits"]) != 1 or
                len(opening["opening_advances"]) != 1 or
                len(opening["opening_payables"]) != 2 or
                len(opening["opening_supplier_credits"]) != 1 or
                len(opening["opening_guarantees"]) != 1 or
                len(opening["opening_stock"]) != 1 or
                opening["opening_receivables"][0]["party"] != party.name or
                opening["opening_receivables"][0]["folio"] != folio_name or
                opening["opening_receivables"][0]["signed_base_balance"] != "25.00" or
                opening["opening_customer_credits"][0]["signed_base_balance"] != "-4.00" or
                opening["opening_advances"][0]["signed_base_balance"] != "-3.00" or
                opening["opening_payables"][0]["party"] != supplier.name or
                opening["opening_payables"][0]["signed_base_balance"] != "-12.00" or
                opening["opening_supplier_credits"][0]["signed_base_balance"] != "4.00" or
                opening["opening_guarantees"][0]["signed_base_balance"] != "-5.00" or
                opening["opening_guarantees"][0]["customer"] != party.name or
                opening["operational_rows"]["bookings"][0]["customer"] != party.name or
                opening["operational_rows"]["bookings"][0]["travel_agent"] != agent.name or
                frappe.parse_json(opening["operational_rows"]["bookings"][0]
                    ["quote_snapshot"])["lines"][0]["charge_items"]
                    ["lodging_item"] != product.name or
                any(row["experience"] != experience.name or
                    row["pms_product"] != product.name or
                    row["item"] is not None or row["item_price"] is not None
                    for row in (projected_booking_experience,
                        projected_portal_quote_experience)) or
                projected_portal_experience != {"experience": experience.name,
                    "quantity": 1} or
                opening["operational_rows"]["allocations"][0]
                    ["booking_room"] != line_name or
                opening["operational_rows"]["service_requests"][0]
                    ["item"] != product.name or
                opening["operational_rows"]["service_requests"][1]
                    ["warehouse"] != warehouse.name or
                opening["operational_rows"]["cleaning_tasks"][0]
                    ["room"] != room.name or
                opening["operational_rows"]["guest_tickets"][0]
                    ["assigned_to"] != "Administrator" or
                opening["operational_rows"]["ticket_events"][0]
                    ["actor"] != "Administrator" or
                opening["operational_rows"]["experience_orders"][0]
                    ["experience"] != experience.name or
                opening["operational_rows"]["experience_orders"][0]
                    ["pms_product"] != product.name or
                opening["operational_rows"]["experience_orders"][0]
                    ["item"] is not None or
                opening["operational_rows"]["experience_orders"][1]
                    ["accepted_tax_profile"] != service_tax.name or
                opening["operational_rows"]["laundry_orders"][0]
                    ["collected_by"] != "Administrator" or
                opening["operational_rows"]["laundry_items"][0]
                    ["laundry_rate"] != laundry_rate.name or
                opening["operational_rows"]["laundry_items"][0]
                    ["pms_product"] != product.name or
                opening["operational_rows"]["laundry_items"][0]
                    ["item"] is not None or
                frappe.parse_json(opening["operational_rows"]
                    ["service_requests"][2]["opening_stock_issue"])
                    ["expense_account"] != service_expense.name or
                {(line["account"], line["debit"], line["credit"])
                    for line in opening["residual_journal"]} != {
                    (temporary.name, "13.00", "0"),
                    (bank.name, "26.00", "0"),
                    (income.name, "0", "29.00"),
                    (equity.name, "0", "16.00"),
                    (service_expense.name, "6.00", "0")} or
                frappe.db.exists("HS Journal", {"property": prop.name})):
            frappe.throw("El plan inverso no cuadró cartera y cuenta temporal: " +
                         canonical(transfer_plan["blockers"]))
        from hospitality_suite import erp_to_pms_transfer_rehearsal as reverse_rehearsal
        verify_posted = reverse_rehearsal._verify_property
        archive_name = frappe.db.get_value("HS Historical Fiscal Document",
            {"source_key": key}, "name")

        evidence_paths = []

        def verify_visible(opening_prop, expected, stock):
            verify_posted(opening_prop, expected, stock)
            target_booking = frappe.get_doc("HS Booking", booking_name)
            target_stay = frappe.get_doc("HS Stay", stay_name)
            target_folio = frappe.get_doc("HS Folio", folio_name)
            target_charge = frappe.get_doc("HS Charge", "CHG-ORIGEN-" + suffix)
            target_service = frappe.get_doc("HS Service Request",
                "SREQ-ORIGEN-" + suffix)
            target_stock_service = frappe.get_doc("HS Service Request",
                "SREQ-STOCK-ORIGEN-" + suffix)
            target_delivered_service = frappe.get_doc("HS Service Request",
                "SREQ-DELIVERED-ORIGEN-" + suffix)
            target_charged_service = frappe.get_doc("HS Service Request",
                "SREQ-CHARGED-ORIGEN-" + suffix)
            target_cleaning = frappe.get_doc("HS Cleaning Task",
                "CLEAN-ORIGEN-" + suffix)
            target_ticket = frappe.get_doc("HS Guest Ticket",
                "TICKET-ORIGEN-" + suffix)
            target_incident = frappe.get_doc("HS Incident",
                "INC-ORIGEN-" + suffix)
            target_evidence_incident = frappe.get_doc("HS Incident",
                "INC-EVIDENCE-ORIGEN-" + suffix)
            target_maintenance = frappe.get_doc("HS Maintenance Order",
                "MAINT-ORIGEN-" + suffix)
            target_pass = frappe.get_doc("HS Day Pass",
                "PASS-ORIGEN-" + suffix)
            historical_invoice = frappe.db.get_value(
                "HS Historical Fiscal Document", {"property": opening_prop.name,
                    "source_name": pass_financial["invoice"],
                    "source_doctype": "Sales Invoice"}, "name")
            target_evidence_file = frappe.get_doc("File", {
                "file_url": target_evidence_incident.evidence,
                "attached_to_doctype": "HS Incident",
                "attached_to_name": target_evidence_incident.name,
                "is_private": 1})
            evidence_paths.append(Path(target_evidence_file.get_full_path()))
            if (target_evidence_incident.room != room.name or
                    target_evidence_incident.kind != "Damage" or
                    not target_evidence_incident.evidence or
                    evidence_paths[-1].read_bytes() != incident_evidence):
                frappe.throw("La evidencia privada no llegó íntegra")
            target_maintenance_file = frappe.get_doc("File", {
                "file_url": target_maintenance.evidence,
                "attached_to_doctype": "HS Maintenance Order",
                "attached_to_name": target_maintenance.name,
                "is_private": 1})
            evidence_paths.append(Path(target_maintenance_file.get_full_path()))
            if (target_maintenance.room != room.name or
                    not target_maintenance.evidence or
                    evidence_paths[-1].read_bytes() != maintenance_evidence):
                frappe.throw("La evidencia de mantenimiento no llegó íntegra")
            target_ticket_events = frappe.get_all("HS Ticket Event",
                filters={"ticket": target_ticket.name},
                fields=["name", "kind", "actor", "occurred_at"],
                order_by="occurred_at asc,creation asc,name asc")
            target_booked_experience = frappe.get_doc("HS Experience Order",
                "EXPO-BOOKED-" + suffix)
            target_direct_experience = frappe.get_doc("HS Experience Order",
                "EXPO-DIRECT-" + suffix)
            target_laundry = frappe.get_doc("HS Laundry Order",
                "LAUNDRY-ORIGEN-" + suffix)
            target_requested_laundry = frappe.get_doc("HS Laundry Order",
                "LAUNDRY-REQUESTED-" + suffix)
            target_web = frappe.get_doc("HS Portal Request", "WEB-ORIGEN-" + suffix)
            target_booking_experience = frappe.parse_json(
                target_booking.quote_snapshot)["experiences"][0]
            target_web_experiences = frappe.parse_json(
                target_web.experiences)
            target_web_quote_experience = frappe.parse_json(
                target_web.quote_snapshot)["experiences"][0]
            target_block = frappe.get_doc("HS Room Block",
                "BLOCK-ORIGEN-" + suffix)
            target_maintenance = frappe.get_doc("HS Maintenance Order",
                "MAINT-ORIGEN-" + suffix)
            target_allocation = frappe.get_doc("HS Allocation",
                "ALLOC-ORIGEN-" + suffix)
            block_allocation = frappe.get_doc("HS Allocation",
                "BLOCK-ALLOC-ORIGEN-" + suffix)
            maintenance_allocation = frappe.get_doc("HS Allocation",
                "MAINT-ALLOC-ORIGEN-" + suffix)
            if (target_booking.customer != party.name or
                    target_booking.travel_agent != agent.name or
                    len(target_booking.rooms) != 1 or
                    target_booking.rooms[0].name != line_name or
                    target_booking.rooms[0].rate != rate.name or
                    target_stay.booking != booking_name or
                    target_stay.customer != party.name or
                    target_stay.guest != guest.name or
                    len(target_stay.guests) != 1 or
                    target_stay.guests[0].guest != guest.name or
                    frappe.parse_json(target_stay.service_entitlements)[0]
                        ["item"] != product.name or
                    target_folio.stay != stay_name or
                    target_folio.customer != party.name or
                    target_charge.folio != folio_name or
                    target_charge.item != product.name or
                    target_service.status != "In Progress" or
                    target_service.stay != stay_name or
                    target_service.folio != folio_name or
                    target_service.customer != party.name or
                    target_service.item != product.name or
                    Decimal(str(target_service.amount)) != Decimal("3") or
                    target_service.charge or target_service.stock_entry or
                    target_stock_service.status != "Requested" or
                    target_stock_service.item != stock_product.name or
                    target_stock_service.warehouse != warehouse.name or
                    not target_stock_service.included or
                    target_stock_service.charge or target_stock_service.stock_entry or
                    target_delivered_service.status != "Delivered" or
                    target_delivered_service.stock_entry != prior_issue["voucher"] or
                    not target_delivered_service.opening_stock_issue or
                    frappe.parse_json(target_delivered_service.opening_stock_issue)
                        ["voucher"] != prior_issue["voucher"] or
                    target_charged_service.status != "Delivered" or
                    target_charged_service.charge != target_charge.name or
                    target_cleaning.room != room.name or
                    target_cleaning.stay or
                    target_cleaning.source_stay != closed_stay_name or
                    target_cleaning.assigned_to != "Administrator" or
                    target_cleaning.status != "Pending" or
                    target_ticket.stay != stay_name or
                    target_ticket.room != room.name or
                    target_ticket.status != "In Progress" or
                    target_ticket.assigned_to != "Administrator" or
                    [event.kind for event in target_ticket_events] !=
                        ["Created", "Started"] or
                    any(event.actor != "Administrator" for event in
                        target_ticket_events) or
                    target_incident.room != room.name or
                    target_incident.status != "Open" or
                    target_incident.kind != "Lost Property" or
                    target_incident.item != "Mochila negra" or
                    target_pass.customer != party.name or
                    target_pass.guest != guest.name or
                    target_pass.status != "Issued" or
                    target_pass.opening_historical_invoice != historical_invoice or
                    target_pass.pms_receivable or target_pass.payment or
                    frappe.parse_json(target_pass.opening_financial)[
                        "invoice_gl"][0]["account"] != account.name or
                    target_booked_experience.booking != booking_name or
                    target_booked_experience.experience != experience.name or
                    target_booked_experience.pms_product != product.name or
                    target_booked_experience.item or
                    target_direct_experience.booking or
                    target_direct_experience.customer != party.name or
                    target_direct_experience.income_account != income.name or
                    target_direct_experience.accepted_tax_profile !=
                        service_tax.name or
                    target_laundry.status != "Ready" or
                    target_laundry.stay != stay_name or
                    target_laundry.folio != folio_name or
                    target_laundry.collected_by != "Administrator" or
                    len(target_laundry.items) != 1 or
                    target_laundry.items[0].name !=
                        "LAUNDRY-LINE-ORIGEN-" + suffix or
                    target_laundry.items[0].laundry_rate !=
                        laundry_rate.name or
                    target_laundry.items[0].pms_product != product.name or
                    target_laundry.items[0].item or
                    target_requested_laundry.status != "Requested" or
                    target_requested_laundry.items or
                    frappe.db.get_value("HS Room", room.name,
                        "cleaning_status") != "Dirty" or
                    target_web.category != category.name or
                    target_web_experiences != [{"experience": experience.name,
                        "quantity": 1}] or
                    any(row["experience"] != experience.name or
                        row["pms_product"] != product.name or
                        row["item"] is not None or row["item_price"] is not None
                        for row in (target_booking_experience,
                            target_web_quote_experience)) or
                    target_block.room != room.name or
                    target_block.created_by != "Administrator" or
                    block_allocation.room_block != target_block.name or
                    block_allocation.kind != "Room Block" or
                    target_maintenance.equipment != equipment.name or
                    target_maintenance.assigned_to != "Administrator" or
                    target_maintenance.blocks_room != 1 or
                    target_maintenance.stock_entry != "SE-VIGENTE-ORIGEN" or
                    len(target_maintenance.parts) != 3 or
                    target_maintenance.parts[0].item != stock_product.name or
                    target_maintenance.parts[0].status != "Returned" or
                    target_maintenance.parts[0].stock_entry != "SE-DEVUELTA-ORIGEN" or
                    target_maintenance.parts[1].item != stock_product.name or
                    target_maintenance.parts[1].status != "Issued" or
                    target_maintenance.parts[1].stock_entry != "SE-VIGENTE-ORIGEN" or
                    not target_maintenance.parts[1].opening_stock_issue or
                    target_maintenance.parts[2].status != "Issued" or
                    target_maintenance.parts[2].stock_entry != "SE-VIGENTE-ORIGEN" or
                    not target_maintenance.parts[2].opening_stock_issue or
                    maintenance_allocation.maintenance != target_maintenance.name or
                    maintenance_allocation.kind != "Maintenance" or
                    target_allocation.booking_room != line_name or
                    target_allocation.stay != stay_name or
                    target_allocation.room != room.name):
                frappe.throw("La apertura inversa perdió vínculos operativos")
            target_maintenance.parts[1].cost = "99.00"
            try:
                target_maintenance.save(ignore_permissions=True)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El repuesto histórico admitió alterar su costo")
            target_maintenance.reload()
            frappe.db.savepoint("hs_reverse_returned_maintenance_probe")
            try:
                from hospitality_suite import standalone_accounting
                new_issue = api.execute(opening_prop.name,
                    "maintenance_parts", "reverse-maintenance-new-" + suffix,
                    {"order": target_maintenance.name,
                     "modified": str(target_maintenance.modified),
                     "warehouse": warehouse.name,
                     "parts": [{"item": stock_product.name, "quantity": "1"}]})
                continued_order = frappe.get_doc("HS Maintenance Order",
                    target_maintenance.name)
                if (len(continued_order.parts) != 4 or
                        continued_order.parts[0].status != "Returned" or
                        continued_order.parts[1].status != "Issued" or
                        continued_order.parts[2].status != "Issued" or
                        continued_order.parts[3].status != "Issued" or
                        Decimal(str(continued_order.cost)) <= 0):
                    frappe.throw("La orden migrada no admite repuestos nuevos")
                api.execute(opening_prop.name, "maintenance_parts",
                    "reverse-maintenance-return-" + suffix,
                    {"order": continued_order.name,
                     "modified": str(continued_order.modified),
                     "return_entry": new_issue["stock_entry"],
                     "reason": "Repuesto nuevo no utilizado"})
                continued_order.reload()
                if (Decimal(str(continued_order.cost)) != Decimal("6") or
                        [part.status for part in continued_order.parts] !=
                            ["Returned", "Issued", "Issued", "Returned"]):
                    frappe.throw("La devolución PMS alteró el historial trasladado")
                frozen_expense = frappe.get_doc("HS Account",
                    service_expense.name)
                frozen_expense.active = 0
                frozen_expense.save()
                from hospitality_suite import standalone_maintenance_parts
                original_return_one = standalone_maintenance_parts._return_one
                calls = [0]
                def interrupted_return(*args, **kwargs):
                    calls[0] += 1
                    if calls[0] == 2:
                        raise frappe.ValidationError("Fallo simulado en la segunda línea")
                    return original_return_one(*args, **kwargs)
                with patch.object(standalone_maintenance_parts, "_return_one",
                        side_effect=interrupted_return):
                    try:
                        api.execute(opening_prop.name, "maintenance_parts",
                            "reverse-maintenance-rollback-" + suffix,
                            {"order": continued_order.name,
                             "modified": str(continued_order.modified),
                             "return_entry": "SE-VIGENTE-ORIGEN",
                             "reason": "Ensayo de reversión atómica"})
                    except frappe.ValidationError:
                        frappe.clear_messages()
                    else:
                        frappe.throw("La devolución interrumpida se publicó")
                continued_order.reload()
                if (frappe.db.count("HS Stock Movement", {"property": opening_prop.name,
                        "source_doctype": "HS Maintenance Order",
                        "source_name": continued_order.name,
                        "purpose": ["like",
                            "Maintenance Return SE-VIGENTE-ORIGEN/%"]}) or
                        [part.status for part in continued_order.parts] !=
                            ["Returned", "Issued", "Issued", "Returned"]):
                    frappe.throw("El fallo parcial dejó movimientos huérfanos")
                historical_request = {"order": continued_order.name,
                    "modified": str(continued_order.modified),
                    "return_entry": "SE-VIGENTE-ORIGEN",
                    "reason": "Repuesto histórico sin utilizar"}
                historical_key = "reverse-maintenance-old-return-" + suffix
                historical_return = api.execute(opening_prop.name,
                    "maintenance_parts", historical_key, historical_request)
                if api.execute(opening_prop.name, "maintenance_parts",
                        historical_key, historical_request) != historical_return:
                    frappe.throw("El reintento duplicó la devolución del grupo histórico")
                continued_order.reload()
                return_movements = [frappe.get_doc("HS Stock Movement", name)
                    for name in historical_return.get("movements", [])]
                return_lines = [frappe.get_all("HS Journal Line",
                    filters={"parent": movement.journal},
                    fields=["account", "debit", "credit"])
                    for movement in return_movements]
                if (Decimal(str(continued_order.cost)) != 0 or
                        any(part.status != "Returned"
                            for part in continued_order.parts) or
                        len(return_movements) != 2 or
                        any(movement.product != stock_product.name or
                            movement.warehouse != warehouse.name or
                            Decimal(str(movement.quantity_delta)) != 1 or
                            Decimal(str(movement.value_delta)) != 3
                            for movement in return_movements) or
                        any({(line.account, Decimal(str(line.debit)),
                            Decimal(str(line.credit))) for line in lines} != {
                                (stock_account.name, Decimal("3"), Decimal(0)),
                                (service_expense.name, Decimal(0), Decimal("3"))}
                            for lines in return_lines) or
                        Decimal(standalone_accounting.account_currency_balance(
                            opening_prop, stock_account.name)["base_balance"]) != 16 or
                        Decimal(standalone_accounting.account_currency_balance(
                            opening_prop, service_expense.name)["base_balance"]) != 0):
                    frappe.throw("La devolución histórica no invirtió costo e inventario")
                try:
                    api.execute(opening_prop.name, "maintenance_parts",
                        "reverse-maintenance-old-duplicate-" + suffix,
                        {"order": continued_order.name,
                         "modified": str(continued_order.modified),
                         "return_entry": "SE-VIGENTE-ORIGEN",
                         "reason": "Intento de devolución duplicada"})
                except frappe.ValidationError:
                    frappe.clear_messages()
                else:
                    frappe.throw("El repuesto histórico se devolvió dos veces")
            finally:
                frappe.db.rollback(save_point="hs_reverse_returned_maintenance_probe")
            from hospitality_suite import tickets
            from hospitality_suite import standalone_day_pass
            pass_row = next((item for item in standalone_day_pass.snapshot(
                opening_prop.name)["day_passes"] if item["name"] ==
                    target_pass.name), None)
            if (not pass_row or Decimal(str(pass_row["amount"])) != Decimal("25") or
                    pass_row["outstanding"] != "0.00" or
                    not pass_row["invoiced"] or pass_row["can_cancel"]):
                frappe.throw("El Day Pass histórico no aparece como pagado")
            target_pass.notes = "Cambio no autorizado"
            try:
                target_pass.save(ignore_permissions=True)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El Day Pass histórico admitió edición directa")
            frappe.db.savepoint("hs_reverse_day_pass_return_probe")
            try:
                from hospitality_suite import standalone_day_pass
                current_pass = frappe.get_doc("HS Day Pass", target_pass.name)
                credit_series = api.execute(opening_prop.name,
                    "pms_fiscal_series", "reverse-pass-credit-series-" + suffix,
                    {"series_code": "NCP" + suffix[:8] + "-",
                     "document_type": "Credit Note", "start_number": 1,
                     "end_number": 10, "padding": 4})["series"]
                old_income = frappe.get_doc("HS Account", income.name)
                old_income.active = 0
                old_income.save()
                return_data = {"day_pass": current_pass.name,
                    "modified": str(current_pass.modified),
                    "series": credit_series, "method": bank_method,
                    "shift": None, "amount": "25.00",
                    "reference": "PASS-RETURN-" + suffix,
                    "reason": "Devolución completa del acceso histórico"}
                reviewed = api.pms_historical_day_pass_return_quote(
                    opening_prop.name, return_data)
                if (reviewed["base_amount"] != "25.00" or
                        reviewed["debit"] != account.name or
                        reviewed["credit"] != bank.name or
                        reviewed["historical_invoice"] != historical_invoice):
                    frappe.throw("La cotización histórica alteró cuentas o factura")
                returned = api.execute(opening_prop.name,
                    "pms_historical_day_pass_return",
                    "reverse-pass-return-" + suffix,
                    {**return_data, "acceptance": reviewed["acceptance"]})
                if api.execute(opening_prop.name,
                        "pms_historical_day_pass_return",
                        "reverse-pass-return-" + suffix,
                        {**return_data,
                         "acceptance": reviewed["acceptance"]}) != returned:
                    frappe.throw("El reintento duplicó el retorno histórico")
                cancelled_pass = frappe.get_doc("HS Day Pass", target_pass.name)
                note_doc = frappe.get_doc("HS PMS Fiscal Document",
                    returned["credit_note"])
                refund_doc = frappe.get_doc("HS Payment", returned["refund"])
                printed_credit = frappe.get_print(
                    "HS PMS Fiscal Document", note_doc.name,
                    print_format="HS Documento fiscal PMS")
                if (cancelled_pass.status != "Cancelled" or
                        cancelled_pass.opening_credit_note != note_doc.name or
                        cancelled_pass.opening_refund != refund_doc.name or
                        note_doc.historical_source_invoice != historical_invoice or
                        note_doc.historical_day_pass != cancelled_pass.name or
                        note_doc.source_invoice or
                        Decimal(str(note_doc.total_amount)) != Decimal("25") or
                        refund_doc.pms_historical_day_pass != cancelled_pass.name or
                        refund_doc.pms_counter_account != account.name or
                        Decimal(str(refund_doc.base_amount)) != Decimal("25") or
                        not refund_doc.pms_journal or
                        row["document_number"] not in printed_credit):
                    frappe.throw("La devolución histórica perdió nota, reembolso o impresión: " +
                        str({"status": cancelled_pass.status,
                             "credit_link": cancelled_pass.opening_credit_note,
                             "refund_link": cancelled_pass.opening_refund,
                             "historical_source": note_doc.historical_source_invoice,
                             "historical_day_pass": note_doc.historical_day_pass,
                             "source_invoice": note_doc.source_invoice,
                             "credit_amount": str(note_doc.total_amount),
                             "refund_source": refund_doc.pms_historical_day_pass,
                             "refund_account": refund_doc.pms_counter_account,
                             "refund_amount": str(refund_doc.base_amount),
                             "refund_journal": refund_doc.pms_journal,
                             "printed_reference": row["document_number"] in printed_credit}))
                credit_lines = frappe.get_all("HS Journal Line",
                    filters={"parent": note_doc.journal},
                    fields=["account", "party", "debit", "credit"])
                refund_lines = frappe.get_all("HS Journal Line",
                    filters={"parent": refund_doc.pms_journal},
                    fields=["account", "party", "debit", "credit"])
                if ({(row.account, row.party,
                        Decimal(str(row.debit)), Decimal(str(row.credit)))
                        for row in credit_lines} != {
                            (account.name, party.name, Decimal(0), Decimal("25")),
                            (income.name, None, Decimal("20"), Decimal(0)),
                            (guarantee_account.name, None, Decimal("5"), Decimal(0))} or
                    {(row.account, row.party,
                        Decimal(str(row.debit)), Decimal(str(row.credit)))
                        for row in refund_lines} != {
                            (account.name, party.name, Decimal("25"), Decimal(0)),
                            (bank.name, None, Decimal(0), Decimal("25"))}):
                    frappe.throw("Los asientos no revierten la venta y entregan el reembolso")
                report_filters = {"from_date": str(opening_prop.business_date),
                    "to_date": str(opening_prop.business_date)}
                sales = api.pms_report(opening_prop.name, "sales",
                    {**report_filters, "account": income.name})
                historical_rows = [item for item in sales["rows"]
                    if item["reference"] == note_doc.document_number]
                if (len(historical_rows) != 1 or
                        historical_rows[0]["source_type"] !=
                            "Historical Credit Note" or
                        historical_rows[0]["income_account"] != income.name or
                        historical_rows[0]["net_amount"] != "-20.00"):
                    frappe.throw("El reporte omitió la reversión de la cuenta histórica")
                tax_sales = api.pms_report(opening_prop.name, "sales",
                    {**report_filters, "account": guarantee_account.name})
                tax_rows = [item for item in tax_sales["rows"]
                    if item["reference"] == note_doc.document_number]
                if (len(tax_rows) != 1 or
                        tax_rows[0]["tax_amount"] != "-5.00" or
                        tax_rows[0]["total_amount"] != "-5.00"):
                    frappe.throw("El reporte omitió la reversión del impuesto histórico")
                close_snapshot = api.pms_close_preview(opening_prop.name)["snapshot"]
                if (not any(item["name"] == note_doc.name and
                        item["historical_source_invoice"] == historical_invoice
                        for item in close_snapshot["sources"]["fiscal_documents"]) or
                    not any(item["name"] == refund_doc.name and
                        item["pms_historical_day_pass"] == cancelled_pass.name
                        for item in close_snapshot["sources"]["payments"])):
                    frappe.throw("El cierre omitió la nota o reembolso históricos")
                pass_after = next(row for row in standalone_day_pass.snapshot(
                    opening_prop.name)["day_passes"] if row["name"] ==
                    current_pass.name)
                if pass_after["can_return"] or pass_after["status"] != "Cancelled":
                    frappe.throw("El Day Pass devuelto sigue disponible para devolución")
                try:
                    api.pms_historical_day_pass_return_quote(
                        opening_prop.name, return_data)
                except frappe.ValidationError:
                    frappe.clear_messages()
                else:
                    frappe.throw("Se cotizó una segunda devolución del mismo acceso")
            finally:
                frappe.db.rollback(save_point="hs_reverse_day_pass_return_probe")
            frappe.db.savepoint("hs_reverse_day_pass_foreign_return_probe")
            try:
                from hospitality_suite import standalone_accounting
                api.execute(opening_prop.name, "pms_currencies",
                    "reverse-pass-usd-currencies-" + suffix,
                    {"currencies": ["NIO", "USD"]})
                opening_prop.reload()
                with operation(opening_prop):
                    usd_bank = insert("HS Account", opening_prop,
                        organization=opening_prop.organization,
                        account_code="USD-" + suffix[:8],
                        account_name="Banco de reembolsos USD",
                        root_type="Asset", account_type="Bank",
                        account_currency="USD", active=1, is_group=0,
                        is_bank=1)
                    standalone_accounting.post(opening_prop,
                        source_doctype="HS Test Funding",
                        source_name="PASS-USD-" + suffix,
                        purpose="Test Funding", lines=[
                            {"account": usd_bank.name, "debit": "25.00",
                             "credit": "0", "account_currency": "USD",
                             "exchange_rate": "25.00",
                             "debit_in_account_currency": "1.00",
                             "credit_in_account_currency": "0"},
                            {"account": equity.name, "debit": "0",
                             "credit": "25.00"}])
                api.execute(opening_prop.name, "pms_exchange_rate",
                    "reverse-pass-usd-rate-" + suffix,
                    {"from_currency": "USD", "rate": "25.00",
                     "source": "Ensayo de devolución histórica"})
                usd_method = api.execute(opening_prop.name,
                    "pms_payment_method", "reverse-pass-usd-method-" + suffix,
                    {"label": "Banco USD histórico", "account": usd_bank.name})["method"]
                usd_series = api.execute(opening_prop.name,
                    "pms_fiscal_series", "reverse-pass-usd-series-" + suffix,
                    {"series_code": "NCU" + suffix[:8] + "-",
                     "document_type": "Credit Note", "start_number": 1,
                     "end_number": 10, "padding": 4})["series"]
                usd_pass = frappe.get_doc("HS Day Pass", target_pass.name)
                usd_data = {"day_pass": usd_pass.name,
                    "modified": str(usd_pass.modified), "series": usd_series,
                    "method": usd_method, "shift": None, "amount": "1.00",
                    "reference": "PASS-USD-" + suffix,
                    "reason": "Devolución bancaria en moneda extranjera"}
                usd_quote = api.pms_historical_day_pass_return_quote(
                    opening_prop.name, usd_data)
                usd_return = api.execute(opening_prop.name,
                    "pms_historical_day_pass_return",
                    "reverse-pass-usd-return-" + suffix,
                    {**usd_data, "acceptance": usd_quote["acceptance"]})
                usd_refund = frappe.get_doc("HS Payment", usd_return["refund"])
                if (usd_quote["base_amount"] != "25.00" or
                        usd_quote["exchange_rate"] != "25.000000000" or
                        usd_refund.currency != "USD" or
                        Decimal(str(usd_refund.amount)) != Decimal("1.00") or
                        Decimal(str(usd_refund.base_amount)) != Decimal("25.00")):
                    frappe.throw("La devolución extranjera perdió moneda o importe base")
            finally:
                frappe.db.rollback(save_point="hs_reverse_day_pass_foreign_return_probe")
            ticket_detail = tickets.detail(target_ticket.name)
            if ([event["kind"] for event in ticket_detail["events"]] !=
                    ["Created", "Started"] or
                    ticket_detail["ticket"]["stay"] != stay_name):
                frappe.throw("El ticket migrado no conserva su historial")
            noted = tickets.change(opening_prop, {"kind": "note",
                "ticket": target_ticket.name,
                "modified": str(target_ticket.modified),
                "note": "Seguimiento después de la apertura"})
            if (noted["status"] != "In Progress" or
                    tickets.detail(target_ticket.name)["total_events"] != 3):
                frappe.throw("El ticket migrado no admite seguimiento PMS")
            from hospitality_suite import linen
            frappe.db.savepoint("hs_reverse_incident_resolution_probe")
            try:
                resolved = linen.incident(opening_prop, {
                    "incident": target_incident.name,
                    "modified": str(target_incident.modified),
                    "resolve": 1,
                    "resolution": "Objeto entregado al propietario"})
                if (resolved["status"] != "Resolved" or
                        frappe.db.get_value("HS Incident",
                            target_incident.name, "resolved_by") !=
                                "Administrator"):
                    frappe.throw("La incidencia trasladada no admite resolución PMS")
            finally:
                frappe.db.rollback(save_point="hs_reverse_incident_resolution_probe")
            frappe.db.savepoint("hs_reverse_portal_experience_probe")
            try:
                conversion = {"portal_request": target_web.name,
                    "customer": party.name, "guest": guest.name}
                quoted_web = api.preview(opening_prop.name, conversion,
                    "convert_portal")
                converted = api.execute(opening_prop.name, "convert_portal",
                    "reverse-portal-experience-" + suffix,
                    {**conversion, "acceptance": quoted_web["acceptance"]})
                web_booking = frappe.get_doc("HS Booking",
                    converted["booking"])
                web_orders = frappe.get_all("HS Experience Order",
                    filters={"booking": web_booking.name},
                    fields=["experience", "pms_product", "quantity"])
                if (web_booking.channel != "Web" or
                        len(web_orders) != 1 or
                        web_orders[0].experience != experience.name or
                        web_orders[0].pms_product != product.name or
                        Decimal(str(web_orders[0].quantity)) != 1):
                    frappe.throw("La solicitud web migrada perdió su experiencia")
            finally:
                frappe.db.rollback(save_point="hs_reverse_portal_experience_probe")
            from hospitality_suite import travel_experiences
            frappe.db.savepoint("hs_reverse_experience_delivery_probe")
            try:
                delivered_experience = travel_experiences.update_order(
                    opening_prop, {"order": target_booked_experience.name,
                        "modified": str(target_booked_experience.modified),
                        "status": "Delivered", "stay": stay_name,
                        "folio": folio_name})
                if (delivered_experience["status"] != "Delivered" or
                        not delivered_experience["charge"] or
                        frappe.db.get_value("HS Charge",
                            delivered_experience["charge"], "item") != product.name):
                    frappe.throw("La experiencia migrada no llegó al folio PMS")
                direct_quote = travel_experiences.direct_delivery_quote(
                    opening_prop, {"order": target_direct_experience.name,
                        "receivable_account": account.name})
                delivered_direct = travel_experiences.update_direct_order(
                    opening_prop, {"order": target_direct_experience.name,
                        "modified": str(target_direct_experience.modified),
                        "status": "Delivered", "receivable_account": account.name,
                        "acceptance": direct_quote["acceptance"]})
                if (delivered_direct["status"] != "Delivered" or
                        not delivered_direct["pms_receivable"]):
                    frappe.throw("La experiencia directa perdió su importe aceptado")
            finally:
                frappe.db.rollback(save_point="hs_reverse_experience_delivery_probe")
            from hospitality_suite import guest_laundry
            frappe.db.savepoint("hs_reverse_laundry_delivery_probe")
            try:
                delivered_laundry = guest_laundry.deliver(opening_prop,
                    {"order": target_laundry.name,
                     "modified": str(target_laundry.modified)})
                charged_laundry = frappe.get_doc("HS Laundry Order",
                    target_laundry.name)
                laundry_charge = frappe.get_doc("HS Charge",
                    charged_laundry.items[0].charge)
                if (delivered_laundry["status"] != "Delivered" or
                        Decimal(str(delivered_laundry["billed_total"])) != 3 or
                        laundry_charge.item != product.name or
                        Decimal(str(laundry_charge.amount)) != 3):
                    frappe.throw("La lavandería migrada no llegó al folio PMS")
            finally:
                frappe.db.rollback(save_point="hs_reverse_laundry_delivery_probe")
            from hospitality_suite import housekeeping
            housekeeping.update_cleaning(opening_prop, {
                "task": target_cleaning.name,
                "modified": str(target_cleaning.modified),
                "status": "In Progress"})
            target_cleaning.reload()
            if (target_cleaning.status != "In Progress" or
                    frappe.db.get_value("HS Room", room.name,
                        "cleaning_status") != "Cleaning"):
                frappe.throw("La tarea migrada no pudo iniciar limpieza")
            checklist = {"baño": True, "cama": True, "minibar": True,
                         "superficies": True}
            housekeeping.update_cleaning(opening_prop, {
                "task": target_cleaning.name,
                "modified": str(target_cleaning.modified),
                "status": "Inspection", "checklist": checklist})
            target_cleaning.reload()
            if (target_cleaning.status != "Inspection" or
                    frappe.db.get_value("HS Room", room.name,
                        "cleaning_status") != "Inspection"):
                frappe.throw("La tarea migrada no pudo pasar a inspección")
            housekeeping.update_cleaning(opening_prop, {
                "task": target_cleaning.name,
                "modified": str(target_cleaning.modified),
                "status": "Completed", "checklist": checklist})
            if (frappe.db.get_value("HS Room", room.name,
                    "cleaning_status") != "Clean"):
                frappe.throw("La tarea migrada no pudo completarse")
            target_delivered_service.opening_stock_issue = canonical({
                **frappe.parse_json(target_delivered_service.opening_stock_issue),
                "cost": "5"})
            try:
                target_delivered_service.save()
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se permitió alterar el costo de una salida histórica")
            target_delivered_service.reload()
            target_delivered_service.stock_entry = "MAT-STE-AJENO"
            try:
                target_delivered_service.save()
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se permitió sustituir la salida histórica original")
            target_delivered_service.reload()
            from hospitality_suite import standalone_services
            frappe.db.savepoint("hs_reverse_service_delivery_probe")
            try:
                delivered = standalone_services.update(opening_prop, {
                    "service": target_service.name,
                    "modified": str(target_service.modified),
                    "status": "Delivered"})
                issued = standalone_services.update(opening_prop, {
                    "service": target_stock_service.name,
                    "modified": str(target_stock_service.modified),
                    "status": "Delivered"})
                returned = standalone_services.update(opening_prop, {
                    "service": target_delivered_service.name,
                    "modified": str(target_delivered_service.modified),
                    "status": "Returned", "reason": "Devolución tras el corte"})
                reversed_charge = standalone_services.update(opening_prop, {
                    "service": target_charged_service.name,
                    "modified": str(target_charged_service.modified),
                    "status": "Returned", "reason": "Servicio cancelado tras el corte"})
                accepted_charge = frappe.get_doc("HS Charge", delivered["charge"])
                movement = frappe.get_doc("HS Stock Movement",
                    issued["stock_movement"])
                restored = frappe.get_doc("HS Stock Movement",
                    returned["return_stock_movement"])
                return_lines = frappe.get_all("HS Journal Line",
                    filters={"parent": restored.journal},
                    fields=["account", "debit", "credit"])
                if (accepted_charge.folio != folio_name or
                        accepted_charge.item != product.name or
                        Decimal(str(accepted_charge.amount)) != Decimal("3") or
                        accepted_charge.status != "Pending" or
                        issued["charge"] or
                        movement.product != stock_product.name or
                        movement.warehouse != warehouse.name or
                        movement.direction != "Issue" or
                        restored.direction != "Receipt" or
                        reversed_charge["charge"] != target_charge.name or
                        frappe.db.get_value("HS Charge", target_charge.name,
                            "status") != "Reversed" or
                        restored.warehouse != warehouse.name or
                        Decimal(str(restored.value_delta)) != Decimal("4") or
                        {(line.account, Decimal(str(line.debit)),
                          Decimal(str(line.credit))) for line in return_lines} != {
                            (stock_account.name, Decimal("4"), Decimal(0)),
                            (service_expense.name, Decimal(0), Decimal("4"))}):
                    frappe.throw("La solicitud migrada no permitió entregar sin duplicar el cargo")
            finally:
                frappe.db.rollback(save_point="hs_reverse_service_delivery_probe")
            visible = api.pms_receivables(opening_prop.name)["receivables"]
            imported = next((item for item in visible if item["reference"] ==
                row["source_name"]), None)
            if (not imported or imported["opening_source_name"] != row["source_name"] or
                    imported["historical_document"] != archive_name or
                    imported["folio"] != folio_name or
                    imported["outstanding"] != "25.00"):
                frappe.throw("La cartera migrada no enlaza su PDF fiscal en la API")
            opening_credits = api.pms_receivables(opening_prop.name)["opening_credits"]["credits"]
            note = next((item for item in opening_credits if item["opening_source_name"] ==
                credit_row["source_name"]), None)
            advance = next((item for item in opening_credits if item["opening_source_name"] ==
                "PE-" + suffix), None)
            archived_note = frappe.db.get_value("HS Historical Fiscal Document",
                {"source_key": credit_key}, "name")
            if (not note or not advance or note["available"] != "4.00" or
                    advance["available"] != "3.00" or
                    note["historical_document"] != archived_note):
                frappe.throw("Los créditos iniciales no conservan saldos y copia fiscal")
            guarantees = api.pms_receivables(opening_prop.name)["opening_guarantees"]
            guarantee = next((item for item in guarantees if item["opening_source_name"] ==
                "HS-GUAR-" + suffix), None)
            if (not guarantee or guarantee["customer"] != party.name or
                    guarantee["available"] != "5.00" or
                    guarantee["source_folio"] != "FOL-ORIGEN-" + suffix or
                    not frappe.db.exists("HS Folio", guarantee["source_folio"]) or
                    guarantee["liability_account"] != guarantee_account.name or
                    frappe.db.exists("HS Payment", {"property": opening_prop.name,
                        "kind": "Guarantee", "status": "Posted"})):
                frappe.throw("La garantía de apertura creó un cobro o perdió su origen")
            frappe.db.savepoint("hs_reverse_imported_invoice_guarantee_probe")
            try:
                direct_data = {"guarantee": guarantee["name"],
                    "receivable": imported["name"], "amount": "1.00",
                    "reason": "Aplicar garantía a factura abierta migrada"}
                direct_quote = api.pms_opening_guarantee_apply_quote(
                    opening_prop.name, direct_data)
                direct_applied = api.execute(opening_prop.name,
                    "pms_apply_opening_guarantee",
                    "reverse-direct-guarantee-" + suffix,
                    {**direct_data, "acceptance": direct_quote["acceptance"]})
                if (direct_applied["guarantee_available"] != "4.00" or
                        direct_applied["receivable_outstanding"] != "24.00" or
                        frappe.db.get_value("HS PMS Receivable",
                            imported["name"], "folio") != folio_name):
                    frappe.throw("La garantía no se aplicó a la factura abierta del folio")
            finally:
                frappe.db.rollback(save_point="hs_reverse_imported_invoice_guarantee_probe")
            try:
                api.execute(opening_prop.name, "pms_reverse_journal",
                    "reverse-opening-guarantee-journal-" + suffix,
                    {"journal": frappe.db.get_value("HS PMS Opening Guarantee",
                        guarantee["name"], "journal"),
                     "reason": "No revertir el pasivo fuera de su flujo"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se revirtió directamente la garantía inicial")
            frappe.db.savepoint("hs_reverse_guarantee_application_probe")
            try:
                folio_data = {"folio": folio_name,
                    "receivable_account": account.name}
                folio_quote = api.pms_folio_quote(opening_prop.name,
                    folio_data)
                billed = api.execute(opening_prop.name, "pms_bill_folio",
                    "reverse-guarantee-folio-" + suffix,
                    {**folio_data, "acceptance": folio_quote["acceptance"]})
                target_receivable = billed["receivables"][0]["receivable"]
                original_due = Decimal(str(frappe.db.get_value(
                    "HS PMS Receivable", target_receivable, "amount")))
                application_data = {"guarantee": guarantee["name"],
                    "receivable": target_receivable, "amount": "1.00",
                    "reason": "Aplicar garantía del folio migrado"}
                try:
                    api.pms_opening_guarantee_apply_quote(other_prop.name,
                        application_data)
                except frappe.PermissionError:
                    frappe.clear_messages()
                else:
                    frappe.throw("Otro hotel pudo aplicar la garantía")
                application_quote = api.pms_opening_guarantee_apply_quote(
                    opening_prop.name, application_data)
                applied_guarantee = api.execute(opening_prop.name,
                    "pms_apply_opening_guarantee",
                    "reverse-guarantee-apply-" + suffix,
                    {**application_data,
                     "acceptance": application_quote["acceptance"]})
                if (applied_guarantee["guarantee_available"] != "4.00" or
                        Decimal(applied_guarantee["receivable_outstanding"]) !=
                        original_due - Decimal("1") or
                        api.execute(opening_prop.name,
                            "pms_apply_opening_guarantee",
                            "reverse-guarantee-apply-" + suffix,
                            {**application_data,
                             "acceptance": application_quote["acceptance"]}) !=
                        applied_guarantee):
                    frappe.throw("Aplicación de garantía no fue idempotente")
                application_lines = frappe.get_all("HS Journal Line",
                    filters={"parent": applied_guarantee["journal"]},
                    fields=["account", "party", "debit", "credit"])
                if {(line.account, line.party, Decimal(str(line.debit)),
                     Decimal(str(line.credit))) for line in application_lines} != {
                        (guarantee_account.name, None, Decimal("1"), Decimal(0)),
                        (account.name, party.name, Decimal(0), Decimal("1"))}:
                    frappe.throw("Aplicación de garantía no concilia")
                reversed_guarantee = api.execute(opening_prop.name,
                    "pms_unapply_opening_guarantee",
                    "reverse-guarantee-unapply-" + suffix,
                    {"allocation": applied_guarantee["allocation"],
                     "amount": "0.40", "reason": "Corrección parcial"})
                if (reversed_guarantee["guarantee_available"] != "4.40" or
                        Decimal(reversed_guarantee["receivable_outstanding"]) !=
                        original_due - Decimal("0.60")):
                    frappe.throw("Reversión parcial de garantía no concilia")
                from frappe.utils import getdate
                from hospitality_suite import portfolio, standalone_reports
                reported = standalone_reports._receivables(opening_prop,
                    getdate(opening_prop.business_date), party.name, 0, 200)
                target_row = next((row for row in reported["rows"]
                    if row["name"] == target_receivable), None)
                portfolio_rows = portfolio._pms_receivables(opening_prop,
                    getdate(opening_prop.business_date))
                if (not target_row or
                        Decimal(target_row["outstanding"]) !=
                        original_due - Decimal("0.60") or
                        sum(Decimal(str(row.receivable)) for row in portfolio_rows) <
                        original_due - Decimal("0.60")):
                    frappe.throw("Reportes de cartera discrepan tras revertir garantía")
                from hospitality_suite import standalone_closing
                closing_snapshot = standalone_closing.build(opening_prop)
                guarantee_movements = [row for row in
                    closing_snapshot["sources"]["opening_guarantee_applications"]
                    if row["opening_guarantee"] == guarantee["name"]]
                if (len(guarantee_movements) != 2 or
                        {row["kind"] for row in guarantee_movements} != {
                            "Opening Guarantee Applied", "Opening Guarantee Reversed"}):
                    frappe.throw("El cierre omitió la aplicación de garantía")
                try:
                    api.pms_opening_guarantee_refund_quote(opening_prop.name,
                        {"guarantee": guarantee["name"], "method": bank_method,
                         "amount": "4.50", "reference": "EXCESO-" + suffix,
                         "reason": "No devolver una garantía aplicada"})
                except frappe.ValidationError:
                    frappe.clear_messages()
                else:
                    frappe.throw("Se devolvió saldo de garantía ya aplicado")
                try:
                    api.execute(opening_prop.name,
                        "pms_unapply_opening_guarantee",
                        "reverse-guarantee-overunapply-" + suffix,
                        {"allocation": applied_guarantee["allocation"],
                         "amount": "0.61", "reason": "Exceso"})
                except frappe.ValidationError:
                    frappe.clear_messages()
                else:
                    frappe.throw("Se revirtió más que la aplicación")
            finally:
                frappe.db.rollback(save_point="hs_reverse_guarantee_application_probe")
            guarantee_refund_data = {"guarantee": guarantee["name"],
                "method": bank_method, "amount": "2.00",
                "reference": "GUAR-REF-" + suffix,
                "reason": "Devolución parcial de garantía histórica"}
            try:
                api.pms_opening_guarantee_refund_quote(other_prop.name,
                    guarantee_refund_data)
            except frappe.PermissionError:
                frappe.clear_messages()
            else:
                frappe.throw("Otro hotel pudo devolver la garantía")
            guarantee_quote = api.pms_opening_guarantee_refund_quote(
                opening_prop.name, guarantee_refund_data)
            if (guarantee_quote["base_amount"] != "2.00" or
                    guarantee_quote["available_after"] != "3.00"):
                frappe.throw("La cotización de la garantía no conservó su pasivo")
            guarantee_refund = api.execute(opening_prop.name,
                "pms_refund_opening_guarantee", "reverse-guarantee-refund-" + suffix,
                {**guarantee_refund_data,
                 "acceptance": guarantee_quote["acceptance"]})
            if (guarantee_refund["guarantee_available"] != "3.00" or
                    frappe.db.get_value("HS Payment", guarantee_refund["payment"],
                        "source_payment")):
                frappe.throw("La devolución no conservó el origen sin cobro ficticio")
            if api.execute(opening_prop.name,
                    "pms_refund_opening_guarantee", "reverse-guarantee-refund-" + suffix,
                    {**guarantee_refund_data,
                     "acceptance": guarantee_quote["acceptance"]}) != guarantee_refund:
                frappe.throw("El reintento duplicó la devolución de garantía")
            guarantee_lines = frappe.get_all("HS Journal Line",
                filters={"parent": guarantee_refund["journal"]},
                fields=["account", "party", "debit", "credit"])
            if {(line.account, line.party, Decimal(str(line.debit)),
                 Decimal(str(line.credit))) for line in guarantee_lines} != {
                    (guarantee_account.name, None, Decimal("2"), Decimal(0)),
                    (bank.name, None, Decimal(0), Decimal("2"))}:
                frappe.throw("La devolución no debitó la garantía contra banco")
            try:
                api.pms_opening_guarantee_refund_quote(opening_prop.name,
                    {**guarantee_refund_data, "amount": "4.00",
                     "reference": "GUAR-EXCESS-" + suffix})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se devolvió más que el saldo de garantía")
            try:
                api.execute(opening_prop.name, "pms_reverse_journal",
                    "reverse-opening-credit-journal-" + suffix,
                    {"journal": frappe.db.get_value("HS PMS Opening Credit",
                        note["name"], "journal"),
                     "reason": "No revertir fuera del flujo de apertura"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se revirtió directamente el crédito inicial")
            apply_data = {"credit": note["name"], "receivable": imported["name"],
                "amount": "2.00", "reason": "Aplicar nota histórica"}
            apply_quote = api.pms_opening_credit_apply_quote(opening_prop.name,
                apply_data)
            if apply_quote["journal_required"] or apply_quote["outstanding_after"] != "23.00":
                frappe.throw("La aplicación en la misma cartera duplicó un asiento")
            applied = api.execute(opening_prop.name, "pms_apply_opening_credit",
                "reverse-note-apply-" + suffix,
                {**apply_data, "acceptance": apply_quote["acceptance"]})
            if (applied["journal"] or applied["credit_available"] != "2.00" or
                    api.pms_receivables(opening_prop.name)["receivables"][0]
                    ["outstanding"] != "23.00"):
                frappe.throw("La nota histórica no redujo la cuenta por cobrar")
            if api.execute(opening_prop.name, "pms_apply_opening_credit",
                    "reverse-note-apply-" + suffix,
                    {**apply_data, "acceptance": apply_quote["acceptance"]}) != applied:
                frappe.throw("La aplicación reintentada duplicó el crédito")
            undone = api.execute(opening_prop.name, "pms_unapply_opening_credit",
                "reverse-note-unapply-" + suffix,
                {"allocation": applied["allocation"], "amount": "1.00",
                 "reason": "Corrección parcial"})
            if (undone["credit_available"] != "3.00" or
                    undone["receivable_outstanding"] != "24.00"):
                frappe.throw("La reversión parcial no restituyó el saldo")
            fresh = api.execute(opening_prop.name, "pms_receivable",
                "reverse-second-ar-" + suffix,
                {"party": party.name, "reference": "NEW-AR-" + suffix,
                 "description": "Cargo en otra cartera", "amount": "2.00",
                 "receivable_account": second_receivable_account.name,
                 "income_account": income.name})
            cross_data = {"credit": note["name"],
                "receivable": fresh["receivable"], "amount": "1.00",
                "reason": "Traslado entre cuentas de cartera"}
            cross_quote = api.pms_opening_credit_apply_quote(opening_prop.name,
                cross_data)
            if (not cross_quote["journal_required"] or
                    cross_quote["debit"] != account.name or
                    cross_quote["credit"] != second_receivable_account.name):
                frappe.throw("El crédito entre cuentas omitió su traspaso")
            crossed = api.execute(opening_prop.name, "pms_apply_opening_credit",
                "reverse-cross-apply-" + suffix,
                {**cross_data, "acceptance": cross_quote["acceptance"]})
            if (not crossed["journal"] or crossed["credit_available"] != "2.00" or
                    crossed["receivable_outstanding"] != "1.00"):
                frappe.throw("El traspaso entre cuentas no concilió el saldo")
            cross_reversed = api.execute(opening_prop.name,
                "pms_unapply_opening_credit", "reverse-cross-unapply-" + suffix,
                {"allocation": crossed["allocation"], "amount": "1.00",
                 "reason": "Revertir traspaso de cartera"})
            if (cross_reversed["credit_available"] != "3.00" or
                    cross_reversed["receivable_outstanding"] != "2.00"):
                frappe.throw("El traspaso inverso no restituyó las cuentas")
            note_refund_data = {"credit": note["name"], "method": bank_method,
                "amount": "3.00", "reference": "CN-REF-" + suffix,
                "reason": "Devolver nota histórica"}
            note_refund_quote = api.pms_opening_credit_refund_quote(
                opening_prop.name, note_refund_data)
            if note_refund_quote["available_after"] != "0.00":
                frappe.throw("La devolución no calculó el remanente de la nota")
            note_refund = api.execute(opening_prop.name, "pms_refund_opening_credit",
                "reverse-note-refund-" + suffix,
                {**note_refund_data, "acceptance": note_refund_quote["acceptance"]})
            if api.execute(opening_prop.name, "pms_refund_opening_credit",
                    "reverse-note-refund-" + suffix,
                    {**note_refund_data,
                     "acceptance": note_refund_quote["acceptance"]}) != note_refund:
                frappe.throw("El reintento duplicó la devolución del crédito")
            refund_lines = frappe.get_all("HS Journal Line",
                filters={"parent": note_refund["journal"]},
                fields=["account", "party", "debit", "credit"])
            if {(line.account, line.party, Decimal(str(line.debit)),
                 Decimal(str(line.credit))) for line in refund_lines} != {
                    (account.name, party.name, Decimal("3"), Decimal(0)),
                    (bank.name, None, Decimal(0), Decimal("3"))}:
                frappe.throw("La devolución de la nota no debitó cartera contra banco")
            advance_data = {"credit": advance["name"],
                "receivable": imported["name"], "amount": "2.00",
                "reason": "Aplicar anticipo histórico"}
            advance_quote = api.pms_opening_credit_apply_quote(opening_prop.name,
                advance_data)
            advance_applied = api.execute(opening_prop.name,
                "pms_apply_opening_credit", "reverse-advance-apply-" + suffix,
                {**advance_data, "acceptance": advance_quote["acceptance"]})
            if (advance_applied["credit_available"] != "1.00" or
                    advance_applied["receivable_outstanding"] != "22.00"):
                frappe.throw("El anticipo trasladado no se aplicó parcialmente")
            advance_refund_data = {"credit": advance["name"],
                "method": bank_method, "amount": "1.00",
                "reference": "ADV-REF-" + suffix,
                "reason": "Devolver remanente de anticipo"}
            advance_refund_quote = api.pms_opening_credit_refund_quote(
                opening_prop.name, advance_refund_data)
            advance_refund = api.execute(opening_prop.name,
                "pms_refund_opening_credit", "reverse-advance-refund-" + suffix,
                {**advance_refund_data,
                 "acceptance": advance_refund_quote["acceptance"]})
            if advance_refund["credit_available"] != "0.00":
                frappe.throw("El anticipo aún conserva un saldo devuelto")
            frappe.set_user("Guest")
            try:
                try:
                    api.pms_opening_credit_apply_quote(opening_prop.name, advance_data)
                except frappe.PermissionError:
                    frappe.clear_messages()
                else:
                    frappe.throw("Un visitante consultó créditos privados")
            finally:
                frappe.set_user("Administrator")
            try:
                api.pms_opening_credit_apply_quote(opening_prop.name,
                    {**advance_data, "amount": "0.01"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se aplicó un anticipo agotado")
            payables = api.pms_purchase_snapshot(opening_prop.name)["opening_payables"]
            opened = next((item for item in payables if item["opening_source_name"] ==
                "PINV-" + suffix), None)
            if not opened or opened["outstanding"] != "12.00":
                frappe.throw("La deuda inicial no es visible al proveedor")
            supplier_credits = api.pms_purchase_snapshot(opening_prop.name)[
                "opening_supplier_credits"]
            supplier_credit = next((item for item in supplier_credits["credits"]
                if item["opening_source_name"] == "PCN-" + suffix), None)
            if not supplier_credit or supplier_credit["available"] != "4.00":
                frappe.throw("El crédito inicial del proveedor no conserva su saldo")
            try:
                api.execute(opening_prop.name, "pms_reverse_journal",
                    "reverse-vendor-opening-" + suffix,
                    {"journal": frappe.db.get_value("HS PMS Opening Supplier Credit",
                        supplier_credit["name"], "journal"),
                     "reason": "No revertir fuera del flujo"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se revirtió directamente el crédito inicial del proveedor")
            try:
                api.pms_opening_supplier_credit_apply_quote(other_prop.name,
                    {"credit": supplier_credit["name"], "target_type": "Opening Payable",
                     "target": opened["name"], "amount": "1.00", "reason": "Otro hotel"})
            except frappe.PermissionError:
                frappe.clear_messages()
            else:
                frappe.throw("Otro hotel pudo consultar el crédito del proveedor")
            second_opened = next((item for item in payables if
                item["opening_source_name"] == "PINV2-" + suffix), None)
            if not second_opened or second_opened["outstanding"] != "2.00":
                frappe.throw("La segunda cuenta por pagar no está disponible")
            cross_supplier_data = {"credit": supplier_credit["name"],
                "target_type": "Opening Payable", "target": second_opened["name"],
                "amount": "1.00", "reason": "Traspasar crédito a otro pasivo"}
            cross_supplier_quote = api.pms_opening_supplier_credit_apply_quote(
                opening_prop.name, cross_supplier_data)
            if (not cross_supplier_quote["journal_required"] or
                    cross_supplier_quote["target_account"] != second_payable_account.name or
                    cross_supplier_quote["source_account"] != payable_account.name):
                frappe.throw("El traspaso entre pasivos omitió su asiento")
            crossed_supplier = api.execute(opening_prop.name,
                "pms_apply_opening_supplier_credit", "reverse-vendor-cross-" + suffix,
                {**cross_supplier_data,
                 "acceptance": cross_supplier_quote["acceptance"]})
            cross_lines = frappe.get_all("HS Journal Line",
                filters={"parent": crossed_supplier["journal"]},
                fields=["account", "party", "debit", "credit"])
            if {(line.account, line.party, Decimal(str(line.debit)),
                 Decimal(str(line.credit))) for line in cross_lines} != {
                    (second_payable_account.name, supplier.name, Decimal("1"), Decimal(0)),
                    (payable_account.name, supplier.name, Decimal(0), Decimal("1"))}:
                frappe.throw("El traspaso entre pasivos no concilió")
            cross_unapplied = api.execute(opening_prop.name,
                "pms_unapply_opening_supplier_credit",
                "reverse-vendor-cross-unapply-" + suffix,
                {"allocation": crossed_supplier["allocation"], "amount": "1.00",
                 "reason": "Revertir traspaso entre pasivos"})
            if (not cross_unapplied["journal"] or
                    cross_unapplied["credit_available"] != "4.00" or
                    cross_unapplied["target_outstanding"] != "2.00"):
                frappe.throw("El traspaso inverso no restituyó los saldos")
            purchase_data = {"supplier": supplier.name,
                "supplier_reference": "NEW-PINV-" + suffix,
                "product": stock_product.name, "warehouse": warehouse.name,
                "quantity": "1", "invoice_currency": "NIO",
                "invoice_amount": "2.00", "recoverable_tax": "0",
                "payable_account": second_payable_account.name}
            purchase_quote = api.pms_purchase_quote(opening_prop.name, purchase_data)
            new_purchase = api.execute(opening_prop.name, "pms_receive_purchase",
                "reverse-vendor-real-purchase-" + suffix,
                {**purchase_data, "acceptance": purchase_quote["acceptance"]})
            stock_before_credit = frappe.db.count("HS Stock Movement",
                {"property": opening_prop.name})
            purchase_apply_data = {"credit": supplier_credit["name"],
                "target_type": "Purchase", "target": new_purchase["purchase"],
                "amount": "1.00", "reason": "Compensar compra PMS con crédito histórico"}
            purchase_apply_quote = api.pms_opening_supplier_credit_apply_quote(
                opening_prop.name, purchase_apply_data)
            purchase_applied = api.execute(opening_prop.name,
                "pms_apply_opening_supplier_credit",
                "reverse-vendor-purchase-apply-" + suffix,
                {**purchase_apply_data,
                 "acceptance": purchase_apply_quote["acceptance"]})
            if (not purchase_applied["journal"] or
                    purchase_applied["target_outstanding"] != "1.00" or
                    frappe.db.count("HS Stock Movement",
                        {"property": opening_prop.name}) != stock_before_credit):
                frappe.throw("La compensación de compra alteró inventario o pasivo")
            purchase_unapplied = api.execute(opening_prop.name,
                "pms_unapply_opening_supplier_credit",
                "reverse-vendor-purchase-unapply-" + suffix,
                {"allocation": purchase_applied["allocation"], "amount": "1.00",
                 "reason": "Restituir crédito y compra"})
            if (purchase_unapplied["credit_available"] != "4.00" or
                    purchase_unapplied["target_outstanding"] != "2.00"):
                frappe.throw("La compra no recuperó el saldo tras la reversión")
            credit_apply_data = {"credit": supplier_credit["name"],
                "target_type": "Opening Payable", "target": opened["name"],
                "amount": "2.00", "reason": "Compensar nota del proveedor"}
            credit_apply_quote = api.pms_opening_supplier_credit_apply_quote(
                opening_prop.name, credit_apply_data)
            if (credit_apply_quote["journal_required"] or
                    credit_apply_quote["outstanding_after"] != "10.00"):
                frappe.throw("La compensación en la misma cuenta duplicó un asiento")
            supplier_applied = api.execute(opening_prop.name,
                "pms_apply_opening_supplier_credit", "reverse-vendor-apply-" + suffix,
                {**credit_apply_data, "acceptance": credit_apply_quote["acceptance"]})
            if (supplier_applied["journal"] or
                    supplier_applied["credit_available"] != "2.00" or
                    supplier_applied["target_outstanding"] != "10.00" or
                    api.execute(opening_prop.name,
                        "pms_apply_opening_supplier_credit",
                        "reverse-vendor-apply-" + suffix,
                        {**credit_apply_data,
                         "acceptance": credit_apply_quote["acceptance"]}) != supplier_applied):
                frappe.throw("La aplicación al proveedor no fue idempotente")
            supplier_unapplied = api.execute(opening_prop.name,
                "pms_unapply_opening_supplier_credit",
                "reverse-vendor-unapply-" + suffix,
                {"allocation": supplier_applied["allocation"], "amount": "1.00",
                 "reason": "Corrección parcial de compensación"})
            if (supplier_unapplied["credit_available"] != "3.00" or
                    supplier_unapplied["target_outstanding"] != "11.00"):
                frappe.throw("La reversión parcial no restituyó el crédito")
            supplier_refund_data = {"credit": supplier_credit["name"],
                "method": bank_method, "amount": "3.00",
                "reference": "PCN-REF-" + suffix,
                "reason": "Reintegro bancario de nota histórica"}
            supplier_refund_quote = api.pms_opening_supplier_credit_refund_quote(
                opening_prop.name, supplier_refund_data)
            supplier_refund = api.execute(opening_prop.name,
                "pms_refund_opening_supplier_credit",
                "reverse-vendor-refund-" + suffix,
                {**supplier_refund_data,
                 "acceptance": supplier_refund_quote["acceptance"]})
            if (supplier_refund["credit_available"] != "0.00" or
                    api.execute(opening_prop.name,
                        "pms_refund_opening_supplier_credit",
                        "reverse-vendor-refund-" + suffix,
                        {**supplier_refund_data,
                         "acceptance": supplier_refund_quote["acceptance"]}) != supplier_refund):
                frappe.throw("El reintegro del proveedor duplicó o excedió el crédito")
            refund_lines = frappe.get_all("HS Journal Line",
                filters={"parent": supplier_refund["journal"]},
                fields=["account", "party", "debit", "credit"])
            if {(line.account, line.party, Decimal(str(line.debit)),
                 Decimal(str(line.credit))) for line in refund_lines} != {
                    (bank.name, None, Decimal("3"), Decimal(0)),
                    (payable_account.name, supplier.name, Decimal(0), Decimal("3"))}:
                frappe.throw("El reintegro no debitó banco contra proveedores")
            try:
                api.pms_opening_supplier_credit_apply_quote(opening_prop.name,
                    {**credit_apply_data, "amount": "0.01"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El crédito agotado permitió otra aplicación")
            payment_data = {"payable": opened["name"], "method": bank_method,
                "amount": "7.00", "reference": "AP-PARTIAL-" + suffix,
                "reason": "Pago parcial de apertura"}
            quote = api.pms_opening_supplier_payment_quote(opening_prop.name,
                payment_data)
            if quote["outstanding_after"] != "4.00":
                frappe.throw("El pago inicial no calculó el saldo restante")
            paid = api.execute(opening_prop.name, "pms_pay_opening_supplier",
                "reverse-ap-payment-" + suffix,
                {**payment_data, "acceptance": quote["acceptance"]})
            current_payable = next(item for item in
                api.pms_purchase_snapshot(opening_prop.name)["opening_payables"]
                if item["name"] == opened["name"])
            if (paid["outstanding"] != "4.00" or
                    current_payable["outstanding"] != "4.00"):
                frappe.throw("El pago no redujo la deuda inicial")
            payment_lines = frappe.get_all("HS Journal Line",
                filters={"parent": paid["journal"]},
                fields=["account", "party", "debit", "credit"])
            if {(line.account, line.party, Decimal(str(line.debit)),
                 Decimal(str(line.credit)))
                    for line in payment_lines} != {
                    (payable_account.name, supplier.name, Decimal("7"), Decimal(0)),
                    (bank.name, None, Decimal(0), Decimal("7"))}:
                frappe.throw("El pago no debitó proveedores contra banco")
            if api.execute(opening_prop.name, "pms_pay_opening_supplier",
                    "reverse-ap-payment-" + suffix,
                    {**payment_data, "acceptance": quote["acceptance"]}) != paid:
                frappe.throw("El reintento duplicó el pago al proveedor")
            too_much = {**payment_data, "amount": "5.00",
                "reference": "AP-EXCESS-" + suffix}
            try:
                api.pms_opening_supplier_payment_quote(opening_prop.name, too_much)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se permitió pagar más que la deuda inicial")
            from hospitality_suite import standalone_closing
            daily = standalone_closing.build(opening_prop)
            breakdown = daily["breakdown"]
            def total(group):
                return sum((Decimal(item["base_amount"]) for item in
                            breakdown[group]), Decimal(0))
            if (daily["version"] != 8 or total("production") != 2 or
                    total("opening_receivables") != 25 or
                    total("opening_payables") != 14 or
                    total("opening_customer_credits") != 7 or
                    total("opening_guarantees") != 5 or
                    total("opening_guarantee_refunds") != 2 or
                    total("opening_credit_refunds") != 4 or
                    total("opening_supplier_payments") != 7 or
                    total("opening_supplier_credits") != 4 or
                    total("opening_supplier_credit_refunds") != 3 or
                    total("supplier_credit_applications") != 7 or
                    len(daily["sources"]["opening_credits"]) != 2 or
                    len(daily["sources"]["opening_guarantees"]) != 1):
                frappe.throw("El cierre duplicó producción o perdió saldos de apertura")

        with patch.object(reverse_rehearsal, "_verify_property",
                          side_effect=verify_visible):
            rehearsal = api.erp_to_pms_transfer_rehearsal(name, source_hash,
                manifest_hash, mapping, transfer_plan["plan_sha256"])
        if (not rehearsal["reconciled"] or not rehearsal["rolled_back"] or
                rehearsal["provider_changed"] or
                len(rehearsal["properties"][0]["receivables"]) != 1 or
                len(rehearsal["properties"][0]["credits"]) != 2 or
                len(rehearsal["properties"][0]["payables"]) != 2 or
                len(rehearsal["properties"][0]["supplier_credits"]) != 1 or
                len(rehearsal["properties"][0]["guarantees"]) != 1 or
                len(rehearsal["properties"][0]["stock_movements"]) != 1 or
                rehearsal["properties"][0]["operations"]["bookings"] !=
                    [booking_name] or
                rehearsal["properties"][0]["operations"]["folios"] !=
                    [folio_name] or
                rehearsal["properties"][0]["operations"]["service_requests"] !=
                    ["SREQ-ORIGEN-" + suffix,
                     "SREQ-STOCK-ORIGEN-" + suffix,
                     "SREQ-DELIVERED-ORIGEN-" + suffix,
                     "SREQ-CHARGED-ORIGEN-" + suffix] or
                rehearsal["properties"][0]["operations"]["guest_tickets"] !=
                    ["TICKET-ORIGEN-" + suffix] or
                rehearsal["properties"][0]["operations"]["ticket_events"] !=
                    ["EVENT-CREATED-" + suffix,
                     "EVENT-STARTED-" + suffix] or
                rehearsal["properties"][0]["operations"]["incidents"] !=
                    ["INC-ORIGEN-" + suffix,
                     "INC-EVIDENCE-ORIGEN-" + suffix] or
                rehearsal["properties"][0]["operations"]["day_passes"] !=
                    ["PASS-ORIGEN-" + suffix] or
                rehearsal["properties"][0]["operations"]["experience_orders"] !=
                    ["EXPO-BOOKED-" + suffix, "EXPO-DIRECT-" + suffix] or
                rehearsal["properties"][0]["operations"]["laundry_orders"] !=
                    ["LAUNDRY-ORIGEN-" + suffix,
                     "LAUNDRY-REQUESTED-" + suffix] or
                rehearsal["properties"][0]["operations"]["laundry_items"] !=
                    ["LAUNDRY-LINE-ORIGEN-" + suffix] or
                rehearsal["properties"][0]["operations"]["room_blocks"] !=
                    ["BLOCK-ORIGEN-" + suffix] or
                rehearsal["properties"][0]["operations"]["maintenance_orders"] !=
                    ["MAINT-ORIGEN-" + suffix] or
                not rehearsal["properties"][0]["residual_journal"] or
                frappe.db.exists("HS Booking", booking_name) or
                frappe.db.exists("HS Stay", stay_name) or
                frappe.db.exists("HS Folio", folio_name) or
                frappe.db.exists("HS Charge", "CHG-ORIGEN-" + suffix) or
                frappe.db.exists("HS Service Request", "SREQ-ORIGEN-" + suffix) or
                frappe.db.exists("HS Service Request",
                    "SREQ-STOCK-ORIGEN-" + suffix) or
                frappe.db.exists("HS Service Request",
                    "SREQ-DELIVERED-ORIGEN-" + suffix) or
                frappe.db.exists("HS Service Request",
                    "SREQ-CHARGED-ORIGEN-" + suffix) or
                frappe.db.exists("HS Guest Ticket", "TICKET-ORIGEN-" + suffix) or
                frappe.db.exists("HS Ticket Event", "EVENT-CREATED-" + suffix) or
                frappe.db.exists("HS Ticket Event", "EVENT-STARTED-" + suffix) or
                frappe.db.exists("HS Incident", "INC-ORIGEN-" + suffix) or
                frappe.db.exists("HS Incident",
                    "INC-EVIDENCE-ORIGEN-" + suffix) or
                frappe.db.exists("HS Day Pass", "PASS-ORIGEN-" + suffix) or
                any(path.exists() for path in evidence_paths) or
                frappe.db.exists("HS Laundry Order",
                    "LAUNDRY-ORIGEN-" + suffix) or
                frappe.db.exists("HS Laundry Order",
                    "LAUNDRY-REQUESTED-" + suffix) or
                frappe.db.exists("HS Experience Order",
                    "EXPO-BOOKED-" + suffix) or
                frappe.db.exists("HS Experience Order",
                    "EXPO-DIRECT-" + suffix) or
                frappe.db.exists("HS Portal Request", "WEB-ORIGEN-" + suffix) or
                frappe.db.exists("HS Room Block", "BLOCK-ORIGEN-" + suffix) or
                frappe.db.exists("HS Maintenance Order",
                    "MAINT-ORIGEN-" + suffix) or
                frappe.db.exists("HS Allocation", "BLOCK-ALLOC-ORIGEN-" + suffix) or
                frappe.db.exists("HS Allocation", "MAINT-ALLOC-ORIGEN-" + suffix) or
                frappe.db.exists("HS Allocation", "ALLOC-ORIGEN-" + suffix) or
                frappe.db.exists("HS PMS Receivable", {"property": prop.name}) or
                frappe.db.exists("HS PMS Opening Credit", {"property": prop.name}) or
                frappe.db.exists("HS PMS Opening Supplier Credit", {"property": prop.name}) or
                frappe.db.exists("HS PMS Opening Guarantee", {"property": prop.name}) or
                frappe.db.exists("HS PMS Supplier Credit Allocation", {"property": prop.name}) or
                frappe.db.exists("HS PMS Allocation", {"property": prop.name,
                    "opening_credit": ["is", "set"]}) or
                frappe.db.exists("HS PMS Opening Payable", {"property": prop.name}) or
                frappe.db.exists("HS Payment", {"property": prop.name,
                    "pms_opening_payable": ["is", "set"]}) or
                frappe.db.exists("HS Payment", {"property": prop.name,
                    "pms_opening_credit": ["is", "set"]}) or
                frappe.db.exists("HS Payment", {"property": prop.name,
                    "pms_opening_guarantee": ["is", "set"]}) or
                frappe.db.exists("HS Stock Movement", {"property": prop.name}) or
                frappe.db.exists("HS Journal", {"property": prop.name})):
            frappe.throw("El ensayo inverso no publicó, concilió y revirtió la cartera")
        frappe.db.savepoint("hs_reverse_staged_transfer_probe")
        staged_files = []
        try:
            staged = reverse_rehearsal._publish_validated(name, source_hash,
                manifest_hash, mapping, transfer_plan["plan_sha256"],
                staged_files)
            staged_property = staged["properties"][0]
            if (not staged["reconciled"] or staged["rolled_back"] or
                    staged["provider_changed"] or
                    len(staged_property["receivables"]) != 1 or
                    not frappe.db.exists("HS PMS Receivable",
                        staged_property["receivables"][0]) or
                    not frappe.db.exists("HS Folio", folio_name) or
                    not frappe.db.exists("HS Journal",
                        staged_property["residual_journal"]) or
                    len(staged_files) != 2 or
                    not all(path.is_file() for _url, path in staged_files)):
                frappe.throw("La publicación inversa no conservó documentos y evidencias")
        finally:
            frappe.db.rollback(save_point="hs_reverse_staged_transfer_probe")
            for url, file_path in staged_files:
                if not frappe.db.exists("File", {"file_url": url}):
                    file_path.unlink(missing_ok=True)
        if (frappe.db.exists("HS Folio", folio_name) or
                frappe.db.exists("HS PMS Receivable", {"property": prop.name}) or
                any(path.exists() for _url, path in staged_files)):
            frappe.throw("La publicación provisional dejó datos tras la reversión")
        from hospitality_suite import erp_to_pms_activation as reverse_activation
        activation_reference = "HS-ERP-PMS-" + suffix[:16]
        activation_args = {"source_sha256": source_hash,
            "manifest_sha256": manifest_hash,
            "receipt_sha256": receipt_hash,
            "source_backup_sha256": receipt["backup_sha256"],
            "mapping_sha256": sha256(canonical(mapping).encode()).hexdigest(),
            "plan_sha256": transfer_plan["plan_sha256"],
            "target_backup_sha256": "0" * 64,
            "target_backup_manifest": None,
            "migration_reference": activation_reference}
        frappe.db.savepoint("hs_reverse_activation_probe")
        activation_files = []
        old_rehearsal = getattr(frappe.local,
            "hs_reverse_cutover_rehearsal", False)
        frappe.local.hs_reverse_cutover_rehearsal = True
        try:
            activated = reverse_activation.activate_validated(name,
                receipt_name, mapping, created_files=activation_files,
                **activation_args)
            record_name = frappe.db.get_value(
                reverse_activation.DOCTYPE,
                {"migration_reference": activation_reference}, "name")
            if (not activated["cutover_performed"] or
                    not activated["reconciled"] or
                    activated["provider_changed"] or
                    not record_name or
                    frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                    frappe.db.get_single_value("HS Site Mode",
                        "migration_reference") != activation_reference or
                    len(activation_files) != 2 or
                    not frappe.db.exists("HS Folio", folio_name)):
                frappe.throw("El corte inverso no conservó acta, libro y documentos")
            replay = reverse_activation.activate_validated(name,
                receipt_name, mapping, created_files=[], **activation_args)
            if (replay != activated or
                    frappe.db.count(reverse_activation.DOCTYPE,
                        {"migration_reference": activation_reference}) != 1):
                frappe.throw("El reintento del corte inverso duplicó la apertura")
            try:
                reverse_activation.activate_validated(name, receipt_name,
                    mapping, created_files=[], **{
                        **activation_args, "plan_sha256": "1" * 64})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El acta aceptó un plan distinto")
            mode = frappe.get_single("HS Site Mode")
            mode.migration_reference = "CAMBIO-NO-AUTORIZADO"
            try:
                mode.save(ignore_permissions=True)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El modo permitió alterar el acta manualmente")
        finally:
            frappe.db.rollback(save_point="hs_reverse_activation_probe")
            frappe.clear_document_cache("HS Site Mode")
            reverse_activation._clean_created_files(activation_files)
            frappe.local.hs_reverse_cutover_rehearsal = old_rehearsal
        if (frappe.db.exists(reverse_activation.DOCTYPE,
                    {"migration_reference": activation_reference}) or
                frappe.db.exists("HS Folio", folio_name) or
                any(path.exists() for _url, path in activation_files)):
            frappe.throw("El ensayo de activación dejó acta o documentos")
        frappe.local.hs_reverse_cutover_rehearsal = False
        prior_maintenance = frappe.local.conf.get("maintenance_mode")
        frappe.local.conf["maintenance_mode"] = False
        try:
            try:
                reverse_activation.activate_validated(name, receipt_name,
                    mapping, created_files=[], **activation_args)
            except frappe.PermissionError:
                frappe.clear_messages()
            else:
                frappe.throw("El corte inverso aceptó un destino sin mantenimiento")
        finally:
            if prior_maintenance is None:
                frappe.local.conf.pop("maintenance_mode", None)
            else:
                frappe.local.conf["maintenance_mode"] = prior_maintenance
        failing_files = []
        frappe.local.hs_reverse_cutover_rehearsal = True
        from hospitality_suite.controllers import PMSCutoverRunDocument
        with patch.object(PMSCutoverRunDocument, "validate",
                          side_effect=frappe.ValidationError("Acta fallida")):
            try:
                reverse_activation.activate_validated(name, receipt_name,
                    mapping, created_files=failing_files, **activation_args)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("El corte sobrevivió al fallo de su acta")
        frappe.local.hs_reverse_cutover_rehearsal = old_rehearsal
        if (frappe.db.exists("HS Folio", folio_name) or
                frappe.db.exists(reverse_activation.DOCTYPE,
                    {"migration_reference": activation_reference}) or
                any(path.exists() for _url, path in failing_files)):
            frappe.throw("El fallo del acta dejó una apertura huérfana")
        from hospitality_suite import erp_to_pms_cli as reverse_cli
        map_file = "hs-erp-map-" + uuid4().hex + ".json"
        backup_file = "hs-pms-backup-" + uuid4().hex + ".json"
        map_path = Path(frappe.get_site_path("private", "files", map_file))
        backup_path = Path(frappe.get_site_path("private", "files", backup_file))
        map_path.write_text(canonical(mapping), encoding="utf-8")
        backup_path.write_text("{}", encoding="utf-8")
        bundle_paths.extend((map_path, backup_path))
        reviewed_cli = reverse_cli.review_file(map_file, receipt_name, name,
            source_sha256=source_hash, manifest_sha256=manifest_hash,
            receipt_sha256=receipt_hash,
            source_backup_sha256=receipt["backup_sha256"])
        if (not reviewed_cli["ready"] or reviewed_cli["blockers"] or
                reviewed_cli["mapping_sha256"] != activation_args["mapping_sha256"] or
                reviewed_cli["plan_sha256"] != activation_args["plan_sha256"]):
            frappe.throw("El comando Bench no revisó el plan congelado")
        frappe.db.savepoint("hs_reverse_cli_probe")
        cli_files = []
        original_rollback = frappe.db.rollback
        # This fixture is intentionally uncommitted. Suppress only the CLI's
        # fresh-snapshot rollback and commit; keep savepoint rollbacks real.
        def fixture_rollback(*args, **kwargs):
            if not args and not kwargs:
                return None
            return original_rollback(*args, **kwargs)
        frappe.local.hs_reverse_cutover_rehearsal = True
        try:
            with patch.object(frappe.db, "rollback",
                              side_effect=fixture_rollback), patch.object(
                                  frappe.db, "commit", return_value=None):
                cli_result = reverse_cli.activate_file(map_file,
                    receipt_name, name, backup_file,
                    **{key: value for key, value in activation_args.items()
                        if key != "target_backup_manifest"})
                replay = reverse_cli.activate_file(map_file,
                    receipt_name, name, backup_file,
                    **{key: value for key, value in activation_args.items()
                        if key != "target_backup_manifest"})
                if (cli_result != replay or
                        not cli_result["cutover_performed"] or
                        frappe.db.count(reverse_activation.DOCTYPE,
                            {"migration_reference": activation_reference}) != 1 or
                        frappe.db.get_single_value("HS Site Mode",
                            "migration_reference") != activation_reference):
                    frappe.throw("El comando Bench no conservó el acta en un reintento")
                try:
                    reverse_cli.activate_file(map_file, receipt_name, name,
                        backup_file, **{**{key: value for key, value in
                            activation_args.items()
                            if key != "target_backup_manifest"},
                            "target_backup_sha256": "1" * 64})
                except frappe.ValidationError:
                    frappe.clear_messages()
                else:
                    frappe.throw("El comando aceptó un respaldo distinto")
                for file_row in frappe.get_all("File", filters={
                        "attached_to_name": ["in", [
                            "INC-EVIDENCE-ORIGEN-" + suffix,
                            "MAINT-ORIGEN-" + suffix]]},
                        fields=["name"]):
                    cli_files.append(Path(frappe.get_doc(
                        "File", file_row.name).get_full_path()))
                if len(cli_files) != 2:
                    frappe.throw("El comando Bench perdió los archivos privados")
        finally:
            frappe.db.rollback(save_point="hs_reverse_cli_probe")
            frappe.clear_document_cache("HS Site Mode")
            for file_path in cli_files:
                file_path.unlink(missing_ok=True)
            frappe.local.hs_reverse_cutover_rehearsal = old_rehearsal
        if (frappe.db.exists(reverse_activation.DOCTYPE,
                    {"migration_reference": activation_reference}) or
                frappe.db.exists("HS Folio", folio_name) or
                any(path.exists() for path in cli_files)):
            frappe.throw("El ensayo del comando Bench dejó acta o documentos")
        foreign_credit_packaged = _foreign_credit_package_probe(
            source_inventory=inventory, source_manifest=manifest,
            original_bundle=Path(frappe.get_site_path("private", "files", name)),
            source_mapping=mapping, prop=prop, org=org,
            temporary=temporary, suffix=suffix, bundle_paths=bundle_paths)
        try:
            api.erp_to_pms_transfer_rehearsal(name, source_hash,
                manifest_hash, mapping, "0" * 64)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("El ensayo inverso aceptó un plan distinto")
        from hospitality_suite.erp_to_pms_transfer_plan import _property_plan
        wrong_source = deepcopy(inventory["properties"][0])
        wrong_source["open_receivables"][0]["outstanding_amount"] = "24.00"
        wrong_plan = _property_plan(wrong_source, preview_property, mapped, 2)
        if not any(row["code"] == "opening_control_mismatch"
                   for row in wrong_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una cartera distinta del mayor")
        wrong_base = deepcopy(inventory["properties"][0])
        wrong_base["open_receivables"][0]["base_outstanding_amount"] = "24.00"
        base_plan = _property_plan(wrong_base, preview_property, mapped, 2)
        if not any(row["code"] == "unrepresentable_open_document"
                   for row in base_plan["blockers"]):
            frappe.throw("El plan inverso aceptó importes divergentes en moneda base")
        wrong_folio = deepcopy(inventory["properties"][0])
        wrong_folio["open_receivables"][0]["folio_property"] = "OTRO-HOTEL"
        folio_plan = _property_plan(wrong_folio, preview_property, mapped, 2)
        if not any(row["code"] == "open_invoice_folio_source_mismatch"
                   for row in folio_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un folio de otro hotel")
        wrong_visit = deepcopy(inventory["properties"][0])
        wrong_visit["open_receivables"][0]["stay"] = "OTRA-ESTANCIA"
        visit_plan = _property_plan(wrong_visit, preview_property, mapped, 2)
        if not any(row["code"] == "open_invoice_folio_mismatch"
                   for row in visit_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una factura de otra estancia")
        wrong_advance = deepcopy(inventory["properties"][0])
        wrong_advance["deposits"]["customer_credits"][0]["available"] = "4.00"
        advance_plan = _property_plan(wrong_advance, preview_property, mapped, 2)
        if not any(row["code"] == "opening_control_mismatch"
                   for row in advance_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un anticipo distinto del mayor")
        foreign_source = deepcopy(inventory["properties"][0])
        foreign_source["open_receivables"][0]["account_currency"] = "USD"
        foreign_plan = _property_plan(foreign_source, preview_property, mapped, 2)
        if not any(row["code"] == "unrepresentable_open_document"
                   for row in foreign_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una cartera extranjera sin valor base")
        open_source = deepcopy(inventory["properties"][0])
        open_source["open_operations"]["bookings"] = [{"name": "BOOKING-ABIERTA"}]
        open_plan = _property_plan(open_source, preview_property, mapped, 2)
        if not any(row["code"] == "incomplete_open_booking"
                   for row in open_plan["blockers"]):
            frappe.throw("El plan inverso omitió una reserva abierta")
        changed_terms = deepcopy(inventory["properties"][0])
        changed_terms["open_operations"]["bookings"][0]["quote_snapshot"] = "{}"
        changed_plan = _property_plan(changed_terms, preview_property, mapped, 2)
        if not any(row["code"] == "open_operation_snapshot_mismatch"
                   for row in changed_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una tarifa alterada")
        mismatched_experience = deepcopy(inventory["properties"][0])
        web = mismatched_experience["open_operations"]["portal_requests"][0]
        quoted = frappe.parse_json(web["quote_snapshot"])
        quoted["experiences"][0]["item"] = "ARTICULO-AJENO"
        web["quote_snapshot"] = canonical(quoted)
        web["quote_snapshot_sha256"] = sha256(
            web["quote_snapshot"].encode()).hexdigest()
        experience_plan = _property_plan(mismatched_experience,
            preview_property, mapped, 2)
        if not any(row["code"] == "experience_snapshot_item_mismatch"
                   for row in experience_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una experiencia web con otro artículo")
        mismatched_web_quantity = deepcopy(inventory["properties"][0])
        web = mismatched_web_quantity["open_operations"][
            "portal_requests"][0]
        web["experiences"] = canonical([{
            "experience": "EXPERIENCE-ORIGEN", "quantity": 2}])
        web["experiences_sha256"] = sha256(
            web["experiences"].encode()).hexdigest()
        experience_plan = _property_plan(mismatched_web_quantity,
            preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_portal_experiences"
                   for row in experience_plan["blockers"]):
            frappe.throw("El plan inverso aceptó otra cantidad web que la cotizada")
        wrong_laundry_amount = deepcopy(inventory["properties"][0])
        wrong_laundry_amount["open_operations"]["laundry_items"][0][
            "amount"] = "4.00"
        laundry_plan = _property_plan(wrong_laundry_amount,
            preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_laundry_item"
                   for row in laundry_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un cobro de lavandería alterado")
        orphan_laundry = deepcopy(inventory["properties"][0])
        orphan_laundry["open_operations"]["laundry_orders"][0][
            "stay"] = "ESTANCIA-AJENA"
        laundry_plan = _property_plan(orphan_laundry,
            preview_property, mapped, 2)
        if not any(row["code"] in ("invalid_open_laundry_order",
                "dangling_open_operation_link") for row in
                laundry_plan["blockers"]):
            frappe.throw("El plan inverso aceptó lavandería sin estancia")
        incident_with_evidence = deepcopy(inventory["properties"][0])
        incident_with_evidence["open_operations"]["incidents"][0][
            "evidence"] = "/private/files/source-evidence.png"
        incident_plan = _property_plan(incident_with_evidence,
            preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_incident" for row in
                incident_plan["blockers"]):
            frappe.throw("El plan inverso aceptó evidencia sin trasladar el archivo")
        foreign_incident = deepcopy(inventory["properties"][0])
        foreign_incident["open_operations"]["incidents"][0][
            "room"] = "ROOM-AJENA"
        incident_plan = _property_plan(foreign_incident,
            preview_property, mapped, 2)
        if not any(row["code"] in ("unmapped_open_operation_link",
                "invalid_open_incident") for row in incident_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una incidencia de otro hotel")
        changed_pass = deepcopy(inventory["properties"][0])
        changed_pass["open_operations"]["day_passes"][0][
            "source_financial"]["invoice_total"] = "26.00"
        pass_plan = _property_plan(changed_pass, preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_day_pass" for row in
                pass_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un Day Pass con venta alterada")
        changed_checklist = deepcopy(inventory["properties"][0])
        changed_checklist["open_operations"]["cleaning_tasks"][0][
            "checklist"] = canonical({"baño": True})
        cleaning_plan = _property_plan(changed_checklist,
            preview_property, mapped, 2)
        if not any(row["code"] == "open_operation_snapshot_mismatch"
                   for row in cleaning_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una lista de limpieza alterada")
        closed_cleaning = deepcopy(inventory["properties"][0])
        historical_task = closed_cleaning["open_operations"]["cleaning_tasks"][0]
        historical_task["stay"] = "STAY-CERRADA-ORIGEN"
        historical_task["kind"] = "Departure"
        historical_task["source_closed_stay"] = {
            "name": historical_task["stay"], "room": historical_task["room"],
            "status": "Checked Out", "modified": "2026-10-19 09:07:44"}
        cleaning_plan = _property_plan(closed_cleaning,
            preview_property, mapped, 2)
        projected_task = cleaning_plan["operational_rows"]["cleaning_tasks"][0]
        if (cleaning_plan["blockers"] or projected_task.get("stay") or
                projected_task.get("source_stay") != "STAY-CERRADA-ORIGEN"):
            frappe.throw("El plan inverso perdió la estancia histórica de limpieza")
        historical_task["source_closed_stay"]["room"] = "ROOM-AJENA"
        cleaning_plan = _property_plan(closed_cleaning,
            preview_property, mapped, 2)
        if not any(row["code"] == "unreplayable_open_cleaning_stay"
                   for row in cleaning_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una estancia histórica alterada")
        mismatched_room = deepcopy(inventory["properties"][0])
        mismatched_room["open_operations"]["cleaning_tasks"][0][
            "room_cleaning_status"] = "Clean"
        cleaning_plan = _property_plan(mismatched_room,
            preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_cleaning_task"
                   for row in cleaning_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una habitación sin estado de limpieza")
        missing_event = deepcopy(inventory["properties"][0])
        missing_event["open_operations"]["ticket_events"] = [row for row in
            missing_event["open_operations"]["ticket_events"]
            if row["kind"] != "Created"]
        ticket_plan = _property_plan(missing_event, preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_guest_ticket"
                   for row in ticket_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un ticket sin evento de creación")
        orphan_event = deepcopy(inventory["properties"][0])
        orphan_event["open_operations"]["ticket_events"][0]["ticket"] = "TICKET-AJENO"
        ticket_plan = _property_plan(orphan_event, preview_property, mapped, 2)
        if not any(row["code"] in ("invalid_open_ticket_event",
                "dangling_open_operation_link") for row in ticket_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un evento de otro ticket")
        orphan_ticket = deepcopy(inventory["properties"][0])
        orphan_ticket["open_operations"]["guest_tickets"][0]["stay"] = "ESTANCIA-AJENA"
        ticket_plan = _property_plan(orphan_ticket, preview_property, mapped, 2)
        if not any(row["code"] in ("invalid_open_guest_ticket",
                "dangling_open_operation_link") for row in ticket_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un ticket sin estancia")
        changed_direct_tax = deepcopy(inventory["properties"][0])
        changed_direct_tax["open_operations"]["experience_orders"][1][
            "accepted_total"] = "4.00"
        experience_plan = _property_plan(changed_direct_tax,
            preview_property, mapped, 2)
        if not any(row["code"] == "invalid_direct_experience_terms"
                   for row in experience_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un impuesto de experiencia alterado")
        orphan_experience = deepcopy(inventory["properties"][0])
        orphan_experience["open_operations"]["experience_orders"][0][
            "booking"] = "RESERVA-AJENA"
        experience_plan = _property_plan(orphan_experience,
            preview_property, mapped, 2)
        if not any(row["code"] in ("dangling_open_experience_booking",
                "dangling_open_operation_link") for row in
                experience_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una experiencia sin reserva")
        orphan_charge = deepcopy(inventory["properties"][0])
        orphan_charge["open_operations"]["charges"][0]["folio"] = "FOL-AJENO"
        orphan_plan = _property_plan(orphan_charge, preview_property, mapped, 2)
        if not any(row["code"] == "dangling_open_operation_link"
                   for row in orphan_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un cargo sin folio")
        orphan_service = deepcopy(inventory["properties"][0])
        orphan_service["open_operations"]["service_requests"][0]["folio"] = "FOL-AJENO"
        service_plan = _property_plan(orphan_service, preview_property, mapped, 2)
        if not any(row["code"] in ("dangling_open_operation_link",
                "invalid_open_service_graph") for row in service_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un servicio sin folio")
        charged_service = deepcopy(inventory["properties"][0])
        charged_service["open_operations"]["service_requests"][0]["charge"] = "CHG-ANTERIOR"
        service_plan = _property_plan(charged_service, preview_property, mapped, 2)
        if not any(row["code"] == "unreplayable_open_service_reference"
                   for row in service_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una entrega ya contabilizada")
        tampered_issue = deepcopy(inventory["properties"][0])
        tampered_issue["open_operations"]["service_requests"][2][
            "source_stock_issue"]["cost"] = "5"
        service_plan = _property_plan(tampered_issue, preview_property, mapped, 2)
        if not any(row["code"] == "unreplayable_delivered_service_stock"
                   for row in service_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un costo histórico alterado")
        duplicated_issue = deepcopy(inventory["properties"][0])
        repeated_service = deepcopy(duplicated_issue["open_operations"]
            ["service_requests"][2])
        repeated_service["name"] = "SREQ-REPEATED-" + suffix
        duplicated_issue["open_operations"]["service_requests"].append(
            repeated_service)
        service_plan = _property_plan(duplicated_issue,
            preview_property, mapped, 2)
        if not any(row["code"] == "duplicate_delivered_service_stock_issue"
                   for row in service_plan["blockers"]):
            frappe.throw("El plan inverso reutilizó una misma salida histórica")
        foreign_service = deepcopy(inventory["properties"][0])
        foreign_service["open_operations"]["service_requests"][0]["currency"] = "USD"
        service_plan = _property_plan(foreign_service, preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_service_graph"
                   for row in service_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un servicio en otra moneda")
        overcommitted_service = deepcopy(inventory["properties"][0])
        overcommitted_service["open_operations"]["service_requests"][1]["quantity"] = 2
        service_plan = _property_plan(overcommitted_service,
            preview_property, mapped, 2)
        if not any(row["code"] == "overcommitted_open_service_entitlement"
                   for row in service_plan["blockers"]):
            frappe.throw("El plan inverso duplicó servicios incluidos")
        missing_block = deepcopy(inventory["properties"][0])
        missing_block["open_operations"]["allocations"] = [
            row for row in missing_block["open_operations"]["allocations"]
            if row["kind"] != "Room Block"]
        block_plan = _property_plan(missing_block, preview_property, mapped, 2)
        if not any(row["code"] == "invalid_open_room_block_graph"
                   for row in block_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un bloqueo sin ocupación")
        issued_parts = deepcopy(inventory["properties"][0])
        issued_parts["open_operations"]["maintenance_parts"] = [{
            "name": "PART-ORIGEN", "parent": "MAINT-ORIGEN-" + suffix,
            "idx": 1, "item": "STOCK-ITEM-ORIGEN", "quantity": 1,
            "cost": "3.00", "status": "Issued", "stock_entry": "SE-ORIGEN"}]
        parts_plan = _property_plan(issued_parts, preview_property, mapped, 2)
        if not any(row["code"] == "unreplayable_open_maintenance_part"
                   for row in parts_plan["blockers"]):
            frappe.throw("El plan inverso aceptó repuestos sin movimiento original")
        incomplete_issue = deepcopy(inventory["properties"][0])
        incomplete_issue["open_operations"]["maintenance_parts"] = [
            part for part in incomplete_issue["open_operations"][
                "maintenance_parts"] if part["name"] !=
                    "PART-VIGENTE-2-ORIGEN-" + suffix]
        incomplete_plan = _property_plan(incomplete_issue,
            preview_property, mapped, 2)
        if not any(row["code"] == "incomplete_open_maintenance_stock_issue"
                   for row in incomplete_plan["blockers"]):
            frappe.throw("El plan inverso aceptó un Stock Entry parcialmente trasladado")
        duplicate_detail = deepcopy(inventory["properties"][0])
        duplicate_part = duplicate_detail["open_operations"][
            "maintenance_parts"][2]
        duplicate_part["source_stock_issue"]["detail"] = maintenance_issue["detail"]
        duplicate_part["source_stock_issue_sha256"] = sha256(canonical(
            duplicate_part["source_stock_issue"]).encode()).hexdigest()
        duplicate_plan = _property_plan(duplicate_detail,
            preview_property, mapped, 2)
        if not any(row["code"] == "duplicate_open_maintenance_part"
                   for row in duplicate_plan["blockers"]):
            frappe.throw("El plan inverso duplicó una línea de Stock Entry")
        altered_return = deepcopy(inventory["properties"][0])
        altered_return["open_operations"]["maintenance_parts"][0][
            "source_returned_entry"]["docstatus"] = 1
        altered_plan = _property_plan(altered_return, preview_property, mapped, 2)
        if not any(row["code"] == "unreplayable_open_maintenance_part"
                   for row in altered_plan["blockers"]):
            frappe.throw("El plan inverso aceptó una devolución nativa sin cancelar")
        wrong_technician = deepcopy(mapped)
        wrong_technician["users"]["ADMIN-ORIGEN"] = "Guest"
        technician_plan = _property_plan(inventory["properties"][0],
            preview_property, wrong_technician, 2)
        if not any(row["code"] == "invalid_target_maintenance_assignee"
                   for row in technician_plan["blockers"]):
            frappe.throw("El plan inverso asignó mantenimiento sin acceso")
        invalid_bridge = deepcopy(mapping)
        invalid_bridge["properties"]["HOTEL-ORIGEN"]["temporary_opening_account"] = account.name
        bridge_review = api.erp_to_pms_mapping_review(name, source_hash,
            manifest_hash, invalid_bridge)
        if (bridge_review["mapping_ready"] or not any(row["code"] ==
                "invalid_temporary_opening_account" for row in bridge_review["blockers"])):
            frappe.throw("El mapa inverso aceptó una cuenta temporal de cartera")
        frappe.db.savepoint("hs_reverse_target_block_probe")
        try:
            frappe.get_doc({"doctype": "HS Room Block",
                "name": "TARGET-BLOCK-" + suffix,
                "company": prop.company, "property": prop.name,
                "room": room.name, "reason": "VIP Hold",
                "starts_at": block_start, "ends_at": block_end,
                "status": "Active"}).db_insert()
            occupied_target = api.erp_to_pms_mapping_review(name, source_hash,
                manifest_hash, mapping)
            if (occupied_target["mapping_ready"] or not any(
                    problem["code"] == "target_has_operational_history"
                    for problem in occupied_target["blockers"])):
                frappe.throw("El mapa aceptó un destino con bloqueo existente")
        finally:
            frappe.db.rollback(save_point="hs_reverse_target_block_probe")
        from hospitality_suite.erp_to_pms_balance_preview import _account_line
        foreign_problems = []
        foreign = _account_line({"account": "FX-ORIGEN", "base_currency": "NIO",
            "account_currency": "USD", "debit": "36.50", "credit": "0",
            "original_balance": "10.00", "party_type": None, "party": None},
            {"accounts": {"FX-ORIGEN": "FX-DESTINO"}, "customers": {},
             "suppliers": {}}, "HOTEL-ORIGEN", 2, foreign_problems)
        if (foreign_problems or not foreign or foreign["exchange_rate"] !=
                "3.650000000" or foreign["debit_in_account_currency"] != "10.00"):
            frappe.throw("La vista previa no conservó el saldo de moneda extranjera")
        impossible = _account_line({"account": "FX-ORIGEN", "base_currency": "NIO",
            "account_currency": "USD", "debit": "36.50", "credit": "0",
            "original_balance": "0", "party_type": None, "party": None},
            {"accounts": {"FX-ORIGEN": "FX-DESTINO"}, "customers": {},
             "suppliers": {}}, "HOTEL-ORIGEN", 2, foreign_problems)
        if impossible or foreign_problems[-1]["code"] != "unrepresentable_gl_balance":
            frappe.throw("La vista previa aceptó un saldo monetario imposible")
        frappe.db.savepoint("hs_reverse_account_nature_probe")
        try:
            frappe.db.set_value("HS Account", account.name, "root_type",
                "Income", update_modified=False)
            wrong_account = api.erp_to_pms_mapping_review(name, source_hash,
                manifest_hash, mapping)
            if (wrong_account["mapping_ready"] or not any(
                    problem["code"] == "account_nature_mismatch" for problem in
                    wrong_account["blockers"])):
                frappe.throw("El mapa aceptó una cuenta de naturaleza distinta")
        finally:
            frappe.db.rollback(save_point="hs_reverse_account_nature_probe")
        frappe.db.savepoint("hs_reverse_agent_type_probe")
        try:
            frappe.db.set_value("HS Travel Agent", agent.name, "agent_type",
                "OTA", update_modified=False)
            wrong_agent = api.erp_to_pms_mapping_review(name, source_hash,
                manifest_hash, mapping)
            if (wrong_agent["mapping_ready"] or not any(
                    problem["code"] == "travel_agent_type_mismatch" for problem
                    in wrong_agent["blockers"])):
                frappe.throw("El mapa aceptó una agencia de otro tipo")
        finally:
            frappe.db.rollback(save_point="hs_reverse_agent_type_probe")
        frappe.db.savepoint("hs_reverse_agent_supplier_probe")
        try:
            frappe.db.set_value("HS Travel Agent", agent.name, "pms_supplier",
                party.name, update_modified=False)
            wrong_supplier = api.erp_to_pms_mapping_review(name, source_hash,
                manifest_hash, mapping)
            if (wrong_supplier["mapping_ready"] or not any(
                    problem["code"] == "agent_supplier_relation_mismatch"
                    for problem in wrong_supplier["blockers"])):
                frappe.throw("El mapa aceptó otra cuenta de agencia")
        finally:
            frappe.db.rollback(save_point="hs_reverse_agent_supplier_probe")
        frappe.db.savepoint("hs_reverse_guest_payer_probe")
        try:
            frappe.db.set_value("HS Guest", guest.name, "customer",
                supplier.name, update_modified=False)
            wrong_guest = api.erp_to_pms_mapping_review(name, source_hash,
                manifest_hash, mapping)
            if (wrong_guest["mapping_ready"] or not any(
                    problem["code"] == "guest_customer_relation_mismatch"
                    for problem in wrong_guest["blockers"])):
                frappe.throw("El mapa aceptó un huésped con otro pagador")
        finally:
            frappe.db.rollback(save_point="hs_reverse_guest_payer_probe")
        frappe.db.savepoint("hs_reverse_equipment_room_probe")
        try:
            frappe.db.set_value("HS Equipment", equipment.name, "room", None,
                update_modified=False)
            wrong_equipment = api.erp_to_pms_mapping_review(name, source_hash,
                manifest_hash, mapping)
            if (wrong_equipment["mapping_ready"] or not any(
                    problem["code"] == "equipment_room_relation_mismatch"
                    for problem in wrong_equipment["blockers"])):
                frappe.throw("El mapa aceptó un equipo de otra habitación")
        finally:
            frappe.db.rollback(save_point="hs_reverse_equipment_room_probe")
        mapped["property"] = other_prop.name
        mismatched_review = api.erp_to_pms_mapping_review(name, source_hash,
            manifest_hash, mapping)
        if (mismatched_review["mapping_ready"] or not any(
                problem["code"] == "fiscal_archive_mismatch" for problem in
                mismatched_review["blockers"])):
            frappe.throw("El mapa aceptó el archivo fiscal de otro hotel")
        mapped["property"] = prop.name
        page = api.historical_fiscal_archive(prop.name, search=row["source_name"])
        if page["total"] != 1 or page["documents"][0]["status"] != "Posted":
            frappe.throw("El archivo importado no aparece en su hotel")
        if api.historical_fiscal_archive(other_prop.name)["total"]:
            frappe.throw("El archivo fiscal apareció en otro hotel")
        doc = frappe.get_doc("HS Historical Fiscal Document",
            page["documents"][0]["name"])
        attachment = frappe.db.get_value("File", {"attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name, "is_private": 1}, "name")
        pdf_path = Path(frappe.get_doc("File", attachment).get_full_path())
        api.historical_fiscal_pdf(doc.name)
        if (frappe.response["filecontent"] != pdf or
                frappe.response["display_content_as"] != "inline"):
            frappe.throw("La copia histórica no se puede abrir para imprimir")
        doc.document_number = "CAMBIADO"
        try:
            doc.save(ignore_permissions=True)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se modificó un documento fiscal histórico")
        try:
            frappe.delete_doc("File", attachment, ignore_permissions=True)
        except frappe.PermissionError:
            frappe.clear_messages()
        else:
            frappe.throw("Se eliminó un PDF fiscal histórico")
        bad = package(pdf + b"ALTERADO")
        try:
            erp_fiscal_history.import_bundle(bad, source_hash,
                manifest_hash, mapping)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se aceptó un PDF fiscal con huella inválida")
        bad_evidence = package(pdf, incident_evidence + b"ALTERADO")
        try:
            erp_fiscal_history.import_bundle(bad_evidence, source_hash,
                manifest_hash, mapping)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se aceptó evidencia de incidencia con huella inválida")
        bad_maintenance_evidence = package(pdf, maintenance_content=
            maintenance_evidence + b"ALTERADO")
        try:
            erp_fiscal_history.import_bundle(bad_maintenance_evidence,
                source_hash, manifest_hash, mapping)
        except frappe.ValidationError:
            frappe.clear_messages()
        else:
            frappe.throw("Se aceptó evidencia de mantenimiento con huella inválida")
        scoped_user = "hs-fiscal-" + suffix + "@example.invalid"
        with patch("frappe.enqueue", return_value=None):
            frappe.get_doc({"doctype": "User", "email": scoped_user,
                "first_name": "Caja archivo", "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "HS Cashier"}]}).insert(
                    ignore_permissions=True)
        frappe.get_doc({"doctype": "HS Access", "user": scoped_user,
            "company": other_prop.company,
            "property": other_prop.name}).insert(ignore_permissions=True)
        frappe.set_user(scoped_user)
        try:
            if api.historical_fiscal_archive(other_prop.name)["total"]:
                frappe.throw("La caja de otro hotel vio el archivo fiscal")
            for forbidden in (lambda: api.historical_fiscal_archive(prop.name),
                              lambda: api.historical_fiscal_pdf(doc.name),
                              lambda: frappe.get_doc("File", attachment).check_permission("read")):
                try:
                    forbidden()
                except frappe.PermissionError:
                    frappe.clear_messages()
                else:
                    frappe.throw("La caja de otro hotel consultó un PDF fiscal")
        finally:
            frappe.set_user("Administrator")
        authorized_user = "hs-fiscal-own-" + suffix + "@example.invalid"
        with patch("frappe.enqueue", return_value=None):
            frappe.get_doc({"doctype": "User", "email": authorized_user,
                "first_name": "Caja propia", "enabled": 1,
                "send_welcome_email": 0,
                "roles": [{"role": "HS Cashier"}]}).insert(
                    ignore_permissions=True)
        frappe.get_doc({"doctype": "HS Access", "user": authorized_user,
            "company": prop.company, "property": prop.name}).insert(
                ignore_permissions=True)
        frappe.set_user(authorized_user)
        try:
            if api.historical_fiscal_archive(prop.name)["total"] != 2:
                frappe.throw("La caja del hotel no vio su archivo fiscal")
            api.historical_fiscal_pdf(doc.name)
            if frappe.response["filecontent"] != pdf:
                frappe.throw("La caja del hotel no pudo imprimir su PDF")
            frappe.get_doc("File", attachment).check_permission("read")
        finally:
            frappe.set_user("Administrator")
        frappe.set_user("Guest")
        try:
            api.historical_fiscal_archive(prop.name)
        except frappe.PermissionError:
            frappe.clear_messages()
        else:
            frappe.throw("Un visitante consultó el archivo fiscal")
        try:
            api.erp_to_pms_mapping_template(name, source_hash, manifest_hash)
        except frappe.PermissionError:
            frappe.clear_messages()
        else:
            frappe.throw("Un visitante consultó el mapa de migración")
        try:
            api.erp_to_pms_balance_preview(name, source_hash, manifest_hash, mapping)
        except frappe.PermissionError:
            frappe.clear_messages()
        else:
            frappe.throw("Un visitante consultó los saldos de migración")
        try:
            api.erp_to_pms_transfer_plan(name, source_hash, manifest_hash, mapping)
        except frappe.PermissionError:
            frappe.clear_messages()
        else:
            frappe.throw("Un visitante consultó el plan de migración")
        try:
            api.erp_to_pms_transfer_rehearsal(name, source_hash,
                manifest_hash, mapping, transfer_plan["plan_sha256"])
        except frappe.PermissionError:
            frappe.clear_messages()
        else:
            frappe.throw("Un visitante ejecutó el ensayo de apertura")
        finally:
            frappe.set_user("Administrator")
        if persist:
            # The disposable clone is the only site allowed to keep this
            # fixture. Commit its masters before taking the native backup.
            frappe.db.commit()
            persisted = True
            bench_root = Path("/home/frappe/frappe-bench")
            subprocess.run(["bench", "--site", frappe.local.site,
                "set-config", "maintenance_mode", "1"], cwd=bench_root,
                check=True, capture_output=True, text=True)
            frappe.local.conf["maintenance_mode"] = 1
            subprocess.run(["bench", "--site", frappe.local.site,
                "backup", "--with-files"], cwd=bench_root,
                check=True, capture_output=True, text=True)
            real_backup_file = "hs-reverse-target-backup-" + uuid4().hex + ".json"
            prepared = reverse_cli.prepare_backup_file(real_backup_file)
            real_args = {key: value for key, value in activation_args.items()
                if key not in ("target_backup_manifest", "target_backup_sha256")}
            real_args["target_backup_sha256"] = prepared["backup_sha256"]
            confirmed = reverse_cli.activate_file(map_file, receipt_name,
                name, real_backup_file, **real_args)
            if (not confirmed["cutover_performed"] or
                    confirmed["property_count"] != 1 or
                    frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                    frappe.db.get_single_value("HS Site Mode",
                        "migration_reference") != activation_reference or
                    not frappe.db.exists("HS Folio", folio_name)):
                frappe.throw("La confirmación persistente perdió acta u operaciones")
            return {"persistent": True,
                "cutover_run": confirmed["cutover_run"],
                "property": prop.name, "folio": folio_name,
                "mapping_file": map_file,
                "receipt_file": receipt_name,
                "bundle_file": name,
                "target_backup_file": real_backup_file,
                **real_args}
        return {"imported": 2, "idempotent": True,
                "private_pdf_printable": True, "tamper_rejected": True,
                "guest_denied": True, "other_hotel_denied": True,
                "own_hotel_printable": True, "mapping_reviewed": True,
                "balance_previewed": True, "transfer_plan_balanced": True,
                "opening_rehearsed_and_rolled_back": True,
                "activation_and_cli_rehearsed": True,
                "foreign_credit_packaged": foreign_credit_packaged}
    finally:
        frappe.set_user("Administrator")
        if not persisted:
            frappe.db.rollback(save_point="hs_reverse_fiscal_target_probe")
            for path in bundle_paths:
                path.unlink(missing_ok=True)
            if pdf_path is not None:
                pdf_path.unlink(missing_ok=True)
