"""Restore the frozen synthetic PMS counter-sale backup into a new test site.

Run as root in the local WSL bench with ``--create``. The fixed destination
must not exist; this script never deletes or overwrites a site or database.
"""

import atexit
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import subprocess
import sys


BENCH = Path("/home/frappe/frappe-bench")
SOURCE = "hs-erp-smoke-persistent.local"
TARGET = "hs-erp-smoke-direct-return.local"
TARGET_DB = "hs_erp_direct_return_20261026"
PREFIX = "20261026_152611-hs-erp-smoke-persistent_local"
ROLES = {
    "database": "database.sql.gz",
    "private_files": "private-files.tar",
    "public_files": "files.tar",
    "site_config": "site_config_backup.json",
}
MANIFEST = BENCH / "sites" / SOURCE / "private/files/persistent-counter-final-backup-manifest.json"
BACKUPS = BENCH / "sites" / SOURCE / "private/backups"
DESTINATION = BENCH / "sites" / TARGET
LOG = BENCH / ".hs-direct-return-clone-restore.log"


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(arguments, output):
    command = [str(BENCH / "env/bin/python"), "-m",
        "frappe.utils.bench_helper", "frappe", *arguments]
    result = subprocess.run(command, cwd=BENCH / "sites", stdin=subprocess.DEVNULL,
        stdout=output, stderr=subprocess.STDOUT, timeout=600, check=False)
    if result.returncode:
        raise RuntimeError("Falló la restauración aislada; consulte el registro privado")


def _repair_ownership():
    owner = pwd.getpwnam("frappe")
    if DESTINATION.is_dir() and not DESTINATION.is_symlink():
        for path in (DESTINATION, *DESTINATION.rglob("*")):
            if path.resolve().is_relative_to(DESTINATION.resolve()):
                os.chown(path, owner.pw_uid, owner.pw_gid)
    if LOG.is_file():
        os.chown(LOG, owner.pw_uid, owner.pw_gid)
    for path in (BENCH / "logs").glob("database.log*"):
        if path.is_file() and path.stat().st_uid == 0:
            os.chown(path, owner.pw_uid, owner.pw_gid)


def main():
    if (sys.argv[1:] != ["--create"] or os.geteuid() != 0 or
            BENCH.resolve() != Path("/home/frappe/frappe-bench") or
            DESTINATION.exists() or DESTINATION.is_symlink()):
        raise RuntimeError("Use root y un destino de ensayo nuevo con --create")
    if subprocess.run(["mariadb", "--batch", "--skip-column-names", "-e",
            f"SHOW DATABASES LIKE '{TARGET_DB}'"], check=True,
            capture_output=True, text=True).stdout.strip():
        raise RuntimeError("La base de ensayo ya existe")
    if MANIFEST.is_symlink() or not MANIFEST.is_file():
        raise RuntimeError("Falta el manifiesto del respaldo PMS")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if set(manifest) != set(ROLES):
        raise RuntimeError("El manifiesto PMS no contiene cuatro archivos")
    files = {}
    for role, suffix in ROLES.items():
        row = manifest[role]
        expected_name = f"{PREFIX}-{suffix}"
        if (set(row) != {"name", "sha256"} or
                row["name"] != expected_name or
                not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
            raise RuntimeError("El respaldo PMS no coincide con el corte sintético")
        path = BACKUPS / expected_name
        if (path.is_symlink() or path.resolve().parent != BACKUPS.resolve() or
                not path.is_file() or _sha256(path) != row["sha256"]):
            raise RuntimeError("El archivo de respaldo PMS cambió o falta")
        files[role] = path
    backup_config = json.loads(files["site_config"].read_text(encoding="utf-8"))
    if not backup_config.get("encryption_key"):
        raise RuntimeError("El respaldo PMS no conserva la clave de cifrado")
    atexit.register(_repair_ownership)
    with LOG.open("w", encoding="utf-8") as output:
        os.chmod(LOG, 0o600)
        _run(["new-site", TARGET, "--db-name", TARGET_DB,
            "--db-socket", "/run/mysqld/mysqld.sock",
            "--db-root-username", "root", "--db-root-password",
            "local-unix-socket-auth", "--admin-password",
            secrets.token_urlsafe(24)], output)
        config_path = DESTINATION / "site_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("db_name") != TARGET_DB:
            raise RuntimeError("El sitio nuevo no usa la base aislada")
        config.update(encryption_key=backup_config["encryption_key"],
            pause_scheduler=1, maintenance_mode=1, allow_tests=True)
        config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
        config_path.chmod(0o600)
        _run(["--site", TARGET, "restore", str(files["database"]),
            "--db-root-username", "root", "--db-root-password",
            "local-unix-socket-auth", "--with-public-files",
            str(files["public_files"]), "--with-private-files",
            str(files["private_files"]), "--force"], output)
        _run(["--site", TARGET, "migrate"], output)
    print(json.dumps({"restored_site": TARGET,
        "source_backup_sha256": _sha256(MANIFEST),
        "maintenance_mode": True}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        sys.exit(str(exc))
