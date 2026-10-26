"""Inspect queued background work on the two isolated reverse-cutover clones."""

import frappe

from frappe.utils.background_jobs import get_queue, get_queue_list


SITES = {
    "hs-erp-smoke-reverse.local": "hs_erp_reverse_source",
    "hs-erp-smoke-reverse-partial.local": "hs_erp_reverse_partial",
    "hs-pms-smoke-real-reverse.local": "hs_pms_real_reverse",
    "hs-pms-smoke-reverse-partial.local": "hs_pms_reverse_partial",
}
METHODS = {"frappe.model.delete_doc.delete_dynamic_links",
    "frappe.search.website_search.build_index_for_all_routes"}
DELETED_SETTERS = {
    "Sales Order-tax_id-hidden", "Sales Order-tax_id-print_hide",
    "Sales Invoice-tax_id-hidden", "Sales Invoice-tax_id-print_hide",
    "Delivery Note-tax_id-hidden", "Delivery Note-tax_id-print_hide",
    "Packed Item-rate-read_only",
    "Sales Invoice Item-discount_account-hidden",
    "Sales Invoice Item-discount_account-mandatory_depends_on",
    "Sales Invoice-additional_discount_account-hidden",
    "Sales Invoice-additional_discount_account-mandatory_depends_on",
}


def inspect():
    site = frappe.local.site
    if SITES.get(site) != frappe.local.conf.get("db_name"):
        frappe.throw("Solo se permiten clones aislados del corte inverso")
    jobs = []
    for queue_name in get_queue_list():
        queue = get_queue(queue_name)
        for job in queue.jobs:
            if job.kwargs.get("site") != site:
                continue
            method = job.kwargs.get("method")
            jobs.append({"queue": queue_name, "job_id": job.id,
                "method": method if isinstance(method, str) else
                    f"{method.__module__}.{method.__qualname__}",
                "kwargs": job.kwargs.get("kwargs"),
                "status": job.get_status()})
    return jobs


def _allowed(row):
    method = row["method"]
    kwargs = row["kwargs"]
    if row["status"] != "queued" or method not in METHODS:
        return False
    if method == "frappe.model.delete_doc.delete_dynamic_links":
        return (row["queue"] == "default" and isinstance(kwargs, dict) and
                set(kwargs) == {"doctype", "name"} and
                kwargs["doctype"] == "Property Setter" and
                kwargs["name"] in DELETED_SETTERS)
    return row["queue"] == "long" and kwargs == {}


def run():
    """Execute only known clone setup jobs before removing their queue entries."""
    pending = inspect()
    if not all(_allowed(row) for row in pending):
        frappe.throw("La cola contiene un trabajo ajeno al ensayo")
    completed = []
    for row in pending:
        queue = get_queue(row["queue"])
        job = queue.fetch_job(row["job_id"])
        if (not job or job.get_status() != "queued" or
                job.kwargs.get("site") != frappe.local.site or
                job.kwargs.get("kwargs") != row["kwargs"]):
            frappe.throw("El trabajo cambió durante la revisión")
        method = job.kwargs["method"]
        actual = method if isinstance(method, str) else (
            f"{method.__module__}.{method.__qualname__}")
        if actual != row["method"]:
            frappe.throw("Cambió el método del trabajo")
        if isinstance(method, str):
            method = frappe.get_attr(method)
        method(**row["kwargs"])
        frappe.db.commit()
        queue.remove(job)
        job.delete()
        completed.append(row["method"])
    from frappe.utils.doctor import any_job_pending
    if any_job_pending(frappe.local.site):
        frappe.throw("Quedan trabajos pendientes para el clon")
    return {"site": frappe.local.site, "completed": completed}
