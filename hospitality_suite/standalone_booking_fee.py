"""Cancellation and no-show penalties posted in the PMS book."""

from decimal import Decimal
from hashlib import sha256

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.accounting import cancellation_fee
from hospitality_suite.item_configuration import _pms_service
from hospitality_suite.security import require
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import account, require_pms
from hospitality_suite.standalone_receivables import _create
from hospitality_suite.standalone_tax import tax_for_amount


def settings(property_name):
    prop = require(property_name, "setup")
    require_pms(prop)
    return {"modified": str(prop.modified),
            "cancellation_fee_mode": prop.cancellation_fee_mode or "None",
            "cancellation_fee_value": str(prop.cancellation_fee_value or 0),
            "no_show_fee_mode": prop.no_show_fee_mode or "None",
            "no_show_fee_value": str(prop.no_show_fee_value or 0),
            "receivable_account": prop.receivable_account,
            "penalty_item": prop.penalty_item,
            "receivable_accounts": frappe.get_all("HS Account", filters={
                "property": prop.name, "organization": prop.organization,
                "root_type": "Asset", "account_type": "Receivable",
                "is_group": 0, "active": 1, "account_currency": prop.currency},
                fields=["name", "account_code", "account_name"],
                order_by="account_code asc")}


def quote(prop, booking, status):
    require_pms(prop)
    if status not in ("Cancelled", "No Show"):
        frappe.throw(_("Seleccione cancelación o no presentación"))
    if booking.property != prop.name or booking.currency != prop.currency:
        frappe.throw(_("La reserva debe pertenecer al establecimiento y usar su moneda base"))
    if booking.status not in ("Hold", "Confirmed"):
        frappe.throw(_("La reserva no admite esta transición"))
    if booking.status == "Hold" and get_datetime(booking.hold_until) <= now_datetime():
        frappe.throw(_("La retención ya venció; cree una nueva reserva"))
    if status == "No Show" and get_datetime(booking.starts_at) > now_datetime():
        frappe.throw(_("La llegada todavía no está vencida"))
    fee = cancellation_fee(prop, booking, status)
    amount = Decimal(fee["amount"])
    details = {"product": None, "income_account": None, "receivable_account": None,
               "tax_profile": None, "net_amount": fee["amount"],
               "tax_amount": "0.00", "total_amount": fee["amount"]}
    if amount:
        if not prop.penalty_item or not prop.receivable_account:
            frappe.throw(_("Configure el producto de penalización y la cuenta por cobrar PMS"))
        product = _pms_service(prop, prop.penalty_item, _("Penalización"))
        profile = frappe.db.get_value("HS Product", product.name,
            ["tax_profile", "modified"], as_dict=True)
        if not profile.tax_profile:
            frappe.throw(_("Clasifique el impuesto del producto de penalización antes de contabilizar"))
        receivable = account(prop, prop.receivable_account)
        if (receivable.root_type != "Asset" or receivable.account_type != "Receivable" or
                receivable.is_cash or receivable.is_bank or
                receivable.account_currency != prop.currency):
            frappe.throw(_("Seleccione una cuenta por cobrar PMS en moneda base"))
        tax = tax_for_amount(prop, profile.tax_profile, amount)
        details = {"product": product.name, "income_account": product.income_account,
                   "receivable_account": receivable.name, "tax_profile": tax["profile"],
                   "net_amount": tax["net"], "tax_amount": tax["tax"],
                   "total_amount": tax["total"]}
        signature_version = {"product_modified": str(profile.modified),
                             "tax_profile_modified": tax["profile_modified"]}
    else:
        signature_version = {}
    signature = {"property": prop.name, "booking": booking.name,
                 "booking_modified": str(booking.modified), "status": status,
                 "mode": fee["mode"], "amount": fee["amount"],
                 **details, **signature_version}
    return {key: value for key, value in fee.items() if key != "acceptance"} | details | {
        "acceptance": sha256(canonical(signature).encode()).hexdigest()}


def post_fee(prop, booking, fee, reason):
    if not Decimal(fee["amount"]):
        return None
    receivable = account(prop, fee["receivable_account"])
    income = account(prop, fee["income_account"])
    description = (_("Penalización por no presentación: ") if fee["status"] == "No Show"
                   else _("Penalización por cancelación: ")) + booking.name
    description += " · " + reason.strip()
    return _create(prop, party=booking.customer,
        reference=("Penalización " + booking.name)[:140],
        description=description[:500], value=Decimal(fee["amount"]),
        receivable=receivable, income=income, booking=booking.name,
        tax_profile=fee["tax_profile"])
