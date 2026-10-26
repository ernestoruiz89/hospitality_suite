"""Disposable ERPNext target masters for the isolated two-hotel round-trip clone.

This is deliberately restricted to the named synthetic clone. It never changes
the provider or runs the cutover; the resulting map still needs review.
"""

import json
from decimal import Decimal
from pathlib import Path

import frappe

from hospitality_suite.pms_cutover import preflight
from hospitality_suite.pms_cutover_mapping import review, template
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


SITE = "hs-pms-reverse-live-retake.local"
COMPANY = "HS Roundtrip Target"
ABBR = "HRT"
MAP_FILE = "hs-roundtrip-target-map.json"
SOURCE_FILE = "hs-roundtrip-source.json"


def _insert(doctype, **values):
    return frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def _root(doctype, company, **filters):
    name = frappe.db.get_value(doctype, {"company": company, "is_group": 1,
        "parent_account" if doctype == "Account" else
        "parent_warehouse" if doctype == "Warehouse" else
        "parent_cost_center": ["is", "not set"], **filters}, "name")
    if not name:
        frappe.throw(f"No se encontró la raíz ERPNext de {doctype}: {filters}")
    return name


def prepare():
    if (frappe.local.site != SITE or frappe.session.user != "Administrator" or
            provider() != "pms" or "erpnext" not in frappe.get_installed_apps()):
        frappe.throw("Este fixture requiere el clon PMS aislado y Administrator")
    source = preflight()
    if not source["ready_for_mapping"] or len(source["properties"]) != 2:
        frappe.throw("Cierre y concilie los dos hoteles sintéticos antes del fixture")

    if not frappe.db.exists("Company", COMPANY):
        _insert("Company", company_name=COMPANY, abbr=ABBR,
                country="Nicaragua", default_currency="NIO",
                enable_perpetual_inventory=1)
    company = frappe.get_doc("Company", COMPANY)
    fiscal = "HS Roundtrip FY 2026"
    if not frappe.db.exists("Fiscal Year", fiscal):
        _insert("Fiscal Year", year=fiscal,
                year_start_date="2026-01-01", year_end_date="2026-12-31",
                companies=[{"company": company.name}])
    if not frappe.db.exists("UOM", "Nos"):
        _insert("UOM", uom_name="Nos", must_be_whole_number=1, enabled=1)
    for name, account_type in (("Customer", "Receivable"), ("Supplier", "Payable")):
        if not frappe.db.exists("Party Type", name):
            _insert("Party Type", party_type=name, account_type=account_type)

    price_list = "HS Roundtrip NIO"
    if not frappe.db.exists("Price List", price_list):
        _insert("Price List", price_list_name=price_list,
                currency="NIO", selling=1, enabled=1)
    mapping = template()
    for index, source_prop in enumerate(source["properties"], start=1):
        property_name = source_prop["property"]
        cfg = mapping["properties"][property_name]
        cfg["company"] = company.name
        center_label = f"HS Roundtrip Hotel {index}"
        center = frappe.db.get_value("Cost Center", {
            "company": company.name, "cost_center_name": center_label}, "name")
        if not center:
            center = _insert("Cost Center", company=company.name,
                cost_center_name=center_label, is_group=0,
                parent_cost_center=_root("Cost Center", company.name)).name
        cfg["cost_center"] = center
        for warehouse_name in cfg["warehouses"]:
            label = f"HS RT {warehouse_name}"
            target = frappe.db.get_value("Warehouse", {
                "company": company.name, "warehouse_name": label}, "name")
            if not target:
                target = _insert("Warehouse", company=company.name,
                    warehouse_name=label, is_group=0,
                    parent_warehouse=_root("Warehouse", company.name)).name
            cfg["warehouses"][warehouse_name] = target

        from erpnext.stock import get_warehouse_account
        stock_target = get_warehouse_account(frappe.get_doc("Warehouse",
            next(iter(cfg["warehouses"].values()))), raise_error=True)
        for row in source_prop["ledger"]["accounts"]:
            if row["account_type"] == "Stock":
                target = stock_target
            else:
                label = f"HS RT {row['name']} {row['account_name']}"[:120]
                target = frappe.db.get_value("Account", {
                    "company": company.name, "account_name": label}, "name")
                if not target:
                    kind = row["account_type"] if row["account_type"] in (
                        "Cash", "Bank", "Receivable", "Payable", "Temporary") else ""
                    target = _insert("Account", company=company.name,
                        account_name=label, parent_account=_root("Account",
                            company.name, root_type=row["root_type"]),
                        root_type=row["root_type"], account_type=kind,
                        account_currency=row["account_currency"] or "NIO",
                        report_type="Balance Sheet" if row["root_type"] in (
                            "Asset", "Liability", "Equity") else "Profit and Loss").name
            cfg["accounts"][row["name"]] = target

        temporary_label = f"HS RT Opening Hotel {index}"
        temporary = frappe.db.get_value("Account", {
            "company": company.name, "account_name": temporary_label}, "name")
        if not temporary:
            temporary = _insert("Account", company=company.name,
                account_name=temporary_label,
                parent_account=_root("Account", company.name, root_type="Asset"),
                root_type="Asset", account_type="Temporary",
                account_currency="NIO", report_type="Balance Sheet").name
        cfg["temporary_opening_account"] = temporary

        for party_name, targets in cfg["parties"].items():
            party = frappe.get_doc("HS Party", party_name)
            if "customer" in targets:
                label = f"HS RT {party_name} {party.party_name}"[:120]
                target = frappe.db.get_value("Customer", {"customer_name": label}, "name")
                if not target:
                    target = _insert("Customer", customer_name=label,
                        customer_type="Individual", customer_group="Individual",
                        territory="Nicaragua").name
                targets["customer"] = target
            if "supplier" in targets:
                label = f"HS RT {party_name} {party.party_name}"[:120]
                target = frappe.db.get_value("Supplier", {"supplier_name": label}, "name")
                if not target:
                    target = _insert("Supplier", supplier_name=label).name
                targets["supplier"] = target

        for product_name in cfg["products"]:
            product = frappe.get_doc("HS Product", product_name)
            code = f"HS-RT-{product_name}"
            if not frappe.db.exists("Item", code):
                _insert("Item", item_code=code,
                    item_name=f"HS Roundtrip {product.product_name}"[:140],
                    item_group="Products" if product.product_type == "Stock" else "Services",
                    stock_uom="Nos", is_stock_item=int(product.product_type == "Stock"),
                    is_sales_item=1, is_purchase_item=int(product.product_type == "Stock"))
            cfg["products"][product_name] = code
            if product.sales_rate and not frappe.db.exists("Item Price", {
                    "item_code": code, "price_list": price_list}):
                _insert("Item Price", item_code=code, price_list=price_list,
                    currency="NIO", selling=1, price_list_rate=product.sales_rate)

        receivable = next(row for row in source_prop["ledger"]["accounts"]
            if row["account_type"] == "Receivable")
        guarantee = next(row for row in source_prop["ledger"]["accounts"]
            if "Garantías" in row["account_name"])
        lodging = next(name for name in cfg["products"]
            if "Alojamiento" in frappe.db.get_value("HS Product", name, "product_name"))
        cfg["target_settings"] = {
            "warehouse": cfg["warehouses"][next(iter(cfg["warehouses"]))],
            "receivable_account": cfg["accounts"][receivable["name"]],
            "guarantee_account": cfg["accounts"][guarantee["name"]],
            "lodging_item": cfg["products"][lodging],
            "price_list": price_list,
            "tax_policy_confirmed": True,
        }

    Path(frappe.get_site_path("private", "files", SOURCE_FILE)).write_text(
        canonical(source), encoding="utf-8")
    target = Path(frappe.get_site_path("private", "files", MAP_FILE))
    target.write_text(canonical(mapping), encoding="utf-8")
    checked = review(mapping)
    return {"file": MAP_FILE, "source_sha256": source["source_sha256"],
        "mapping_ready": checked["source_and_mapping_ready"],
        "mapping_blockers": checked["mapping_blockers"]}


def rehearse():
    if frappe.local.site != SITE or frappe.session.user != "Administrator":
        frappe.throw("El ensayo requiere el clon PMS aislado y Administrator")
    from hospitality_suite.pms_cutover_activation import rehearse_activation
    from hospitality_suite.pms_cutover_plan import review as review_plan

    mapping = json.loads(Path(frappe.get_site_path("private", "files", MAP_FILE))
        .read_text(encoding="utf-8"))
    checked = review_plan(mapping)
    if not checked["cutover_inputs_consistent"]:
        frappe.throw("El mapa o el plan de regreso cambió")
    result = rehearse_activation(mapping,
        source_sha256=checked["plan"]["source_sha256"],
        plan_sha256=checked["plan"]["plan_sha256"],
        link_sha256=checked["link_manifest"]["link_sha256"],
        migration_reference="hs-roundtrip-synthetic-rehearsal")
    if provider() != "pms" or frappe.db.count("HS Cutover Run"):
        frappe.throw("El ensayo no restauró el proveedor y el acta")
    return {"activation_rehearsed": result["activation_rehearsed"],
        "provider_after": provider(),
        "property_count": len(result.get("properties") or []),
        "source_sha256": checked["plan"]["source_sha256"],
        "plan_sha256": checked["plan"]["plan_sha256"]}


def verify_persistent():
    if frappe.local.site != SITE or frappe.session.user != "Administrator":
        frappe.throw("La verificación requiere el clon aislado")
    mode = frappe.get_single("HS Site Mode")
    run_name = frappe.db.get_value("HS Cutover Run",
        {"migration_reference": "hs-roundtrip-20261026"}, "name")
    if not run_name:
        frappe.throw("Falta el acta de regreso a ERPNext")
    run = frappe.get_doc("HS Cutover Run", run_name)
    result = frappe.parse_json(run.result_json)
    if (mode.provider != "ERPNext" or mode.migration_reference !=
            "hs-roundtrip-20261026" or not result.get("cutover_performed") or
            not result.get("transfer_validated") or
            result.get("prior_reverse_cutover") != {
                "cutover_run": "uvatp0mi7j",
                "migration_reference": "reverse-live-stage-20261026"}):
        frappe.throw("El corte de regreso no conserva autoridad, conciliación y linaje")
    mapping = json.loads(Path(frappe.get_site_path("private", "files", MAP_FILE))
        .read_text(encoding="utf-8"))
    source = json.loads(Path(frappe.get_site_path("private", "files",
        SOURCE_FILE)).read_text(encoding="utf-8"))
    if source["source_sha256"] != result["source_sha256"]:
        frappe.throw("La fuente de comprobación no coincide con el acta")
    source_properties = {row["property"]: row for row in source["properties"]}
    properties = []
    for row in result.get("properties") or []:
        prop = frappe.get_doc("HS Property", row["property"])
        cfg = mapping["properties"][prop.name]
        warehouses = list(cfg["warehouses"].values())
        if prop.company != cfg["company"] or prop.cost_center != cfg["cost_center"]:
            frappe.throw("El hotel no conserva su compañía y centro de costo ERPNext")
        balances = frappe.db.sql(
            "SELECT account,SUM(debit-credit) AS base_amount,"
            "SUM(debit_in_account_currency-credit_in_account_currency) AS original_amount "
            "FROM `tabGL Entry` WHERE company=%s AND cost_center=%s "
            "AND is_cancelled=0 GROUP BY account",
            (prop.company, prop.cost_center), as_dict=True)
        by_account = {entry.account: entry for entry in balances}
        for account_name, expected in row["reconciliation"]["accounts"].items():
            actual = Decimal(str(by_account.get(account_name, {}).get("base_amount") or 0))
            if abs(actual - Decimal(str(expected))) > Decimal("0.01"):
                frappe.throw(f"No concilia el mayor ERPNext de {prop.name}: {account_name}")
        for account_name, expected in row["reconciliation"]["account_currency_balances"].items():
            actual = Decimal(str(by_account.get(account_name, {}).get("original_amount") or 0))
            if abs(actual - Decimal(str(expected))) > Decimal("0.01"):
                frappe.throw(f"No concilia la moneda de cuenta de {prop.name}: {account_name}")
        for account_name, entry in by_account.items():
            if (account_name not in row["reconciliation"]["accounts"] and
                    abs(Decimal(str(entry.base_amount))) > Decimal("0.01")):
                frappe.throw(f"El mayor ERPNext tiene saldo no mapeado en {prop.name}")
        stock_checks = 0
        for position in source_properties[prop.name]["stock_positions"]:
            bin_row = frappe.db.get_value("Bin", {
                "warehouse": cfg["warehouses"][position["warehouse"]],
                "item_code": cfg["products"][position["product"]]},
                ["actual_qty", "stock_value"], as_dict=True)
            if not bin_row or (abs(Decimal(str(bin_row.actual_qty)) -
                    Decimal(position["quantity"])) > Decimal("0.001") or
                    abs(Decimal(str(bin_row.stock_value)) -
                    Decimal(position["value"])) > Decimal("0.01")):
                frappe.throw(f"No concilia el inventario ERPNext de {prop.name}")
            stock_checks += 1
        properties.append({"property": prop.name, "company": prop.company,
            "cost_center": prop.cost_center,
            "gl_entries": frappe.db.count("GL Entry", {
                "company": prop.company, "cost_center": prop.cost_center,
                "is_cancelled": 0}),
            "sales_invoices": frappe.db.count("Sales Invoice", {
                "company": prop.company, "hs_property": prop.name,
                "docstatus": 1}),
            "stock_entries": frappe.db.count("Stock Ledger Entry", {
                "company": prop.company, "warehouse": ["in", warehouses],
                "is_cancelled": 0}),
            "stock_positions_verified": stock_checks,
            "accounts_verified": len(row["reconciliation"]["accounts"]),
            "vouchers": row.get("vouchers")})
    historical_count = frappe.db.count("HS Historical Fiscal Document")
    if (len(properties) != 2 or
            frappe.db.count("HS ERP to PMS Cutover Run") != 1 or
            historical_count != 7):
        frappe.throw("El recorrido no conserva ambos hoteles y el acta inversa")
    from hospitality_suite.erp_fiscal_history import _verified_content
    historical_name = frappe.db.get_value("HS Historical Fiscal Document", {
        "property": properties[0]["property"]}, "name")
    if not _verified_content(frappe.get_doc("HS Historical Fiscal Document",
            historical_name)).startswith(b"%PDF"):
        frappe.throw("El PDF fiscal histórico no se puede verificar")
    opening_invoice = next(name for doctype, name in properties[0]["vouchers"]
        if doctype == "Sales Invoice")
    if opening_invoice not in frappe.get_print("Sales Invoice", opening_invoice):
        frappe.throw("La factura de apertura ERPNext no se puede imprimir")
    return {"provider": mode.provider,
        "migration_reference": mode.migration_reference,
        "cutover_run": run_name,
        "prior_reverse_cutover": result.get("prior_reverse_cutover"),
        "historical_fiscal_documents": historical_count,
        "historical_pdf_verified": historical_name,
        "native_invoice_print_verified": opening_invoice,
        "properties": properties}


def verify_reverse_origin_guard():
    if frappe.local.site != SITE or frappe.session.user != "Administrator":
        frappe.throw("La verificación requiere el clon aislado")
    from hospitality_suite.pms_cutover_activation import _prior_reverse_cutover

    if _prior_reverse_cutover(frappe._dict(migration_reference=None)) is not None:
        frappe.throw("Se confundió un sitio PMS nuevo con un corte inverso")
    valid = _prior_reverse_cutover(frappe._dict(
        migration_reference="reverse-live-stage-20261026"))
    if valid != {"cutover_run": "uvatp0mi7j",
            "migration_reference": "reverse-live-stage-20261026"}:
        frappe.throw("El acta previa no se reconoció")
    try:
        _prior_reverse_cutover(frappe._dict(migration_reference="no-such-cutover"))
    except frappe.ValidationError:
        pass
    else:
        frappe.throw("Se aceptó una referencia sin acta inversa")
    return {"new_pms_site_allowed": True,
        "valid_reverse_cutover": valid, "unknown_reference_rejected": True}
