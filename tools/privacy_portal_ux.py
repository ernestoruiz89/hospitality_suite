"""Bounded native observations and a filesystem fault affecting only new QA evidence."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re

import frappe

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
TARGET=BENCH/'sites'/SITE
STATE=BENCH/'.hospitality-privacy-portal-state.json'
PAYLOAD=BENCH/'.hospitality-privacy-portal-fault-payload.pdf'
DESCRIPTION='Objeto sintético para retención de aceptación'
CONTROL='Objeto de control que se conserva en aceptación'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['before','checkpoint','age-and-fault','repair-file','files-restored'])
parser.add_argument('--label',required=True)
args=parser.parse_args()
assert re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',args.label)
assert (BENCH/'.hospitality-privacy-portal-ux-baseline.json').is_file()
output=ROOT/f'docs/evidence/privacy-portal-{args.label}.json'
assert not output.exists()
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
def tree():
    result={}
    for kind in ['public','private']:
        folder=TARGET/kind/'files'
        for path in folder.rglob('*'):
            assert not path.is_symlink() and path.resolve().is_relative_to(folder.resolve())
            if path.is_file():result[path.relative_to(TARGET).as_posix()]=sha(path)
    return result
def write(proof):
    output.write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({key:proof[key] for key in ['label','mutation','counts'] if key in proof},ensure_ascii=False))
if args.action=='files-restored':
    state=json.loads(STATE.read_text())
    assert not PAYLOAD.exists()
    # Only source files explicitly observed during this QA run may be moved.
    # Preserve unknown pre-existing files, even if their File metadata is absent.
    current=tree()
    assert all(current.get(name)==digest for name,digest in state['original_files'].items())
    assert set(current)-set(state['original_files'])<=set(state.get('created_files',{}))
    receipt=json.loads((BENCH/'.hospitality-privacy-portal-ux-restored-receipt.json').read_text())
    assert receipt['site']==SITE and receipt['baseline_sha256']==sha(BENCH/'.hospitality-privacy-portal-ux-baseline.json')
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        from hospitality_suite.tests.setup import require_test_site
        require_test_site(paused=True);frappe.set_user('Administrator')
        quarantine=BENCH/'.hospitality-privacy-portal-gui-files'
        quarantine.mkdir(mode=0o700,exist_ok=True)
        for name,digest in state['created_files'].items():
            destination=quarantine/(digest+'-'+Path(name).name)
            assert destination.is_file() and sha(destination)==digest
        for name in set(current)-set(state['original_files']):
            path=(TARGET/name).resolve()
            assert path.parent==(TARGET/'private/files').resolve() and sha(path)==state['created_files'][name]
            assert not frappe.db.exists('File',{'file_url':'/private/files/'+path.name})
            destination=quarantine/(sha(path)+'-'+path.name)
            if destination.exists():assert sha(destination)==sha(path)
            else:destination.write_bytes(path.read_bytes());destination.chmod(0o600)
            assert sha(destination)==sha(path)
            path.unlink()
        assert tree()==state['original_files']
    finally:frappe.db.rollback();frappe.destroy()
    write(dict(label=args.label,mutation=False,original_files=len(state['original_files']),all_original_bytes_preserved=True,
        GUI_artifacts_preserved_outside_site=len(state['created_files']),
        remaining_unreferenced_GUI_files_quarantined=len(set(current)-set(state['original_files']))))
    raise SystemExit()
os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    from hospitality_suite import api,privacy
    require_test_site(paused=True)
    assert frappe.conf.db_name=='hospitality_acceptance'
    frappe.set_user('Administrator')
    prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
    assert str(prop.business_date)=='2026-10-19'
    if args.action=='before':
        assert not STATE.exists() and not PAYLOAD.exists()
        assert not any(frappe.db.count(dt) for dt in ['HS Incident','HS Retention Run','HS Portal Request','HS Booking','HS Stay','HS Payment'])
        state=dict(original_files=tree(),created_files={})
    else:state=json.loads(STATE.read_text())
    if args.action=='age-and-fault':
        assert 'fault' not in state and not PAYLOAD.exists()
        assert frappe.db.count('HS Incident')==2
        rows=[frappe.get_doc('HS Incident',{'property':prop.name,'description':text}) for text in [DESCRIPTION,CONTROL]]
        assert all(row.owner=='housekeeping@hospitality.example.invalid' and row.status=='Resolved' and row.evidence for row in rows)
        old=frappe.utils.now_datetime()-timedelta(days=400)
        created={}
        for doc in rows:
            for row in privacy.files_for(doc):
                file=frappe.get_doc('File',row.name)
                path=Path(file.get_full_path()).resolve()
                assert file.is_private and path.parent==(TARGET/'private/files').resolve()
                name=path.relative_to(TARGET).as_posix()
                assert name not in state['original_files'] and path.is_file()
                created[name]=sha(path)
                frappe.db.set_value('File',file.name,dict(creation=old,modified=old),update_modified=False)
            frappe.db.set_value(doc.doctype,doc.name,'modified',old,update_modified=False)
        target=Path(frappe.get_doc('File',{'file_url':rows[0].evidence}).get_full_path()).resolve()
        assert target.suffix=='.pdf' and target.read_bytes().startswith(b'%PDF-')
        assert not (target.relative_to(TARGET).as_posix() in state['original_files'])
        state.update(created_files=created,targets=[row.name for row in rows],fault=dict(path=target.relative_to(TARGET).as_posix(),sha256=sha(target)))
        # Native Attach processing can retain another sanitized PDF copy when
        # the incident is saved. Track every new private path of these two
        # incidents rather than assuming one physical file per logical upload.
        assert 2<=len(created)<=4
        archive=BENCH/'.hospitality-privacy-portal-gui-files'
        archive.mkdir(mode=0o700,exist_ok=True)
        for name,digest in created.items():
            path=(TARGET/name).resolve();destination=archive/(digest+'-'+path.name)
            assert path.parent==(TARGET/'private/files').resolve() and sha(path)==digest
            if destination.exists():assert sha(destination)==digest
            else:destination.write_bytes(path.read_bytes());destination.chmod(0o600)
        # Native os.remove on this one new path raises IsADirectoryError. All
        # original bytes remain in a private recovery payload outside the site.
        target.replace(PAYLOAD);PAYLOAD.chmod(0o600);target.mkdir(mode=0o700)
        assert sha(PAYLOAD)==state['fault']['sha256']
    elif args.action=='repair-file':
        assert state.get('fault') and not state.get('repaired')
        target=(TARGET/state['fault']['path']).resolve()
        assert target.parent==(TARGET/'private/files').resolve() and target.is_dir() and not list(target.iterdir())
        runs=frappe.get_all('HS Retention Run',fields=['name','status','attempts'])
        assert len(runs)==1 and runs[0].status=='Failed' and runs[0].attempts==3
        assert PAYLOAD.is_file() and sha(PAYLOAD)==state['fault']['sha256']
        target.rmdir();PAYLOAD.replace(target)
        state['repaired']=True
    if args.action in ['before','age-and-fault','repair-file']:
        STATE.write_text(json.dumps(state));STATE.chmod(0o600)
        if args.action=='age-and-fault':frappe.db.commit()
    incidents=frappe.get_all('HS Incident',fields=['name','property','room','kind','description','status','evidence','resolution','owner','resolved_by','modified'])
    runs=[]
    for name in frappe.get_all('HS Retention Run',pluck='name'):
        run=frappe.get_doc('HS Retention Run',name)
        runs.append(dict(name=run.name,status=run.status,attempts=run.attempts,approved_by=run.approved_by,reason=run.reason,
            files=[dict(status=row.status,last_error=row.last_error,retained_path=bool(row.file_url),retained_hash=bool(row.content_hash)) for row in run.files]))
    candidates=api.retention_candidates(prop.name)
    counts={dt:frappe.db.count(dt) for dt in ['HS Incident','HS Retention Run','File','HS Guest','HS Portal Request','HS Booking','HS Allocation',
        'HS Stay','HS Charge','HS Payment','HS Shift','Sales Invoice','Payment Entry','Journal Entry']}
    requests=frappe.get_all('HS Portal Request',fields=['name','full_name','status','rooms','people','amount','currency','booking','hold_until','owner'])
    bookings=frappe.get_all('HS Booking',fields=['name','status','guest','customer','channel','amount','currency','owner'])
    created_paths={}
    for name,digest in state['created_files'].items():
        path=(TARGET/name).resolve()
        created_paths[name]=dict(exists=path.exists(),is_file=path.is_file(),is_directory=path.is_dir(),
            sha256=sha(path) if path.is_file() else None,original_sha256=digest)
    history=[]
    for name in state.get('targets',[]):
        versions=frappe.get_all('Version',filters={'ref_doctype':'HS Incident','docname':name},pluck='data')
        comments=frappe.get_all('Comment',filters={'reference_doctype':'HS Incident','reference_name':name,
            'comment_type':['in',['Attachment','Attachment Removed']]},pluck='name')
        history.append(dict(incident=name,versions_with_private_file_urls=sum('/private/files/' in value for value in versions),
            attachment_comments=len(comments)))
    proof=dict(label=args.label,at_utc=datetime.now(timezone.utc).isoformat(),mutation=args.action in ['age-and-fault','repair-file'],
        fixture_origin='All incident/attachment/resolution/approval/request/conversion business records originate in UI. QA helper only observes, ages the two new closed incidents/files, and injects/repairs one filesystem fault.',
        counts=counts,incidents=incidents,runs=runs,candidates=candidates,portal_requests=requests,bookings=bookings,
        allocations=frappe.get_all('HS Allocation',fields=['name','status','portal_request','booking','booking_room','room','category']),
        audit=frappe.get_all('HS Audit Event',filters={'property':prop.name},fields=['action','actor','source_doctype','source_name','reason'],order_by='creation'),
        file_docs=frappe.get_all('File',filters={'attached_to_doctype':'HS Incident'},fields=['name','file_url','is_private','attached_to_name','owner']),
        file_state=dict(original_files=len(state['original_files']),new_QA_files=len(state['created_files']),fault_injected='fault' in state,
            repaired=bool(state.get('repaired')),known_paths=created_paths),history=history)
    write(proof)
finally:
    frappe.db.rollback();frappe.destroy()
