"""Preserve every original file and quarantine only new, unreferenced test artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import tarfile

import frappe

ROOT=Path(__file__).resolve().parents[1]
BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
TARGET=BENCH/'sites'/SITE
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['before','after','cleanup','verify'])
parser.add_argument('--phase',choices=['secondary-finance','secondary-flows','privacy-portal'],required=True)
parser.add_argument('--run-label',default='native-full-1')
args=parser.parse_args()
expected_tests={'secondary-finance':407,'secondary-flows':409,'privacy-portal':410}[args.phase]
assert args.run_label in ['native-full-1','native-full-2','native-full-3']
BASE=BENCH/f'.hospitality-{args.phase}-ux-baseline.json'
STATE=BENCH/f'.hospitality-{args.phase}-native-files.json'
sha=lambda data:hashlib.sha256(data).hexdigest()
assert TARGET.resolve()==Path('/home/frappe/benches/hospitality-bench/sites/hospitality-acceptance.localhost')
config=json.loads((TARGET/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('allow_tests') and config.get('pause_scheduler') and config.get('hospitality_integration_test_site')
with socket.socket() as sock:
    assert sock.connect_ex(('127.0.0.1',8089))!=0,'Stop UI writes before inspecting test files'
def tree():
    rows={}
    for kind in ['public','private']:
        folder=TARGET/kind/'files'
        for path in folder.rglob('*'):
            assert not path.is_symlink()
            if path.is_file():
                assert path.resolve().is_relative_to(folder.resolve())
                rows[path.relative_to(TARGET).as_posix()]=sha(path.read_bytes())
    return rows
current=tree()
receipt=json.loads((BENCH/f'.hospitality-{args.phase}-ux-restored-receipt.json').read_text())
assert receipt['site']==SITE and receipt['baseline_sha256']==sha(BASE.read_bytes())
if args.action=='before':
    assert not STATE.exists()
    backup=json.loads(BASE.read_text())
    original={}
    for kind in ['public','private']:
        archive_path=TARGET/'private/backups'/backup[kind+'_files']
        assert sha(archive_path.read_bytes())==backup['backup_files'][archive_path.name]
        with tarfile.open(archive_path,'r:*') as archive:
            for member in archive:
                if not member.isfile():continue
                parts=PurePosixPath(member.name).parts
                i=parts.index(kind)
                assert parts[i-1]==SITE and parts[i+1]=='files' and '..' not in parts
                name=PurePosixPath(*parts[i:]).as_posix()
                assert name not in original
                original[name]=sha(archive.extractfile(member).read())
    assert current==original
    state=dict(original=original,baseline_sha256=sha(BASE.read_bytes()),sources={
        path.relative_to(ROOT).as_posix():sha(path.read_bytes()) for path in (ROOT/'hospitality_suite').rglob('*.py')})
    STATE.write_text(json.dumps(state));STATE.chmod(0o600)
    print(json.dumps(dict(before_files=len(original),pre_UI_archive_tree_identical=True)))
    raise SystemExit()
state=json.loads(STATE.read_text())
assert state['baseline_sha256']==sha(BASE.read_bytes())
original=state['original']
assert all(current.get(name)==digest for name,digest in original.items())
if args.action=='after':
    assert 'created' not in state
    report=ROOT/f'docs/evidence/{args.phase}-native-run.json'
    run=json.loads(report.read_text())
    assert run['site']==SITE and run['tests']==expected_tests and run['exit_code']==0
    assert not any(run[k] for k in ['errors','failures','skipped'])
    assert run['raw_log_sha256']==sha((ROOT/f'.local/{args.phase}/{args.run_label}.log').read_bytes())
    assert state['sources']=={path.relative_to(ROOT).as_posix():sha(path.read_bytes()) for path in (ROOT/'hospitality_suite').rglob('*.py')}
    state.update(created={name:digest for name,digest in current.items() if name not in original},
        native_run_sha256=sha(report.read_bytes()),native_run_label=args.run_label)
    STATE.write_text(json.dumps(state));STATE.chmod(0o600)
    print(json.dumps(dict(native_new_physical_files=len(state['created']),all_original_files_preserved=True,successful_native_tests=expected_tests)))
    raise SystemExit()
if args.action=='cleanup':
    assert set(current)-set(original)<=set(state['created'])
    os.chdir(BENCH/'sites')
    frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        from hospitality_suite.tests.setup import require_test_site
        require_test_site(paused=True)
        quarantine=BENCH/f'.hospitality-{args.phase}-file-quarantine'
        quarantine.mkdir(mode=0o700,exist_ok=True)
        for name in set(current)-set(original):
            path=(TARGET/name).resolve()
            parts=PurePosixPath(name).parts
            assert parts[0] in ['public','private'] and parts[1]=='files'
            assert path.is_relative_to((TARGET/parts[0]/'files').resolve())
            digest=state['created'][name]
            assert current[name]==digest
            url=('/private' if parts[0]=='private' else '')+'/files/'+PurePosixPath(*parts[2:]).as_posix()
            assert not frappe.db.exists('File',{'file_url':url})
            destination=quarantine/(digest+'-'+path.name)
            if destination.exists():assert sha(destination.read_bytes())==digest
            else:
                shutil.copyfile(path,destination);destination.chmod(0o600)
            assert sha(destination.read_bytes())==digest
            path.unlink()
        assert tree()==original
    finally:
        frappe.db.rollback();frappe.destroy()
    print(json.dumps(dict(original_files_preserved=len(original),test_files_quarantined=len(state['created']))))
else:
    assert current==original and 'native_run_sha256' in state
    proof=dict(original_physical_files=len(original),all_original_bytes_preserved=True,
        native_artifacts_preserved_outside_site=len(state['created']),tree_sha256=sha(json.dumps(current,sort_keys=True).encode()),
        baseline_sha256=state['baseline_sha256'],successful_native_run_sha256=state['native_run_sha256'])
    (ROOT/f'docs/evidence/{args.phase}-files-restored.json').write_text(json.dumps(proof,indent=2)+'\n',newline='\n')
    print(json.dumps(proof))
