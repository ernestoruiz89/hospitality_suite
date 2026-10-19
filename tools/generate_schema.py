"""Generate native Frappe metadata without importing Frappe."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hospitality_suite.schema import SCHEMA, MANAGERS, PAGES


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


for name, spec in SCHEMA.items():
    slug = name.lower().replace(" ", "_")
    folder = ROOT / "hospitality_suite/hospitality_suite/doctype" / slug
    perms = []
    for role in dict.fromkeys(["System Manager"] + spec.get("roles", [])):
        row = dict(role=role, read=1, report=1, export=1 if role in MANAGERS + ["HS Accountant", "System Manager"] else 0, print=1)
        if role == "System Manager" or (role != "HS Auditor" and name not in ("HS Audit Event", "HS Request", "HS Allocation", "HS Access")):
            row.update(create=1, write=1)
        perms.append(row)
    data = dict(doctype="DocType", name=name, module="Hospitality Suite", custom=0, engine="InnoDB",
                track_changes=1, autoname="hash", naming_rule="Random", fields=spec["fields"],
                field_order=[f["fieldname"] for f in spec["fields"]], permissions=perms,
                sort_field="modified", sort_order="DESC", allow_rename=0)
    if spec.get("child"):
        data.update(istable=1, permissions=[])
    write(folder / (slug + ".json"), json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    class_name = name.replace(" ", "")
    write(folder / "__init__.py", "")
    write(folder / (slug + ".py"), f'from hospitality_suite.controllers import ScopedDocument\n\n\nclass {class_name}(ScopedDocument):\n    pass\n')

for route, (title, roles) in PAGES.items():
    slug = route.replace("-", "_")
    folder = ROOT / "hospitality_suite/hospitality_suite/page" / slug
    data = dict(doctype="Page", name=route, page_name=route, title=title, module="Hospitality Suite", standard="Yes",
                roles=[dict(role=r) for r in ["System Manager"] + roles])
    write(folder / (slug + ".json"), json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    write(folder / (slug + ".js"), f'frappe.pages["{route}"].on_page_load = function(wrapper) {{\n  new hospitality_suite.Desk(wrapper, "{route}");\n}};\n')
    write(folder / "__init__.py", "")

for folder in ["hospitality_suite/hospitality_suite", "hospitality_suite/hospitality_suite/doctype", "hospitality_suite/hospitality_suite/page"]:
    write(ROOT / folder / "__init__.py", "")
print(f"Generated {len(SCHEMA)} DocTypes and {len(PAGES)} Pages")
