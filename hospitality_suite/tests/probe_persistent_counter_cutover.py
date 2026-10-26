"""Inspect the disposable PMS counter-sale cutover and its historical documents."""

from decimal import Decimal

import frappe

from hospitality_suite import api, cashier, pms_cutover_activation, pms_cutover_cli
from hospitality_suite.standalone_accounting import provider


SITE = "hs-erp-smoke-persistent.local"
REFERENCE = "HS-PERSISTENT-DAY-PASS-20261026"
MAPPING_FILE = "cutover-day-pass-mapping.json"
BACKUP_FILE = "persistent-counter-final-backup-manifest.json"
SOURCE_SHA256 = "9a20d3c517bc01b9da5d53438086c5c3b2c1dccc4ebd45ad049a7fe04aa760e4"
MAPPING_SHA256 = "b3632b53976073808e5a4af542286755d7fb9820334bb543350053ccc9ad5b7d"
PLAN_SHA256 = "8966d744efaf156ff319b470464262b0024e18aca4fe44c6f2acda39991e00a2"
LINK_SHA256 = "2a5e4c664d6eaad346ffb5d2843f1f1449b5802c656302a077d791401f28467c"
BACKUP_SHA256 = "b2c6d695b5b23ff91d60924e49ebe8cc9f0762d40b81860944757422346f2f0f"
SALE = "SER-2026-00001"
RETURNED_SALE = "SER-2026-00002"


def rehearse():
    if frappe.local.site != SITE or provider() != "pms":
        frappe.throw("Use only the isolated PMS cutover source")
    frappe.set_user("Administrator")
    reviewed = pms_cutover_cli.review_file(MAPPING_FILE)
    if not reviewed["ready"]:
        frappe.throw("The persistent source is not ready for rehearsal")
    mapping = pms_cutover_cli._json_file(MAPPING_FILE)
    result = pms_cutover_activation.rehearse_activation(mapping,
        source_sha256=reviewed["source_sha256"],
        plan_sha256=reviewed["plan_sha256"],
        link_sha256=reviewed["link_sha256"],
        migration_reference=REFERENCE)
    if (not result["activation_rehearsed"] or provider() != "pms" or
            frappe.db.count("HS Cutover Run")):
        frappe.throw("The rehearsal left a persistent cutover")
    return {"activation_rehearsed": True, "provider": provider(),
        "property_count": len(result.get("properties") or []),
        "source_sha256": reviewed["source_sha256"],
        "mapping_sha256": reviewed["mapping_sha256"],
        "plan_sha256": reviewed["plan_sha256"],
        "link_sha256": reviewed["link_sha256"]}


def activate():
    if frappe.local.site != SITE:
        frappe.throw("Use only the isolated persistent cutover site")
    frappe.set_user("Administrator")
    return pms_cutover_cli.activate_file(MAPPING_FILE, BACKUP_FILE,
        source_sha256=SOURCE_SHA256, mapping_sha256=MAPPING_SHA256,
        plan_sha256=PLAN_SHA256, link_sha256=LINK_SHA256,
        backup_sha256=BACKUP_SHA256, migration_reference=REFERENCE)


def pending_jobs():
    if frappe.local.site != SITE:
        frappe.throw("Use only the isolated persistent cutover site")
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
    """Finish the single known website index job created while cloning."""
    if frappe.local.site != SITE:
        frappe.throw("Use only the isolated persistent cutover site")
    rows = pending_jobs()
    if (len(rows) != 1 or rows[0]["queue"] != "long" or
            rows[0]["status"] != "queued" or rows[0]["kwargs"] != {} or
            rows[0]["method"] !=
                "frappe.search.website_search.build_index_for_all_routes"):
        frappe.throw("The pending jobs differ from the known clone index job")
    from frappe.utils.background_jobs import get_queue

    queue = get_queue("long")
    job = queue.fetch_job(rows[0]["job_id"])
    if (not job or job.get_status() != "queued" or
            job.kwargs.get("site") != SITE or
            job.kwargs.get("kwargs") != {}):
        frappe.throw("The clone index job changed")
    frappe.get_attr(rows[0]["method"])()
    frappe.db.commit()
    queue.remove(job)
    job.delete()
    if pending_jobs():
        frappe.throw("The clone still has pending jobs")
    return {"site": SITE, "completed": rows[0]["method"]}


def inspect():
    if frappe.local.site != SITE or provider() != "erpnext":
        frappe.throw("Use only the isolated committed cutover site")
    frappe.set_user("Administrator")
    runs = frappe.get_all("HS Cutover Run", fields=["name",
        "migration_reference", "result_json"], limit_page_length=0)
    if len(runs) != 1 or runs[0].migration_reference != REFERENCE:
        frappe.throw("The committed cutover has an unexpected receipt")
    receipt = frappe.parse_json(runs[0].result_json)
    if receipt.get("backup", {}).get("sha256") != BACKUP_SHA256:
        frappe.throw("The receipt lost its frozen backup")
    sale = frappe.get_doc("HS Service Request", SALE)
    returned = frappe.get_doc("HS Service Request", RETURNED_SALE)
    if (sale.property != returned.property or sale.status != "Delivered" or
            returned.status != "Returned" or sale.folio or returned.folio):
        frappe.throw("The direct sales changed property, state, or scope")
    property_name = sale.property
    history = api.pms_direct_sale_history(property_name,
        search="HIST-", page_length=25)
    if {row["name"] for row in history["rows"]} != {SALE, RETURNED_SALE}:
        frappe.throw("The ERPNext view lost historical PMS counter sales")
    try:
        api.pms_direct_sale_history(property_name, returnable=1)
    except frappe.ValidationError:
        pass
    else:
        frappe.throw("The ERPNext view offered a PMS sale as natively returnable")
    invoice = frappe.get_doc("HS PMS Fiscal Document", sale.pms_fiscal_invoice)
    returned_invoice = frappe.get_doc("HS PMS Fiscal Document",
        returned.pms_fiscal_invoice)
    credit = frappe.get_doc("HS PMS Fiscal Document", returned.pms_fiscal_credit)
    for row in (sale, returned):
        if (not frappe.db.exists("Customer", row.customer) or
                not frappe.db.exists("Item", row.item) or
                not frappe.db.exists("HS Party", row.pms_party) or
                not frappe.db.exists("HS Product", row.pms_product) or
                row.sales_invoice or row.credit_note or not row.pms_receivable):
            frappe.throw("A historical direct sale lost its native or PMS link")
        receivable = frappe.get_doc("HS PMS Receivable", row.pms_receivable)
        if (receivable.source_service != row.name or
                Decimal(str(receivable.amount)) != Decimal("8")):
            frappe.throw("The PMS direct-sale receivable changed")
    if (invoice.document_type != "Invoice" or
            returned_invoice.document_type != "Invoice" or
            credit.document_type != "Credit Note" or
            credit.source_invoice != returned_invoice.name or
            any(Decimal(str(doc.total_amount)) != Decimal("8") or
                doc.status != "Posted" for doc in
                (invoice, returned_invoice, credit))):
        frappe.throw("The historical fiscal documents do not reconcile")
    for doc in (invoice, returned_invoice, credit):
        archive = api.pms_fiscal_archive(property_name,
            search=doc.document_number)
        if (not any(row.name == doc.name for row in archive["documents"]) or
                doc.document_number not in frappe.get_print(
                    "HS PMS Fiscal Document", doc.name,
                    print_format="HS Documento fiscal PMS")):
            frappe.throw("The historical fiscal document is not archived or printable")
    direct_payments = frappe.get_all("HS Payment",
        filters={"service": ["in", [sale.name, returned.name]]},
        fields=["name", "service", "kind", "status", "amount", "shift",
            "payment_entry"], limit_page_length=0)
    by_service = {name: [row for row in direct_payments if row.service == name]
        for name in (sale.name, returned.name)}
    if (len(by_service[sale.name]) != 1 or
            len(by_service[returned.name]) != 1 or
            any(row.status != "Posted" or row.kind != "Payment" or
                row.payment_entry or Decimal(str(row.amount)) != Decimal("8")
                for row in direct_payments)):
        frappe.throw("The historical counter payments changed")
    shift_names = {row.shift for row in direct_payments}
    if len(shift_names) != 1:
        frappe.throw("The historical counter payments changed shifts")
    shift = frappe.get_doc("HS Shift", shift_names.pop())
    refunds = frappe.get_all("HS Payment",
        filters={"source_payment": by_service[returned.name][0].name},
        fields=["name", "kind", "status", "amount", "shift",
            "payment_entry"], limit_page_length=0)
    if (len(refunds) != 1 or refunds[0].kind != "Refund" or
            refunds[0].status != "Posted" or refunds[0].payment_entry or
            refunds[0].shift != shift.name or
            Decimal(str(refunds[0].amount)) != Decimal("8")):
        frappe.throw("The returned counter sale lost its refund")
    expected = cashier.expected(shift)
    if expected.get("NIO") != "8.00":
        frappe.throw("The historical cash drawer no longer reconciles")
    closes = frappe.get_all("HS Daily Close",
        filters={"property": property_name, "status": "Closed"},
        fields=["name", "summary"], limit_page_length=0)
    if len(closes) != 1:
        frappe.throw("The historical daily close changed")
    snapshot = frappe.parse_json(closes[0].summary)
    sources = snapshot.get("sources") or {}
    if (not {sale.pms_receivable, returned.pms_receivable} <=
            {row["name"] for row in sources.get("receivables", [])} or
            not {invoice.name, returned_invoice.name, credit.name} <=
            {row["name"] for row in sources.get("fiscal_documents", [])} or
            not {row.name for row in direct_payments + refunds} <=
            {row["name"] for row in sources.get("payments", [])}):
        frappe.throw("The historical daily-close snapshot lost the counter sale")
    return {"persistent_counter_cutover_verified": True,
        "provider": provider(), "cutover_run": runs[0].name,
        "sale": sale.name, "returned_sale": returned.name,
        "historical_invoice": invoice.document_number,
        "historical_credit": credit.document_number,
        "cash_expected_nio": expected["NIO"],
        "daily_close": closes[0].name,
        "payment_count": len(direct_payments) + len(refunds),
        "backup_sha256": BACKUP_SHA256}
