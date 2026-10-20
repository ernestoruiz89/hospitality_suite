"""Deduplicated expiry jobs with bounded retries within one Frappe job context."""
import time

import frappe

EXPIRY_ATTEMPTS=3
EXPIRY_BACKOFF=(1,2)


class ExpiryExecutionError(RuntimeError):
    """Stop native recursive retries; Frappe must log this failure and roll back."""


def expire_holds():
    for name in frappe.get_all("HS Property", pluck="name"):
        frappe.enqueue("hospitality_suite.jobs.expire_property", property_name=name, queue="short",
                       job_id="hs-expire-" + name, deduplicate=True)


def expire_property(property_name):
    for attempt in range(1,EXPIRY_ATTEMPTS+1):
        try:
            return _expire_once(property_name)
        except (frappe.QueryDeadlockError,frappe.QueryTimeoutError,frappe.RetryBackgroundJobError,
                frappe.db.InternalError,frappe.db.OperationalError) as exc:
            retryable=isinstance(exc,(frappe.QueryDeadlockError,frappe.QueryTimeoutError,frappe.RetryBackgroundJobError)) or frappe.db.is_deadlocked(exc) or frappe.db.is_timedout(exc)
            # Reset SQL and its transaction callbacks before rereading the holds.
            # Never let execute_job recursively reinitialize/destroy this context:
            # Frappe 16.52's recursive finally can lose local.job after a retry.
            frappe.db.rollback()
            if not retryable or attempt==EXPIRY_ATTEMPTS:
                raise ExpiryExecutionError(frappe._('La caducidad de retenciones no pudo completarse; revise Error Log y vuelva a ejecutar el trabajo después de corregir la causa')) from exc
            time.sleep(EXPIRY_BACKOFF[attempt-1])


def _expire_once(property_name):
    from hospitality_suite.service import lock_property, operation
    from hospitality_suite.availability import expire_locked
    from hospitality_suite.security import realtime
    with operation():
        prop = lock_property(property_name)
        count = expire_locked(prop)
        if count:
            realtime(prop.name)
    return count
