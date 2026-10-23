"""Generate native Frappe metadata without importing Frappe."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hospitality_suite.schema import SCHEMA, MANAGERS, PAGES, PAGE_ICONS
from hospitality_suite.document_naming import DOCUMENT_SERIES


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


for name, spec in SCHEMA.items():
    slug = name.lower().replace(" ", "_")
    folder = ROOT / "hospitality_suite/hospitality_suite/doctype" / slug
    perms = []
    for role in dict.fromkeys(["System Manager"] + spec.get("roles", [])):
        row = dict(role=role, read=1, report=1, export=1 if role in MANAGERS + ["HS Accountant", "System Manager"] else 0, print=1)
        if role == "System Manager" or (role != "HS Auditor" and name not in ("HS Audit Event", "HS Request", "HS Allocation", "HS Access", "HS Ticket Event")):
            row.update(create=1, write=1)
        perms.append(row)
    protected={"HS Property":("cost_center","income_account","expense_account","service_accounts","receivable_account","guarantee_account","cash_transfer_account","petty_cash_account","petty_cash_responsible","petty_cash_overage_account","petty_cash_shortage_account","tax_template","financial_enabled","early_hour_rate","late_hour_rate","cancellation_fee_value","no_show_fee_value"),"HS Maintenance Order":("cost","parts","stock_entry","evidence")}
    if name in protected:
        for df in spec["fields"]:
            if df["fieldname"] in protected[name]:
                df["permlevel"]=1
        for role in ["System Manager"]+MANAGERS+["HS Accountant","HS Auditor"]+(["HS Maintenance"] if name=="HS Maintenance Order" else ["HS Cashier"]):
            perms.append(dict(role=role,permlevel=1,read=1,write=1 if role in MANAGERS+["System Manager"] else 0))
    data = dict(doctype="DocType", name=name, module="Hospitality Suite", custom=0, engine="InnoDB",
                track_changes=1, autoname="hash", naming_rule="Random", fields=spec["fields"],
                field_order=[f["fieldname"] for f in spec["fields"]], permissions=perms,
                sort_field="modified", sort_order="DESC", allow_rename=0)
    if name in DOCUMENT_SERIES:
        data.update(autoname=DOCUMENT_SERIES[name], naming_rule="Expression (old style)")
    if spec.get("child"):
        data.update(istable=1, permissions=[])
    if spec.get("single"):
        data.update(issingle=1)
        data.pop("autoname", None)
        data.pop("naming_rule", None)
    titles = {"HS Property":"property_name", "HS Category":"category_name", "HS Room":"room_number", "HS Rate":"title", "HS Guest":"full_name", "HS Payment Method":"mode_of_payment", "HS Folio":"label", "HS Travel Agent":"agent_name", "HS Experience":"experience_name"}
    if name in titles:
        data.update(title_field=titles[name], search_fields=titles[name], show_title_field_in_link=1)
    write(folder / (slug + ".json"), json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    class_name = name.replace(" ", "")
    write(folder / "__init__.py", "")
    controller = spec.get("controller", "ScopedDocument")
    write(folder / (slug + ".py"), f'from hospitality_suite.controllers import {controller}\n\n\nclass {class_name}({controller}):\n    pass\n')

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
sidebar = dict(doctype="Sidebar", name="Hospitality Suite", title="Hospitality Suite", module="Hospitality Suite",
               app="hospitality_suite", standard=1, header_icon="hotel", items=[
                   dict(type="Link", link_type="Page", link_to=route, label=title, icon=PAGE_ICONS[route])
                   for route, (title, roles) in PAGES.items()])
write(ROOT / "hospitality_suite/hospitality_suite/sidebar/hospitality_suite/hospitality_suite.json",
      json.dumps(sidebar, indent=1, ensure_ascii=False) + "\n")
formats = {"reservation":("HS Booking","HS Confirmación de reserva"),"registration":("HS Stay","HS Registro de huésped"),
           "folio":("HS Stay","HS Cuenta de estancia"),"receipt":("HS Payment","HS Recibo"),
           "shift":("HS Shift","HS Arqueo"),"cleaning":("HS Cleaning Task","HS Orden de limpieza"),
           "maintenance":("HS Maintenance Order","HS Orden de mantenimiento"),"daily_close":("HS Daily Close","HS Cierre diario"),
           "invoice":("Sales Invoice","HS Factura"),"laundry":("HS Laundry Order","HS Comprobante de lavandería")}
for source,(dt,name) in formats.items():
    slug="hs_"+source
    data=dict(doctype="Print Format",name=name,doc_type=dt,module="Hospitality Suite",standard="Yes",custom_format=1,
              print_format_type="Jinja",html=(ROOT / f"hospitality_suite/templates/print/{source}.html").read_text(encoding="utf-8"),
              css=".hs-print{font-family:Arial,sans-serif;color:#173c32;font-size:11px}.hs-print h1{font-size:25px}.hs-print h2{font-size:15px;margin-top:25px}.hs-print table{width:100%;border-collapse:collapse;margin:18px 0}.hs-print th,.hs-print td{border-bottom:1px solid #dce5dc;padding:10px;text-align:left}.hs-print th{background:#edf2e9}.eyebrow{font-size:9px;letter-spacing:2px}.muted{color:#6c7b70;font-size:9px}")
    if source == "invoice":
        destination = ROOT / f"hospitality_suite/erpnext_assets/print_format/{slug}.json"
    else:
        destination = ROOT / f"hospitality_suite/hospitality_suite/print_format/{slug}/{slug}.json"
    write(destination,json.dumps(data,indent=1,ensure_ascii=False)+"\n")
print(f"Generated {len(SCHEMA)} DocTypes and {len(PAGES)} Pages")
