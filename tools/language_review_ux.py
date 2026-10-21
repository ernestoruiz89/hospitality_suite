"""Temporary acceptance server for read-only language checks on the original baseline."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess

BENCH=Path('/home/frappe/benches/hospitality-bench')
SITE='hospitality-acceptance.localhost'
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop']);args=parser.parse_args()
config=json.loads((BENCH/'sites'/SITE/'site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config.get('pause_scheduler') and config.get('allow_tests') and config.get('hospitality_integration_test_site')
assert (BENCH/'.hospitality-language-review-ux-baseline.json').is_file()
pidfile=BENCH/'.hospitality-run/language-review-web.pid';log=pidfile.with_suffix('.log')
if args.action=='start':
    with socket.socket() as connection:assert connection.connect_ex(('127.0.0.1',8089))!=0
    with log.open('ab') as stream:
        log.chmod(0o600)
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site',SITE,'serve','--port','8089','--noreload'],cwd=BENCH,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,env={**os.environ,'DEV_SERVER':'true'})
    pidfile.write_text(str(process.pid));print('Acceptance language review server started on 8089')
elif pidfile.exists():
    process_path=Path('/proc')/pidfile.read_text().strip()
    if process_path.exists():
        command=(process_path/'cmdline').read_bytes().decode(errors='replace')
        assert SITE in command and 'serve' in command and '8089' in command
        assert (process_path/'cwd').resolve() in (BENCH,BENCH/'sites')
        os.kill(int(process_path.name),signal.SIGTERM)
    print('Temporary language review server stopped')
