"""Loopback clock emulation for the fixed disposable-site browser test only.

The shim changes the JavaScript device clock, never server timestamps or money.
No credentials, headers or request bodies are recorded. Page commands are blocked.
"""
import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

BENCH=Path('/home/frappe/benches/hospitality-bench')
ROOT=Path(__file__).resolve().parents[1]
RUN=BENCH/'.hospitality-run'
PID=RUN/'countdown-proxy.pid'
METRICS=BENCH/'.hospitality-countdown-proxy.json'
PORT=8087
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','serve','inspect']);args=parser.parse_args()
config=json.loads((BENCH/'sites/hospitality-acceptance.localhost/site_config.json').read_text())
assert config['db_name']=='hospitality_acceptance' and config['allow_tests'] and config['pause_scheduler']
assert (BENCH/'.hospitality-countdown-ui-fixture.json').is_file()


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.2)
        return sock.connect_ex(('127.0.0.1',port))==0


SHIM='''<script>
(() => {
  const RealDate=window.Date;
  let skew=86400000;
  function ProbeDate(...args) {
    if (!new.target) return new RealDate(RealDate.now()+skew).toString();
    return Reflect.construct(RealDate,args.length?args:[RealDate.now()+skew],new.target);
  }
  ProbeDate.prototype=RealDate.prototype;Object.setPrototypeOf(ProbeDate,RealDate);
  ProbeDate.now=()=>RealDate.now()+skew;window.Date=ProbeDate;
  document.addEventListener('DOMContentLoaded',()=>{
    const bar=document.createElement('section');bar.id='hs-clock-probe';
    bar.setAttribute('aria-label','Prueba del reloj del dispositivo');
    bar.style.cssText='padding:8px 12px;background:#fff3cd;color:#302600;display:flex;gap:12px;align-items:center;flex-wrap:wrap;position:fixed;bottom:0;left:0;right:0;z-index:2000;font-size:12px';
    const text=document.createElement('span'),button=document.createElement('button');
    button.type='button';button.textContent='Alternar reloj de prueba';
    const update=()=>{text.textContent='PRUEBA LOCAL · Reloj del dispositivo '+(skew>0?'+24 h':'−24 h')+' · '+new ProbeDate().toISOString();};
    button.addEventListener('click',()=>{skew=-skew;update();});
    bar.append(text,button);document.body.prepend(bar);update();
  });
})();
</script>'''.encode()


if args.action=='start':
    assert listening(8089),'Inicie primero el preview del sitio de aceptación'
    assert not listening(PORT),'El puerto de prueba ya está ocupado'
    RUN.mkdir(exist_ok=True)
    log=RUN/'countdown-proxy.log'
    with log.open('ab') as stream:
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve'],cwd=BENCH,stdin=subprocess.DEVNULL,
                                 stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    log.chmod(0o600);PID.write_text(str(process.pid));PID.chmod(0o600)
    for _ in range(30):
        if listening(PORT):break
        time.sleep(.1)
    assert listening(PORT)
    print('Reloj de prueba en http://localhost:8087; destino exclusivo 8089, sin cambios al reloj del servidor.')
elif args.action=='stop':
    pid=int(PID.read_text());process=Path('/proc')/str(pid)
    if process.exists():
        command=(process/'cmdline').read_bytes().decode(errors='replace')
        assert str(Path(__file__).resolve()) in command and 'serve' in command
        os.kill(pid,signal.SIGTERM)
        for _ in range(30):
            if not listening(PORT):break
            time.sleep(.1)
    assert not listening(PORT)
    print('Proxy de reloj detenido; 8087 cerrado.')
elif args.action=='inspect':
    proof=json.loads(METRICS.read_text())
    assert proof['html_shims']>=2 and proof['bootstrap_requests']>=2 and proof['blocked_app_writes']==0
    proof.update(loopback_only=True,target='hospitality-acceptance.localhost:8089',device_clock_only=True,
                 business_responses_unmodified=True,credentials_or_request_bodies_recorded=False)
    (ROOT/'docs/evidence/countdown-proxy.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(proof))
else:
    state=json.loads(METRICS.read_text()) if METRICS.exists() else dict(html_shims=0,bootstrap_requests=0,blocked_app_writes=0)
    lock=threading.Lock()
    def record(field):
        with lock:
            state[field]+=1;METRICS.write_text(json.dumps(state));METRICS.chmod(0o600)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.forward()
        def do_POST(self):self.forward()
        def forward(self):
            path=self.path.split('?',1)[0]
            if path.startswith('/api/method/hospitality_suite.api.'):
                method=path.rsplit('.',1)[-1]
                if method not in ('bootstrap','stay_detail','room_balances','stay_board'):
                    record('blocked_app_writes');self.send_error(403);return
                if method=='bootstrap':record('bootstrap_requests')
            length=int(self.headers.get('Content-Length',0))
            if length>1000000:self.send_error(413);return
            body=self.rfile.read(length) if length else None
            headers={key:value for key,value in self.headers.items() if key.lower() not in ('connection','transfer-encoding','accept-encoding')}
            headers['Accept-Encoding']='identity'
            connection=HTTPConnection('127.0.0.1',8089,timeout=60)
            try:
                connection.request(self.command,self.path,body=body,headers=headers)
                response=connection.getresponse();content=response.read()
                html='text/html' in response.getheader('Content-Type','') and b'<head>' in content
                if html:
                    content=content.replace(b'<head>',b'<head>'+SHIM,1);record('html_shims')
                self.send_response(response.status)
                for key,value in response.getheaders():
                    if key.lower() not in ('content-length','connection','transfer-encoding','etag'):
                        self.send_header(key,value)
                self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
            except (ConnectionError,OSError):
                self.close_connection=True
            finally:
                connection.close()
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
