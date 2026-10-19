"""Stop only the verified isolated Socket.IO process for a browser recovery test."""
import json
import os
from pathlib import Path
import signal
import socket
import time

bench=Path("/home/frappe/benches/hospitality-bench")
assert json.loads((bench/"sites/hospitality.localhost/site_config.json").read_text()).get("allow_tests")
pid=int((bench/".hospitality-run/socketio.pid").read_text())
proc=Path(f"/proc/{pid}")
cmd=(proc/"cmdline").read_bytes().decode(errors="replace")
assert str(bench/"apps/frappe/socketio.js") in cmd and (proc/"cwd").resolve()==bench
os.kill(pid,signal.SIGTERM)
for _ in range(50):
    with socket.socket() as connection:
        connection.settimeout(.1)
        if connection.connect_ex(("127.0.0.1",9001))!=0:
            print("Socket.IO aislado detenido; reinicie con tools/run_dev.py")
            break
    time.sleep(.1)
else:
    raise RuntimeError("El puerto aislado sigue activo; no se fuerza otro proceso")
