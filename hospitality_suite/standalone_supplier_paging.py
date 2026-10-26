"""Property-scoped pages for PMS supplier balances and credit applications."""

from decimal import Decimal

import frappe
from frappe import _

from hospitality_suite.security import require
from hospitality_suite.standalone_accounting import require_pms


def _money(value):
    return format(Decimal(str(value)).quantize(Decimal("0.01")), "f")


def page(property_name, kind="Target", search="", supplier="", currency="",
         offset=0, page_length=25):
    if kind not in ("Target", "Credit", "Application"):
        frappe.throw(_("Seleccione un listado de proveedores válido"))
    prop = require(property_name, "finance")
    require_pms(prop)
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError, OverflowError):
        frappe.throw(_("Revise la paginación de proveedores"))
    if (offset < 0 or page_length < 1 or page_length > 100 or
            not isinstance(search, str) or len(search) > 100 or
            not isinstance(supplier, str) or len(supplier) > 140 or
            not isinstance(currency, str) or len(currency) > 3):
        frappe.throw(_("Revise los filtros de proveedores"))
    term = search.strip()
    supplier = supplier.strip()
    currency = currency.strip()
    if kind == "Credit":
        rows = frappe.db.sql(
            "SELECT c.name,c.supplier,p.party_name,c.opening_source_name,"
            "c.currency,c.amount,c.base_amount,c.payable_account,c.creation "
            "FROM `tabHS PMS Opening Supplier Credit` c "
            "LEFT JOIN `tabHS Party` p ON p.name=c.supplier AND p.property=c.property "
            "WHERE c.property=%s AND c.status='Posted' "
            "AND (%s='' OR c.supplier=%s) AND (%s='' OR c.currency=%s) "
            "AND (%s='' OR LOCATE(%s,c.name)>0 OR "
            "LOCATE(%s,c.opening_source_name)>0 OR LOCATE(%s,p.party_name)>0) "
            "ORDER BY c.creation DESC,c.name DESC LIMIT %s OFFSET %s",
            (prop.name, supplier, supplier, currency, currency,
             term, term, term, term, page_length + 1, offset), as_dict=True)
        from hospitality_suite.standalone_opening_supplier_credits import balances
        page_rows = []
        for row in rows[:page_length]:
            nominal, base = balances(prop, row.name)
            row.pop("creation", None)
            page_rows.append({**row, "kind": kind, "available": _money(nominal),
                              "base_available": _money(base)})
    elif kind == "Target":
        rows = frappe.db.sql(
            "SELECT x.name,x.kind,x.supplier,x.party_name,x.reference,"
            "x.currency,x.amount,x.base_amount,x.due_date,"
            "x.invoice_currency,x.invoice_amount,x.creation "
            "FROM ("
            "SELECT o.name,'Opening Payable' AS kind,o.supplier,p.party_name,"
            "o.opening_source_name AS reference,o.currency,o.amount,"
            "o.base_amount,o.due_date,NULL AS invoice_currency,"
            "NULL AS invoice_amount,o.creation "
            "FROM `tabHS PMS Opening Payable` o "
            "LEFT JOIN `tabHS Party` p ON p.name=o.supplier AND p.property=o.property "
            "WHERE o.property=%s AND o.status='Posted' "
            "AND (%s='' OR o.supplier=%s) AND (%s='' OR o.currency=%s) "
            "AND (%s='' OR LOCATE(%s,o.name)>0 OR "
            "LOCATE(%s,o.opening_source_name)>0 OR LOCATE(%s,p.party_name)>0) "
            "UNION ALL "
            "SELECT b.name,'Purchase' AS kind,b.supplier,p.party_name,"
            "b.supplier_reference AS reference,%s AS currency,b.base_amount AS amount,"
            "b.base_amount,NULL AS due_date,b.invoice_currency,"
            "b.invoice_amount,b.creation "
            "FROM `tabHS PMS Purchase` b "
            "LEFT JOIN `tabHS Party` p ON p.name=b.supplier AND p.property=b.property "
            "WHERE b.property=%s AND b.status='Posted' "
            "AND (%s='' OR b.supplier=%s) AND (%s='' OR %s=%s) "
            "AND (%s='' OR LOCATE(%s,b.name)>0 OR "
            "LOCATE(%s,b.supplier_reference)>0 OR LOCATE(%s,p.party_name)>0)"
            ") x ORDER BY x.creation DESC,x.name DESC LIMIT %s OFFSET %s",
            (prop.name, supplier, supplier, currency, currency,
             term, term, term, term,
             prop.currency, prop.name, supplier, supplier,
             currency, currency, prop.currency,
             term, term, term, term, page_length + 1, offset), as_dict=True)
        from hospitality_suite.standalone_opening_payables import _balances
        from hospitality_suite.standalone_purchases import outstanding
        from hospitality_suite.service import locked_doc
        page_rows = []
        for row in rows[:page_length]:
            row.pop("creation", None)
            if row.kind == "Opening Payable":
                nominal, base = _balances(prop,
                    locked_doc("HS PMS Opening Payable", row.name))
            else:
                nominal = base = outstanding(prop, row.name)
            page_rows.append({**row, "outstanding": _money(nominal),
                              "base_outstanding": _money(base)})
    else:
        rows = frappe.db.sql(
            "SELECT a.name,a.opening_credit,a.target_type,a.opening_payable,"
            "a.purchase,a.currency,a.amount,c.opening_source_name AS credit_reference,"
            "COALESCE(o.opening_source_name,b.supplier_reference) AS target_reference,"
            "p.party_name,c.supplier "
            "FROM `tabHS PMS Supplier Credit Allocation` a "
            "JOIN `tabHS PMS Opening Supplier Credit` c "
            "ON c.name=a.opening_credit AND c.property=a.property "
            "LEFT JOIN `tabHS PMS Opening Payable` o "
            "ON o.name=a.opening_payable AND o.property=a.property "
            "LEFT JOIN `tabHS PMS Purchase` b "
            "ON b.name=a.purchase AND b.property=a.property "
            "LEFT JOIN `tabHS Party` p ON p.name=c.supplier AND p.property=c.property "
            "LEFT JOIN (SELECT reverses,SUM(amount) AS reversed_amount "
            "FROM `tabHS PMS Supplier Credit Allocation` "
            "WHERE property=%s AND kind='Reversed' GROUP BY reverses) r "
            "ON r.reverses=a.name "
            "WHERE a.property=%s AND a.kind='Applied' "
            "AND a.amount>COALESCE(r.reversed_amount,0) "
            "AND (%s='' OR c.supplier=%s) AND (%s='' OR a.currency=%s) "
            "AND (%s='' OR LOCATE(%s,a.name)>0 OR "
            "LOCATE(%s,c.opening_source_name)>0 OR "
            "LOCATE(%s,COALESCE(o.opening_source_name,b.supplier_reference))>0 "
            "OR LOCATE(%s,p.party_name)>0) "
            "ORDER BY a.creation DESC,a.name DESC LIMIT %s OFFSET %s",
            (prop.name, prop.name, supplier, supplier, currency, currency,
             term, term, term, term, term, page_length + 1, offset), as_dict=True)
        from hospitality_suite.standalone_opening_supplier_credits import remaining_application
        page_rows = [{**row, "kind": kind,
                      "remaining": _money(remaining_application(prop, row.name))}
                     for row in rows[:page_length]]
    return {"rows": page_rows, "search": term, "offset": offset,
            "has_more": len(rows) > page_length}
