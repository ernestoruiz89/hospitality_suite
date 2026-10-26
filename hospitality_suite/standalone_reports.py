"""Scoped accounting and treasury reports sourced from the PMS ledger."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO
import csv
import re

import frappe
from frappe import _
from frappe.utils import getdate

from hospitality_suite.security import require
from hospitality_suite.standalone_accounting import account, require_pms, trial_balance


REPORTS = {
    "trial_balance": "Balance de comprobación",
    "general_ledger": "Mayor general",
    "receivables": "Cartera por vencimiento",
    "funds": "Movimientos de fondos",
    "sales": "Producción neta",
}

COLUMNS = {
    "trial_balance": [("account_code", "Código"), ("account_name", "Cuenta"),
        ("root_type", "Naturaleza"), ("account_currency", "Moneda de cuenta"),
        ("debit", "Débitos base"), ("credit", "Créditos base"),
        ("balance", "Saldo base"), ("account_balance", "Saldo moneda de cuenta")],
    "general_ledger": [("posting_date", "Fecha contable"), ("journal", "Asiento"),
        ("account_code", "Código"), ("account_name", "Cuenta"),
        ("party_name", "Cliente"), ("debit", "Débito base"),
        ("credit", "Crédito base"), ("running_base", "Saldo base"),
        ("account_currency", "Moneda de cuenta"), ("account_debit", "Débito original"),
        ("account_credit", "Crédito original"), ("running_account", "Saldo original"),
        ("source_doctype", "Origen"), ("source_name", "Referencia")],
    "receivables": [("party_name", "Cliente"), ("reference", "Referencia"),
        ("business_date", "Fecha del cargo"), ("due_date", "Vence"),
        ("days_overdue", "Días vencidos"), ("amount", "Cargo"),
        ("outstanding", "Pendiente original"), ("currency", "Moneda"),
        ("base_outstanding", "Pendiente base"), ("folio", "Folio")],
    "funds": [("business_date", "Fecha operativa"), ("source_type", "Origen"),
        ("kind", "Concepto"), ("channel", "Canal"), ("currency", "Moneda"),
        ("signed_amount", "Movimiento original"), ("signed_base", "Movimiento base"),
        ("cash_account", "Cuenta de fondos"), ("counter_account", "Contracuenta"),
        ("concept", "Concepto configurado"), ("reference", "Referencia"),
        ("journal", "Asiento")],
    "sales": [("business_date", "Fecha operativa"), ("source_type", "Movimiento"),
        ("reference", "Referencia"), ("party_name", "Cliente"), ("folio", "Folio"),
        ("income_account", "Cuenta contable"), ("net_amount", "Base"),
        ("tax_amount", "Impuesto"), ("total_amount", "Total"),
        ("currency", "Moneda"), ("journal", "Asiento")],
}


def _money(value):
    return format(Decimal(str(value or 0)).quantize(Decimal("0.01")), "f")


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        frappe.throw(_("Indique {0} en formato AAAA-MM-DD").format(label))
    try:
        result = getdate(value)
    except (TypeError, ValueError):
        frappe.throw(_("La fecha {0} no es válida").format(label))
    if result.isoformat() != value:
        frappe.throw(_("La fecha {0} no es válida").format(label))
    return result


def _arguments(prop, report_name, filters, offset, page_length):
    require_pms(prop)
    if report_name not in REPORTS or not isinstance(filters, dict) or set(filters) - {
            "from_date", "to_date", "account", "party"}:
        frappe.throw(_("Seleccione un reporte PMS y filtros válidos"))
    try:
        offset, page_length = int(offset), int(page_length)
    except (TypeError, ValueError):
        frappe.throw(_("La paginación del reporte no es válida"))
    if offset < 0 or not 1 <= page_length <= 200:
        frappe.throw(_("Consulte entre 1 y 200 filas por página"))
    end = _date(filters.get("to_date") or str(prop.business_date), "final")
    start = (end if report_name in ("trial_balance", "receivables") else
             _date(filters.get("from_date") or end.isoformat(), "inicial"))
    if end < start or (end - start).days > 366:
        frappe.throw(_("Seleccione un período de hasta 366 días"))
    selected_account = filters.get("account") or None
    if selected_account:
        # Historical journals remain reportable after an account is deactivated.
        account(prop, selected_account, allow_inactive=True)
    selected_party = filters.get("party") or None
    if selected_party and frappe.db.get_value("HS Party", selected_party, "property") != prop.name:
        frappe.throw(_("El cliente pertenece a otro establecimiento"), frappe.PermissionError)
    if report_name in ("trial_balance", "funds") and selected_party:
        frappe.throw(_("Este reporte no admite filtro de cliente"))
    if report_name in ("receivables", "funds") and selected_account:
        frappe.throw(_("Este reporte no admite filtro de cuenta"))
    return start, end, selected_account, selected_party, offset, page_length


def _ledger(prop, start, end, selected_account, selected_party, offset, page_length):
    where = "j.property=%s AND j.status='Posted' AND j.posting_date<=%s"
    params = [prop.name, end]
    if selected_account:
        where += " AND l.account=%s"
        params.append(selected_account)
    if selected_party:
        where += " AND l.party=%s"
        params.append(selected_party)
    cte = (
        "WITH entries AS (SELECT j.posting_date,j.business_date,j.name AS journal,"
        "j.source_doctype,j.source_name,j.purpose,j.reversal_of,"
        "l.name AS line,l.idx,l.account,l.party,l.account_currency,l.exchange_rate,"
        "l.debit,l.credit,l.debit_in_account_currency AS account_debit,"
        "l.credit_in_account_currency AS account_credit,a.account_code,a.account_name,"
        "p.party_name FROM `tabHS Journal Line` l "
        "JOIN `tabHS Journal` j ON j.name=l.parent "
        "JOIN `tabHS Account` a ON a.name=l.account "
        "LEFT JOIN `tabHS Party` p ON p.name=l.party WHERE " + where + "),"
        "running AS (SELECT entries.* ,"
        "SUM(debit-credit) OVER(PARTITION BY account ORDER BY posting_date,journal,idx,line "
        "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_base,"
        "SUM(account_debit-account_credit) OVER(PARTITION BY account ORDER BY posting_date,journal,idx,line "
        "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_account "
        "FROM entries) ")
    rows = frappe.db.sql(cte + "SELECT * FROM running WHERE posting_date>=%s "
        "ORDER BY posting_date,journal,idx,line LIMIT %s OFFSET %s",
        tuple(params + [start, page_length, offset]), as_dict=True)
    totals = frappe.db.sql(
        "SELECT COUNT(*) AS row_count,COALESCE(SUM(l.debit),0) AS debit,"
        "COALESCE(SUM(l.credit),0) AS credit FROM `tabHS Journal Line` l "
        "JOIN `tabHS Journal` j ON j.name=l.parent WHERE " + where +
        " AND j.posting_date>=%s", tuple(params + [start]), as_dict=True)[0]
    return {"rows": [{**row, "debit": _money(row.debit), "credit": _money(row.credit),
        "account_debit": _money(row.account_debit), "account_credit": _money(row.account_credit),
        "running_base": _money(row.running_base), "running_account": _money(row.running_account),
        "exchange_rate": str(row.exchange_rate)} for row in rows],
        "total_rows": int(totals.row_count),
        "totals": {"currency": prop.currency, "debit": _money(totals.debit),
                   "credit": _money(totals.credit)}}


def _receivables(prop, end, selected_party, offset, page_length):
    party_filter = " AND r.party=%s" if selected_party else ""
    cte = (
        "WITH allocations AS (SELECT receivable,"
        "SUM(CASE WHEN kind IN ('Direct Reversed','Advance Reversed','Guarantee Reversed',"
        "'Opening Credit Reversed','Opening Guarantee Reversed') "
        "THEN -amount ELSE amount END) AS base_amount,"
        "SUM(CASE WHEN kind IN ('Direct Reversed','Advance Reversed','Guarantee Reversed',"
        "'Opening Credit Reversed','Opening Guarantee Reversed') "
        "THEN -COALESCE(NULLIF(settled_amount,0),amount) "
        "ELSE COALESCE(NULLIF(settled_amount,0),amount) END) AS original_amount "
        "FROM `tabHS PMS Allocation` "
        "WHERE property=%s AND business_date<=%s GROUP BY receivable),"
        "credits AS (SELECT l.receivable,SUM(l.total_amount) AS amount "
        "FROM `tabHS PMS Fiscal Line` l JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
        "WHERE d.property=%s AND d.business_date<=%s AND d.document_type='Credit Note' "
        "AND d.status='Posted' GROUP BY l.receivable),"
        "positions AS (SELECT r.name,r.party,p.party_name,r.reference,r.description,"
        "r.business_date,r.due_date,r.folio,r.currency,r.amount,r.receivable_account,"
        "r.amount-COALESCE(a.original_amount,0)-COALESCE(c.amount,0) AS outstanding,"
        "COALESCE(NULLIF(r.base_amount,0),r.amount)-COALESCE(a.base_amount,0)-"
        "COALESCE(c.amount,0) AS base_outstanding "
        "FROM `tabHS PMS Receivable` r JOIN `tabHS Party` p ON p.name=r.party "
        "LEFT JOIN allocations a ON a.receivable=r.name "
        "LEFT JOIN credits c ON c.receivable=r.name "
        "LEFT JOIN `tabHS Journal` rev ON rev.name=r.reversal_journal "
        "WHERE r.property=%s AND r.business_date<=%s "
        "AND (r.status='Posted' OR (r.status='Cancelled' AND rev.business_date>%s))"
        + party_filter + ") ")
    # The repeated property/date pair in params also anchors a historical
    # cancelled receivable; no current-status shortcut may erase old balances.
    query_params = [prop.name, end, prop.name, end, prop.name, end, end]
    if selected_party:
        query_params.append(selected_party)
    rows = frappe.db.sql(cte + "SELECT * FROM positions WHERE outstanding>0 "
        "ORDER BY due_date,name LIMIT %s OFFSET %s",
        tuple(query_params + [page_length, offset]), as_dict=True)
    summary = frappe.db.sql(cte + "SELECT COUNT(*) AS row_count,"
        "COALESCE(SUM(base_outstanding),0) AS outstanding,"
        "COALESCE(SUM(CASE WHEN due_date>=%s THEN base_outstanding ELSE 0 END),0) AS current_amount,"
        "COALESCE(SUM(CASE WHEN due_date<%s AND due_date>=%s THEN base_outstanding ELSE 0 END),0) AS d1_30,"
        "COALESCE(SUM(CASE WHEN due_date<%s AND due_date>=%s THEN base_outstanding ELSE 0 END),0) AS d31_60,"
        "COALESCE(SUM(CASE WHEN due_date<%s AND due_date>=%s THEN base_outstanding ELSE 0 END),0) AS d61_90,"
        "COALESCE(SUM(CASE WHEN due_date<%s THEN base_outstanding ELSE 0 END),0) AS d90_plus "
        "FROM positions WHERE outstanding>0",
        tuple(query_params + [end, end, end - timedelta(days=30),
            end - timedelta(days=30), end - timedelta(days=60),
            end - timedelta(days=60), end - timedelta(days=90),
            end - timedelta(days=90)]), as_dict=True)[0]
    return {"rows": [{**row, "amount": _money(row.amount),
        "outstanding": _money(row.outstanding),
        "base_outstanding": _money(row.base_outstanding),
        "days_overdue": max(0, (end - getdate(row.due_date)).days)} for row in rows],
        "total_rows": int(summary.row_count),
        "totals": {"currency": prop.currency,
            **{field: _money(summary[field]) for field in
                ("outstanding", "current_amount", "d1_30", "d31_60", "d61_90", "d90_plus")}}}


def _funds(prop, start, end, offset, page_length):
    union = (
        "SELECT 'Payment' AS source_type,p.name,p.business_date,p.kind,p.currency,"
        "p.amount,p.base_amount,p.exchange_rate,p.method,p.shift,m.account AS cash_account,"
        "p.pms_counter_account AS counter_account,p.pms_concept AS concept,p.reference,"
        "p.pms_journal AS journal,IF(m.is_cash,'Cash','Bank') AS channel,"
        "CASE WHEN p.kind IN ('Expense','Supplier Payment','Refund','Guarantee Refund') "
        "THEN -1 ELSE 1 END AS sign FROM `tabHS Payment` p "
        "JOIN `tabHS Payment Method` m ON m.name=p.method "
        "WHERE p.property=%s AND p.business_date BETWEEN %s AND %s AND p.status='Posted' "
        "AND p.pms_journal IS NOT NULL "
        "UNION ALL SELECT 'Treasury',t.name,t.business_date,t.kind,t.currency,"
        "t.amount,t.base_amount,t.exchange_rate,t.method,t.shift,t.cash_account,"
        "t.counter_account,t.concept,t.reference,t.pms_journal,"
        "IF(t.shift IS NULL,'Bank','Cash'),"
        "CASE WHEN t.kind IN ('Initial Fund','Replenishment','Loan Repayment',"
        "'Capital Withdrawal') THEN -1 ELSE 1 END "
        "FROM `tabHS Treasury Movement` t WHERE t.property=%s "
        "AND t.business_date BETWEEN %s AND %s AND t.status='Posted' AND t.pms_journal IS NOT NULL "
        "UNION ALL SELECT 'Petty Cash Expense',e.name,e.business_date,'Petty Expense',"
        "e.currency,e.amount,e.amount,1,NULL,NULL,e.petty_account,e.expense_account,"
        "e.category,e.receipt_reference,e.pms_journal,'Petty Cash',-1 "
        "FROM `tabHS Petty Cash Expense` e WHERE e.property=%s "
        "AND e.business_date BETWEEN %s AND %s AND e.status='Posted' AND e.pms_journal IS NOT NULL "
        "UNION ALL SELECT 'Petty Cash Variance',r.name,r.approved_business_date,"
        "IF(r.variance>0,'Overage','Shortage'),r.currency,ABS(r.variance),ABS(r.variance),"
        "1,NULL,NULL,NULL,r.variance_account,NULL,r.name,r.pms_variance_journal,"
        "'Petty Cash',IF(r.variance>0,1,-1) "
        "FROM `tabHS Petty Cash Rendition` r WHERE r.property=%s "
        "AND r.approved_business_date BETWEEN %s AND %s "
        "AND r.status IN ('Approved','Partially Reimbursed','Reimbursed') "
        "AND r.pms_variance_journal IS NOT NULL AND r.pms_variance_reversal_journal IS NULL")
    params = (prop.name, start, end) * 4
    rows = frappe.db.sql("SELECT * FROM (" + union + ") f "
        "ORDER BY business_date,source_type,name LIMIT %s OFFSET %s",
        params + (page_length, offset), as_dict=True)
    total = frappe.db.sql("SELECT COUNT(*) AS row_count FROM (" + union + ") f",
                          params, as_dict=True)[0]
    totals = frappe.db.sql("SELECT currency,channel,"
        "SUM(amount*sign) AS net_amount,SUM(base_amount*sign) AS net_base "
        "FROM (" + union + ") f GROUP BY currency,channel ORDER BY currency,channel",
        params, as_dict=True)
    return {"rows": [{**row, "amount": _money(row.amount),
        "base_amount": _money(row.base_amount),
        "signed_amount": _money(Decimal(str(row.amount)) * row.sign),
        "signed_base": _money(Decimal(str(row.base_amount)) * row.sign)} for row in rows],
        "total_rows": int(total.row_count),
        "totals": [{"currency": row.currency, "channel": row.channel,
            "net_amount": _money(row.net_amount), "net_base": _money(row.net_base)}
                   for row in totals]}


def _sales(prop, start, end, selected_account, selected_party, offset, page_length):
    union = (
        "SELECT 'Charge' AS source_type,r.name,r.business_date,r.reference,r.party,"
        "p.party_name,r.folio,r.currency,r.income_account,r.net_amount,r.tax_amount,"
        "r.amount AS total_amount,r.journal FROM `tabHS PMS Receivable` r "
        "JOIN `tabHS Party` p ON p.name=r.party "
        "WHERE r.property=%s AND r.business_date BETWEEN %s AND %s "
        "AND r.journal IS NOT NULL "
        "UNION ALL SELECT 'Charge Cancellation',r.name,j.business_date,r.reference,"
        "r.party,p.party_name,r.folio,r.currency,r.income_account,"
        "-r.net_amount,-r.tax_amount,-r.amount,r.reversal_journal "
        "FROM `tabHS PMS Receivable` r JOIN `tabHS Journal` j ON j.name=r.reversal_journal "
        "JOIN `tabHS Party` p ON p.name=r.party "
        "WHERE r.property=%s AND j.business_date BETWEEN %s AND %s "
        "AND r.status='Cancelled' "
        "UNION ALL SELECT 'Credit Note',l.name,d.business_date,d.document_number,"
        "d.party,p.party_name,d.folio,d.currency,l.income_account,"
        "-l.net_amount,-l.tax_amount,-l.total_amount,d.journal "
        "FROM `tabHS PMS Fiscal Line` l "
        "JOIN `tabHS PMS Fiscal Document` d ON d.name=l.parent "
        "JOIN `tabHS Party` p ON p.name=d.party "
        "WHERE d.property=%s AND d.business_date BETWEEN %s AND %s "
        "AND d.document_type='Credit Note' AND d.status='Posted' "
        "AND d.historical_day_pass IS NULL "
        "UNION ALL SELECT 'Historical Credit Note',jl.name,d.business_date,"
        "d.document_number,d.party,p.party_name,d.folio,d.currency,"
        "jl.account,"
        "CASE WHEN a.root_type='Income' THEN jl.credit-jl.debit ELSE 0 END,"
        "CASE WHEN a.root_type='Liability' THEN jl.credit-jl.debit ELSE 0 END,"
        "jl.credit-jl.debit,d.journal "
        "FROM `tabHS Journal Line` jl "
        "JOIN `tabHS PMS Fiscal Document` d ON d.journal=jl.parent "
        "JOIN `tabHS Account` a ON a.name=jl.account "
        "JOIN `tabHS Party` p ON p.name=d.party "
        "WHERE d.property=%s AND d.business_date BETWEEN %s AND %s "
        "AND d.document_type='Credit Note' AND d.status='Posted' "
        "AND d.historical_day_pass IS NOT NULL "
        "AND a.root_type IN ('Income','Liability')")
    where = ""
    extra = []
    if selected_account:
        where += " AND income_account=%s"
        extra.append(selected_account)
    if selected_party:
        where += " AND party=%s"
        extra.append(selected_party)
    params = list((prop.name, start, end) * 4) + extra
    selection = "SELECT * FROM (" + union + ") sales WHERE 1=1" + where
    rows = frappe.db.sql(selection + " ORDER BY business_date,source_type,name "
        "LIMIT %s OFFSET %s", tuple(params + [page_length, offset]), as_dict=True)
    totals = frappe.db.sql("SELECT COUNT(*) AS row_count,"
        "COALESCE(SUM(net_amount),0) AS net_amount,"
        "COALESCE(SUM(tax_amount),0) AS tax_amount,"
        "COALESCE(SUM(total_amount),0) AS total_amount FROM (" + union +
        ") sales WHERE 1=1" + where, tuple(params), as_dict=True)[0]
    return {"rows": [{**row, "net_amount": _money(row.net_amount),
        "tax_amount": _money(row.tax_amount), "total_amount": _money(row.total_amount)}
        for row in rows], "total_rows": int(totals.row_count),
        "totals": {"currency": prop.currency, "net_amount": _money(totals.net_amount),
                   "tax_amount": _money(totals.tax_amount),
                   "total_amount": _money(totals.total_amount)}}


def report(property_name, report_name, filters=None, offset=0, page_length=100):
    prop = require(property_name, "report")
    start, end, selected_account, selected_party, offset, page_length = _arguments(
        prop, report_name, filters or {}, offset, page_length)
    if report_name == "trial_balance":
        balance = trial_balance(prop.name, end)
        rows = [row for row in balance["rows"] if not selected_account or
                row["account"] == selected_account]
        result = {"rows": rows[offset:offset + page_length], "total_rows": len(rows),
                  "totals": {"currency": prop.currency,
                      "debit": _money(sum((Decimal(row["debit"]) for row in rows), Decimal(0))),
                      "credit": _money(sum((Decimal(row["credit"]) for row in rows), Decimal(0)))}}
    elif report_name == "general_ledger":
        result = _ledger(prop, start, end, selected_account, selected_party, offset, page_length)
    elif report_name == "receivables":
        result = _receivables(prop, end, selected_party, offset, page_length)
    elif report_name == "sales":
        result = _sales(prop, start, end, selected_account, selected_party, offset, page_length)
    else:
        result = _funds(prop, start, end, offset, page_length)
    return {"property": prop.name, "report": report_name, "label": REPORTS[report_name],
            "base_currency": prop.currency, "from_date": start.isoformat(),
            "to_date": end.isoformat(), "offset": offset, "page_length": page_length,
            "columns": [{"key": key, "label": label} for key, label in COLUMNS[report_name]],
            **result}


def options(property_name):
    prop = require(property_name, "report")
    require_pms(prop)
    return {"reports": [{"name": key, "label": label} for key, label in REPORTS.items()],
        "accounts": frappe.get_all("HS Account", filters={"property": prop.name,
            "is_group": 0}, fields=["name", "account_code", "account_name"],
            order_by="account_code asc", limit_page_length=5000),
        "parties": frappe.get_all("HS Party", filters={"property": prop.name,
            "party_type": ["in", ["Customer", "Both"]]},
            fields=["name", "party_name"], order_by="party_name asc", limit_page_length=5000)}


def export_csv(property_name, report_name, filters=None):
    selected = filters or {}
    first = report(property_name, report_name, selected, 0, 200)
    if first["total_rows"] > 50000:
        frappe.throw(_("El CSV supera 50000 filas; reduzca el período o seleccione una cuenta"))
    output = StringIO(newline="")
    writer = csv.writer(output)
    keys = [column["key"] for column in first["columns"]]
    writer.writerow([column["label"] for column in first["columns"]])
    numeric = {"debit", "credit", "balance", "account_balance", "account_debit",
        "account_credit", "running_base", "running_account", "days_overdue",
        "amount", "outstanding", "base_outstanding", "signed_amount", "signed_base", "net_amount",
        "tax_amount", "total_amount"}

    def write_rows(rows):
        for row in rows:
            values = []
            for key in keys:
                value = str(row.get(key) or "")
                if key not in numeric and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                    value = "'" + value
                values.append(value)
            writer.writerow(values)

    write_rows(first["rows"])
    for offset in range(200, first["total_rows"], 200):
        write_rows(report(property_name, report_name, selected, offset, 200)["rows"])
    frappe.local.response.update(filename=f"hospitality-pms-{report_name}.csv",
                                 filecontent=output.getvalue().encode("utf-8-sig"),
                                 type="binary", content_type="text/csv")
