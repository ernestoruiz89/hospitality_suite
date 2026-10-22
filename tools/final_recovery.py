"""Bounded deployment/recovery rehearsal on the existing independent test bench.

All SQL, configuration, credentials, original media and failed-state artifacts
remain private. Only counts, hashes, revisions and command receipts are exported.
"""
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess

import frappe
import hospitality_suite
from hospitality_suite.schema import SCHEMA

ROOT=Path(__file__).resolve().parents[1]
MAIN=Path('/home/frappe/benches/hospitality-bench')
BENCH=Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
SITE='hospitality-release.localhost'
TARGET=BENCH/'sites'/SITE
STATE=Path('/home/frappe/.hospitality-final-recovery')
DATA=STATE/'state.json'
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['snapshot-original','restore-source','baseline','backup-baseline','checkout-current',
    'checkout-previous','install-deps','migrate','build','check','inject-asset-fault','backup-failed','restore-baseline','restore-original',
    'restore-clean','uninstall-clean-app','install-clean-app','check-original'])
parser.add_argument('--label',required=True)
parser.add_argument('--expect',choices=['previous','current'])
args=parser.parse_args()
assert re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*',args.label)
output=ROOT/f'docs/evidence/f26-{args.label}.json'
assert not output.exists(),'Preserve earlier observations; use a new label'
assert BENCH.resolve()==BENCH and BENCH!=MAIN
CONFIG=TARGET/'site_config.json'
config=json.loads(CONFIG.read_text())
assert config['db_name']=='hospitality_release' and config.get('pause_scheduler') and config.get('allow_tests')
assert config.get('hospitality_integration_test_site')
owner=pwd.getpwnam('frappe')
STATE.mkdir(mode=0o700,exist_ok=True);os.chown(STATE,owner.pw_uid,owner.pw_gid)
lock=STATE/'operation.lock'
lock_handle=lock.open('a+');lock.chmod(0o600);os.chown(lock,owner.pw_uid,owner.pw_gid)
fcntl.flock(lock_handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
git=lambda *args:subprocess.check_output(['git',*args],cwd=BENCH/'apps/hospitality_suite',text=True).strip()
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()

def write_private(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,default=str));path.chmod(0o600)
    os.chown(path,owner.pw_uid,owner.pw_gid)

def stopped():
    with socket.socket() as sock:assert sock.connect_ex(('127.0.0.1',8091))!=0,'Stop release web first'
    for name in ['web','worker','socket']:
        path=BENCH.parents[1]/'runtime'/f'{name}.pid'
        assert not path.exists() or not (Path('/proc')/path.read_text().strip()).exists(),'Stop release processes first'

def tree(target):
    rows={}
    for kind in ['public','private']:
        folder=target/kind/'files'
        for path in folder.rglob('*'):
            assert not path.is_symlink() and path.resolve().is_relative_to(folder.resolve())
            if path.is_file():rows[path.relative_to(target).as_posix()]=sha(path)
    return rows

def fingerprint():
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        frappe.set_user('Administrator')
        source=json.loads((MAIN/'.hospitality-final-recovery-upgrade.json').read_text())['hospitality.localhost']
        tables={}
        for dt,old in source['tables'].items():
            columns=old['columns']
            assert all(name.replace('_','').isalnum() for name in columns)
            rows=frappe.db.sql('SELECT '+','.join('`'+name+'`' for name in columns)+' FROM `tab'+dt+'` ORDER BY name',as_dict=True)
            raw=json.dumps(rows,default=str,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            tables[dt]=dict(columns=columns,rows=len(rows),sha256=hashlib.sha256(raw).hexdigest())
        private={}
        for name in frappe.get_all('File',filters={'is_private':1,'is_folder':0},pluck='name'):
            file=frappe.get_doc('File',name);path=Path(file.get_full_path()).resolve()
            assert path.is_relative_to((TARGET/'private/files').resolve()) and path.is_file()
            private[name]=sha(path)
        counts={dt:frappe.db.count(dt) for dt in ['HS Property','HS Room','HS Booking','HS Stay','HS Charge','HS Payment',
            'Sales Invoice','Payment Entry','Journal Entry','GL Entry','Stock Entry','Stock Ledger Entry','File']}
        return dict(tables=tables,private_files=private,physical_files=tree(TARGET),counts=counts)
    finally:frappe.db.rollback();frappe.destroy()

def command(label,command,cwd=BENCH):
    log=STATE/(label+'.log');assert not log.exists()
    print('F26 step: '+label,flush=True)
    with log.open('w') as stream:
        log.chmod(0o600)
        result=subprocess.run(command,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,
            env={**os.environ,'PATH':str(MAIN/'.runtime/wkhtmltox/usr/local/bin')+os.pathsep+os.environ.get('PATH','')})
    os.chown(log,owner.pw_uid,owner.pw_gid)
    assert result.returncode==0,'Native command failed; inspect private log '+str(log)
    return dict(exit_code=result.returncode,native_log_sha256=sha(log))

def backup(label):
    command(label,['/home/frappe/.local/bin/bench','--site',SITE,'backup','--with-files'])
    folder=TARGET/'private/backups';database=max(folder.glob('*-database.sql.gz'),key=lambda p:p.stat().st_mtime)
    files=list(folder.glob(database.name.removesuffix('-database.sql.gz')+'*'))
    assert len(files)>=4
    for path in files:path.chmod(0o600)
    return dict(database=database.name,files={path.name:sha(path) for path in files})

def quarantine_media(label):
    stopped();destination=STATE/(label+'-media');assert not destination.exists()
    destination.mkdir(mode=0o700);os.chown(destination,owner.pw_uid,owner.pw_gid)
    for kind in ['public','private']:
        folder=(TARGET/kind/'files').resolve()
        assert folder==Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench/sites/hospitality-release.localhost')/kind/'files'
        if folder.exists():folder.rename(destination/kind)

def restore(label,backup,folder,source_config):
    assert os.geteuid()==0,'Native MariaDB restore requires local Unix socket administrator'
    stopped()
    for name,digest in backup['files'].items():
        path=(folder/name).resolve();assert path.parent==folder.resolve() and sha(path)==digest
    public,=[folder/name for name in backup['files'] if '-files.' in name and '-private-files.' not in name]
    private,=[folder/name for name in backup['files'] if '-private-files.' in name]
    quarantine_media(label)
    current=json.loads(CONFIG.read_text());current['db_socket']='/run/mysqld/mysqld.sock'
    if source_config.get('encryption_key'):current['encryption_key']=source_config['encryption_key']
    current.update(pause_scheduler=True,allow_tests=True,hospitality_integration_test_site=True,
        host_name='http://hospitality-release.localhost:8091')
    current.pop('maintenance_mode',None);write_private(CONFIG,current)
    proof=command(label,[str(BENCH/'env/bin/python'),'-m','frappe.utils.bench_helper','frappe','--site',SITE,'restore',
        str(folder/backup['database']),'--db-root-username','root','--db-root-password','local-unix-socket-auth',
        '--with-public-files',str(public),'--with-private-files',str(private)],cwd=BENCH/'sites')
    for path in [TARGET]+list(TARGET.rglob('*')):
        assert not path.is_symlink() and path.resolve().is_relative_to(TARGET.resolve())
        os.chown(path,owner.pw_uid,owner.pw_gid)
    return proof

state=json.loads(DATA.read_text()) if DATA.exists() else {}
proof=dict(action=args.action,label=args.label,at_utc=datetime.now(timezone.utc).isoformat(),site=SITE)
if args.action=='snapshot-original':
    assert not state and hospitality_suite.__version__=='0.8.8' and git('rev-parse','HEAD')=='be67c92d3b22b70f9a4a17d0841eb829a8e38f02'
    stopped();assert not git('status','--porcelain')
    original=fingerprint();record=backup(args.label)
    users=TARGET/'private/hospitality-demo-users.json'
    if users.exists():shutil.copyfile(users,STATE/'original-demo-users.json');(STATE/'original-demo-users.json').chmod(0o600)
    state=dict(original=original,original_config=config,original_backup=record,previous_revision=git('rev-parse','HEAD'))
    proof.update(previous_revision=state['previous_revision'],counts=original['counts'],original_physical_files=len(original['physical_files']),backup_verified=True)
elif args.action=='restore-source':
    assert state and 'baseline' not in state
    source=json.loads((MAIN/'.hospitality-final-recovery-upgrade.json').read_text())['hospitality.localhost']
    database,=[name for name in source['backup_files'] if name.endswith('-database.sql.gz')]
    record=dict(database=database,files=source['backup_files'])
    source_config=json.loads((MAIN/'sites/hospitality.localhost/site_config.json').read_text())
    proof.update(restore(args.label,record,MAIN/'sites/hospitality.localhost/private/backups',source_config))
    shutil.copyfile(MAIN/'sites/hospitality.localhost/private/hospitality-demo-users.json',TARGET/'private/hospitality-demo-users.json')
    os.chown(TARGET/'private/hospitality-demo-users.json',owner.pw_uid,owner.pw_gid)
    (TARGET/'private/hospitality-demo-users.json').chmod(0o600)
elif args.action=='baseline':
    assert 'baseline' not in state and hospitality_suite.__version__=='0.8.8'
    current=fingerprint();source=json.loads((MAIN/'.hospitality-final-recovery-upgrade.json').read_text())['hospitality.localhost']
    assert current['tables']==source['tables'] and current['private_files']==source['private_files']
    assert current['physical_files']==tree(MAIN/'sites/hospitality.localhost')
    state['baseline']=current
    proof.update(counts=current['counts'],tables=len(current['tables']),rows=sum(r['rows'] for r in current['tables'].values()),
        private_files=len(current['private_files']),physical_files=len(current['physical_files']),source_bytes_identical=True)
elif args.action=='backup-baseline':
    assert 'baseline' in state and 'baseline_backup' not in state
    stopped();state['baseline_backup']=backup(args.label);state['baseline_config']=json.loads(CONFIG.read_text())
    proof.update(backup_verified=True,previous_revision=state['previous_revision'])
elif args.action in ['checkout-current','checkout-previous']:
    stopped();assert not git('status','--porcelain')
    if args.action=='checkout-current':
        current=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        assert subprocess.run(['git','diff','--quiet','--','hospitality_suite','pyproject.toml'],cwd=ROOT).returncode==0
        assert '__version__ = "0.8.9"' in (ROOT/'hospitality_suite/__init__.py').read_text()
        assert not state.get('current_revision') or state['current_revision']==current
        state['current_revision']=current
        remote=git('remote','get-url','upstream');assert remote in [str(ROOT),'file://'+str(ROOT)]
        command(args.label+'-fetch',['git','fetch','upstream'],cwd=BENCH/'apps/hospitality_suite')
        revision=current
    else:revision=state['previous_revision']
    command(args.label,['git','checkout','--detach',revision],cwd=BENCH/'apps/hospitality_suite')
    assert git('rev-parse','HEAD')==revision and not git('status','--porcelain')
    proof.update(revision=revision,source_checkout_unchanged=True)
elif args.action in ['migrate','build','install-deps','uninstall-clean-app','install-clean-app']:
    stopped()
    if args.action in ['uninstall-clean-app','install-clean-app']:
        assert state.get('clean_restored') and not state.get('original_restored')
        assert git('rev-parse','HEAD')==state['current_revision'] and hospitality_suite.__version__=='0.8.9'
        os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
        try:
            if args.action=='uninstall-clean-app':
                counts={dt:frappe.db.count(dt) for dt,spec in SCHEMA.items() if not spec.get('child')}
                counts.update({dt:frappe.db.count(dt) for dt in ['Company','Account','Item','File','Customer','Supplier',
                    'Sales Invoice','Payment Entry','Journal Entry','GL Entry','Stock Entry','Stock Reconciliation']})
                folders=frappe.get_all('File',filters={'is_folder':1},fields=['file_name','file_url','attached_to_doctype'])
                assert {row.file_name for row in folders}=={'Home','Attachments'}
                assert all(not row.file_url and not row.attached_to_doctype for row in folders)
                counts['File']=frappe.db.count('File',{'is_folder':0})
                assert not any(counts.values()),'Uninstall is restricted to the verified empty restore'
                proof['empty_business_counts_before_uninstall']=counts
                proof['native_framework_File_folders']=len(folders)
            else:assert not frappe.db.exists('DocType','HS Property')
        finally:frappe.db.rollback();frappe.destroy()
    cmd=(['/home/frappe/.local/bin/bench','--site',SITE,'uninstall-app','hospitality_suite','--yes','--no-backup'] if args.action=='uninstall-clean-app'
        else ['/home/frappe/.local/bin/bench','--site',SITE,'install-app','hospitality_suite'] if args.action=='install-clean-app'
        else [str(BENCH/'env/bin/python'),'-m','pip','install','--no-build-isolation','--no-deps','-e','apps/hospitality_suite[test]'] if args.action=='install-deps'
        else ['/home/frappe/.local/bin/bench','build','--app','hospitality_suite'] if args.action=='build'
        else ['/home/frappe/.local/bin/bench','--site',SITE,'migrate'])
    proof.update(command(args.label,cmd),revision=git('rev-parse','HEAD'),version=hospitality_suite.__version__)
elif args.action=='check':
    assert args.expect and git('rev-parse','HEAD')==state[args.expect+'_revision']
    current=fingerprint();assert current==state['baseline'],'Business DB/private/physical files differ from the exact baseline'
    proof.update(revision=git('rev-parse','HEAD'),version=hospitality_suite.__version__,counts=current['counts'],
        all_business_rows_and_columns_identical=True,all_physical_files_identical=True,
        tables=len(current['tables']),rows=sum(r['rows'] for r in current['tables'].values()),private_files=len(current['private_files']))
    state.setdefault('checks',{})[args.label]=dict(revision=git('rev-parse','HEAD'),all_business_and_file_bytes_identical=True)
elif args.action=='inject-asset-fault':
    assert 'fault' not in state and git('rev-parse','HEAD')==state['current_revision']
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        from hospitality_suite.service import operation
        from frappe.utils.file_manager import save_file
        frappe.set_user('Administrator');prop=frappe.get_doc('HS Property',{'property_name':'Hotel Jardín Demo'})
        with operation():prop.property_name+=' · SONDA F26';prop.save()
        file=save_file('sonda-f26-posterior-al-respaldo.txt',b'Synthetic deployment probe; no operational transaction.',prop.doctype,prop.name,is_private=1)
        frappe.db.commit();state['probe']=dict(property=prop.name,file=file.name,file_url=file.file_url)
    finally:frappe.destroy()
    assets=json.loads((BENCH/'sites/assets/assets.json').read_text());bundle=assets['hospitality.bundle.js']
    path=(BENCH/'sites'/bundle.lstrip('/')).resolve()
    assert path.is_relative_to((BENCH/'apps/hospitality_suite/hospitality_suite/public/dist').resolve()) and path.is_file()
    destination=STATE/'failed-deployment-bundle.js';assert not destination.exists()
    digest=sha(path);path.rename(destination);destination.chmod(0o600)
    state['fault']=dict(bundle=bundle,sha256=digest,preserved=str(destination))
    proof.update(controlled_asset_fault=True,bundle=bundle,synthetic_DB_and_private_file_probe=True,
        no_new_operational_financial_activity=True,failed_asset_bytes_preserved=True)
elif args.action=='backup-failed':
    assert 'fault' in state and 'failed_backup' not in state
    stopped();state['failed_fingerprint']=fingerprint();state['failed_backup']=backup(args.label)
    assert state['failed_fingerprint']!=state['baseline']
    proof.update(failed_state_preserved_before_rollback=True,counts=state['failed_fingerprint']['counts'])
elif args.action=='restore-baseline':
    assert 'failed_backup' in state
    proof.update(restore(args.label,state['baseline_backup'],TARGET/'private/backups',state['baseline_config']))
elif args.action=='restore-original':
    native=json.loads((ROOT/'docs/evidence/final-recovery-native-run.json').read_text())
    assert native['tests']==410 and not any(native[k] for k in ['exit_code','errors','failures','skipped'])
    state['native_test_files']=tree(TARGET)
    proof['native_test_physical_files_archived']=len(state['native_test_files'])
    proof.update(restore(args.label,state['original_backup'],TARGET/'private/backups',state['original_config']))
    if (STATE/'original-demo-users.json').exists():
        shutil.copyfile(STATE/'original-demo-users.json',TARGET/'private/hospitality-demo-users.json')
        os.chown(TARGET/'private/hospitality-demo-users.json',owner.pw_uid,owner.pw_gid)
    state['original_restored']=True
elif args.action=='restore-clean':
    assert 'failed_backup' in state and 'redeployed-current' in state.get('checks',{})
    clean=json.loads((BENCH.parents[1]/'clean-backup.json').read_text())
    assert clean['site']==SITE
    database,=[name for name in clean['files'] if name.endswith('-database.sql.gz')]
    proof.update(restore(args.label,dict(database=database,files=clean['files']),TARGET/'private/backups',state['original_config']))
    state['clean_restored']=True
elif args.action=='check-original':
    assert state.get('original_restored') and git('rev-parse','HEAD')==state['current_revision']
    current=fingerprint();assert current==state['original']
    proof.update(original_release_rows_and_bytes_restored=True,original_physical_files=len(current['physical_files']),counts=current['counts'],
        current_revision=state['current_revision'],current_version=hospitality_suite.__version__)
    os.chdir(BENCH/'sites');frappe.init(site=SITE,sites_path=str(BENCH/'sites'));frappe.connect()
    try:
        versions={r.app_name:r.app_version for r in frappe.get_single('Installed Applications').installed_applications}
        assert versions=={'frappe':'16.52.0','erpnext':'16.51.1','hospitality_suite':'0.8.9'}
        proof['registered_versions']=versions
    finally:frappe.db.rollback();frappe.destroy()
write_private(DATA,state)
proof.update(external_providers_activated=False)
output.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({key:value for key,value in proof.items() if key not in ['counts']},ensure_ascii=False))
