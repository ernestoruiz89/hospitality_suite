"""Loopback-only fault proxy: discard one successful synthetic sale response.

No app monkeypatches or payment simulations. The real backend finishes its
request normally; only its response to the browser is lost. Keep this helper
out of deployment process configurations.
"""
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
from urllib.parse import parse_qs

bench=Path("/home/frappe/benches/hospitality-bench")
assert json.loads((bench/"sites/hospitality.localhost/site_config.json").read_text()).get("allow_tests")
assert (bench/".hospitality-network-sale.json").exists()
state_path=bench/".hospitality-drop-response.json"
assert not state_path.exists(),"El ensayo ya tiene estado; no se vuelve a armar automáticamente"
state={"attempts":0,"dropped":0}
lock=threading.Lock()
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass
    def do_GET(self):self.forward()
    def do_POST(self):self.forward()
    def forward(self):
        length=int(self.headers.get("Content-Length",0))
        if length>5_000_000:
            self.send_error(413);return
        body=self.rfile.read(length) if length else None
        fields=parse_qs(body.decode()) if body and self.headers.get("Content-Type","").startswith("application/x-www-form-urlencoded") else {}
        action=fields.get("action",[None])[0]
        data=json.loads(fields.get("data",["{}"])[0]) if fields.get("data") else {}
        probe=self.command=="POST" and self.path.split("?")[0]=="/api/method/hospitality_suite.api.execute" and action=="direct_sale" and data.get("reference")=="UX-NET-001"
        connection=HTTPConnection("127.0.0.1",8086,timeout=90)
        headers={k:v for k,v in self.headers.items() if k.lower() not in ("connection","transfer-encoding")}
        try:
            connection.request(self.command,self.path,body=body,headers=headers)
            response=connection.getresponse();content=response.read();drop=False
            if probe and response.status==200:
                result=json.loads(content).get("message")
                if result:
                    with lock:
                        state["attempts"]+=1
                        key=fields.get("request_key",[""])[0]
                        if not state["dropped"]:
                            state.update(dropped=1,first_payload_hash=digest(data),first_key_hash=digest(key),first_result=result,backend_http_status=200)
                            drop=True
                        else:
                            state.update(same_payload=state["first_payload_hash"]==digest(data),same_key=state["first_key_hash"]==digest(key),same_result=state["first_result"]==result,retry_result=result)
                        state_path.write_text(json.dumps(state),encoding="utf-8");state_path.chmod(0o600)
                    print(json.dumps(dict(synthetic_sale=True,response_dropped=drop,successful_backend_requests=state["attempts"])),flush=True)
            if drop:
                self.close_connection=True
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(response.status)
            for key,value in response.getheaders():
                if key.lower() not in ("content-length","connection","transfer-encoding"):
                    self.send_header(key,value)
            self.send_header("Content-Length",str(len(content)));self.end_headers();self.wfile.write(content)
        except (ConnectionError,OSError):
            self.close_connection=True
        finally:
            connection.close()
print("Proxy de prueba local 127.0.0.1:8087; solo UX-NET-001 puede perder una respuesta",flush=True)
ThreadingHTTPServer(("127.0.0.1",8087),Handler).serve_forever()
