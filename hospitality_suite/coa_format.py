"""ERPNext Chart of Accounts Importer eight-column CSV/XLSX interchange."""

import csv
import io


HEADERS = ("Account Name", "Parent Account", "Account Number", "Parent Account Number",
           "Is Group", "Account Type", "Root Type", "Account Currency")
ROOT_TYPES = ("Asset", "Liability", "Equity", "Income", "Expense")


class ChartFormatError(ValueError):
    pass


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text[1:] if len(text) > 1 and text.startswith("'") and text[1] in "=+-@" else text


def parse_rows(rows, base_currency):
    if not rows:
        raise ChartFormatError("El archivo está vacío")
    headers = tuple(_cell(value).lstrip("\ufeff") for value in rows[0])
    if headers != HEADERS:
        raise ChartFormatError("Use las ocho columnas del importador de catálogo de ERPNext")
    by_key = {}
    ordered = []
    for number, raw in enumerate(rows[1:], start=2):
        if not any(_cell(value) for value in raw):
            continue
        if len(raw) != len(HEADERS):
            raise ChartFormatError(f"Fila {number}: se requieren ocho columnas")
        name, parent_name, external, parent_external, group, account_type, root, currency = map(_cell, raw)
        if not name or len(name) > 140 or len(external) > 40:
            raise ChartFormatError(f"Fila {number}: nombre o número de cuenta inválido")
        if parent_external and not parent_name:
            raise ChartFormatError(f"Fila {number}: indique el nombre de la cuenta superior")
        if group not in ("", "0", "1"):
            raise ChartFormatError(f"Fila {number}: Is Group debe ser 0 o 1")
        if root and root not in ROOT_TYPES:
            raise ChartFormatError(f"Fila {number}: naturaleza contable inválida")
        key = (name, external)
        if key in by_key:
            raise ChartFormatError(f"Fila {number}: la cuenta está duplicada")
        item = dict(key=key, parent_key=(parent_name, parent_external) if parent_name else None,
                    account_name=name, account_number=external, is_group=group == "1",
                    account_type=account_type or "General", root_type=root,
                    account_currency=currency or base_currency, row=number)
        by_key[key] = item
        ordered.append(item)
    if not ordered or len(ordered) > 3000:
        raise ChartFormatError("El catálogo debe contener entre 1 y 3000 cuentas")
    for item in ordered:
        parent = by_key.get(item["parent_key"]) if item["parent_key"] else None
        if item["parent_key"] and not parent:
            raise ChartFormatError(f"Fila {item['row']}: no existe la cuenta superior")
        if parent:
            parent["is_group"] = True
    visiting = set()
    visited = set()
    output = []

    def visit(item, depth=0):
        if depth > 64:
            raise ChartFormatError(f"Fila {item['row']}: la jerarquía supera 64 niveles")
        key = item["key"]
        if key in visiting:
            raise ChartFormatError(f"Fila {item['row']}: la jerarquía contiene un ciclo")
        if key in visited:
            return
        visiting.add(key)
        parent = by_key[item["parent_key"]] if item["parent_key"] else None
        if parent:
            visit(parent, depth + 1)
            if item["root_type"] and item["root_type"] != parent["root_type"]:
                raise ChartFormatError(f"Fila {item['row']}: la naturaleza difiere de la cuenta superior")
            item["root_type"] = parent["root_type"]
        elif not item["root_type"]:
            raise ChartFormatError(f"Fila {item['row']}: la cuenta raíz requiere Root Type")
        visiting.remove(key)
        visited.add(key)
        output.append(item)

    for item in ordered:
        visit(item)
    roots = {item["root_type"] for item in output if not item["parent_key"]}
    if roots != set(ROOT_TYPES):
        raise ChartFormatError("El archivo debe incluir raíces para Activo, Pasivo, Patrimonio, Ingresos y Gastos")
    numbers = {item["account_number"] for item in output if item["account_number"]}
    if len(numbers) != sum(bool(item["account_number"]) for item in output):
        raise ChartFormatError("Los números de cuenta deben ser únicos")
    for position, item in enumerate(output, start=1):
        code = item["account_number"] or f"COA-{position:05d}"
        if code in numbers and not item["account_number"]:
            raise ChartFormatError(f"El código interno {code} colisiona con otro número de cuenta")
        item["account_code"] = code
    return output


def parse_csv(content, base_currency):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ChartFormatError("El CSV debe estar codificado en UTF-8") from exc
    return parse_rows(list(csv.reader(io.StringIO(text))), base_currency)


def export_csv(accounts, base_currency):
    by_name = {row["name"]: row for row in accounts}
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADERS)

    def safe(value):
        value = str(value or "")
        return "'" + value if value.startswith(("=", "+", "-", "@")) else value

    for row in accounts:
        parent = by_name.get(row.get("parent_account"))
        writer.writerow([safe(row["account_name"]), safe(parent["account_name"]) if parent else "",
                         safe(row.get("account_number")), safe(parent.get("account_number")) if parent else "",
                         int(bool(row["is_group"])),
                         "" if row.get("account_type") == "General" else row.get("account_type", ""),
                         row["root_type"], row.get("account_currency") or base_currency])
    return "\ufeff" + stream.getvalue()
