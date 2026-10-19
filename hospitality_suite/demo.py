"""Explicit synthetic seed, never executed at install time. Safe to rerun."""
import secrets
import json
from pathlib import Path

import frappe
from frappe.utils import nowdate

from hospitality_suite.schema import ROLES
from hospitality_suite.service import operation


def seed():
    if frappe.local.site != "hospitality.localhost" and not frappe.conf.get("hospitality_allow_demo"):
        frappe.throw("La demostración requiere hospitality_allow_demo en un sitio de pruebas")
    if frappe.session.user != "Administrator":
        frappe.throw("Ejecute la demostración como Administrator", frappe.PermissionError)
    credential_path=Path(frappe.get_site_path("private","hospitality-demo-users.json"))
    credentials=json.loads(credential_path.read_text()) if credential_path.exists() else {}
    from erpnext.setup.setup_wizard.operations.install_fixtures import install as install_erp_defaults
    if not frappe.db.exists("Warehouse Type", "Transit"):
        install_erp_defaults("Nicaragua")
    frappe.db.set_single_value("System Settings", "time_zone", "America/Managua")
    frappe.db.set_single_value("System Settings", "language", "es")
    frappe.db.set_single_value("System Settings", "country", "Nicaragua")
    company_name = "Alojamiento Demostración"
    if not frappe.db.exists("Company", company_name):
        company = frappe.get_doc(dict(doctype="Company", company_name=company_name, abbr="HSD", country="Nicaragua",
                                     default_currency="NIO", chart_of_accounts="Standard", enable_perpetual_inventory=1))
        company.insert()
    company = frappe.get_doc("Company", company_name)
    if not frappe.db.exists("Fiscal Year", str(nowdate()[:4])):
        frappe.get_doc(dict(doctype="Fiscal Year", year=str(nowdate()[:4]), year_start_date=nowdate()[:4] + "-01-01",
                            year_end_date=nowdate()[:4] + "-12-31")).insert()
    if not frappe.db.exists("Item", "HS-DEMO-LODGING"):
        frappe.get_doc(dict(doctype="Item", item_code="HS-DEMO-LODGING", item_name="Alojamiento (demostración)",
                            item_group="Services", stock_uom="Nos", is_stock_item=0, is_sales_item=1,
                            item_defaults=[dict(company=company.name, income_account=company.default_income_account)])).insert()
    if not frappe.db.exists("Item", "HS-DEMO-WATER"):
        frappe.get_doc(dict(doctype="Item", item_code="HS-DEMO-WATER", item_name="Agua minibar (demostración)",
                            item_group="Products", stock_uom="Nos", is_stock_item=1, is_sales_item=1,
                            valuation_rate=10, item_defaults=[dict(company=company.name, income_account=company.default_income_account)])).insert()
    price_list = "HS Demo NIO"
    if not frappe.db.exists("Price List", price_list):
        frappe.get_doc(dict(doctype="Price List", price_list_name=price_list, selling=1, currency="NIO", enabled=1)).insert()
    frappe.db.set_single_value("Selling Settings", "selling_price_list", price_list)
    frappe.db.set_single_value("Selling Settings", "customer_group", "Individual")
    frappe.db.set_single_value("Selling Settings", "territory", "Nicaragua")
    if not frappe.db.exists("Item Price", {"item_code": "HS-DEMO-WATER", "price_list": price_list}):
        frappe.get_doc(dict(doctype="Item Price", item_code="HS-DEMO-WATER", price_list=price_list, price_list_rate=30, currency="NIO")).insert()
    guarantee = frappe.db.get_value("Account", {"company": company.name, "account_name": "Garantías de huéspedes demo"})
    if not guarantee:
        parent = frappe.db.get_value("Account", {"company": company.name, "root_type": "Liability", "is_group": 1, "parent_account": ["is", "not set"]})
        guarantee = frappe.get_doc(dict(doctype="Account", company=company.name, account_name="Garantías de huéspedes demo",
                                        parent_account=parent, root_type="Liability", account_type="", account_currency="NIO")).insert().name
    cash = company.default_cash_account or frappe.db.get_value("Account", {"company": company.name, "account_type": "Cash", "is_group": 0})
    warehouse = frappe.db.get_value("Warehouse", {"company": company.name, "warehouse_name": "Stores", "is_group": 0})
    if not frappe.db.exists("Mode of Payment", "Efectivo demo"):
        frappe.get_doc(dict(doctype="Mode of Payment", mode_of_payment="Efectivo demo", type="Cash",
                            accounts=[dict(company=company.name, default_account=cash)])).insert()
    if not frappe.db.exists("Currency Exchange", {"from_currency": "USD", "to_currency": "NIO", "date": nowdate()}):
        frappe.get_doc(dict(doctype="Currency Exchange", date=nowdate(), from_currency="USD", to_currency="NIO", exchange_rate=36.6243, for_selling=1, for_buying=1)).insert()
    result = []
    with operation():
        for mode, property_name, prefix in [("Hotel", "Hotel Jardín Demo", "H"), ("Motel", "Motel Luna Demo", "M")]:
            prop_name = frappe.db.get_value("HS Property", {"property_name": property_name})
            if not prop_name:
                prop = frappe.get_doc(dict(doctype="HS Property", property_name=property_name, company=company.name, mode=mode,
                                           time_zone="America/Managua", business_date=nowdate(), currency="NIO", cleaning_minutes=30,
                                           inspection_required=1, discreet_mode=mode=="Motel", hold_minutes=15,
                                           cost_center=company.cost_center, warehouse=warehouse, receivable_account=company.default_receivable_account,
                                           guarantee_account=guarantee, lodging_item="HS-DEMO-LODGING", tax_policy_confirmed=1, financial_enabled=1)).insert()
            else:
                prop = frappe.get_doc("HS Property", prop_name)
                prop.warehouse = warehouse
                prop.save()
            cat_name = frappe.db.get_value("HS Category", {"property": prop.name, "category_name": "Estándar"})
            if not cat_name:
                cat_name = frappe.get_doc(dict(doctype="HS Category", property=prop.name, company=company.name,
                                               category_name="Estándar", capacity=3, amenities="Wi-Fi, baño privado, aire acondicionado")).insert().name
            for i in range(1, 11):
                number = prefix + str(100 + i)
                if not frappe.db.exists("HS Room", {"property": prop.name, "room_number": number}):
                    frappe.get_doc(dict(doctype="HS Room", property=prop.name, company=company.name, room_number=number,
                                        category=cat_name, floor="1" if i <= 5 else "2", zone="Jardín" if i<=5 else "Patio",
                                        beds=1, parking=str(i) if mode=="Motel" else None, active=1, cleaning_status="Clean")).insert()
            if not frappe.db.exists("HS Rate", {"property": prop.name}):
                frappe.get_doc(dict(doctype="HS Rate", property=prop.name, company=company.name, title="Noche estándar" if mode=="Hotel" else "Bloque de 3 horas",
                                    category=cat_name, mode=mode, currency="NIO", amount=1500 if mode=="Hotel" else 450,
                                    block_hours=3, extra_hour_rate=150, grace_minutes=10, rounding_minutes=60,
                                    included_people=2, priority=10, active=1)).insert()
            if not frappe.db.exists("HS Payment Method", {"property": prop.name}):
                frappe.get_doc(dict(doctype="HS Payment Method", property=prop.name, company=company.name,
                                    mode_of_payment="Efectivo demo", account=cash, currency="NIO", is_cash=1)).insert()
            for i in range(1, 4):
                full_name = f"Huésped ficticio {prefix}{i}"
                if not frappe.db.exists("HS Guest", {"property": prop.name, "full_name": full_name}):
                    customer_name = f"Cliente ficticio {prefix}{i}"
                    if not frappe.db.exists("Customer", customer_name):
                        frappe.get_doc(dict(doctype="Customer", customer_name=customer_name, customer_type="Individual", customer_group="Individual", territory="Nicaragua")).insert()
                    frappe.get_doc(dict(doctype="HS Guest", property=prop.name, company=company.name,
                                        full_name=full_name, customer=customer_name, email=f"guest-{prefix.lower()}{i}@example.invalid")).insert()
            for role in ROLES:
                email = role.lower().replace("hs ", "").replace(" ", "-") + "@hospitality.example.invalid"
                if not frappe.db.exists("User", email):
                    password=secrets.token_urlsafe(24)
                    user = frappe.get_doc(dict(doctype="User", email=email, first_name=role.replace("HS ", ""), send_welcome_email=0,
                                               language="es",time_zone="America/Managua", user_type="System User", new_password=password, roles=[dict(role=role)]))
                    user.insert()
                    credentials[email]=password
                elif email not in credentials:
                    from frappe.utils.password import update_password
                    password=secrets.token_urlsafe(24)
                    update_password(email,password)
                    credentials[email]=password
                if not frappe.db.exists("HS Access", {"user": email, "property": prop.name}):
                    frappe.get_doc(dict(doctype="HS Access", user=email, company=prop.company, property=prop.name)).insert()
            result.append(dict(property=prop.name, property_name=prop.property_name))
        if not frappe.db.exists("Stock Entry Detail", {"item_code": "HS-DEMO-WATER", "t_warehouse": warehouse}):
            entry = frappe.get_doc(dict(doctype="Stock Entry", stock_entry_type="Material Receipt", company=company.name,
                                        set_posting_time=1, posting_date=nowdate(), posting_time="00:00:00",
                                        items=[dict(item_code="HS-DEMO-WATER", qty=100, t_warehouse=warehouse, basic_rate=10)]))
            entry.insert().submit()
    frappe.db.set_single_value("System Settings", "setup_complete", 1)
    for app in frappe.get_all("Installed Application", filters={"app_name": ["in", ["frappe", "erpnext"]]}, pluck="name"):
        frappe.db.set_value("Installed Application", app, "is_setup_complete", 1)
    frappe.clear_cache()
    frappe.db.set_default("company", company.name)
    credential_path.write_text(json.dumps(credentials),encoding="utf-8")
    credential_path.chmod(0o600)
    return result
