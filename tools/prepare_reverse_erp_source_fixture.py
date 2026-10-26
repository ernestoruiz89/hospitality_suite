"""Restore an isolated ERPNext smoke source for a real-voucher reverse cutover.

Run as root in the local WSL bench. Refuses an existing target site/database.
The original ERPNext smoke site and its full native backup are read-only.
"""

import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess


BENCH = Path("/home/frappe/frappe-bench")
SOURCE = "hs-erp-smoke.local"
TARGET = "hs-erp-smoke-reverse.local"
DATABASE = "hs_erp_reverse_source"
BACKUP_PREFIX = "20261026_020202-hs-erp-smoke_local-"
ROOT = BENCH / "sites" / TARGET
LOG = BENCH / ".hs-reverse-erp-source-setup.log"
PYTHON = BENCH / "env" / "bin" / "python"
PARTIAL_SOURCE = "hs-erp-smoke-reverse.local"
PARTIAL_TARGET = "hs-erp-smoke-reverse-partial.local"
PARTIAL_DATABASE = "hs_erp_reverse_partial"
PARTIAL_BACKUP_PREFIX = "20261026_021327-hs-erp-smoke-reverse_local-"


def _bench(arguments, output):
    result = subprocess.run([str(PYTHON), "-m", "frappe.utils.bench_helper",
        "frappe", *arguments], cwd=BENCH / "sites", stdout=output,
        stderr=subprocess.STDOUT, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError("The isolated ERPNext source setup failed; inspect the bench log")


def main(*, source=SOURCE, target=TARGET, database=DATABASE,
         backup_prefix=BACKUP_PREFIX, log=LOG):
    allowed = {
        (SOURCE, TARGET, DATABASE, BACKUP_PREFIX),
        (PARTIAL_SOURCE, PARTIAL_TARGET, PARTIAL_DATABASE,
         PARTIAL_BACKUP_PREFIX),
    }
    if (source, target, database, backup_prefix) not in allowed:
        raise RuntimeError("The requested source clone is not an approved fixture")
    root = BENCH / "sites" / target
    if (os.geteuid() != 0 or BENCH.resolve() != Path("/home/frappe/frappe-bench") or
            root.exists()):
        raise RuntimeError("Run as root with an unused isolated source site")
    existing = subprocess.run(["mariadb", "--batch", "--skip-column-names",
        "-e", f"SHOW DATABASES LIKE '{database}'"], capture_output=True,
        text=True, check=True)
    if existing.stdout.strip():
        raise RuntimeError("The isolated source database already exists")
    backup_root = BENCH / "sites" / source / "private" / "backups"
    names = {
        "database": backup_prefix + "database.sql.gz",
        "public_files": backup_prefix + "files.tar",
        "private_files": backup_prefix + "private-files.tar",
        "site_config": backup_prefix + "site_config_backup.json",
    }
    paths = {}
    hashes = {}
    for role, name in names.items():
        path = backup_root / name
        if (path.is_symlink() or path.resolve().parent != backup_root.resolve() or
                not path.is_file()):
            raise RuntimeError("The complete ERPNext source backup is missing")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        paths[role], hashes[role] = path, digest.hexdigest()
    saved_config = json.loads(paths["site_config"].read_text(encoding="utf-8"))
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
            "schema_migrated": True, "backup_sha256": hashes}, sort_keys=True))
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
