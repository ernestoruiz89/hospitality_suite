"""Preserve complete file trees, including native restore's unreferenced leftovers."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import tarfile

import frappe

ROOT = Path(__file__).resolve().parents[1]
BENCH = Path('/home/frappe/benches/hospitality-bench')
SITE = 'hospitality-acceptance.localhost'
TARGET = BENCH / 'sites' / SITE
BASE = BENCH / '.hospitality-secondary-acceptance-ux-baseline.json'
TREE = BENCH / '.hospitality-secondary-acceptance-files-baseline.json'
CREATED = BENCH / '.hospitality-secondary-acceptance-created-files.json'
NATIVE = BENCH / '.hospitality-secondary-acceptance-native-files-before.json'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['before-from-backup', 'observe', 'native-before', 'native-after', 'cleanup', 'verify'])
parser.add_argument('--label', default='files')
args = parser.parse_args()
assert TARGET.resolve() == Path('/home/frappe/benches/hospitality-bench/sites/hospitality-acceptance.localhost')
config = json.loads((TARGET / 'site_config.json').read_text())
assert config['db_name'] == 'hospitality_acceptance' and config.get('allow_tests') and config.get('pause_scheduler') and config.get('hospitality_integration_test_site')
backup = json.loads(BASE.read_text())
sha = lambda value: hashlib.sha256(value).hexdigest()
def disk_tree():
    result = {}
    for kind in ['public', 'private']:
        folder = TARGET / kind / 'files'
        for path in folder.rglob('*'):
            assert not path.is_symlink(), 'Review file-tree symlinks explicitly'
            if path.is_file():
                assert path.resolve().is_relative_to(folder.resolve())
                result[path.relative_to(TARGET).as_posix()] = sha(path.read_bytes())
    return result
if args.action == 'before-from-backup':
    assert not TREE.exists()
    original = {}
    for kind in ['public', 'private']:
        path = TARGET / 'private/backups' / backup[kind + '_files']
        assert sha(path.read_bytes()) == backup['backup_files'][path.name]
        with tarfile.open(path, 'r:*') as archive:
            for member in archive:
                if not member.isfile():
                    continue
                parts = PurePosixPath(member.name).parts
                index = parts.index(kind)
                assert parts[index - 1] == SITE and parts[index + 1] == 'files' and '..' not in parts
                name = PurePosixPath(*parts[index:]).as_posix()
                assert name not in original
                original[name] = sha(archive.extractfile(member).read())
    TREE.write_text(json.dumps(dict(backup_baseline_sha256=sha(BASE.read_bytes()), tree=original)))
    TREE.chmod(0o600)
    print(json.dumps(dict(baseline_from_pre_UI_backups=True, files=len(original), metadata_only=False)))
    raise SystemExit()
baseline = json.loads(TREE.read_text())
assert baseline['backup_baseline_sha256'] == sha(BASE.read_bytes())
original = baseline['tree']
current = disk_tree()
if args.action in ['native-before', 'native-after']:
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', 8089)) != 0, 'Stop the temporary UI writer first'
    assert all(current.get(name) == digest for name, digest in original.items())
    sources = {path.relative_to(ROOT).as_posix(): sha(path.read_bytes())
        for path in (ROOT / 'hospitality_suite').rglob('*.py')}
    if args.action == 'native-before':
        assert not NATIVE.exists() and current == original
        NATIVE.write_text(json.dumps(dict(tree=current, sources=sources)))
        NATIVE.chmod(0o600)
        print(json.dumps(dict(native_before_files=len(current), all_original_files_preserved=True)))
        raise SystemExit()
    before = json.loads(NATIVE.read_text())
    assert before['tree'] == original and before['sources'] == sources
    report = ROOT / 'docs/evidence/secondary-acceptance-native-run.json'
    run = json.loads(report.read_text())
    assert run['site'] == SITE and run['exit_code'] == 0 and run['tests'] == 405
    assert not any(run[key] for key in ['errors', 'failures', 'skipped'])
    assert run['raw_log_sha256'] == sha((ROOT / '.local/secondary-acceptance/native-full-1.log').read_bytes())
    created = json.loads(CREATED.read_text())
    for name in set(current) - set(before['tree']):
        path = TARGET / name
        parts = PurePosixPath(name).parts
        assert parts[0] in ['public', 'private'] and parts[1] == 'files'
        assert path.resolve().is_relative_to((TARGET / parts[0] / 'files').resolve())
        assert name not in created, 'Do not reclassify a preceding upload'
        created[name] = dict(sha256=current[name], url=('/private' if parts[0] == 'private' else '')
            + '/files/' + PurePosixPath(*parts[2:]).as_posix(), origin='protected-native-405',
            successful_run_sha256=sha(report.read_bytes()))
    CREATED.write_text(json.dumps(created))
    CREATED.chmod(0o600)
    print(json.dumps(dict(native_new_physical_files=len(set(current) - set(before['tree'])),
        all_original_files_preserved=True, successful_native_cases=run['tests'])))
    raise SystemExit()
if args.action == 'verify':
    assert current == original, 'File tree differs from the pre-UI archives'
    proof = dict(physical_file_tree_restored=True, files=len(original),
        tree_sha256=sha(json.dumps(current, sort_keys=True).encode()), baseline_sha256=sha(TREE.read_bytes()))
    (ROOT / 'docs/evidence/secondary-acceptance-files-restored.json').write_text(json.dumps(proof, indent=2) + '\n', newline='\n')
    print(json.dumps(proof))
    raise SystemExit()
os.chdir(BENCH / 'sites')
frappe.init(site=SITE, sites_path=str(BENCH / 'sites'))
frappe.connect()
try:
    from hospitality_suite.tests.setup import require_test_site
    require_test_site(paused=True)
    frappe.set_user('Administrator')
    created = json.loads(CREATED.read_text()) if CREATED.exists() else {}
    if args.action == 'observe':
        allowed = [ROOT / '.local' / name for name in ['secondary-acceptance-evidence.txt', 'secondary-incident-evidence.txt', 'secondary-retention-identification.txt']]
        contents = {sha(path.read_bytes()) for path in allowed if path.exists()}
        for name, digest in current.items():
            if name in original:
                assert original[name] == digest
                continue
            path = (TARGET / name).resolve()
            assert path.is_relative_to((TARGET / 'private/files').resolve()) and digest in contents
            url = '/private/files/' + path.relative_to(TARGET / 'private/files').as_posix()
            rows = frappe.get_all('File', filters={'file_url': url, 'is_private': 1},
                fields=['name', 'owner', 'attached_to_doctype', 'attached_to_name'])
            assert rows
            for row in rows:
                assert row.owner.endswith('@hospitality.example.invalid')
                assert row.attached_to_doctype in ['HS Maintenance Order', 'HS Incident', 'HS Guest']
                assert frappe.db.get_value(row.attached_to_doctype, row.attached_to_name, 'property') == json.loads((TARGET / 'private/secondary-acceptance-fixture.json').read_text())['property']
            created[name] = dict(sha256=digest, url=url, attachments=rows)
        CREATED.write_text(json.dumps(created))
        CREATED.chmod(0o600)
        print(json.dumps(dict(known_synthetic_uploaded_files=len(created), all_original_files_unchanged=True)))
    else:
        receipt = json.loads((BENCH / '.hospitality-secondary-acceptance-ux-restored-receipt.json').read_text())
        assert receipt['site'] == SITE and receipt['baseline_sha256'] == sha(BASE.read_bytes())
        extra = set(current) - set(original)
        assert extra <= set(created), 'Unregistered files must be reviewed; do not remove them'
        quarantine = BENCH / '.hospitality-secondary-acceptance-file-quarantine'
        quarantine.mkdir(mode=0o700, exist_ok=True)
        preserved = 0
        for name in extra:
            record = created[name]
            path = (TARGET / name).resolve()
            parts = PurePosixPath(name).parts
            assert parts[0] in ['public', 'private'] and parts[1] == 'files'
            assert path.is_relative_to((TARGET / parts[0] / 'files').resolve())
            assert current[name] == record['sha256'] and not frappe.db.exists('File', {'file_url': record['url']})
            destination = quarantine / (record['sha256'] + '-' + path.name)
            if destination.exists():
                assert sha(destination.read_bytes()) == record['sha256']
            else:
                shutil.copyfile(path, destination)
                destination.chmod(0o600)
            assert sha(destination.read_bytes()) == record['sha256']
            path.unlink()
            preserved += 1
        assert disk_tree() == original
        print(json.dumps(dict(restored_file_tree=True, synthetic_leftovers_preserved_outside_site=preserved)))
finally:
    frappe.db.rollback()
    frappe.destroy()
