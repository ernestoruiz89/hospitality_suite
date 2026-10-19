"""Temporary local web server only for the named restored development site."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['start','stop'])
args=parser.parse_args()
bench=Path('/home/frappe/benches/hospitality-bench')
site=bench/'sites/hospitality-restore.localhost'
config=json.loads((site/'site_config.json').read_text())
assert config['db_name']=='hospitality_restore' and config.get('pause_scheduler') and config.get('allow_tests')
state=bench/'.hospitality-run'
pidfile=state/'restore-web.pid'
if args.action=='stop':
    if pidfile.exists():
        process=Path('/proc')/pidfile.read_text().strip()
        if process.exists():
            command=(process/'cmdline').read_bytes().decode(errors='replace')
            assert 'serve' in command and '8088' in command and 'hospitality-restore.localhost' in command
            assert (process/'cwd').resolve() in (bench,bench/'sites')
            os.kill(int(process.name),signal.SIGTERM)
    print('Servidor temporal de restauración detenido; servidor principal intacto')
else:
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1',8088))!=0,'Puerto 8088 ocupado; no se reutiliza'
    with (state/'restore-web.log').open('ab') as log:
        (state/'restore-web.log').chmod(0o600)
        environment={**os.environ,'DEV_SERVER':'true'}
        runtime=bench/'.runtime/wkhtmltox/usr/local/bin'
        if (runtime/'wkhtmltopdf').is_file():
            environment['PATH']=str(runtime)+os.pathsep+environment.get('PATH','')
        process=subprocess.Popen(['/home/frappe/.local/bin/bench','--site','hospitality-restore.localhost','serve','--port','8088','--noreload'],cwd=bench,env=environment,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    pidfile.write_text(str(process.pid))
    print('Servidor de copia de pruebas iniciado: http://hospitality-restore.localhost:8088/app/hospitality-reception')
