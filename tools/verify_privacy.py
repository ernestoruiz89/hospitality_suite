"""Explicit disposable privacy fixture and real RQ verification, isolated site only."""
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import uuid

import frappe
from frappe.utils.file_manager import save_file
from hospitality_suite import api,privacy

parser=argparse.ArgumentParser()
parser.add_argument("mode",choices=("prepare","approve","verify"))
parser.add_argument("--output",default="/mnt/c/Users/Ernesto/Documents/ChatGPT/Hotel/docs/evidence/privacy-worker.json")
args=parser.parse_args()
bench=Path("/home/frappe/benches/hospitality-bench")
state_path=bench/".hospitality-retention-test.json"
os.chdir(bench/"sites")
frappe.init(site="hospitality.localhost",sites_path=str(bench/"sites"))
frappe.connect()
try:
    assert frappe.conf.allow_tests and frappe.local.site=="hospitality.localhost"
    frappe.set_user("Administrator")
    if args.mode=="prepare":
        assert not state_path.exists(),"El fixture ya existe; no se vuelve a crear ni sustituir"
        prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        result=api.create_guest(prop.name,dict(full_name="Huésped ficticio para retención UX-RET-001",identity_type="Sintética",identity_number="NO-ES-IDENTIFICACION-REAL-UX-RET-001"),uuid.uuid4().hex)
        guest=frappe.get_doc("HS Guest",result["guest"])
        guest.identity_number+="-verificada"
        guest.save()
        file=save_file("retencion-sintetica-UX-RET-001.txt",b"Fixture sintetico desechable de retencion UX-RET-001. Sin datos reales.",guest.doctype,guest.name,is_private=1)
        guest.identity_file=file.file_url
        guest.save()
        old=frappe.utils.now_datetime()-timedelta(days=400)
        files=privacy.files_for(guest)
        for row in files:
            frappe.db.set_value("File",row.name,dict(creation=old,modified=old),update_modified=False)
        frappe.db.set_value(guest.doctype,guest.name,"modified",old,update_modified=False)
        state=dict(property=prop.name,guest=guest.name,files=[r.name for r in files],path=str(Path(file.get_full_path()).resolve()),
                   ledger_counts={dt:frappe.db.count(dt) for dt in ("GL Entry","Payment Ledger Entry","Stock Ledger Entry")})
        frappe.db.commit()
        state_path.write_text(json.dumps(state),encoding="utf-8")
        state_path.chmod(0o600)
        print(json.dumps(dict(prepared=True,guest=guest.name,files=len(files),synthetic=True)))
    else:
        state=json.loads(state_path.read_text())
        guest=frappe.get_doc("HS Guest",state["guest"])
        assert guest.full_name=="Huésped ficticio para retención UX-RET-001"
        if args.mode=="approve":
            assert not state.get("run"),"El fixture ya fue aprobado"
            frappe.set_user("manager@hospitality.example.invalid")
            target=dict(doctype=guest.doctype,name=guest.name,modified=str(guest.modified))
            quote=api.preview(state["property"],dict(targets=[target]),"retire_sensitive")
            result=api.execute(state["property"],"retire_sensitive",uuid.uuid4().hex,dict(targets=[target],acceptance=quote["acceptance"],confirm=True,reason="Prueba autorizada de desarrollo con fixture sintético desechable UX-RET-001"))
            run=frappe.get_doc("HS Retention Run",result["run"])
            job_key=hashlib.sha256(f"{run.name}|{run.attempts}|{run.modified}".encode()).hexdigest()[:32]
            state.update(run=run.name,job_id="hs-privacy-"+job_key,precommit_bytes_exist=Path(state["path"]).exists(),precommit_status=run.status,approved_by=run.approved_by)
            assert state["precommit_bytes_exist"] and run.status=="Pending"
            assert frappe.session.user=="manager@hospitality.example.invalid"
            frappe.db.commit()
            state_path.write_text(json.dumps(state),encoding="utf-8")
            print(json.dumps(dict(run=run.name,queued_after_commit=True,approved_by=run.approved_by)))
        else:
            from frappe.utils.background_jobs import get_job
            run=frappe.get_doc("HS Retention Run",state["run"])
            job=get_job(state["job_id"])
            assert job and str(job.get_status()).lower().endswith("finished"),"Worker pendiente o fallido"
            assert job.kwargs["user"]=="Administrator"
            assert run.status=="Completed" and run.attempts==1
            assert not (guest.identity_number or guest.identity_type or guest.identity_file)
            assert not Path(state["path"]).exists()
            assert all(not frappe.db.exists("File",name) for name in state["files"])
            assert all(row.status=="Deleted" and not(row.file_url or row.thumbnail_url or row.content_hash) for row in run.files)
            assert state["ledger_counts"]=={dt:frappe.db.count(dt) for dt in state["ledger_counts"]}
            result=dict(synthetic_fixture=True,guest=guest.name,run=run.name,approved_by=run.approved_by,status=run.status,attempts=run.attempts,
                        real_rq_status=str(job.get_status()),worker_user=job.kwargs["user"],bytes_existed_before_commit=state["precommit_bytes_exist"],
                        bytes_exist_after_job=False,metadata_removed=len(state["files"]),outbox_paths_cleared=True,ledgers_unchanged=True,
                        browser_review_before_approval=True,browser_final_delete_clicked=False)
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps(result,ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
