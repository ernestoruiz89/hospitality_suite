"""Restore only the named third hospitality test site using native Bench."""
import json
import os
from pathlib import Path
import subprocess

BENCH=Path("/home/frappe/benches/hospitality-bench")
TARGET=BENCH/"sites/hospitality-restore.localhost"
SOURCE=BENCH/"sites/hospitality.localhost/private/backups"
if os.geteuid()!=0 or TARGET.resolve()!=Path("/home/frappe/benches/hospitality-bench/sites/hospitality-restore.localhost"):
    raise SystemExit("Ejecute como root solo en el bench aislado de pruebas")
config_path=TARGET/"site_config.json"
config=json.loads(config_path.read_text())
if config["db_name"]!="hospitality_restore":
    raise SystemExit("El destino no es la base aislada esperada")
database=sorted(SOURCE.glob("*-database.sql.gz"))[-1]
prefix=database.name.removesuffix("-database.sql.gz")
backup_config=json.loads((SOURCE/(prefix+"-site_config_backup.json")).read_text())
config.update(db_socket="/run/mysqld/mysqld.sock",allow_tests=True,hospitality_allow_demo=True,pause_scheduler=True)
if backup_config.get("encryption_key"):
    config["encryption_key"]=backup_config["encryption_key"]
config_path.write_text(json.dumps(config,indent=1))
config_path.chmod(0o600)
args=[str(BENCH/"env/bin/python"),"-m","frappe.utils.bench_helper","frappe","--site","hospitality-restore.localhost","restore",str(database),
      "--db-root-username","root","--db-root-password","local-unix-socket-auth",
      "--with-public-files",str(SOURCE/(prefix+"-files.tgz")),"--with-private-files",str(SOURCE/(prefix+"-private-files.tgz"))]
log=BENCH/".hospitality-restore.log"
with log.open("w") as output:
    result=subprocess.run(args,cwd=BENCH/"sites",stdout=output,stderr=subprocess.STDOUT)
log.chmod(0o600)
import pwd
owner=pwd.getpwnam("frappe")
os.chown(log,owner.pw_uid,owner.pw_gid)
for path in [TARGET]+list(TARGET.rglob("*")):
    if path.resolve().is_relative_to(TARGET.resolve()):
        os.chown(path,owner.pw_uid,owner.pw_gid)
print("Restauración nativa:","correcta" if result.returncode==0 else "fallida; revise el registro privado", "→ hospitality-restore.localhost")
raise SystemExit(result.returncode)
