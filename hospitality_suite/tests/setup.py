import frappe


def before_tests():
    site=frappe.local.site
    if not frappe.conf.allow_tests or not (site.endswith(".localhost") or "test" in site):
        frappe.throw("La batería de integración requiere un sitio de pruebas explícito")
    if not frappe.conf.get("hospitality_integration_test_site"):
        frappe.throw("Designe un sitio vacío con hospitality_integration_test_site antes de ejecutar esta batería")
    # Fail before seeding or creating documents if infrastructure or the initial
    # fixture is unavailable. A demo/UX site is not the test suite's baseline.
    frappe.cache.ping()
    from frappe.utils.background_jobs import get_redis_conn
    get_redis_conn().ping()
    if any(frappe.db.count(dt) for dt in ("HS Stay","HS Booking","HS Charge","HS Payment","HS Shift","HS Daily Close")):
        frappe.throw("El sitio contiene operaciones; use un sitio de integración vacío o restaure su respaldo inicial")
    from hospitality_suite.demo import seed
    previous=frappe.conf.get("hospitality_allow_demo")
    frappe.conf.hospitality_allow_demo=True
    try:
        seed()
    finally:
        frappe.conf.hospitality_allow_demo=previous
