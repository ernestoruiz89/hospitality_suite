"""Rollback-only opening proof for an ERPNext customer credit note in USD."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import frappe

from hospitality_suite import api, erp_to_pms_transfer_plan, setup
from hospitality_suite.erp_to_pms_transfer_rehearsal import _post_property
from hospitality_suite.service import insert, operation
from hospitality_suite.standalone_accounting import account_currency_balance, post
from hospitality_suite.standalone_closing import build as close_snapshot
from hospitality_suite.standalone_opening_credits import balances
from hospitality_suite.standalone_receivables import opening_balances


def run(kind="Credit Note"):
    if "erpnext" in frappe.get_installed_apps() or not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente el sitio PMS de ensayo")
    if kind not in ("Credit Note", "Advance"):
        frappe.throw("Tipo de crédito de ensayo inválido")
    frappe.set_user("Administrator")
    suffix = uuid4().hex
    savepoint = "hs_foreign_credit_opening"
    frappe.db.savepoint(savepoint)
    try:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "Foreign credit " + suffix,
            "base_currency": "NIO", "tax_regime": "General", "active": 1}).insert()
        created = setup.create_property({"property_name": "Foreign credit " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "fx-credit-opening-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        prop.set("accepted_currencies", [{"currency": "USD"}])
        prop.save()
        with operation(prop):
            bridge = insert("HS Account", prop, organization=org.name,
                account_code="1992-" + suffix[:8], account_name="Puente crédito FX",
                root_type="Asset", account_type="Temporary",
                account_currency="NIO", active=1, is_group=0)
            ar = insert("HS Account", prop, organization=org.name,
                account_code="1212-" + suffix[:8], account_name="Clientes USD",
                root_type="Asset", account_type="Receivable",
                account_currency="USD", active=1, is_group=0)
            bank = insert("HS Account", prop, organization=org.name,
                account_code="1112-" + suffix[:8], account_name="Banco NIO",
                root_type="Asset", account_type="Bank",
                account_currency="NIO", active=1, is_group=0, is_bank=1)
            variance = insert("HS Account", prop, organization=org.name,
                account_code="5192-" + suffix[:8], account_name="Cambio crédito",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            new_variance = insert("HS Account", prop, organization=org.name,
                account_code="5193-" + suffix[:8], account_name="Cambio futuro",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            customer = insert("HS Party", prop, organization=org.name,
                party_name="Cliente crédito FX", party_type="Customer", active=1)
            invoice_source = "SINV-" + suffix
            previous_flag = getattr(frappe.local, "hs_fiscal_archive_import", False)
            frappe.local.hs_fiscal_archive_import = True
            try:
                insert("HS Historical Fiscal Document", prop,
                    organization=org.name,
                    source_key=sha256(("erp.example.invalid|Sales Invoice|" +
                        invoice_source).encode()).hexdigest(),
                    source_site="erp.example.invalid", source_company="ERP-ORIGIN",
                    source_doctype="Sales Invoice", source_name=invoice_source,
                    document_type="Invoice", document_number=invoice_source,
                    posting_date=prop.business_date, buyer_name="Cliente crédito FX",
                    currency="USD", total_amount="100.00", status="Posted",
                    snapshot_sha256="c" * 64, pdf_sha256="d" * 64,
                    package_sha256="e" * 64,
                    archived_at=frappe.utils.now_datetime())
            finally:
                frappe.local.hs_fiscal_archive_import = previous_flag
            group_name = ("opening_advances" if kind == "Advance" else
                          "opening_customer_credits")
            records = {"blockers": [], "opening_customer_credits": [],
                "opening_advances": [], "opening_receivables": []}
            controls = defaultdict(Decimal)
            erp_to_pms_transfer_plan._control(
                {"property": "SOURCE-HOTEL", "currency": "NIO"},
                {"accounts": {"AR-USD": ar.name},
                 "customers": {"CUSTOMER": customer.name}},
                records, controls, group_name,
                ("PAY-ADV-" if kind == "Advance" else "SINV-CN-") + suffix,
                "AR-USD", "CUSTOMER", "customers", "-1800.00", "USD", 2,
                signed_original="-50.00",
                voucher_type="Payment Entry" if kind == "Advance" else None)
            if (records["blockers"] or len(records[group_name]) != 1 or
                    controls[(ar.name, customer.name)] != Decimal("-1800")):
                frappe.throw("El plan no representó la nota extranjera")
            erp_to_pms_transfer_plan._control(
                {"property": "SOURCE-HOTEL", "currency": "NIO"},
                {"accounts": {"AR-USD": ar.name},
                 "customers": {"CUSTOMER": customer.name}},
                records, controls, "opening_receivables", invoice_source,
                "AR-USD", "CUSTOMER", "customers", "3500.00", "USD", 2,
                signed_original="100.00", due_date=str(prop.business_date))
            if records["blockers"] or controls[(ar.name, customer.name)] != 1700:
                frappe.throw("El plan no concilió cartera y crédito extranjeros")
            plan = {"temporary_opening_account": bridge.name,
                "opening_receivables": records["opening_receivables"],
                "opening_customer_credits": records["opening_customer_credits"],
                "opening_advances": records["opening_advances"],
                "opening_guarantees": [],
                "opening_payables": [], "opening_supplier_credits": [],
                "opening_stock": [], "residual_journal": []}
            posted = _post_property(prop, "erp.example.invalid", "b" * 64, plan)
            credit = frappe.get_doc("HS PMS Opening Credit", posted["credits"][0])
            receivable = frappe.get_doc("HS PMS Receivable", posted["receivables"][0])
            position = account_currency_balance(prop, ar.name)
            close = close_snapshot(prop)
            opened = next(row for row in close["breakdown"]["opening_customer_credits"]
                if row["currency"] == "USD")
            if (credit.currency != "USD" or Decimal(str(credit.amount)) != 50 or
                    credit.base_currency != "NIO" or
                    Decimal(str(credit.base_amount)) != 1800 or
                    balances(prop, credit.name) != (Decimal(50), Decimal(1800)) or
                    Decimal(position["balance"]) != 50 or
                    Decimal(position["base_balance"]) != 1700 or
                    (opened["amount"], opened["base_amount"]) !=
                        ("50.00", "1800.00")):
                frappe.throw("La apertura perdió el principal o valor base del crédito")
            post(prop, source_doctype="HS Account", source_name=bank.name,
                purpose="Opening Bank", memo="Fondo bancario de prueba",
                lines=[{"account": bank.name, "debit": "2000.00", "credit": "0"},
                    {"account": bridge.name, "debit": "0", "credit": "2000.00"}])
            prop.pms_exchange_variance_account = variance.name
            prop.save()
            apply_data = {"credit": credit.name, "receivable": receivable.name,
                "amount": "20.00", "reason": "Aplicación parcial USD"}
            try:
                api.pms_opening_credit_apply_quote(prop.name,
                    {**apply_data, "amount": "50.01"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La nota extranjera permitió aplicar más del disponible")
            apply_quote = api.pms_opening_credit_apply_quote(prop.name, apply_data)
            if ((apply_quote["source_base_amount"],
                    apply_quote["target_base_amount"],
                    apply_quote["exchange_variance_base"]) !=
                    ("720.00", "700.00", "20.00")):
                frappe.throw("La aplicación no separó valores históricos")
            applied = api.execute(prop.name, "pms_apply_opening_credit",
                "fx-credit-apply-" + suffix,
                {**apply_data, "acceptance": apply_quote["acceptance"]})
            if (balances(prop, credit.name) != (Decimal(30), Decimal(1080)) or
                    opening_balances(prop, receivable.name) !=
                    (Decimal(80), Decimal(2800))):
                frappe.throw("La aplicación no redujo ambas obligaciones")
            try:
                api.execute(prop.name, "pms_apply_opening_credit",
                    "fx-credit-apply-stale-" + suffix,
                    {**apply_data, "acceptance": apply_quote["acceptance"]})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La vista previa antigua duplicó la aplicación")
            prop.pms_exchange_variance_account = new_variance.name
            prop.save()
            original_variance = frappe.get_doc("HS Account", variance.name)
            original_variance.active = 0
            try:
                original_variance.save()
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Se desactivó la cuenta cambiaria de una aplicación pendiente")
            reversed_application = api.execute(prop.name, "pms_unapply_opening_credit",
                "fx-credit-unapply-" + suffix,
                {"allocation": applied["allocation"], "amount": "10.00",
                 "reason": "Reversión parcial USD"})
            reversed_accounts = {row.account for row in frappe.get_all(
                "HS Journal Line",
                filters={"parent": frappe.db.get_value("HS PMS Allocation",
                    reversed_application["allocation"], "journal")},
                fields=["account"])}
            if (variance.name not in reversed_accounts or
                    new_variance.name in reversed_accounts):
                frappe.throw("La reversión cambió la cuenta original de diferencia")
            prop.pms_exchange_variance_account = variance.name
            prop.save()
            if (balances(prop, credit.name) != (Decimal(40), Decimal(1440)) or
                    opening_balances(prop, receivable.name) !=
                    (Decimal(90), Decimal(3150))):
                frappe.throw("La reversión no restauró ambos saldos históricos")
            method = api.execute(prop.name, "pms_payment_method",
                "fx-credit-method-" + suffix,
                {"label": "Banco NIO crédito", "account": bank.name})["method"]
            first_data = {"credit": credit.name, "method": method,
                "amount": "740.00", "settled_amount": "20.00",
                "reference": "FX-CREDIT-REF-1-" + suffix,
                "reason": "Devolución parcial nota USD"}
            first_quote = api.pms_opening_credit_refund_quote(prop.name, first_data)
            if ((first_quote["settled_amount"],
                    first_quote["released_base_amount"],
                    first_quote["exchange_variance_base"]) !=
                    ("20.00", "720.00", "20.00")):
                frappe.throw("La devolución no midió la diferencia cambiaria")
            first_payload = {**first_data, "acceptance": first_quote["acceptance"]}
            first = api.execute(prop.name, "pms_refund_opening_credit",
                "fx-credit-ref-1-" + suffix, first_payload)
            if (api.execute(prop.name, "pms_refund_opening_credit",
                    "fx-credit-ref-1-" + suffix, first_payload) != first or
                    balances(prop, credit.name) !=
                        (Decimal("20"), Decimal("720"))):
                frappe.throw("La devolución duplicó o perdió el crédito")
            try:
                api.pms_opening_credit_refund_quote(prop.name,
                    {**first_data, "amount": "1080.00",
                     "settled_amount": "30.00",
                     "reference": "OVER-" + suffix})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La devolución superó el principal disponible")
            changed_payment = frappe.get_doc("HS Payment", first["payment"])
            changed_payment.pms_settled_amount = "21.00"
            try:
                changed_payment.save()
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La devolución contabilizada permitió alterar el principal")
            lines = frappe.get_all("HS Journal Line",
                filters={"parent": first["journal"]},
                fields=["account", "debit", "credit",
                        "debit_in_account_currency"])
            if {(row.account, Decimal(str(row.debit)),
                    Decimal(str(row.credit)),
                    Decimal(str(row.debit_in_account_currency)))
                    for row in lines} != {
                    (ar.name, Decimal("720"), Decimal(0), Decimal("20")),
                    (bank.name, Decimal(0), Decimal("740"), Decimal(0)),
                    (variance.name, Decimal("20"), Decimal(0), Decimal("20"))}:
                frappe.throw("El reembolso extranjero no concilió el asiento")
            final_data = {"credit": credit.name, "method": method,
                "amount": "720.00", "settled_amount": "20.00",
                "reference": "FX-CREDIT-REF-FINAL-" + suffix,
                "reason": "Devolución del crédito restante"}
            final_quote = api.pms_opening_credit_refund_quote(prop.name, final_data)
            api.execute(prop.name, "pms_refund_opening_credit",
                "fx-credit-ref-final-" + suffix,
                {**final_data, "acceptance": final_quote["acceptance"]})
            if (balances(prop, credit.name) != (Decimal(0), Decimal(0)) or
                    opening_balances(prop, receivable.name) !=
                    (Decimal(90), Decimal(3150))):
                frappe.throw("El crédito extranjero no quedó liquidado")
            settled_close = close_snapshot(prop)
            movements = settled_close["breakdown"]
            applied_row = next(row for row in movements
                ["foreign_opening_credit_applications"]
                if row["kind"] == "Opening Credit Applied")
            reversed_row = next(row for row in movements
                ["foreign_opening_credit_applications"]
                if row["kind"] == "Opening Credit Reversed")
            refunded_row = movements["foreign_opening_credit_refunds"][0]
            fx_rows = {(row["direction"], row["kind"]): row["base_amount"]
                for row in movements["foreign_opening_credit_exchange_differences"]}
            if (settled_close["version"] != 8 or
                    (applied_row["amount"], applied_row["base_amount"]) !=
                    ("20.00", "700.00") or
                    (reversed_row["amount"], reversed_row["base_amount"]) !=
                    ("10.00", "350.00") or
                    (refunded_row["amount"], refunded_row["base_amount"]) !=
                    ("40.00", "1440.00") or
                    fx_rows != {("Opening Credit Applied", "Gain"): "20.00",
                        ("Opening Credit Reversed", "Loss"): "10.00"} or
                    movements["foreign_opening_credit_refund_exchange_differences"]
                    [0]["base_amount"] != "20.00" or movements["production"]):
                frappe.throw("El cierre mezcló la nota extranjera con ventas")
            report = api.pms_report(prop.name, "receivables",
                {"party": customer.name})
            if (report["total_rows"] != 1 or
                    report["rows"][0]["outstanding"] != "90.00" or
                    report["rows"][0]["base_outstanding"] != "3150.00"):
                frappe.throw("El reporte no concilió la nota aplicada y revertida")
        return {"credit_kind": kind,
            "original_usd": "50.00", "base_nio": "1800.00",
            "plan_and_writer_reconciled": True, "close_separates_currencies": True,
            "partial_application_and_reversal": True,
            "partial_and_final_refund": True, "fx_loss": "20.00",
            "final_close_and_report_reconciled": True,
            "rolled_back": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
        frappe.set_user("Administrator")


def run_advance():
    return run("Advance")
