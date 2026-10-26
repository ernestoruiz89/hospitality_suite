"""Day Pass access without a room, billed as a registered counter service."""
import hashlib

import frappe
from frappe.utils import get_datetime, now_datetime

from hospitality_suite import direct_sales
from hospitality_suite.availability_search import positive_integer
from hospitality_suite.service import audit, canonical, insert
from hospitality_suite.time import local, to_site


def erp_snapshot(property_name):
    """The counter-sale view of roomless Day Pass after an ERPNext cutover."""
    from hospitality_suite import standalone_accounting
    from hospitality_suite.security import require

    prop = require(property_name, "finance")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte los Day Pass desde la contabilidad PMS"))
    guests = frappe.get_all("HS Guest", filters={"property": prop.name,
                                                  "company": prop.company},
                         fields=["name", "full_name", "customer"],
                         order_by="full_name asc", limit_page_length=1000)
    parties = frappe.get_all("HS Billing Party", filters={"property": prop.name,
                                                         "company": prop.company},
                          fields=["customer"], limit_page_length=1000)
    customer_ids = sorted({row.customer for row in guests + parties if row.customer})
    customer_names = {row.name: row.customer_name for row in
                      frappe.get_all("Customer", filters={"name": ["in", customer_ids]},
                                     fields=["name", "customer_name"],
                                     limit_page_length=1000)} if customer_ids else {}
    rows = frappe.get_all("HS Day Pass", filters={"property": prop.name,
                                                "company": prop.company},
                       fields=["name", "modified", "customer", "guest", "people", "starts_at",
                               "ends_at", "status", "service", "sales_invoice",
                               "payment", "pms_receivable", "erp_opening_invoice",
                               "erp_opening_snapshot", "erp_opening_sha256",
                               "erp_return_credit_note", "erp_return_refund",
                               "erp_return_corrections"],
                       order_by="creation desc", limit_page_length=100)
    invoice_ids = sorted({name for row in rows for name in
        (row.sales_invoice, row.erp_opening_invoice) if name})
    invoices = {row.name: row for row in frappe.get_all(
        "Sales Invoice", filters={"name": ["in", invoice_ids],
                                   "company": prop.company, "hs_property": prop.name},
        fields=["name", "grand_total", "outstanding_amount", "currency", "docstatus"],
        limit_page_length=100)} if invoice_ids else {}
    service_ids = [row.service for row in rows if row.service]
    services = {row.name: row.status for row in frappe.get_all(
        "HS Service Request", filters={"property": prop.name,
                                       "company": prop.company,
                                       "name": ["in", service_ids]},
        fields=["name", "status"], limit_page_length=100)} if service_ids else {}
    now = now_datetime()
    for row in rows:
        corrections = row.pop("erp_return_corrections")
        row["correction_count"] = len(frappe.parse_json(corrections)) if corrections else 0
        historical = bool(row.pms_receivable)
        invoice = invoices.get(row.erp_opening_invoice if historical else
                               row.sales_invoice)
        legacy_without_bridge = (historical and not row.erp_opening_invoice and
            not row.erp_opening_snapshot and not row.erp_opening_sha256)
        if legacy_without_bridge:
            row["amount"] = None
            row["currency"] = prop.currency
            row["outstanding"] = None
            row["historical_invoice_number"] = None
            row["historical"] = True
            row["transfer_problem"] = True
        elif historical:
            proof = frappe.parse_json(row.erp_opening_snapshot or "{}")
            if (not isinstance(proof, dict) or not row.erp_opening_sha256 or
                    hashlib.sha256(str(row.erp_opening_snapshot or "").encode()
                        ).hexdigest() != row.erp_opening_sha256 or
                    proof.get("source") != row.name or
                    proof.get("property") != prop.name or
                    proof.get("customer") != row.customer or
                    proof.get("source_receivable") != row.pms_receivable or
                    proof.get("opening_invoice") != row.erp_opening_invoice or
                    bool(invoice) != bool(row.erp_opening_invoice)):
                frappe.throw(frappe._(
                    "La continuación ERPNext del Day Pass no concilia"))
            sale = proof["accepted_sale"]
            fiscal = proof["source_fiscal"]
            row["amount"] = sale["total_amount"]
            row["currency"] = prop.currency
            row["outstanding"] = (str(invoice.outstanding_amount)
                if invoice else "0")
            row["historical_invoice_number"] = (
                fiscal["invoice"]["document_number"]
                if fiscal.get("invoice") else None)
            row["historical"] = True
            row["transfer_problem"] = False
        else:
            row["amount"] = str(invoice.grand_total) if invoice else None
            row["currency"] = invoice.currency if invoice else prop.currency
            row["outstanding"] = str(invoice.outstanding_amount) if invoice else None
            row["historical_invoice_number"] = None
            row["historical"] = False
            row["transfer_problem"] = False
        row["can_return"] = bool(row.status == "Issued" and (
            (historical and not row.transfer_problem and
             not row.erp_return_credit_note and not row.erp_return_refund and
             (not invoice or invoice.docstatus == 1)) or
            (not historical and row.service and
             services.get(row.service) == "Delivered" and invoice and
             invoice.docstatus == 1)))
        row["effective_status"] = ("Cancelled" if row.status == "Cancelled" else
                                   "Upcoming" if get_datetime(row.starts_at) > now else
                                   "Expired" if get_datetime(row.ends_at) <= now else "Active")
        row.pop("erp_opening_snapshot", None)
        row.pop("erp_opening_sha256", None)
        row["starts_at"] = local(row.starts_at, prop).isoformat()
        row["ends_at"] = local(row.ends_at, prop).isoformat()
    item = (frappe.db.get_value("Item", prop.day_pass_item,
                                ["name", "item_name", "disabled", "is_stock_item"],
                                as_dict=True) if prop.day_pass_item else None)
    methods = frappe.get_all("HS Payment Method", filters={"property": prop.name,
                                                       "company": prop.company},
                          fields=["name", "mode_of_payment", "currency", "is_cash",
                                  "reference_required"], order_by="mode_of_payment asc")
    shifts = frappe.get_all("HS Shift", filters={"property": prop.name,
                                                 "company": prop.company,
                                                 "status": "Open"},
                         fields=["name", "cashier", "currency", "status"],
                         order_by="creation desc")
    return {"currency": prop.currency, "time_zone": prop.time_zone,
            "item": item, "price_list": prop.price_list,
            "receivable_account": prop.receivable_account,
            "customers": [{"name": name, "party_name": customer_names.get(name, name)}
                          for name in customer_ids if name in customer_names],
            "guests": guests, "methods": methods, "shifts": shifts,
            "day_passes": rows}


def _context(prop, data):
    item = prop.get("day_pass_item")
    if not item:
        frappe.throw(frappe._("Configure el artículo de Day Pass sin habitación"))
    if frappe.db.get_value("Item", item, "is_stock_item"):
        frappe.throw(frappe._("Day Pass sin habitación requiere un artículo de servicio sin inventario"))
    people = positive_integer(data.get("people"), frappe._("Personas del Day Pass"))
    if people > 100:
        frappe.throw(frappe._("Day Pass admite hasta 100 personas por venta"))
    start, end = to_site(data["starts_at"], prop), to_site(data["ends_at"], prop)
    if end <= start or local(start, prop).date() != local(end, prop).date():
        frappe.throw(frappe._("Day Pass requiere entrada y salida en el mismo día local"))
    if end <= now_datetime():
        frappe.throw(frappe._("No puede emitir un Day Pass cuyo período ya terminó"))
    guest = data.get("guest")
    if guest and frappe.db.get_value("HS Guest", guest, "property") != prop.name:
        frappe.throw(frappe._("El huésped no pertenece al establecimiento"), frappe.PermissionError)
    return dict(item=item, people=people, starts_at=start, ends_at=end, guest=guest)


def quote_without_room(prop, data):
    context = _context(prop, data)
    sale = direct_sales.quote(prop, {**data, "item": context["item"], "quantity": context["people"]})
    result = {**sale, "people": context["people"], "starts_at": str(context["starts_at"]),
              "ends_at": str(context["ends_at"]), "guest": context["guest"],
              "sale_acceptance": sale["acceptance"]}
    result["acceptance"] = hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def sell_without_room(prop, data):
    quote = quote_without_room(prop, data)
    if data.get("acceptance") != quote["acceptance"]:
        frappe.throw(frappe._("Revise y acepte la cotización vigente de Day Pass"))
    sale = direct_sales.sell(prop, {**data, "item": prop.day_pass_item,
                                   "quantity": quote["people"], "acceptance": quote["sale_acceptance"]})
    doc = insert("HS Day Pass", prop, customer=data["customer"], guest=quote["guest"], people=quote["people"],
                 starts_at=quote["starts_at"], ends_at=quote["ends_at"], status="Issued",
                 service=sale["service"], sales_invoice=sale["invoice"], payment=sale["payment"],
                 notes=data.get("notes"))
    audit(prop, "Day Pass issued", doc, details=dict(service=sale["service"], invoice=sale["invoice"]))
    return {**sale, "day_pass": doc.name}
