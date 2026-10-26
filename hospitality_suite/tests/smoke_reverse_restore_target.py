"""Read-only check that the pre-cutover PMS backup restores without an acta."""

import frappe
from datetime import timedelta
from uuid import uuid4


def verify():
    if frappe.local.site != "hs-pms-smoke-reverse-restore.local":
        frappe.throw("Use únicamente el sitio de restauración aislado")
    frappe.set_user("Administrator")
    mode = frappe.get_single("HS Site Mode")
    counts = {doctype: frappe.db.count(doctype) for doctype in (
        "HS Property", "HS Account", "HS Historical Fiscal Document",
        "HS Folio", "HS Journal", "HS ERP to PMS Cutover Run")}
    if (mode.provider != "PMS" or mode.migration_reference or
            counts["HS Property"] < 2 or counts["HS Account"] < 2 or
            counts["HS Historical Fiscal Document"] < 2 or
            counts["HS Folio"] or counts["HS Journal"] or
            counts["HS ERP to PMS Cutover Run"]):
        frappe.throw("El respaldo anterior al corte no restauró su estado")
    return {"restored": True, "provider": mode.provider,
            "migration_reference": None, "counts": counts}


def verify_continuity():
    """Exercise ordinary PMS reservation and ledger commands, then roll back."""
    baseline = verify()
    from hospitality_suite import api
    from hospitality_suite.time import now_local

    property_name = frappe.db.get_value("HS Historical Fiscal Document", {},
                                        "property")
    prop = frappe.get_doc("HS Property", property_name)
    room = frappe.db.get_value("HS Room", {"property": prop.name, "active": 1},
                               ["name", "category"], as_dict=True)
    guest = frappe.db.get_value("HS Guest", {"property": prop.name},
                                ["name", "customer"], as_dict=True)
    product = frappe.db.get_value("HS Product", {"property": prop.name,
        "product_type": "Service", "active": 1}, "name")
    receivable = frappe.db.get_value("HS Account", {"property": prop.name,
        "organization": prop.organization, "account_type": "Receivable",
        "active": 1, "is_group": 0}, "name")
    method = frappe.db.get_value("HS Payment Method", {"property": prop.name,
        "is_cash": 0}, "name")
    expense = frappe.db.get_value("HS Account", {"property": prop.name,
        "organization": prop.organization, "root_type": "Expense", "active": 1,
        "is_group": 0}, "name")
    income = frappe.db.get_value("HS Account", {"property": prop.name,
        "organization": prop.organization, "root_type": "Income", "active": 1,
        "is_group": 0}, "name")
    if not all((room, guest, product, receivable, method, expense, income)):
        frappe.throw("El respaldo no conserva los maestros operativos del hotel")
    before_bookings = frappe.db.count("HS Booking", {"property": prop.name})
    before_closes = frappe.db.count("HS Daily Close", {"property": prop.name})
    before_day = str(prop.business_date)
    suffix = uuid4().hex
    start = (now_local(prop) - timedelta(minutes=1)).replace(microsecond=0)
    reservation = {"starts_at": str(start), "ends_at": str(start + timedelta(days=1)),
        "guest": guest.name, "customer": guest.customer,
        "rooms": [{"category": room.category, "room": room.name, "people": 1}]}
    frappe.db.savepoint("hs_reverse_restore_continuity")
    try:
        board = api.setup_board(prop.name)
        if not any(row["name"] == room.name for row in board["rooms"]):
            frappe.throw("La habitación restaurada no aparece en Configuración")
        api.save_setup(prop.name, "property", {"lodging_item": product},
                       "restore-lodging-item-" + suffix,
                       expected_modified=str(board["property"]["modified"]))
        quote = api.preview(prop.name, reservation, "reserve")
        booking = api.execute(prop.name, "reserve", "restore-booking-" + suffix,
                              {**reservation, "acceptance": quote["acceptance"]})
        if (not frappe.db.exists("HS Booking", booking["booking"]) or
                api.execute(prop.name, "reserve", "restore-booking-" + suffix,
                            {**reservation, "acceptance": quote["acceptance"]}) != booking):
            frappe.throw("La reserva posterior a la restauración no concilia")
        arrival_quote = api.preview(prop.name, {"booking": booking["booking"]},
                                    "check_in")
        arrived = api.execute(prop.name, "check_in", "restore-arrival-" + suffix,
            {"booking": booking["booking"], "modified": booking["modified"],
             "guest": guest.name, "timing_acceptance": arrival_quote["acceptance"]})
        if not frappe.db.exists("HS Folio", arrived["folio"]):
            frappe.throw("La entrada posterior a la restauración no creó folio")
        folio_data = {"folio": arrived["folio"], "receivable_account": receivable}
        bill_quote = api.pms_folio_quote(prop.name, folio_data)
        bill = api.execute(prop.name, "pms_bill_folio", "restore-bill-" + suffix,
                           {**folio_data, "acceptance": bill_quote["acceptance"]})
        claim = bill["receivables"][0]["receivable"]
        series = api.execute(prop.name, "pms_fiscal_series",
            "restore-series-" + suffix,
            {"series_code": "REST" + suffix[:8] + "-", "document_type": "Invoice",
             "start_number": 1, "end_number": 5, "padding": 4})["series"]
        invoice_data = {"series": series, "receivables": [claim]}
        invoice_quote = api.pms_invoice_quote(prop.name, invoice_data)
        invoice = api.execute(prop.name, "pms_issue_invoice",
            "restore-invoice-" + suffix,
            {**invoice_data, "acceptance": invoice_quote["acceptance"]})
        if (not frappe.db.exists("HS PMS Fiscal Document", invoice["document"]) or
                api.execute(prop.name, "pms_issue_invoice",
                            "restore-invoice-" + suffix,
                            {**invoice_data,
                             "acceptance": invoice_quote["acceptance"]}) != invoice):
            frappe.throw("La factura posterior a la restauración no quedó archivada")
        printed = frappe.get_print("HS PMS Fiscal Document", invoice["document"],
                                   print_format="HS Documento fiscal PMS")
        if invoice["document_number"] not in printed:
            frappe.throw("La factura posterior a la restauración no se pudo imprimir")
        payment_data = {"kind": "Payment", "amount": str(bill["total"]),
                        "method": method, "receivable": claim,
                        "reference": "RESTORE-PAY-" + suffix,
                        "reason": "Ensayo reversible de cobro"}
        payment = api.execute(prop.name, "pms_cash_movement",
                              "restore-payment-" + suffix, payment_data)
        from hospitality_suite.standalone_receivables import outstanding
        if (not frappe.db.exists("HS Payment", payment["payment"]) or
                not frappe.db.exists("HS Journal", payment["journal"]) or
                outstanding(prop, claim) or
                api.execute(prop.name, "pms_cash_movement",
                            "restore-payment-" + suffix, payment_data) != payment):
            frappe.throw("El cobro posterior a la restauración no liquidó la cuenta")
        journal = api.execute(prop.name, "pms_manual_journal",
            "restore-journal-" + suffix,
            {"reference": "RESTORE-" + suffix, "reason": "Ensayo reversible de continuidad",
             "lines": [{"account": expense, "debit": "1.00", "credit": "0"},
                       {"account": income, "debit": "0", "credit": "1.00"}]})
        if (not frappe.db.exists("HS Journal", journal["journal"]) or
                api.execute(prop.name, "pms_manual_journal",
                            "restore-journal-" + suffix,
                            {"reference": "RESTORE-" + suffix,
                             "reason": "Ensayo reversible de continuidad",
                             "lines": [{"account": expense, "debit": "1.00", "credit": "0"},
                                       {"account": income, "debit": "0", "credit": "1.00"}]}) != journal):
            frappe.throw("El asiento posterior a la restauración no concilia")
        shift = api.execute(prop.name, "pms_open_shift",
            "restore-shift-" + suffix,
            {"opening_by_currency": {prop.currency: "0.00"}})["shift"]
        blocked = api.pms_close_preview(prop.name)
        if not any(row["type"] == "Turnos sin arquear" for row in blocked["blockers"]):
            frappe.throw("El cierre no detectó el turno sin arquear")
        api.execute(prop.name, "pms_close_shift", "restore-shift-close-" + suffix,
            {"shift": shift, "counted_by_currency": {prop.currency: "0.00"}})
        close_review = api.pms_close_preview(prop.name)
        if close_review["blockers"]:
            frappe.throw("El recorrido restaurado dejó pendientes de cierre")
        closed = api.execute(prop.name, "pms_daily_close",
            "restore-close-" + suffix,
            {"review_acceptance": close_review["review_acceptance"],
             "reason": "Ensayo reversible de cierre restaurado"})
        saved = api.pms_close_detail(prop.name, closed["close"])
        sources = saved["snapshot"]["sources"]
        if (saved["snapshot"] != close_review["snapshot"] or
                not any(row["name"] == invoice["document"] for row in
                        sources["fiscal_documents"]) or
                not any(row["name"] == payment["payment"] for row in
                        sources["payments"]) or
                not any(row["name"] == journal["journal"] for row in
                        sources["journals"]) or
                not any(row["name"] == shift for row in sources["closed_shifts"])):
            frappe.throw("El cierre restaurado no congeló los movimientos")
        result = {"restored": baseline["restored"], "reservation_created": True,
                  "arrival_registered": True, "folio_billed": True,
                  "invoice_issued": True, "invoice_printed": True,
                  "bank_payment_settled": True,
                  "journal_posted": True, "cash_shift_reconciled": True,
                  "daily_close_frozen": True,
                  "idempotent_retries": True,
                  "historical_fiscal_documents": baseline["counts"]["HS Historical Fiscal Document"]}
    finally:
        frappe.db.rollback(save_point="hs_reverse_restore_continuity")
    if (frappe.db.count("HS Booking", {"property": prop.name}) != before_bookings or
            frappe.db.count("HS Daily Close", {"property": prop.name}) != before_closes or
            str(frappe.db.get_value("HS Property", prop.name,
                                    "business_date")) != before_day or
            verify()["counts"] != baseline["counts"]):
        frappe.throw("El ensayo de continuidad dejó datos de prueba")
    return {**result, "rolled_back": True}
