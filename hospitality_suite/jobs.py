"""Scheduler dispatches one transactional job per property; failures remain in RQ logs."""
import frappe


def expire_holds():
    for name in frappe.get_all("HS Property", pluck="name"):
        frappe.enqueue("hospitality_suite.jobs.expire_property", property_name=name, queue="short",
                       job_id="hs-expire-" + name, deduplicate=True)


def expire_property(property_name):
    from hospitality_suite.service import lock_property, operation
    from hospitality_suite.availability import expire_locked
    from hospitality_suite.security import realtime
    with operation():
        prop = lock_property(property_name)
        count = expire_locked(prop)
        if count:
            realtime(prop.name)
    return count
