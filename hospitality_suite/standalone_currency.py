"""Currencies enabled per property and immutable dated FX quotations."""

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from hospitality_suite.security import require
from hospitality_suite.service import audit, insert
from hospitality_suite.standalone_accounting import require_pms


def enabled_currencies(prop):
    return {prop.currency} | {row.currency for row in prop.accepted_currencies if row.currency}


def enabled(prop, currency):
    return bool(currency and currency in enabled_currencies(prop))


def _currency_active(name):
    return bool(frappe.db.get_value("Currency", name, "enabled"))


def configure(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    currencies = data.get("currencies") if isinstance(data, dict) else None
    if not isinstance(currencies, list) or not 1 <= len(currencies) <= 12 or any(
        not isinstance(code, str) or not code.strip() for code in currencies):
        frappe.throw(_("Seleccione entre una y doce monedas habilitadas"))
    currencies = [code.strip().upper() for code in currencies]
    if len(set(currencies)) != len(currencies) or prop.currency not in currencies or any(
        code != prop.currency and not _currency_active(code) for code in currencies):
        frappe.throw(_("Incluya la moneda base y seleccione únicamente monedas activas"))
    prop.set("accepted_currencies", [dict(currency=code) for code in currencies if code != prop.currency])
    prop.save()
    audit(prop, "pms_currencies_configured", prop, details={"currencies": currencies})
    return {"currencies": currencies, "base_currency": prop.currency}


def record_rate(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) - {"from_currency", "rate", "effective_at", "source"}:
        frappe.throw(_("Revise los datos del tipo de cambio"))
    currency = data.get("from_currency")
    if not enabled(prop, currency) or currency == prop.currency:
        frappe.throw(_("Seleccione una moneda adicional habilitada"))
    effective = get_datetime(data.get("effective_at") or now_datetime())
    source = data.get("source")
    if not isinstance(source, str) or not source.strip():
        frappe.throw(_("Indique la fuente del tipo de cambio"))
    doc = insert("HS Exchange Rate", prop, organization=prop.organization,
                 from_currency=currency, to_currency=prop.currency,
                 rate=data.get("rate"), effective_at=effective, source=source.strip())
    audit(prop, "pms_exchange_rate_recorded", doc, details={"rate": doc.rate,
                                                        "from_currency": currency, "to_currency": prop.currency})
    return {"rate": doc.name, "from_currency": currency, "to_currency": prop.currency,
            "value": str(doc.rate), "effective_at": str(doc.effective_at)}


def settings(property_name):
    prop = require(property_name, "chart")
    require_pms(prop)
    return {"base_currency": prop.currency, "accepted_currencies": sorted(enabled_currencies(prop)),
            "available_currencies": sorted({prop.currency} | set(frappe.get_all(
                "Currency", filters={"enabled": 1}, pluck="name", order_by="name asc"))),
            "rates": frappe.get_all("HS Exchange Rate", filters={"property": prop.name},
                fields=["name", "from_currency", "to_currency", "rate", "effective_at", "source"],
                order_by="effective_at desc", limit_page_length=100)}


def latest_rate(prop, currency, at=None):
    require_pms(prop)
    if not enabled(prop, currency):
        frappe.throw(_("La moneda no está habilitada en este establecimiento"))
    if currency == prop.currency:
        return Decimal(1), None
    rate = frappe.db.sql("SELECT name, rate FROM `tabHS Exchange Rate` "
                         "WHERE property=%s AND from_currency=%s AND to_currency=%s "
                         "AND effective_at<=%s ORDER BY effective_at DESC LIMIT 1",
                         (prop.name, currency, prop.currency, get_datetime(at or now_datetime())), as_dict=True)
    if not rate:
        frappe.throw(_("Configure un tipo de cambio vigente para esta moneda"))
    return Decimal(str(rate[0].rate)), rate[0].name
