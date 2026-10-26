"""Rollback-only proof of a foreign ERPNext receivable opening in PMS."""

from collections import defaultdict
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import frappe

from hospitality_suite import api, erp_to_pms_transfer_plan, setup
from hospitality_suite.erp_to_pms_transfer_rehearsal import _post_property
from hospitality_suite.service import insert, operation
from hospitality_suite.standalone_accounting import account_currency_balance
from hospitality_suite.standalone_closing import build as close_snapshot
from hospitality_suite.standalone_receivables import outstanding
from hospitality_suite.standalone_receivables import opening_balances


def run():
    if "erpnext" in frappe.get_installed_apps() or not frappe.local.site.startswith("hs-pms-smoke"):
        frappe.throw("Use únicamente el sitio PMS de ensayo")
    if not frappe.db.get_value("Currency", "USD", "enabled"):
        frappe.throw("Habilite USD en el sitio de ensayo")
    frappe.set_user("Administrator")
    suffix = uuid4().hex
    source_site = "erp.example.invalid"
    source_name = "SINV-FX-" + suffix
    source_hash = "b" * 64
    savepoint = "hs_foreign_receivable_opening"
    frappe.db.savepoint(savepoint)
    try:
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "Foreign AR " + suffix, "base_currency": "NIO",
            "tax_regime": "General", "active": 1}).insert()
        created = setup.create_property({"property_name": "Foreign AR " + suffix,
            "organization": org.name, "currency": "NIO", "mode": "Hotel"},
            "fx-ar-opening-" + suffix)
        prop = frappe.get_doc("HS Property", created["property"])
        prop.set("accepted_currencies", [{"currency": "USD"}])
        prop.save()
        with operation(prop):
            temporary = insert("HS Account", prop, organization=org.name,
                account_code="1991-" + suffix[:8], account_name="Puente FX clientes",
                root_type="Asset", account_type="Temporary",
                account_currency="NIO", active=1, is_group=0)
            receivable = insert("HS Account", prop, organization=org.name,
                account_code="1211-" + suffix[:8], account_name="Clientes USD",
                root_type="Asset", account_type="Receivable",
                account_currency="USD", active=1, is_group=0)
            bank = insert("HS Account", prop, organization=org.name,
                account_code="1111-" + suffix[:8], account_name="Banco NIO",
                root_type="Asset", account_type="Bank",
                account_currency="NIO", active=1, is_group=0, is_bank=1)
            variance = insert("HS Account", prop, organization=org.name,
                account_code="5191-" + suffix[:8], account_name="Cambio clientes",
                root_type="Expense", account_type="General",
                account_currency="NIO", active=1, is_group=0)
            customer = insert("HS Party", prop, organization=org.name,
                party_name="Cliente FX", party_type="Customer", active=1)
            previous_flag = getattr(frappe.local, "hs_fiscal_archive_import", False)
            frappe.local.hs_fiscal_archive_import = True
            try:
                insert("HS Historical Fiscal Document", prop,
                    organization=org.name,
                    source_key=sha256((source_site + "|Sales Invoice|" +
                        source_name).encode()).hexdigest(),
                    source_site=source_site, source_company="ERP-ORIGIN",
                    source_doctype="Sales Invoice", source_name=source_name,
                    document_type="Invoice", document_number=source_name,
                    posting_date=prop.business_date, buyer_name="Cliente FX",
                    currency="USD", total_amount="100.00", status="Posted",
                    snapshot_sha256="c" * 64, pdf_sha256="d" * 64,
                    package_sha256="e" * 64,
                    archived_at=frappe.utils.now_datetime())
            finally:
                frappe.local.hs_fiscal_archive_import = previous_flag
            records = {"blockers": [], "opening_receivables": []}
            controls = defaultdict(Decimal)
            source = {"property": "SOURCE-HOTEL", "currency": "NIO"}
            mapping = {"accounts": {"AR-USD": receivable.name},
                "customers": {"CUSTOMER": customer.name}}
            erp_to_pms_transfer_plan._control(source, mapping, records,
                controls, "opening_receivables", source_name, "AR-USD",
                "CUSTOMER", "customers", "3600.00", "USD", 2,
                signed_original="100.00")
            if (records["blockers"] or
                    records["opening_receivables"][0]["signed_account_balance"] !=
                        "100.00" or
                    controls[(receivable.name, customer.name)] != Decimal("3600")):
                frappe.throw("El plan no aceptó la cartera extranjera conciliada")
            invalid = {"blockers": [], "opening_receivables": []}
            erp_to_pms_transfer_plan._control(source, mapping, invalid,
                defaultdict(Decimal), "opening_receivables", "BAD-" + source_name,
                "AR-USD", "CUSTOMER", "customers", "3600.00", "EUR", 2,
                signed_original="100.00")
            if not invalid["blockers"] or invalid["opening_receivables"]:
                frappe.throw("El plan aceptó una moneda de cuenta distinta")
            plan = {"temporary_opening_account": temporary.name,
                "opening_receivables": [{**records["opening_receivables"][0],
                    "due_date": str(prop.business_date)}],
                "opening_customer_credits": [], "opening_advances": [],
                "opening_guarantees": [], "opening_payables": [],
                "opening_supplier_credits": [], "opening_stock": [],
                "residual_journal": []}
            refs = _post_property(prop, source_site, source_hash, plan)
            opened = frappe.get_doc("HS PMS Receivable", refs["receivables"][0])
            balance = account_currency_balance(prop, receivable.name)
            visible = next(row for row in api.pms_receivables(prop.name)["receivables"]
                if row["name"] == opened.name)
            if (opened.currency != "USD" or
                    Decimal(str(opened.amount)) != Decimal("100") or
                    opened.base_currency != "NIO" or
                    Decimal(str(opened.base_amount)) != Decimal("3600") or
                    outstanding(prop, opened.name) != Decimal("100") or
                    Decimal(balance["balance"]) != Decimal("100") or
                    Decimal(balance["base_balance"]) != Decimal("3600") or
                    visible["outstanding"] != "100.00" or
                    Decimal(str(visible["base_amount"])) != Decimal("3600")):
                frappe.throw("La apertura perdió el principal o el valor base")
            close = close_snapshot(prop)
            opening_close = next(row for row in close["breakdown"]["opening_receivables"]
                if row["currency"] == "USD")
            report = api.pms_report(prop.name, "receivables",
                {"party": customer.name})
            if ((opening_close["amount"], opening_close["base_amount"]) !=
                    ("100.00", "3600.00") or close["breakdown"]["production"] or
                    report["total_rows"] != 1 or
                    report["rows"][0]["outstanding"] != "100.00" or
                    report["rows"][0]["base_outstanding"] != "3600.00" or
                    report["totals"]["outstanding"] != "3600.00"):
                frappe.throw("El cierre o reporte mezcló moneda original y base")
            method = api.execute(prop.name, "pms_payment_method",
                "fx-ar-method-" + suffix,
                {"label": "Banco NIO FX", "account": bank.name})["method"]
            first_data = {"kind": "Payment", "method": method,
                "amount": "1480.00", "settled_amount": "40.00",
                "receivable": opened.name, "reference": "FX-AR-1-" + suffix,
                "reason": "Primer cobro extranjero"}
            try:
                api.pms_cash_preview(prop.name, first_data)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Caja permitió cambio sin cuenta configurada")
            prop.pms_exchange_variance_account = variance.name
            prop.save()
            first_quote = api.pms_cash_preview(prop.name, first_data)
            if ((first_quote["settled_amount"],
                    first_quote["released_base_amount"],
                    first_quote["exchange_variance_base"]) !=
                    ("40.00", "1440.00", "40.00")):
                frappe.throw("El primer cobro no conserva la ganancia cambiaria")
            def reviewed(data, quote):
                return {**data, "expected_exchange_rate": quote["exchange_rate"],
                    "expected_rate_record": quote["exchange_rate_record"],
                    "expected_debit": quote["debit"],
                    "expected_credit": quote["credit"],
                    "expected_settled_amount": quote["settled_amount"],
                    "expected_released_base_amount": quote["released_base_amount"],
                    "expected_exchange_variance_base": quote["exchange_variance_base"]}
            first_payload = reviewed(first_data, first_quote)
            first = api.execute(prop.name, "pms_cash_movement",
                "fx-ar-first-" + suffix, first_payload)
            if (api.execute(prop.name, "pms_cash_movement",
                    "fx-ar-first-" + suffix, first_payload) != first or
                    opening_balances(prop, opened.name) !=
                    (Decimal("60.00"), Decimal("2160.00"))):
                frappe.throw("El primer cobro duplicó o perdió el saldo")
            first_lines = frappe.get_all("HS Journal Line",
                filters={"parent": first["journal"]},
                fields=["account", "debit", "credit", "credit_in_account_currency"])
            if {(line.account, Decimal(str(line.debit)),
                    Decimal(str(line.credit)),
                    Decimal(str(line.credit_in_account_currency)))
                    for line in first_lines} != {
                    (bank.name, Decimal("1480"), Decimal(0), Decimal(0)),
                    (receivable.name, Decimal(0), Decimal("1440"), Decimal("40")),
                    (variance.name, Decimal(0), Decimal("40"), Decimal("40"))}:
                frappe.throw("La ganancia cambiaria del cliente no concilió")
            second_data = {"kind": "Payment", "method": method,
                "amount": "2100.00", "settled_amount": "60.00",
                "receivable": opened.name, "reference": "FX-AR-2-" + suffix,
                "reason": "Cobro final extranjero"}
            second_quote = api.pms_cash_preview(prop.name, second_data)
            if ((second_quote["settled_amount"],
                    second_quote["released_base_amount"],
                    second_quote["exchange_variance_base"]) !=
                    ("60.00", "2160.00", "-60.00")):
                frappe.throw("El cobro final no libera el remanente exacto")
            second = api.execute(prop.name, "pms_cash_movement",
                "fx-ar-second-" + suffix, reviewed(second_data, second_quote))
            if (opening_balances(prop, opened.name) !=
                    (Decimal(0), Decimal(0)) or
                    outstanding(prop, opened.name) != 0 or
                    Decimal(account_currency_balance(prop,
                        receivable.name)["base_balance"]) != 0 or
                    Decimal(account_currency_balance(prop,
                        receivable.name)["balance"]) != 0):
                frappe.throw("El cobro final no saldó cartera original y base")
            second_lines = frappe.get_all("HS Journal Line",
                filters={"parent": second["journal"]},
                fields=["account", "debit", "credit"])
            if {(line.account, Decimal(str(line.debit)),
                    Decimal(str(line.credit))) for line in second_lines} != {
                    (bank.name, Decimal("2100"), Decimal(0)),
                    (receivable.name, Decimal(0), Decimal("2160")),
                    (variance.name, Decimal("60"), Decimal(0))}:
                frappe.throw("La pérdida cambiaria del cliente no concilió")
            settled_close = close_snapshot(prop)
            principal = next(row for row in settled_close["breakdown"]
                ["opening_customer_settlements"] if row["currency"] == "USD")
            differences = {row["kind"]: row["base_amount"] for row in
                settled_close["breakdown"]["opening_customer_exchange_differences"]}
            if (settled_close["version"] != 8 or
                    (principal["amount"], principal["base_amount"]) !=
                    ("100.00", "3600.00") or
                    differences != {"Gain": "40.00", "Loss": "60.00"} or
                    settled_close["breakdown"]["production"]):
                frappe.throw("El cierre mezcló el principal y cambio del cliente")
            final_report = api.pms_report(prop.name, "receivables",
                {"party": customer.name})
            if (final_report["total_rows"] != 0 or
                    final_report["totals"]["outstanding"] != "0.00"):
                frappe.throw("El reporte no saldó la cartera extranjera")
            refundable = {row["name"]: row for row in
                api.pms_cash_snapshot(prop.name)["refundable"]}
            if (refundable[first["payment"]]["remaining_settled_amount"] !=
                    "40.00" or refundable[second["payment"]]
                    ["remaining_released_base"] != "2160.00"):
                frappe.throw("Caja no muestra los cobros extranjeros devolvibles")
            refund_one_data = {"source_payment": first["payment"],
                "amount": "740.00", "reference": "FX-AR-REF-1-" + suffix,
                "reason": "Devolución parcial del primer cobro"}
            refund_one_quote = api.pms_refund_preview(prop.name, refund_one_data)
            if ((refund_one_quote["settled_amount"],
                    refund_one_quote["released_base_amount"],
                    refund_one_quote["exchange_variance_base"]) !=
                    ("20.00", "720.00", "20.00")):
                frappe.throw("La devolución no invirtió la ganancia original")
            try:
                api.execute(prop.name, "pms_refund", "fx-ar-unreviewed-" + suffix,
                    refund_one_data)
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La devolución extranjera no exigió revisar el asiento")
            def reviewed_refund(data, quote):
                return {**data, "expected_base_amount": quote["base_amount"],
                    "expected_debit": quote["debit"],
                    "expected_credit": quote["credit"],
                    "expected_settled_amount": quote["settled_amount"],
                    "expected_released_base_amount": quote["released_base_amount"],
                    "expected_exchange_variance_base": quote["exchange_variance_base"]}
            refund_one_payload = reviewed_refund(refund_one_data, refund_one_quote)
            refund_one = api.execute(prop.name, "pms_refund",
                "fx-ar-refund-1-" + suffix, refund_one_payload)
            if (api.execute(prop.name, "pms_refund",
                    "fx-ar-refund-1-" + suffix, refund_one_payload) != refund_one or
                    opening_balances(prop, opened.name) !=
                        (Decimal("20"), Decimal("720"))):
                frappe.throw("La devolución parcial duplicó o perdió cartera")
            changed_refund = frappe.get_doc("HS Payment", refund_one["payment"])
            changed_refund.pms_settled_amount = "21.00"
            try:
                changed_refund.save()
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("Una devolución registrada permitió alterar el principal")
            try:
                api.pms_refund_preview(prop.name, {
                    **refund_one_data, "amount": "740.01"})
            except frappe.ValidationError:
                frappe.clear_messages()
            else:
                frappe.throw("La devolución excedió el cobro disponible")
            refund_one_lines = frappe.get_all("HS Journal Line",
                filters={"parent": refund_one["journal"]},
                fields=["account", "debit", "credit",
                        "debit_in_account_currency"])
            if {(line.account, Decimal(str(line.debit)),
                    Decimal(str(line.credit)),
                    Decimal(str(line.debit_in_account_currency)))
                    for line in refund_one_lines} != {
                    (receivable.name, Decimal("720"), Decimal(0), Decimal("20")),
                    (bank.name, Decimal(0), Decimal("740"), Decimal(0)),
                    (variance.name, Decimal("20"), Decimal(0), Decimal("20"))}:
                frappe.throw("La devolución no invirtió el asiento del primer cobro")
            refund_two_data = {"source_payment": second["payment"],
                "amount": "1050.00", "reference": "FX-AR-REF-2-" + suffix,
                "reason": "Devolución parcial del cobro final"}
            refund_two_quote = api.pms_refund_preview(prop.name, refund_two_data)
            if ((refund_two_quote["settled_amount"],
                    refund_two_quote["released_base_amount"],
                    refund_two_quote["exchange_variance_base"]) !=
                    ("30.00", "1080.00", "-30.00")):
                frappe.throw("La devolución no invirtió la pérdida original")
            refund_two = api.execute(prop.name, "pms_refund",
                "fx-ar-refund-2-" + suffix,
                reviewed_refund(refund_two_data, refund_two_quote))
            if (opening_balances(prop, opened.name) !=
                    (Decimal("50"), Decimal("1800")) or
                    Decimal(account_currency_balance(prop,
                        receivable.name)["balance"]) != Decimal("50") or
                    Decimal(account_currency_balance(prop,
                        receivable.name)["base_balance"]) != Decimal("1800")):
                frappe.throw("Las devoluciones no restituyeron cartera original y base")
            refunds_close = close_snapshot(prop)
            refund_principal = next(row for row in refunds_close["breakdown"]
                ["opening_customer_refunds"] if row["currency"] == "USD")
            refund_differences = {row["kind"]: row["base_amount"] for row in
                refunds_close["breakdown"]
                    ["opening_customer_refund_exchange_differences"]}
            if ((refund_principal["amount"], refund_principal["base_amount"]) !=
                    ("50.00", "1800.00") or refund_differences !=
                    {"Gain Reversed": "20.00", "Loss Reversed": "30.00"} or
                    refunds_close["breakdown"]["production"]):
                frappe.throw("El cierre no desglosó los reversos de cartera")
            reopened = api.pms_report(prop.name, "receivables",
                {"party": customer.name})
            if (reopened["total_rows"] != 1 or
                    reopened["rows"][0]["outstanding"] != "50.00" or
                    reopened["rows"][0]["base_outstanding"] != "1800.00"):
                frappe.throw("El reporte no reabrió la cartera restituida")
            for original_payment, remaining_amount in (
                    (first["payment"], "740.00"),
                    (second["payment"], "1050.00")):
                data = {"source_payment": original_payment,
                    "amount": remaining_amount,
                    "reference": "FX-AR-REF-FINAL-" + original_payment,
                    "reason": "Devolución del remanente original"}
                preview = api.pms_refund_preview(prop.name, data)
                api.execute(prop.name, "pms_refund",
                    "fx-ar-refund-final-" + original_payment,
                    reviewed_refund(data, preview))
            if (opening_balances(prop, opened.name) !=
                    (Decimal("100"), Decimal("3600")) or
                    Decimal(account_currency_balance(prop,
                        receivable.name)["balance"]) != Decimal("100") or
                    Decimal(account_currency_balance(prop,
                        receivable.name)["base_balance"]) != Decimal("3600") or
                    Decimal(account_currency_balance(prop, bank.name)["balance"]) != 0 or
                    Decimal(account_currency_balance(prop, variance.name)["balance"]) != 0 or
                    any(row["name"] in (first["payment"], second["payment"])
                        for row in api.pms_cash_snapshot(prop.name)["refundable"])):
                frappe.throw("El reembolso final no revirtió íntegramente los cobros")
        return {"original_usd": "100.00", "base_nio": "3600.00",
            "plan_accepts_foreign_ar": True,
            "account_currency_reconciled": True,
            "close_and_report_separate_currencies": True,
            "partial_collections": 2, "fx_gain": "40.00",
            "fx_loss": "60.00", "idempotent": True,
            "nominal_and_base_zero_after_collection": True,
            "partial_refunds": 2, "full_residual_refunds": 2,
            "refunded_usd": "100.00", "restored_base": "3600.00",
            "rolled_back": True}
    finally:
        frappe.db.rollback(save_point=savepoint)
        frappe.set_user("Administrator")
