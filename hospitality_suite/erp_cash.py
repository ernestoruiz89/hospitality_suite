"""Scoped ERPNext cash desk projections for the React operating screen."""

import frappe

from hospitality_suite import cashier, standalone_accounting, standalone_currency
from hospitality_suite.pricing import decimal, money
from hospitality_suite.reconciliation import unmatched_cash
from hospitality_suite.security import require


def snapshot(property_name, shift_name="", offset=0, page_length=50):
    prop = require(property_name, "finance")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Use la Caja PMS de este sitio"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la página de movimientos de Caja"))
    if offset < 0 or offset > 1000 or page_length < 1 or page_length > 100:
        frappe.throw(frappe._("Revise la página de movimientos de Caja"))
    if not isinstance(shift_name, str) or len(shift_name) > 140:
        frappe.throw(frappe._("Seleccione un turno válido"))

    scope = {"property": prop.name, "company": prop.company}
    active = frappe.get_all("HS Shift", filters={**scope,
        "status": ["in", ["Open", "Review"]]},
        fields=["name", "cashier", "currency", "status", "opened_at",
                "closed_at", "modified"], order_by="opened_at desc")
    recent = frappe.get_all("HS Shift", filters={**scope, "status": "Closed"},
        fields=["name", "cashier", "currency", "status", "opened_at",
                "closed_at", "modified"], order_by="closed_at desc",
        limit_page_length=20)
    shifts = active + recent
    selected = None
    if shift_name:
        if not frappe.db.exists("HS Shift", {**scope, "name": shift_name}):
            frappe.throw(frappe._("El turno no pertenece al establecimiento"),
                         frappe.PermissionError)
        selected = frappe.get_doc("HS Shift", shift_name)
    elif shifts:
        own_open = next((row for row in active if row.cashier == frappe.session.user
                         and row.status == "Open"), None)
        selected = frappe.get_doc("HS Shift", (own_open or shifts[0]).name)

    detail = None
    movements = []
    unmatched = []
    if selected:
        frozen = frappe.parse_json(selected.denominations or "{}")
        expected = (frozen.get("expected") or cashier.expected(selected)
                    if selected.status == "Closed" else cashier.expected(selected))
        detail = dict(name=selected.name, cashier=selected.cashier,
            currency=selected.currency, status=selected.status,
            opened_at=selected.opened_at, closed_at=selected.closed_at,
            modified=str(selected.modified), opening_amount=str(selected.opening_amount),
            expected=expected, counts=frozen.get("counts") or {},
            differences=frozen.get("differences") or {},
            reason=selected.reason, approved_by=selected.approved_by)
        unmatched = unmatched_cash(prop, selected.name)
        query_limit = offset + page_length + 1
        for row in frappe.get_all("HS Payment", filters={**scope,
                "shift": selected.name},
                fields=["name", "creation", "business_date", "kind", "amount",
                        "currency", "method", "reference", "status"],
                order_by="creation desc", limit_page_length=query_limit):
            movements.append(dict(source="HS Payment", **row))
        for row in frappe.get_all("HS Treasury Movement", filters={**scope,
                "shift": selected.name},
                fields=["name", "creation", "business_date", "kind", "amount",
                        "currency", "method", "status"],
                order_by="creation desc", limit_page_length=query_limit):
            movements.append(dict(source="HS Treasury Movement", **row))
        from hospitality_suite.native_pos import movements as pos_movements
        for row in pos_movements(prop.name, selected.name):
            movements.append(dict(source="ERPNext POS", name=row["name"],
                creation=row["creation"], business_date=row["posting_date"],
                kind="POS", amount=str(row["amount"]), currency=row["currency"],
                method=row["account"], status="Posted" if row["mapped"] else "Unmatched"))
        movements.sort(key=lambda row: (str(row["creation"]), row["name"]),
                       reverse=True)

    methods = frappe.get_all("HS Payment Method", filters={**scope, "is_cash": 1},
        fields=["name", "mode_of_payment", "currency", "account"],
        order_by="mode_of_payment asc")
    categories = frappe.get_all("HS Expense Category", filters={**scope, "active": 1},
        fields=["name", "label", "currency", "account", "max_amount"],
        order_by="label asc")
    return dict(currencies=sorted(standalone_currency.enabled_currencies(prop)),
        methods=methods, categories=categories, user=frappe.session.user,
        cash_transfer_configured=bool(prop.cash_transfer_account),
        shifts=shifts, selected=detail, unmatched=unmatched,
        movements=movements[offset:offset + page_length], offset=offset,
        has_more=len(movements) > offset + page_length)


def settings(property_name):
    prop = require(property_name, "setup")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Use la configuración de Caja PMS"))
    base_currency = frappe.db.get_value("Company", prop.company,
                                        "default_currency")
    accounts = frappe.get_all("Account", filters={
        "company": prop.company, "is_group": 0, "root_type": "Asset",
        "account_currency": base_currency, "disabled": 0},
        fields=["name", "account_number", "account_name", "account_type"],
        order_by="account_number asc, account_name asc")
    expense_accounts = frappe.get_all("Account", filters={
        "company": prop.company, "is_group": 0, "root_type": "Expense",
        "account_currency": base_currency, "disabled": 0},
        fields=["name", "account_number", "account_name"],
        order_by="account_number asc, account_name asc")
    categories = frappe.get_all("HS Expense Category", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "label", "account", "max_amount", "active", "modified"],
        order_by="label asc")
    return dict(account=prop.cash_transfer_account or "",
        base_currency=base_currency, property_modified=str(prop.modified),
        accounts=accounts, expense_accounts=expense_accounts,
        categories=categories)


def settlement_sources(property_name, search="", offset=0, page_length=20):
    """Posted noncash receipts and refunds with an unsettled clearing balance."""
    prop = require(property_name, "finance")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Use la Caja PMS de este sitio"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(frappe._("Revise la página de liquidaciones"))
    if offset < 0 or offset > 5000 or page_length < 1 or page_length > 100:
        frappe.throw(frappe._("Revise la página de liquidaciones"))
    if not isinstance(search, str) or len(search) > 140:
        frappe.throw(frappe._("Revise la búsqueda de cobros"))
    search = search.strip()
    rows = frappe.db.sql("""
        SELECT p.name, p.kind, p.creation, p.business_date, p.amount, p.currency,
               p.reference, p.payment_entry, p.journal_entry,
               m.mode_of_payment, m.name AS method,
               COALESCE(s.settled, 0) AS settled
        FROM `tabHS Payment` p
        INNER JOIN `tabHS Payment Method` m ON m.name = p.method
          AND m.property = p.property AND m.company = p.company AND m.is_cash = 0
        LEFT JOIN (
            SELECT source_payment, SUM(amount) AS settled
            FROM `tabHS Payment`
            WHERE property = %(property)s AND company = %(company)s
              AND kind = 'Settlement' AND status = 'Posted'
            GROUP BY source_payment
        ) s ON s.source_payment = p.name
        WHERE p.property = %(property)s AND p.company = %(company)s
          AND p.status = 'Posted'
          AND p.kind IN ('Payment', 'Advance', 'Guarantee', 'Refund', 'Guarantee Refund')
          AND CASE WHEN JSON_VALID(p.fee_snapshot) THEN
            COALESCE(JSON_UNQUOTE(JSON_EXTRACT(p.fee_snapshot, '$.settlement_account')), '')
            ELSE '' END != ''
          AND p.amount > COALESCE(s.settled, 0)
          AND (%(search)s = '' OR LOCATE(%(search)s, p.name) > 0
            OR LOCATE(%(search)s, COALESCE(p.reference, '')) > 0
            OR LOCATE(%(search)s, COALESCE(p.payment_entry, '')) > 0
            OR LOCATE(%(search)s, COALESCE(p.journal_entry, '')) > 0)
        ORDER BY p.creation DESC, p.name DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """, dict(property=prop.name, company=prop.company, search=search,
              limit=page_length + 1, offset=offset), as_dict=True)
    candidates = []
    for row in rows[:page_length]:
        candidates.append(dict(name=row.name, kind=row.kind,
            creation=row.creation, business_date=row.business_date,
            currency=row.currency, amount=str(money(row.amount, currency=row.currency)),
            settled=str(money(row.settled, currency=row.currency)),
            available=str(money(decimal(row.amount) - decimal(row.settled),
                                currency=row.currency)),
            direction="Pay" if row.kind in ("Refund", "Guarantee Refund") else "Receive",
            reference=row.reference, voucher=row.payment_entry or row.journal_entry,
            method=row.method, method_label=row.mode_of_payment))
    return dict(sources=candidates, offset=offset,
                has_more=len(rows) > page_length)


def method_settings(property_name):
    prop = require(property_name, "setup")
    if standalone_accounting.provider() != "erpnext":
        frappe.throw(frappe._("Use la configuración de medios PMS"))
    base_currency = frappe.db.get_value("Company", prop.company, "default_currency")
    methods = frappe.get_all("HS Payment Method", filters={
        "property": prop.name, "company": prop.company},
        fields=["name", "mode_of_payment", "account", "currency", "is_cash",
                "reference_required", "fee_percent", "fee_fixed", "fee_account",
                "refund_fee_percent", "refund_fee_fixed", "withholding_percent",
                "withholding_account", "settlement_account", "modified"],
        order_by="mode_of_payment asc, currency asc, name asc", limit_page_length=500)
    for method in methods:
        method["core_locked"] = bool(frappe.db.exists("HS Payment", {
            "method": method.name}))
    accounts = frappe.get_all("Account", filters={"company": prop.company,
        "is_group": 0, "disabled": 0, "root_type": ["in", ["Asset", "Expense"]]},
        fields=["name", "account_number", "account_name", "root_type",
                "account_type", "account_currency"],
        order_by="account_number asc, account_name asc", limit_page_length=2000)
    modes = frappe.get_all("Mode of Payment", fields=["name", "type"],
                           order_by="name asc", limit_page_length=500)
    return dict(methods=methods, accounts=accounts, modes=modes,
                currencies=sorted(standalone_currency.enabled_currencies(prop)),
                base_currency=base_currency)
