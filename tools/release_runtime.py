"""Start/stop only the independent release test bench, with verified process ownership."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

BENCH = Path('/home/frappe/.hospitality-release-install/benches/hospitality-release-bench')
STATE = Path('/home/frappe/.hospitality-release-install/runtime')
SITE = 'hospitality-release.localhost'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['start', 'stop'])
parser.add_argument('--component', choices=['redis', 'web', 'socket', 'worker', 'all'], required=True)
args = parser.parse_args()
if args.action == 'start' and args.component in ('all', 'web', 'socket'):
    try:
        assert socket.gethostbyname(SITE) == '127.0.0.1'
    except (OSError, AssertionError):
        raise SystemExit('Configure primero el alias local con release_install.py configure-host como root') from None
assert BENCH.is_dir() and BENCH.resolve() == BENCH
config = json.loads((BENCH / 'sites/common_site_config.json').read_text())
assert config['redis_cache'] == 'redis://127.0.0.1:13003' and config['redis_queue'] == 'redis://127.0.0.1:11003'
assert config['socketio_port'] == 9003 and config['webserver_port'] == 8091
STATE.mkdir(exist_ok=True, mode=0o700)
components = {
    'redis-cache': dict(port=13003, redis='redis_cache'),
    'redis-queue': dict(port=11003, redis='redis_queue'),
    'socket': dict(port=9003, command=['/usr/bin/node', str(BENCH / 'apps/frappe/socketio.js')], marker='socketio.js'),
    'worker': dict(command=['/home/frappe/.local/bin/bench', 'worker', '--queue', 'short,default,long'], marker='worker'),
    'web': dict(port=8091, command=['/home/frappe/.local/bin/bench', '--site', SITE, 'serve', '--port', '8091', '--noreload'], marker='8091'),
}
selected = list(components) if args.component == 'all' else ['redis-cache', 'redis-queue'] if args.component == 'redis' else [args.component]
if args.action == 'stop':
    selected.reverse()


def listening(port):
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', port)) == 0


def verify_process(name, spec, pid):
    process = Path('/proc') / str(pid)
    if not process.exists():
        return False
    command = (process / 'cmdline').read_bytes().decode(errors='replace')
    cwd = (process / 'cwd').resolve()
    if spec.get('redis'):
        assert 'redis-server' in command and str(spec['port']) in command
        assert cwd == BENCH / 'config/pids'
        info = subprocess.check_output(['redis-cli', '-p', str(spec['port']), 'INFO', 'server'], text=True)
        values = dict(line.split(':', 1) for line in info.splitlines() if ':' in line and not line.startswith('#'))
        assert values['process_id'] == str(pid) and values['config_file'] == str(BENCH / 'config' / (spec['redis'] + '.conf'))
    else:
        assert spec['marker'] in command and cwd in (BENCH, BENCH / 'sites'), name
    return True


for name in selected:
    spec = components[name]
    pidfile = STATE / (name + '.pid')
    if args.action == 'stop':
        if pidfile.exists() and verify_process(name, spec, int(pidfile.read_text())):
            os.kill(int(pidfile.read_text()), signal.SIGTERM)
            for _ in range(100):
                if spec.get('port') and not listening(spec['port']):
                    break
                if not spec.get('port') and not (Path('/proc') / pidfile.read_text().strip()).exists():
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Release process did not stop: ' + name)
        print(name + ': stopped')
        continue
    if pidfile.exists() and verify_process(name, spec, int(pidfile.read_text())):
        print(name + ': already running')
        continue
    if spec.get('port'):
        assert not listening(spec['port']), 'Refuse an occupied port: ' + name
    command = spec.get('command')
    if spec.get('redis'):
        conf = BENCH / 'config' / (spec['redis'] + '.conf')
        lines = conf.read_text().splitlines()
        assert sum(line.startswith('port ') for line in lines) == 1
        conf.write_text('\n'.join('port ' + str(spec['port']) if line.startswith('port ') else line for line in lines) + '\n')
        command = ['/usr/bin/redis-server', str(conf)]
    log = STATE / (name + '.log')
    environment = {**os.environ, 'DEV_SERVER': 'true'}
    pdf = Path('/home/frappe/benches/hospitality-bench/.runtime/wkhtmltox/usr/local/bin')
    # PDF is a declared host dependency; never take app Python/assets from the source bench.
    environment['PATH'] = str(pdf) + os.pathsep + environment.get('PATH', '')
    with log.open('ab') as output:
        log.chmod(0o600)
        process = subprocess.Popen(command, cwd=BENCH, env=environment, stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    pidfile.write_text(str(process.pid))
    for _ in range(100):
        assert process.poll() is None, 'Release process exited; inspect private log: ' + name
        if not spec.get('port') or listening(spec['port']):
            break
        time.sleep(.1)
    else:
        raise RuntimeError('Release process not ready; inspect it before retrying: ' + name)
    assert verify_process(name, spec, process.pid)
    print(name + ': started')
