"""Restore the named demo backup only into a disposable cutover audit site.

Run as root in the local WSL bench. The source site is never restored or edited.
"""

import json
import os
from pathlib import Path
import pwd
import subprocess
import sys


BENCH = Path("/home/frappe/benches/hospitality-bench")
SOURCE = BENCH / "sites/hospitality.localhost/private/backups"
TARGET = BENCH / "sites/hospitality-cutover-audit.localhost"
PREFIX = "20261025_204735-hospitality_localhost"


def main():
    if sys.argv[1:] != ["--confirm-disposable-restore"]:
        raise RuntimeError("Pass --confirm-disposable-restore to replace this named test site")
    if os.geteuid() != 0 or not TARGET.is_dir() or TARGET.is_symlink():
        raise RuntimeError("Run as root with the disposable target already created")
    config_path = TARGET / "site_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("db_name") != "hospitality_cutover_audit":
        raise RuntimeError("The target is not the disposable audit database")
    files = {
        "database": SOURCE / (PREFIX + "-database.sql.gz"),
        "public": SOURCE / (PREFIX + "-files.tar"),
        "private": SOURCE / (PREFIX + "-private-files.tar"),
        "config": SOURCE / (PREFIX + "-site_config_backup.json"),
    }
    if any(path.is_symlink() or path.resolve().parent != SOURCE.resolve()
           or not path.is_file() for path in files.values()):
        raise RuntimeError("The exact complete source backup is unavailable")
    original = json.loads(files["config"].read_text(encoding="utf-8"))
    if not original.get("encryption_key"):
        raise RuntimeError("The source encryption key is missing")
    config.update(encryption_key=original["encryption_key"],
                  db_socket="/run/mysqld/mysqld.sock", allow_tests=True,
                  hospitality_allow_demo=True, pause_scheduler=True,
                  maintenance_mode=1)
    config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
    config_path.chmod(0o600)
    command = [str(BENCH / "env/bin/python"), "-m",
               "frappe.utils.bench_helper", "frappe", "--site", TARGET.name,
               "restore", str(files["database"]), "--db-root-username", "root",
               "--db-root-password", "local-unix-socket-auth",
               "--with-public-files", str(files["public"]),
               "--with-private-files", str(files["private"]), "--force"]
    log = BENCH / ".hospitality-cutover-audit-restore.log"
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=BENCH / "sites", stdin=subprocess.DEVNULL,
                                stdout=output, stderr=subprocess.STDOUT, check=False)
    log.chmod(0o600)
    owner = pwd.getpwnam("frappe")
    for path in [TARGET, *TARGET.rglob("*")]:
        if path.resolve().is_relative_to(TARGET.resolve()):
            os.chown(path, owner.pw_uid, owner.pw_gid)
    os.chown(log, owner.pw_uid, owner.pw_gid)
    if result.returncode:
        raise RuntimeError("Native restore failed; inspect the private bench log")
    print("Restored disposable cutover audit site from", PREFIX)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        sys.exit(str(exc))
