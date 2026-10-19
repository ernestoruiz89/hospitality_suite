import frappe
from frappe.utils import now_datetime

from hospitality_suite.security import document, require,private_evidence,allowed_properties
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
        target = data.get("status") or doc.status
        if doc.status == "Completed" or target not in (doc.status,"In Progress", "Completed"):
            frappe.throw("Transición de mantenimiento inválida")
        maintenance_owner(prop,doc)
        if "assigned_to" in data and data["assigned_to"]!=doc.assigned_to:
            require(prop.name,"inspect")
            validate_technician(prop,data["assigned_to"])
            doc.assigned_to=data["assigned_to"]
        if data.get("evidence"):
            doc.evidence=private_evidence(data["evidence"],doc)
        if target == "Completed":
            require(prop.name, "inspect")
            availability.release(maintenance=doc.name)
            doc.reopened_by = frappe.session.user
        doc.status, doc.notes = target, data.get("notes",doc.notes)
        doc.save()
    else:
        from hospitality_suite.service import current_all
        equipment=document("HS Equipment",data["equipment"],"maintain") if data.get("equipment") else None
        if equipment and (not equipment.active or equipment.property!=prop.name):
            frappe.throw("Seleccione un equipo activo del establecimiento")
        if equipment and equipment.room and data.get("room") and equipment.room!=data["room"]:
            frappe.throw("La habitación no corresponde a la ubicación del equipo")
        room_name=data.get("room") or (equipment.room if equipment else None)
        room=document("HS Room",room_name,"maintain") if room_name else None
        if not room and not equipment:
            frappe.throw("Seleccione habitación o equipo")
        blocks=bool(data.get("blocks_room",bool(room)))
        if blocks and not room:
            frappe.throw("Para bloquear disponibilidad seleccione una habitación")
        if not data.get("title") or data.get("kind","Corrective") not in ("Corrective","Preventive"):
            frappe.throw("Indique título y tipo de mantenimiento")
        validate_technician(prop,data.get("assigned_to"))
        start, end = to_site(data["starts_at"], prop), to_site(data["ends_at"], prop)
        if equipment and current_all("HS Maintenance Order",filters={"equipment":equipment.name,"status":["!=","Completed"],"starts_at":["<",end],"ends_at":[">",start]},pluck="name"):
            frappe.throw("El equipo ya tiene una orden que coincide con ese intervalo")
        if blocks:
            availability.check(prop, room.category, start, end, room.name)
        doc = insert("HS Maintenance Order", prop, room=room.name if room else None,equipment=equipment.name if equipment else None,blocks_room=blocks, title=data["title"], starts_at=start, ends_at=end,
                     kind=data.get("kind") or "Corrective", status="Open", notes=data.get("notes"), assigned_to=data.get("assigned_to"))
        if blocks:
            insert("HS Allocation", prop, category=room.category, room=room.name, starts_at=start, ends_at=end,
                   buffer_minutes=0, kind="Maintenance", status="Active", maintenance=doc.name)
    audit(prop, "Maintenance " + doc.status, doc, doc.notes)
    return dict(order=doc.name, status=doc.status)


def validate_technician(prop,user):
    if user and (not frappe.db.get_value("User",user,"enabled") or prop.name not in allowed_properties(user) or not set(frappe.get_roles(user)).intersection({"HS Maintenance","HS Supervisor","HS Manager","HS Administrator","System Manager"})):
        frappe.throw("El responsable debe tener acceso y rol de mantenimiento en este establecimiento")


def maintenance_owner(prop,doc):
    if doc.assigned_to and doc.assigned_to!=frappe.session.user:
        require(prop.name,"inspect")


def maintenance_parts(prop,data):
    from hospitality_suite.accounting import ready,post_standard
    from hospitality_suite.pricing import decimal,money
    from hospitality_suite.service import locked_doc
    ready(prop)
    doc=document("HS Maintenance Order",data["order"],"maintain")
    assert_version(doc,data.get("modified"))
    maintenance_owner(prop,doc)
    if doc.status=="Completed":
        frappe.throw("La orden ya está cerrada")
    if data.get("return_entry"):
        require(prop.name,"approve")
        if not data.get("reason"):
            frappe.throw("Indique el motivo de devolución de repuestos")
        parts=[r for r in doc.parts if r.stock_entry==data["return_entry"] and r.status=="Issued"]
        if not parts:
            frappe.throw("La salida no pertenece a los repuestos pendientes de esta orden")
        entry=locked_doc("Stock Entry",data["return_entry"])
        entry.flags.ignore_permissions=True
        entry.hs_correction_reason=data["reason"]
        entry.cancel()
        for part in parts:
            part.status="Returned"
    else:
        parts=data.get("parts")
        if not isinstance(parts,list) or not 1<=len(parts)<=100:
            frappe.throw("Seleccione los repuestos y sus cantidades")
        entry=frappe.new_doc("Stock Entry")
        entry.update(dict(company=prop.company,stock_entry_type="Material Issue",remarks="Mantenimiento "+doc.name,hs_stock_purpose="Maintenance"))
        for part in parts:
            item=locked_doc("Item",part["item"])
            qty=decimal(part.get("quantity"))
            if item.disabled or not item.is_stock_item or qty<=0:
                frappe.throw("El repuesto debe ser un artículo de inventario habilitado y la cantidad positiva")
            entry.append("items",dict(item_code=item.name,qty=float(qty),s_warehouse=prop.warehouse,cost_center=prop.cost_center))
        post_standard(entry,prop)
        for row in entry.items:
            doc.append("parts",dict(item=row.item_code,quantity=row.qty,stock_entry=entry.name,cost=abs(row.basic_amount),status="Issued"))
        doc.stock_entry=entry.name
    doc.cost=money(sum(decimal(r.cost) for r in doc.parts if r.status=="Issued"))
    # Only derived stock fields are delegated; operators never supply a valuation.
    doc.save(ignore_permissions=True)
    audit(prop,"Maintenance parts return" if data.get("return_entry") else "Maintenance parts issue",doc,data.get("reason"),dict(stock_entry=entry.name,cost=str(doc.cost)))
    return dict(order=doc.name,stock_entry=entry.name,cost=str(doc.cost))
