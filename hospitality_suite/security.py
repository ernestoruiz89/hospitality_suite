"""Authorization is enforced before every query/mutation, including direct REST access."""
import frappe
from frappe import _

from hospitality_suite.schema import SCOPED, MANAGERS

ACTIONS = {
    "setup": MANAGERS, "reserve": MANAGERS + ["HS Receptionist"],
    "stay": MANAGERS + ["HS Receptionist"],
    "finance": MANAGERS + ["HS Cashier", "HS Accountant"],
    "clean": MANAGERS + ["HS Housekeeping"], "inspect": MANAGERS,
    "maintain": MANAGERS + ["HS Maintenance"],
    "service": MANAGERS + ["HS Receptionist", "HS Cashier"],
    "report": MANAGERS + ["HS Accountant", "HS Auditor"], "approve": MANAGERS[:2],
    "guest": MANAGERS + ["HS Receptionist"],
}


def is_system(user=None):
    user = user or frappe.session.user
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def allowed_properties(user=None):
    user = user or frappe.session.user
    if user == "Guest":
        return []
    if is_system(user):
        return frappe.get_all("HS Property", pluck="name")
    rows = frappe.get_all("HS Access", filters={"user": user}, fields=["property", "company"])
    return [r.property for r in rows if frappe.db.get_value("HS Property", r.property, "company") == r.company]


def require(property_name, action=None):
    if frappe.session.user == "Guest" or property_name not in allowed_properties():
        frappe.throw(_("No tiene acceso a este establecimiento"), frappe.PermissionError)
    if action and not is_system() and not set(ACTIONS[action]).intersection(frappe.get_roles()):
        frappe.throw(_("No tiene permiso para esta operación"), frappe.PermissionError)
    return frappe.get_doc("HS Property", property_name)


def document(dt, name, action=None):
    doc = frappe.get_doc(dt, name)
    require(doc.name if dt == "HS Property" else doc.property, action)
    doc.check_permission("read")
    return doc


def has_scope_permission(doc, user=None, permission_type=None, **kwargs):
    prop = doc.name if doc.doctype == "HS Property" else doc.get("property")
    if not prop or prop not in allowed_properties(user):
        return False
    return None  # Frappe's role permissions remain authoritative as well.


def scope_query(dt, user=None):
    props = allowed_properties(user)
    if not props:
        return "1=0"
    field = "name" if dt == "HS Property" else "property"
    names = ",".join(frappe.db.escape(v) for v in props)
    return f"`tab{dt}`.`{field}` IN ({names})"


for _dt in SCOPED:
    globals()["query_" + _dt.lower().replace(" ", "_")] = lambda user=None, dt=_dt: scope_query(dt, user)


def validate_file(doc, method=None):
    if doc.attached_to_doctype and doc.attached_to_doctype.startswith("HS "):
        target = document(doc.attached_to_doctype, doc.attached_to_name)
        if not doc.is_private:
            frappe.throw(_("Los archivos de Hospitality Suite deben ser privados"))
        target.check_permission("write")


def realtime(property_name):
    users = frappe.get_all("HS Access", filters={"property": property_name}, pluck="user")
    users.append("Administrator")
    for user in set(users):
        # Events contain no document names, guests, financial values or room details.
        frappe.publish_realtime("hospitality_changed", {"property": property_name}, user=user, after_commit=True)
