import frappe
from frappe.utils import now_datetime

from hospitality_suite.security import document, require
from hospitality_suite.service import audit, assert_version, canonical, insert
from hospitality_suite import availability
from hospitality_suite.time import to_site


def schedule_cleaning(prop,data):
    require(prop.name,"inspect")
    room=document("HS Room",data["room"],"inspect")
    kind=data.get("kind") or "Stay"
    if kind not in ("Stay","Deep","Departure") or data.get("priority","Normal") not in ("Normal","High","Urgent"):
        frappe.throw("Tipo o prioridad de limpieza inválido")
    from hospitality_suite.service import current_all
    if current_all("HS Cleaning Task",filters={"room":room.name,"status":["!=","Completed"]}):
        frappe.throw("La habitación ya tiene una tarea de limpieza pendiente")
    assigned=data.get("assigned_to")
    validate_cleaner(prop,assigned)
    task=insert("HS Cleaning Task",prop,room=room.name,kind=kind,priority=data.get("priority") or "Normal",
                assigned_to=assigned,status="Pending",notes=data.get("notes"),
                checklist=canonical({"baño":False,"cama":False,"minibar":False,"superficies":False}))
    audit(prop,"Schedule cleaning",task,task.notes)
    return dict(task=task.name)


def validate_cleaner(prop,user):
    if not user:
        return
    from hospitality_suite.security import allowed_properties
    if not frappe.db.get_value("User",user,"enabled") or prop.name not in allowed_properties(user) or not set(frappe.get_roles(user)).intersection({"HS Housekeeping","HS Supervisor","HS Manager","HS Administrator","System Manager"}):
        frappe.throw("El responsable debe tener acceso y rol de limpieza en este establecimiento")


def update_cleaning(prop, data):
    task = document("HS Cleaning Task", data["task"], "clean")
    assert_version(task, data.get("modified"))
    target = data["status"]
    transitions = {"Pending": ["In Progress"], "In Progress": ["Inspection", "Completed"], "Inspection": ["Completed", "In Progress"], "Completed": []}
    if target not in transitions[task.status]:
        frappe.throw("Transición de limpieza inválida")
    room = frappe.get_doc("HS Room", task.room)
    if task.assigned_to and task.assigned_to!=frappe.session.user:
        require(prop.name,"inspect")
    if target == "In Progress":
        task.started_at = task.started_at or now_datetime()
        task.assigned_to = data.get("assigned_to") or frappe.session.user
        validate_cleaner(prop,task.assigned_to)
        room.cleaning_status = "Cleaning"
    elif target in ("Inspection", "Completed"):
        checklist = data.get("checklist") or {}
        required=set(frappe.parse_json(task.checklist or "{}")) or {"baño","cama","minibar","superficies"}
        if set(checklist)!=required or not all(v is True or v==1 for v in checklist.values()):
            frappe.throw("Complete la lista de revisión antes de marcar limpia")
        task.checklist = canonical(checklist)
        if target == "Completed" and prop.inspection_required:
            if task.status != "Inspection":
                frappe.throw("La habitación requiere inspección previa")
            require(prop.name, "inspect")
            task.inspected_by = frappe.session.user
        task.completed_at = now_datetime()
        room.cleaning_status = "Clean" if target == "Completed" else "Inspection"
    task.status, task.notes = target, data.get("notes")
    task.save()
    room.save()
    audit(prop, "Cleaning " + target, task, task.notes)
    return dict(task=task.name, status=target)


def maintenance(prop, data):
    if data.get("order"):
        doc = document("HS Maintenance Order", data["order"], "maintain")
        assert_version(doc, data.get("modified"))
        target = data["status"]
        if doc.status == "Completed" or target not in ("In Progress", "Completed"):
            frappe.throw("Transición de mantenimiento inválida")
        if target == "Completed":
            require(prop.name, "inspect")
            availability.release(maintenance=doc.name)
            doc.reopened_by = frappe.session.user
        doc.status, doc.notes = target, data.get("notes")
        doc.save()
    else:
        room = document("HS Room", data["room"], "maintain")
        start, end = to_site(data["starts_at"], prop), to_site(data["ends_at"], prop)
        availability.check(prop, room.category, start, end, room.name)
        doc = insert("HS Maintenance Order", prop, room=room.name, title=data["title"], starts_at=start, ends_at=end,
                     kind=data.get("kind") or "Corrective", status="Open", notes=data.get("notes"), assigned_to=data.get("assigned_to"))
        insert("HS Allocation", prop, category=room.category, room=room.name, starts_at=start, ends_at=end,
               buffer_minutes=0, kind="Maintenance", status="Active", maintenance=doc.name)
    audit(prop, "Maintenance " + doc.status, doc, doc.notes)
    return dict(order=doc.name, status=doc.status)
