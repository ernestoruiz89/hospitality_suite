"""Rollback-only probes of a native ERPNext credit for a PMS historical sale."""

from hashlib import sha256

import frappe

from hospitality_suite import accounting, api as suite_api, cashier, day_pass as erp_day_pass_view, pms_cutover_writer, standalone_currency
from hospitality_suite.service import canonical, insert, operation


def inspect():
    if frappe.local.site != "hospitality-acceptance.localhost":
        frappe.throw("Use el sitio ERPNext de aceptación")
    prop = frappe.get_doc("HS Property", "qmqrio5i1h")
    return {"provider": __import__(
        "hospitality_suite.standalone_accounting",
        fromlist=["provider"]).provider(),
        "accepted_currencies": [row.currency for row in prop.accepted_currencies],
        "company_currency": frappe.db.get_value("Company", prop.company,
            "default_currency"),
        "usd_accounts": frappe.get_all("Account", filters={
            "company": prop.company, "account_currency": "USD",
            "is_group": 0}, fields=["name", "account_type"],
            limit_page_length=20),
        "asset_groups": frappe.get_all("Account", filters={
            "company": prop.company, "root_type": "Asset", "is_group": 1},
            fields=["name", "account_type", "parent_account"],
            limit_page_length=20),
        "methods": frappe.get_all("HS Payment Method",
            filters={"property": prop.name},
            fields=["name", "mode_of_payment", "currency", "is_cash", "account"]),
        "shifts": frappe.get_all("HS Shift",
            filters={"property": prop.name, "status": "Open"},
            fields=["name", "cashier", "currency"])}


def run():
    if frappe.local.site != "hospitality-acceptance.localhost":
        frappe.throw("Use el sitio ERPNext de aceptación")
    before = frappe.session.user
    frappe.set_user("Administrator")
    frappe.db.savepoint("hs_historical_day_pass_credit_probe")
    try:
        prop = frappe.get_doc("HS Property", "qmqrio5i1h")
        customer = "Cliente ficticio M3"
        item = "HS-DEMO-EXTRA-HOUR"
        income = "Servicios - HSD"
        tax = "VAT - HSD"
        temporary = frappe.db.get_value("Account", {
            "company": prop.company, "is_group": 0,
            "account_type": "Temporary"}, "name")
        if (not frappe.db.exists("Customer", customer) or
                not frappe.db.exists("Item", item) or
                not frappe.db.exists("Account", income) or
                not frappe.db.exists("Account", tax) or not temporary):
            frappe.throw("Falta un maestro de ensayo")
        with pms_cutover_writer._migration_posting():
            opening = pms_cutover_writer._opening_invoice({
                "company": prop.company, "customer": customer,
                "cost_center": prop.cost_center,
                "temporary_opening_account": temporary,
                "source": "PMS-DAY-PROBE", "reference": "PMS-FISCAL-PROBE",
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(), "currency": prop.currency,
                "outstanding": "8", "debit_to": prop.receivable_account,
                "property": prop.name}, sales=True)
        credit = frappe.new_doc("Sales Invoice")
        credit.flags.ignore_permissions = True
        credit.flags.dont_auto_add_taxes = True
        credit.update({"company": prop.company, "customer": customer,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(), "currency": prop.currency,
            "debit_to": prop.receivable_account,
            "cost_center": prop.cost_center, "hs_property": prop.name,
            "is_return": 1, "update_stock": 0,
            "selling_price_list": prop.price_list,
            "price_list_currency": prop.currency,
            "plc_conversion_rate": 1,
            "remarks": "PMS historical Day Pass credit probe"})
        credit.append("items", {"item_code": item, "qty": -1,
            "rate": 18, "income_account": income,
            "cost_center": prop.cost_center, "warehouse": prop.warehouse})
        credit.append("taxes", {"charge_type": "Actual",
            "account_head": tax, "tax_amount": -2,
            "description": "PMS historical tax"})
        credit.set_missing_values()
        credit.calculate_taxes_and_totals()
        before_total = credit.grand_total
        with operation(prop):
            accounting.post_standard(credit, prop)
        accounting._reconcile_credit_to_unpaid(prop, opening, credit)
        opening.reload()
        credit.reload()
        refund = frappe.new_doc("Payment Entry")
        refund.update({"company": prop.company, "payment_type": "Pay",
            "posting_date": frappe.utils.today(),
            "party_type": "Customer", "party": customer,
            "paid_from": "Efectivo - HSD",
            "paid_to": prop.receivable_account,
            "paid_amount": 12, "received_amount": 12,
            "source_exchange_rate": 1, "target_exchange_rate": 1,
            "reference_no": credit.name,
            "reference_date": frappe.utils.today(),
            "cost_center": prop.cost_center,
            "remarks": "PMS historical Day Pass refund probe"})
        refund.append("references", {"reference_doctype": "Sales Invoice",
            "reference_name": credit.name, "allocated_amount": -12})
        with operation(prop):
            accounting.post_standard(refund, prop)
        credit.reload()
        entries = frappe.get_all("GL Entry", filters={
            "voucher_type": "Sales Invoice", "voucher_no": credit.name,
            "is_cancelled": 0}, fields=["account", "debit", "credit",
                                      "party", "against_voucher"],
            limit_page_length=0)
        return {"prepared_total": before_total,
            "posted_total": credit.grand_total,
            "outstanding": credit.outstanding_amount,
            "is_return": credit.is_return,
            "return_against": credit.return_against,
            "opening_outstanding": opening.outstanding_amount,
            "credit_outstanding": credit.outstanding_amount,
            "refund": refund.name,
            "gl": entries}
    finally:
        frappe.db.rollback(save_point="hs_historical_day_pass_credit_probe")
        frappe.set_user(before)


def run_return():
    return _run_return()


def run_return_after_payment():
    return _run_return(collect=3)


def run_return_after_pms_credit():
    return _run_return(credited=5)


def run_return_fully_paid_in_pms():
    return _run_return(opening_due=0)


def run_return_fully_unpaid():
    return _run_return(opening_due=20)


def run_return_foreign_bank():
    return _run_return(opening_due=0, foreign_bank=True)


def _run_return(collect=0, credited=0, opening_due=8, foreign_bank=False):
    if frappe.local.site != "hospitality-acceptance.localhost":
        frappe.throw("Use el sitio ERPNext de aceptación")
    before = frappe.session.user
    frappe.set_user("Administrator")
    frappe.db.savepoint("hs_historical_day_pass_return_probe")
    try:
        prop = frappe.get_doc("HS Property", "qmqrio5i1h")
        customer = "Cliente ficticio M3"
        item = "HS-DEMO-EXTRA-HOUR"
        income = "Servicios - HSD"
        tax = "VAT - HSD"
        method = frappe.db.get_value("HS Payment Method", {
            "property": prop.name, "is_cash": 1,
            "currency": prop.currency}, "name")
        temporary = frappe.db.get_value("Account", {
            "company": prop.company, "is_group": 0,
            "account_type": "Temporary"}, "name")
        if not method or not temporary:
            frappe.throw("Falta un maestro de ensayo")
        if foreign_bank:
            with operation(prop):
                standalone_currency.configure_erp(prop, {
                    "currencies": [prop.currency, "USD"]})
                bank = frappe.get_doc({"doctype": "Account",
                    "account_name": "HS Day Pass USD Probe",
                    "parent_account": frappe.db.get_value("Account", {
                        "company": prop.company, "account_type": "Bank",
                        "is_group": 1}, "name"),
                    "company": prop.company, "account_type": "Bank",
                    "account_currency": "USD", "is_group": 0}).insert(
                        ignore_permissions=True)
                mode = frappe.get_doc({"doctype": "Mode of Payment",
                    "mode_of_payment": "HS Day Pass USD Probe", "type": "Bank",
                    "accounts": [{"company": prop.company,
                        "default_account": bank.name}]}).insert(
                            ignore_permissions=True)
                method = insert("HS Payment Method", prop,
                    mode_of_payment=mode.name, account=bank.name,
                    currency="USD", is_cash=0, reference_required=1).name
                existing_rate = frappe.db.get_value("Currency Exchange", {
                    "date": frappe.utils.today(),
                    "from_currency": "USD", "to_currency": prop.currency,
                    "for_buying": 1, "for_selling": 1}, "name")
                if existing_rate:
                    frappe.db.set_value("Currency Exchange", existing_rate,
                        "exchange_rate", 36.5)
                else:
                    frappe.get_doc({"doctype": "Currency Exchange",
                        "date": frappe.utils.today(),
                        "from_currency": "USD", "to_currency": prop.currency,
                        "exchange_rate": 36.5, "for_buying": 1,
                        "for_selling": 1}).insert(ignore_permissions=True)
        opening = None
        if opening_due:
            with pms_cutover_writer._migration_posting():
                opening = pms_cutover_writer._opening_invoice({
                    "company": prop.company, "customer": customer,
                    "cost_center": prop.cost_center,
                    "temporary_opening_account": temporary,
                    "source": "PMS-DAY-RETURN-PROBE", "reference": "PMS-FISCAL-RETURN-PROBE",
                    "posting_date": frappe.utils.today(),
                    "due_date": frappe.utils.today(), "currency": prop.currency,
                    "outstanding": str(opening_due),
                    "debit_to": prop.receivable_account,
                    "property": prop.name}, sales=True)
        receivable = "HS-PROBE-RECV-" + frappe.generate_hash(length=8)
        name = "HS-PROBE-DAY-" + frappe.generate_hash(length=8)
        now = frappe.utils.now_datetime()
        frappe.db.sql("""INSERT INTO `tabHS PMS Receivable`
            (name, creation, modified, owner, modified_by, docstatus, idx,
             company, property, organization, party, reference, description,
             business_date, currency, amount, status)
             VALUES (%s,%s,%s,%s,%s,0,0,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (receivable, now, now, "Administrator", "Administrator",
             prop.company, prop.name, prop.organization, customer,
             "HS-RETURN-PROBE", "Historical Day Pass probe", prop.business_date,
             prop.currency, 20, "Posted"))
        proof = canonical({"source": name, "property": prop.name,
            "company": prop.company, "customer": customer,
            "source_receivable": receivable,
            "opening_invoice": opening.name if opening else None,
            "outstanding": str(opening_due), "source_financial": {
                "outstanding_amount": str(opening_due)},
            "accepted_sale": {"net_amount": "18", "tax_amount": "2",
                "total_amount": "20"},
            "source_fiscal": {"invoice": {
                "document_number": "PMS-RETURN-PROBE"},
                "credits": ([{"net_amount": "4.50", "tax_amount": "0.50",
                    "total_amount": "5.00"}] if credited else [])},
            "target_accounts": {"receivable_account": prop.receivable_account,
                "income_account": income, "tax_account": tax},
            "item_code": item})
        frappe.db.sql("""INSERT INTO `tabHS Day Pass`
            (name, creation, modified, owner, modified_by, docstatus, idx,
             company, property, customer, people, starts_at, ends_at, status,
             pms_receivable, quote_snapshot, erp_opening_invoice,
             erp_opening_snapshot, erp_opening_sha256)
             VALUES (%s,%s,%s,%s,%s,0,0,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (name, now, now, "Administrator", "Administrator", prop.company,
             prop.name, customer, now,
             frappe.utils.add_to_date(now, hours=2), "Issued", receivable,
             "{}", opening.name if opening else None, proof,
             sha256(proof.encode()).hexdigest()))
        with operation(prop):
            shift = cashier.open_shift(prop, {"currency": prop.currency,
                "opening_amount": "100"})["shift"]
            if collect and opening:
                collected = frappe.new_doc("Payment Entry")
                collected.update({"company": prop.company,
                    "payment_type": "Receive", "posting_date": frappe.utils.today(),
                    "party_type": "Customer", "party": customer,
                    "paid_from": prop.receivable_account,
                    "paid_to": "Efectivo - HSD", "paid_amount": collect,
                    "received_amount": collect, "source_exchange_rate": 1,
                    "target_exchange_rate": 1, "hs_shift": shift,
                    "reference_no": "HS-COLLECTION-PROBE",
                    "reference_date": frappe.utils.today(),
                    "cost_center": prop.cost_center})
                collected.append("references", {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": opening.name,
                    "allocated_amount": collect})
                accounting.post_standard(collected, prop)
                insert("HS Payment", prop, customer=customer, shift=shift,
                    method=method, currency=prop.currency, amount=collect,
                    exchange_rate=1, base_amount=collect,
                    kind="Payment", status="Posted",
                    payment_entry=collected.name, sales_invoice=opening.name,
                    reference="HS-COLLECTION-PROBE")
            opening_ple = (frappe.get_all("Payment Ledger Entry", filters={
                "against_voucher_type": "Sales Invoice",
                "against_voucher_no": opening.name, "delinked": 0},
                fields=["voucher_type", "voucher_no", "amount",
                    "amount_in_account_currency"],
                limit_page_length=0) if opening else [])
            doc = frappe.get_doc("HS Day Pass", name)
            listed = [row for row in erp_day_pass_view.erp_snapshot(prop.name)["day_passes"]
                if row.name == name]
            if len(listed) != 1 or not listed[0].can_return or not listed[0].historical:
                frappe.throw("La pantalla no ofrece devolver el pase trasladado")
            request = {"day_pass": name, "modified": str(doc.modified),
                "method": method if opening_due < 20 - credited else "",
                "shift": (shift if opening_due < 20 - credited and
                    not foreign_bank else ""),
                "amount": "",
                "reference": "HS-RETURN-PROBE", "reason": "Ensayo de devolución histórica"}
            try:
                frappe.set_user("Guest")
                try:
                    suite_api.erp_historical_day_pass_return_quote(
                        prop.name, canonical(request))
                except frappe.PermissionError:
                    pass
                else:
                    frappe.throw("Un usuario sin acceso revisó la devolución")
            finally:
                frappe.set_user("Administrator")
            review = suite_api.erp_historical_day_pass_return_quote(
                prop.name, canonical(request))
            accepted = {**request, "amount": review["refund_amount"],
                "acceptance": review["acceptance"]}
            key = "HS-DAY-RETURN-PROBE-" + name
            result = suite_api.execute(prop.name,
                "erp_historical_day_pass_return", key, accepted)
            retried = suite_api.execute(prop.name,
                "erp_historical_day_pass_return", key, accepted)
            if result != retried:
                frappe.throw("La devolución no tolera el reintento")
        credit = frappe.get_doc("Sales Invoice", result["credit_note"])
        refund = frappe.get_doc("HS Payment", result["refund"]) if result["refund"] else None
        day_pass = frappe.get_doc("HS Day Pass", name)
        listed_after = [row for row in erp_day_pass_view.erp_snapshot(prop.name)["day_passes"]
            if row.name == name]
        if opening:
            opening.reload()
        expected = cashier.expected(frappe.get_doc("HS Shift", shift))
        expected_credit = 20 - credited
        expected_refund = expected_credit - (opening_due - collect)
        gl = frappe.get_all("GL Entry", filters={
            "voucher_type": "Sales Invoice", "voucher_no": credit.name,
            "is_cancelled": 0}, fields=["account", "debit", "credit"],
            limit_page_length=0)
        gl_amounts = {(row.account, str(row.debit), str(row.credit)) for row in gl}
        expected_gl = {
            (prop.receivable_account, "0.0", str(float(expected_credit))),
            (income, str(float(18 - credited * 0.9)), "0.0"),
            (tax, str(float(2 - credited * 0.1)), "0.0")}
        if (credit.docstatus != 1 or credit.grand_total != -expected_credit or
                credit.outstanding_amount != 0 or
                (opening and opening.outstanding_amount != 0) or
                (refund.base_amount if refund else 0) != expected_refund or
                day_pass.status != "Cancelled" or
                day_pass.erp_return_credit_note != credit.name or
                day_pass.erp_return_refund != (refund.name if refund else None) or
                len(listed_after) != 1 or listed_after[0].can_return or
                listed_after[0].erp_return_credit_note != credit.name or
                expected[prop.currency] !=
                    f"{100 + collect - (0 if foreign_bank else expected_refund):.2f}" or
                (foreign_bank and (refund.currency != "USD" or
                    refund.amount != 0.55)) or gl_amounts != expected_gl or
                credit.name not in frappe.get_print("Sales Invoice", credit.name) or
                "PMS-RETURN-PROBE" not in credit.remarks):
            frappe.throw("La devolución histórica no concilia")
        from hospitality_suite.security import guard_cancel
        for native in (credit, *([opening] if opening else []),
                *([frappe.get_doc("Payment Entry", refund.payment_entry)]
                  if refund else [])):
            native.hs_correction_reason = "Ensayo de protección"
            try:
                guard_cancel(native)
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("Se permitió cancelar un comprobante vinculado")
        if refund:
            refund.status = "Cancelled"
            try:
                with operation(prop):
                    refund.save()
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("Se permitió alterar el reembolso histórico")
        return {"credit_total": credit.grand_total,
            "opening_outstanding": opening.outstanding_amount if opening else None,
            "credit_outstanding": credit.outstanding_amount,
            "refund_amount": refund.amount if refund else None,
            "refund_entry": refund.payment_entry if refund else None,
            "shift_expected": expected[prop.currency],
            "status": day_pass.status, "retry_same_result": True,
            "linked_cancel_blocked": True,
            "opening_ple_before": opening_ple}
    finally:
        frappe.db.rollback(save_point="hs_historical_day_pass_return_probe")
        frappe.set_user(before)
