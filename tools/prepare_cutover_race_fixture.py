"""Create one isolated, schema-current cutover race fixture from a saved DB.

Run as root in the Ubuntu test WSL. The source restore and all existing sites
are read-only inputs. The script refuses an existing target site or database.
It deliberately leaves a failed target for inspection instead of removing it.
"""

import json
import os
from pathlib import Path
import pwd
import re
import secrets
import subprocess


BENCH = Path("/home/frappe/frappe-bench")
SOURCE = "hs-cutover-data-restore.local"
TARGET = "hs-cutover-race.local"
DATABASE = "hs_cutover_race"
SOURCE_BACKUPS = BENCH / "sites" / SOURCE / "private" / "backups"
TARGET_ROOT = BENCH / "sites" / TARGET
LOG = BENCH / ".hs-cutover-race-setup.log"
PYTHON = BENCH / "env" / "bin" / "python"


def run(arguments, output):
    command = [str(PYTHON), "-m", "frappe.utils.bench_helper", "frappe", *arguments]
    result = subprocess.run(command, cwd=BENCH / "sites", stdout=output,
                            stderr=subprocess.STDOUT, timeout=900, check=False)
    if result.returncode:
        raise RuntimeError("The isolated fixture setup failed; inspect the bench log")


def main():
    if (os.geteuid() != 0 or BENCH.resolve() != Path("/home/frappe/frappe-bench") or
            TARGET_ROOT.resolve() != (BENCH / "sites" / TARGET).resolve() or
            TARGET_ROOT.exists()):
        raise RuntimeError("Run as root with an unused isolated target site")
    existing = subprocess.run(["mariadb", "--batch", "--skip-column-names",
        "-e", f"SHOW DATABASES LIKE '{DATABASE}'"], capture_output=True,
        text=True, check=True)
    if existing.stdout.strip():
        raise RuntimeError("The isolated target database already exists")
    databases = list(SOURCE_BACKUPS.glob(
        "*-hs-cutover-data-restore_local-database.sql.gz"))
    if len(databases) != 1 or databases[0].is_symlink():
        raise RuntimeError("Expected exactly one saved data-bearing database")
    stamp = re.fullmatch(r"(\d{8}_\d{6})-hs-cutover-data-restore_local-"
                         r"database\.sql\.gz", databases[0].name)
    if not stamp:
        raise RuntimeError("The source backup has an unexpected name")
    config_file = SOURCE_BACKUPS / (stamp.group(1) +
        "-hs-cutover-data-restore_local-site_config_backup.json")
    if config_file.is_symlink() or not config_file.is_file():
        raise RuntimeError("The saved site configuration is missing")
    backup_config = json.loads(config_file.read_text(encoding="utf-8"))
    if backup_config.get("maintenance_mode") not in (1, True, "1"):
        raise RuntimeError("The source backup was not taken under maintenance")
    owner = pwd.getpwnam("frappe")
    try:
        with LOG.open("w", encoding="utf-8") as output:
            os.chmod(LOG, 0o600)
            run(["new-site", TARGET, "--db-name", DATABASE,
                "--db-socket", "/run/mysqld/mysqld.sock",
                "--db-root-username", "root", "--db-root-password",
                "local-unix-socket-auth", "--admin-password",
                secrets.token_urlsafe(24)], output)
            config_path = TARGET_ROOT / "site_config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if config.get("db_name") != DATABASE:
                raise RuntimeError("The new site points to another database")
            config.update(pause_scheduler=1, maintenance_mode=1)
            if backup_config.get("encryption_key"):
                config["encryption_key"] = backup_config["encryption_key"]
            config_path.write_text(json.dumps(config, indent=1), encoding="utf-8")
            run(["--site", TARGET, "restore", str(databases[0]),
                "--db-root-username", "root", "--db-root-password",
                "local-unix-socket-auth", "--force"], output)
            run(["--site", TARGET, "migrate"], output)
        print(json.dumps({"site": TARGET, "database": DATABASE,
                          "schema_migrated": True}))
    finally:
        if TARGET_ROOT.exists():
            for path in (TARGET_ROOT, *TARGET_ROOT.rglob("*")):
                if path.resolve().is_relative_to(TARGET_ROOT.resolve()):
                    os.chown(path, owner.pw_uid, owner.pw_gid)
        if LOG.is_file():
            os.chown(LOG, owner.pw_uid, owner.pw_gid)
        for path in (BENCH / "logs").glob("database.log*"):
            if path.is_file() and path.stat().st_uid == 0:
                os.chown(path, owner.pw_uid, owner.pw_gid)


if __name__ == "__main__":
    main()
