"""Property-scoped purchase and return pages for PMS supplier workflows."""

from decimal import Decimal

import frappe
from frappe import _

from hospitality_suite.security import require
from hospitality_suite.standalone_accounting import require_pms


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def page(property_name, kind="Purchase", search="", offset=0,
         page_length=25, available_only=0):
    if kind not in ("Purchase", "Return"):
        frappe.throw(_("Seleccione compras o devoluciones"))
    prop = require(property_name, "finance")
    require_pms(prop)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError, OverflowError):
        frappe.throw(_("Revise la paginación de compras"))
    if (offset < 0 or page_length < 1 or page_length > 100 or
            not isinstance(search, str) or len(search) > 100 or
            str(available_only) not in ("0", "1")):
        frappe.throw(_("Revise los filtros de compras"))
    term = search.strip()
    if kind == "Purchase":
        if str(available_only) == "1":
            frappe.throw(_("El filtro de créditos solo corresponde a devoluciones"))
        rows = frappe.db.sql(
            "SELECT b.name,b.supplier,p.party_name,b.supplier_reference,"
            "b.invoice_currency,b.invoice_amount,b.base_amount,b.business_date,"
            "b.product,b.warehouse,b.quantity,b.stock_movement "
            "FROM `tabHS PMS Purchase` b "
            "LEFT JOIN `tabHS Party` p ON p.name=b.supplier AND p.property=b.property "
            "WHERE b.property=%s AND b.status='Posted' "
            "AND (%s='' OR LOCATE(%s,b.name)>0 OR "
            "LOCATE(%s,b.supplier_reference)>0 OR LOCATE(%s,p.party_name)>0) "
            "ORDER BY b.creation DESC,b.name DESC LIMIT %s OFFSET %s",
            (prop.name, term, term, term, term, page_length + 1, offset),
            as_dict=True)
        page_rows = rows[:page_length]
        names = [row.name for row in page_rows]
        children = frappe.get_all("HS PMS Purchase Line",
            filters={"parenttype": "HS PMS Purchase", "parent": ["in", names]},
            fields=["parent", "idx", "product", "warehouse", "quantity",
                    "stock_movement"], order_by="parent asc, idx asc",
            limit_page_length=10000) if names else []
        by_parent = {}
        for line in children:
            by_parent.setdefault(line.parent, []).append(line)
        for row in page_rows:
            row["kind"] = kind
            row["lines"] = by_parent.get(row.name) or [{key: row.get(key) for key in
                ("product", "warehouse", "quantity", "stock_movement")}]
            row["can_cancel"] = not (frappe.db.exists("HS Payment", {
                "property": prop.name, "pms_purchase": row.name,
                "kind": "Supplier Payment", "status": "Posted"}) or
                frappe.db.exists("HS PMS Purchase Return", {
                    "property": prop.name, "purchase": row.name,
                    "status": "Posted"}))
            for key in ("product", "warehouse", "quantity", "stock_movement"):
                row.pop(key, None)
        product_ids = {line["product"] for row in page_rows for line in row["lines"]
                       if line.get("product")}
        labels = {product.name: product.product_name for product in frappe.get_all(
            "HS Product", filters={"property": prop.name,
                                   "organization": prop.organization,
                                   "name": ["in", list(product_ids)]},
            fields=["name", "product_name"], limit_page_length=len(product_ids))
            } if product_ids else {}
        for row in page_rows:
            for line in row["lines"]:
                line["product_name"] = labels.get(line.get("product")) or line.get("product")
    else:
        only_open = str(available_only) == "1"
        rows = frappe.db.sql(
            "SELECT r.name,r.purchase,r.supplier,p.party_name,"
            "r.kind AS return_kind,r.reference,r.business_date,"
            "r.invoice_currency,r.credit_amount,r.base_credit,"
            "r.supplier_credit,b.supplier_reference,"
            "r.supplier_credit-COALESCE(s.received,0) AS refund_available "
            "FROM `tabHS PMS Purchase Return` r "
            "LEFT JOIN `tabHS PMS Purchase` b ON b.name=r.purchase "
            "AND b.property=r.property "
            "LEFT JOIN `tabHS Party` p ON p.name=r.supplier AND p.property=r.property "
            "LEFT JOIN (SELECT pms_purchase_return,SUM(base_amount) AS received "
            "FROM `tabHS Payment` WHERE property=%s AND kind='Supplier Refund' "
            "AND status='Posted' GROUP BY pms_purchase_return) s "
            "ON s.pms_purchase_return=r.name "
            "WHERE r.property=%s AND r.status='Posted' "
            + ("AND r.supplier_credit>COALESCE(s.received,0) " if only_open else "") +
            "AND (%s='' OR LOCATE(%s,r.name)>0 OR LOCATE(%s,r.reference)>0 "
            "OR LOCATE(%s,b.supplier_reference)>0 OR LOCATE(%s,p.party_name)>0) "
            "ORDER BY r.creation DESC,r.name DESC LIMIT %s OFFSET %s",
            (prop.name, prop.name, term, term, term, term, term,
             page_length + 1, offset), as_dict=True)
        page_rows = rows[:page_length]
        for row in page_rows:
            if Decimal(str(row.refund_available)) < 0:
                frappe.throw(_("El reintegro del proveedor requiere conciliación"))
            row["kind"] = kind
            row["refund_available"] = _money(row.refund_available)
    return {"rows": page_rows, "search": term, "offset": offset,
            "has_more": len(rows) > page_length}
