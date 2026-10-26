"""Reviewed, property-scoped tax profiles for PMS sale postings.

Rates are configuration, never inferred from an organization's tax regime.
The resulting amounts are frozen on each receivable and may be referenced by
a numbered document without posting the sale twice.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe import _

from hospitality_suite.security import require
from hospitality_suite.service import audit, insert, locked_doc
from hospitality_suite.standalone_accounting import account, require_pms


CENT = Decimal("0.01")


def _money(value):
    return str(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


def _rate(value):
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        frappe.throw(_("Indique una tasa tributaria válida"))
    if not rate.is_finite() or rate < 0 or rate > 100 or rate.as_tuple().exponent < -6:
        frappe.throw(_("La tasa debe estar entre 0 y 100 con hasta seis decimales"))
    return rate


def setup(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) - {"label", "treatment", "rate",
            "included_in_price", "liability_account"}:
        frappe.throw(_("Revise el perfil tributario"))
    label = data.get("label")
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 140:
        frappe.throw(_("Indique el nombre del perfil tributario"))
    treatment = data.get("treatment")
    if treatment not in ("Taxable", "Exempt", "Zero Rate", "Outside Scope"):
        frappe.throw(_("Seleccione el tratamiento tributario"))
    rate = _rate(data.get("rate", 0))
    if (treatment == "Taxable") != (rate > 0):
        frappe.throw(_("Un perfil gravado requiere tasa positiva; los demás requieren tasa cero"))
    liability = None
    if rate:
        liability = account(prop, data.get("liability_account"))
        if liability.root_type != "Liability" or liability.account_currency != prop.currency:
            frappe.throw(_("El impuesto requiere una cuenta de pasivo en moneda base"))
    elif data.get("liability_account"):
        frappe.throw(_("Un perfil sin impuesto no usa cuenta tributaria"))
    doc = insert("HS PMS Tax Profile", prop, organization=prop.organization,
        label=label.strip(), treatment=treatment, rate=str(rate),
        included_in_price=int(bool(data.get("included_in_price"))),
        liability_account=liability.name if liability else None, active=1)
    audit(prop, "pms_tax_profile_created", doc, details={"treatment": treatment,
        "rate": str(rate)})
    return {"profile": doc.name}


def tax_for_amount(prop, profile_name, amount):
    """Return one immutable sale split. ``amount`` is the configured price."""
    price = Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP)
    if price <= 0:
        frappe.throw(_("El cargo tributable debe ser positivo"))
    if not profile_name:
        return {"profile": None, "treatment": "Unclassified", "rate": "0",
            "included_in_price": False, "liability_account": None,
            "price": _money(price), "net": _money(price), "tax": "0.00", "total": _money(price)}
    doc = locked_doc("HS PMS Tax Profile", profile_name)
    if doc.property != prop.name or doc.organization != prop.organization or not doc.active:
        frappe.throw(_("Seleccione un perfil tributario activo del establecimiento"))
    rate = _rate(doc.rate)
    if doc.treatment == "Taxable":
        if rate <= 0:
            frappe.throw(_("El perfil gravado requiere una tasa positiva"))
        liability = account(prop, doc.liability_account)
        if liability.root_type != "Liability" or liability.account_currency != prop.currency:
            frappe.throw(_("La cuenta del impuesto ya no es válida"))
    elif doc.treatment in ("Exempt", "Zero Rate", "Outside Scope") and rate == 0:
        liability = None
    else:
        frappe.throw(_("El perfil tributario ya no es válido"))
    if doc.included_in_price and rate:
        total = price
        net = (total / (Decimal(1) + rate / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
        tax = total - net
    else:
        net = price
        tax = (net * rate / 100).quantize(CENT, rounding=ROUND_HALF_UP)
        total = net + tax
    return {"profile": doc.name, "treatment": doc.treatment, "rate": str(rate),
        "included_in_price": bool(doc.included_in_price),
        "liability_account": liability.name if liability else None,
        "price": _money(price), "net": _money(net), "tax": _money(tax),
        "total": _money(total), "profile_modified": str(doc.modified)}


def profiles(property_name):
    prop = require(property_name, "finance")
    require_pms(prop)
    return frappe.get_all("HS PMS Tax Profile", filters={"property": prop.name},
        fields=["name", "label", "treatment", "rate", "included_in_price",
                "liability_account", "active"], order_by="label asc")
