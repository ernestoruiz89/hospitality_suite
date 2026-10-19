import frappe


def before_tests():
    site=frappe.local.site
    if not frappe.conf.allow_tests or not (site.endswith(".localhost") or "test" in site):
        frappe.throw("La batería de integración requiere un sitio de pruebas explícito")
    from hospitality_suite.demo import seed
    previous=frappe.conf.get("hospitality_allow_demo")
    frappe.conf.hospitality_allow_demo=True
    try:
        seed()
    finally:
        frappe.conf.hospitality_allow_demo=previous
