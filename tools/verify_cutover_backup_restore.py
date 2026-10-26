"""Restore an ERP smoke backup into one new, isolated cutover test site.

Run as root in the Ubuntu test WSL with the JSON output of
``hospitality_suite.pms_cutover_backup.prepare`` as the sole argument.
Never targets an existing site or database and never deletes the checkout.
"""

import atexit
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


BENCH = Path("/home/frappe/frappe-bench")
SOURCE_SITE = "hs-erp-smoke.local"
TARGET_SITE = "hs-cutover-restore.local"
TARGET_DB = "hs_cutover_restore"
BACKUPS = BENCH / "sites" / SOURCE_SITE / "private" / "backups"
TARGET = BENCH / "sites" / TARGET_SITE
PYTHON = BENCH / "env" / "bin" / "python"
LOG = BENCH / ".hs-cutover-restore.log"
ROLES = ("database", "public_files", "private_files", "site_config")
COUNTS = ("HS Property", "HS Organization", "HS Cutover Run", "Company",
          "Account", "HS Account", "HS Journal", "GL Entry", "File")
DATA_TABLES = COUNTS + (
    "HS Party", "HS Product", "HS Booking", "HS Allocation", "HS Stay",
    "HS Folio", "HS Charge", "HS Payment", "HS PMS Receivable",
    "HS PMS Allocation", "HS PMS Fiscal Document", "HS PMS Agency Commission",
    "HS PMS Purchase", "HS Journal Line", "HS Stock Movement",
)
SYSTEM_COLUMNS = {"creation", "modified", "modified_by", "owner", "idx"}


def fail(message):
    raise SystemExit(message)


def run(arguments, output):
    command = [str(PYTHON), "-m", "frappe.utils.bench_helper", "frappe", *arguments]
    result = subprocess.run(command, cwd=BENCH / "sites", stdout=output,
                            stderr=subprocess.STDOUT, timeout=600, check=False)
    if result.returncode:
        fail("Falló la restauración aislada; revise el registro privado del bench")


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_snapshot(site):
    root = BENCH / "sites" / site
    result = {}
    for kind in ("public", "private"):
        files = root / kind / "files"
        digest = hashlib.sha256()
        count = 0
        if files.exists():
            for path in sorted(files.rglob("*")):
                if path.is_symlink():
                    fail("El sitio contiene un enlace simbólico entre sus archivos")
                if path.is_file():
                    relative = path.relative_to(files).as_posix()
                    digest.update(json.dumps([relative, path.stat().st_size,
                                              digest_file(path)],
                                             separators=(",", ":")).encode())
                    digest.update(b"\n")
                    count += 1
        result[kind] = {"count": count, "sha256": digest.hexdigest()}
    return result


def row_snapshot():
    import frappe

    result = {}
    hotel_tables = {row[0][3:] for row in frappe.db.sql(
        "SHOW TABLES LIKE 'tabHS %'", as_list=True)}
    for doctype in sorted(set(DATA_TABLES) | hotel_tables):
        if not re.fullmatch(r"[A-Za-z0-9 _-]+", doctype):
            fail("El sitio contiene un nombre de tabla hotelera inesperado")
        if not frappe.db.table_exists(doctype):
            result[doctype] = None
            continue
        exact = hashlib.sha256()
        stable = hashlib.sha256()
        count = 0
        # DATA_TABLES is a fixed list of DocType names, never user input.
        for row in frappe.db.sql(f"SELECT * FROM `tab{doctype}` ORDER BY name",
                                 as_dict=True):
            values = dict(row)
            exact.update(json.dumps(values, sort_keys=True, default=str,
                                    separators=(",", ":")).encode())
            exact.update(b"\n")
            stable.update(json.dumps({key: value for key, value in values.items()
                                      if key not in SYSTEM_COLUMNS},
                                     sort_keys=True, default=str,
                                     separators=(",", ":")).encode())
            stable.update(b"\n")
            count += 1
        result[doctype] = {"count": count, "exact_sha256": exact.hexdigest(),
                           "stable_sha256": stable.hexdigest()}
    return result


def snapshot(site):
    import frappe

    frappe.init(site, sites_path=str(BENCH / "sites"))
    try:
        frappe.connect()
        return {"tables": row_snapshot(), "files": file_snapshot(site)}
    finally:
        frappe.destroy()
        import pwd

        owner = pwd.getpwnam("frappe")
        for path in (BENCH / "logs").glob("database.log*"):
            if path.is_file() and path.stat().st_uid == 0:
                os.chown(path, owner.pw_uid, owner.pw_gid)


def repair_ownership():
    import pwd

    owner = pwd.getpwnam("frappe")
    if TARGET.exists():
        for path in (TARGET, *TARGET.rglob("*")):
            if path.resolve().is_relative_to(TARGET.resolve()):
                os.chown(path, owner.pw_uid, owner.pw_gid)
    if LOG.is_file():
        os.chown(LOG, owner.pw_uid, owner.pw_gid)
    for path in (BENCH / "logs").glob("database.log*"):
        if path.is_file() and path.stat().st_uid == 0:
            os.chown(path, owner.pw_uid, owner.pw_gid)


def operationally_equal(source, target):
    if source["files"] != target["files"]:
        return False
    for name, before in source["tables"].items():
        after = target["tables"].get(name)
        if before is None or after is None:
            if before != after:
                return False
        elif (before["count"] != after["count"] or
              before["stable_sha256"] != after["stable_sha256"]):
            return False
    if any(row is not None and row["count"] for name, row in target["tables"].items()
           if name not in source["tables"]):
        return False
    return True


def summarize(snapshot):
    counts = {name: row["count"] for name, row in snapshot["tables"].items()
              if row is not None and row["count"]}
    fingerprints = {mode: hashlib.sha256(json.dumps(
        {name: (None if row is None else [row["count"], row[mode + "_sha256"]])
         for name, row in snapshot["tables"].items()},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        for mode in ("exact", "stable")}
    return {"nonempty_tables": counts, "files": snapshot["files"],
            "table_fingerprints": fingerprints}


def main():
    global SOURCE_SITE, TARGET_SITE, TARGET_DB, BACKUPS, TARGET
    if os.geteuid() != 0 or len(sys.argv) not in (2, 3):
        fail("Use root en el WSL de ensayo e indique un manifiesto JSON")
    if len(sys.argv) == 3:
        if sys.argv[1] != "--data-bearing":
            fail("Modo de restauración desconocido")
        SOURCE_SITE = "hs-cutover-restore.local"
        TARGET_SITE = "hs-cutover-data-restore.local"
        TARGET_DB = "hs_cutover_data_restore"
        BACKUPS = BENCH / "sites" / SOURCE_SITE / "private" / "backups"
        TARGET = BENCH / "sites" / TARGET_SITE
        manifest_argument = sys.argv[2]
    else:
        manifest_argument = sys.argv[1]
    if manifest_argument == "--inspect":
        if not TARGET.is_dir():
            fail("El sitio restaurado no existe")
        atexit.register(repair_ownership)
        os.chdir(BENCH / "sites")
        source, target = snapshot(SOURCE_SITE), snapshot(TARGET_SITE)
        print(json.dumps({"source": summarize(source),
                          "target": summarize(target),
                          "operationally_equal": operationally_equal(source, target)},
                         sort_keys=True))
        return
    if (BENCH.resolve() != Path("/home/frappe/frappe-bench") or
            TARGET.resolve() != (BENCH / "sites" / TARGET_SITE).resolve() or
            TARGET.exists()):
        fail("El destino aislado no está disponible")
    atexit.register(repair_ownership)
    os.chdir(BENCH / "sites")
    existing = subprocess.run(
        ["mariadb", "--batch", "--skip-column-names", "-e",
         f"SHOW DATABASES LIKE '{TARGET_DB}'"], capture_output=True, text=True,
        check=True)
    if existing.stdout.strip():
        fail("La base aislada ya existe")
    manifest_path = Path(manifest_argument).resolve()
    if not manifest_path.is_file():
        fail("Falta el manifiesto del respaldo")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != set(ROLES):
        fail("El manifiesto no contiene cuatro archivos")
    paths = {}
    stamp = None
    for role in ROLES:
        row = manifest[role]
        if not isinstance(row, dict) or set(row) != {"name", "sha256"}:
            fail("El manifiesto tiene un archivo inválido")
        name, expected = row["name"], row["sha256"]
        if (not isinstance(name, str) or not isinstance(expected, str) or
                not re.fullmatch(r"[0-9a-f]{64}", expected)):
            fail("El manifiesto tiene un hash inválido")
        matched = re.fullmatch(
            r"(\d{8}_\d{6})-" + re.escape(SOURCE_SITE.replace(".", "_")) + r"-" +
            {"database": r"database\.sql\.gz",
             "public_files": r"files\.(?:tar|tgz)",
             "private_files": r"private-files\.(?:tar|tgz)",
             "site_config": r"site_config_backup\.json"}[role], name)
        if not matched or (stamp and matched.group(1) != stamp):
            fail("Los archivos no pertenecen al mismo respaldo de ensayo")
        stamp = matched.group(1)
        path = BACKUPS / name
        if (path.is_symlink() or path.resolve().parent != BACKUPS.resolve() or
                not path.is_file() or not path.stat().st_size):
            fail("Falta un archivo del respaldo de ensayo")
        if digest_file(path) != expected:
            fail("Un archivo del respaldo cambió")
        paths[role] = path
    backup_config = json.loads(paths["site_config"].read_text(encoding="utf-8"))
    if backup_config.get("maintenance_mode") not in (1, True, "1"):
        fail("El respaldo no se tomó bajo mantenimiento")
    source = snapshot(SOURCE_SITE)
    with LOG.open("w", encoding="utf-8") as output:
        os.chmod(LOG, 0o600)
        run(["new-site", TARGET_SITE, "--db-name", TARGET_DB,
             "--db-socket", "/run/mysqld/mysqld.sock",
             "--db-root-username", "root", "--db-root-password",
             "local-unix-socket-auth", "--admin-password",
             secrets.token_urlsafe(24)], output)
        target_config_path = TARGET / "site_config.json"
        target_config = json.loads(target_config_path.read_text(encoding="utf-8"))
        if target_config.get("db_name") != TARGET_DB:
            fail("El sitio nuevo no apunta a la base aislada")
        target_config.update(pause_scheduler=1, maintenance_mode=1)
        if backup_config.get("encryption_key"):
            target_config["encryption_key"] = backup_config["encryption_key"]
        target_config_path.write_text(json.dumps(target_config, indent=1),
                                      encoding="utf-8")
        run(["--site", TARGET_SITE, "restore", str(paths["database"]),
             "--db-root-username", "root", "--db-root-password",
             "local-unix-socket-auth", "--with-public-files",
             str(paths["public_files"]), "--with-private-files",
             str(paths["private_files"]), "--force"], output)
        restored = snapshot(TARGET_SITE)
        if restored != source:
            fail("Los registros o archivos restaurados no coinciden con el origen")
        run(["--site", TARGET_SITE, "migrate"], output)
        migrated = snapshot(TARGET_SITE)
        if not operationally_equal(source, migrated):
            fail("La migración alteró registros o archivos operativos restaurados")
    print(json.dumps({"restored_site": TARGET_SITE,
                      "exact_restore_match": restored == source,
                      "operational_match_after_migrate": operationally_equal(source, migrated),
                      "source": summarize(source), "restored": summarize(restored),
                      "migrated": summarize(migrated)},
                     sort_keys=True))


if __name__ == "__main__":
    main()
