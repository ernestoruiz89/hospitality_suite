"""Manage only the temporary, designated print acceptance server on port 8089."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess

BENCH = Path('/home/frappe/benches/hospitality-bench')
SITE = 'hospitality-acceptance.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['start', 'stop'])
args = parser.parse_args()
config = json.loads((BENCH / 'sites' / SITE / 'site_config.json').read_text())
assert config['db_name'] == 'hospitality_acceptance' and config.get('allow_tests') and config.get('pause_scheduler')
assert config.get('hospitality_integration_test_site') and (BENCH / '.hospitality-print-delivery-ux-baseline.json').is_file()
pidfile = BENCH / '.hospitality-run/print-delivery-web.pid'
if args.action == 'start':
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', 8089)) != 0
    with pidfile.with_suffix('.log').open('ab') as output:
        pidfile.with_suffix('.log').chmod(0o600)
        process = subprocess.Popen(['/home/frappe/.local/bin/bench', '--site', SITE, 'serve', '--port', '8089', '--noreload'],
            cwd=BENCH, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, 'DEV_SERVER': 'true'})
    pidfile.write_text(str(process.pid))
    print('Temporary print acceptance server started on 8089')
else:
    if pidfile.exists():
        proc = Path('/proc') / pidfile.read_text().strip()
        if proc.exists():
            command = (proc / 'cmdline').read_bytes().decode(errors='replace')
            assert SITE in command and 'serve' in command and '8089' in command and (proc / 'cwd').resolve() in (BENCH, BENCH / 'sites')
            os.kill(int(proc.name), signal.SIGTERM)
    print('Temporary print acceptance server stopped')
