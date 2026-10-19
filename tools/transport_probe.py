"""Native backend fixture for authenticated Socket.IO tests; no production sites."""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import uuid

import frappe
from hospitality_suite import api
from hospitality_suite.service import operation

parser=argparse.ArgumentParser()
parser.add_argument("mode",choices=("prepare","pending","sale"))
parser.add_argument("--token")
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
state_path=bench/".hospitality-transport-users.json"
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.local.site=="hospitality.localhost"
    frappe.set_user("Administrator")
    if args.mode=="prepare":
        state=json.loads(state_path.read_text()) if state_path.exists() else {}
        for mode,label in (("hotel","Hotel Jardín Demo"),("motel","Motel Luna Demo")):
            prop=frappe.get_doc("HS Property",{"property_name":label})
            user="transport-"+mode+"@hospitality.example.invalid"
            if not frappe.db.exists("User",user):
                password=secrets.token_urlsafe(24)
                frappe.get_doc(dict(doctype="User",email=user,first_name="Prueba de transporte "+mode,send_welcome_email=0,user_type="System User",new_password=password,roles=[dict(role="HS Receptionist")])).insert()
                state[mode]=dict(user=user,password=password,property=prop.name)
            assert state[mode]["user"]==user and state[mode]["property"]==prop.name
            if not frappe.db.exists("HS Access",{"user":user,"property":prop.name}):
                with operation():
                    frappe.get_doc(dict(doctype="HS Access",user=user,company=prop.company,property=prop.name)).insert()
            assert frappe.db.count("HS Access",{"user":user})==1
        frappe.db.commit()
        state_path.write_text(json.dumps(state),encoding="utf-8")
        state_path.chmod(0o600)
        print(json.dumps(dict(prepared=True,users=2,properties=2)))
    elif args.mode=="sale":
        prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        frappe.set_user("manager@hospitality.example.invalid")
        state_path=bench/".hospitality-network-sale.json"
        assert not state_path.exists(),"Ya existe el fixture de venta; no se repite apertura"
        shift=api.execute(prop.name,"open_shift",uuid.uuid4().hex,dict(opening_amount=0))["shift"]
        result=dict(property=prop.name,shift=shift,warehouse=prop.warehouse,item="HS-DEMO-WATER",
                    before_quantity=frappe.db.get_value("Bin",{"warehouse":prop.warehouse,"item_code":"HS-DEMO-WATER"},"actual_qty"))
        frappe.db.commit()
        state_path.write_text(json.dumps(result),encoding="utf-8")
        state_path.chmod(0o600)
        print(json.dumps(dict(prepared=True,shift=shift,synthetic=True)))
    else:
        assert args.token and args.token.startswith("transport-") and len(args.token)<100
        state=json.loads(state_path.read_text())
        result=api.create_guest(state["hotel"]["property"],dict(full_name="Fixture sintético "+args.token),uuid.uuid4().hex)
        print(json.dumps(dict(ready=True,guest=result["guest"])),flush=True)
        decision=sys.stdin.readline().strip()
        assert decision in ("commit","rollback")
        getattr(frappe.db,decision)()
        print(json.dumps(dict(decision=decision,guest=result["guest"])),flush=True)
finally:
    frappe.db.rollback()
    frappe.destroy()
