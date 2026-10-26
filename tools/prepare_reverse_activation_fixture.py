"""Restore an isolated PMS smoke clone for a real reverse-cutover commit test.

Run as root in the local WSL bench. Refuses an existing target site/database and
leaves the clone for inspection. The source smoke site is read-only.
"""

import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess


BENCH = Path("/home/frappe/frappe-bench")
SOURCE = "hs-pms-smoke.local"
TARGET = "hs-pms-smoke-reverse.local"
DATABASE = "hs_pms_reverse_activation"
MANIFEST = "hs-reverse-backup-probe-b3cb11cf90a045599614d0b26c882daa.json"
LOG = BENCH / ".hs-reverse-activation-setup.log"
PYTHON = BENCH / "env" / "bin" / "python"


def _bench(arguments, output):
    command = [str(PYTHON), "-m", "frappe.utils.bench_helper", "frappe", *arguments]
    result = subprocess.run(command, cwd=BENCH / "sites", stdout=output,
                            stderr=subprocess.STDOUT, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError("The isolated PMS clone setup failed; inspect the bench log")


def main(*, target=TARGET, database=DATABASE, log=LOG):
    root = BENCH / "sites" / target
    if (os.geteuid() != 0 or BENCH.resolve() != Path("/home/frappe/frappe-bench") or
            root.exists()):
        raise RuntimeError("Run as root with an unused isolated target site")
    existing = subprocess.run(["mariadb", "--batch", "--skip-column-names",
        "-e", f"SHOW DATABASES LIKE '{database}'"], capture_output=True,
        text=True, check=True)
    if existing.stdout.strip():
        raise RuntimeError("The isolated target database already exists")
    manifest_path = BENCH / "sites" / SOURCE / "private" / "files" / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError("The verified source backup manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_root = BENCH / "sites" / SOURCE / "private" / "backups"
    paths = {}
    from hashlib import sha256
    for role in ("database", "public_files", "private_files", "site_config"):
        entry = manifest.get(role) or {}
        name, digest = entry.get("name"), entry.get("sha256")
        if not isinstance(name, str) or not isinstance(digest, str):
            raise RuntimeError("The backup manifest is incomplete")
        path = backup_root / name
        if (path.is_symlink() or path.resolve().parent != backup_root.resolve() or
                not path.is_file()):
            raise RuntimeError("A backup file is missing or unsafe")
        with path.open("rb") as stream:
            actual = sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                actual.update(chunk)
        if actual.hexdigest() != digest:
            raise RuntimeError("A backup file changed")
        paths[role] = path
    saved_config = json.loads(paths["site_config"].read_text(encoding="utf-8"))
    if saved_config.get("maintenance_mode") not in (1, True, "1"):
        raise RuntimeError("The source backup was not frozen")
    owner = pwd.getpwnam("frappe")
    try:
        with log.open("w", encoding="utf-8") as output:
            os.chmod(log, 0o600)
            _bench(["new-site", target, "--db-name", database,
                "--db-socket", "/run/mysqld/mysqld.sock",
                "--db-root-username", "root", "--db-root-password",
                "local-unix-socket-auth", "--admin-password",
                secrets.token_urlsafe(24)], output)
            config_path = root / "site_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config.get("db_name") != database:
                raise RuntimeError("The new site points to another database")
            config.update(pause_scheduler=1, maintenance_mode=0)
            if saved_config.get("encryption_key"):
                config["encryption_key"] = saved_config["encryption_key"]
            config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
            _bench(["--site", target, "restore", str(paths["database"]),
                "--db-root-username", "root", "--db-root-password",
                "local-unix-socket-auth", "--with-public-files",
                str(paths["public_files"]), "--with-private-files",
                str(paths["private_files"]), "--force"], output)
            _bench(["--site", target, "migrate"], output)
        print(json.dumps({"site": target, "database": database,
                          "schema_migrated": True, "source_backup_files": 4}))
    finally:
        if root.exists():
            for path in (root, *root.rglob("*")):
                if path.resolve().is_relative_to(root.resolve()):
                    os.chown(path, owner.pw_uid, owner.pw_gid)
        if log.is_file():
            os.chown(log, owner.pw_uid, owner.pw_gid)
        for path in (BENCH / "logs").glob("database.log*"):
            if path.is_file() and path.stat().st_uid == 0:
                os.chown(path, owner.pw_uid, owner.pw_gid)


if __name__ == "__main__":
    main()
