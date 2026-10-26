"""Rollback-only rehearsal of the complete PMS to ERPNext opening transfer.

The rehearsal uses the same source/map validation, ERP postings, and link
rewrites needed by a future cutover. It never commits or changes HS Site Mode.
It remains internal until a mixed-site fixture and the final routing are
verified. Document names in its result are provisional because of rollback.
"""

import frappe
from frappe import _

from hospitality_suite import pms_cutover_links, pms_cutover_plan, pms_cutover_writer
from hospitality_suite.security import is_system
from hospitality_suite.service import operation


def prepare_suppliers(mapping, plan):
    """Bind mapped PMS suppliers to each ERP property before opening invoices.

    The native Purchase Invoice hook requires an active HS Supplier. Inactive
    source suppliers with open payables are enabled only while posting and
    restored to inactive afterward. All writes stay in the cutover transaction.
    """
    required = {prop["property"]: ({row["supplier"] for row in
                prop["opening_payables"]} | {row["supplier"] for row in
                prop.get("purchase_orders", [])}) for prop in plan["properties"]}
    restore_inactive = []
    created = 0
    for property_name, cfg in mapping["properties"].items():
        prop = frappe.get_doc("HS Property", property_name)
        for source_name, target in cfg["parties"].items():
            supplier = target.get("supplier") if isinstance(target, dict) else None
            if not supplier:
                continue
            source = frappe.db.get_value("HS Party", source_name,
                ["property", "active"], as_dict=True)
            if not source or source.property != property_name:
                frappe.throw(_("Un proveedor de origen cambió durante el corte"))
            matches = frappe.get_all("HS Supplier", filters={"property": property_name,
                "supplier": supplier}, fields=["name", "company", "active"],
                limit_page_length=0)
            if len(matches) > 1 or (matches and matches[0].company != cfg["company"]):
                frappe.throw(_("La asociación ERPNext del proveedor es ambigua"))
            active_for_posting = bool(source.active or supplier in required[property_name])
            if matches:
                name = matches[0].name
                if bool(matches[0].active) != active_for_posting:
                    frappe.db.set_value("HS Supplier", name, "active",
                                        int(active_for_posting), update_modified=False)
            else:
                with operation(prop):
                    name = frappe.get_doc({"doctype": "HS Supplier",
                        "company": cfg["company"], "property": property_name,
                        "supplier": supplier,
                        "active": int(active_for_posting)}).insert(
                            ignore_permissions=True).name
                created += 1
            if not source.active and active_for_posting:
                restore_inactive.append(name)
    return {"created": created, "restore_inactive": restore_inactive}


def restore_supplier_status(prepared):
    for name in prepared["restore_inactive"]:
        frappe.db.set_value("HS Supplier", name, "active", 0,
                            update_modified=False)


def prepare_warehouses(mapping):
    assigned = 0
    for property_name, cfg in mapping["properties"].items():
        settings = cfg["target_settings"]
        targets = set(cfg["warehouses"].values()) | {
            settings[field] for field in ("warehouse", "laundry_warehouse")
            if settings.get(field)}
        for target in sorted(targets):
            current = frappe.db.get_value("Warehouse", target,
                ["company", "hs_property", "is_group", "disabled"], as_dict=True)
            if (not current or current.company != cfg["company"] or
                    current.is_group or current.disabled or
                    current.hs_property not in (None, "", property_name)):
                frappe.throw(_("Un almacén ERPNext pertenece a otro establecimiento"))
            if not current.hs_property:
                frappe.db.set_value("Warehouse", target, "hs_property",
                                    property_name, update_modified=False)
                assigned += 1
    return assigned


def transfer_validated(mapping, *, source_sha256, plan_sha256, link_sha256):
    """Post a hash-checked transfer inside the caller's open transaction.

    The caller owns commit or rollback and the authority switch. This helper
    deliberately has no public API and never changes HS Site Mode.
    """
    if not is_system():
        frappe.throw(_("Solo administración del sistema puede ensayar la migración"),
                     frappe.PermissionError)
    if isinstance(mapping, str):
        mapping = frappe.parse_json(mapping)
    if not all(isinstance(value, str) and len(value) == 64 for value in
               (source_sha256, plan_sha256, link_sha256)):
        frappe.throw(_("Indique los tres hashes de la revisión aprobada"))
    reviewed = pms_cutover_plan.review(mapping)
    plan = reviewed.get("plan")
    manifest = reviewed.get("link_manifest")
    if (not reviewed.get("cutover_inputs_consistent") or not plan or not manifest or
            plan["source_sha256"] != source_sha256 or
            plan["plan_sha256"] != plan_sha256 or
            manifest["link_sha256"] != link_sha256):
        frappe.throw(_("La fuente, el mapeo o el plan cambió desde la revisión"))
    # ERPNext's scoped voucher hooks require the property's target Company
    # and mapped Customer/Item links before opening vouchers are submitted.
    links = pms_cutover_links.apply(manifest, link_sha256)
    warehouses_assigned = prepare_warehouses(mapping)
    suppliers = prepare_suppliers(mapping, plan)
    properties = [pms_cutover_writer.post_property(prop)
                  for prop in plan["properties"]]
    restore_supplier_status(suppliers)
    return {"source_sha256": source_sha256,
            "plan_sha256": plan_sha256,
            "link_sha256": link_sha256,
            "properties": properties,
            "links": links,
            "warehouses_assigned": warehouses_assigned,
            "supplier_bindings_created": suppliers["created"],
            "transfer_validated": True,
            "cutover_performed": False}


def run(mapping, *, source_sha256, plan_sha256, link_sha256):
    """Exercise all property openings and historical link rewrites atomically."""
    savepoint = "hs_cutover_rehearsal_" + frappe.generate_hash(length=12)
    frappe.db.savepoint(savepoint)
    try:
        result = transfer_validated(mapping,
            source_sha256=source_sha256,
            plan_sha256=plan_sha256,
            link_sha256=link_sha256)
        return {**result, "rehearsal_passed": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
