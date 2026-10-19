"""Start only the isolated WSL development bench; keep credentials out of logs."""
import json
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import signal
import time

BENCH=Path("/home/frappe/benches/hospitality-bench")
SITE="hospitality.localhost"


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(("127.0.0.1",port))==0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--restart-web",action="store_true")
    args=parser.parse_args()
    if os.name!="posix" or not (BENCH/"sites"/SITE/"site_config.json").exists():
        raise SystemExit("Ejecute como frappe dentro de WSL, después de crear el sitio aislado")
    bench="/home/frappe/.local/bin/bench"
    config=json.loads((BENCH/"sites/common_site_config.json").read_text())
    if config.get("redis_cache")!="redis://127.0.0.1:13001" or config.get("redis_queue")!="redis://127.0.0.1:11001":
        raise SystemExit("Se requieren Redis aislados de este bench")
    state=BENCH/".hospitality-run"
    state.mkdir(exist_ok=True,mode=0o700)
    for name,port in (("cache",13001),("queue",11001)):
        if not port_open(port):
            subprocess.run(["redis-server",str(BENCH/f"config/redis_{name}.conf"),"--daemonize","yes"],cwd=BENCH,check=True)
    commands={
        "web":([bench,"--site",SITE,"serve","--port","8086","--noreload"],8086),
        "socketio":([shutil.which("node"),str(BENCH/"apps/frappe/socketio.js")],9001),
        "worker":([bench,"worker","--queue","short,default,long"],None),
        "scheduler":([bench,"schedule"],None),
    }
    for name,(command,port) in commands.items():
        pidfile=state/(name+".pid")
        if name=="web" and args.restart_web and pidfile.exists():
            pid=int(pidfile.read_text())
            process_path=Path(f"/proc/{pid}")
            if process_path.exists():
                cmdline=(process_path/"cmdline").read_bytes().decode(errors="replace")
                cwd=(process_path/"cwd").resolve()
                if "serve" not in cmdline or "8086" not in cmdline or cwd not in (BENCH,BENCH/"sites"):
                    raise SystemExit("El PID no coincide con el servidor aislado; no se interrumpe")
                os.kill(pid,signal.SIGTERM)
                for _ in range(50):
                    if not port_open(8086):
                        break
                    time.sleep(.1)
                if port_open(8086):
                    raise SystemExit("El servidor no se detuvo todavía; revise su registro")
        if port and port_open(port):
            print(name+": puerto activo")
            continue
        if pidfile.exists():
            pid=pidfile.read_text().strip()
            cmdline=Path(f"/proc/{pid}/cmdline")
            if cmdline.exists() and name in ("worker","scheduler") and ("worker" if name=="worker" else "schedule") in cmdline.read_bytes().decode(errors="replace"):
                print(name+": proceso activo")
                continue
        with (state/(name+".log")).open("ab") as log:
            process=subprocess.Popen(command,cwd=BENCH,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        pidfile.write_text(str(process.pid))
        print(name+": iniciado")
    subprocess.run([bench,"--site",SITE,"enable-scheduler"],cwd=BENCH,check=True)
    print("Sitio de pruebas: http://localhost:8086/app/hospitality-reception")
    print("Registros:",state)


if __name__=="__main__":
    main()
