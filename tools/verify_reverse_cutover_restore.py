"""Restore the isolated PMS target's verified pre-cutover native backup.

Run as root in WSL. Creates a new site/database and refuses an existing one.
The confirmed-cutover site is read-only input and remains in maintenance.
"""

import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess


BENCH = Path("/home/frappe/frappe-bench")
SOURCE = "hs-pms-smoke-reverse.local"
TARGET = "hs-pms-smoke-reverse-restore.local"
DATABASE = "hs_pms_reverse_restore"
ROOT = BENCH / "sites" / TARGET
LOG = BENCH / ".hs-reverse-cutover-restore.log"
PYTHON = BENCH / "env" / "bin" / "python"


def _bench(arguments, output):
    result = subprocess.run([str(PYTHON), "-m", "frappe.utils.bench_helper",
        "frappe", *arguments], cwd=BENCH / "sites", stdout=output,
        stderr=subprocess.STDOUT, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError("The isolated restore failed; inspect the bench log")


def main():
    if (os.geteuid() != 0 or BENCH.resolve() != Path("/home/frappe/frappe-bench") or
            ROOT.exists()):
        raise RuntimeError("Run as root with an unused restore target")
    existing = subprocess.run(["mariadb", "--batch", "--skip-column-names",
        "-e", f"SHOW DATABASES LIKE '{DATABASE}'"], capture_output=True,
        text=True, check=True)
    if existing.stdout.strip():
        raise RuntimeError("The restore target database already exists")
    private = BENCH / "sites" / SOURCE / "private" / "files"
    manifests = list(private.glob("hs-reverse-target-backup-*.json"))
    if len(manifests) != 1 or manifests[0].is_symlink():
        raise RuntimeError("Expected one verified pre-cutover manifest")
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    backup_root = BENCH / "sites" / SOURCE / "private" / "backups"
    paths = {}
    for role in ("database", "public_files", "private_files", "site_config"):
        entry = manifest.get(role) or {}
        name, digest = entry.get("name"), entry.get("sha256")
        if not isinstance(name, str) or not isinstance(digest, str):
            raise RuntimeError("The target backup manifest is incomplete")
        path = backup_root / name
        if (path.is_symlink() or path.resolve().parent != backup_root.resolve() or
                not path.is_file()):
            raise RuntimeError("A backup file is missing or unsafe")
        actual = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                actual.update(chunk)
        if actual.hexdigest() != digest:
            raise RuntimeError("A pre-cutover backup file changed")
        paths[role] = path
    backed_config = json.loads(paths["site_config"].read_text(encoding="utf-8"))
    if backed_config.get("maintenance_mode") not in (1, True, "1"):
        raise RuntimeError("The destination backup was not frozen")
    owner = pwd.getpwnam("frappe")
    try:
        with LOG.open("w", encoding="utf-8") as output:
            os.chmod(LOG, 0o600)
            _bench(["new-site", TARGET, "--db-name", DATABASE,
                "--db-socket", "/run/mysqld/mysqld.sock",
                "--db-root-username", "root", "--db-root-password",
                "local-unix-socket-auth", "--admin-password",
                secrets.token_urlsafe(24)], output)
            config_path = ROOT / "site_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config.get("db_name") != DATABASE:
                raise RuntimeError("The new site points to another database")
            config.update(maintenance_mode=1, pause_scheduler=1)
            if backed_config.get("encryption_key"):
                config["encryption_key"] = backed_config["encryption_key"]
            config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
            _bench(["--site", TARGET, "restore", str(paths["database"]),
                "--db-root-username", "root", "--db-root-password",
                "local-unix-socket-auth", "--with-public-files",
                str(paths["public_files"]), "--with-private-files",
                str(paths["private_files"]), "--force"], output)
            _bench(["--site", TARGET, "migrate"], output)
        for path in (ROOT, *ROOT.rglob("*")):
            if path.resolve().is_relative_to(ROOT.resolve()):
                os.chown(path, owner.pw_uid, owner.pw_gid)
        check = subprocess.run(["runuser", "-u", "frappe", "--", str(PYTHON),
            "-m", "frappe.utils.bench_helper", "frappe", "--site", TARGET,
            "execute", "hospitality_suite.tests.smoke_reverse_restore_target.verify_continuity"],
            cwd=BENCH / "sites", capture_output=True, text=True, check=False)
        if check.returncode:
            raise RuntimeError(check.stderr or check.stdout or "Restore verification failed")
        result = json.loads(check.stdout.strip().splitlines()[-1])
        print(json.dumps({"site": TARGET, "backup_files": 4, **result},
                         sort_keys=True))
    finally:
        if ROOT.exists():
            for path in (ROOT, *ROOT.rglob("*")):
                if path.resolve().is_relative_to(ROOT.resolve()):
                    os.chown(path, owner.pw_uid, owner.pw_gid)
        if LOG.is_file():
            os.chown(LOG, owner.pw_uid, owner.pw_gid)
        for path in (BENCH / "logs").glob("database.log*"):
            if path.is_file() and path.stat().st_uid == 0:
                os.chown(path, owner.pw_uid, owner.pw_gid)


if __name__ == "__main__":
    main()
