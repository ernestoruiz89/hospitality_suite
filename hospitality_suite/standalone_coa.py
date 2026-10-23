"""Import/export compatible with ERPNext's eight-column CoA Importer template."""

import base64
import hashlib

import frappe
from frappe import _

from hospitality_suite.coa_format import ChartFormatError, export_csv, parse_csv, parse_rows
from hospitality_suite.schema import SCHEMA
from hospitality_suite.security import require
from hospitality_suite.service import audit, insert
from hospitality_suite.standalone_accounting import chart, require_pms
from hospitality_suite.standalone_currency import enabled


def _parsed(prop, file_name, encoded):
    if not isinstance(file_name, str) or not isinstance(encoded, str) or len(encoded) > 1400000:
        frappe.throw(_("Seleccione un archivo de catálogo de hasta 1 MB"))
    try:
        content = base64.b64decode(encoded, validate=True)
    except Exception:
        frappe.throw(_("El archivo del catálogo no es válido"))
    if not content or len(content) > 1048576:
        frappe.throw(_("Seleccione un archivo de catálogo de hasta 1 MB"))
    extension = file_name.rsplit(".", 1)[-1].lower()
    try:
        if extension == "csv":
            rows = parse_csv(content, prop.currency)
        elif extension in ("xlsx", "xls"):
            from frappe.utils.xlsxutils import read_xls_file_from_attached_file, read_xlsx_file_from_attached_file

            workbook = (read_xlsx_file_from_attached_file(fcontent=content) if extension == "xlsx"
                        else read_xls_file_from_attached_file(content))
            rows = parse_rows(workbook, prop.currency)
        else:
            frappe.throw(_("Use CSV, XLSX o XLS como en el importador de ERPNext"))
    except ChartFormatError as exc:
        frappe.throw(str(exc))
    account_type_options = next(field["options"].split("\n") for field in SCHEMA["HS Account"]["fields"]
                                if field["fieldname"] == "account_type")
    for row in rows:
        if row["account_type"] not in account_type_options:
            frappe.throw(_("Fila {0}: tipo de cuenta desconocido").format(row["row"]))
        if not frappe.db.exists("Currency", row["account_currency"]):
            frappe.throw(_("Fila {0}: moneda desconocida").format(row["row"]))
        if not enabled(prop, row["account_currency"]):
            frappe.throw(_("Fila {0}: habilite la moneda en el establecimiento antes de importar").format(row["row"]))
    return rows, hashlib.sha256(content).hexdigest()


def preview(property_name, file_name, content_base64):
    prop = require(property_name, "chart")
    require_pms(prop)
    rows, digest = _parsed(prop, file_name, content_base64)
    return {"count": len(rows), "sha256": digest, "root_types": sorted({row["root_type"] for row in rows}),
            "foreign_currencies": sorted({row["account_currency"] for row in rows if row["account_currency"] != prop.currency}),
            "sample": [{key: row[key] for key in ("account_code", "account_name", "root_type", "account_type",
                                                       "account_currency", "is_group")} for row in rows[:20]]}


def import_chart(prop, data):
    require_pms(prop)
    require(prop.name, "chart")
    if not isinstance(data, dict) or set(data) != {"file_name", "content_base64", "sha256"}:
        frappe.throw(_("Revise el archivo antes de importar"))
    rows, digest = _parsed(prop, data["file_name"], data["content_base64"])
    if digest != data["sha256"]:
        frappe.throw(_("El archivo cambió desde la vista previa"))
    if frappe.db.exists("HS Account", {"property": prop.name}):
        frappe.throw(_("Importe el catálogo antes de crear cuentas en este establecimiento"))
    names = {}
    for row in rows:
        parent = names.get(row["parent_key"]) if row["parent_key"] else None
        account = insert("HS Account", prop, organization=prop.organization,
            account_code=row["account_code"], account_number=row["account_number"],
            account_name=row["account_name"], parent_account=parent,
            root_type=row["root_type"], account_type=row["account_type"],
            account_currency=row["account_currency"], is_group=int(row["is_group"]), active=1)
        names[row["key"]] = account.name
    audit(prop, "pms_chart_imported", account, details={"count": len(rows), "sha256": digest,
                                                     "file_name": data["file_name"]})
    return {"count": len(rows), "sha256": digest}


def export_chart(property_name):
    prop = require(property_name, "chart")
    require_pms(prop)
    rows = chart(property_name)
    return {"file_name": "coa_hospitality.csv",
            "content_base64": base64.b64encode(export_csv(rows, prop.currency).encode("utf-8")).decode("ascii"),
            "count": len(rows)}
