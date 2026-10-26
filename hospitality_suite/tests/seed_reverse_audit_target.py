"""Disposable two-property target for the 2026-10-25 ERP-to-PMS audit bundle.

The source attribution was hypothetical on a clone. Never run this on a live site.
"""

from pathlib import Path

import frappe

from hospitality_suite import (erp_fiscal_history, erp_to_pms_mapping,
    erp_to_pms_transfer_plan, erp_to_pms_transfer_rehearsal, setup)
from hospitality_suite.service import canonical, insert, operation
from hospitality_suite.standalone_accounting import provider


SITE = "hs-pms-audit-target.local"
BUNDLE = "hs-erp-fiscal-ef0940945e374d1a85dfce91f40074b9.zip"
SOURCE_SHA256 = "e974bb1f78d6dab950ade620b3c501ecbec67b8edcbae6954c76a8b76f36a9dc"
MANIFEST_SHA256 = "316a8baca827d7e5f56b01fbf2968352352806f32f82de6584f841dc23a1e82d"
MAP_FILE = "reverse-audit-target-mapping.json"


def _guard():
    if frappe.local.site != SITE or "erpnext" in frappe.get_installed_apps() or provider() != "pms":
        frappe.throw("Este ensayo requiere el sitio PMS descartable exacto")
    frappe.set_user("Administrator")


def _source():
    return erp_fiscal_history.load_source_inventory(
        BUNDLE, SOURCE_SHA256, MANIFEST_SHA256)


def _property(source, index, organization):
    values = {"property_name": f"Hotel de auditoría PMS {index}",
        "currency": source["currency"], "mode": "Hotel",
        "time_zone": "America/Managua", "close_time": "06:00",
        "business_date": source["business_date"]}
    if organization:
        values["organization"] = organization
    else:
        values["new_organization"] = {"legal_name": "Entidad de auditoría reversa descartable",
            "tax_regime": "General"}
    created = setup.create_property(values, f"reverse-audit-property-{index}")
    return frappe.get_doc("HS Property", created["property"])


def _seed_property(source, prop, index, target):
    requirements = source["mapping_requirements"]
    with operation(prop):
        for number, row in enumerate(requirements["accounts"], 1):
            account = insert("HS Account", prop, organization=prop.organization,
                account_code=f"AUD-{index}-{number:03d}",
                account_name=row["name"], root_type=row["root_type"],
                account_type=row.get("account_type") or "General",
                account_currency=row.get("account_currency") or prop.currency,
                active=1, is_group=0)
            target["accounts"][row["name"]] = account.name
        temporary = insert("HS Account", prop, organization=prop.organization,
            account_code=f"AUD-{index}-TEMP", account_name="Puente de apertura de auditoría",
            root_type="Asset", account_type="Temporary",
            account_currency=prop.currency, active=1, is_group=0)
        target["temporary_opening_account"] = temporary.name

        account_by_nature = {}
        for row in requirements["accounts"]:
            account_by_nature.setdefault(row["root_type"], target["accounts"][row["name"]])
        stock_account = next((target["accounts"][row["name"]]
            for row in requirements["accounts"] if row.get("account_type") == "Stock"),
            account_by_nature.get("Asset"))

        tax = insert("HS PMS Tax Profile", prop, organization=prop.organization,
            label="Exento de auditoría", treatment="Exempt", rate=0, active=1)
        for number, row in enumerate(requirements["products"], 1):
            kind = ("Asset" if row.get("is_fixed_asset") else
                "Stock" if row.get("is_stock_item") else "Service")
            product = insert("HS Product", prop, organization=prop.organization,
                product_code=f"AUD-P-{index}-{number:03d}",
                product_name=row.get("item_name") or row["name"],
                product_type=kind, sales_rate=100, active=1,
                income_account=account_by_nature.get("Income"),
                expense_account=account_by_nature.get("Expense") if kind != "Service" else None,
                inventory_account=stock_account if kind == "Stock" else None,
                tax_profile=tax.name)
            target["products"][row["name"]] = product.name

        for kind, party_type in (("customers", "Customer"), ("suppliers", "Supplier")):
            for row in requirements["parties"][party_type]:
                party = insert("HS Party", prop, organization=prop.organization,
                    party_name=row.get("customer_name") or row.get("supplier_name") or row["name"],
                    party_type=party_type, active=1)
                target[kind][row["name"]] = party.name

        for number, row in enumerate(requirements["warehouses"], 1):
            warehouse = insert("HS Warehouse", prop, organization=prop.organization,
                warehouse_code=f"AUD-W-{index}-{number:03d}",
                warehouse_name=row["name"], inventory_account=stock_account,
                active=1)
            target["warehouses"][row["name"]] = warehouse.name

        for number, row in enumerate(requirements["categories"], 1):
            category = insert("HS Category", prop,
                category_name=f"Categoría de auditoría {index}-{number}", capacity=2)
            target["categories"][row["name"]] = category.name
        for number, row in enumerate(requirements["rooms"], 1):
            room = insert("HS Room", prop,
                room_number=f"AUD-{index}-{number:03d}",
                category=target["categories"][row["category"]],
                cleaning_status="Clean", active=1)
            target["rooms"][row["name"]] = room.name
        for number, row in enumerate(requirements["rates"], 1):
            rate = insert("HS Rate", prop,
                title=f"Tarifa de auditoría {index}-{number}",
                category=target["categories"][row["category"]],
                mode=row["mode"], currency=row["currency"], amount=100,
                block_hours=3, rounding_minutes=60, included_people=2, active=1)
            target["rates"][row["name"]] = rate.name
        for number, row in enumerate(requirements["guests"], 1):
            guest = insert("HS Guest", prop,
                full_name=f"Huésped de auditoría {index}-{number}",
                customer=target["customers"].get(row.get("customer")))
            target["guests"][row["name"]] = guest.name

    for row in requirements["users"]:
        name = row["name"]
        if not frappe.db.exists("User", name):
            frappe.get_doc({"doctype": "User", "email": name,
                "first_name": "Auditoría", "user_type": "System User",
                "send_welcome_email": 0, "enabled": 1}).insert(ignore_permissions=True)
        target["users"][name] = name


def prepare():
    _guard()
    if frappe.db.count("HS Property") or frappe.db.count("HS Organization"):
        frappe.throw("El destino de auditoría debe comenzar sin hoteles ni entidades")
    manifest, inventory = _source()
    if len(inventory["properties"]) != 2 or inventory["blockers"]:
        frappe.throw("El paquete de auditoría no contiene exactamente dos hoteles listos")
    mapping = erp_to_pms_mapping.template(BUNDLE, SOURCE_SHA256, MANIFEST_SHA256)
    organization = None
    for index, source in enumerate(inventory["properties"], 1):
        prop = _property(source, index, organization)
        organization = prop.organization
        target = mapping["properties"][source["property"]]
        target["property"] = prop.name
        _seed_property(source, prop, index, target)
    archive = erp_fiscal_history.import_bundle(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256,
        {source: config["property"] for source, config in mapping["properties"].items()})
    review = erp_to_pms_mapping.review(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)
    path = Path(frappe.get_site_path("private", "files", MAP_FILE))
    if path.exists():
        frappe.throw("El archivo del mapa de auditoría ya existe")
    frappe.db.commit()
    path.write_text(canonical(mapping) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return {"properties": {source: config["property"] for source, config in
        mapping["properties"].items()}, "fiscal": archive,
        "documents": len(manifest["documents"]), "map_file": MAP_FILE,
        "mapping_ready": review["mapping_ready"], "blockers": review["blockers"]}


def review():
    _guard()
    path = Path(frappe.get_site_path("private", "files", MAP_FILE))
    if not path.is_file():
        frappe.throw("Prepare antes el destino de auditoría")
    mapping = frappe.parse_json(path.read_text(encoding="utf-8"))
    return erp_to_pms_mapping.review(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)


def plan():
    _guard()
    path = Path(frappe.get_site_path("private", "files", MAP_FILE))
    if not path.is_file():
        frappe.throw("Prepare antes el destino de auditoría")
    mapping = frappe.parse_json(path.read_text(encoding="utf-8"))
    result = erp_to_pms_transfer_plan.review(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)
    return {"ready_for_transfer": result["ready_for_transfer"],
        "arithmetically_balanced": result["arithmetically_balanced"],
        "plan_sha256": result.get("plan_sha256"),
        "property_count": len(result["properties"]),
        "blockers": result["blockers"]}


def rehearse():
    _guard()
    path = Path(frappe.get_site_path("private", "files", MAP_FILE))
    if not path.is_file():
        frappe.throw("Prepare antes el destino de auditoría")
    mapping = frappe.parse_json(path.read_text(encoding="utf-8"))
    inspected = erp_to_pms_transfer_plan.review(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping)
    if not inspected["ready_for_transfer"]:
        return {"ready_for_transfer": False, "blockers": inspected["blockers"]}
    result = erp_to_pms_transfer_rehearsal.rehearse(BUNDLE, SOURCE_SHA256,
        MANIFEST_SHA256, mapping, inspected["plan_sha256"])
    if not result["reconciled"] or not result["rolled_back"]:
        frappe.throw("El ensayo de auditoría no concilió o no revirtió")
    return {"reconciled": True, "rolled_back": True,
        "plan_sha256": inspected["plan_sha256"],
        "properties": result["properties"]}
