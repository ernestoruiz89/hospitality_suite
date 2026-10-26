"""Exercise a committed PMS counter-sale return on an isolated restored site."""

from decimal import Decimal
from hashlib import sha256

import frappe

from hospitality_suite import api, cashier, pms_cutover_activation, pms_cutover_backup, pms_cutover_cli
from hospitality_suite.service import canonical
from hospitality_suite.standalone_accounting import provider


SITE = "hs-erp-smoke-direct-return.local"
SALE = "SER-2026-00001"
MAPPING_FILE = "cutover-day-pass-mapping.json"
BACKUP_FILE = "direct-return-final-backup-manifest.json"
REFERENCE = "HS-PERSISTENT-DIRECT-RETURN-20261026"
RETURN_KEY = "persistent-direct-return-20261026"
SHIFT_KEY = "persistent-direct-return-shift-20261026"


def _site(expected_provider):
    if frappe.local.site != SITE or provider() != expected_provider:
        frappe.throw("Use only the isolated direct-return cutover site")
    frappe.set_user("Administrator")
    sale = frappe.get_doc("HS Service Request", SALE)
    if sale.status != "Delivered" or sale.stay or sale.folio:
        frappe.throw("The synthetic PMS counter sale is not available")
    return sale


def pending_jobs():
    if frappe.local.site != SITE:
        frappe.throw("Use only the isolated direct-return cutover site")
    from frappe.utils.background_jobs import get_queue, get_queue_list

    rows = []
    for queue_name in get_queue_list():
        for job in get_queue(queue_name).jobs:
            if job.kwargs.get("site") != SITE:
                continue
            method = job.kwargs.get("method")
            rows.append({"queue": queue_name, "job_id": job.id,
                "method": method if isinstance(method, str) else
                    f"{method.__module__}.{method.__qualname__}",
                "kwargs": job.kwargs.get("kwargs"),
                "status": job.get_status()})
    return rows


def drain_index_job():
    _site("pms")
    jobs = pending_jobs()
    if not jobs:
        return {"pending_jobs": 0}
    if (len(jobs) != 1 or jobs[0]["queue"] != "long" or
            jobs[0]["status"] != "queued" or jobs[0]["kwargs"] != {} or
            jobs[0]["method"] !=
                "frappe.search.website_search.build_index_for_all_routes"):
        frappe.throw("The clone has unexpected background work")
    from frappe.utils.background_jobs import get_queue

    job = get_queue("long").fetch_job(jobs[0]["job_id"])
    if not job or job.get_status() != "queued":
        frappe.throw("The clone index job changed")
    frappe.get_attr(jobs[0]["method"])()
    frappe.db.commit()
    get_queue("long").remove(job)
    job.delete()
    if pending_jobs():
        frappe.throw("The clone still has pending jobs")
    return {"completed": jobs[0]["method"], "pending_jobs": 0}


def review_and_rehearse():
    sale = _site("pms")
    reviewed = pms_cutover_cli.review_file(MAPPING_FILE)
    if not reviewed["ready"] or any(reviewed[key] for key in (
            "mapping_blockers", "source_blockers", "plan_blockers",
            "link_blockers")):
        frappe.throw("The restored PMS source has cutover blockers: " +
            frappe.as_json(reviewed))
    mapping = pms_cutover_cli._json_file(MAPPING_FILE)
    result = pms_cutover_activation.rehearse_activation(mapping,
        source_sha256=reviewed["source_sha256"],
        plan_sha256=reviewed["plan_sha256"],
        link_sha256=reviewed["link_sha256"],
        migration_reference=REFERENCE)
    if (not result["activation_rehearsed"] or provider() != "pms" or
            frappe.db.count("HS Cutover Run") or
            frappe.db.get_value("HS Service Request", sale.name,
                "erp_cutover_snapshot")):
        frappe.throw("The rehearsal did not restore the PMS source")
    return {"rehearsed": True, "source_sha256": reviewed["source_sha256"],
        "plan_sha256": reviewed["plan_sha256"],
        "link_sha256": reviewed["link_sha256"]}


def prepare_backup():
    _site("pms")
    if pending_jobs():
        frappe.throw("The clone still has pending jobs")
    return pms_cutover_cli.prepare_backup_file(BACKUP_FILE)


def activate():
    _site("pms")
    reviewed = pms_cutover_cli.review_file(MAPPING_FILE)
    if not reviewed["ready"]:
        frappe.throw("The PMS source changed after rehearsal")
    manifest = pms_cutover_cli._json_file(BACKUP_FILE)
    backup_sha256 = pms_cutover_backup.verify(manifest)["sha256"]
    args = {key: reviewed[key] for key in (
        "source_sha256", "mapping_sha256", "plan_sha256", "link_sha256")}
    args.update(backup_sha256=backup_sha256, migration_reference=REFERENCE)
    first = pms_cutover_cli.activate_file(MAPPING_FILE, BACKUP_FILE, **args)
    second = pms_cutover_cli.activate_file(MAPPING_FILE, BACKUP_FILE, **args)
    sale = frappe.get_doc("HS Service Request", SALE)
    if (first != second or provider() != "erpnext" or
            frappe.db.count("HS Cutover Run") != 1 or
            not sale.erp_cutover_snapshot or
            sha256(sale.erp_cutover_snapshot.encode()).hexdigest() !=
                sale.erp_cutover_sha256):
        frappe.throw("The committed direct-sale cutover did not freeze its proof")
    return {**first, "replay_identical": True,
        "sale_proof_sha256": sale.erp_cutover_sha256}


def return_sale():
    sale = _site("erpnext")
    if sale.credit_note or sale.erp_return_refund or not sale.erp_cutover_snapshot:
        frappe.throw("The historical sale was already returned or has no proof")
    eligible = api.pms_direct_sale_history(sale.property, returnable=1)
    if [row["name"] for row in eligible["rows"]] != [sale.name]:
        frappe.throw("The historical sale is not eligible in React")
    method = frappe.db.get_value("HS Payment", {
        "service": sale.name, "kind": "Payment", "status": "Posted"},
        "method")
    if not method or not frappe.db.get_value("HS Payment Method", method,
            "is_cash"):
        frappe.throw("The synthetic source payment is not in cash")
    opened = api.execute(sale.property, "open_shift", SHIFT_KEY,
        {"currency": sale.currency, "opening_amount": "100"})
    request = {"service": sale.name, "modified": str(sale.modified),
        "method": method, "shift": opened["shift"],
        "reference": "PERSISTENT-PMS-DIRECT-RETURN",
        "reason": "Devolución persistente de venta PMS sintética"}
    quote = api.erp_historical_direct_sale_return_quote(
        sale.property, canonical(request))
    submitted = {**request, "acceptance": quote["acceptance"]}
    first = api.execute(sale.property, "erp_historical_direct_sale_return",
        RETURN_KEY, submitted)
    second = api.execute(sale.property, "erp_historical_direct_sale_return",
        RETURN_KEY, submitted)
    sale.reload()
    shift = frappe.get_doc("HS Shift", opened["shift"])
    if (first != second or sale.status != "Returned" or
            sale.credit_note != first["credit_note"] or
            sale.erp_return_refund != first["refund"] or
            cashier.expected(shift).get(sale.currency) != "92.00"):
        frappe.throw("The committed historical return did not reconcile")
    frappe.db.commit()
    return {"returned": sale.name, "credit_note": sale.credit_note,
        "refund": sale.erp_return_refund, "shift": shift.name,
        "cash_expected": cashier.expected(shift).get(sale.currency),
        "retry_identical": True}


def inspect_return():
    if frappe.local.site != SITE or provider() != "erpnext":
        frappe.throw("Use only the isolated committed cutover site")
    frappe.set_user("Administrator")
    sale = frappe.get_doc("HS Service Request", SALE)
    proof = frappe.parse_json(sale.erp_cutover_snapshot)
    credit = frappe.get_doc("Sales Invoice", sale.credit_note)
    refund = frappe.get_doc("HS Payment", sale.erp_return_refund)
    payment = frappe.get_doc("Payment Entry", refund.payment_entry)
    fiscal = frappe.get_doc("HS PMS Fiscal Document", sale.pms_fiscal_invoice)
    if (frappe.db.count("HS Cutover Run") != 1 or
            sha256(sale.erp_cutover_snapshot.encode()).hexdigest() !=
                sale.erp_cutover_sha256 or
            sale.status != "Returned" or sale.pms_fiscal_credit or
            fiscal.document_number != proof["document_number"] or
            credit.docstatus != 1 or not credit.is_return or
            Decimal(str(credit.grand_total)) != -8 or
            refund.source_payment != proof["source_payment"] or
            refund.sales_invoice != credit.name or
            payment.docstatus != 1 or
            payment.references[0].reference_name != credit.name or
            api.pms_direct_sale_history(sale.property, returnable=1)["rows"] or
            not any(row["name"] == sale.name and
                    row["native_credit_note"] == credit.name for row in
                    api.pms_direct_sale_history(sale.property)["rows"]) or
            fiscal.document_number not in frappe.get_print(
                "HS PMS Fiscal Document", fiscal.name,
                print_format="HS Documento fiscal PMS")):
        frappe.throw("The committed historical return lost its fiscal or ledger trail")
    return {"persistent_direct_return_verified": True,
        "cutover_run": frappe.db.get_value("HS Cutover Run", {}, "name"),
        "fiscal_invoice": fiscal.document_number,
        "native_credit_note": credit.name, "refund": refund.name,
        "original_payment": proof["source_payment"]}
