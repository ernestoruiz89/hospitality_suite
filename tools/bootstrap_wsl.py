"""Local, isolated WSL test site. Never targets an existing site's database."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

BENCH = Path("/home/frappe/benches/hospitality-bench")
SITE = "hospitality.localhost"
PRIVATE = BENCH / ".hospitality-setup.json"

if sys.argv[1] == "init-db":
    import pwd
    if not PRIVATE.exists():
        check = subprocess.run(["mariadb", "-N", "-e", "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='hospitality_dev'"], capture_output=True, text=True, check=True)
        if check.stdout.strip() != "0":
            raise SystemExit("Database hospitality_dev already exists; refusing to reuse it")
        cfg = dict(db_password=secrets.token_urlsafe(32), admin_password=secrets.token_urlsafe(24))
        sql = f"CREATE DATABASE hospitality_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER 'hospitality_dev'@'localhost' IDENTIFIED BY '{cfg['db_password']}'; GRANT ALL PRIVILEGES ON hospitality_dev.* TO 'hospitality_dev'@'localhost';"
        result = subprocess.run(["mariadb"], input=sql, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit("Could not create isolated test database; inspect MariaDB administration locally")
        PRIVATE.write_text(json.dumps(cfg))
        user = pwd.getpwnam("frappe")
        os.chown(PRIVATE, user.pw_uid, user.pw_gid)
        PRIVATE.chmod(0o600)
        print("Isolated database and private credentials created")
elif sys.argv[1] == "create-site":
    cfg = json.loads(PRIVATE.read_text())
    if (BENCH / "sites" / SITE / "site_config.json").exists():
        raise SystemExit("Site already exists; no changes made")
    cmd = ["/home/frappe/.local/bin/bench", "new-site", SITE, "--db-name", "hospitality_dev", "--db-user", "hospitality_dev", "--db-password", cfg["db_password"], "--admin-password", cfg["admin_password"], "--no-setup-db", "--install-app", "erpnext"]
    result = subprocess.run(cmd, cwd=BENCH, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode:
        print(result.stderr)
        raise SystemExit(result.returncode)
    print("Site created; Administrator password stored only in", PRIVATE)
