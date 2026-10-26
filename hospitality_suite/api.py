"""Authenticated API for Desk Pages. Every mutation is POST + scoped + idempotent."""
import json
from decimal import Decimal

import frappe
from frappe.utils import now_datetime

from hospitality_suite import operations, cashier, housekeeping, inventory, accounting, closing, linen, portal,timing,direct_sales,treasury,procurement,privacy,tickets,credit,day_pass,financial_movements,guest_laundry,room_blocks,travel_experiences
from hospitality_suite import pms_cutover, pms_cutover_mapping, pms_cutover_plan
from hospitality_suite.security import allowed_properties, require, document, property_document, ACTIONS, is_system, selected_property, petty_handover_users
from hospitality_suite.service import command, insert, audit, canonical, current_all
from hospitality_suite.time import to_site, now_local
from hospitality_suite.schema import PAGES, PAGE_ICONS, PAGE_MODULES, NAV_MODULES
from hospitality_suite import setup
from hospitality_suite import user_settings
from hospitality_suite import service_accounting
from hospitality_suite import periodic
from hospitality_suite import booking_drafts
from hospitality_suite import standalone_accounting
from hospitality_suite import standalone_coa
from hospitality_suite import standalone_currency
from hospitality_suite import standalone_cash, standalone_receivables
from hospitality_suite import standalone_tax
from hospitality_suite import standalone_fiscal
from hospitality_suite import erp_fiscal_history
from hospitality_suite import erp_to_pms_mapping
from hospitality_suite import erp_to_pms_balance_preview as reverse_balance_preview
from hospitality_suite import erp_to_pms_transfer_plan as reverse_transfer_plan
from hospitality_suite import erp_to_pms_transfer_rehearsal as reverse_transfer_rehearsal
from hospitality_suite import standalone_agency_commissions
from hospitality_suite import standalone_folio_services
from hospitality_suite import standalone_reception
from hospitality_suite import standalone_departure
from hospitality_suite import standalone_credit
from hospitality_suite import standalone_services
from hospitality_suite import standalone_inventory
from hospitality_suite import standalone_purchases
from hospitality_suite import standalone_opening_payables
from hospitality_suite import standalone_opening_credits
from hospitality_suite import standalone_opening_guarantees
from hospitality_suite import standalone_opening_supplier_credits
from hospitality_suite import standalone_supplier_paging
from hospitality_suite import standalone_purchase_paging
from hospitality_suite import standalone_purchase_orders
from hospitality_suite import standalone_purchase_returns
from hospitality_suite import standalone_financing
from hospitality_suite import standalone_petty_cash
from hospitality_suite import standalone_closing
from hospitality_suite import standalone_reports
from hospitality_suite import standalone_day_pass
from hospitality_suite import standalone_direct_sales
from hospitality_suite import erp_historical_day_pass
from hospitality_suite import erp_historical_direct_sales
from hospitality_suite import standalone_maintenance_parts
from hospitality_suite import standalone_linen
from hospitality_suite import erp_cash
from hospitality_suite.inputs import object_payload as payload


def _request_service(prop, data):
    return (standalone_services.request(prop, data) if standalone_accounting.provider() == "pms"
            else inventory.request_service(prop, data))


def _update_service(prop, data):
    return (standalone_services.update(prop, data) if standalone_accounting.provider() == "pms"
            else inventory.update_service(prop, data))


def _daily_close(prop, data):
    return (standalone_closing.close(prop, data) if standalone_accounting.provider() == "pms"
            else closing.daily_close(prop, data))


def _day_pass_no_room(prop, data):
    return (standalone_day_pass.issue(prop, data) if standalone_accounting.provider() == "pms"
            else day_pass.sell_without_room(prop, data))


def _maintenance_parts(prop, data):
    return (standalone_maintenance_parts.change(prop, data)
            if standalone_accounting.provider() == "pms"
            else housekeeping.maintenance_parts(prop, data))


def _linen(prop, data):
    return (standalone_linen.move(prop, data)
            if standalone_accounting.provider() == "pms"
            else linen.move_linen(prop, data))

COMMANDS = {
    "pms_account": ("chart", standalone_accounting.save_account),
    "pms_coa_import": ("chart", standalone_coa.import_chart),
    "pms_currencies": ("chart", standalone_currency.configure),
    "erp_property_currencies": ("chart", standalone_currency.configure_erp),
    "pms_exchange_rate": ("chart", standalone_currency.record_rate),
    "pms_payment_method": ("chart", standalone_cash.setup_method),
    "pms_expense_category": ("chart", standalone_cash.setup_category),
    "pms_income_concept": ("chart", standalone_cash.setup_concept),
    "pms_income_concept_update": ("chart", standalone_cash.update_concept),
    "pms_customer": ("finance", standalone_cash.create_customer),
    "pms_tax_profile": ("chart", standalone_tax.setup),
    "pms_fiscal_series": ("setup", standalone_fiscal.create_series),
    "pms_issue_invoice": ("finance", standalone_fiscal.issue_invoice),
    "pms_direct_sale": ("finance", standalone_direct_sales.sell),
    "pms_direct_sale_return": ("approve", standalone_direct_sales.return_sale),
    "erp_historical_direct_sale_return": ("approve", erp_historical_direct_sales.return_sale),
    "erp_historical_direct_sale_return_reversal": ("approve", erp_historical_direct_sales.reverse_return),
    "pms_issue_credit_note": ("approve", standalone_fiscal.issue_credit),
    "pms_warehouse": ("setup", standalone_inventory.create_warehouse),
    "pms_opening_stock": ("inventory", standalone_inventory.opening_stock),
    "pms_transfer_stock": ("inventory", standalone_inventory.transfer_stock),
    "pms_count_stock": ("approve", standalone_inventory.count_stock),
    "pms_supplier": ("inventory", standalone_purchases.create_supplier),
    "pms_order_request": ("inventory", standalone_purchase_orders.request),
    "pms_order_approve": ("approve", standalone_purchase_orders.approve),
    "pms_order_close": ("inventory", standalone_purchase_orders.close),
    "pms_receive_purchase": ("inventory", standalone_purchases.receive_purchase),
    "pms_pay_supplier": ("finance", standalone_purchases.pay_supplier),
    "pms_pay_opening_supplier": ("finance", standalone_opening_payables.pay),
    "pms_apply_opening_credit": ("finance", standalone_opening_credits.apply),
    "pms_unapply_opening_credit": ("approve", standalone_opening_credits.unapply),
    "pms_refund_opening_credit": ("approve", standalone_opening_credits.refund),
    "pms_refund_opening_guarantee": ("approve", standalone_opening_guarantees.refund),
    "pms_apply_opening_guarantee": ("approve", standalone_opening_guarantees.apply),
    "pms_unapply_opening_guarantee": ("approve", standalone_opening_guarantees.unapply),
    "pms_apply_opening_supplier_credit": ("finance", standalone_opening_supplier_credits.apply),
    "pms_unapply_opening_supplier_credit": ("approve", standalone_opening_supplier_credits.unapply),
    "pms_refund_opening_supplier_credit": ("finance", standalone_opening_supplier_credits.refund),
    "pms_pay_agent_commission": ("finance", standalone_agency_commissions.pay),
    "pms_cancel_agent_commission": ("approve", standalone_agency_commissions.cancel),
    "pms_return_purchase": ("approve", standalone_purchase_returns.return_purchase),
    "pms_cancel_purchase": ("approve", standalone_purchase_returns.cancel_purchase),
    "pms_supplier_refund": ("finance", standalone_purchase_returns.refund),
    "pms_financing_request": ("finance", standalone_financing.request),
    "pms_financing_approve": ("approve", standalone_financing.approve),
    "pms_financing_cancel": ("finance", standalone_financing.cancel_request),
    "pms_financing_post": ("finance", standalone_financing.post_movement),
    "pms_petty_configure": ("setup", standalone_petty_cash.configure),
    "pms_petty_fund": ("finance", standalone_petty_cash.fund),
    "pms_petty_expense": ("petty", standalone_petty_cash.expense),
    "pms_petty_correct": ("petty", standalone_petty_cash.correct_expense),
    "pms_petty_submit": ("petty", standalone_petty_cash.submit),
    "pms_petty_review": ("approve", standalone_petty_cash.review),
    "pms_petty_handover": ("approve", standalone_petty_cash.handover_request),
    "pms_petty_accept": ("petty", standalone_petty_cash.handover_accept),
    "pms_petty_handover_cancel": ("approve", standalone_petty_cash.handover_cancel),
    "pms_petty_reverse": ("approve", standalone_petty_cash.reverse),
    "pms_daily_close": ("approve", standalone_closing.close),
    "pms_open_shift": ("finance", standalone_cash.open_shift),
    "pms_close_shift": ("finance", standalone_cash.close_shift),
    "pms_cash_movement": ("finance", standalone_cash.post_movement),
    "pms_refund": ("approve", standalone_cash.refund),
    "pms_receivable": ("chart", standalone_receivables.create),
    "pms_bill_folio": ("finance", standalone_receivables.bill_folio),
    "pms_add_folio_service": ("finance", standalone_folio_services.add_charge),
    "pms_adjust_folio_charge": ("approve", standalone_folio_services.adjust_charge),
    "pms_create_guest": ("guest", standalone_reception.create_guest),
    "pms_credit_terms": ("approve", standalone_credit.update_terms),
    "pms_credit_policy": ("approve", standalone_credit.update_policy),
    "pms_apply_advance": ("finance", standalone_receivables.apply_advance),
    "pms_unapply_advance": ("approve", standalone_receivables.unapply_advance),
    "pms_apply_guarantee": ("approve", standalone_receivables.apply_guarantee),
    "pms_unapply_guarantee": ("approve", standalone_receivables.unapply_guarantee),
    "pms_cancel_receivable": ("approve", standalone_receivables.cancel),
    "pms_day_pass_cancel": ("approve", standalone_day_pass.cancel),
    "pms_historical_day_pass_return": ("approve", standalone_day_pass.historical_return),
    "erp_historical_day_pass_return": ("approve", erp_historical_day_pass.return_pass),
    "erp_historical_day_pass_return_reversal": ("approve", erp_historical_day_pass.reverse_return),
    "pms_opening_balance": ("setup", standalone_accounting.opening_balance),
    "pms_manual_journal": ("journal", standalone_accounting.manual_journal),
    "pms_reverse_journal": ("approve", standalone_accounting.reverse),
    "travel_agent": ("setup", travel_experiences.save_agent),
    "experience": ("setup", travel_experiences.save_experience),
    "experience_order": ("reserve", travel_experiences.order_experience),
    "experience_status": ("service", travel_experiences.update_order),
    "pms_direct_experience_order": ("finance", travel_experiences.direct_order),
    "pms_legacy_direct_experience_review": ("approve", travel_experiences.freeze_legacy_direct),
    "pms_direct_experience_status": ("finance", travel_experiences.update_direct_order),
    "agent_commission": ("commission", travel_experiences.settle_commission),
    "room_block": ("block", room_blocks.create),
    "room_unblock": ("block", room_blocks.release),
    "laundry_rate": ("setup", guest_laundry.save_rate),
    "laundry_request": ("laundry", guest_laundry.request_pickup),
    "laundry_collect": ("laundry", guest_laundry.collect),
    "laundry_advance": ("laundry", guest_laundry.advance),
    "laundry_return": ("laundry", guest_laundry.return_pieces),
    "laundry_deliver": ("laundry", guest_laundry.deliver),
    "laundry_cancel": ("laundry", guest_laundry.cancel),
    "ticket": ("ticket", tickets.change),
    "billing_party": ("setup", credit.update),
    'save_booking_draft':('reserve',booking_drafts.save),
    'confirm_booking_draft':('reserve',booking_drafts.confirm),
    'discard_booking_draft':('reserve',booking_drafts.discard),
    "generate_lodging":("finance",periodic.generate_command),
    "service_accounting":("setup",service_accounting.save),
    "reserve": ("reserve", operations.reserve), "booking_status": ("reserve", operations.update_booking),
    "check_in": ("stay", operations.check_in), "walk_in": ("stay", operations.walk_in),
    "extend": ("stay", operations.extend), "change_room": ("stay", operations.change_room),
    "check_out": ("stay", operations.check_out), "create_folio": ("stay", operations.create_folio),
    "move_charge": ("stay", operations.move_charge), "invoice": ("finance", accounting.invoice_folio),
    "payment": ("finance", accounting.payment), "open_shift": ("finance", cashier.open_shift),
    "apply_customer_advance": ("finance", accounting.apply_customer_advance),
    "close_shift": ("finance", cashier.close_shift), "cleaning": ("clean", housekeeping.update_cleaning),
    "maintenance": ("maintain", housekeeping.maintenance), "request_service": ("service", _request_service),
    "maintenance_parts":("maintain",_maintenance_parts),
    "update_service": ("service", _update_service), "daily_close": ("report", _daily_close),
    "reopen_day": ("approve", closing.reopen),
    "credit_note": ("approve", accounting.credit_note),
    "apply_guarantee": ("approve", accounting.apply_guarantee),
    "incident": ("incident", linen.incident), "linen": ("clean", _linen),
    "convert_portal": ("reserve", portal.convert), "reject_portal": ("reserve", portal.reject), "portal_link": ("reserve", portal.link),
    "withdrawal": ("finance",cashier.withdrawal),
    "modify_reservation": ("reserve",operations.modify_reservation),
    "prepare_departure":("stay",timing.prepare_departure),"inspect_departure":("inspect",timing.inspect_departure),
    "adjustment":("approve",operations.adjustment),
    "schedule_cleaning":("inspect",housekeeping.schedule_cleaning),
    "direct_sale":("finance",direct_sales.sell),"return_direct_sale":("approve",direct_sales.return_sale),
    "day_pass_no_room":("finance",_day_pass_no_room),
    "assign_user":("setup",setup.assign_user),
    "revoke_user_access":("setup",setup.revoke_user_access),
    "companions":("guest",operations.companions),
    "cash_expense":("finance",treasury.expense),
    "cash_expense_reviewed":("finance",treasury.reviewed_expense),
    "settle_payment":("finance",treasury.settle),
    "purchase_order":("inventory",procurement.purchase_order),"receive_purchase":("inventory",procurement.receive_purchase),
    "purchase_invoice":("inventory",procurement.purchase_invoice),"supplier_payment":("finance",procurement.supplier_payment),
    "move_stock":("inventory",procurement.move_stock),"adjust_stock":("approve",procurement.adjust_stock),
    "register_supplier":("inventory",procurement.register_supplier),
    "create_warehouse":("inventory",procurement.create_warehouse),"stock_policy":("setup",procurement.stock_policy),
    "retire_sensitive":("approve",privacy.retire),"retry_retention":("approve",privacy.retry),
    "petty_fund": ("finance", financial_movements.fund_transfer),
    "petty_expense": ("petty", financial_movements.petty_expense),
    "petty_correct": ("petty", financial_movements.correct_expense),
    "petty_rendition": ("petty", financial_movements.submit_rendition),
    "petty_review": ("approve", financial_movements.review_rendition),
    "petty_handover": ("approve", financial_movements.request_handover),
    "petty_accept": ("petty", financial_movements.accept_handover),
    "petty_handover_cancel": ("approve", financial_movements.cancel_handover),
    "finance_request": ("finance", financial_movements.financing_request),
    "finance_approve": ("approve", financial_movements.approve_financing),
    "finance_cancel_request": ("finance", financial_movements.cancel_financing_request),
    "finance_post": ("finance", financial_movements.post_financial),
    "finance_reverse": ("approve", financial_movements.reverse),
    "finance_concept": ("setup", financial_movements.update_concept),
}


# These handlers post or configure ERPNext's own hotel book. The PMS commands
# remain available while ERPNext is installed for mapping and rehearsal; only
# the verified authority switch enables these legacy handlers.
ERP_ONLY_ACTIONS = frozenset({
    "erp_property_currencies",
    "billing_party", "service_accounting", "invoice", "payment",
    "apply_customer_advance", "open_shift", "close_shift",
    "credit_note", "apply_guarantee", "withdrawal",
    "direct_sale", "return_direct_sale", "erp_historical_day_pass_return",
    "erp_historical_day_pass_return_reversal",
    "erp_historical_direct_sale_return_reversal",
    "cash_expense", "cash_expense_reviewed",
    "settle_payment", "purchase_order", "receive_purchase",
    "purchase_invoice", "supplier_payment", "move_stock", "adjust_stock",
    "register_supplier", "create_warehouse", "stock_policy",
    "petty_fund", "petty_expense", "petty_correct", "petty_rendition",
    "petty_review", "petty_handover", "petty_accept", "petty_handover_cancel",
    "finance_request", "finance_approve", "finance_cancel_request", "finance_post",
    "finance_reverse", "finance_concept",
})


@frappe.whitelist()
def pms_trial_balance(property_name, through_date=None):
    return standalone_accounting.trial_balance(property_name, through_date)


@frappe.whitelist()
def pms_accounts(property_name):
    return standalone_accounting.list_accounts(property_name)


@frappe.whitelist()
def pms_opening_balance_status(property_name):
    return standalone_accounting.opening_status(property_name)


@frappe.whitelist()
def pms_reversible_journals(property_name, search="", offset=0,
                            page_length=25):
    return standalone_accounting.reversible_journals(
        property_name, search, offset, page_length)


@frappe.whitelist()
def pms_chart(property_name):
    rows = standalone_accounting.chart(property_name)
    account_types = next(field["options"].split("\n") for field in standalone_coa.SCHEMA["HS Account"]["fields"]
                         if field["fieldname"] == "account_type")
    return {"accounts": rows, "account_types": [name for name in account_types if name],
            "currencies": frappe.get_all("Currency", filters={"enabled": 1}, pluck="name", order_by="name asc")}


@frappe.whitelist(methods=["POST"])
def pms_coa_preview(property_name, file_name, content_base64):
    return standalone_coa.preview(property_name, file_name, content_base64)


@frappe.whitelist()
def pms_coa_export(property_name):
    return standalone_coa.export_chart(property_name)


@frappe.whitelist()
def pms_currency_settings(property_name):
    return standalone_currency.settings(property_name)


@frappe.whitelist()
def erp_property_currency_settings(property_name):
    return standalone_currency.erp_settings(property_name)


@frappe.whitelist()
def pms_cash_snapshot(property_name, folio=None, receivable=None):
    return standalone_cash.snapshot(property_name, folio=folio, receivable=receivable)


@frappe.whitelist()
def pms_customers(property_name):
    return standalone_cash.customers(property_name)


@frappe.whitelist()
def pms_receivables(property_name):
    return standalone_receivables.snapshot(property_name)


@frappe.whitelist()
def pms_receivables_page(property_name, search="", offset=0, page_length=25,
                         party="", currency="", folio="", stay="", booking=""):
    return standalone_receivables.receivables_page(property_name, search, offset,
        page_length, party, currency, folio, stay, booking)


@frappe.whitelist()
def pms_deposits_page(property_name, receivable, kind="Advance", search="",
                      offset=0, page_length=25):
    return standalone_receivables.deposits_page(property_name, receivable,
        kind, search, offset, page_length)


@frappe.whitelist()
def pms_applications_page(property_name, kind="Advance", search="",
                          offset=0, page_length=25):
    return standalone_receivables.applications_page(property_name, kind,
        search, offset, page_length)


@frappe.whitelist()
def pms_opening_balances_page(property_name, kind="Credit", search="",
                              offset=0, page_length=25):
    return standalone_receivables.opening_balances_page(property_name, kind,
        search, offset, page_length)


@frappe.whitelist()
def pms_supplier_document_page(property_name, kind="Target", search="",
                               supplier="", currency="", offset=0, page_length=25):
    return standalone_supplier_paging.page(property_name, kind, search, supplier,
        currency, offset, page_length)


@frappe.whitelist()
def pms_supplier_payment_page(property_name, search="", offset=0, page_length=25):
    return standalone_supplier_paging.payments_page(property_name, search,
        offset, page_length)


@frappe.whitelist()
def pms_purchase_document_page(property_name, kind="Purchase", search="",
                               offset=0, page_length=25, available_only=0):
    return standalone_purchase_paging.page(property_name, kind, search, offset,
        page_length, available_only)


@frappe.whitelist()
def pms_fiscal_snapshot(property_name):
    return standalone_fiscal.snapshot(property_name)


@frappe.whitelist()
def pms_fiscal_candidates(property_name, kind="ready", search="", offset=0,
                          page_length=50):
    return standalone_fiscal.candidates(property_name, kind, search, offset,
                                        page_length)


@frappe.whitelist()
def pms_fiscal_archive(property_name, offset=0, page_length=50, search=""):
    return standalone_fiscal.archive(property_name, offset, page_length, search)


@frappe.whitelist()
def historical_fiscal_archive(property_name, offset=0, page_length=50, search=""):
    return erp_fiscal_history.archive(property_name, offset, page_length, search)


@frappe.whitelist()
def historical_fiscal_pdf(document):
    return erp_fiscal_history.pdf_response(document)


@frappe.whitelist()
def erp_fiscal_archive(property_name, offset=0, page_length=50, search=""):
    """Find native invoices and credit notes scoped to one ERPNext property."""
    prop = require(property_name, "finance")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("El archivo ERPNext requiere el proveedor contable activo"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación del archivo fiscal"))
    if offset < 0 or not 1 <= page_length <= 100:
        frappe.throw(frappe._("Revise la paginación del archivo fiscal"))
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda del archivo fiscal"))
    where = "si.hs_property=%s AND si.company=%s AND si.docstatus IN (1,2)"
    values = [prop.name, prop.company]
    if search.strip():
        where += " AND (si.name LIKE %s OR si.customer_name LIKE %s OR si.return_against LIKE %s)"
        values.extend(["%" + search.strip() + "%"] * 3)
    total = frappe.db.sql("SELECT COUNT(*) FROM `tabSales Invoice` si WHERE " + where,
                          values, as_list=True)[0][0]
    rows = frappe.db.sql(
        "SELECT si.name,si.posting_date,si.customer_name,si.currency,"
        "si.grand_total,si.is_return,si.return_against,si.is_opening,si.docstatus "
        "FROM `tabSales Invoice` si WHERE " + where +
        " ORDER BY si.posting_date DESC,si.creation DESC,si.name DESC "
        "LIMIT %s OFFSET %s", [*values, page_length, offset], as_dict=True)
    allow_cancelled_print = bool(int(frappe.db.get_single_value(
        "Print Settings", "allow_print_for_cancelled") or 0))
    return {"property": prop.name, "total": int(total), "offset": offset,
        "page_length": page_length,
        "documents": [{"name": row.name, "posting_date": str(row.posting_date),
            "buyer_name": row.customer_name, "currency": row.currency,
            "total_amount": str(abs(Decimal(str(row.grand_total or 0)))),
            "document_type": "Credit Note" if row.is_return else "Invoice",
            "source_invoice": row.return_against,
            "is_opening": row.is_opening == "Yes",
            "status": "Cancelled" if row.docstatus == 2 else "Posted",
            "can_print": row.docstatus == 1 or allow_cancelled_print}
            for row in rows]}


@frappe.whitelist()
def pms_departure_snapshot(property_name):
    return standalone_departure.snapshot(property_name)


@frappe.whitelist()
def erp_departure_snapshot(property_name):
    return standalone_departure.snapshot(property_name, "erpnext")


@frappe.whitelist()
def pms_departure_detail(property_name, stay):
    return standalone_departure.detail(property_name, stay)


@frappe.whitelist()
def erp_departure_detail(property_name, stay):
    return standalone_departure.detail(property_name, stay, "erpnext")


@frappe.whitelist()
def pms_credit_overview(property_name, offset=0, page_length=50):
    return standalone_credit.overview(property_name, offset, page_length)


@frappe.whitelist()
def pms_credit_status(property_name, party):
    return standalone_credit.status(property_name, party)


@frappe.whitelist()
def pms_service_snapshot(property_name, stay=None):
    return standalone_services.snapshot(property_name, stay)


@frappe.whitelist()
def erp_service_snapshot(property_name, stay=None):
    return inventory.erp_service_snapshot(property_name, stay)


@frappe.whitelist()
def erp_direct_sale_options(property_name):
    return direct_sales.options(property_name)


@frappe.whitelist()
def erp_direct_sale_customers(property_name, search="", offset=0, page_length=25):
    return direct_sales.customer_page(property_name, search, offset, page_length)


@frappe.whitelist()
def erp_direct_sale_history(property_name, search="", offset=0, page_length=25,
                            returnable=0):
    return direct_sales.history(property_name, search, offset, page_length, returnable)


@frappe.whitelist()
def pms_direct_sale_options(property_name):
    return standalone_direct_sales.options(property_name)


@frappe.whitelist()
def pms_direct_sale_customers(property_name, search="", offset=0, page_length=25):
    return standalone_direct_sales.customer_page(property_name, search, offset, page_length)


@frappe.whitelist()
def pms_direct_sale_products(property_name, search="", offset=0, page_length=25):
    return standalone_direct_sales.product_page(property_name, search, offset, page_length)


@frappe.whitelist()
def pms_direct_sale_history(property_name, search="", offset=0, page_length=25,
                            returnable=0):
    return standalone_direct_sales.history(property_name, search, offset,
                                           page_length, returnable)


@frappe.whitelist()
def pms_inventory_snapshot(property_name):
    return standalone_inventory.snapshot(property_name)


@frappe.whitelist()
def erp_inventory_snapshot(property_name):
    prop = require(property_name, "inventory")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte las existencias desde Inventario PMS"))
    names = procurement.warehouses(prop)
    rows = frappe.get_all("Warehouse", filters={"name": ["in", names],
                                             "company": prop.company},
                          fields=["name", "warehouse_name"],
                          limit_page_length=len(names)) if names else []
    categories = frappe.get_all("HS Expense Category", filters={
        "property": prop.name, "company": prop.company, "active": 1},
        fields=["name", "label", "account"], order_by="label asc",
        limit_page_length=200)
    return {"currency": frappe.db.get_value("Company", prop.company,
                                             "default_currency"),
            "default_warehouse": prop.warehouse,
            "warehouses": rows, "categories": categories}


@frappe.whitelist()
def erp_purchases_snapshot(property_name):
    prop = require(property_name)
    if not (may("inventory") or may("finance")):
        frappe.throw(frappe._("No tiene permiso para consultar compras"),
                     frappe.PermissionError)
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte las compras desde Compras PMS"))
    linked = frappe.get_all("HS Supplier", filters={"property": prop.name,
                                                   "company": prop.company,
                                                   "active": 1},
                            fields=["supplier"], limit_page_length=1000)
    supplier_ids = sorted({row.supplier for row in linked if row.supplier})
    names = {row.name: row.supplier_name for row in frappe.get_all(
        "Supplier", filters={"name": ["in", supplier_ids], "disabled": 0},
        fields=["name", "supplier_name"],
        limit_page_length=len(supplier_ids))} if supplier_ids else {}
    warehouses = procurement.warehouses(prop)
    warehouse_rows = frappe.get_all("Warehouse", filters={
        "name": ["in", warehouses], "company": prop.company},
        fields=["name", "warehouse_name"],
        limit_page_length=len(warehouses)) if warehouses else []
    orders = frappe.get_all("Purchase Order", filters={
        "hs_property": prop.name, "company": prop.company, "docstatus": 1,
        "status": ["not in", ["Closed", "Cancelled", "Completed"]]},
        fields=["name", "supplier", "currency", "grand_total", "schedule_date",
                "status", "per_received"], order_by="creation desc",
        limit_page_length=100)
    order_ids = [row.name for row in orders]
    order_items = frappe.get_all("Purchase Order Item", filters={
        "parent": ["in", order_ids], "parenttype": "Purchase Order"},
        fields=["name", "parent", "item_code", "item_name", "qty",
        "received_qty", "rate"], limit_page_length=10000) if order_ids else []
    for order in orders:
        order["items"] = [row for row in order_items if row.parent == order.name]
    receipts = frappe.get_all("Purchase Receipt", filters={
        "hs_property": prop.name, "company": prop.company,
        "docstatus": 1, "is_return": 0, "per_billed": ["<", 100]},
        fields=["name", "supplier", "posting_date", "currency",
                "grand_total", "per_billed"], order_by="creation desc",
        limit_page_length=100)
    invoices = frappe.get_all("Purchase Invoice", filters={
        "hs_property": prop.name, "company": prop.company,
        "docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0]},
        fields=["name", "supplier", "bill_no", "currency", "grand_total",
                "outstanding_amount"], order_by="creation desc",
        limit_page_length=100)
    can_pay = may("finance")
    return {"currency": prop.currency, "default_warehouse": prop.warehouse,
            "suppliers": [{"name": key, "supplier_name": names[key]}
                          for key in supplier_ids if key in names],
            "warehouses": warehouse_rows, "orders": orders,
            "receipts": receipts, "invoices": invoices,
            "methods": frappe.get_all("HS Payment Method", filters={
                "property": prop.name, "company": prop.company},
                fields=["name", "mode_of_payment", "currency", "is_cash",
                        "reference_required"], limit_page_length=200) if can_pay else [],
            "shifts": frappe.get_all("HS Shift", filters={
                "property": prop.name, "company": prop.company, "status": "Open"},
                fields=["name", "cashier", "currency"],
                limit_page_length=100) if can_pay else []}


@frappe.whitelist()
def erp_purchase_search(property_name, mode="orders", search="", offset=0,
                        page_length=50):
    prop = require(property_name)
    if not (may("inventory") or may("finance")):
        frappe.throw(frappe._("No tiene permiso para consultar compras"),
                     frappe.PermissionError)
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte las compras desde Compras PMS"))
    if (mode not in ("orders", "receipts", "invoices") or
            not isinstance(search, str) or len(search) > 100):
        frappe.throw(frappe._("Revise la búsqueda de compras"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la página de compras"))
    if offset < 0 or offset > 100000 or page_length < 1 or page_length > 100:
        frappe.throw(frappe._("Revise la página de compras"))
    kinds = {
        "orders": ("Purchase Order", {"status": ["not in", [
            "Closed", "Cancelled", "Completed"]]},
            ["name", "supplier", "currency", "grand_total", "schedule_date",
             "status", "per_received"]),
        "receipts": ("Purchase Receipt", {"is_return": 0,
            "per_billed": ["<", 100]},
            ["name", "supplier", "posting_date", "currency", "grand_total",
             "per_billed"]),
        "invoices": ("Purchase Invoice", {"is_return": 0,
            "outstanding_amount": [">", 0]},
            ["name", "supplier", "bill_no", "currency", "grand_total",
             "outstanding_amount"]),
    }
    doctype, conditions, fields = kinds[mode]
    filters = {"hs_property": prop.name, "company": prop.company,
               "docstatus": 1, **conditions}
    term = search.strip()
    or_filters = None
    if term:
        matching_suppliers = frappe.get_all("Supplier", filters={
            "supplier_name": ["like", "%" + term + "%"]},
            pluck="name", limit_page_length=200)
        or_filters = [[doctype, "name", "like", "%" + term + "%"],
                      [doctype, "supplier", "like", "%" + term + "%"]]
        if matching_suppliers:
            or_filters.append([doctype, "supplier", "in", matching_suppliers])
        if mode == "invoices":
            or_filters.append([doctype, "bill_no", "like", "%" + term + "%"])
    result = frappe.get_all(doctype, filters=filters, or_filters=or_filters,
        fields=fields, order_by="creation desc, name desc",
        limit_start=offset, limit_page_length=page_length + 1)
    rows = result[:page_length]
    if mode == "orders" and rows:
        children = frappe.get_all("Purchase Order Item", filters={
            "parent": ["in", [row.name for row in rows]],
            "parenttype": "Purchase Order"},
            fields=["name", "parent", "item_code", "item_name", "qty",
                    "received_qty", "rate"], limit_page_length=page_length * 100)
        by_parent = {}
        for child in children:
            by_parent.setdefault(child.parent, []).append(child)
        for row in rows:
            row["items"] = by_parent.get(row.name, [])
    return {"rows": rows, "offset": offset, "has_more": len(result) > page_length}


@frappe.whitelist()
def pms_purchase_snapshot(property_name, compact=0):
    return standalone_purchases.snapshot(property_name, compact)


@frappe.whitelist()
def pms_purchase_catalog_page(property_name, kind="Supplier", search="",
                              offset=0, page_length=25):
    return standalone_purchases.catalog_page(property_name, kind, search,
        offset, page_length)


@frappe.whitelist()
def pms_purchase_order_page(property_name, search="", offset=0,
                            page_length=25, receivable_only=0):
    return standalone_purchase_orders.page(property_name, search, offset,
        page_length, receivable_only)


@frappe.whitelist()
def pms_laundry_snapshot(property_name):
    prop = require(property_name, "laundry")
    standalone_accounting.require_pms(prop)
    return guest_laundry.board(prop)


@frappe.whitelist()
def erp_laundry_snapshot(property_name):
    prop = require(property_name, "laundry")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("La lavandería ERPNext no está activa en este sitio"))
    return guest_laundry.board(prop)


@frappe.whitelist()
def pms_financing_snapshot(property_name):
    return standalone_financing.snapshot(property_name)


@frappe.whitelist()
def erp_financing_snapshot(property_name):
    prop = require(property_name)
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("La financiación ERPNext no está activa en este sitio"))
    if not (may("finance") or may("report") or may("approve")):
        frappe.throw(frappe._("No tiene acceso a movimientos financieros"),
                     frappe.PermissionError)
    currency = financial_movements.base(prop)
    concepts = frappe.get_all("HS Treasury Concept", filters={
        "property": prop.name, "company": prop.company, "active": 1},
        fields=["name", "label", "nature", "account"],
        order_by="label asc", limit_page_length=200)
    concept_settings = frappe.get_all("HS Treasury Concept", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "label", "nature", "account", "active", "modified"],
        order_by="label asc", limit_page_length=200) if may("setup") else []
    accounts = frappe.get_all("Account", filters={
        "company": prop.company, "is_group": 0,
        "account_currency": currency,
        "root_type": ["in", ["Asset", "Income", "Liability", "Equity"]]},
        fields=["name", "account_number", "account_name", "root_type",
                "account_type"], order_by="account_number asc, name asc",
        limit_page_length=1000) if may("setup") or may("finance") else []
    for row in accounts:
        row["account_code"] = row.account_number or row.name
    methods = frappe.get_all("HS Payment Method", filters={
        "property": prop.name, "company": prop.company,
        "currency": currency, "is_cash": 1},
        fields=["name", "mode_of_payment", "currency", "is_cash"],
        limit_page_length=100) if may("finance") else []
    shifts = frappe.get_all("HS Shift", filters={
        "property": prop.name, "cashier": frappe.session.user,
        "status": "Open", "currency": currency},
        fields=["name", "opened_at"], limit_page_length=100) if may("finance") else []
    kinds = ["Other Income", "Loan Received", "Loan Repayment",
             "Capital Contribution", "Capital Withdrawal"]
    movements = frappe.get_all("HS Treasury Movement", filters={
        "property": prop.name, "company": prop.company,
        "kind": ["in", kinds]},
        fields=["name", "kind", "concept", "concept_label", "source_movement",
                "counter_account", "cash_account", "method", "shift", "currency",
                "amount", "base_amount", "status", "requested_by", "approved_by",
                "reference", "business_date", "journal_entry"],
        order_by="creation desc", limit_page_length=200)
    sources = current_all("HS Treasury Movement", filters={
        "property": prop.name, "company": prop.company,
        "kind": ["in", ["Loan Received", "Capital Contribution"]],
        "status": "Posted"},
        fields=["name", "kind", "concept_label", "currency", "amount",
                "base_amount", "status", "requested_by", "reference",
                "pms_journal", "journal_entry"], order_by="creation desc")
    for row in sources:
        row["available"] = str(financial_movements.outstanding(row))
        row["principal_outstanding"] = str(
            financial_movements.outstanding(row, reserve=False))
    return {"currency": currency, "user": frappe.session.user,
        "concepts": concepts, "concept_settings": concept_settings,
        "accounts": accounts,
        "methods": methods, "shifts": shifts,
        "movements": movements, "sources": sources}


@frappe.whitelist()
def pms_petty_snapshot(property_name):
    return standalone_petty_cash.snapshot(property_name)


@frappe.whitelist()
def erp_petty_snapshot(property_name):
    prop = require(property_name)
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Caja Chica ERPNext no está activa en este sitio"))
    handovers = frappe.get_all("HS Petty Cash Handover", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "outgoing", "incoming", "expected_cash", "counted_cash",
                "status", "outgoing_accepted", "incoming_accepted"],
        order_by="creation desc", limit_page_length=50)
    visible = (prop.petty_cash_responsible == frappe.session.user or
               may("finance") or may("report") or may("approve") or
               any(row.status == "Awaiting Acceptance" and
                   frappe.session.user in (row.outgoing, row.incoming)
                   for row in handovers))
    if not visible:
        frappe.throw(frappe._("No tiene acceso a Caja Chica"), frappe.PermissionError)
    currency = financial_movements.base(prop)
    active = all(prop.get(field) for field in (
        "petty_cash_account", "petty_cash_responsible",
        "petty_cash_overage_account", "petty_cash_shortage_account"))
    expenses = frappe.get_all("HS Petty Cash Expense", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "category", "category_label", "responsible", "beneficiary",
                "concept", "receipt_reference", "amount", "business_date",
                "rendition", "status", "journal_entry"],
        order_by="creation desc", limit_page_length=200)
    renditions = frappe.get_all("HS Petty Cash Rendition", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "responsible", "expense_total", "expected_cash",
                "counted_cash", "variance", "explanation", "status", "submitted_by",
                "reviewed_by", "review_note", "approved_business_date",
                "variance_journal"],
        order_by="creation desc", limit_page_length=100)
    funds = frappe.get_all("HS Treasury Movement", filters={
        "property": prop.name, "company": prop.company,
        "kind": ["in", ["Initial Fund", "Replenishment"]]},
        fields=["name", "kind", "rendition", "amount", "reference", "status",
                "business_date", "shift", "journal_entry"],
        order_by="creation desc", limit_page_length=100)
    pending = current_all("HS Petty Cash Expense", filters={
        "property": prop.name, "company": prop.company, "status": "Posted",
        "rendition": ["is", "not set"]}, fields=["amount"])
    accounts = frappe.get_all("Account", filters={
        "company": prop.company, "is_group": 0, "account_currency": currency,
        "root_type": ["in", ["Asset", "Income", "Expense"]]},
        fields=["name", "account_number", "account_name", "root_type"],
        order_by="account_number asc, name asc",
        limit_page_length=1000) if may("setup") else []
    for row in accounts:
        row["account_code"] = row.account_number or row.name
    categories = frappe.get_all("HS Expense Category", filters={
        "property": prop.name, "active": 1},
        fields=["name", "label", "max_amount"], order_by="label asc",
        limit_page_length=200)
    methods = frappe.get_all("HS Payment Method", filters={
        "property": prop.name, "currency": currency, "is_cash": 1},
        fields=["name", "mode_of_payment", "currency"],
        limit_page_length=100) if may("finance") else []
    shifts = frappe.get_all("HS Shift", filters={
        "property": prop.name, "cashier": frappe.session.user, "status": "Open",
        "currency": currency}, fields=["name", "opened_at"],
        limit_page_length=100) if may("finance") else []
    ledger = financial_movements.ledger_balance(prop) if active else Decimal(0)
    operational = financial_movements.balance(prop) if active else Decimal(0)
    return {"active": active, "currency": currency, "user": frappe.session.user,
        "property_modified": str(prop.modified),
        "initial_fund_exists": bool(frappe.db.exists("HS Treasury Movement", {
            "property": prop.name, "company": prop.company,
            "kind": "Initial Fund", "status": ["!=", "Cancelled"]})),
        "responsible": prop.petty_cash_responsible,
        "account": prop.petty_cash_account,
        "overage_account": prop.petty_cash_overage_account,
        "shortage_account": prop.petty_cash_shortage_account,
        "balance": str(ledger), "expected_cash": str(operational),
        "pending_expenses": str(sum((Decimal(str(row.amount)) for row in pending), Decimal(0))),
        "reconciled": ledger == operational,
        "accounts": accounts, "categories": categories,
        "methods": methods, "shifts": shifts,
        "expenses": expenses, "renditions": renditions,
        "handovers": handovers, "funds": funds,
        "users": petty_handover_users(prop)
            if may("setup") or may("approve") else []}


@frappe.whitelist()
def pms_close_preview(property_name):
    return standalone_closing.preview(property_name)


@frappe.whitelist()
def pms_close_history(property_name):
    return standalone_closing.history(property_name)


@frappe.whitelist()
def pms_close_detail(property_name, name):
    return standalone_closing.detail(property_name, name)


@frappe.whitelist()
def erp_close_snapshot(property_name):
    prop = require(property_name, "report")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("El cierre ERPNext no está activo en este sitio"))
    from hospitality_suite.close_financials import display_groups
    current = frappe.get_all("HS Daily Close", filters={
        "property": prop.name, "company": prop.company,
        "business_date": prop.business_date, "status": "Review"},
        fields=["name", "business_date", "revision", "status", "summary",
                "blockers", "reason"], order_by="revision desc",
        limit_page_length=1)
    row = current[0] if current else None
    if row:
        row["snapshot"] = frappe.parse_json(row.pop("summary") or "{}")
        row["blockers"] = frappe.parse_json(row.blockers or "[]")
    return {"business_date": str(prop.business_date),
        "base_currency": financial_movements.base(prop),
        "groups": display_groups(), "current": row}


@frappe.whitelist()
def erp_close_history(property_name, search="", offset=0, page_length=50):
    prop = require(property_name, "report")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("El cierre ERPNext no está activo en este sitio"))
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de cierres"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la página de cierres"))
    if offset < 0 or offset > 100000 or page_length < 1 or page_length > 100:
        frappe.throw(frappe._("Revise la página de cierres"))
    term = search.strip()
    filters = {"property": prop.name, "company": prop.company}
    if term:
        if (len(term) == 10 and term[4] == term[7] == "-" and
                (term[:4] + term[5:7] + term[8:]).isdigit()):
            filters["business_date"] = term
        else:
            filters["name"] = ["like", "%" + term + "%"]
    rows = frappe.get_all("HS Daily Close", filters=filters,
        fields=["name", "business_date", "revision", "status",
                "closed_at", "reason"],
        order_by="business_date desc, revision desc, creation desc",
        limit_start=offset, limit_page_length=page_length + 1)
    return {"rows": rows[:page_length], "offset": offset,
        "has_more": len(rows) > page_length}


@frappe.whitelist()
def erp_close_detail(property_name, name):
    prop = require(property_name, "report")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("El cierre ERPNext no está activo en este sitio"))
    row = document("HS Daily Close", name, "report")
    if row.property != prop.name or row.company != prop.company:
        frappe.throw(frappe._("El cierre pertenece a otro establecimiento"),
                     frappe.PermissionError)
    return {"name": row.name, "business_date": str(row.business_date),
        "revision": row.revision, "status": row.status,
        "closed_at": str(row.closed_at) if row.closed_at else None,
        "reason": row.reason,
        "snapshot": frappe.parse_json(row.summary or "{}"),
        "blockers": frappe.parse_json(row.blockers or "[]")}


@frappe.whitelist()
def pms_report_options(property_name):
    return standalone_reports.options(property_name)


@frappe.whitelist()
def pms_report(property_name, report_name, filters=None, offset=0, page_length=100):
    return standalone_reports.report(property_name, report_name,
        payload(filters or {}), offset, page_length)


@frappe.whitelist()
def pms_report_csv(property_name, report_name, filters=None):
    return standalone_reports.export_csv(property_name, report_name, payload(filters or {}))


@frappe.whitelist()
def pms_financing_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_financing.quote(prop, payload(data))


@frappe.whitelist()
def pms_order_quote(property_name, data):
    prop = require(property_name, "inventory")
    return standalone_purchase_orders.quote(prop, payload(data))


@frappe.whitelist()
def pms_purchase_quote(property_name, data):
    prop = require(property_name, "inventory")
    return standalone_purchases.purchase_quote(prop, payload(data))


@frappe.whitelist()
def pms_supplier_payment_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_purchases.payment_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_supplier_payment_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_opening_payables.payment_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_credit_apply_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_opening_credits.apply_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_credit_refund_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_opening_credits.refund_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_guarantee_refund_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_opening_guarantees.refund_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_guarantee_apply_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_opening_guarantees.apply_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_supplier_credit_apply_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_opening_supplier_credits.apply_quote(prop, payload(data))


@frappe.whitelist()
def pms_opening_supplier_credit_refund_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_opening_supplier_credits.refund_quote(prop, payload(data))


@frappe.whitelist()
def pms_agent_commission_payment_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_agency_commissions.payment_quote(prop, payload(data))


@frappe.whitelist()
def pms_purchase_return_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_purchase_returns.quote(prop, payload(data))


@frappe.whitelist()
def pms_purchase_cancel_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_purchase_returns.cancellation_quote(prop, payload(data))


@frappe.whitelist()
def pms_supplier_refund_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_purchase_returns.refund_quote(prop, payload(data))


@frappe.whitelist()
def pms_tax_profiles(property_name):
    return standalone_tax.profiles(property_name)


@frappe.whitelist()
def pms_invoice_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_fiscal.invoice_quote(prop, payload(data))


@frappe.whitelist()
def pms_direct_sale_return_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_direct_sales.return_quote(prop, payload(data))


@frappe.whitelist()
def erp_historical_direct_sale_return_quote(property_name, data):
    prop = require(property_name, "approve")
    return erp_historical_direct_sales.quote(prop, payload(data))


@frappe.whitelist()
def erp_historical_direct_sale_return_reversal_quote(property_name, data):
    prop = require(property_name, "approve")
    return erp_historical_direct_sales.reversal_quote(prop, payload(data))


@frappe.whitelist()
def pms_credit_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_fiscal.credit_quote(prop, payload(data))


@frappe.whitelist()
def pms_historical_day_pass_return_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_day_pass.historical_return_quote(prop, payload(data))


@frappe.whitelist()
def erp_historical_day_pass_return_quote(property_name, data):
    prop = require(property_name, "approve")
    return erp_historical_day_pass.quote(prop, payload(data))


@frappe.whitelist()
def erp_historical_day_pass_return_reversal_quote(property_name, data):
    prop = require(property_name, "approve")
    return erp_historical_day_pass.reversal_quote(prop, payload(data))


@frappe.whitelist()
def pms_credit_options(property_name, invoice):
    return standalone_fiscal.credit_options(property_name, invoice)


@frappe.whitelist()
def pms_folio_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_receivables.folio_quote(prop, payload(data))


@frappe.whitelist()
def pms_folio_service_options(property_name, folio):
    return standalone_folio_services.options(property_name, folio)


@frappe.whitelist()
def pms_folio_service_quote(property_name, data):
    prop = require(property_name, "finance")
    return standalone_folio_services.quote(prop, payload(data))


@frappe.whitelist()
def pms_folio_adjustment_options(property_name, folio):
    return standalone_folio_services.adjustment_options(property_name, folio)


@frappe.whitelist()
def pms_folio_adjustment_quote(property_name, data):
    prop = require(property_name, "approve")
    return standalone_folio_services.adjustment_quote(prop, payload(data))


@frappe.whitelist()
def pms_folios(property_name):
    prop = require(property_name, "finance")
    standalone_accounting.require_pms(prop)
    from hospitality_suite.accounting import folio_balance
    rows = frappe.get_all("HS Folio", filters={"property": prop.name},
        fields=["name", "label", "customer", "currency", "status", "stay", "booking"],
        order_by="modified desc", limit_page_length=200)
    return [{**row, "customer_name": frappe.db.get_value("HS Party", row.customer, "party_name"),
             "balance": folio_balance(row.name)} for row in rows]


def _erp_open_folios(property_name, search, offset, page_length, permission):
    """Small property-scoped picker shared by independent ERPNext workflows."""
    from hospitality_suite.paging import page

    prop = require(property_name, permission)
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("La facturación ERPNext requiere el modo ERPNext"))
    if not isinstance(search, str) or len(search) > 80:
        frappe.throw(frappe._("Revise la búsqueda de cuentas de estancia"))
    page([], offset, page_length)
    start, length = int(offset), int(page_length)
    if length > 50:
        frappe.throw(frappe._("Consulte hasta 50 cuentas de estancia por página"))
    query = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    matches = [[field, "like", f"%{query}%"] for field in
        ("name", "label", "customer", "stay", "booking")] if query else None
    rows = frappe.get_all("HS Folio", filters={"property": prop.name,
        "company": prop.company, "status": "Open"}, or_filters=matches,
        fields=["name", "label", "customer", "currency", "stay", "booking"],
        order_by="creation desc, name desc", start=start, limit=length + 1)
    visible = rows[:length]
    customers = {row.customer for row in visible if row.customer}
    labels = {row.name: row.customer_name for row in frappe.get_all("Customer",
        filters={"name": ["in", list(customers)]},
        fields=["name", "customer_name"])} if customers else {}
    return {"property": prop.name, "offset": start, "page_length": length,
            "has_more": len(rows) > length,
            "rows": [{**row, "customer_name": labels.get(row.customer) or row.customer}
                     for row in visible]}


@frappe.whitelist()
def erp_invoice_folios(property_name, search="", offset=0, page_length=25):
    """Open ERPNext folios for the independent React invoicing workflow."""
    return _erp_open_folios(property_name, search, offset, page_length, "finance")


@frappe.whitelist()
def erp_adjustment_folios(property_name, search="", offset=0, page_length=25):
    return _erp_open_folios(property_name, search, offset, page_length, "approve")


@frappe.whitelist()
def erp_adjustment_charges(property_name, folio, offset=0, page_length=25):
    """Reviewable main charges and their remaining value on an open ERP folio."""
    from hospitality_suite.paging import page

    prop = require(property_name, "approve")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Los ajustes ERPNext requieren el modo ERPNext"))
    target = document("HS Folio", folio, "approve")
    if target.property != prop.name or target.company != prop.company or target.status != "Open":
        frappe.throw(frappe._("Seleccione una cuenta de estancia abierta del establecimiento"),
            frappe.PermissionError)
    page([], offset, page_length)
    start, length = int(offset), int(page_length)
    if length > 50:
        frappe.throw(frappe._("Consulte hasta 50 cargos por página"))
    filters = {"property": prop.name, "company": prop.company,
        "folio": target.name, "status": ["in", ["Pending", "Scheduled"]],
        "applies_to_charge": ["is", "not set"], "amount": [">", 0]}
    rows = frappe.get_all("HS Charge", filters=filters,
        fields=["name", "description", "amount", "currency", "status", "stay"],
        order_by="creation desc, name desc", start=start, limit=length + 1)
    visible = rows[:length]
    names = [row.name for row in visible]
    related = frappe.get_all("HS Charge", filters={"property": prop.name,
        "company": prop.company, "folio": target.name,
        "applies_to_charge": ["in", names], "status": ["!=", "Reversed"]},
        fields=["applies_to_charge", "amount"]) if names else []
    from collections import defaultdict
    from hospitality_suite.pricing import decimal, money
    totals = defaultdict(lambda: decimal(0))
    for row in related:
        totals[row.applies_to_charge] += decimal(row.amount)
    return {"folio": target.name, "offset": start, "page_length": length,
            "has_more": len(rows) > length,
            "rows": [{**row, "current_amount": str(money(decimal(row.amount) + totals[row.name]))}
                     for row in visible]}


@frappe.whitelist(methods=["POST"])
def erp_adjustment_quote(property_name, data):
    prop = require(property_name, "approve")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Los ajustes ERPNext requieren el modo ERPNext"))
    return operations.adjustment_quote(prop, payload(data))


@frappe.whitelist()
def pms_reception_snapshot(property_name):
    return standalone_reception.snapshot(property_name)


@frappe.whitelist()
def erp_reception_snapshot(property_name):
    return standalone_reception.snapshot(property_name, "erpnext")


@frappe.whitelist()
def portal_request_queue(property_name, offset=0, page_length=25, search=""):
    return portal.staff_queue(property_name, offset, page_length, search)


@frappe.whitelist()
def folio_pending_charges(property_name, folio, offset=0, page_length=25):
    return standalone_reception.pending_folio_charges(property_name, folio, offset, page_length)


@frappe.whitelist()
def folio_transfer_targets(property_name, charge):
    return standalone_reception.charge_transfer_targets(property_name, charge)


@frappe.whitelist()
def pms_travel_experiences_snapshot(property_name):
    return travel_experiences.pms_snapshot(property_name)


@frappe.whitelist()
def erp_travel_experiences_snapshot(property_name):
    return travel_experiences.erp_snapshot(property_name)


@frappe.whitelist()
def pms_cutover_preflight():
    return pms_cutover.preflight()


@frappe.whitelist()
def erp_to_pms_preflight():
    from hospitality_suite.erp_to_pms_preflight import preflight
    return preflight()


@frappe.whitelist()
def erp_to_pms_mapping_template(file_name, source_sha256, manifest_sha256):
    return erp_to_pms_mapping.template(file_name, source_sha256,
                                       manifest_sha256)


@frappe.whitelist()
def erp_to_pms_mapping_review(file_name, source_sha256, manifest_sha256, mapping):
    return erp_to_pms_mapping.review(file_name, source_sha256,
                                     manifest_sha256, mapping)


@frappe.whitelist()
def erp_to_pms_balance_preview(file_name, source_sha256, manifest_sha256, mapping):
    return reverse_balance_preview.preview(file_name, source_sha256,
                                           manifest_sha256, mapping)


@frappe.whitelist()
def erp_to_pms_transfer_plan(file_name, source_sha256, manifest_sha256, mapping):
    return reverse_transfer_plan.review(file_name, source_sha256,
                                        manifest_sha256, mapping)


@frappe.whitelist()
def erp_to_pms_transfer_rehearsal(file_name, source_sha256, manifest_sha256,
                                  mapping, plan_sha256):
    return reverse_transfer_rehearsal.rehearse(file_name, source_sha256,
        manifest_sha256, mapping, plan_sha256)


@frappe.whitelist()
def pms_cutover_mapping_template():
    return pms_cutover_mapping.template()


@frappe.whitelist()
def pms_cutover_mapping_review(mapping):
    return pms_cutover_mapping.review(mapping)


@frappe.whitelist()
def pms_cutover_transfer_plan(mapping):
    return pms_cutover_plan.review(mapping)


@frappe.whitelist()
def pms_day_pass_snapshot(property_name):
    return standalone_day_pass.snapshot(property_name)


@frappe.whitelist()
def erp_day_pass_snapshot(property_name):
    return day_pass.erp_snapshot(property_name)


@frappe.whitelist()
def pms_room_operations(property_name):
    from hospitality_suite.standalone_room_operations import snapshot
    return snapshot(property_name)


@frappe.whitelist()
def erp_room_operations(property_name):
    from hospitality_suite.standalone_room_operations import snapshot
    return snapshot(property_name, "erpnext")


@frappe.whitelist()
def room_incident_page(property_name, status="Open", offset=0, page_length=25,
                       search="", room=""):
    from hospitality_suite.standalone_room_operations import incident_page
    return incident_page(property_name, status, offset, page_length, search, room)


@frappe.whitelist()
def maintenance_parts_board(property_name, order, warehouse="", search="",
                            offset=0, page_length=25):
    return standalone_maintenance_parts.board(property_name, order, warehouse,
        search, offset, page_length)


@frappe.whitelist()
def linen_board(property_name, direction="Send", search="", offset=0,
                page_length=25, history_offset=0):
    return standalone_linen.board(property_name, direction, search, offset,
                                  page_length, history_offset)


@frappe.whitelist()
def pms_linen_setup_options(property_name):
    return standalone_linen.setup_options(property_name)


@frappe.whitelist()
def pms_booking_fee_settings(property_name):
    from hospitality_suite.standalone_booking_fee import settings
    return settings(property_name)


@frappe.whitelist()
def pms_products(property_name):
    prop = require(property_name, "setup")
    standalone_accounting.require_pms(prop)
    return {"products": frappe.get_all("HS Product", filters={"property": prop.name},
                fields=["name", "modified", "product_code", "product_name", "product_type", "income_account", "tax_profile",
                        "inventory_account", "expense_account", "sales_rate", "active"], order_by="product_code asc"),
            "tax_profiles": frappe.get_all("HS PMS Tax Profile", filters={"property": prop.name,
                "active": 1}, fields=["name", "label", "treatment", "rate", "included_in_price"],
                order_by="label asc"),
            "income_accounts": frappe.get_all("HS Account", filters={"property": prop.name,
                "organization": prop.organization, "root_type": "Income", "is_group": 0,
                "active": 1, "account_currency": prop.currency},
                fields=["name", "account_code", "account_name"], order_by="account_code asc"),
            "asset_accounts": frappe.get_all("HS Account", filters={"property": prop.name,
                "organization": prop.organization, "root_type": "Asset", "is_group": 0,
                "active": 1, "account_currency": prop.currency},
                fields=["name", "account_code", "account_name"], order_by="account_code asc"),
            "expense_accounts": frappe.get_all("HS Account", filters={"property": prop.name,
                "organization": prop.organization, "root_type": "Expense", "is_group": 0,
                "active": 1, "account_currency": prop.currency},
                fields=["name", "account_code", "account_name"], order_by="account_code asc"),
            "bindings": {field: prop.get(field) for field in
                ("lodging_item", "extra_hour_item", "timing_item", "day_pass_item", "penalty_item")},
            "property_modified": str(prop.modified)}


@frappe.whitelist()
def pms_cash_preview(property_name, data):
    prop = require(property_name, "finance")
    return standalone_cash.quote(prop, payload(data))


@frappe.whitelist()
def pms_refund_preview(property_name, data):
    prop = require(property_name, "approve")
    return standalone_cash.refund_quote(prop, payload(data))


@frappe.whitelist()
def erp_cash_snapshot(property_name, shift_name="", offset=0, page_length=50):
    return erp_cash.snapshot(property_name, shift_name, offset, page_length)


@frappe.whitelist()
def erp_cash_settings(property_name):
    return erp_cash.settings(property_name)


@frappe.whitelist()
def erp_cash_settlement_sources(property_name, search="", offset=0, page_length=20):
    return erp_cash.settlement_sources(property_name, search, offset, page_length)


@frappe.whitelist()
def erp_cash_method_settings(property_name):
    return erp_cash.method_settings(property_name)


@frappe.whitelist()
def erp_customer_credits_snapshot(property_name, folio_search="",
                                  advance_search="", guarantee_search="",
                                  advance_offset=0, guarantee_offset=0,
                                  funds_page_length=50, invoice_search="",
                                  invoice_offset=0, folio_offset=0,
                                  receivable_page_length=50):
    prop = require(property_name, "finance")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte los anticipos desde Cuentas por cobrar PMS"))
    if any(not isinstance(value, str) or len(value) > 100 for value in
           (folio_search, advance_search, guarantee_search, invoice_search)):
        frappe.throw(frappe._("Revise la búsqueda de fondos o cuentas de estancia"))
    try:
        advance_offset, guarantee_offset, funds_page_length, \
            invoice_offset, folio_offset, receivable_page_length = (
                int(advance_offset), int(guarantee_offset),
                int(funds_page_length), int(invoice_offset),
                int(folio_offset), int(receivable_page_length))
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de fondos"))
    if (advance_offset < 0 or guarantee_offset < 0 or
            invoice_offset < 0 or folio_offset < 0 or
            funds_page_length < 1 or funds_page_length > 100 or
            receivable_page_length < 1 or receivable_page_length > 100):
        frappe.throw(frappe._("Revise la paginación de fondos"))
    folio_search, advance_search, guarantee_search, invoice_search = (
        folio_search.strip(), advance_search.strip(),
        guarantee_search.strip(), invoice_search.strip())

    def fund_matches(query):
        if not query:
            return None
        customers = frappe.get_all("Customer", filters={
            "customer_name": ["like", "%" + query + "%"]},
            pluck="name", limit_page_length=200)
        return ([
            ["HS Payment", "name", "like", "%" + query + "%"],
            ["HS Payment", "reference", "like", "%" + query + "%"],
            ["HS Payment", "customer", "like", "%" + query + "%"],
        ] + ([["HS Payment", "customer", "in", customers]]
             if customers else []))

    advance_rows = frappe.get_all("HS Payment", filters={
        "property": prop.name, "company": prop.company,
        "kind": "Advance", "status": "Posted",
        "payment_entry": ["is", "set"]},
        or_filters=fund_matches(advance_search),
        fields=["name", "customer", "reference", "payment_entry", "currency",
                "method"],
        order_by="creation desc", limit_start=advance_offset,
        limit_page_length=funds_page_length + 1)
    sources = advance_rows[:funds_page_length]
    payments = {row.name: row for row in frappe.get_all("Payment Entry", filters={
        "name": ["in", [row.payment_entry for row in sources]]},
        fields=["name", "company", "hs_property", "party", "paid_from",
                "paid_from_account_currency", "unallocated_amount", "docstatus"])} if sources else {}
    advances = []
    for source in sources:
        payment = payments.get(source.payment_entry)
        if (payment and payment.docstatus == 1 and
                payment.company == prop.company and
                payment.hs_property == prop.name and
                payment.party == source.customer and
                payment.paid_from == prop.receivable_account and
                payment.paid_from_account_currency == prop.currency and
                payment.unallocated_amount > 0):
            advances.append(dict(name=source.name, customer=source.customer,
                                 reference=source.reference or source.name,
                                 source_currency=source.currency,
                                 available=str(payment.unallocated_amount)))
    can_approve = bool(is_system() or set(ACTIONS["approve"]).intersection(
        frappe.get_roles()))
    advance_refunds = []
    if can_approve:
        from hospitality_suite.refunds import balance as refund_balance
        refundable_sources = {row.name: row for row in sources}
        for row in advances:
            source = refundable_sources[row["name"]]
            balance = refund_balance(prop, frappe.get_doc("HS Payment", source.name))
            if balance.remaining > 0 and balance.funds.unallocated > 0:
                advance_refunds.append(dict(name=source.name,
                    customer=source.customer,
                    reference=source.reference or source.name,
                    currency=source.currency, method=source.method,
                    remaining=str(balance.remaining),
                    unallocated=str(balance.funds.unallocated)))
    guarantee_rows = frappe.get_all("HS Payment", filters={
        "property": prop.name, "company": prop.company,
        "kind": "Guarantee", "status": "Posted",
        "journal_entry": ["is", "set"]},
        or_filters=fund_matches(guarantee_search),
        fields=["name", "customer", "stay", "booking", "folio",
                "method", "currency", "reference"],
        order_by="creation desc", limit_start=guarantee_offset,
        limit_page_length=funds_page_length + 1)
    guarantee_sources = guarantee_rows[:funds_page_length]
    guarantees = []
    for source in guarantee_sources:
        balance = accounting.guarantee_balance(
            prop, frappe.get_doc("HS Payment", source.name))
        if balance.nominal > 0:
            guarantees.append(dict(name=source.name, customer=source.customer,
                stay=source.stay, booking=source.booking, folio=source.folio,
                method=source.method, currency=source.currency,
                reference=source.reference or source.name,
                available=str(balance.nominal),
                available_book=str(balance.book)))
    matching_invoice_customers = frappe.get_all("Customer", filters={
        "customer_name": ["like", "%" + invoice_search + "%"]},
        pluck="name", limit_page_length=200) if invoice_search else []
    invoice_matches = ([
        ["Sales Invoice", "name", "like", "%" + invoice_search + "%"],
        ["Sales Invoice", "customer", "like", "%" + invoice_search + "%"],
    ] + ([["Sales Invoice", "customer", "in", matching_invoice_customers]]
         if matching_invoice_customers else [])) if invoice_search else None
    invoice_rows = frappe.get_all("Sales Invoice", filters={
        "company": prop.company, "hs_property": prop.name,
        "docstatus": 1, "is_return": 0, "is_pos": 0,
        "currency": prop.currency,
        "debit_to": prop.receivable_account,
        "outstanding_amount": [">", 0]},
        or_filters=invoice_matches,
        fields=["name", "customer", "posting_date", "currency",
                "hs_folio", "hs_stay", "hs_booking",
                "outstanding_amount"], order_by="posting_date desc, name desc",
        limit_start=invoice_offset,
        limit_page_length=receivable_page_length + 1)
    invoices = invoice_rows[:receivable_page_length]
    shift_rows = project("HS Shift", prop,
        ["name", "cashier", "currency", "status", "modified"],
        filters={"status": ["in", ["Open", "Review"]]})
    matching_customers = frappe.get_all("Customer", filters={
        "customer_name": ["like", "%" + folio_search + "%"]},
        pluck="name", limit_page_length=200) if folio_search else []
    folio_matches = ([
        ["HS Folio", "name", "like", "%" + folio_search + "%"],
        ["HS Folio", "label", "like", "%" + folio_search + "%"],
        ["HS Folio", "customer", "like", "%" + folio_search + "%"],
    ] + ([["HS Folio", "customer", "in", matching_customers]]
         if matching_customers else [])) if folio_search else None
    folio_page_rows = frappe.get_all("HS Folio", filters={
        "property": prop.name, "company": prop.company},
        or_filters=folio_matches,
        fields=["name", "label", "customer", "stay", "booking",
                "currency", "status"],
        order_by="modified desc", limit_start=folio_offset,
        limit_page_length=receivable_page_length + 1)
    folio_rows = folio_page_rows[:receivable_page_length]
    folios = []
    guarantee_folios = []
    for row in folio_rows:
        balance = accounting.folio_balance(row.name)
        guarantee_folios.append(dict(name=row.name, label=row.label,
            customer=row.customer, stay=row.stay, booking=row.booking,
            currency=row.currency, status=row.status, balance=balance))
        if Decimal(balance["outstanding"]) > 0:
            folios.append(guarantee_folios[-1])
    return dict(currency=prop.currency, advances=advances,
                advance_refunds=advance_refunds,
                advance_page=dict(search=advance_search, offset=advance_offset,
                    has_more=len(advance_rows) > funds_page_length),
                guarantees=guarantees, guarantee_folios=guarantee_folios,
                guarantee_page=dict(search=guarantee_search,
                    offset=guarantee_offset,
                    has_more=len(guarantee_rows) > funds_page_length),
                invoice_page=dict(search=invoice_search,
                    offset=invoice_offset,
                    has_more=len(invoice_rows) > receivable_page_length),
                invoices=[dict(name=row.name, customer=row.customer,
                               posting_date=str(row.posting_date),
                               currency=row.currency,
                               direct=not (row.hs_folio or row.hs_stay or row.hs_booking),
                               outstanding=str(row.outstanding_amount))
                          for row in invoices],
                folios=folios,
                folio_page=dict(search=folio_search, offset=folio_offset,
                    has_more=len(folio_page_rows) > receivable_page_length),
                advance_bookings=project("HS Booking", prop,
                    ["name", "customer", "status", "starts_at"],
                    filters={"status": ["in", ["Hold", "Confirmed", "Checked In"]]}),
                advance_stays=project("HS Stay", prop,
                    ["name", "booking", "customer", "status", "room"],
                    filters={"status": "Active"}),
                methods=project("HS Payment Method", prop,
                    ["name", "mode_of_payment", "currency", "is_cash",
                     "reference_required"]),
                shifts=[{**row, "expected": cashier.expected(
                            frappe.get_doc("HS Shift", row["name"]))}
                        for row in shift_rows])


@frappe.whitelist()
def erp_direct_credit_search(property_name, mode="invoices", search="",
                             credit_note="", offset=0, page_length=50):
    """Find direct invoices, their credit notes and original payments at any age."""
    prop = require(property_name, "approve")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte los documentos fiscales desde Facturación PMS"))
    if (mode not in ("invoices", "notes", "payments") or
            any(not isinstance(value, str) or len(value) > 100
                for value in (search, credit_note))):
        frappe.throw(frappe._("Revise la búsqueda de documentos directos"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de documentos directos"))
    if offset < 0 or page_length < 1 or page_length > 100:
        frappe.throw(frappe._("Revise la paginación de documentos directos"))
    search, credit_note = search.strip(), credit_note.strip()
    direct_source = (
        "src.company=%s AND src.hs_property=%s AND src.docstatus=1 "
        "AND src.is_return=0 AND src.is_pos=0 AND src.currency=%s "
        "AND src.debit_to=%s AND COALESCE(src.hs_folio,'')='' "
        "AND COALESCE(src.hs_stay,'')='' AND COALESCE(src.hs_booking,'')=''"
    )
    scope = (prop.company, prop.name, prop.currency, prop.receivable_account)
    if mode == "invoices":
        rows = frappe.db.sql(
            "SELECT src.name, src.customer, src.posting_date "
            "FROM `tabSales Invoice` src "
            "LEFT JOIN `tabCustomer` buyer ON buyer.name=src.customer "
            "WHERE " + direct_source + " AND (%s='' OR src.name LIKE %s "
            "OR src.customer LIKE %s OR buyer.customer_name LIKE %s) "
            "ORDER BY src.posting_date DESC, src.name DESC LIMIT %s OFFSET %s",
            (*scope, search, "%" + search + "%", "%" + search + "%",
             "%" + search + "%", page_length + 1, offset), as_dict=True)
        return {"rows": [dict(name=row.name, customer=row.customer,
                              posting_date=str(row.posting_date))
                         for row in rows[:page_length]],
                "offset": offset, "has_more": len(rows) > page_length}
    note_sql = (
        "SELECT note.name, note.customer, note.return_against AS invoice, "
        "note.outstanding_amount "
        "FROM `tabSales Invoice` note "
        "JOIN `tabSales Invoice` src ON src.name=note.return_against "
        "LEFT JOIN `tabCustomer` buyer ON buyer.name=note.customer "
        "WHERE " + direct_source + " AND note.company=%s "
        "AND note.hs_property=%s AND note.docstatus=1 AND note.is_return=1 "
        "AND note.currency=%s AND note.debit_to=%s "
        "AND note.customer=src.customer AND note.outstanding_amount<0"
    )
    note_scope = (*scope, *scope)
    if mode == "notes":
        rows = frappe.db.sql(
            note_sql + " AND (%s='' OR note.name LIKE %s "
            "OR note.return_against LIKE %s OR note.customer LIKE %s "
            "OR buyer.customer_name LIKE %s) "
            "ORDER BY note.posting_date DESC, note.name DESC LIMIT %s OFFSET %s",
            (*note_scope, search, *(["%" + search + "%"] * 4),
             page_length + 1, offset), as_dict=True)
        return {"rows": [dict(name=row.name, customer=row.customer,
                              invoice=row.invoice,
                              available=str(-Decimal(str(row.outstanding_amount))))
                         for row in rows[:page_length]],
                "offset": offset, "has_more": len(rows) > page_length}
    if not credit_note:
        frappe.throw(frappe._("Seleccione una nota de crédito directa"))
    notes = frappe.db.sql(note_sql + " AND note.name=%s LIMIT 1",
                          (*note_scope, credit_note), as_dict=True)
    if not notes:
        frappe.throw(frappe._("La nota no tiene saldo disponible en este establecimiento"))
    note = notes[0]
    rows = frappe.db.sql(
        "SELECT payment.name, payment.customer, payment.sales_invoice AS invoice, "
        "payment.amount, payment.currency, payment.method "
        "FROM `tabHS Payment` payment "
        "WHERE payment.property=%s AND payment.company=%s "
        "AND payment.customer=%s AND payment.sales_invoice=%s "
        "AND payment.kind='Payment' AND payment.status='Posted' "
        "AND COALESCE(payment.stay,'')='' AND COALESCE(payment.booking,'')='' "
        "AND COALESCE(payment.folio,'')='' "
        "AND (%s='' OR payment.name LIKE %s OR payment.reference LIKE %s) "
        "ORDER BY payment.creation DESC, payment.name DESC LIMIT %s OFFSET %s",
        (prop.name, prop.company, note.customer, note.invoice,
         search, "%" + search + "%", "%" + search + "%",
         page_length + 1, offset), as_dict=True)
    return {"rows": [dict(name=row.name, customer=row.customer,
                          invoice=row.invoice, amount=str(row.amount),
                          currency=row.currency, method=row.method)
                     for row in rows[:page_length]],
            "offset": offset, "has_more": len(rows) > page_length}


@frappe.whitelist()
def erp_credit_refund_search(property_name, search="", credit_note="",
                             source_search="", offset=0, page_length=50):
    """Page old credit notes and their original funds without scanning every receipt."""
    prop = require(property_name, "approve")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Consulte las devoluciones desde Caja PMS"))
    if any(not isinstance(value, str) or len(value) > 100
           for value in (search, credit_note, source_search)):
        frappe.throw(frappe._("Revise la búsqueda de devoluciones"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de devoluciones"))
    if offset < 0 or page_length < 1 or page_length > 100:
        frappe.throw(frappe._("Revise la paginación de devoluciones"))
    search, credit_note, source_search = (
        search.strip(), credit_note.strip(), source_search.strip())
    filters = {"company": prop.company, "hs_property": prop.name,
        "docstatus": 1, "is_return": 1,
        "currency": prop.currency, "debit_to": prop.receivable_account,
        "outstanding_amount": ["<", 0],
        "return_against": ["is", "set"]}
    if not credit_note:
        matching_customers = frappe.get_all("Customer", filters={
            "customer_name": ["like", "%" + search + "%"]},
            pluck="name", limit_page_length=200) if search else []
        matches = ([
            ["Sales Invoice", "name", "like", "%" + search + "%"],
            ["Sales Invoice", "return_against", "like", "%" + search + "%"],
            ["Sales Invoice", "customer", "like", "%" + search + "%"],
        ] + ([["Sales Invoice", "customer", "in", matching_customers]]
             if matching_customers else [])) if search else None
        rows = frappe.get_all("Sales Invoice", filters=filters,
            or_filters=matches,
            fields=["name", "customer", "return_against",
                    "outstanding_amount"],
            order_by="posting_date desc, name desc", limit_start=offset,
            limit_page_length=page_length + 1)
        return {"notes": [dict(name=row.name, customer=row.customer,
            invoice=row.return_against,
            available=str(-Decimal(str(row.outstanding_amount))))
            for row in rows[:page_length]],
            "sources": [], "offset": offset,
            "has_more": len(rows) > page_length}
    note = frappe.db.get_value("Sales Invoice",
        {**filters, "name": credit_note},
        ["name", "customer", "return_against", "outstanding_amount"],
        as_dict=True)
    if not note:
        frappe.throw(frappe._("La nota no tiene crédito disponible en este establecimiento"))
    source_filters = {"property": prop.name, "company": prop.company,
        "customer": note.customer,
        "kind": ["in", ["Payment", "Advance", "Guarantee Applied"]],
        "status": "Posted"}
    source_matches = ([
        ["HS Payment", "name", "like", "%" + source_search + "%"],
        ["HS Payment", "reference", "like", "%" + source_search + "%"],
    ]) if source_search else None
    candidates = frappe.get_all("HS Payment", filters=source_filters,
        or_filters=source_matches,
        fields=["name", "customer", "kind", "currency", "method",
                "sales_invoice", "stay", "booking", "folio",
                "payment_entry", "journal_entry"],
        order_by="creation desc", limit_start=offset,
        limit_page_length=page_length + 1)
    from hospitality_suite.refunds import balance as refund_balance, invoice_available
    sources = []
    for source in candidates[:page_length]:
        if (not (source.payment_entry or source.journal_entry) or
                source.kind == "Payment" and
                source.sales_invoice == note.return_against and
                not (source.stay or source.booking or source.folio)):
            continue
        values = refund_balance(prop, frappe.get_doc("HS Payment", source.name))
        if (values.remaining <= 0 or
                values.funds.account != prop.receivable_account):
            continue
        available = invoice_available(values, note.return_against)
        if available > 0:
            sources.append(dict(credit_note=note.name, source=source.name,
                kind=source.kind, customer=source.customer,
                currency=source.currency, method=source.method,
                remaining=str(values.remaining),
                available_party=str(available)))
    return {"notes": [dict(name=note.name, customer=note.customer,
        invoice=note.return_against,
        available=str(-Decimal(str(note.outstanding_amount))))],
        "sources": sources, "offset": offset,
        "has_more": len(candidates) > page_length}


@frappe.whitelist(methods=["POST"])
def execute(property_name, action, request_key, data=None):
    data = payload({} if data is None else data)
    if not isinstance(action,str) or action not in COMMANDS:
        frappe.throw(frappe._("Acción desconocida"))
    if standalone_accounting.provider() == "pms" and action in ERP_ONLY_ACTIONS:
        frappe.throw(frappe._("Use el flujo PMS de este sitio para la operación financiera"))
    permission, handler = COMMANDS[action]
    body = {**data, "operation": action}
    return command(property_name, permission, request_key, body, lambda prop: handler(prop, data))


@frappe.whitelist()
def preview(property_name, data, action="reserve"):
    if standalone_accounting.provider() == "pms" and action in ERP_ONLY_ACTIONS:
        frappe.throw(frappe._("Use el flujo PMS de este sitio para la operación financiera"))
    permission="inventory" if action=="purchase_order" else "service" if action=="request_service" else "approve" if action in ("adjust_stock","retire_sensitive","credit_note","pms_legacy_direct_experience_review") else "commission" if action=="agent_commission" else "finance" if action in ("invoice","payment","direct_sale","pms_direct_sale","day_pass_no_room","cash_expense_reviewed","settle_payment","supplier_payment","finance_post","pms_direct_experience_order","pms_direct_experience_delivery") else "reserve" if action in ("reserve","booking_status","modify_reservation","convert_portal","confirm_booking_draft","experience_order") else "stay"
    prop = require(property_name, permission)
    with selected_property(prop):
        return _preview(prop,payload(data),action)


def _preview(prop,data,action):
    if action == "request_service":
        return (standalone_services.quote(prop, data) if standalone_accounting.provider() == "pms"
                else inventory.service_quote(prop, data))
    if action == "experience_order":
        return travel_experiences.order_quote(prop,data)
    if action == "pms_direct_experience_order":
        return travel_experiences.direct_order_quote(prop,data)
    if action == "pms_legacy_direct_experience_review":
        return travel_experiences.legacy_direct_quote(prop,data)
    if action == "pms_direct_experience_delivery":
        return travel_experiences.direct_delivery_quote(prop,data)
    if action == "agent_commission":
        return travel_experiences.commission_quote(prop,data)
    if action == "finance_post":
        return financial_movements.financial_preview(prop,data)
    if action == "cash_expense_reviewed":
        return treasury.expense_quote(prop,data)
    if action == 'confirm_booking_draft':
        return booking_drafts.preview(prop,data)
    if action=='invoice':
        return accounting.invoice_quote(prop,data)
    if action == "reserve":
        return operations.quote_request(prop, data)
    if action == "extend":
        return operations.extension_quote(prop, data)
    if action=="change_room":
        return operations.room_change_quote(prop,data)
    if action=="modify_reservation":
        doc,values,excluded=operations.modification_values(prop,data)
        return operations.quote_request(prop,values,exclude=excluded,
            previous_agent_pct=doc.agent_commission_pct if values["travel_agent"]==doc.travel_agent else None)
    if action=="booking_status":
        booking=document("HS Booking",data["booking"],"reserve")
        if standalone_accounting.provider() == "pms":
            from hospitality_suite.standalone_booking_fee import quote
            return quote(prop, booking, data["status"])
        return accounting.cancellation_fee(prop,booking,data["status"])
    if action=="check_in":
        return operations.arrival_quote(prop,data)
    if action=="departure":
        return timing.departure(prop,data)
    if action=="direct_sale":
        require(prop.name,"finance")
        return direct_sales.quote(prop,data)
    if action=="pms_direct_sale":
        return standalone_direct_sales.quote(prop,data)
    if action=="day_pass_no_room":
        return (standalone_day_pass.quote(prop, data) if standalone_accounting.provider() == "pms"
                else day_pass.quote_without_room(prop,data))
    if action=="payment":
        require(prop.name,"finance")
        return accounting.payment_quote(prop,data)
    if action=='credit_note':
        return accounting.credit_note_quote(prop,data)
    if action=="settle_payment":
        return treasury.settlement_quote(prop,data)
    if action=="supplier_payment":
        return procurement.supplier_payment_quote(prop,data)
    if action=="adjust_stock":
        return procurement.adjustment_quote(prop,data)
    if action=="purchase_order":
        return procurement.purchase_order_quote(prop,data)
    if action=="retire_sensitive":
        return privacy.quote(prop,data)
    if action=="convert_portal":
        request_doc,values=portal.conversion_values(prop,data)
        excluded=frappe.get_all("HS Allocation",filters={"portal_request":request_doc.name,"status":"Active"},pluck="name")
        return operations.quote_request(prop,values,exclude=excluded)
    frappe.throw(frappe._("Cotización desconocida"))


@frappe.whitelist()
def service_configuration(property_name,item=None):
    from hospitality_suite.item_configuration import configuration
    return configuration(property_name,item)


@frappe.whitelist()
def service_accounting_configuration(property_name):
    return service_accounting.configuration(property_name)


def may(action):
    return is_system() or bool(set(ACTIONS[action]).intersection(frappe.get_roles()))


@frappe.whitelist()
def stay_board(property_name,date=None,view='hosted',offset=0,page_length=25):
    from hospitality_suite.desk_board import board
    return board(property_name,date,view,offset,page_length)


@frappe.whitelist()
def home_queue_summary(property_name):
    from hospitality_suite.desk_board import home_summary
    return home_summary(property_name)


@frappe.whitelist()
def ticket_board(property_name,view='open',offset=0,page_length=40):
    return tickets.board(property_name,view,offset,page_length)


@frappe.whitelist()
def ticket_detail(name,offset=0,page_length=100):
    return tickets.detail(name,offset,page_length)


@frappe.whitelist()
def credit_overview(property_name,offset=0,page_length=50):
    return credit.overview(property_name,offset,page_length)


@frappe.whitelist()
def erp_credit_customer_search(property_name, search):
    return credit.customer_search(property_name, search)


@frappe.whitelist()
def credit_status(property_name,customer,offset=0,page_length=100):
    return credit.status(property_name,customer,offset,page_length)


@frappe.whitelist()
def portfolio_snapshot():
    from hospitality_suite.portfolio import snapshot
    return snapshot()


@frappe.whitelist()
def health_snapshot(property_name):
    from hospitality_suite.health import snapshot
    return snapshot(property_name)


def project(dt, prop, fields=None, filters=None, or_filters=None):
    from hospitality_suite.paging import permitted_all
    return permitted_all(dt, filters={"property": prop.name, **(filters or {})},
                         or_filters=or_filters, fields=fields or ["*"])


@frappe.whitelist()
def bootstrap(property_name=None):
    names = allowed_properties()
    props = frappe.get_all("HS Property", filters={"name": ["in", names]}, fields=["name", "company", "property_name", "brand_name", "mode", "day_pass_item", "time_zone", "currency", "business_date", "discreet_mode", "inspection_required", "guest_id_required"])
    roles = frappe.get_roles()
    pages = [dict(route=route, title=title, icon=PAGE_ICONS[route], module=PAGE_MODULES[route])
             for route, (title, accepted) in PAGES.items() if is_system() or set(roles).intersection(accepted)]
    navigation_modules = [{key: value for key, value in module.items() if key != "routes"} for module in NAV_MODULES]
    result = dict(user=frappe.session.user, properties=props, pages=pages, navigation_modules=navigation_modules,
                  actions=[a for a in ACTIONS if may(a)],
                  accounting_provider=standalone_accounting.provider(), server_time=str(now_datetime()))
    result["can_create_property"]=is_system()
    result["can_manage_users"]=is_system()
    result["system_timezone"] = frappe.utils.get_system_timezone()
    if not property_name:
        return result
    prop = require(property_name)
    if standalone_accounting.provider() == "pms":
        result["accounting_provider"] = "pms"
        result["petty_visible"] = (is_system() or
            prop.petty_cash_responsible == frappe.session.user or
            may("finance") or may("report"))
        result["accepted_currencies"] = sorted(standalone_currency.enabled_currencies(prop))
        result["rooms"] = project("HS Room", prop,
            ["name", "room_number", "category", "floor", "zone", "cleaning_status", "active"])
        result["categories"] = project("HS Category", prop, ["name", "category_name", "capacity"])
        result["cleaning"] = project("HS Cleaning Task", prop,
            ["name", "room", "kind", "status", "priority", "assigned_to"])
        return result
    if any(may(a) for a in ("reserve","finance","report")):
        result["travel_experiences"]=travel_experiences.board(prop)
    petty_visible=(may("finance") or may("report") or prop.petty_cash_responsible==frappe.session.user or
                   frappe.db.exists("HS Petty Cash Handover", {"property":prop.name,"status":"Awaiting Acceptance","incoming":frappe.session.user}) or
                   frappe.db.exists("HS Petty Cash Handover", {"property":prop.name,"status":"Awaiting Acceptance","outgoing":frappe.session.user}))
    result["petty_visible"] = bool(petty_visible)
    if not petty_visible:
        result["pages"]=[p for p in result["pages"] if p["route"]!="hospitality-petty-cash"]
    result["inventory_currency"]=frappe.db.get_value("Company",prop.company,"default_currency")
    result["default_warehouse"]=prop.warehouse
    result["property_now"] = now_local(prop).isoformat()
    if may("laundry"):
        result["laundry"] = guest_laundry.board(prop)
    if may("block"):
        result["room_blocks"] = room_blocks.board(prop)
    result["print_formats"]=dict(invoice=prop.invoice_print_format or "HS Factura",receipt=prop.receipt_print_format or "HS Recibo")
    result["rooms"] = project("HS Room", prop, ["name", "room_number", "category", "floor", "zone", "cleaning_status", "active", "parking"])
    result["categories"] = project("HS Category", prop, ["name", "category_name", "capacity"])
    # Minimal operational projection is intentionally separate from stay documents.
    active = frappe.get_all("HS Stay", filters={"property": prop.name, "status": "Active"}, fields=["name", "room", "starts_at", "ends_at"])
    result["occupied"] = active
    result["blocks"] = frappe.get_all("HS Allocation", filters={"property": prop.name,
        "kind": ["in", ["Maintenance", "Room Block"]], "status": "Active"},
        fields=["room", "starts_at", "ends_at", "kind", "room_block"])
    result["rooms"].sort(key=lambda r: r.room_number)
    if may("stay") or may("finance"):
        from hospitality_suite.desk_board import room_arrivals
        result["room_arrivals"]=room_arrivals(prop)
        result["stays"] = project("HS Stay", prop)
        result["bookings"] = project("HS Booking", prop)
        result["guests"] = project("HS Guest", prop, ["name", "full_name", "customer"])
        result["rates"] = project("HS Rate", prop, ["name", "title", "category", "mode", "day_pass", "currency", "amount", "block_hours"])
        result["folios"] = project("HS Folio", prop)
        result["portal_requests"] = [row for row in project("HS Portal Request",prop,filters={"status":["in",["Hold","Requested"]]})
                                     if row.status=="Hold" or row.request_until and row.request_until>now_datetime()]
        result["services"] = project("HS Service Request", prop)
        result["day_passes"] = project("HS Day Pass",prop,["name","customer","guest","people","starts_at","ends_at","status","sales_invoice","service"])
        for day_pass_record in result["day_passes"]:
            day_pass_record["effective_status"] = ("Cancelled" if day_pass_record.status=="Cancelled" else
                "Upcoming" if day_pass_record.starts_at>now_datetime() else
                "Expired" if day_pass_record.ends_at<=now_datetime() else "Active")
        result["billing_parties"]=project("HS Billing Party",prop)
        customers = set(r.customer for r in result["guests"] + result["folios"] + result["bookings"] + result["billing_parties"] if r.get("customer"))
        result["customers"] = [dict(name=n, customer_name=frappe.db.get_value("Customer", n, "customer_name")) for n in sorted(customers)]
    if may("finance") or may("report"):
        from hospitality_suite.payment_policies import policies
        result["payment_policies"]=policies(prop)
        result["denominations"]=frappe.parse_json(prop.get("cash_denominations") or "{}")
        result["shifts"] = project("HS Shift", prop)
        for shift in result["shifts"]:
            shift["current_expected"]=cashier.expected(shift)
            frozen=frappe.parse_json(shift.denominations or "{}")
            shift["expected_by_currency"] = frozen.get("expected",shift["current_expected"]) if shift.status=="Closed" else shift["current_expected"]
        result["payment_methods"] = project("HS Payment Method", prop)
        result["payments"] = project("HS Payment", prop)
        from hospitality_suite.native_pos import movements
        result["native_pos"]=[{**row,"amount":str(row["amount"])} for row in movements(prop.name)]
        result["expense_categories"]=project("HS Expense Category",prop)
        result["treasury_concepts"]=project("HS Treasury Concept",prop)
        result["treasury_movements"]=project("HS Treasury Movement",prop)
        result["suppliers"]=project("HS Supplier",prop)
        result["purchase_orders"]=frappe.get_list("Purchase Order",filters={"hs_property":prop.name,"docstatus":1,"status":["not in",["Closed","Cancelled","Completed"]]},fields=["name","supplier","currency","grand_total","schedule_date"],limit=500)
        for order in result["purchase_orders"]:
            order["items"]=[dict(name=r.name,item=r.item_code,quantity=r.qty,received_quantity=r.received_qty,rate=r.rate) for r in frappe.get_doc("Purchase Order",order.name).items]
        result["purchase_receipts"]=frappe.get_list("Purchase Receipt",filters={"hs_property":prop.name,"docstatus":1,"per_billed":["<",100],"is_return":0},fields=["name","supplier","currency","grand_total"],limit=500)
        result["purchase_invoices"]=frappe.get_list("Purchase Invoice",filters={"hs_property":prop.name,"docstatus":1,"outstanding_amount":[">",0],"is_return":0},fields=["name","supplier","currency","outstanding_amount","bill_no"],limit=500)
    if petty_visible:
        result["petty_cash"]=financial_movements.fund_view(prop)
        result["petty_expenses"]=project("HS Petty Cash Expense",prop)
        result["petty_renditions"]=project("HS Petty Cash Rendition",prop)
        result["petty_handovers"]=project("HS Petty Cash Handover",prop)
        if "expense_categories" not in result:
            result["expense_categories"]=project("HS Expense Category",prop)
    if any(may(a) for a in ("inventory","clean","maintain","report","service")):
        result["warehouses"]=[dict(name=n,warehouse_name=frappe.db.get_value("Warehouse",n,"warehouse_name")) for n in procurement.warehouses(prop)]
    result["cleaning"] = project("HS Cleaning Task", prop, ["name", "room", "kind", "status", "priority", "assigned_to", "modified", "checklist", "notes","started_at","completed_at","inspected_by"])
    for task in result["cleaning"]:
        task["assigned_label"]=frappe.db.get_value("User",task.assigned_to,"full_name") if task.assigned_to else None
    result["equipment"]=project("HS Equipment",prop,["name","equipment_code","label","room","active","instructions"])
    result["maintenance"] = project("HS Maintenance Order", prop, ["name", "room","equipment","blocks_room","until_reopened", "title", "starts_at", "ends_at", "status", "modified", "notes","assigned_to"])
    if may("setup"):
        result["assets"] = frappe.get_all("Asset",filters={"hs_property":prop.name,"company":prop.company,"docstatus":["!=",2]},fields=["name","asset_name"],limit=500)
    result["incidents"]=project("HS Incident",prop,["name","room","kind","description","status","evidence","resolution","modified"])
    if may("maintain") or may("report"):
        for order in result["maintenance"]:
            doc=frappe.get_doc("HS Maintenance Order",order.name)
            order["cost"]=doc.cost
            order["evidence"]=doc.evidence
            order["parts"]=[r.as_dict() for r in doc.parts]
    if may("report"):
        from hospitality_suite.reports import summary, REPORTS
        from hospitality_suite.close_financials import display_groups
        result["close_financial_groups"]=display_groups()
        from hospitality_suite.report_formatting import LABELS
        from hospitality_suite.printing import VALUE_LABELS
        result["summary"] = summary(prop)
        result["reports"] = list(REPORTS)
        result["report_labels"]={key:frappe._(value) for key,value in LABELS.items()}
        result["report_values"]={key:frappe._(value) for key,value in VALUE_LABELS.items()}
        result["closes"] = project("HS Daily Close", prop)
    if may("approve"):
        result["retention_runs"]=project("HS Retention Run",prop,["name","status","approved_by","approved_at","attempts","last_error","modified"])
        for run in result["retention_runs"]:
            counts=current_all_retention_files(run.name)
            run["file_counts"]={status:sum(r.status==status for r in counts) for status in ("Pending","Deleted","Shared","Failed")}
    if any(may(a) for a in ("clean","service","maintain","inventory")):
        from hospitality_suite.catalog import bootstrap_items
        result["items"]=bootstrap_items(result)
    return result


@frappe.whitelist()
def catalog_search(property_name,txt="",purpose="any"):
    from hospitality_suite.catalog import search
    return search(property_name,txt,purpose)


def current_all_retention_files(name):
    from hospitality_suite.service import current_all
    return current_all("HS Retention File",filters={"parent":name,"parenttype":"HS Retention Run"},fields=["status"])


@frappe.whitelist()
def retention_candidates(property_name):
    return privacy.candidates(require(property_name,"approve"))


@frappe.whitelist()
def retention_history(property_name, offset=0, page_length=25):
    prop = require(property_name, "approve")
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de retención"))
    if offset < 0 or not 1 <= page_length <= 50:
        frappe.throw(frappe._("Revise la paginación de retención"))
    filters = {"property": prop.name}
    runs = frappe.get_all("HS Retention Run", filters=filters,
        fields=["name", "status", "approved_by", "approved_at", "attempts",
                "last_error", "modified"], order_by="approved_at desc, name desc",
        limit_start=offset, limit_page_length=page_length)
    for run in runs:
        files = current_all_retention_files(run.name)
        run["file_counts"] = {status: sum(row.status == status for row in files)
            for status in ("Pending", "Deleted", "Shared", "Failed")}
    return {"property": prop.name, "total": frappe.db.count("HS Retention Run", filters),
            "offset": offset, "page_length": page_length, "runs": runs}


@frappe.whitelist()
def stay_detail(name):
    doc = document("HS Stay", name)
    prop = require(doc.property)
    folios = accounting.folios_for_stay(doc)
    for folio in folios:
        folio["balance"] = accounting.folio_balance(folio.name)
    from hospitality_suite.tariff_explanations import describe_charge
    charges=project("HS Charge",prop,filters={"stay":name})
    for row in charges:
        row['pricing']=describe_charge(row)
        from hospitality_suite.display_labels import generated_label
        row['description_label']=generated_label(row.description)
    return dict(stay=doc.as_dict(), folios=folios, charges=charges,
                segments=project("HS Allocation", prop, filters={"stay": name}))


@frappe.whitelist()
def stay_page(property_name, status="active", search="", offset=0, page_length=25):
    """Find current and historical stays without loading the full reception snapshot."""
    from hospitality_suite.paging import page
    from hospitality_suite.time import local

    prop = require(property_name, "stay")
    states = {"active": "Active", "history": "Checked Out"}
    if status not in states or not isinstance(search, str) or len(search) > 80:
        frappe.throw(frappe._("Revise los filtros de estancias"))
    page([], offset, page_length)
    start, length = int(offset), int(page_length)
    where = "s.property=%s AND s.company=%s AND s.status=%s"
    values = [prop.name, prop.company, states[status]]
    query = search.strip()
    if query:
        choices = ["s.name LIKE %s", "s.booking LIKE %s", "r.room_number LIKE %s"]
        if not prop.discreet_mode:
            choices.append("g.full_name LIKE %s")
        where += " AND (" + " OR ".join(choices) + ")"
        values.extend(["%" + query + "%"] * len(choices))
    rows = frappe.db.sql(
        "SELECT s.name,s.status,s.booking,s.guest,s.customer,s.room,"
        "s.starts_at,s.ends_at,s.actual_check_in,s.actual_check_out,"
        "s.currency,s.amount,s.modified,g.full_name AS guest_label,"
        "r.room_number AS room_label "
        "FROM `tabHS Stay` s "
        "LEFT JOIN `tabHS Guest` g ON g.name=s.guest AND g.property=s.property "
        "AND g.company=s.company "
        "LEFT JOIN `tabHS Room` r ON r.name=s.room AND r.property=s.property "
        "AND r.company=s.company "
        "WHERE " + where +
        (" ORDER BY s.actual_check_out DESC,s.creation DESC,s.name DESC "
         if status == "history" else
         " ORDER BY s.actual_check_in DESC,s.creation DESC,s.name DESC ") +
        "LIMIT %s OFFSET %s", [*values, length + 1, start], as_dict=True)
    more = len(rows) > length
    rows = rows[:length]
    return {"property": prop.name, "status": status, "search": search,
            "offset": start, "page_length": length, "has_more": more,
            "rows": [{"name": row.name, "status": row.status,
                      "booking": row.booking, "guest": row.guest,
                      "guest_label": (frappe._("Huésped registrado") if prop.discreet_mode
                                      else row.guest_label or frappe._("Por registrar")),
                      "customer": row.customer, "room": row.room,
                      "room_label": row.room_label or row.room,
                      "starts_at_local": local(row.starts_at, prop).isoformat() if row.starts_at else None,
                      "ends_at_local": local(row.ends_at, prop).isoformat() if row.ends_at else None,
                      "actual_check_in_local": local(row.actual_check_in, prop).isoformat() if row.actual_check_in else None,
                      "actual_check_out_local": local(row.actual_check_out, prop).isoformat() if row.actual_check_out else None,
                      "currency": row.currency, "amount": str(row.amount or 0),
                      "modified": str(row.modified)} for row in rows]}


@frappe.whitelist()
def stay_overview(property_name, stay):
    """One authorized stay and its folios, including shared group folios."""
    from hospitality_suite.time import local

    prop = require(property_name, "stay")
    doc = property_document(prop, "HS Stay", stay, "stay")
    guest_label = frappe.db.get_value("HS Guest", {"name": doc.guest,
        "property": prop.name, "company": prop.company}, "full_name")
    room_label = frappe.db.get_value("HS Room", {"name": doc.room,
        "property": prop.name, "company": prop.company}, "room_number")
    payer_type, payer_field = (("HS Party", "party_name")
        if standalone_accounting.provider() == "pms" else ("Customer", "customer_name"))
    payer_filters = {"name": doc.customer}
    if payer_type == "HS Party":
        payer_filters.update(property=prop.name, organization=prop.organization)
    payer_label = frappe.db.get_value(payer_type, payer_filters, payer_field)
    folios = accounting.folios_for_stay(doc)
    return {"property": prop.name, "stay": doc.name, "status": doc.status,
            "booking": doc.booking, "guest": doc.guest,
            "guest_label": (frappe._("Huésped registrado") if prop.discreet_mode
                            else guest_label or frappe._("Por registrar")),
            "customer_label": payer_label or frappe._("Por definir"),
            "room": doc.room, "room_label": room_label or doc.room,
            "starts_at_local": local(doc.starts_at, prop).isoformat() if doc.starts_at else None,
            "ends_at_local": local(doc.ends_at, prop).isoformat() if doc.ends_at else None,
            "actual_check_in_local": local(doc.actual_check_in, prop).isoformat() if doc.actual_check_in else None,
            "actual_check_out_local": local(doc.actual_check_out, prop).isoformat() if doc.actual_check_out else None,
            "currency": doc.currency, "amount": str(doc.amount or 0),
            "modified": str(doc.modified),
            "folios": [{"name": folio.name, "label": folio.label,
                        "shared": not bool(folio.stay),
                        "status": folio.status,
                        "balance": accounting.folio_balance(folio.name)}
                       for folio in folios]}


@frappe.whitelist()
def stay_charge_page(property_name, stay, offset=0, page_length=25):
    from hospitality_suite.paging import page

    prop = require(property_name, "stay")
    property_document(prop, "HS Stay", stay, "stay")
    page([], offset, page_length)
    start, length = int(offset), int(page_length)
    rows = frappe.get_list("HS Charge", filters={"property": prop.name,
        "company": prop.company, "stay": stay},
        fields=["name", "folio", "kind", "description", "status",
                "amount", "currency", "business_date"],
        order_by="creation desc,name desc", limit=length + 1, offset=start)
    more = len(rows) > length
    return {"property": prop.name, "stay": stay, "offset": start,
            "page_length": length, "has_more": more,
            "rows": [{"name": row.name, "folio": row.folio,
                      "kind": row.kind, "description": row.description,
                      "status": row.status, "amount": str(row.amount or 0),
                      "currency": row.currency,
                      "business_date": str(row.business_date) if row.business_date else None}
                     for row in rows[:length]]}


@frappe.whitelist()
def stay_companions(property_name, stay, search="", offset=0, page_length=25):
    """Provide a bounded guest picker without loading ERPNext folio details."""
    prop = require(property_name, "guest")
    doc = property_document(prop, "HS Stay", stay, "guest")
    if doc.status != "Active":
        frappe.throw(frappe._("Seleccione una estancia activa"))
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de huéspedes"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de huéspedes"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(frappe._("Revise la paginación de huéspedes"))
    snapshot = frappe.parse_json(doc.quote_snapshot or "{}")
    capacity = int(snapshot.get("people") or 1)
    selected_names = [row.guest for row in doc.guests if row.guest != doc.guest]
    selected = (frappe.get_all("HS Guest", filters={"property": prop.name,
        "company": prop.company, "name": ["in", selected_names]},
        fields=["name", "full_name", "identity_number"],
        limit_page_length=len(selected_names))
        if selected_names else [])
    for row in selected:
        row["has_identity"] = bool(row.pop("identity_number"))
    where = "property=%s AND company=%s AND name!=%s"
    values = [prop.name, prop.company, doc.guest]
    if search.strip():
        where += " AND (name LIKE %s OR full_name LIKE %s)"
        values.extend(["%" + search.strip() + "%"] * 2)
    total = frappe.db.sql("SELECT COUNT(*) FROM `tabHS Guest` WHERE " + where,
        values, as_list=True)[0][0]
    candidates = frappe.db.sql(
        "SELECT name,full_name,identity_number FROM `tabHS Guest` WHERE " + where +
        " ORDER BY full_name ASC,name ASC LIMIT %s OFFSET %s",
        [*values, page_length, offset], as_dict=True)
    for row in candidates:
        row["has_identity"] = bool(row.pop("identity_number"))
    return {"stay": doc.name, "modified": str(doc.modified),
        "principal": doc.guest, "capacity": capacity,
        "guest_id_required": bool(prop.guest_id_required),
        "selected": selected, "candidates": candidates, "total": int(total),
        "offset": offset, "has_more": offset + len(candidates) < total}


@frappe.whitelist()
def availability_search(property_name, starts_at, ends_at, category, people=1, quantity=1):
    from hospitality_suite.availability_search import search
    return search(property_name, starts_at, ends_at, category, people, quantity)


@frappe.whitelist()
def availability_options(property_name):
    """Small, property-scoped picker for the React interval search."""
    prop = require(property_name, "reserve")
    return {"property": prop.name, "time_zone": prop.time_zone, "mode": prop.mode,
            "local_now": now_local(prop).strftime("%Y-%m-%dT%H:%M"),
            "categories": frappe.get_all("HS Category", filters={"property": prop.name},
                fields=["name", "category_name", "capacity"],
                order_by="category_name asc, name asc")}


@frappe.whitelist()
def rate_calendar(property_name, category, from_date, days=14, mode=None, people=1, hours=3):
    from hospitality_suite.rate_calendar import view
    return view(property_name, category, from_date, days, mode, people, hours)


def _require_erp_reporting():
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Use los reportes PMS de este sitio"))


@frappe.whitelist()
def report(property_name, report_name, filters=None):
    _require_erp_reporting()
    from hospitality_suite.reports import rows
    from hospitality_suite.report_queries import scopes,metadata,validate,reconciliation_scopes
    filters=payload(filters or {})
    selected=scopes(property_name,filters.get("company"))
    meta=metadata(report_name)
    validate(filters,meta)
    if meta["base"]=="Conciliación":
        selected=reconciliation_scopes(selected,filters)
    records=[]
    for prop in selected:
        batch=rows(prop,report_name,filters)
        if not property_name:
            for row in batch:
                row.update(company=prop.company,property=prop.name,time_zone=prop.time_zone)
                row.setdefault("_display",{})["property"]=prop.property_name
        records.extend(batch)
    return records


@frappe.whitelist()
def erp_report_catalog(property_name):
    require(property_name, "report")
    _require_erp_reporting()
    from hospitality_suite.reports import REPORTS
    from hospitality_suite.report_formatting import LABELS
    from hospitality_suite.printing import VALUE_LABELS
    roles = set(frappe.get_roles())
    return dict(reports=list(REPORTS),
        labels={key: frappe._(value) for key, value in LABELS.items()},
        values={key: frappe._(value) for key, value in VALUE_LABELS.items()},
        can_export=is_system() or bool(roles.intersection({
            "HS Administrator", "HS Manager", "HS Accountant"})))


@frappe.whitelist()
def report_options(property_name,report_name,company=None):
    """Return only applicable filters and options from authorized properties."""
    _require_erp_reporting()
    from hospitality_suite.report_queries import scopes,metadata
    selected=scopes(property_name,company)
    meta=metadata(report_name)
    from hospitality_suite.reports import REPORTS
    base_dt=REPORTS[meta["base"]][0]
    meta["statuses"]=(frappe.get_meta(base_dt).get_field("status").options or "").splitlines() if base_dt and frappe.get_meta(base_dt).has_field("status") else ["OK","Difference"] if meta["base"]=="Conciliación" else []
    meta["kinds"]=(frappe.get_meta(base_dt).get_field("kind").options or "").splitlines() if base_dt and frappe.get_meta(base_dt).has_field("kind") else []
    props=frappe.get_all("HS Property",filters={"name":["in",allowed_properties()]},fields=["name","property_name","company"])
    result=dict(meta,properties=props,companies=sorted({p.company for p in props}),rooms=[],categories=[],shifts=[],stays=[],methods=[],warehouses=[],users=[],channels=[])
    users=set()
    for prop in selected:
        for key,dt,fields in (("rooms","HS Room",["name","room_number","category"]),("categories","HS Category",["name","category_name"]),
                              ("shifts","HS Shift",["name","cashier","opened_at","status"]),("methods","HS Payment Method",["name","mode_of_payment","currency"])):
            if ("method" if key=="methods" else "shift" if key=="shifts" else "category" if key=="categories" else "room") not in meta["filters"]:
                continue
            for row in project(dt,prop,fields):
                row["property_label"]=prop.property_name
                if key=="shifts":
                    row["label"]=f"{row.cashier} · {local_report_time(row.opened_at,prop)} · {row.name}"
                result[key].append(row)
        if "stay" in meta["filters"]:
            from hospitality_suite.report_presentation import Descriptions
            descriptions=Descriptions([prop])
            from hospitality_suite.printing import hs_label
            for row in project("HS Stay",prop,["name","actual_check_in","status"]):
                row["label"]=f"{descriptions.stay(row.name,include_time=True)} · {hs_label(row.status)}"
                row["property_label"]=prop.property_name
                result["stays"].append(row)
        if "warehouse" in meta["filters"]:
            from hospitality_suite.procurement import warehouses
            result["warehouses"] += [dict(name=n,warehouse_name=n,property_label=prop.property_name) for n in warehouses(prop)]
        if "user" in meta["filters"]:
            dt=REPORTS[meta["base"]][0]
            if dt:
                users.update((r.actor if dt=="HS Audit Event" else r.owner) for r in permitted_report_owners(dt,prop))
                if meta["base"]=="Producción":
                    users.update(r.owner for r in permitted_report_owners("HS Service Request",prop))
                    from hospitality_suite.paging import permitted_all
                    users.update(r.actor for r in permitted_all("HS Audit Event",filters={"property":prop.name,"source_doctype":"Sales Invoice","action":"on_submit"},fields=["actor"]))
            else:
                for native in ("Stock Entry","Stock Reconciliation","Purchase Receipt","Sales Invoice"):
                    users.update(r.owner for r in permitted_report_owners(native,prop))
        result["channels"] += [r.channel for r in project("HS Booking",prop,["channel"]) if r.channel]
        if "assigned_to" in meta["filters"]:
            users.update(r.assigned_to for r in project(base_dt,prop,["assigned_to"]) if r.assigned_to)
    users.discard(None)
    result["users"]=frappe.get_all("User",filters={"name":["in",list(users)]},fields=["name","full_name"])
    result["channels"]=sorted(set(result["channels"]+["Venta directa"]))
    return result


def local_report_time(value,prop):
    from hospitality_suite.time import local
    return local(value,prop).strftime("%d/%m/%Y %H:%M") if value else "—"


def permitted_report_owners(dt,prop):
    from hospitality_suite.paging import permitted_all
    field="hs_property" if not dt.startswith("HS ") else "property"
    return permitted_all(dt,filters={field:prop.name},fields=["owner"]+(["actor"] if dt=="HS Audit Event" else []))


@frappe.whitelist()
def report_page(property_name,report_name,filters=None,offset=0,page_length=50):
    _require_erp_reporting()
    from hospitality_suite.paging import page
    from hospitality_suite.report_presentation import prepare
    from hospitality_suite.report_queries import scopes
    selected=payload(filters or {})
    records,columns=prepare(report_name,report(property_name,report_name,selected),scopes(property_name,selected.get("company")),selected.get("detail_level") or "operational")
    result=page(records,offset,page_length)
    result["columns"]=columns
    return result


@frappe.whitelist()
def guest_history(name,offset=0,page_length=50):
    from hospitality_suite.paging import permitted_all,page
    guest=document("HS Guest",name)
    companions=frappe.get_all("HS Stay Guest",filters={"guest":guest.name},fields=["parent","relationship"])
    relation={row.parent:row.relationship for row in companions}
    records=permitted_all("HS Stay",filters={"property":guest.property},
                          or_filters={"guest":guest.name,"name":["in",list(relation) or [""]]},
                          fields=["name","guest","room","starts_at","ends_at","actual_check_in","actual_check_out","status"])
    for row in records:
        row["relationship"]="Principal" if row.pop("guest")==guest.name else relation[row.name]
    from hospitality_suite.report_presentation import prepare
    records,columns=prepare("Historial de estancias",records,[require(guest.property)])
    result=page(records,offset,page_length)
    result["columns"]=columns
    return result


@frappe.whitelist()
def export_report(property_name, report_name, filters=None, file_format="xlsx"):
    _require_erp_reporting()
    from hospitality_suite.report_queries import scopes,metadata,describe_filters
    selected=scopes(property_name,payload(filters or {}).get("company"))
    if not is_system() and not set(frappe.get_roles()).intersection(["HS Administrator","HS Manager","HS Accountant"]):
        frappe.throw(frappe._("La exportación requiere gerencia o contabilidad"),frappe.PermissionError)
    from hospitality_suite.report_presentation import prepare
    records,headers=prepare(report_name,report(property_name,report_name,filters),selected,payload(filters or {}).get("detail_level") or "operational")
    headers=headers or ["Sin datos"]
    from hospitality_suite.report_formatting import xlsx_data,pdf_html
    if file_format=="xlsx":
        from frappe.utils.xlsxutils import make_xlsx
        data,widths,styles=xlsx_data(records,headers)
        content=make_xlsx(data,"Reporte",column_widths=widths,styles=styles).getvalue()
    elif file_format=="pdf":
        from frappe.utils.pdf import get_pdf,is_wkhtmltopdf_valid
        if not is_wkhtmltopdf_valid():
            frappe.throw(frappe._("El generador PDF del servidor requiere wkhtmltopdf con Qt parcheado. Solicite a administración revisar la instalación."))
        scope_label=selected[0].property_name+" · "+selected[0].time_zone if property_name else selected[0].company+" · establecimientos autorizados"
        note=metadata(report_name)['note']+" "+describe_filters(selected,report_name,payload(filters or {}))
        content=get_pdf(pdf_html(report_name,scope_label,records,headers,note),{"orientation":"Landscape","footer-right":"[page] / [topage]","footer-font-size":"8","footer-spacing":"5"})
    else:
        frappe.throw(frappe._("Formato no permitido"))
    frappe.local.response.update(filename="hospitality-report."+file_format,filecontent=content,type="binary")


@frappe.whitelist(methods=["POST"])
def save_setup(property_name, section, data, request_key, expected_modified=None):
    values = payload(data)
    submitted = dict(values)
    if section in ("property", "rate") and values.get("mode"):
        from hospitality_suite.mode import normalize_mode
        values["mode"] = normalize_mode(values["mode"])
    allowed = {
        "property": ["lodging_charge_policy", "brand_name", "mode", "time_zone", "check_in_time", "check_out_time", "cleaning_minutes", "inspection_required", "discreet_mode", "hold_minutes", "guest_id_required", "allow_credit", "close_time", "retention_days", "portal_enabled", "cost_center", "warehouse", "laundry_warehouse", "receivable_account", "guarantee_account", "cash_transfer_account", "petty_cash_account", "petty_cash_responsible", "petty_cash_overage_account", "petty_cash_shortage_account", "price_list", "lodging_item", "day_pass_item", "tax_template", "tax_policy_confirmed", "financial_enabled", "cancellation_fee_mode", "cancellation_fee_value", "no_show_fee_mode", "no_show_fee_value", "penalty_item", "early_hour_rate", "late_hour_rate", "schedule_grace_minutes", "schedule_rounding_minutes", "timing_item", "checkout_inspection_required", "checkout_quote_minutes", "cash_denominations"],
        "room": ["name", "room_number", "category", "floor", "zone", "beds", "parking", "active"],
        "category": ["name", "category_name", "capacity", "amenities","max_extra_beds","portal_description","portal_image"],
        "rate": ["name", "title", "category", "mode", "day_pass", "currency", "amount", "block_hours", "extra_hour_rate", "grace_minutes", "rounding_minutes", "additional_person_rate", "included_people","extra_bed_rate", "priority", "valid_from", "valid_to", "weekdays", "customer", "night_start","night_end","active", "change_reason"],
        "payment_method": ["name", "mode_of_payment", "account", "currency", "reference_required", "is_cash"],
        "billing_party": ["customer","kind","credit_authorized","credit_limit","credit_days","valid_until","reason"],
    }
    allowed["property"] += ["invoice_series","payment_series","invoice_print_format","receipt_print_format"]
    allowed["property"] += ["advance_policy","guarantee_policy","extra_hour_item"]
    allowed["property"] += ["agent_commission_item", "pms_commission_expense_account",
                            "pms_commission_payable_account"]
    allowed["property"] += list(standalone_linen.FIELDS)
    allowed["property"] += ["pms_exchange_variance_account"]
    allowed["property"] += ["income_account", "expense_account"]
    allowed["rate"].append("included_services")
    allowed["payment_method"]+=list(treasury.METHOD_FIELDS)
    allowed["expense_category"]=["name","label","account","max_amount","active"]
    allowed["treasury_concept"]=["label","nature","account","active"]
    allowed["supplier"]=["supplier","active"]
    allowed["equipment"]=["equipment_code","label","room","asset","active","instructions"]
    allowed["product"]=["name","product_code","product_name","product_type","income_account","tax_profile",
                        "expense_account","inventory_account","sales_rate","active"]
    if "included_services" in values:
        services=values["included_services"]
        if not isinstance(services,list) or len(services)>100:
            frappe.throw(frappe._("Revise la lista de servicios incluidos"))
        values["included_services"]=[{key:row.get(key) for key in ("item","quantity","basis")} for row in services]
    if section not in allowed or any(k not in allowed[section] for k in values):
        frappe.throw(frappe._("Campo de configuración no admitido"))
    if "pms_exchange_variance_account" in values and standalone_accounting.provider() != "pms":
        frappe.throw(frappe._("La cuenta de diferencia cambiaria pertenece al libro PMS"))
    def save(prop):
        if section == "property":
            from hospitality_suite.service import assert_version
            assert_version(prop,expected_modified)
            prop.update(values)
            prop.save()
            doc = prop
        else:
            if section == "product" and standalone_accounting.provider() != "pms":
                frappe.throw(frappe._("Los productos PMS solo se configuran sin ERPNext"))
            if section in ("product", "room", "category", "rate", "expense_category", "payment_method") and values.get("name"):
                from hospitality_suite.service import assert_version, locked_doc
                dt = {"product": "HS Product", "room": "HS Room",
                      "category": "HS Category", "rate": "HS Rate",
                      "expense_category": "HS Expense Category",
                      "payment_method": "HS Payment Method"}[section]
                doc = locked_doc(dt, values["name"])
                if doc.property != prop.name or doc.company != prop.company:
                    frappe.throw(frappe._("El registro pertenece a otro establecimiento"), frappe.PermissionError)
                assert_version(doc, expected_modified)
                doc.update({key: value for key, value in values.items() if key != "name"})
                doc.save()
                if section in ("product", "category", "expense_category", "payment_method"):
                    audit(prop, "Setup " + section, doc)
                return dict(name=doc.name)
            dt = {"room": "HS Room", "category": "HS Category", "rate": "HS Rate", "payment_method": "HS Payment Method","billing_party":"HS Billing Party","expense_category":"HS Expense Category","treasury_concept":"HS Treasury Concept","supplier":"HS Supplier","equipment":"HS Equipment", "product":"HS Product"}[section]
            if section == "product":
                values["organization"] = prop.organization
            doc = insert(dt, prop, **values)
        if section!='rate':audit(prop, "Setup " + section, doc)
        return dict(name=doc.name)
    return command(property_name, "setup", request_key, dict(operation="setup_" + section, **submitted), save)


@frappe.whitelist()
def audit_detail(property_name,name):
    from hospitality_suite.audit_trail import detail
    return detail(require(property_name,'report'),name)


@frappe.whitelist(methods=["POST"])
def create_guest(property_name, data, request_key):
    values = payload(data)
    from hospitality_suite.guest_profiles import create
    return command(property_name, "guest", request_key, dict(operation="create_guest", **values), lambda prop:create(prop,values))


@frappe.whitelist()
def guest_detail(name):
    if standalone_accounting.provider() == "pms":
        return standalone_reception.guest_detail(name)
    from hospitality_suite.guest_profiles import detail
    return detail(name)


@frappe.whitelist()
def guest_directory(property_name, search="", offset=0, page_length=25):
    prop = require(property_name, "guest")
    if not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de huéspedes"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la paginación de huéspedes"))
    if offset < 0 or offset > 1000000 or not 1 <= page_length <= 50:
        frappe.throw(frappe._("Revise la paginación de huéspedes"))
    where = "property=%s AND company=%s"
    values = [prop.name, prop.company]
    if search.strip():
        where += " AND (name LIKE %s OR full_name LIKE %s)"
        values.extend(["%" + search.strip() + "%"] * 2)
    total = frappe.db.sql("SELECT COUNT(*) FROM `tabHS Guest` WHERE " + where,
        values, as_list=True)[0][0]
    rows = frappe.db.sql("SELECT name,full_name FROM `tabHS Guest` WHERE " + where +
        " ORDER BY full_name ASC,name ASC LIMIT %s OFFSET %s",
        [*values, page_length, offset], as_dict=True)
    return {"property": prop.name, "total": int(total), "offset": offset,
        "has_more": offset + len(rows) < total, "rows": rows}


@frappe.whitelist(methods=["POST"])
def update_guest(property_name, name, modified, data, reason, request_key, related_versions=None):
    from hospitality_suite.guest_profiles import update
    values,versions=payload(data),payload(related_versions or {})
    body=dict(operation='update_guest',guest=name,modified=modified,values=values,reason=reason,related_versions=versions)
    return command(property_name,'guest',request_key,body,
        lambda prop: (standalone_reception.update_guest if standalone_accounting.provider() == "pms"
                      else update)(prop,name,modified,values,reason,versions))


@frappe.whitelist(methods=["POST"])
def create_property(data, request_key):
    return setup.create_property(payload(data),request_key)


@frappe.whitelist()
def onboarding_options():
    return setup.onboarding_options()


@frappe.whitelist()
def configuration(property_name):
    return require(property_name,"setup").as_dict()


@frappe.whitelist()
def setup_board(property_name):
    prop = require(property_name, "setup")
    scope = {"property": prop.name, "company": prop.company}
    return {
        "property": prop.as_dict(),
        "categories": frappe.get_all("HS Category", filters=scope,
            fields=["name", "modified", "category_name", "capacity", "amenities", "max_extra_beds"],
            order_by="category_name asc", limit_page_length=500),
        "rooms": frappe.get_all("HS Room", filters=scope,
            fields=["name", "modified", "room_number", "category", "floor", "zone", "beds", "parking", "active"],
            order_by="room_number asc", limit_page_length=1000),
        "rates": frappe.get_all("HS Rate", filters=scope,
            fields=["name", "modified", "title", "category", "mode", "day_pass", "currency",
                    "amount", "block_hours", "priority", "active"],
            order_by="title asc", limit_page_length=1000),
        "currencies": sorted(standalone_currency.enabled_currencies(prop)),
        "pms_variance_accounts": frappe.get_all("HS Account",
            filters={"property": prop.name, "organization": prop.organization,
                     "active": 1, "is_group": 0,
                     "root_type": ["in", ["Income", "Expense"]],
                     "account_currency": prop.currency},
            fields=["name", "account_code", "account_name", "root_type"],
            order_by="account_code asc", limit_page_length=0)
            if standalone_accounting.provider() == "pms" else [],
    }


@frappe.whitelist()
def financial_setup_options(property_name, field, search=""):
    """Company-scoped ERPNext choices for the property accounting form."""
    prop = require(property_name, "setup")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("La configuración contable ERPNext requiere el modo ERPNext"))
    if not isinstance(field, str) or not isinstance(search, str) or len(search) > 100:
        frappe.throw(frappe._("Revise la búsqueda de configuración contable"))
    account_roots = {
        "income_account": "Income", "expense_account": "Expense",
        "receivable_account": "Asset", "guarantee_account": "Liability",
        "cash_transfer_account": "Asset",
    }
    item_fields = {"lodging_item", "extra_hour_item", "day_pass_item",
                   "penalty_item", "timing_item", "agent_commission_item"}
    base_currency = frappe.db.get_value("Company", prop.company, "default_currency")
    if field in account_roots:
        doctype = "Account"
        filters = {"company": prop.company, "disabled": 0, "is_group": 0,
                   "root_type": account_roots[field],
                   "account_currency": prop.currency if field in {
                       "receivable_account", "guarantee_account"} else base_currency}
        if field == "receivable_account":
            filters["account_type"] = "Receivable"
        label_field = "account_name"
    elif field == "cost_center":
        doctype, label_field = "Cost Center", "cost_center_name"
        filters = {"company": prop.company, "disabled": 0, "is_group": 0}
    elif field in {"warehouse", "laundry_warehouse"}:
        doctype, label_field = "Warehouse", "warehouse_name"
        filters = {"company": prop.company, "disabled": 0, "is_group": 0}
    elif field in item_fields or field == "service_accounting_item":
        doctype, label_field = "Item", "item_name"
        filters = {"disabled": 0, "is_fixed_asset": 0}
        if field != "service_accounting_item":
            filters.update(is_sales_item=1, is_stock_item=0)
    elif field == "price_list":
        doctype, label_field = "Price List", "price_list_name"
        filters = {"enabled": 1, "selling": 1, "currency": prop.currency}
    elif field == "tax_template":
        doctype, label_field = "Sales Taxes and Charges Template", "title"
        filters = {"company": prop.company, "disabled": 0}
    else:
        frappe.throw(frappe._("Campo de configuración contable no admitido"))
    query = search.strip()
    matches = [["name", "like", f"%{query}%"],
               [label_field, "like", f"%{query}%"]] if query else None
    rows = frappe.get_all(doctype, filters=filters,
        or_filters=matches, fields=["name", label_field],
        order_by="name asc", limit_page_length=40)
    return [{"name": row.name, "label": row.get(label_field) or row.name} for row in rows]


@frappe.whitelist()
def setup_options(property_name):
    return setup.document_settings(require(property_name,"setup"))


@frappe.whitelist()
def user_access_board(property_name, offset=0, page_length=50):
    return setup.access_board(property_name, offset, page_length)


@frappe.whitelist(methods=["POST"])
def create_operational_user(data):
    return setup.create_operational_user(payload(data))


@frappe.whitelist()
def my_user_settings():
    return user_settings.read()


@frappe.whitelist()
def guest_portal_records(offset=0, page_length=25):
    return portal.guest_portal_records(offset, page_length)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def request_guest_portal_account(token):
    return portal.request_guest_account(token)


@frappe.whitelist(methods=["POST"])
def claim_guest_booking(token):
    return portal.claim_booking(token)


@frappe.whitelist(methods=["POST"])
def save_my_user_settings(data):
    return user_settings.save(payload(data))


@frappe.whitelist()
def booking_detail(name):
    doc = document("HS Booking",name)
    prop = require(doc.property)
    from hospitality_suite.booking_presentation import summary
    from hospitality_suite.time import local

    allocations = project("HS Allocation", prop,
        fields=["name", "booking", "room", "category", "booking_room"],
        filters={"booking": name, "kind": "Reservation", "status": "Active"})
    try:
        accepted = frappe.parse_json(doc.quote_snapshot or "{}")
    except (TypeError, ValueError):
        accepted = {}
    lines = (accepted.get("lines") or []) if isinstance(accepted, dict) else []
    first = lines[0] if isinstance(lines, list) and lines and isinstance(lines[0], dict) else {}
    rules = first.get("rules") if isinstance(first.get("rules"), dict) else {}
    mode = first.get("stay_type") or ("Day Pass" if rules.get("day_pass") else rules.get("mode")) or prop.mode
    has_stay = bool(frappe.db.exists("HS Stay", {"property": prop.name, "booking": doc.name}))
    workflow = dict(name=doc.name, status=doc.status, customer=doc.customer,
        guest=doc.guest, modified=str(doc.modified), currency=doc.currency,
        amount=str(doc.amount or 0), travel_agent=doc.travel_agent,
        agent_commission_pct=doc.agent_commission_pct,
        agent_commission_estimate=doc.agent_commission_estimate,
        starts_at_local=local(doc.starts_at, prop).strftime("%Y-%m-%d %H:%M") if doc.starts_at else None,
        ends_at_local=local(doc.ends_at, prop).strftime("%Y-%m-%d %H:%M") if doc.ends_at else None,
        mode=mode, modifiable=doc.status in ("Hold", "Confirmed") and not has_stay,
        can_arrive=doc.status in ("Confirmed", "Checked In") and bool(allocations),
        can_cancel=doc.status in ("Hold", "Confirmed"),
        rooms=[dict(category=row.category, room=row.room, people=row.people,
                    extra_beds=row.extra_beds, rate=row.rate, idx=row.idx)
               for row in doc.rooms])
    return dict(booking=doc.as_dict(), summary=summary(doc, prop),
        workflow=workflow,
        draft=booking_drafts.values_for(doc, prop) if doc.status == "Draft" else None,
        allocations=allocations)


@frappe.whitelist()
def reservation_page(property_name, status="current", search="", offset=0, page_length=25):
    """Bounded reservations and drafts for the React reception list."""
    from hospitality_suite.paging import page
    from hospitality_suite.time import local

    prop = require(property_name, "reserve")
    states = {"current": ["Hold", "Confirmed", "Checked In"],
              "history": ["Completed", "Cancelled", "No Show"],
              "draft": ["Draft"]}
    if status not in states or not isinstance(search, str) or len(search) > 80:
        frappe.throw(frappe._("Revise los filtros de reservas"))
    page([], offset, page_length)
    start, length = int(offset), int(page_length)
    filters = {"property": prop.name, "company": prop.company,
               "status": ["in", states[status]]}
    query = search.strip()
    or_filters = [["name", "like", f"%{query}%"],
                  ["channel", "like", f"%{query}%"]] if query else None
    rows = frappe.get_list("HS Booking", filters=filters, or_filters=or_filters,
        fields=["name", "status", "guest", "customer", "starts_at", "ends_at",
                "channel", "currency", "amount", "modified", "creation"],
        order_by="creation desc, name desc", limit=length + 1, offset=start)
    more = len(rows) > length
    rows = rows[:length]
    guest_names = {row.guest for row in rows if row.guest}
    guest_labels = {row.name: row.full_name for row in frappe.get_all("HS Guest",
        filters={"property": prop.name, "name": ["in", list(guest_names)]},
        fields=["name", "full_name"])} if guest_names else {}
    payer_names = {row.customer for row in rows if row.customer}
    if standalone_accounting.provider() == "pms":
        payer_labels = {row.name: row.party_name for row in frappe.get_all("HS Party",
            filters={"property": prop.name, "name": ["in", list(payer_names)]},
            fields=["name", "party_name"])} if payer_names else {}
    else:
        payer_labels = {row.name: row.customer_name for row in frappe.get_all("Customer",
            filters={"name": ["in", list(payer_names)]},
            fields=["name", "customer_name"])} if payer_names else {}
    return {"property": prop.name, "status": status, "search": search,
            "offset": start, "page_length": length, "has_more": more,
            "rows": [{"name": row.name, "status": row.status,
                      "guest": row.guest,
                      "guest_label": (frappe._("Huésped registrado") if prop.discreet_mode and row.guest
                                      else guest_labels.get(row.guest)),
                      "customer": row.customer,
                      "customer_label": payer_labels.get(row.customer),
                      "starts_at_local": local(row.starts_at, prop).isoformat() if row.starts_at else None,
                      "ends_at_local": local(row.ends_at, prop).isoformat() if row.ends_at else None,
                      "channel": row.channel, "currency": row.currency,
                      "amount": str(row.amount or 0), "modified": str(row.modified)}
                     for row in rows]}


@frappe.whitelist()
def calendar(property_name,starts_at,ends_at):
    from hospitality_suite.time import local
    prop=require(property_name)
    start,end=to_site(starts_at,prop),to_site(ends_at,prop)
    if end<=start or (end-start).days>31:
        frappe.throw(frappe._("Consulte un intervalo de hasta 31 días"))
    rows=project("HS Allocation",prop,fields=["name","room","category","starts_at","ends_at","kind","status","booking","stay","maintenance","room_block"],
                 filters={"starts_at":["<",end]},
                 or_filters=[["ends_at", ">", start], ["ends_at", "is", "not set"]])
    result=[]
    for row in rows:
        if row.ends_at and frappe.utils.get_datetime(row.ends_at)<=start:
            continue
        row["until_reopened"]=row.kind=="Maintenance" and not row.ends_at
        if not row.ends_at:
            row.ends_at=end
        if row.status=="Released" and row.kind not in ("Stay","Maintenance","Room Block"):
            continue
        if row.status=="Released" and row.kind=="Maintenance":
            order=frappe.get_doc("HS Maintenance Order",row.maintenance) if row.maintenance else None
            if not order or order.status!="Completed":
                continue
            row.ends_at=min(frappe.utils.get_datetime(row.ends_at),housekeeping.maintenance_finished_at(order))
            if row.ends_at<=frappe.utils.get_datetime(row.starts_at):
                continue
        if row.kind=="Room Block":
            block=frappe.db.get_value("HS Room Block",{"name":row.room_block,"property":prop.name},
                                      ["reason","status","released_on"],as_dict=True) if row.room_block else None
            if not block or (row.status=="Released" and block.status!="Released"):
                continue
            row["block_reason"]=block.reason
            if row.status=="Released":
                row.ends_at=min(frappe.utils.get_datetime(row.ends_at),frappe.utils.get_datetime(block.released_on))
                if row.ends_at<=frappe.utils.get_datetime(row.starts_at):
                    continue
        if row.kind=="Stay" and row.stay:
            stay=frappe.get_doc("HS Stay",row.stay)
            row.starts_at=max(frappe.utils.get_datetime(row.starts_at),frappe.utils.get_datetime(stay.actual_check_in))
            if stay.actual_check_out:
                row.ends_at=min(frappe.utils.get_datetime(row.ends_at),frappe.utils.get_datetime(stay.actual_check_out))
            if row.ends_at<=row.starts_at:
                continue
        if frappe.utils.get_datetime(row.ends_at)<=start:
            continue
        row.starts_at=local(row.starts_at,prop).isoformat()
        row.ends_at=local(row.ends_at,prop).isoformat()
        result.append(row)
    return result


@frappe.whitelist()
def room_calendar(property_name, from_date, view="week"):
    """A bounded room timeline with exact property-local window boundaries."""
    from datetime import UTC, date, datetime, time, timedelta
    import re
    from hospitality_suite.time import aware

    prop = require(property_name, "reserve")
    if (not isinstance(from_date, str) or
            not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_date) or
            view not in ("day", "week")):
        frappe.throw(frappe._("Revise la fecha y la vista del calendario"))
    try:
        first = date.fromisoformat(from_date)
        days = 1 if view == "day" else 7
        last = first + timedelta(days=days)
        start = aware(datetime.combine(first, time.min), prop.time_zone)
        end = aware(datetime.combine(last, time.min), prop.time_zone)
    except (ValueError, OverflowError):
        frappe.throw(frappe._("Revise la fecha del calendario"))
    if view == "week":
        ticks = [{"at": aware(datetime.combine(first + timedelta(days=index),
            time.min), prop.time_zone).isoformat(),
            "label": str(first + timedelta(days=index))}
            for index in range(days)]
    else:
        ticks = [{"at": (start.astimezone(UTC) + timedelta(hours=2 * index))
            .astimezone(start.tzinfo).isoformat(),
            "label": (start.astimezone(UTC) + timedelta(hours=2 * index))
            .astimezone(start.tzinfo).strftime("%H:%M")}
            for index in range(12)]
    return {"property": prop.name, "from_date": from_date, "view": view,
            "time_zone": prop.time_zone, "window_start": start.isoformat(),
            "window_end": end.isoformat(), "ticks": ticks,
            "rooms": project("HS Room", prop,
                fields=["name", "room_number", "category", "active",
                        "cleaning_status"]),
            "allocations": calendar(prop.name, start.isoformat(), end.isoformat()),
            "read_only": True}


@frappe.whitelist()
def room_balances(property_name):
    prop=require(property_name)
    if not may("stay") and not may("finance"):
        frappe.throw(frappe._("No tiene acceso a saldos"),frappe.PermissionError)
    result={}
    for stay in project("HS Stay",prop,fields=["name"],filters={"status":"Active"}):
        total=0
        shared=False
        stay_doc=frappe.get_doc("HS Stay",stay.name)
        for folio in accounting.folios_for_stay(stay_doc):
            total+=float(accounting.folio_balance(folio.name)["outstanding"])
            shared=shared or not bool(folio.stay)
        result[stay.name]=dict(amount=total,shared=shared)
    return result


@frappe.whitelist()
def room_history(property_name,room,starts_at,ends_at,view='activity',offset=0,page_length=25):
    from hospitality_suite.room_history import history
    return history(property_name,room,starts_at,ends_at,view,offset,page_length)


@frappe.whitelist()
def room_board_snapshot(property_name):
    from hospitality_suite.room_view import board_snapshot
    return board_snapshot(property_name)


@frappe.whitelist()
def room_snapshot(property_name,room):
    from hospitality_suite.room_view import room_snapshot as snapshot
    return snapshot(property_name,room)


@frappe.whitelist()
def room_schedule(property_name,room,starts_at,ends_at):
    from hospitality_suite.room_view import room_schedule as schedule
    return schedule(property_name,room,starts_at,ends_at)


@frappe.whitelist()
def room_insights(property_name,days=30):
    from hospitality_suite.room_view import room_insights as insights
    return insights(property_name,days)


@frappe.whitelist()
def inventory_status(property_name,warehouse_name=None):
    prop=require(property_name)
    if not any(may(a) for a in ("service","report","inventory","clean","maintain")):
        frappe.throw(frappe._("No tiene permiso para consultar existencias"),frappe.PermissionError)
    if not prop.warehouse and not warehouse_name:
        return dict(warehouse=None,items=[])
    target=procurement.warehouse(prop,warehouse_name)
    bins=frappe.get_all("Bin",filters={"warehouse":target},fields=["item_code","actual_qty","projected_qty"])
    minimums={r.parent:r for r in frappe.get_all("Item Reorder",filters={"warehouse":target},fields=["parent","warehouse_reorder_level","warehouse_reorder_qty"])}
    existing={r.item_code for r in bins}
    bins += [frappe._dict(item_code=item,actual_qty=0,projected_qty=0) for item in minimums if item not in existing]
    purposes={r.item:r.purpose for r in frappe.get_all("HS Stock Policy",filters={"property":prop.name,"warehouse":target},fields=["item","purpose"])}
    existing={r.item_code for r in bins}
    bins += [frappe._dict(item_code=item,actual_qty=0,projected_qty=0) for item in purposes if item not in existing]
    for row in bins:
        row["item_name"]=frappe.db.get_value("Item",row.item_code,"item_name")
        setting=minimums.get(row.item_code)
        row["minimum"]=setting.warehouse_reorder_level if setting else None
        row["reorder_quantity"]=setting.warehouse_reorder_qty if setting else None
        row["purpose"]=purposes.get(row.item_code) or ("Asset" if frappe.db.get_value("Item",row.item_code,"is_fixed_asset") else "Merchandise")
        row["stock_managed"]=row["purpose"]!="Asset"
        if not row["stock_managed"]:
            row["actual_qty"],row["projected_qty"],row["minimum"]=None,None,None
        row["needs_restock"]=bool(setting and row.actual_qty<setting.warehouse_reorder_level)
    return dict(warehouse=target,items=bins)
