"""Reviewed retention of identity fields and closed operational evidence.

Database redaction, native File deletion and the disposal outbox commit together.
The worker removes unreferenced bytes afterwards; a rolled-back request cannot
delete bytes. This does not anonymize accounting, names, contacts or backups.
"""
from datetime import timedelta
import hashlib
from pathlib import Path

import frappe

from hospitality_suite.security import document,require,is_system,realtime
from hospitality_suite.service import current_all,locked_doc,insert,audit,canonical,operation,lock_property,assert_version
from hospitality_suite.time import now_local,to_site

FIELDS={"HS Guest":("identity_type","identity_number","identity_file"),"HS Maintenance Order":("evidence",),"HS Incident":("evidence",)}


def policy(prop):
    days=prop.retention_days or 0
    if not days:
        frappe.throw("La política de retención está desactivada; configure los días antes de revisar")
    return days,to_site(str(now_local(prop).date()-timedelta(days=days))+" 00:00:00",prop)


def eligible(prop,doc,cutoff,files):
    if doc.property!=prop.name or frappe.utils.get_datetime(doc.modified)>=cutoff:
        return False
    if any(frappe.utils.get_datetime(f.creation)>=cutoff or frappe.utils.get_datetime(f.modified)>=cutoff or not f.is_private for f in files):
        return False
    if doc.doctype=="HS Guest":
        bookings=current_all("HS Booking",filters={"guest":doc.name},fields=["status","modified"])
        if any(b.status not in ("Completed","Cancelled","No Show") or frappe.utils.get_datetime(b.modified)>=cutoff for b in bookings):
            return False
        companions=current_all("HS Stay Guest",filters={"guest":doc.name,"parenttype":"HS Stay"},pluck="parent")
        stays=current_all("HS Stay",filters={"guest":doc.name},fields=["name","status","actual_check_out"])
        if companions:
            stays+=current_all("HS Stay",filters={"name":["in",companions]},fields=["name","status","actual_check_out"])
        if any(s.status!="Checked Out" or not s.actual_check_out or frappe.utils.get_datetime(s.actual_check_out)>=cutoff for s in stays):
            return False
    elif doc.status!=("Completed" if doc.doctype=="HS Maintenance Order" else "Resolved"):
        return False
    return any(doc.get(field) for field in FIELDS[doc.doctype]) or bool(files)


def files_for(doc):
    return current_all("File",filters={"attached_to_doctype":doc.doctype,"attached_to_name":doc.name,"is_folder":0},
                       fields=["name","file_url","thumbnail_url","content_hash","creation","modified","is_private"],order_by="name")


def validate_local_file(doc):
    root=Path(frappe.get_site_path("private","files")).resolve()
    if not doc.is_private or not doc.file_url.startswith("/private/files/") or not doc.content_hash or Path(doc.get_full_path()).resolve().parent!=root:
        frappe.throw("Revise el adjunto: la retención solo procesa archivos privados locales de este sitio")
    if doc.thumbnail_url:
        thumb=Path(doc.thumbnail_url)
        if str(thumb.parent) not in ("/files","/private/files") or not thumb.stem.startswith(Path(doc.file_url).stem+"_"):
            frappe.throw("Revise la miniatura del archivo antes de eliminarla por retención")


def file_snapshot(file):
    doc=locked_doc("File",file.name)
    validate_local_file(doc)
    return dict(name=doc.name,file_url=doc.file_url,thumbnail_url=doc.thumbnail_url,content_hash=doc.content_hash,modified=str(doc.modified))


def plan(prop,targets):
    require(prop.name,"approve")
    days,cutoff=policy(prop)
    if not isinstance(targets,list) or not 1<=len(targets)<=50:
        frappe.throw("Seleccione de uno a cincuenta documentos para revisar")
    identities=[(r.get("doctype"),r.get("name")) for r in targets]
    if len(set(identities))!=len(identities) or any(dt not in FIELDS for dt,name in identities):
        frappe.throw("Revise los tipos de documento y evite repetirlos")
    selected=[]
    for target in targets:
        doc=document(target["doctype"],target["name"],"approve")
        if doc.property!=prop.name:
            frappe.throw("El documento no pertenece al establecimiento de esta revisión",frappe.PermissionError)
        assert_version(doc,target.get("modified"))
        files=files_for(doc)
        if not eligible(prop,doc,cutoff,files):
            frappe.throw("El documento cambió, tiene actividad vigente o todavía no cumple la política de retención")
        selected.append(dict(doctype=doc.doctype,name=doc.name,modified=str(doc.modified),fields=[f for f in FIELDS[doc.doctype] if doc.get(f)],files=[file_snapshot(f) for f in files]))
    return dict(retention_days=days,cutoff=str(cutoff),targets=sorted(selected,key=lambda r:(r["doctype"],r["name"])))


def acceptance(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def quote(prop,data):
    value=plan(prop,data.get("targets"))
    return dict(retention_days=value["retention_days"],cutoff=value["cutoff"],acceptance=acceptance(value),
                targets=[{**{k:r[k] for k in ("doctype","name","fields")},"file_count":len(r["files"])} for r in value["targets"]])


def candidates(prop):
    require(prop.name,"approve")
    if not prop.retention_days:
        return dict(enabled=False,targets=[])
    days,cutoff=policy(prop)
    result=[]
    for dt,fields in FIELDS.items():
        names=set(frappe.get_all(dt,filters={"property":prop.name,"modified":["<",cutoff]},or_filters=[[f,"is","set"] for f in fields],pluck="name",order_by="modified",limit=500))
        attached=frappe.get_all("File",filters={"attached_to_doctype":dt,"is_folder":0,"creation":["<",cutoff]},pluck="attached_to_name",limit=500)
        if attached:
            names.update(frappe.get_all(dt,filters={"property":prop.name,"name":["in",attached],"modified":["<",cutoff]},pluck="name",limit=500))
        for name in sorted(names):
            doc=locked_doc(dt,name)
            files=files_for(doc)
            if eligible(prop,doc,cutoff,files):
                result.append(dict(doctype=dt,name=name,modified=str(doc.modified),label=doc.get("full_name") or doc.get("title") or "Novedad cerrada",fields=[f for f in fields if doc.get(f)],file_count=len(files)))
                if len(result)==50:
                    return dict(enabled=True,retention_days=days,cutoff=str(cutoff),targets=result,more_possible=True)
    return dict(enabled=True,retention_days=days,cutoff=str(cutoff),targets=result,more_possible=False)


def scrub_versions(doc,fields,run):
    for name in current_all("Version",filters={"ref_doctype":doc.doctype,"docname":doc.name},pluck="name"):
        version=locked_doc("Version",name)
        data=frappe.parse_json(version.data or "{}")
        changed=data.get("changed",[])
        redacted=[row for row in changed if row and row[0] in fields]
        if redacted:
            data["changed"]=[row for row in changed if row not in redacted]
            data["hospitality_retention_run"]=run.name
            version.data=canonical(data)
            version.save(ignore_permissions=True)


def queue(run):
    key=hashlib.sha256(f"{run.name}|{run.attempts}|{run.modified}".encode()).hexdigest()[:32]
    # Frappe captures the submitting user in the job. Only this private,
    # already-approved outbox task runs as the system disposal service.
    previous=frappe.session.user
    try:
        frappe.set_user("Administrator")
        frappe.enqueue("hospitality_suite.privacy.purge_run",run_name=run.name,queue="short",enqueue_after_commit=True,job_id="hs-privacy-"+key,deduplicate=True)
    finally:
        frappe.set_user(previous)


def retire(prop,data):
    value=plan(prop,data.get("targets"))
    if not data.get("reason") or data.get("acceptance")!=acceptance(value) or data.get("confirm") is not True:
        frappe.throw("Revise los documentos, confirme la eliminación de datos sensibles e indique el motivo")
    summary=[dict(doctype=r["doctype"],name=r["name"],fields=r["fields"],file_count=len(r["files"])) for r in value["targets"]]
    run=insert("HS Retention Run",prop,status="Pending",approved_by=frappe.session.user,approved_at=frappe.utils.now_datetime(),
               retention_days=value["retention_days"],cutoff=value["cutoff"],reason=data["reason"],plan=canonical(summary),attempts=0)
    previous=getattr(frappe.local,"hs_retention_run",None)
    frappe.local.hs_retention_run=run.name
    try:
        for target in value["targets"]:
            doc=locked_doc(target["doctype"],target["name"])
            for field in FIELDS[doc.doctype]:
                doc.set(field,None)
            doc.flags.ignore_version=True
            doc.save(ignore_permissions=True)
            scrub_versions(doc,FIELDS[doc.doctype],run)
            for file in target["files"]:
                run.append("files",dict(source_file=file["name"],file_url=file["file_url"],thumbnail_url=file["thumbnail_url"],content_hash=file["content_hash"],status="Pending"))
                frappe.delete_doc("File",file["name"],ignore_permissions=True,delete_permanently=True)
            for name in current_all("Comment",filters={"reference_doctype":doc.doctype,"reference_name":doc.name,"comment_type":["in",["Attachment","Attachment Removed"]]},pluck="name"):
                frappe.delete_doc("Comment",name,ignore_permissions=True,delete_permanently=True)
            audit(prop,"Retire sensitive fields",doc,data["reason"],dict(run=run.name,fields=target["fields"],files=len(target["files"])))
        if not run.files:
            run.status,run.completed_at="Completed",frappe.utils.now_datetime()
        run.save()
        audit(prop,"Approve data retention",run,data["reason"],dict(targets=len(summary),files=len(run.files),cutoff=value["cutoff"]))
        if run.files:
            queue(run)
        return dict(run=run.name,status=run.status,targets=len(summary),files=len(run.files))
    finally:
        frappe.local.hs_retention_run=previous


def purge_run(run_name):
    """Private worker entry; absent/rolled-back runs cannot affect the filesystem."""
    if not is_system():
        frappe.throw("La eliminación física se ejecuta en el worker del sistema",frappe.PermissionError)
    prop_name=frappe.db.get_value("HS Retention Run",run_name,"property")
    if not prop_name:
        return dict(status="Missing")
    with operation():
        prop=lock_property(prop_name)
        run=locked_doc("HS Retention Run",run_name)
        if run.status=="Completed" or run.attempts>=3:
            return dict(run=run.name,status=run.status,attempts=run.attempts)
        run.attempts+=1
        for row in run.files:
            if row.status in ("Deleted","Shared"):
                continue
            try:
                if frappe.db.exists("File",row.source_file):
                    raise ValueError("File metadata still exists")
                shared=bool(current_all("File",filters={"content_hash":row.content_hash},pluck="name"))
                file=frappe.get_doc(dict(doctype="File",name=row.source_file,file_name=row.file_url.rsplit("/",1)[-1],is_private=1,file_url=row.file_url,thumbnail_url=row.thumbnail_url,content_hash=row.content_hash))
                validate_local_file(file)
                if not shared:
                    if file.thumbnail_url and current_all("File",filters={"file_url":file.thumbnail_url},pluck="name"):
                        file.thumbnail_url=None
                    file._delete_file_on_disk()
                row.status="Shared" if shared else "Deleted"
                row.file_url=row.thumbnail_url=row.content_hash=None
                row.last_error=None
            except Exception as exc:
                # Keep a recoverable private outbox, without copying paths/PII into logs.
                row.status="Failed"
                row.last_error=type(exc).__name__+" errno="+str(getattr(exc,"errno",None))
        run.status="Failed" if any(r.status=="Failed" for r in run.files) else "Completed"
        run.last_error="Revise los archivos pendientes; el reintento automático está limitado a tres intentos." if run.status=="Failed" else None
        run.completed_at=frappe.utils.now_datetime() if run.status=="Completed" else None
        run.save(ignore_permissions=True)
        audit(prop,"Dispose retained files",run,details=dict(status=run.status,attempts=run.attempts,deleted=sum(r.status=="Deleted" for r in run.files),shared=sum(r.status=="Shared" for r in run.files)))
        realtime(prop.name)
        if run.status=="Failed" and run.attempts<3:
            queue(run)
        return dict(run=run.name,status=run.status,attempts=run.attempts)


def retry(prop,data):
    run=document("HS Retention Run",data["run"],"approve")
    assert_version(run,data.get("modified"))
    if run.property!=prop.name or run.status!="Failed" or not data.get("reason"):
        frappe.throw("Seleccione una ejecución fallida e indique la corrección realizada")
    run.attempts,run.status,run.last_error=0,"Pending",None
    run.save()
    audit(prop,"Retry file disposal",run,data["reason"])
    queue(run)
    return dict(run=run.name,status=run.status)
