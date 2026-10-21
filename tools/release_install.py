"""Provision only the named, independent WSL clean-install bench.

No existing site's settings, app links, database or processes are changed.
Native output and generated credentials stay private; receipts omit secrets.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/home/frappe/benches/hospitality-bench')
SITE = 'hospitality-release.localhost'
DATABASE = 'hospitality_release'
STATE = Path('/home/frappe/.hospitality-release-install')
BENCH = STATE / 'benches/hospitality-release-bench'
BENCH_CLI = '/home/frappe/.local/bin/bench'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['archive-failed-init', 'init', 'get-erpnext', 'get-app', 'init-db', 'create-site', 'install-app', 'migrate', 'build', 'configure-host', 'backup-clean', 'restore-clean', 'test-deps', 'sync-test-probe'])
parser.add_argument('--label')
args = parser.parse_args()
assert args.label is None or re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', args.label)
assert BENCH == Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench') and BENCH != SOURCE
STATE.mkdir(mode=0o700, exist_ok=True)
owner = pwd.getpwnam('frappe')
os.chown(STATE, owner.pw_uid, owner.pw_gid)


def run(label, command, *, cwd=BENCH, environment=None):
    path = STATE / (label + '.log')
    assert not path.exists(), 'Preserve the preceding attempt'
    print('Clean-install step: ' + label, flush=True)
    with path.open('w') as output:
        path.chmod(0o600)
        result = subprocess.run(command, cwd=cwd, env=environment, stdout=output, stderr=subprocess.STDOUT)
    os.chown(path, owner.pw_uid, owner.pw_gid)
    proof = dict(step=label, exit_code=result.returncode, native_log_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bench=str(BENCH), site=SITE, main_bench_changed=False)
    (ROOT / f'docs/evidence/release-install-{label}.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)


if args.action == 'sync-test-probe':
    installed = BENCH / 'apps/hospitality_suite'
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=installed)
    original = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=installed, text=True).strip()
    current = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    allowed = {'hospitality_suite/tests/' + name for name in ['concurrency.py', 'setup.py', 'test_print_delivery.py', 'test_tariff_explanations.py']}
    changed = set(subprocess.check_output(['git', 'diff', '--name-only', original, current, '--', 'hospitality_suite'], cwd=ROOT, text=True).splitlines())
    assert changed and changed <= allowed
    prefix = args.label or 'sync-probe'
    run(prefix + '-fetch', ['git', 'fetch', 'upstream'], cwd=installed)
    run(prefix + '-checkout', ['git', 'checkout', '--detach', current], cwd=installed)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=installed, text=True).strip() == current
elif args.action == 'restore-clean':
    assert os.geteuid() == 0
    config_path = BENCH / 'sites' / SITE / 'site_config.json'
    config = json.loads(config_path.read_text())
    assert config['db_name'] == DATABASE and config.get('pause_scheduler') and config.get('allow_tests')
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1', 8091)) != 0, 'Stop the release web first'
    for name in ['web', 'worker', 'socket']:
        pidfile = STATE / 'runtime' / (name + '.pid')
        assert not pidfile.exists() or not (Path('/proc') / pidfile.read_text().strip()).exists(), 'Stop release runtime before restoring'
    backup = json.loads((STATE / 'clean-backup.json').read_text())
    assert backup['site'] == SITE
    backups = BENCH / 'sites' / SITE / 'private/backups'
    for name, digest in backup['files'].items():
        path = (backups / name).resolve()
        assert path.parent == backups.resolve() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
    database, = [backups / name for name in backup['files'] if name.endswith('-database.sql.gz')]
    public, = [backups / name for name in backup['files'] if '-files.' in name and '-private-files.' not in name]
    private, = [backups / name for name in backup['files'] if '-private-files.' in name]
    config['db_socket'] = '/run/mysqld/mysqld.sock'
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    config_path.chmod(0o600)
    run(args.label or 'restore-clean', [str(BENCH / 'env/bin/python'), '-m', 'frappe.utils.bench_helper', 'frappe', '--site', SITE,
        'restore', str(database), '--db-root-username', 'root', '--db-root-password', 'local-unix-socket-auth',
        '--with-public-files', str(public), '--with-private-files', str(private)], cwd=BENCH / 'sites')
    target = BENCH / 'sites' / SITE
    for path in [target] + list(target.rglob('*')):
        assert path.resolve().is_relative_to(target.resolve())
        os.chown(path, owner.pw_uid, owner.pw_gid)
elif args.action == 'configure-host':
    assert os.geteuid() == 0
    hosts = Path('/etc/hosts')
    original = hosts.read_text()
    addresses = [line.split('#', 1)[0].split()[0] for line in original.splitlines()
        if SITE in line.split('#', 1)[0].split()[1:]]
    assert not addresses or set(addresses) == {'127.0.0.1'}, 'Conflicting release hostname; no rewrite'
    if not addresses:
        with hosts.open('a') as output:
            output.write(('' if original.endswith('\n') else '\n') + '127.0.0.1 ' + SITE + '\n')
        assert hosts.read_text().startswith(original)
    print('Named release origin resolves locally; existing hosts preserved')
elif args.action == 'archive-failed-init':
    failed = Path('/home/frappe/benches/hospitality-release-bench')
    target = STATE / 'failed-init-bench'
    assert failed.resolve() == failed and not target.exists()
    assert json.loads((ROOT / 'docs/evidence/release-install-init.json').read_text())['exit_code'] == 1
    assert not list((failed / 'sites').glob('*/site_config.json')) and not list((failed / 'apps').iterdir())
    failed.rename(target)
    print('Uninitialized, failed bench preserved under the private test directory')
elif args.action == 'init':
    assert os.geteuid() == owner.pw_uid and not BENCH.exists()
    for port in (11003, 13003, 8091, 9003):
        with socket.socket() as connection:
            assert connection.connect_ex(('127.0.0.1', port)) != 0, f'Port {port} is already used'
    # Reuse tested versions, never an editable path or a credential-bearing URL.
    constraints = STATE / 'constraints.txt'
    excluded = {'frappe', 'erpnext', 'hospitality-suite', 'hospitality_suite', 'pip'}
    packages = sorted({f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions()
        if d.metadata['Name'].lower() not in excluded})
    content = '\n'.join(packages) + '\n'
    if constraints.exists():
        assert constraints.read_text() == content
    else:
        constraints.write_text(content)
    constraints.chmod(0o600)
    environment = {**os.environ, 'PIP_CONSTRAINT': str(constraints), 'UV_CONSTRAINT': str(constraints)}
    BENCH.parent.mkdir(exist_ok=True)
    run('init-isolated-parent', [BENCH_CLI, 'init', '--frappe-path', str(SOURCE / 'apps/frappe'), '--frappe-branch', 'version-16',
        '--python', '/usr/bin/python3.14', '--skip-assets', '--no-backups', str(BENCH)],
        cwd=BENCH.parent, environment=environment)
    config = BENCH / 'sites/common_site_config.json'
    data = json.loads(config.read_text())
    data.update(redis_cache='redis://127.0.0.1:13003', redis_queue='redis://127.0.0.1:11003',
        redis_socketio='redis://127.0.0.1:11003', socketio_port=9003, webserver_port=8091)
    config.write_text(json.dumps(data, indent=2) + '\n')
elif args.action == 'get-erpnext':
    assert not (BENCH / 'apps/erpnext').exists()
    environment = {**os.environ, 'PIP_CONSTRAINT': str(STATE / 'constraints.txt'), 'UV_CONSTRAINT': str(STATE / 'constraints.txt')}
    run('get-erpnext', [BENCH_CLI, 'get-app', '--branch', 'version-16', '--skip-assets', str(SOURCE / 'apps/erpnext')], environment=environment)
elif args.action == 'init-db':
    assert os.geteuid() == 0 and BENCH.is_dir()
    private = STATE / 'credentials.json'
    assert not private.exists()
    check = subprocess.check_output(['mariadb', '-N', '-e',
        "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='hospitality_release'"], text=True)
    assert check.strip() == '0', 'Refuse an existing database'
    check = subprocess.check_output(['mariadb', '-N', '-e',
        "SELECT COUNT(*) FROM mysql.user WHERE User='hospitality_release'"], text=True)
    assert check.strip() == '0', 'Refuse an existing database user'
    credentials = dict(db_password=secrets.token_urlsafe(32), admin_password=secrets.token_urlsafe(24))
    sql = (f'CREATE DATABASE {DATABASE} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; '
        f"CREATE USER '{DATABASE}'@'localhost' IDENTIFIED BY '{credentials['db_password']}'; "
        f"GRANT ALL PRIVILEGES ON {DATABASE}.* TO '{DATABASE}'@'localhost';")
    result = subprocess.run(['mariadb'], input=sql, capture_output=True, text=True)
    assert result.returncode == 0, 'Isolated database initialization failed; no credentials printed'
    private.write_text(json.dumps(credentials))
    private.chmod(0o600)
    os.chown(private, owner.pw_uid, owner.pw_gid)
    print('Isolated release database and private credentials created')
elif args.action == 'create-site':
    assert os.geteuid() == owner.pw_uid and not (BENCH / 'sites' / SITE).exists()
    credentials = json.loads((STATE / 'credentials.json').read_text())
    run('create-site', [BENCH_CLI, 'new-site', SITE, '--db-name', DATABASE, '--db-user', DATABASE,
        '--db-password', credentials['db_password'], '--admin-password', credentials['admin_password'],
        '--no-setup-db', '--install-app', 'erpnext'])
    config = BENCH / 'sites' / SITE / 'site_config.json'
    data = json.loads(config.read_text())
    assert data['db_name'] == DATABASE
    data.update(allow_tests=True, hospitality_integration_test_site=True, pause_scheduler=True, host_name='http://hospitality-release.localhost:8091')
    config.write_text(json.dumps(data, indent=2) + '\n')
    config.chmod(0o600)
elif args.action == 'get-app':
    assert not (BENCH / 'apps/hospitality_suite').exists()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert subprocess.run(['git', 'diff', '--quiet', '--', 'hospitality_suite', 'pyproject.toml', 'LICENSE'], cwd=ROOT).returncode == 0
    frozen = STATE / 'source-revision.txt'
    assert not frozen.exists()
    frozen.write_text(revision + '\n')
    package = ROOT / 'docs/evidence/release-install-package.json'
    if package.exists():
        assert json.loads(package.read_text())['revision'] == revision
    environment = {**os.environ, 'PIP_CONSTRAINT': str(STATE / 'constraints.txt'), 'UV_CONSTRAINT': str(STATE / 'constraints.txt')}
    run('get-app', [BENCH_CLI, 'get-app', 'hospitality_suite', str(ROOT), '--skip-assets'], environment=environment)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=BENCH / 'apps/hospitality_suite', text=True).strip()
    assert actual == revision and not (BENCH / 'apps/hospitality_suite').is_symlink()
else:
    config = json.loads((BENCH / 'sites' / SITE / 'site_config.json').read_text())
    assert config['db_name'] == DATABASE and config.get('pause_scheduler') and config.get('allow_tests')
    command = [BENCH_CLI, '--site', SITE, args.action]
    if args.action == 'install-app':
        command.append('hospitality_suite')
    elif args.action == 'build':
        command = [BENCH_CLI, 'build']
    elif args.action == 'backup-clean':
        clean = json.loads((ROOT / 'docs/evidence/release-install-clean.json').read_text())
        assert clean['no_implicit_demo'] and not any(clean['empty_business_counts'].values())
        assert not (STATE / 'clean-backup.json').exists()
        command = [BENCH_CLI, '--site', SITE, 'backup', '--with-files']
    elif args.action == 'test-deps':
        command = [BENCH_CLI, 'pip', 'install', '-e', 'apps/hospitality_suite[test]']
    run(args.label or args.action, command)
    if args.action == 'backup-clean':
        backups = BENCH / 'sites' / SITE / 'private/backups'
        database = max(backups.glob('*-database.sql.gz'), key=lambda path: path.stat().st_mtime)
        files = list(backups.glob(database.name.removesuffix('-database.sql.gz') + '*'))
        assert len(files) >= 4
        for path in files:
            path.chmod(0o600)
        (STATE / 'clean-backup.json').write_text(json.dumps(dict(site=SITE,
            files={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files})))
        (STATE / 'clean-backup.json').chmod(0o600)
