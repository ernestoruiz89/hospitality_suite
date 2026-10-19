"""Read-only evidence for the equipment/file/incident browser workflow."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import frappe

parser=argparse.ArgumentParser()
parser.add_argument("--output",required=True)
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests
    frappe.set_user("Administrator")
    equipment=frappe.get_doc("HS Equipment",{"equipment_code":"BOMBA-UI-001"})
    order=frappe.get_doc("HS Maintenance Order",{"equipment":equipment.name,"title":"Revisión preventiva de bomba de demostración"})
    incident=frappe.get_doc("HS Incident",{"property":equipment.property,"description":"Paraguas de demostración UX-OBJ-001, custodia ficticia"})
    assert order.status=="Completed" and order.reopened_by=="supervisor@hospitality.example.invalid"
    assert not order.room and not order.blocks_room
    assert not frappe.db.exists("HS Allocation",{"maintenance":order.name})
    file=frappe.get_doc("File",{"file_url":order.evidence,"attached_to_doctype":order.doctype,"attached_to_name":order.name})
    assert file.is_private and file.file_url.startswith("/private/files/")
    content=Path(file.get_full_path()).read_bytes()
    assert b"Evidencia sint" in content and b"UX/UI" in content
    assert incident.status=="Resolved" and incident.resolution and incident.resolved_by=="supervisor@hospitality.example.invalid"
    permissions={}
    for user in ("supervisor@hospitality.example.invalid","maintenance@hospitality.example.invalid","housekeeping@hospitality.example.invalid"):
        frappe.set_user(user)
        permissions[user]=bool(frappe.has_permission("File","read",doc=file))
    assert permissions["supervisor@hospitality.example.invalid"]
    assert permissions["maintenance@hospitality.example.invalid"]
    assert not permissions["housekeeping@hospitality.example.invalid"]
    frappe.set_user("Administrator")
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=True)
    (output/"equipment.pdf").write_bytes(frappe.get_print(order.doctype,order.name,print_format="HS Orden de mantenimiento",as_pdf=True))
    result=dict(equipment=equipment.name,order=order.name,status=order.status,room=order.room,blocks_room=order.blocks_room,allocations=0,
                private_file=file.name,evidence_sha256=hashlib.sha256(content).hexdigest(),permissions=permissions,incident=incident.name,
                incident_status=incident.status,resolved_by=incident.resolved_by)
    (output/"equipment.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
