"""Mixed cutover rehearsal; only the guarded fixture seeder commits source data."""

from datetime import datetime, timedelta
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo
from zipfile import ZipFile

import frappe

from hospitality_suite import erp_fiscal_history, pms_cutover, pms_cutover_backup, pms_cutover_mapping, pms_cutover_plan, pms_cutover_rehearsal
from hospitality_suite.service import canonical, operation


def run(include_live_day_pass=False, prior_day_pass_credit=False,
        post_cutover_day_pass_collection=False, persist_source=False):
    if not frappe.local.site.startswith("hs-erp-smoke"):
        frappe.throw("Use únicamente el sitio ERPNext de ensayo")
    if persist_source and (frappe.local.site !=
            "hs-erp-smoke-persistent.local" or not include_live_day_pass or
            post_cutover_day_pass_collection or frappe.db.count("HS Property") or
            frappe.db.count("HS Cutover Run")):
        frappe.throw("La fuente persistente exige un sitio de ensayo nuevo y aislado")
    frappe.set_user("Administrator")
    previous_maintenance = frappe.local.conf.get("maintenance_mode")
    previous_rehearsal = getattr(frappe.local, "hs_cutover_rehearsal", False)
    backup_dir = None
    fiscal_bundle_path = None
    incident_evidence_path = None
    maintenance_evidence_path = None
    persistent_mapping_path = None
    source_committed = False
    frappe.db.savepoint("hs_mixed_cutover_probe")
    try:
        if not frappe.db.exists("Warehouse Type", "Transit"):
            frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(
                ignore_permissions=True)
        if not frappe.db.exists("UOM", "Nos"):
            frappe.get_doc({"doctype": "UOM", "uom_name": "Nos",
                            "must_be_whole_number": 1, "enabled": 1}).insert(
                                ignore_permissions=True)
        for party_type, account_type in (("Customer", "Receivable"),
                                         ("Supplier", "Payable")):
            if not frappe.db.exists("Party Type", party_type):
                frappe.get_doc({"doctype": "Party Type",
                    "party_type": party_type,
                    "account_type": account_type}).insert(ignore_permissions=True)
        suffix = uuid4().hex[:6].upper()
        org = frappe.get_doc({"doctype": "HS Organization",
            "legal_name": "HS Rehearsal Source " + suffix,
            "base_currency": "NIO", "active": 1}).insert(ignore_permissions=True)
        source_company = frappe.get_doc({"doctype": "Company",
            "company_name": org.name, "abbr": "S" + suffix,
            "country": "Nicaragua", "default_currency": "NIO"}).insert(
                ignore_permissions=True)
        target_company = frappe.get_doc({"doctype": "Company",
            "company_name": "HS Rehearsal Target " + suffix,
            "abbr": "T" + suffix, "country": "Nicaragua",
            "default_currency": "NIO",
            "enable_perpetual_inventory": 1}).insert(ignore_permissions=True)
        today = datetime.now(ZoneInfo("America/Managua")).date()
        previous = today - timedelta(days=1)
        year = str(today.year)
        frappe.get_doc({"doctype": "Fiscal Year", "year": "HS Rehearsal FY " + suffix,
            "year_start_date": year + "-01-01", "year_end_date": year + "-12-31",
            "companies": [{"company": target_company.name}]}).insert(
                ignore_permissions=True)
        frappe.db.set_single_value("HS Site Mode", "provider", "PMS")
        # The ERPNext smoke site starts with ERP Link setters. A real PMS site
        # staged with ERPNext runs this during migrate before PMS work resumes.
        from hospitality_suite.install import restore_pms_data_fields
        restore_pms_data_fields()
        # Installing ERPNext for a future cutover does not freeze PMS work.
        # The target native book stays unavailable for hotel operations.
        from frappe.model.naming import make_autoname
        prop = frappe.get_doc({"doctype": "HS Property",
            "name": make_autoname("ESTAB-.#####"),
            "property_name": "HS Rehearsal Hotel " + suffix,
            "company": source_company.name, "organization": org.name,
            "currency": "NIO", "mode": "Hotel",
            "lodging_charge_policy": "Arrival",
            "advance_policy": "Manual", "guarantee_policy": "Manual",
            "cancellation_fee_mode": "None", "no_show_fee_mode": "None",
            "time_zone": "America/Managua", "close_time": "06:00:00",
            "check_in_time": "14:00:00", "check_out_time": "12:00:00",
            "cleaning_minutes": 30, "hold_minutes": 15,
            "retention_days": 365, "checkout_quote_minutes": 5,
            "schedule_rounding_minutes": 60,
            "business_date": str(today)})
        prop.db_insert()
        from hospitality_suite.api import execute
        from hospitality_suite.security import validate_standard, guard_cancel
        frappe.db.savepoint("hs_mixed_pms_operation_probe")
        try:
            created = execute(prop.name, "pms_account", "mixed-pms-" + suffix,
                {"account_code": "MIXED-" + suffix,
                 "account_name": "Caja PMS durante preparación",
                 "root_type": "Asset", "account_type": "Cash",
                 "account_currency": "NIO"})
            if not frappe.db.exists("HS Account", created["account"]):
                frappe.throw("PMS could not post while ERPNext was staged")
            capital = execute(prop.name, "pms_account",
                "mixed-capital-" + suffix,
                {"account_code": "MIXED-EQ-" + suffix,
                 "account_name": "Capital PMS durante preparación",
                 "root_type": "Equity", "account_type": "Equity",
                 "account_currency": "NIO"})
            opening = execute(prop.name, "pms_opening_balance",
                "mixed-opening-" + suffix,
                {"reference": "MIXED-OPENING-" + suffix,
                 "lines": [{"account": created["account"], "debit": "5",
                            "credit": "0"},
                           {"account": capital["account"], "debit": "0",
                            "credit": "5"}]})
            if (not frappe.db.exists("HS Journal", opening["journal"]) or
                    frappe.db.count("GL Entry", {"company": source_company.name})):
                frappe.throw("Mixed installation wrote to the wrong accounting book")
            for blocked in ("payment", "credit_note", "purchase_order"):
                try:
                    execute(prop.name, blocked, "mixed-erp-" + blocked + suffix, {})
                except frappe.ValidationError:
                    pass
                else:
                    frappe.throw("ERPNext hotel command ran before the authority switch")
            try:
                validate_standard(frappe.get_doc({"doctype": "Sales Invoice",
                    "company": source_company.name, "hs_property": prop.name}))
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("Native ERPNext hotel voucher ran while PMS owned the book")
            try:
                guard_cancel(frappe.get_doc({"doctype": "Sales Invoice",
                    "company": source_company.name, "hs_property": prop.name}))
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("Native ERPNext hotel cancellation ran while PMS owned the book")
        finally:
            frappe.db.rollback(save_point="hs_mixed_pms_operation_probe")
        party = frappe.get_doc({"doctype": "HS Party",
            "name": make_autoname("TER-.#####"),
            "company": source_company.name, "property": prop.name,
            "organization": org.name, "party_name": "Payer " + suffix,
            "party_type": "Customer", "active": 1,
            "credit_authorized": 1, "credit_limit": "200",
            "credit_days": 10,
            "credit_valid_until": str(today + timedelta(days=30)),
            "credit_reason": "Autorización de crédito previa al corte"})
        party.db_insert()
        customer = frappe.get_doc({"doctype": "Customer",
            "customer_name": "Payer ERP " + suffix,
            "customer_type": "Individual",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name")}).insert(
                ignore_permissions=True)
        supplier_party = frappe.get_doc({"doctype": "HS Party",
            "name": make_autoname("TER-.#####"),
            "company": source_company.name, "property": prop.name,
            "organization": org.name, "party_name": "Vendor " + suffix,
            "party_type": "Supplier", "active": 1})
        supplier_party.db_insert()
        travel_agent = frappe.get_doc({"doctype": "HS Travel Agent",
            "name": frappe.generate_hash(length=10),
            "company": source_company.name, "property": prop.name,
            "agent_name": "Agencia de corte " + suffix,
            "agent_type": "Travel Agent", "commission_pct": 5,
            "pms_supplier": supplier_party.name, "active": 1})
        travel_agent.db_insert()
        supplier = frappe.get_doc({"doctype": "Supplier",
            "supplier_name": "Vendor ERP " + suffix,
            "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0},
                "name")}).insert(ignore_permissions=True)
        category = frappe.get_doc({"doctype": "HS Category",
            "name": make_autoname("CAT-.#####"),
            "company": source_company.name, "property": prop.name,
            "category_name": "Habitación de corte " + suffix, "capacity": 2})
        category.db_insert()
        room = frappe.get_doc({"doctype": "HS Room",
            "name": make_autoname("HAB-.#####"),
            "company": source_company.name, "property": prop.name,
            "room_number": "CUT-" + suffix, "category": category.name,
            "active": 1, "cleaning_status": "Clean"})
        room.db_insert()
        from hospitality_suite import api as suite_api
        legacy_ticket = suite_api.execute(prop.name, "ticket",
            "cutover-legacy-ticket-" + suffix,
            {"kind": "create", "room": room.name,
             "subject": "Solicitud anterior al corte",
             "description": "Continuar seguimiento en ERPNext", "priority": "High"})
        rate = frappe.get_doc({"doctype": "HS Rate",
            "name": make_autoname("TAR-.#####"),
            "company": source_company.name, "property": prop.name,
            "title": "Tarifa de corte " + suffix, "category": category.name,
            "mode": "Hotel", "currency": "NIO", "amount": "20",
            "active": 1})
        rate.db_insert()
        source_service = frappe.get_doc({"doctype": "HS Product",
            "name": make_autoname("PROD-.#####"),
            "company": source_company.name, "property": prop.name,
            "organization": org.name, "product_code": "ROOM-" + suffix,
            "product_name": "Alojamiento PMS", "product_type": "Service",
            "active": 1})
        source_service.db_insert()
        frappe.db.set_value("HS Property", prop.name, "lodging_item",
                            source_service.name, update_modified=False)
        frappe.db.set_value("HS Property", prop.name, "portal_enabled", 1,
                            update_modified=False)
        from hospitality_suite import portal as portal_service
        web_start = today + timedelta(days=7)
        web_data = {"full_name": "Solicitud antes del corte " + suffix,
            "email": "cutover-portal-" + suffix.lower() + "@example.invalid",
            "starts_at": str(web_start) + "T14:00:00",
            "ends_at": str(web_start + timedelta(days=1)) + "T12:00:00",
            "category": category.name, "mode": "Hotel", "quantity": 1,
            "people": 1, "request_mode": "Requested"}
        web_quote = portal_service.quote(prop.name, web_data)
        web_confirmation = portal_service.request(prop.name,
            {**web_data, "acceptance": web_quote["acceptance"]},
            "cutover-portal-" + suffix)
        source_request = frappe.get_doc("HS Portal Request", {
            "property": prop.name, "email": web_data["email"]})
        if (source_request.company != source_company.name or
                source_request.status != "Requested" or
                portal_service.confirmation(
                    web_confirmation["confirmation_url"].split("token=", 1)[1]
                )["status"] != "Requested"):
            frappe.throw("The source web request was not confirmed before cutover")
        hold_start = today + timedelta(days=9)
        hold_data = {**web_data,
            "email": "cutover-hold-" + suffix.lower() + "@example.invalid",
            "starts_at": str(hold_start) + "T14:00:00",
            "ends_at": str(hold_start + timedelta(days=1)) + "T12:00:00",
            "request_mode": "Hold"}
        hold_quote = portal_service.quote(prop.name, hold_data)
        hold_confirmation = portal_service.request(prop.name,
            {**hold_data, "acceptance": hold_quote["acceptance"]},
            "cutover-hold-" + suffix)
        source_hold = frappe.get_doc("HS Portal Request", {
            "property": prop.name, "email": hold_data["email"]})
        if (source_hold.status != "Hold" or
                frappe.db.count("HS Allocation", {
                    "portal_request": source_hold.name, "status": "Active"}) != 1 or
                portal_service.confirmation(
                    hold_confirmation["confirmation_url"].split("token=", 1)[1]
                )["status"] != "Hold"):
            frappe.throw("The source web hold did not reserve availability")
        arrival = str(today) + " 15:00:00"
        departure = str(today + timedelta(days=1)) + " 12:00:00"
        accepted_line = {"category": category.name, "room": room.name,
            "currency": "NIO", "amount": "20.00", "people": 1,
            "start": arrival, "end": departure, "units": 1,
            "rules": {"name": rate.name, "mode": "Hotel",
                      "category": category.name},
            "charge_items": {"lodging_item": source_service.name}}
        booking = frappe.get_doc({"doctype": "HS Booking",
            "name": make_autoname("RES-.YYYY.-.#####"),
            "company": source_company.name, "property": prop.name,
            "customer": party.name, "status": "Confirmed",
            "travel_agent": travel_agent.name,
            "agent_commission_pct": 5,
            "agent_commission_estimate": "1",
            "starts_at": arrival, "ends_at": departure,
            "currency": "NIO", "quote_snapshot": canonical({
                "currency": "NIO", "amount": "20.00",
                "lines": [accepted_line]})})
        booking.db_insert()
        booking_line = frappe.get_doc({"doctype": "HS Booking Room",
            "name": frappe.generate_hash(length=10),
            "parent": booking.name, "parenttype": "HS Booking",
            "parentfield": "rooms", "idx": 1, "category": category.name,
            "room": room.name, "rate": rate.name, "people": 1})
        booking_line.db_insert()
        reservation = frappe.get_doc({"doctype": "HS Allocation",
            "name": frappe.generate_hash(length=10),
            "company": source_company.name, "property": prop.name,
            "category": category.name, "room": room.name,
            "starts_at": arrival, "ends_at": departure,
            "kind": "Reservation", "status": "Active",
            "booking": booking.name, "booking_room": booking_line.name,
            "rate": rate.name, "currency": "NIO", "accepted_amount": "20.00",
            "quote_snapshot": canonical(accepted_line)})
        reservation.db_insert()
        folio = frappe.get_doc({"doctype": "HS Folio",
            "name": make_autoname("FOL-.YYYY.-.#####"),
            "company": source_company.name, "property": prop.name,
            "booking": booking.name, "customer": party.name,
            "currency": "NIO", "status": "Open", "label": "Principal"})
        folio.db_insert()

        with operation(prop):
            cash = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "CASH-" + suffix,
                "account_name": "Caja de prueba", "root_type": "Asset",
                "account_type": "Cash", "account_currency": "NIO",
                "is_cash": 1, "active": 1}).insert(ignore_permissions=True)
            if not frappe.db.exists("Mode of Payment", "Cash"):
                frappe.get_doc({"doctype": "Mode of Payment",
                    "mode_of_payment": "Cash", "type": "Cash",
                    "enabled": 1}).insert(ignore_permissions=True)
            cash_method = frappe.get_doc({"doctype": "HS Payment Method",
                "name": make_autoname("MED-.#####"),
                "company": source_company.name, "property": prop.name,
                "mode_of_payment": "Cash", "account": cash.name,
                "currency": "NIO", "is_cash": 1})
            cash_method.db_insert()
            equity = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "EQ-" + suffix,
                "account_name": "Capital de prueba", "root_type": "Equity",
                "account_type": "Equity", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            receivable = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "AR-" + suffix,
                "account_name": "Cartera de prueba", "root_type": "Asset",
                "account_type": "Receivable", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            frappe.db.set_value("HS Property", prop.name, "receivable_account",
                                receivable.name, update_modified=False)
            payable = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "AP-" + suffix,
                "account_name": "Proveedores de prueba", "root_type": "Liability",
                "account_type": "Payable", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            guarantee_liability = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "GUAR-" + suffix,
                "account_name": "Garantías de huéspedes", "root_type": "Liability",
                "account_type": "Current Liability", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            inventory = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "ST-" + suffix,
                "account_name": "Inventario de prueba", "root_type": "Asset",
                "account_type": "Stock", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            purchase_tax_account = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "TAX-" + suffix,
                "account_name": "Impuesto recuperable de compras",
                "root_type": "Asset", "account_type": "Tax",
                "account_currency": "NIO", "active": 1}).insert(
                    ignore_permissions=True)
            income = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "INC-" + suffix,
                "account_name": "Alojamiento de prueba", "root_type": "Income",
                "account_type": "Income Account", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            frappe.db.set_value("HS Product", source_service.name,
                                "income_account", income.name,
                                update_modified=False)
            tax_profile = frappe.get_doc({"doctype": "HS PMS Tax Profile",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "label": "Exento histórico " + suffix,
                "treatment": "Exempt", "rate": 0, "active": 1})
            tax_profile.db_insert()
            experience_product = frappe.get_doc({"doctype": "HS Product",
                "name": make_autoname("PROD-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "product_code": "EXP-" + suffix,
                "product_name": "Experiencia PMS", "product_type": "Service",
                "income_account": income.name, "active": 1})
            experience_product.db_insert()
            laundry_rate = frappe.get_doc({"doctype": "HS Laundry Rate",
                "name": make_autoname("LAVTAR-.#####"),
                "company": source_company.name, "property": prop.name,
                "garment": "Camisa de corte", "service_type": "Wash & Iron",
                "pms_product": experience_product.name, "currency": "NIO",
                "rate": "6", "express_rate": "9", "active": 1})
            laundry_rate.db_insert()
            experience = frappe.get_doc({"doctype": "HS Experience",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "experience_name": "Experiencia de corte " + suffix,
                "experience_category": "Activity",
                "pms_product": experience_product.name, "active": 1})
            experience.db_insert()
            experience_order = frappe.get_doc({"doctype": "HS Experience Order",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "experience": experience.name, "booking": booking.name,
                "customer": party.name,
                "pms_product": experience_product.name,
                "quantity": 1, "participants": 1,
                "unit_rate": "8", "amount": "8", "currency": "NIO",
                "status": "Reserved"})
            experience_order.db_insert()
            accepted_booking = frappe.parse_json(frappe.db.get_value(
                "HS Booking", booking.name, "quote_snapshot"))
            accepted_booking["experiences"] = [{"experience": experience.name,
                "item": None, "pms_product": experience_product.name,
                "quantity": 1, "rate": "8", "amount": "8"}]
            frappe.db.set_value("HS Booking", booking.name, "quote_snapshot",
                                canonical(accepted_booking), update_modified=False)
            source_warehouse = frappe.get_doc({"doctype": "HS Warehouse",
                "name": make_autoname("ALM-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "warehouse_code": "WH-" + suffix,
                "warehouse_name": "Almacén fuente", "active": 1})
            source_warehouse.db_insert()
            product = frappe.get_doc({"doctype": "HS Product",
                "name": make_autoname("PROD-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "product_code": "ST-" + suffix,
                "product_name": "Artículo fuente", "product_type": "Stock",
                "inventory_account": inventory.name, "active": 1})
            product.db_insert()
            source_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous), "source_doctype": "Smoke",
                "source_name": "smoke-" + suffix, "purpose": "Opening",
                "status": "Posted", "lines": [
                    {"account": cash.name, "debit": "100", "credit": "0",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "100"},
                    {"account": receivable.name, "debit": "40", "credit": "0",
                     "party": party.name, "account_currency": "NIO",
                     "exchange_rate": 1, "debit_in_account_currency": "40"},
                    {"account": inventory.name, "debit": "30", "credit": "0",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "30"},
                    {"account": payable.name, "debit": "0", "credit": "40",
                     "party": supplier_party.name, "account_currency": "NIO",
                     "exchange_rate": 1, "credit_in_account_currency": "40"},
                    {"account": equity.name, "debit": "0", "credit": "130",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "credit_in_account_currency": "130"}]}).insert(ignore_permissions=True)
            stock_movement = frappe.get_doc({"doctype": "HS Stock Movement",
                "name": make_autoname("MOVSTK-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "product": product.name,
                "warehouse": source_warehouse.name, "direction": "Receipt",
                "quantity_delta": 3, "value_delta": "30",
                "balance_quantity": 3, "balance_value": "30",
                "business_date": str(previous), "source_doctype": "Smoke",
                "source_name": "stock-" + suffix, "purpose": "Opening",
                "journal": source_journal.name})
            stock_movement.db_insert()
            source_laundry = frappe.get_doc({"doctype": "HS Warehouse",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "warehouse_code": "LINEN-" + suffix,
                "warehouse_name": "Lavandería PMS", "active": 1}).insert(
                    ignore_permissions=True)
            linen_clearing = frappe.get_doc({"doctype": "HS Account",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "LINEN-" + suffix,
                "account_name": "Tránsito ropa de hotel", "root_type": "Asset",
                "account_type": "Temporary", "account_currency": "NIO",
                "active": 1}).insert(ignore_permissions=True)
            frappe.db.set_value("HS Property", prop.name, {
                "pms_linen_operating_warehouse": source_warehouse.name,
                "pms_linen_laundry_warehouse": source_laundry.name,
                "pms_linen_clearing_account": linen_clearing.name,
                "business_date": str(previous)}, update_modified=False)
            prop.reload()
            from hospitality_suite import standalone_linen
            linen_transfer = standalone_linen.move(prop, {
                "room": room.name, "item": product.name,
                "quantity": "1", "direction": "Send"})
            if (not linen_transfer["stock_entry"] or
                    frappe.db.get_value("HS Incident", linen_transfer["incident"],
                                        "linen_direction") != "Send"):
                frappe.throw("The PMS linen transfer was not posted before cutover")
            frappe.db.set_value("HS Property", prop.name, "business_date",
                                str(today), update_modified=False)
            prop.reload()
            pms_receivable = frappe.get_doc({"doctype": "HS PMS Receivable",
                "name": make_autoname("COBR-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "party": party.name,
                "reference": "ROOM-" + suffix,
                "description": "Alojamiento histórico",
                "business_date": str(previous),
                "receivable_account": receivable.name,
                "income_account": income.name,
                "currency": "NIO", "amount": "40",
                "net_amount": "40", "tax_amount": "0",
                "tax_profile": tax_profile.name, "tax_treatment": "Exempt",
                "folio": folio.name, "booking": booking.name,
                "due_date": str(today + timedelta(days=7)),
                "journal": source_journal.name, "status": "Posted"})
            pms_receivable.db_insert()
            guarantee = frappe.get_doc({"doctype": "HS Payment",
                "name": make_autoname("PAG-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "folio": folio.name,
                "pms_party": party.name,
                "pms_counter_account": guarantee_liability.name,
                "currency": "NIO", "amount": "30", "base_amount": "30",
                "exchange_rate": 1, "kind": "Guarantee", "status": "Posted"})
            guarantee.db_insert()
            guarantee_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous), "source_doctype": "HS Payment",
                "source_name": guarantee.name, "purpose": "Guarantee",
                "status": "Posted", "lines": [
                    {"account": cash.name, "debit": "30", "credit": "0",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "30"},
                    {"account": guarantee_liability.name,
                     "debit": "0", "credit": "30",
                     "party": party.name, "account_currency": "NIO",
                     "exchange_rate": 1,
                     "credit_in_account_currency": "30"}]}).insert(
                        ignore_permissions=True)
            frappe.db.set_value("HS Payment", guarantee.name, "pms_journal",
                                guarantee_journal.name, update_modified=False)
            allocation = frappe.get_doc({"doctype": "HS PMS Allocation",
                "name": make_autoname("APL-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name,
                "receivable": pms_receivable.name, "payment": guarantee.name,
                "kind": "Guarantee Applied", "business_date": str(previous),
                "currency": "NIO", "amount": "10"})
            allocation.db_insert()
            application_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous),
                "source_doctype": "HS PMS Allocation",
                "source_name": allocation.name,
                "purpose": "Guarantee Applied", "status": "Posted",
                "lines": [
                    {"account": guarantee_liability.name,
                     "debit": "10", "credit": "0", "party": party.name,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "10"},
                    {"account": receivable.name, "debit": "0", "credit": "10",
                     "party": party.name, "account_currency": "NIO",
                     "exchange_rate": 1,
                     "credit_in_account_currency": "10"}]}).insert(
                        ignore_permissions=True)
            frappe.db.set_value("HS PMS Allocation", allocation.name, "journal",
                                application_journal.name, update_modified=False)
            historical_refund = frappe.get_doc({"doctype": "HS Payment",
                "name": make_autoname("PAG-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "folio": folio.name, "pms_party": party.name,
                "pms_counter_account": guarantee_liability.name,
                "source_payment": guarantee.name,
                "currency": "NIO", "amount": "5", "base_amount": "5",
                "exchange_rate": 1, "kind": "Guarantee Refund",
                "status": "Posted"})
            historical_refund.db_insert()
            refund_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous), "source_doctype": "HS Payment",
                "source_name": historical_refund.name,
                "purpose": "Refund", "status": "Posted",
                "lines": [
                    {"account": guarantee_liability.name,
                     "debit": "5", "credit": "0", "party": party.name,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "5"},
                    {"account": cash.name, "debit": "0", "credit": "5",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "credit_in_account_currency": "5"}]}).insert(
                        ignore_permissions=True)
            frappe.db.set_value("HS Payment", historical_refund.name,
                "pms_journal", refund_journal.name, update_modified=False)
            advance = frappe.get_doc({"doctype": "HS Payment",
                "name": make_autoname("PAG-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "pms_party": party.name,
                "pms_counter_account": guarantee_liability.name,
                "currency": "NIO", "amount": "20", "base_amount": "20",
                "exchange_rate": 1, "kind": "Advance", "status": "Posted"})
            advance.db_insert()
            advance_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous), "source_doctype": "HS Payment",
                "source_name": advance.name, "purpose": "Advance",
                "status": "Posted", "lines": [
                    {"account": cash.name, "debit": "20", "credit": "0",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "20"},
                    {"account": guarantee_liability.name,
                     "debit": "0", "credit": "20", "party": party.name,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "credit_in_account_currency": "20"}]}).insert(
                        ignore_permissions=True)
            frappe.db.set_value("HS Payment", advance.name, "pms_journal",
                                advance_journal.name, update_modified=False)
            advance_allocation = frappe.get_doc({"doctype": "HS PMS Allocation",
                "name": make_autoname("APL-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name,
                "receivable": pms_receivable.name, "payment": advance.name,
                "kind": "Advance Applied", "business_date": str(previous),
                "currency": "NIO", "amount": "5"})
            advance_allocation.db_insert()
            advance_application_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous),
                "source_doctype": "HS PMS Allocation",
                "source_name": advance_allocation.name,
                "purpose": "Advance Applied", "status": "Posted",
                "lines": [
                    {"account": guarantee_liability.name,
                     "debit": "5", "credit": "0", "party": party.name,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "5"},
                    {"account": receivable.name, "debit": "0", "credit": "5",
                     "party": party.name, "account_currency": "NIO",
                     "exchange_rate": 1,
                     "credit_in_account_currency": "5"}]}).insert(
                        ignore_permissions=True)
            frappe.db.set_value("HS PMS Allocation", advance_allocation.name,
                "journal", advance_application_journal.name,
                update_modified=False)
            advance_refund = frappe.get_doc({"doctype": "HS Payment",
                "name": make_autoname("PAG-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "pms_party": party.name,
                "pms_counter_account": guarantee_liability.name,
                "source_payment": advance.name,
                "currency": "NIO", "amount": "3", "base_amount": "3",
                "exchange_rate": 1, "kind": "Refund", "status": "Posted"})
            advance_refund.db_insert()
            advance_refund_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous), "source_doctype": "HS Payment",
                "source_name": advance_refund.name,
                "purpose": "Refund", "status": "Posted", "lines": [
                    {"account": guarantee_liability.name,
                     "debit": "3", "credit": "0", "party": party.name,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "3"},
                    {"account": cash.name, "debit": "0", "credit": "3",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "credit_in_account_currency": "3"}]}).insert(
                        ignore_permissions=True)
            frappe.db.set_value("HS Payment", advance_refund.name,
                "pms_journal", advance_refund_journal.name,
                update_modified=False)
            pms_purchase = frappe.get_doc({"doctype": "HS PMS Purchase",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "supplier": supplier_party.name,
                "supplier_reference": "INV-" + suffix,
                "invoice_currency": "NIO", "invoice_amount": "40",
                "exchange_rate": 1, "base_amount": "40",
                "payable_account": payable.name,
                "journal": source_journal.name, "status": "Posted"})
            pms_purchase.db_insert()
            # A foreign-currency PMS loan retains principal in the base ledger.
            foreign_bank = frappe.get_doc({"doctype": "HS Account",
                "name": make_autoname("CUENTA-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "BANK-USD-" + suffix,
                "account_name": "Banco USD de corte", "root_type": "Asset",
                "account_type": "Bank", "account_currency": "USD",
                "is_bank": 1, "active": 1})
            foreign_bank.db_insert()
            frappe.get_doc({"doctype": "HS Property Currency",
                "parent": prop.name, "parenttype": "HS Property",
                "parentfield": "accepted_currencies", "idx": 1,
                "currency": "USD"}).db_insert()
            source_foreign_mode = "PMS USD " + suffix
            source_foreign_method = frappe.get_doc({
                "doctype": "HS Payment Method",
                "name": make_autoname("MED-.#####"),
                "company": source_company.name, "property": prop.name,
                "mode_of_payment": source_foreign_mode,
                "account": foreign_bank.name, "currency": "USD",
                "is_cash": 0, "reference_required": 1})
            source_foreign_method.db_insert()
            loan_liability = frappe.get_doc({"doctype": "HS Account",
                "name": make_autoname("CUENTA-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "LOAN-" + suffix,
                "account_name": "Préstamo histórico", "root_type": "Liability",
                "account_type": "Current Liability", "account_currency": "NIO",
                "active": 1})
            loan_liability.db_insert()
            loan_concept = frappe.get_doc({"doctype": "HS Treasury Concept",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "label": "Préstamo histórico", "nature": "Loan",
                "account": loan_liability.name, "currency": "NIO", "active": 1})
            loan_concept.db_insert()
            historical_loan = frappe.get_doc({"doctype": "HS Treasury Movement",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "kind": "Loan Received", "concept": loan_concept.name,
                "concept_label": loan_concept.label,
                "cash_account": foreign_bank.name,
                "counter_account": loan_liability.name,
                "currency": "USD", "amount": "2", "base_amount": "73",
                "exchange_rate": "36.5", "business_date": str(previous),
                "reference": "LOAN-" + suffix, "reason": "Préstamo anterior",
                "status": "Posted", "requested_by": "Administrator"})
            historical_loan.db_insert()
            loan_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous),
                "source_doctype": "HS Treasury Movement",
                "source_name": historical_loan.name, "purpose": "Loan Received",
                "status": "Posted", "lines": [
                    {"account": foreign_bank.name, "debit": "73", "credit": "0",
                     "account_currency": "USD", "exchange_rate": "36.5",
                     "debit_in_account_currency": "2"},
                    {"account": loan_liability.name, "debit": "0", "credit": "73",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "credit_in_account_currency": "73"}]}).insert(ignore_permissions=True)
            frappe.db.set_value("HS Treasury Movement", historical_loan.name,
                "pms_journal", loan_journal.name, update_modified=False)
            historical_repayment = frappe.get_doc({"doctype": "HS Treasury Movement",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "kind": "Loan Repayment", "concept": loan_concept.name,
                "concept_label": loan_concept.label,
                "source_movement": historical_loan.name,
                "cash_account": foreign_bank.name,
                "counter_account": loan_liability.name,
                "currency": "USD", "amount": "1", "base_amount": "36.5",
                "exchange_rate": "36.5", "business_date": str(previous),
                "reference": "REPAY-" + suffix, "reason": "Abono anterior",
                "status": "Posted", "requested_by": "Administrator"})
            historical_repayment.db_insert()
            repayment_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous),
                "source_doctype": "HS Treasury Movement",
                "source_name": historical_repayment.name,
                "purpose": "Loan Repayment", "status": "Posted", "lines": [
                    {"account": loan_liability.name, "debit": "36.5", "credit": "0",
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "36.5"},
                    {"account": foreign_bank.name, "debit": "0", "credit": "36.5",
                     "account_currency": "USD", "exchange_rate": "36.5",
                     "credit_in_account_currency": "1"}]}).insert(ignore_permissions=True)
            frappe.db.set_value("HS Treasury Movement", historical_repayment.name,
                "pms_journal", repayment_journal.name, update_modified=False)
            petty_account = frappe.get_doc({"doctype": "HS Account",
                "name": make_autoname("CUENTA-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "PETTY-" + suffix,
                "account_name": "Caja Chica histórica", "root_type": "Asset",
                "account_type": "Cash", "account_currency": "NIO",
                "is_cash": 1, "active": 1})
            petty_account.db_insert()
            petty_expense_account = frappe.get_doc({"doctype": "HS Account",
                "name": make_autoname("CUENTA-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "account_code": "PETTY-EXP-" + suffix,
                "account_name": "Gastos menores históricos",
                "root_type": "Expense", "account_type": "Expense Account",
                "account_currency": "NIO", "active": 1})
            petty_expense_account.db_insert()
            frappe.db.set_value("HS Property", prop.name, {
                "petty_cash_account": petty_account.name,
                "petty_cash_responsible": "Administrator",
                "petty_cash_overage_account": income.name,
                "petty_cash_shortage_account": petty_expense_account.name},
                update_modified=False)
            petty_category = frappe.get_doc({"doctype": "HS Expense Category",
                "name": make_autoname("CATG-.#####"),
                "company": source_company.name, "property": prop.name,
                "label": "Gastos menores de corte",
                "account": petty_expense_account.name,
                "currency": "NIO", "max_amount": 50, "active": 1})
            petty_category.db_insert()

            def historical_petty_journal(movement, kind, value, debit, credit):
                posted = frappe.get_doc({"doctype": "HS Journal",
                    "company": source_company.name, "property": prop.name,
                    "organization": org.name, "posting_date": str(previous),
                    "business_date": str(previous),
                    "source_doctype": movement.doctype,
                    "source_name": movement.name, "purpose": kind,
                    "status": "Posted", "lines": [
                        {"account": debit, "debit": value, "credit": 0,
                         "account_currency": "NIO", "exchange_rate": 1,
                         "debit_in_account_currency": value},
                        {"account": credit, "debit": 0, "credit": value,
                         "account_currency": "NIO", "exchange_rate": 1,
                         "credit_in_account_currency": value}]}).insert(
                             ignore_permissions=True)
                frappe.db.set_value(movement.doctype, movement.name,
                    "pms_journal", posted.name, update_modified=False)

            initial_fund = frappe.get_doc({"doctype": "HS Treasury Movement",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "kind": "Initial Fund", "cash_account": cash.name,
                "counter_account": petty_account.name,
                "currency": "NIO", "amount": 50, "base_amount": 50,
                "exchange_rate": 1, "business_date": str(previous),
                "status": "Posted", "requested_by": "Administrator"})
            initial_fund.db_insert()
            historical_petty_journal(initial_fund, "Initial Fund", 50,
                                     petty_account.name, cash.name)
            petty_expense = frappe.get_doc({"doctype": "HS Petty Cash Expense",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "category": petty_category.name,
                "category_label": petty_category.label,
                "responsible": "Administrator", "beneficiary": "Proveedor menor",
                "concept": "Gasto histórico", "receipt_reference": "REC-" + suffix,
                "business_date": str(previous), "currency": "NIO",
                "amount": 20, "expense_account": petty_expense_account.name,
                "petty_account": petty_account.name, "status": "Posted"})
            petty_expense.db_insert()
            historical_petty_journal(petty_expense, "Petty Cash Expense", 20,
                                     petty_expense_account.name, petty_account.name)
            petty_rendition = frappe.get_doc({"doctype": "HS Petty Cash Rendition",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "responsible": "Administrator", "expenses": canonical([petty_expense.name]),
                "currency": "NIO", "expense_total": 20,
                "expected_cash": 30, "counted_cash": 30, "variance": 0,
                "status": "Partially Reimbursed", "submitted_by": "Administrator",
                "submitted_at": frappe.utils.now_datetime(),
                "reviewed_by": "Administrator",
                "reviewed_at": frappe.utils.now_datetime(),
                "approved_business_date": str(previous)})
            petty_rendition.db_insert()
            frappe.db.set_value("HS Petty Cash Expense", petty_expense.name,
                "rendition", petty_rendition.name, update_modified=False)
            prior_replenishment = frappe.get_doc({"doctype": "HS Treasury Movement",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "kind": "Replenishment", "rendition": petty_rendition.name,
                "cash_account": cash.name,
                "counter_account": petty_account.name,
                "currency": "NIO", "amount": 8, "base_amount": 8,
                "exchange_rate": 1, "business_date": str(previous),
                "status": "Posted", "requested_by": "Administrator"})
            prior_replenishment.db_insert()
            historical_petty_journal(prior_replenishment, "Replenishment", 8,
                                     petty_account.name, cash.name)
            frappe.get_doc({"doctype": "HS Daily Close",
                "company": source_company.name, "property": prop.name,
                "business_date": str(previous), "revision": 1,
                "status": "Closed", "summary": "{}",
                "closed_at": frappe.utils.now_datetime()}).insert(
                    ignore_permissions=True)

        from hospitality_suite import api as suite_api
        fiscal_series = suite_api.execute(prop.name, "pms_fiscal_series",
            "cutover-fiscal-series-" + suffix,
            {"series_code": "HIST-" + suffix + "-", "document_type": "Invoice",
             "start_number": 1, "end_number": 10, "padding": 6})["series"]
        fiscal_request = {"series": fiscal_series,
                          "receivables": [pms_receivable.name]}
        fiscal_review = suite_api.pms_invoice_quote(prop.name, fiscal_request)
        historical_fiscal = suite_api.execute(prop.name, "pms_issue_invoice",
            "cutover-fiscal-invoice-" + suffix,
            {**fiscal_request, "acceptance": fiscal_review["acceptance"]})
        if (historical_fiscal["document_number"] not in frappe.get_print(
                "HS PMS Fiscal Document", historical_fiscal["document"],
                print_format="HS Documento fiscal PMS")):
            frappe.throw("The source fiscal document cannot be printed")

        def target_account(**filters):
            return frappe.db.get_value("Account", {"company": target_company.name,
                "is_group": 0, **filters}, "name")

        if not frappe.db.exists("Item Group", "All Item Groups"):
            frappe.get_doc({"doctype": "Item Group",
                "item_group_name": "All Item Groups", "is_group": 1}).insert(
                    ignore_permissions=True)
        group = frappe.get_doc({"doctype": "Item Group",
            "item_group_name": "HS Rehearsal Group " + suffix,
            "is_group": 0, "parent_item_group": "All Item Groups"}).insert(
                ignore_permissions=True)
        item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-REHEARSAL-" + suffix,
            "item_name": "Artículo ERP " + suffix, "is_stock_item": 1,
            "is_purchase_item": 1,
            "item_group": group.name, "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        lodging_item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-REHEARSAL-ROOM-" + suffix,
            "item_name": "Alojamiento ERP " + suffix,
            "is_stock_item": 0, "is_sales_item": 1,
            "item_group": group.name, "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        experience_item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-REHEARSAL-EXP-" + suffix,
            "item_name": "Experiencia ERP " + suffix,
            "is_stock_item": 0, "is_sales_item": 1,
            "item_group": group.name, "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        commission_item = frappe.get_doc({"doctype": "Item",
            "item_code": "HS-REHEARSAL-COMMISSION-" + suffix,
            "item_name": "Comisión de agencia ERP " + suffix,
            "is_stock_item": 0, "is_purchase_item": 1,
            "item_group": group.name, "stock_uom": "Nos", "uom": "Nos"}).insert(
                ignore_permissions=True)
        price_list = frappe.get_doc({"doctype": "Price List",
            "price_list_name": "HS Rehearsal Sales " + suffix,
            "currency": "NIO", "selling": 1, "enabled": 1})
        price_list.db_insert()
        frappe.get_doc({"doctype": "Item Price",
            "item_code": experience_item.name, "price_list": price_list.name,
            "currency": "NIO", "selling": 1,
            "price_list_rate": "8"}).db_insert()
        target_warehouse = frappe.db.get_value("Warehouse", {
            "company": target_company.name, "is_group": 0,
            "warehouse_name": "Stores"}, "name")
        from erpnext.stock import get_warehouse_account
        stock_account = get_warehouse_account(
            frappe.get_doc("Warehouse", target_warehouse), raise_error=True)
        target_laundry = frappe.get_doc({"doctype": "Warehouse",
            "warehouse_name": "HS Rehearsal Laundry " + suffix,
            "company": target_company.name,
            "parent_warehouse": frappe.db.get_value("Warehouse", {
                "company": target_company.name, "is_group": 1}, "name")}).insert(
                    ignore_permissions=True)
        target_linen_clearing = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Linen Transit " + suffix,
            "parent_account": frappe.db.get_value("Account", {
                "company": target_company.name,
                "account_name": "Current Assets", "is_group": 1}, "name"),
            "company": target_company.name, "account_type": "Temporary",
            "account_currency": "NIO", "is_group": 0}).insert(
                ignore_permissions=True)
        target_opening_temp = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Opening Transit " + suffix,
            "parent_account": frappe.db.get_value("Account", {
                "company": target_company.name,
                "account_name": "Current Assets", "is_group": 1}, "name"),
            "company": target_company.name, "account_type": "Temporary",
            "account_currency": "NIO", "is_group": 0}).insert(
                ignore_permissions=True)
        with operation(prop):
            approved_order = frappe.get_doc({"doctype": "HS PMS Purchase Order",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "supplier": supplier_party.name,
                "reference": "APPROVED-" + suffix, "currency": "NIO",
                "payable_account": payable.name,
                "tax_account": purchase_tax_account.name,
                "amount": "12", "recoverable_tax": "2",
                "business_date": str(previous),
                "expected_date": str(today + timedelta(days=1)),
                "requested_by": "Administrator", "status": "Pending",
                "lines": [{"product": product.name,
                    "warehouse": source_warehouse.name,
                    "quantity": 2, "currency": "NIO", "amount": "12",
                    "recoverable_tax": "2",
                    "inventory_account": inventory.name}]}).insert(
                        ignore_permissions=True)
        frappe.db.set_value("HS PMS Purchase Order", approved_order.name,
            {"status": "Approved", "approved_by": "Guest",
             "approved_at": frappe.utils.now_datetime()},
            update_modified=False)
        target_purchase_tax = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Purchase Tax " + suffix,
            "parent_account": frappe.db.get_value("Account", {
                "company": target_company.name,
                "account_name": "Current Assets", "is_group": 1}, "name"),
            "company": target_company.name, "account_type": "Tax",
            "account_currency": "NIO", "is_group": 0}).insert(
                ignore_permissions=True)
        frappe.db.savepoint("hs_open_day_pass_preflight_probe")
        try:
            active_pass = frappe.get_doc({"doctype": "HS Day Pass",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "customer": party.name, "people": 1,
                "starts_at": frappe.utils.now_datetime(),
                "ends_at": frappe.utils.now_datetime() + timedelta(hours=2),
                "status": "Issued", "pms_receivable": pms_receivable.name})
            active_pass.db_insert()
            active_review = pms_cutover.preflight()
            if not any(row["code"] == "invalid_active_pms_day_pass_quote" and
                       row["source"] == active_pass.name for row in
                       active_review["blockers"]):
                frappe.throw("An invalid PMS Day Pass did not block cutover")
            frozen_passes = next(row for row in active_review["properties"]
                if row["property"] == prop.name)["open_operations"]["day_passes"]
            if not any(row["name"] == active_pass.name and
                       row["pms_receivable"] == pms_receivable.name and
                       row["quote_sha256"] == sha256(b"").hexdigest()
                       for row in frozen_passes):
                frappe.throw("The active PMS Day Pass was not frozen in preflight")
            frappe.db.set_value("HS Day Pass", active_pass.name, "ends_at",
                frappe.utils.now_datetime() - timedelta(minutes=1),
                update_modified=False)
            expired_review = pms_cutover.preflight()
            if any(row["code"] == "invalid_active_pms_day_pass_quote" and
                   row["source"] == active_pass.name for row in
                   expired_review["blockers"]):
                frappe.throw("An expired PMS Day Pass still blocked cutover")
            expired_passes = next(row for row in expired_review["properties"]
                if row["property"] == prop.name)["open_operations"]["day_passes"]
            if any(row["name"] == active_pass.name for row in expired_passes):
                frappe.throw("An expired PMS Day Pass remained in live work")
        finally:
            frappe.db.rollback(save_point="hs_open_day_pass_preflight_probe")
        baseline = pms_cutover.preflight()
        if not baseline["ready_for_mapping"]:
            frappe.throw("A complete open reservation did not pass preflight: " +
                         frappe.as_json(baseline["blockers"]))
        frappe.db.savepoint("hs_property_config_preflight_probe")
        try:
            frappe.db.set_value("HS Property", prop.name, {
                "hold_minutes": 0, "lodging_charge_policy": ""},
                update_modified=False)
            invalid_settings = pms_cutover.preflight()
            codes = {(row["code"], row.get("field"))
                     for row in invalid_settings["blockers"]}
            if (("invalid_property_timing_setting", "hold_minutes") not in codes or
                    ("missing_property_required_field", "lodging_charge_policy") not in codes or
                    invalid_settings["ready_for_mapping"]):
                frappe.throw("Invalid property settings passed cutover preflight")
        finally:
            frappe.db.rollback(save_point="hs_property_config_preflight_probe")
        if pms_cutover.preflight()["source_sha256"] != baseline["source_sha256"]:
            frappe.throw("The property configuration probe changed the source")
        frappe.db.savepoint("hs_open_purchase_order_preflight_probe")
        try:
            with operation(prop):
                pending_order = frappe.get_doc({"doctype": "HS PMS Purchase Order",
                    "company": source_company.name, "property": prop.name,
                    "organization": org.name, "supplier": supplier_party.name,
                    "reference": "PO-CUTOVER-" + suffix, "currency": "NIO",
                    "payable_account": payable.name, "amount": "12",
                    "recoverable_tax": 0, "business_date": str(previous),
                    "requested_by": "Administrator", "status": "Pending",
                    "lines": [{"product": product.name,
                        "warehouse": source_warehouse.name,
                        "quantity": 2, "currency": "NIO",
                        "amount": "12", "recoverable_tax": 0,
                        "inventory_account": inventory.name}]}).insert(
                            ignore_permissions=True)
            pending_source = pms_cutover.preflight()
            match = [row for row in pending_source["blockers"] if
                row["code"] == "unapproved_pms_purchase_order" and
                row["source"] == pending_order.name]
            if (pending_source["ready_for_mapping"] or len(match) != 1 or
                    match[0]["remaining"][0]["quantity"] != "2"):
                frappe.throw("An unapproved PMS purchase order passed cutover")
        finally:
            frappe.db.rollback(save_point="hs_open_purchase_order_preflight_probe")
        if pms_cutover.preflight()["source_sha256"] != baseline["source_sha256"]:
            frappe.throw("The purchase-order probe changed the source")
        accepted_booking_snapshot = frappe.db.get_value(
            "HS Booking", booking.name, "quote_snapshot")
        frappe.db.savepoint("hs_pending_experience_preflight_probe")
        try:
            direct_order = frappe.get_doc({"doctype": "HS Experience Order",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "customer": party.name, "pms_product": source_service.name,
                "quantity": 1, "participants": 1,
                "unit_rate": "20", "amount": "20", "currency": "NIO",
                "status": "Confirmed"})
            direct_order.db_insert()
            invalid_experience = pms_cutover.preflight()
            if not any(row["code"] == "pending_direct_experience_incomplete" and
                       row.get("source") == direct_order.name for row in
                       invalid_experience["blockers"]):
                frappe.throw("Cutover accepted an unpriced direct PMS experience")
        finally:
            frappe.db.rollback(save_point="hs_pending_experience_preflight_probe")
        frappe.db.savepoint("hs_open_stay_preflight_probe")
        try:
            guest = frappe.get_doc({"doctype": "HS Guest",
                "name": make_autoname("HUE-.#####"),
                "company": source_company.name, "property": prop.name,
                "customer": party.name, "full_name": "Guest " + suffix})
            guest.db_insert()
            stay = frappe.get_doc({"doctype": "HS Stay",
                "name": make_autoname("EST-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "booking": booking.name, "guest": guest.name,
                "customer": party.name, "room": room.name,
                "rate": rate.name, "starts_at": arrival, "ends_at": departure,
                "status": "Active", "currency": "NIO", "amount": "20.00",
                "quote_snapshot": canonical(accepted_line),
                "service_entitlements": "[]"})
            stay.db_insert()
            frappe.db.set_value("HS Booking", booking.name, "status",
                                "Checked In", update_modified=False)
            frappe.db.set_value("HS Allocation", reservation.name,
                                {"kind": "Stay", "stay": stay.name},
                                update_modified=False)
            frappe.db.set_value("HS Folio", folio.name, "stay", stay.name,
                                update_modified=False)
            if not pms_cutover.preflight()["ready_for_mapping"]:
                frappe.throw("A complete active stay did not pass preflight")
            frappe.db.set_value("HS Allocation", reservation.name, "status",
                                "Released", update_modified=False)
            invalid_stay = pms_cutover.preflight()
            if not any(row["code"] == "active_stay_incomplete" and
                       row.get("source") == stay.name for row in
                       invalid_stay["blockers"]):
                frappe.throw("Cutover accepted an active stay without allocation")
        finally:
            frappe.db.rollback(save_point="hs_open_stay_preflight_probe")
        frappe.db.set_value("HS Booking", booking.name, "quote_snapshot", "{}",
                            update_modified=False)
        invalid_booking = pms_cutover.preflight()
        if (not any(row["code"] == "open_booking_incomplete_quote" and
                    row.get("source") == booking.name for row in
                    invalid_booking["blockers"]) or
                invalid_booking["source_sha256"] == baseline["source_sha256"]):
            frappe.throw("Cutover accepted an unusable open reservation quote")
        embedded_line = {**accepted_line,
            "charge_items": {"lodging_item": product.name}}
        changed_booking = frappe.parse_json(accepted_booking_snapshot)
        changed_booking["lines"] = [embedded_line]
        frappe.db.set_value("HS Booking", booking.name, "quote_snapshot",
                            canonical(changed_booking),
                            update_modified=False)
        embedded_booking = pms_cutover.preflight()
        if (not embedded_booking["ready_for_mapping"] or
                embedded_booking["source_sha256"] == baseline["source_sha256"] or
                not any(row["name"] == booking.name and
                        product.name in row["embedded_products"] for row in
                        embedded_booking["properties"][0]["open_operations"]["bookings"])):
            frappe.throw("Preflight lost an embedded product in an open quote")
        frappe.db.set_value("HS Booking", booking.name, "quote_snapshot",
                            accepted_booking_snapshot,
                            update_modified=False)
        frappe.db.set_value("HS Allocation", reservation.name,
                            "quote_snapshot", canonical(embedded_line),
                            update_modified=False)
        embedded_allocation = pms_cutover.preflight()
        if (not embedded_allocation["ready_for_mapping"] or
                embedded_allocation["source_sha256"] == baseline["source_sha256"] or
                not any(row["name"] == reservation.name and
                        row["embedded_products"] == [product.name] for row in
                        embedded_allocation["properties"][0]["open_operations"]["bookings"][0]["allocations"])):
            frappe.throw("Preflight lost an embedded product in an allocation")
        frappe.db.set_value("HS Allocation", reservation.name,
                            "quote_snapshot", canonical(accepted_line),
                            update_modified=False)
        frappe.db.set_value("HS Allocation", reservation.name, "status",
                            "Released", update_modified=False)
        invalid_allocation = pms_cutover.preflight()
        if not any(row["code"] == "open_booking_allocation_mismatch" and
                   row.get("source") == booking.name for row in
                   invalid_allocation["blockers"]):
            frappe.throw("Cutover accepted a reservation without its room allocation")
        frappe.db.set_value("HS Allocation", reservation.name, "status",
                            "Active", update_modified=False)
        frappe.db.set_value("HS Folio", folio.name, "booking", None,
                            update_modified=False)
        invalid_folio = pms_cutover.preflight()
        if not any(row["code"] == "open_folio_invalid_link" and
                   row.get("source") == folio.name for row in
                   invalid_folio["blockers"]):
            frappe.throw("Cutover accepted an open folio without its visit")
        frappe.db.set_value("HS Folio", folio.name, "booking", booking.name,
                            update_modified=False)
        if pms_cutover.preflight()["source_sha256"] != baseline["source_sha256"]:
            frappe.throw("Restoring the reservation did not restore the source fingerprint")
        frappe.db.set_value("HS Payment", guarantee.name, "pms_journal",
                            source_journal.name, update_modified=False)
        invalid_origin = pms_cutover.preflight()
        if not any(row["code"] == "invalid_guarantee_origin" and
                   row.get("source") == guarantee.name
                   for row in invalid_origin["blockers"]):
            frappe.throw("Cutover accepted a guarantee with the wrong source journal")
        frappe.db.set_value("HS Payment", guarantee.name, "pms_journal",
                            guarantee_journal.name, update_modified=False)
        frappe.db.set_value("HS PMS Allocation", advance_allocation.name,
                            "journal", source_journal.name, update_modified=False)
        invalid_application = pms_cutover.preflight()
        if not any(row["code"] == "invalid_deposit_application_journal" and
                   row.get("allocation") == advance_allocation.name
                   for row in invalid_application["blockers"]):
            frappe.throw("Cutover accepted an unposted advance application")
        frappe.db.set_value("HS PMS Allocation", advance_allocation.name,
                            "journal", advance_application_journal.name,
                            update_modified=False)
        frappe.db.set_value("HS Payment", advance_refund.name, "pms_journal",
                            source_journal.name, update_modified=False)
        invalid_refund = pms_cutover.preflight()
        if not any(row["code"] == "invalid_deposit_refund_journal" and
                   row.get("refund") == advance_refund.name
                   for row in invalid_refund["blockers"]):
            frappe.throw("Cutover accepted an unposted advance refund")
        frappe.db.set_value("HS Payment", advance_refund.name, "pms_journal",
                            advance_refund_journal.name, update_modified=False)
        target_liability = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Guest Guarantees " + suffix,
            "parent_account": frappe.db.get_value("Account", {
                "company": target_company.name,
                "account_name": "Current Liabilities", "is_group": 1}, "name"),
            "company": target_company.name,
            "account_currency": "NIO", "is_group": 0}).insert(
                ignore_permissions=True)
        target_loan = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Historical Loan " + suffix,
            "parent_account": frappe.db.get_value("Account", {
                "company": target_company.name,
                "account_name": "Current Liabilities", "is_group": 1}, "name"),
            "company": target_company.name,
            "account_currency": "NIO", "is_group": 0}).insert(
                ignore_permissions=True)
        bank_parent = (frappe.db.get_value("Account", {
            "company": target_company.name, "account_name": "Bank Accounts",
            "is_group": 1}, "name") or frappe.db.get_value("Account", {
            "company": target_company.name, "account_name": "Current Assets",
            "is_group": 1}, "name"))
        target_foreign_bank = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Foreign Bank " + suffix,
            "parent_account": bank_parent, "company": target_company.name,
            "account_type": "Bank", "account_currency": "USD",
            "is_group": 0}).insert(ignore_permissions=True)
        target_foreign_mode = "HS USD Bank " + suffix
        frappe.get_doc({"doctype": "Mode of Payment",
            "mode_of_payment": target_foreign_mode, "type": "Bank",
            "enabled": 1}).insert(ignore_permissions=True)
        target_shift_cash = target_account(account_type="Cash")
        cash_parent = (frappe.db.get_value("Account", {
            "company": target_company.name, "account_name": "Cash In Hand",
            "is_group": 1}, "name") or frappe.db.get_value("Account", {
            "company": target_company.name, "account_name": "Current Assets",
            "is_group": 1}, "name"))
        target_petty = frappe.get_doc({"doctype": "Account",
            "account_name": "HS Petty Cash " + suffix,
            "parent_account": cash_parent, "company": target_company.name,
            "account_type": "Cash", "account_currency": "NIO",
            "is_group": 0}).insert(ignore_permissions=True)

        mapping = pms_cutover_mapping.template()
        cfg = mapping["properties"][prop.name]
        cfg["company"] = target_company.name
        cfg["cost_center"] = frappe.db.get_value("Cost Center", {
            "company": target_company.name, "is_group": 0}, "name")
        cfg["temporary_opening_account"] = target_opening_temp.name
        cfg["accounts"][cash.name] = target_shift_cash
        cfg["accounts"][equity.name] = target_account(root_type="Equity")
        cfg["accounts"][receivable.name] = target_account(account_type="Receivable")
        cfg["accounts"][payable.name] = target_account(account_type="Payable")
        cfg["accounts"][guarantee_liability.name] = target_liability.name
        cfg["accounts"][inventory.name] = stock_account
        cfg["accounts"][linen_clearing.name] = target_linen_clearing.name
        cfg["accounts"][purchase_tax_account.name] = target_purchase_tax.name
        cfg["accounts"][income.name] = target_account(root_type="Income")
        cfg["accounts"][foreign_bank.name] = target_foreign_bank.name
        cfg["legacy_links"]["Mode of Payment"] = {
            source_foreign_mode: target_foreign_mode}
        cfg["accounts"][loan_liability.name] = target_loan.name
        cfg["accounts"][petty_account.name] = target_petty.name
        cfg["accounts"][petty_expense_account.name] = target_account(
            root_type="Expense")
        cfg["parties"][party.name]["customer"] = customer.name
        cfg["parties"][supplier_party.name]["supplier"] = supplier.name
        cfg["products"][product.name] = item.name
        cfg["products"][source_service.name] = lodging_item.name
        cfg["products"][experience_product.name] = experience_item.name
        cfg["warehouses"][source_warehouse.name] = target_warehouse
        cfg["warehouses"][source_laundry.name] = target_laundry.name
        cfg["target_settings"] = {
            "warehouse": target_warehouse,
            "laundry_warehouse": target_laundry.name,
            "receivable_account": cfg["accounts"][receivable.name],
            "guarantee_account": target_liability.name,
            "lodging_item": lodging_item.name,
            "day_pass_item": experience_item.name,
            "agent_commission_item": commission_item.name,
            "expense_account": target_account(root_type="Expense"),
            "petty_cash_account": target_petty.name,
            "petty_cash_overage_account": cfg["accounts"][income.name],
            "petty_cash_shortage_account": cfg["accounts"][petty_expense_account.name],
            "price_list": price_list.name,
            "tax_policy_confirmed": False}
        if frappe.db.exists("Print Format", "Standard"):
            frappe.throw("The legacy Standard print-format probe needs no real Standard format")
        frappe.db.set_value("HS Property", prop.name,
            {"invoice_print_format": "Standard", "receipt_print_format": "Standard"},
            update_modified=False)
        source_linen = next(row for row in pms_cutover.preflight()["properties"]
            if row["property"] == prop.name)
        if (len(source_linen["stock_positions"]) != 2 or
                {row["warehouse"] for row in source_linen["stock_positions"]} !=
                {source_warehouse.name, source_laundry.name} or
                source_linen["pms_linen_laundry_warehouse"] != source_laundry.name):
            frappe.throw("Cutover source did not retain linen stock in both warehouses")
        wrong_laundry = deepcopy(mapping)
        wrong_laundry["properties"][prop.name]["target_settings"][
            "laundry_warehouse"] = target_warehouse
        if not any(row["code"] == "linen_laundry_warehouse_mismatch" for row in
                pms_cutover_mapping.review(wrong_laundry)["mapping_blockers"]):
            frappe.throw("Cutover accepted the wrong destination laundry warehouse")
        wrong_operating = deepcopy(mapping)
        wrong_operating["properties"][prop.name]["target_settings"][
            "warehouse"] = target_laundry.name
        if not any(row["code"] == "linen_operating_warehouse_mismatch" for row in
                pms_cutover_mapping.review(wrong_operating)["mapping_blockers"]):
            frappe.throw("Cutover accepted the wrong operating warehouse")
        bad_receivable_setting = deepcopy(mapping)
        bad_receivable_setting["properties"][prop.name]["target_settings"][
            "receivable_account"] = "MISSING-ACCOUNT-" + suffix
        bad_receivable_review = pms_cutover_mapping.review(bad_receivable_setting)
        if (bad_receivable_review["source_and_mapping_ready"] or
                not any(row["code"] == "incompatible_target_setting" and
                        row.get("kind") == "receivable_account" for row in
                        bad_receivable_review["mapping_blockers"])):
            frappe.throw("Map review accepted a missing ERP receivable account")
        wrong_petty_account = deepcopy(mapping)
        wrong_petty_account["properties"][prop.name]["target_settings"][
            "petty_cash_account"] = target_shift_cash
        if not any(row["code"] == "petty_cash_setting_account_mismatch" for row in
                pms_cutover_mapping.review(wrong_petty_account)["mapping_blockers"]):
            frappe.throw("Cutover accepted a different petty cash opening account")
        wrong_receivable_account = deepcopy(mapping)
        wrong_receivable_account["properties"][prop.name]["target_settings"][
            "receivable_account"] = target_shift_cash
        if not any(row["code"] == "receivable_setting_account_mismatch" for row in
                pms_cutover_mapping.review(wrong_receivable_account)["mapping_blockers"]):
            frappe.throw("Cutover accepted a different receivable opening account")
        wrong_transfer_account = deepcopy(mapping)
        wrong_transfer_account["properties"][prop.name]["target_settings"][
            "cash_transfer_account"] = target_liability.name
        if not any(row["code"] == "incompatible_target_account_role" and
                row.get("kind") == "cash_transfer_account" for row in
                pms_cutover_mapping.review(wrong_transfer_account)["mapping_blockers"]):
            frappe.throw("Map review accepted a liability as the cash transfer account")
        wrong_petty_overage = deepcopy(mapping)
        wrong_petty_overage["properties"][prop.name]["target_settings"][
            "petty_cash_overage_account"] = cfg["accounts"][petty_expense_account.name]
        if not any(row["code"] == "petty_cash_overage_account_mismatch" for row in
                pms_cutover_mapping.review(wrong_petty_overage)["mapping_blockers"]):
            frappe.throw("Cutover changed the petty cash overage account")
        frappe.db.savepoint("hs_cutover_price_list_setting_probe")
        try:
            frappe.db.set_value("Price List", price_list.name, "selling", 0,
                                update_modified=False)
            bad_price_review = pms_cutover_mapping.review(mapping)
            if (bad_price_review["source_and_mapping_ready"] or
                    not any(row["code"] == "incompatible_target_price_list" for row in
                            bad_price_review["mapping_blockers"])):
                frappe.throw("Map review accepted a purchase-only ERP price list")
        finally:
            frappe.db.rollback(save_point="hs_cutover_price_list_setting_probe")
        frappe.db.savepoint("hs_cutover_target_warehouse_scope_probe")
        try:
            frappe.db.set_value("Warehouse", target_laundry.name,
                "hs_property", "ESTAB-OTHER-" + suffix,
                update_modified=False)
            scoped = pms_cutover_mapping.review(mapping)
            if not any(row["code"] == "target_warehouse_property_conflict" and
                    row.get("kind") == "laundry_warehouse" for row in
                    scoped["mapping_blockers"]):
                frappe.throw("Cutover accepted a laundry warehouse owned by another hotel")
        finally:
            frappe.db.rollback(save_point="hs_cutover_target_warehouse_scope_probe")
        frappe.db.savepoint("hs_cutover_shared_target_warehouse_probe")
        try:
            other_hotel = frappe.copy_doc(frappe.get_doc("HS Property", prop.name))
            other_hotel.name = make_autoname("ESTAB-.#####")
            other_hotel.property_name = "HS Other Rehearsal Hotel " + suffix
            other_hotel.docstatus = 0
            other_hotel.petty_cash_account = None
            other_hotel.pms_linen_operating_warehouse = None
            other_hotel.pms_linen_laundry_warehouse = None
            other_hotel.pms_linen_clearing_account = None
            other_hotel.db_insert()
            shared_target = deepcopy(mapping)
            shared_target["properties"][other_hotel.name] = {
                "company": target_company.name,
                "cost_center": cfg["cost_center"],
                "temporary_opening_account": target_opening_temp.name,
                "target_settings": {"warehouse": target_warehouse},
                "accounts": {}, "parties": {}, "products": {}, "warehouses": {}}
            shared_review = pms_cutover_mapping.review(shared_target)
            if not any(row["code"] == "warehouse_shared_between_properties" and
                    row.get("property") == other_hotel.name and
                    row.get("kind") == "warehouse" for row in
                    shared_review["mapping_blockers"]):
                frappe.throw("Cutover accepted one operating warehouse for two hotels")
        finally:
            frappe.db.rollback(save_point="hs_cutover_shared_target_warehouse_probe")
        frappe.db.savepoint("hs_cutover_target_only_warehouse_probe")
        try:
            extra_target = frappe.get_doc({"doctype": "Warehouse",
                "warehouse_name": "HS Target Only " + suffix,
                "company": target_company.name,
                "parent_warehouse": frappe.db.get_value("Warehouse", {
                    "company": target_company.name, "is_group": 1}, "name")}).insert(
                        ignore_permissions=True)
            target_only = deepcopy(mapping)
            target_only["properties"][prop.name]["target_settings"][
                "laundry_warehouse"] = extra_target.name
            if pms_cutover_rehearsal.prepare_warehouses(target_only) != 3 or \
                    frappe.db.get_value("Warehouse", extra_target.name,
                                        "hs_property") != prop.name:
                frappe.throw("A settings-only ERP warehouse was not assigned")
        finally:
            frappe.db.rollback(save_point="hs_cutover_target_only_warehouse_probe")
        frappe.db.savepoint("hs_cutover_party_type_probe")
        try:
            frappe.db.set_value("Party Type", "Customer", "account_type",
                                "Payable", update_modified=False)
            party_type_review = pms_cutover_mapping.review(mapping)
            if not any(row["code"] == "target_party_type_account_mismatch" and
                       row.get("kind") == "Customer" for row in
                       party_type_review["mapping_blockers"]):
                frappe.throw("Cutover ignored an incompatible ERPNext customer party type")
        finally:
            frappe.db.rollback(save_point="hs_cutover_party_type_probe")
        frappe.db.savepoint("hs_cutover_fiscal_year_probe")
        try:
            frappe.db.set_value("Fiscal Year", "HS Rehearsal FY " + suffix,
                "disabled", 1, update_modified=False)
            fiscal_review = pms_cutover_mapping.review(mapping)
            if not any(row["code"] == "target_fiscal_year_missing" and
                       row.get("property") == prop.name for row in
                       fiscal_review["mapping_blockers"]):
                frappe.throw("Cutover ignored a missing target fiscal year")
        finally:
            frappe.db.rollback(save_point="hs_cutover_fiscal_year_probe")
        if include_live_day_pass:
            # Exercise the complete PMS Day Pass continuation and return in
            # a disposable transaction with production validation enabled.
            from hospitality_suite import pms_cutover_activation
            previous_close = frappe.db.get_value("HS Daily Close",
                {"property": prop.name, "business_date": str(previous),
                 "status": "Closed"}, "name")
            frappe.db.set_value("HS Daily Close", previous_close, "status",
                "Reopened", update_modified=False)
            frappe.db.set_value("HS Property", prop.name, "business_date",
                str(previous), update_modified=False)
            frappe.db.set_value("HS Product", experience_product.name,
                {"sales_rate": "8", "tax_profile": tax_profile.name},
                update_modified=False)
            frappe.db.set_value("HS Property", prop.name, "day_pass_item",
                experience_product.name, update_modified=False)
            tomorrow = today + timedelta(days=1)
            request = {"customer": party.name, "people": 2,
                "starts_at": str(tomorrow) + "T09:00:00",
                "ends_at": str(tomorrow) + "T17:00:00"}
            offered = suite_api.preview(prop.name, request, "day_pass_no_room")
            issued = suite_api.execute(prop.name, "day_pass_no_room",
                "cutover-live-day-pass-" + suffix,
                {**request, "acceptance": offered["acceptance"]})
            shift = suite_api.execute(prop.name, "pms_open_shift",
                "cutover-live-pass-shift-" + suffix,
                {"opening_by_currency": {"NIO": "0"}})
            collected = suite_api.execute(prop.name, "pms_cash_movement",
                "cutover-live-pass-payment-" + suffix,
                {"kind": "Payment", "amount": "6", "method": cash_method.name,
                 "shift": shift["shift"], "receivable": issued["receivable"],
                 "reference": "DAY-PASS-CUTOVER-" + suffix,
                 "reason": "Cobro parcial del pase"})
            suite_api.execute(prop.name, "pms_close_shift",
                "cutover-live-pass-close-" + suffix,
                {"shift": shift["shift"],
                 "counted_by_currency": {"NIO": "6.00"}})
            fiscal_request = {"series": fiscal_series,
                "receivables": [issued["receivable"]]}
            fiscal_quote = suite_api.pms_invoice_quote(prop.name, fiscal_request)
            invoice = suite_api.execute(prop.name, "pms_issue_invoice",
                "cutover-live-pass-invoice-" + suffix,
                {**fiscal_request, "acceptance": fiscal_quote["acceptance"]})
            prior_credit = None
            if prior_day_pass_credit:
                credit_series = suite_api.execute(prop.name,
                    "pms_fiscal_series", "cutover-live-pass-credit-series-" + suffix,
                    {"series_code": "HIST-CREDIT-" + suffix + "-",
                     "document_type": "Credit Note", "start_number": 1,
                     "end_number": 10, "padding": 6})["series"]
                credit_request = {"invoice": invoice["document"],
                    "series": credit_series,
                    "lines": [{"receivable": issued["receivable"],
                               "amount": "4"}]}
                credit_quote = suite_api.pms_credit_quote(
                    prop.name, credit_request)
                prior_credit = suite_api.execute(prop.name,
                    "pms_issue_credit_note",
                    "cutover-live-pass-prior-credit-" + suffix,
                    {**credit_request, "acceptance": credit_quote["acceptance"],
                     "reason": "Corrección parcial anterior al corte"})
            persistent_counter_sale = persistent_counter_return = None
            if persist_source:
                counter_shift = suite_api.execute(prop.name, "pms_open_shift",
                    "persistent-counter-shift-" + suffix,
                    {"opening_by_currency": {"NIO": "0"}})["shift"]
                counter_data = {"customer": party.name,
                    "item": experience_product.name, "quantity": "1",
                    "method": cash_method.name, "shift": counter_shift,
                    "series": fiscal_series, "reference": "COUNTER-" + suffix}
                first_quote = suite_api.preview(prop.name, counter_data,
                    "pms_direct_sale")
                persistent_counter_sale = suite_api.execute(prop.name,
                    "pms_direct_sale", "persistent-counter-sale-" + suffix,
                    {**counter_data, "acceptance": first_quote["acceptance"]})
                second_quote = suite_api.preview(prop.name, counter_data,
                    "pms_direct_sale")
                second_sale = suite_api.execute(prop.name,
                    "pms_direct_sale", "persistent-counter-returned-" + suffix,
                    {**counter_data, "acceptance": second_quote["acceptance"]})
                counter_credit_series = suite_api.execute(prop.name,
                    "pms_fiscal_series", "persistent-counter-credit-series-" + suffix,
                    {"series_code": "HIST-COUNTER-CR-" + suffix + "-",
                     "document_type": "Credit Note", "start_number": 1,
                     "end_number": 10, "padding": 6})["series"]
                return_data = {"service": second_sale["service"],
                    "series": counter_credit_series, "shift": counter_shift,
                    "reference": "COUNTER-RETURN-" + suffix,
                    "reason": "Devolución previa al corte persistente"}
                return_quote = suite_api.pms_direct_sale_return_quote(
                    prop.name, return_data)
                persistent_counter_return = suite_api.execute(prop.name,
                    "pms_direct_sale_return", "persistent-counter-return-" + suffix,
                    {**return_data, "acceptance": return_quote["acceptance"]})
                suite_api.execute(prop.name, "pms_close_shift",
                    "persistent-counter-shift-close-" + suffix,
                    {"shift": counter_shift,
                     "counted_by_currency": {"NIO": "8.00"}})
                from hospitality_suite import standalone_closing
                prop.reload()
                close_snapshot = standalone_closing.build(prop)
                frappe.db.set_value("HS Daily Close", previous_close,
                    "summary", canonical(close_snapshot), update_modified=False)
            frappe.db.set_value("HS Property", prop.name, "business_date",
                str(today), update_modified=False)
            frappe.db.set_value("HS Daily Close", previous_close, "status",
                "Closed", update_modified=False)
            ready = pms_cutover.preflight()
            if not ready["ready_for_mapping"]:
                frappe.throw("Live Day Pass source remains blocked: " +
                             frappe.as_json(ready["blockers"]))
            live_mapping = deepcopy(mapping)
            live_mapping["source_sha256"] = ready["source_sha256"]
            live_review = pms_cutover_plan.review(live_mapping)
            if not live_review["cutover_inputs_consistent"]:
                frappe.throw("Live Day Pass mapping did not pass: " +
                             frappe.as_json(live_review))
            live_plan = live_review["plan"]
            live_manifest = live_review["link_manifest"]
            if persist_source:
                persistent_mapping_path = Path(frappe.get_site_path(
                    "private", "files", "cutover-day-pass-mapping.json"))
                with persistent_mapping_path.open("x", encoding="utf-8") as stream:
                    stream.write(canonical(live_mapping) + "\n")
                frappe.db.commit()
                source_committed = True
                return {"persistent_source_seeded": True,
                    "property": prop.name, "day_pass": issued["day_pass"],
                    "direct_sale": persistent_counter_sale["service"],
                    "direct_return": persistent_counter_return["service"],
                    "source_receivable": issued["receivable"],
                    "source_invoice": invoice["document"],
                    "prior_credit": prior_credit["document"] if prior_credit else None,
                    "mapping_file": persistent_mapping_path.name,
                    "source_sha256": live_plan["source_sha256"],
                    "plan_sha256": live_plan["plan_sha256"],
                    "link_sha256": live_manifest["link_sha256"]}
            frappe.local.hs_cutover_rehearsal = True
            moved = pms_cutover_activation.activate_validated(live_mapping,
                source_sha256=live_plan["source_sha256"],
                plan_sha256=live_plan["plan_sha256"],
                link_sha256=live_manifest["link_sha256"],
                migration_reference="HS-LIVE-PASS-" + suffix)
            migrated = frappe.get_doc("HS Day Pass", issued["day_pass"])
            opening = frappe.get_doc("Sales Invoice",
                migrated.erp_opening_invoice)
            expected_opening = 6 if prior_day_pass_credit else 10
            if (not moved["cutover_performed"] or
                    migrated.status != "Issued" or
                    opening.outstanding_amount != expected_opening or
                    str(opening.due_date) != str(today) or
                    "original due date: " + str(previous) not in
                        opening.remarks or
                    not migrated.erp_opening_sha256 or
                    frappe.db.get_single_value("HS Site Mode", "provider") !=
                        "ERPNext"):
                frappe.throw("Live Day Pass did not migrate its net balance")
            historical_proof = frappe.parse_json(migrated.erp_opening_snapshot)
            if (len(historical_proof["source_fiscal"]["credits"]) !=
                    (1 if prior_credit else 0) or
                    (prior_credit and
                     historical_proof["source_fiscal"]["credits"][0]["document"] !=
                        prior_credit["document"])):
                frappe.throw("The prior PMS credit was not frozen in the cutover")
            target_shift = suite_api.execute(prop.name, "open_shift",
                "cutover-live-pass-target-shift-" + suffix,
                {"currency": "NIO", "opening_amount": "100"})
            later_payment = None
            if post_cutover_day_pass_collection:
                later_request = {"kind": "Payment", "invoice": opening.name,
                    "shift": target_shift["shift"],
                    "method": cash_method.name, "amount": "3"}
                later_quote = suite_api.preview(prop.name,
                    later_request, "payment")
                later_payment = suite_api.execute(prop.name, "payment",
                    "cutover-live-pass-later-payment-" + suffix,
                    {**later_request,
                     "fx_acceptance": later_quote["acceptance"]})
                opening.reload()
                if opening.outstanding_amount != expected_opening - 3:
                    frappe.throw("Post-cutover collection did not reduce the opening")
            return_request = {"day_pass": migrated.name,
                "modified": str(migrated.modified),
                "method": cash_method.name, "shift": target_shift["shift"],
                "amount": "", "reference": "LIVE-PASS-RETURN-" + suffix,
                "reason": "Devolución tras corte"}
            reviewed_return = suite_api.erp_historical_day_pass_return_quote(
                prop.name, canonical(return_request))
            accepted_return = {**return_request,
                "amount": reviewed_return["refund_amount"],
                "acceptance": reviewed_return["acceptance"]}
            returned = suite_api.execute(prop.name,
                "erp_historical_day_pass_return",
                "cutover-live-pass-return-" + suffix, accepted_return)
            if (suite_api.execute(prop.name,
                    "erp_historical_day_pass_return",
                    "cutover-live-pass-return-" + suffix,
                    accepted_return) != returned or
                    reviewed_return["original_invoice"] !=
                        invoice["document_number"] or
                    Decimal(str(reviewed_return["credit_total"])) !=
                        (12 if prior_credit else 16) or
                    Decimal(str(reviewed_return["opening_applied"])) !=
                        expected_opening -
                            (3 if post_cutover_day_pass_collection else 0) or
                    Decimal(str(reviewed_return["refund_base"])) !=
                        (9 if post_cutover_day_pass_collection else 6) or
                    frappe.db.get_value("HS Day Pass", migrated.name,
                        "status") != "Cancelled"):
                frappe.throw("Live Day Pass return did not reconcile")
            opening.reload()
            return_credit = frappe.get_doc("Sales Invoice",
                returned["credit_note"])
            refund = frappe.get_doc("HS Payment", returned["refund"])
            refund_entry = frappe.get_doc("Payment Entry", refund.payment_entry)
            from hospitality_suite import cashier
            shift_expected = cashier.expected(
                frappe.get_doc("HS Shift", target_shift["shift"]))
            if (opening.outstanding_amount != 0 or
                    return_credit.docstatus != 1 or
                    Decimal(str(return_credit.grand_total)) !=
                        (-12 if prior_credit else -16) or
                    Decimal(str(return_credit.outstanding_amount)) != 0 or
                    refund_entry.docstatus != 1 or
                    refund_entry.references[0].reference_name !=
                        return_credit.name or
                    shift_expected["NIO"] != "94.00" or
                    frappe.db.get_value("HS Payment", returned["refund"],
                        "base_amount") !=
                        (9 if post_cutover_day_pass_collection else 6) or
                    frappe.db.get_value("HS Payment", collected["payment"],
                        "company") != target_company.name):
                frappe.throw("Live Day Pass opening or refund diverged")
            return {"live_day_pass_rehearsed": True,
                "source_payment": collected["payment"],
                "opening_invoice": opening.name,
                "credit_note": returned["credit_note"],
                "refund": returned["refund"],
                "prior_credit": prior_credit["document"] if prior_credit else None,
                "post_cutover_payment": (later_payment["payment_entry"]
                    if later_payment else None),
                "production_cutover_gate_verified": True}
        checked = pms_cutover_plan.review(mapping)
        if not checked["cutover_inputs_consistent"]:
            frappe.throw("Synthetic cutover mapping did not pass: " +
                         frappe.as_json(checked))
        frappe.db.savepoint("hs_cutover_two_hotels_probe")
        try:
            second_hotel = frappe.get_doc({"doctype": "HS Property",
                "name": make_autoname("ESTAB-.#####"),
                "property_name": "HS Second Hotel " + suffix,
                "company": source_company.name, "organization": org.name,
                "currency": "NIO", "mode": "Hotel",
                "lodging_charge_policy": "Arrival",
                "advance_policy": "Manual", "guarantee_policy": "Manual",
                "cancellation_fee_mode": "None", "no_show_fee_mode": "None",
                "time_zone": "America/Managua", "close_time": "06:00:00",
                "check_in_time": "14:00:00", "check_out_time": "12:00:00",
                "cleaning_minutes": 30, "hold_minutes": 15,
                "retention_days": 365, "checkout_quote_minutes": 5,
                "schedule_rounding_minutes": 60,
                "business_date": str(today), "docstatus": 0})
            second_hotel.db_insert()
            with operation(second_hotel):
                second_cash = frappe.get_doc({"doctype": "HS Account",
                    "company": source_company.name, "property": second_hotel.name,
                    "organization": org.name, "account_code": "B-CASH-" + suffix,
                    "account_name": "Caja segundo hotel", "root_type": "Asset",
                    "account_type": "Cash", "account_currency": "NIO",
                    "is_cash": 1, "active": 1}).insert(ignore_permissions=True)
                second_equity = frappe.get_doc({"doctype": "HS Account",
                    "company": source_company.name, "property": second_hotel.name,
                    "organization": org.name, "account_code": "B-EQ-" + suffix,
                    "account_name": "Capital segundo hotel", "root_type": "Equity",
                    "account_type": "Equity", "account_currency": "NIO",
                    "active": 1}).insert(ignore_permissions=True)
                frappe.get_doc({"doctype": "HS Journal",
                    "company": source_company.name, "property": second_hotel.name,
                    "organization": org.name, "posting_date": str(previous),
                    "business_date": str(previous), "source_doctype": "Smoke",
                    "source_name": "second-hotel-" + suffix, "purpose": "Opening",
                    "status": "Posted", "lines": [
                        {"account": second_cash.name, "debit": "7", "credit": "0",
                         "account_currency": "NIO", "exchange_rate": 1,
                         "debit_in_account_currency": "7"},
                        {"account": second_equity.name, "debit": "0", "credit": "7",
                         "account_currency": "NIO", "exchange_rate": 1,
                         "credit_in_account_currency": "7"}]}).insert(
                             ignore_permissions=True)
            with operation(second_hotel):
                frappe.get_doc({"doctype": "HS Daily Close",
                    "company": source_company.name, "property": second_hotel.name,
                    "business_date": str(previous), "revision": 1,
                    "status": "Closed", "summary": "{}",
                    "closed_at": frappe.utils.now_datetime()}).insert(
                        ignore_permissions=True)
            second_center = frappe.get_doc({"doctype": "Cost Center",
                "cost_center_name": "HS Second Hotel " + suffix,
                "company": target_company.name,
                "parent_cost_center": frappe.db.get_value("Cost Center", {
                    "company": target_company.name, "is_group": 1}, "name")}).insert(
                        ignore_permissions=True)
            second_warehouse = frappe.get_doc({"doctype": "Warehouse",
                "warehouse_name": "HS Second Hotel " + suffix,
                "company": target_company.name,
                "parent_warehouse": frappe.db.get_value("Warehouse", {
                    "company": target_company.name, "is_group": 1}, "name")}).insert(
                        ignore_permissions=True)
            two_hotels = deepcopy(mapping)
            two_hotels["source_sha256"] = pms_cutover.preflight()["source_sha256"]
            two_hotels["properties"][second_hotel.name] = {
                "company": target_company.name,
                "cost_center": second_center.name,
                "temporary_opening_account": target_opening_temp.name,
                "target_settings": {
                    "warehouse": second_warehouse.name,
                    "receivable_account": cfg["target_settings"]["receivable_account"],
                    "guarantee_account": cfg["target_settings"]["guarantee_account"],
                    "lodging_item": lodging_item.name,
                    "price_list": price_list.name},
                "legacy_links": {},
                "accounts": {second_cash.name: target_shift_cash,
                             second_equity.name: cfg["accounts"][equity.name]},
                "parties": {}, "products": {}, "warehouses": {}}
            two_review = pms_cutover_plan.review(two_hotels)
            if not two_review["cutover_inputs_consistent"]:
                frappe.throw("Two-hotel mapping failed: " +
                    frappe.as_json(two_review.get("mapping_review", {}))[:2000])
            from hospitality_suite import pms_cutover_activation
            two_result = pms_cutover_activation.rehearse_activation(two_hotels,
                source_sha256=two_review["plan"]["source_sha256"],
                plan_sha256=two_review["plan"]["plan_sha256"],
                link_sha256=two_review["link_manifest"]["link_sha256"],
                migration_reference="HS-TWO-HOTELS-" + suffix)
            by_hotel = {row["property"]: row for row in two_result["properties"]}
            if (set(by_hotel) != {prop.name, second_hotel.name} or
                    two_result["warehouses_assigned"] != 3 or
                    by_hotel[second_hotel.name]["reconciliation"]["accounts"].get(
                        target_shift_cash) != "7" or
                    by_hotel[second_hotel.name]["reconciliation"]["accounts"].get(
                        cfg["accounts"][equity.name]) != "-7" or
                    by_hotel[prop.name]["reconciliation"]["accounts"].get(
                        target_shift_cash) != "84" or
                    frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                    frappe.db.get_value("HS Property", second_hotel.name,
                        "company") != source_company.name or
                    frappe.db.get_value("Warehouse", second_warehouse.name,
                        "hs_property")):
                frappe.throw("Two-hotel cutover mixed balances or left target changes")
        finally:
            frappe.db.rollback(save_point="hs_cutover_two_hotels_probe")
        plan = checked["plan"]
        manifest = checked["link_manifest"]
        legacy_print_rewrites = {row["field"] for row in manifest["rewrites"]
            if row["doctype"] == "HS Property" and row["property"] == prop.name
            and row["source"] == "Standard" and row["target"] == ""}
        if legacy_print_rewrites != {"invoice_print_format", "receipt_print_format"}:
            frappe.throw("The legacy pseudo print formats were not cleared in the cutover manifest")
        planned_orders = plan["properties"][0]["purchase_orders"]
        if (len(planned_orders) != 1 or
                planned_orders[0]["source"] != approved_order.name or
                planned_orders[0]["remaining_gross"] != "12" or
                planned_orders[0]["recoverable_tax"] != "2" or
                planned_orders[0]["lines"][0]["quantity"] != "2"):
            frappe.throw("Approved PMS purchase order was not planned for ERPNext")
        frappe.db.savepoint("hs_partial_source_order_probe")
        try:
            historical_receipt = frappe.get_doc({
                "doctype": "HS PMS Purchase",
                "name": frappe.generate_hash(length=12),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "supplier": supplier_party.name,
                "supplier_reference": "PARTIAL-" + suffix,
                "purchase_order": approved_order.name,
                "product": product.name, "warehouse": source_warehouse.name,
                "quantity": 1, "invoice_currency": "NIO",
                "invoice_amount": "6", "recoverable_tax": "1",
                "exchange_rate": 1, "base_amount": "6",
                "base_cost": "5", "base_tax": "1",
                "payable_account": payable.name,
                "inventory_account": inventory.name,
                "tax_account": purchase_tax_account.name,
                "status": "Posted"})
            historical_receipt.db_insert()
            receipt_journal = frappe.get_doc({"doctype": "HS Journal",
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "posting_date": str(previous),
                "business_date": str(previous),
                "source_doctype": "HS PMS Purchase",
                "source_name": historical_receipt.name,
                "purpose": "Purchase", "status": "Posted", "lines": [
                    {"account": inventory.name, "debit": "5", "credit": 0,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "5"},
                    {"account": purchase_tax_account.name,
                     "debit": "1", "credit": 0,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "debit_in_account_currency": "1"},
                    {"account": payable.name, "debit": 0, "credit": "6",
                     "party": supplier_party.name,
                     "account_currency": "NIO", "exchange_rate": 1,
                     "credit_in_account_currency": "6"}]})
            with operation(prop):
                receipt_journal.insert(ignore_permissions=True)
            historical_stock = frappe.get_doc({"doctype": "HS Stock Movement",
                "name": make_autoname("MOVSTK-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name, "product": product.name,
                "warehouse": source_warehouse.name, "direction": "Receipt",
                "quantity_delta": 1, "value_delta": "5",
                "balance_quantity": 4, "balance_value": "35",
                "business_date": str(previous),
                "source_doctype": "HS PMS Purchase",
                "source_name": historical_receipt.name,
                "purpose": "Purchase", "journal": receipt_journal.name})
            historical_stock.db_insert()
            frappe.db.set_value("HS PMS Purchase", historical_receipt.name,
                {"tax_journal": receipt_journal.name,
                 "stock_movement": historical_stock.name},
                update_modified=False)
            purchase_line = frappe.get_doc({
                "doctype": "HS PMS Purchase Line",
                "name": frappe.generate_hash(length=10),
                "parent": historical_receipt.name,
                "parenttype": "HS PMS Purchase", "parentfield": "lines",
                "idx": 1, "product": product.name,
                "warehouse": source_warehouse.name,
                "order_line": approved_order.lines[0].name,
                "quantity": 1, "invoice_currency": "NIO",
                "base_currency": "NIO", "invoice_amount": "6",
                "recoverable_tax": "1", "base_amount": "6",
                "base_cost": "5", "base_tax": "1",
                "inventory_account": inventory.name,
                "stock_movement": historical_stock.name})
            purchase_line.db_insert()
            partial_source = pms_cutover.preflight()
            if not partial_source["ready_for_mapping"]:
                frappe.throw("A partially received PMS order failed preflight: " +
                             frappe.as_json(partial_source["blockers"]))
            partial_map = deepcopy(mapping)
            partial_map["source_sha256"] = partial_source["source_sha256"]
            partial_review = pms_cutover_plan.review(partial_map)
            partial_orders = partial_review["plan"]["properties"][0][
                "purchase_orders"]
            if (not partial_review["cutover_inputs_consistent"] or
                    len(partial_orders) != 1 or
                    partial_orders[0]["lines"][0]["quantity"] != "1" or
                    partial_orders[0]["remaining_gross"] != "6" or
                    partial_orders[0]["recoverable_tax"] != "1"):
                frappe.throw("The cutover repeated a received PMS order slice")
            partial_rehearsal = pms_cutover_rehearsal.run(partial_map,
                source_sha256=partial_source["source_sha256"],
                plan_sha256=partial_review["plan"]["plan_sha256"],
                link_sha256=partial_review["link_manifest"]["link_sha256"])
            if (not partial_rehearsal["rehearsal_passed"] or
                    len(partial_rehearsal["properties"][0]["purchase_orders"]) != 1):
                frappe.throw("A partially received PMS order did not transfer")
        finally:
            frappe.db.rollback(save_point="hs_partial_source_order_probe")
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The partial-order probe did not restore the source")
        frappe.db.savepoint("hs_foreign_purchase_order_probe")
        try:
            buying_rate = frappe.get_doc({"doctype": "Currency Exchange",
                "date": str(today), "from_currency": "USD",
                "to_currency": "NIO", "exchange_rate": "36.5",
                "for_buying": 1, "for_selling": 0}).insert(
                    ignore_permissions=True)
            with operation(prop):
                foreign_order = frappe.get_doc({
                    "doctype": "HS PMS Purchase Order",
                    "company": source_company.name, "property": prop.name,
                    "organization": org.name,
                    "supplier": supplier_party.name,
                    "reference": "FX-APPROVED-" + suffix,
                    "currency": "USD", "payable_account": payable.name,
                    "tax_account": purchase_tax_account.name,
                    "amount": "4", "recoverable_tax": "0.50",
                    "business_date": str(previous),
                    "requested_by": "Administrator", "status": "Pending",
                    "lines": [{"product": product.name,
                        "warehouse": source_warehouse.name,
                        "quantity": 2, "currency": "USD",
                        "amount": "4", "recoverable_tax": "0.50",
                        "inventory_account": inventory.name}]}).insert(
                            ignore_permissions=True)
            frappe.db.set_value("HS PMS Purchase Order", foreign_order.name,
                {"status": "Approved", "approved_by": "Guest",
                 "approved_at": frappe.utils.now_datetime()},
                update_modified=False)
            foreign_source = pms_cutover.preflight()
            if not foreign_source["ready_for_mapping"]:
                frappe.throw("An approved USD order failed PMS preflight: " +
                             frappe.as_json(foreign_source["blockers"]))
            foreign_map = deepcopy(mapping)
            foreign_map["source_sha256"] = foreign_source["source_sha256"]
            foreign_review = pms_cutover_plan.review(foreign_map)
            foreign_orders = foreign_review["plan"]["properties"][0][
                "purchase_orders"]
            foreign_planned = [row for row in foreign_orders
                               if row["source"] == foreign_order.name]
            if (not foreign_review["cutover_inputs_consistent"] or
                    len(foreign_planned) != 1 or
                    foreign_planned[0]["currency"] != "USD" or
                    Decimal(foreign_planned[0]["conversion_rate"]) !=
                        Decimal("36.5") or
                    foreign_planned[0]["exchange_rate_record"] !=
                        buying_rate.name or
                    foreign_planned[0]["exchange_rate_date"] != str(today)):
                frappe.throw("The USD purchase order lost its buying rate")
            from hospitality_suite import pms_cutover_activation
            previous_fx_flag = getattr(frappe.local,
                "hs_cutover_rehearsal", False)
            frappe.local.hs_cutover_rehearsal = True
            try:
                foreign_result = pms_cutover_activation.activate_validated(
                    foreign_map,
                    source_sha256=foreign_source["source_sha256"],
                    plan_sha256=foreign_review["plan"]["plan_sha256"],
                    link_sha256=foreign_review["link_manifest"]["link_sha256"],
                    migration_reference="HS-FX-ORDER-" + suffix)
                foreign_index = next(index for index, row in
                    enumerate(foreign_orders)
                    if row["source"] == foreign_order.name)
                native_foreign = frappe.get_doc("Purchase Order",
                    foreign_result["properties"][0]["purchase_orders"][
                        foreign_index])
                if (native_foreign.docstatus != 1 or
                        native_foreign.currency != "USD" or
                        Decimal(str(native_foreign.conversion_rate)) !=
                            Decimal("36.5") or
                        Decimal(str(native_foreign.grand_total)) !=
                            Decimal("4") or
                        Decimal(str(native_foreign.base_grand_total)) !=
                            Decimal("146")):
                    frappe.throw("The USD order changed amount during cutover")
                from hospitality_suite import api as suite_api
                foreign_receipt = suite_api.execute(prop.name,
                    "receive_purchase", "cutover-fx-receipt-" + suffix,
                    {"order": native_foreign.name,
                     "items": [{"order_item": native_foreign.items[0].name,
                                "quantity": "1"}],
                     "reason": "Recepción parcial USD tras el corte"})
                native_foreign_receipt = frappe.get_doc("Purchase Receipt",
                    foreign_receipt["receipt"])
                if (native_foreign_receipt.docstatus != 1 or
                        native_foreign_receipt.currency != "USD" or
                        Decimal(str(native_foreign_receipt.grand_total)) !=
                            Decimal("2") or
                        Decimal(str(native_foreign_receipt.base_grand_total)) !=
                            Decimal("73") or
                        Decimal(str(native_foreign_receipt.total_taxes_and_charges)) !=
                            Decimal("0.25")):
                    frappe.throw("The USD partial receipt lost rate or tax")
                foreign_bill = suite_api.execute(prop.name,
                    "purchase_invoice", "cutover-fx-bill-" + suffix,
                    {"receipt": native_foreign_receipt.name,
                     "bill_no": "BILL-FX-" + suffix,
                     "bill_date": str(today),
                     "reason": "Facturar recepción USD tras el corte"})
                native_foreign_bill = frappe.get_doc("Purchase Invoice",
                    foreign_bill["invoice"])
                if (native_foreign_bill.docstatus != 1 or
                        native_foreign_bill.currency != "USD" or
                        Decimal(str(native_foreign_bill.grand_total)) !=
                            Decimal("2") or
                        Decimal(str(native_foreign_bill.base_grand_total)) !=
                            Decimal("73") or
                        Decimal(str(native_foreign_bill.outstanding_amount)) !=
                            Decimal("73")):
                    frappe.throw("The USD receipt could not be billed: " +
                        frappe.as_json({"currency": native_foreign_bill.currency,
                            "grand_total": native_foreign_bill.grand_total,
                            "base_grand_total": native_foreign_bill.base_grand_total,
                            "outstanding": native_foreign_bill.outstanding_amount,
                            "conversion_rate": native_foreign_bill.conversion_rate}))
            finally:
                frappe.local.hs_cutover_rehearsal = previous_fx_flag
        finally:
            frappe.db.rollback(save_point="hs_foreign_purchase_order_probe")
            from hospitality_suite.pms_cutover_activation import _clear_cutover_metadata
            _clear_cutover_metadata()
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The USD-order probe did not restore the source")
        frappe.db.savepoint("hs_mixed_purchase_tax_probe")
        try:
            second_product = frappe.get_doc({"doctype": "HS Product",
                "name": make_autoname("PROD-.#####"),
                "company": source_company.name, "property": prop.name,
                "organization": org.name,
                "product_code": "MIX-" + suffix,
                "product_name": "Artículo exento de orden mixta",
                "product_type": "Stock",
                "inventory_account": inventory.name,
                "active": 1})
            second_product.db_insert()
            second_item = frappe.get_doc({"doctype": "Item",
                "item_code": "HS-REHEARSAL-MIX-" + suffix,
                "item_name": "Artículo exento ERP " + suffix,
                "is_stock_item": 1, "is_purchase_item": 1,
                "item_group": group.name, "stock_uom": "Nos",
                "uom": "Nos"}).insert(ignore_permissions=True)
            with operation(prop):
                mixed_order = frappe.get_doc({
                    "doctype": "HS PMS Purchase Order",
                    "company": source_company.name, "property": prop.name,
                    "organization": org.name,
                    "supplier": supplier_party.name,
                    "reference": "MIXED-TAX-" + suffix,
                    "currency": "NIO", "payable_account": payable.name,
                    "tax_account": purchase_tax_account.name,
                    "amount": "22", "recoverable_tax": "2",
                    "business_date": str(previous),
                    "requested_by": "Administrator", "status": "Pending",
                    "lines": [
                        {"product": product.name,
                         "warehouse": source_warehouse.name,
                         "quantity": 2, "currency": "NIO",
                         "amount": "12", "recoverable_tax": "2",
                         "inventory_account": inventory.name},
                        {"product": second_product.name,
                         "warehouse": source_warehouse.name,
                         "quantity": 2, "currency": "NIO",
                         "amount": "10", "recoverable_tax": "0",
                         "inventory_account": inventory.name}]}).insert(
                            ignore_permissions=True)
            frappe.db.set_value("HS PMS Purchase Order", mixed_order.name,
                {"status": "Approved", "approved_by": "Guest",
                 "approved_at": frappe.utils.now_datetime()},
                update_modified=False)
            mixed_source = pms_cutover.preflight()
            if not mixed_source["ready_for_mapping"]:
                frappe.throw("A mixed-tax PMS order failed preflight: " +
                             frappe.as_json(mixed_source["blockers"]))
            mixed_map = deepcopy(mapping)
            mixed_map["source_sha256"] = mixed_source["source_sha256"]
            mixed_map["properties"][prop.name]["products"][
                second_product.name] = second_item.name
            mixed_review = pms_cutover_plan.review(mixed_map)
            mixed_orders = mixed_review["plan"]["properties"][0][
                "purchase_orders"]
            split = [row for row in mixed_orders
                     if row["source"] == mixed_order.name]
            if (not mixed_review["cutover_inputs_consistent"] or
                    len(split) != 2 or
                    {row["source_line"] for row in split} !=
                        {line.name for line in mixed_order.lines} or
                    {(row["remaining_gross"], row["recoverable_tax"])
                     for row in split} != {("12", "2"), ("10", "0")}):
                frappe.throw("Mixed line taxes were not split in the plan")
            from hospitality_suite import pms_cutover_activation
            previous_mixed_flag = getattr(frappe.local,
                "hs_cutover_rehearsal", False)
            frappe.local.hs_cutover_rehearsal = True
            try:
                mixed_result = pms_cutover_activation.activate_validated(
                    mixed_map,
                    source_sha256=mixed_source["source_sha256"],
                    plan_sha256=mixed_review["plan"]["plan_sha256"],
                    link_sha256=mixed_review["link_manifest"]["link_sha256"],
                    migration_reference="HS-MIXED-TAX-" + suffix)
                posted = mixed_result["properties"][0]["purchase_orders"]
                native_split = {row["source_line"]: frappe.get_doc(
                    "Purchase Order", posted[index])
                    for index, row in enumerate(mixed_orders)
                    if row["source"] == mixed_order.name}
                traced = [row for row in mixed_result["properties"][0][
                    "source_documents"] if row.get("source_name") ==
                    mixed_order.name and row.get("target_doctype") ==
                    "Purchase Order"]
                if (len(native_split) != 2 or len(traced) != 2 or
                        {row["source_line"] for row in traced} !=
                            set(native_split)):
                    frappe.throw("The split order lost its source-line trace")
                from hospitality_suite import api as suite_api
                for source_line, gross, tax, partial_gross, partial_tax in (
                        (mixed_order.lines[0].name, "12", "2", "6", "1"),
                        (mixed_order.lines[1].name, "10", "0", "5", "0")):
                    native_order = native_split[source_line]
                    if (native_order.docstatus != 1 or
                            len(native_order.items) != 1 or
                            Decimal(str(native_order.grand_total)) !=
                                Decimal(gross) or
                            Decimal(str(native_order.total_taxes_and_charges)) !=
                                Decimal(tax)):
                        frappe.throw("A split purchase order changed its tax")
                    received = suite_api.execute(prop.name,
                        "receive_purchase",
                        "cutover-mixed-receipt-" + source_line,
                        {"order": native_order.name,
                         "items": [{"order_item": native_order.items[0].name,
                                    "quantity": "1"}],
                         "reason": "Recepción parcial de orden mixta"})
                    receipt = frappe.get_doc("Purchase Receipt",
                        received["receipt"])
                    if (receipt.docstatus != 1 or
                            Decimal(str(receipt.grand_total)) !=
                                Decimal(partial_gross) or
                            Decimal(str(receipt.total_taxes_and_charges)) !=
                                Decimal(partial_tax)):
                        frappe.throw("A partial mixed-tax receipt changed tax")
                    billed = suite_api.execute(prop.name,
                        "purchase_invoice",
                        "cutover-mixed-invoice-" + source_line,
                        {"receipt": receipt.name,
                         "bill_no": "MIX-BILL-" + source_line,
                         "bill_date": str(today),
                         "reason": "Facturar recepción mixta"})
                    invoice = frappe.get_doc("Purchase Invoice",
                        billed["invoice"])
                    if (invoice.docstatus != 1 or
                            Decimal(str(invoice.grand_total)) !=
                                Decimal(partial_gross) or
                            Decimal(str(invoice.total_taxes_and_charges)) !=
                                Decimal(partial_tax)):
                        frappe.throw("A mixed-tax receipt could not be billed")
            finally:
                frappe.local.hs_cutover_rehearsal = previous_mixed_flag
        finally:
            frappe.db.rollback(save_point="hs_mixed_purchase_tax_probe")
            from hospitality_suite.pms_cutover_activation import _clear_cutover_metadata
            _clear_cutover_metadata()
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The mixed-tax probe did not restore the source")
        frappe.db.savepoint("hs_direct_experience_cutover_probe")
        try:
            with operation(prop):
                direct_tax_account = frappe.get_doc({
                    "doctype": "HS Account", "company": source_company.name,
                    "property": prop.name, "organization": org.name,
                    "account_code": "EXP-TAX-" + suffix,
                    "account_name": "Impuesto de experiencia directa",
                    "root_type": "Liability", "account_type": "Tax",
                    "account_currency": "NIO", "active": 1}).insert(
                        ignore_permissions=True)
                direct_tax_profile = frappe.get_doc({
                    "doctype": "HS PMS Tax Profile",
                    "company": source_company.name, "property": prop.name,
                    "organization": org.name,
                    "label": "Experiencia gravada " + suffix,
                    "treatment": "Taxable", "rate": "12.5",
                    "included_in_price": 0,
                    "liability_account": direct_tax_account.name,
                    "active": 1}).insert(ignore_permissions=True)
                experience_product.sales_rate = 8
                experience_product.tax_profile = direct_tax_profile.name
                experience_product.save()
            # The ERP smoke site's target Link metadata is already installed;
            # insert the PMS source snapshot directly, as the other cutover
            # fixtures do, then exercise the live ERP delivery through API.
            source_direct = frappe.get_doc({
                "doctype": "HS Experience Order",
                "name": frappe.generate_hash(length=10),
                "company": source_company.name, "property": prop.name,
                "experience": experience.name,
                "customer": party.name,
                "pms_product": experience_product.name,
                "quantity": 1, "participants": 1,
                "unit_rate": "8", "amount": "8",
                "currency": "NIO", "status": "Confirmed",
                "scheduled_at": arrival})
            source_direct.db_insert()
            from hospitality_suite import api as suite_api
            incomplete_source = pms_cutover.preflight()
            if not any(row["code"] == "pending_direct_experience_incomplete" and
                       row["source"] == source_direct.name for row in
                       incomplete_source["blockers"]):
                frappe.throw("A legacy direct order did not block cutover")
            historical_data = {"order": source_direct.name,
                "modified": str(source_direct.modified),
                "tax_profile": direct_tax_profile.name,
                "income_account": income.name,
                "evidence": "Original direct sale " + suffix}
            historical_quote = suite_api.preview(prop.name, historical_data,
                "pms_legacy_direct_experience_review")
            if (historical_quote["net_amount"] != "8.00" or
                    historical_quote["tax_amount"] != "1.00" or
                    historical_quote["total_amount"] != "9.00"):
                frappe.throw("The legacy review changed accepted tax")
            frozen_direct = suite_api.execute(prop.name,
                "pms_legacy_direct_experience_review",
                "cutover-legacy-direct-" + suffix,
                {**historical_data,
                 "acceptance": historical_quote["acceptance"]})
            source_direct.reload()
            if (frozen_direct["order"] != source_direct.name or
                    source_direct.accepted_tax_profile != direct_tax_profile.name):
                frappe.throw("The reviewed direct order lost its tax profile")
            if (Decimal(str(source_direct.accepted_net)) != Decimal("8") or
                    Decimal(str(source_direct.accepted_tax)) != Decimal("1") or
                    Decimal(str(source_direct.accepted_total)) != Decimal("9")):
                frappe.throw("The direct PMS experience did not freeze tax")
            target_direct_tax = frappe.get_doc({"doctype": "Account",
                "account_name": "HS Experience Tax " + suffix,
                "parent_account": frappe.db.get_value("Account", {
                    "company": target_company.name,
                    "account_name": "Current Liabilities",
                    "is_group": 1}, "name"),
                "company": target_company.name,
                "account_currency": "NIO", "is_group": 0}).insert(
                    ignore_permissions=True)
            direct_source = pms_cutover.preflight()
            if not direct_source["ready_for_mapping"]:
                frappe.throw("A direct PMS experience failed preflight: " +
                             frappe.as_json(direct_source["blockers"]))
            direct_map = deepcopy(mapping)
            direct_map["source_sha256"] = direct_source["source_sha256"]
            direct_map["properties"][prop.name]["accounts"][
                direct_tax_account.name] = target_direct_tax.name
            direct_review = pms_cutover_plan.review(direct_map)
            expected_rewrite = {"doctype": "HS Experience Order",
                "name": source_direct.name,
                "target_item": experience_item.name}
            if (not direct_review["cutover_inputs_consistent"] or
                    not any(all(row.get(key) == value for key, value in
                                expected_rewrite.items()) for row in
                            direct_review["link_manifest"]["experience_rewrites"])):
                frappe.throw("The direct experience was not mapped for cutover: " +
                             frappe.as_json(direct_review["link_manifest"]["blockers"]))
            from hospitality_suite import pms_cutover_activation
            previous_direct_flag = getattr(frappe.local,
                "hs_cutover_rehearsal", False)
            frappe.local.hs_cutover_rehearsal = True
            try:
                pms_cutover_activation.activate_validated(direct_map,
                    source_sha256=direct_source["source_sha256"],
                    plan_sha256=direct_review["plan"]["plan_sha256"],
                    link_sha256=direct_review["link_manifest"]["link_sha256"],
                    migration_reference="HS-DIRECT-EXP-" + suffix)
                migrated_direct = frappe.get_doc("HS Experience Order",
                    source_direct.name)
                if (migrated_direct.customer != customer.name or
                        migrated_direct.item != experience_item.name or
                        migrated_direct.income_account !=
                            direct_map["properties"][prop.name]["accounts"][income.name] or
                        migrated_direct.tax_account != target_direct_tax.name):
                    frappe.throw("The direct experience lost its mapped links")
                delivery_quote = suite_api.preview(prop.name,
                    {"order": migrated_direct.name},
                    "pms_direct_experience_delivery")
                if (Decimal(delivery_quote["net_amount"]) != Decimal("8") or
                        Decimal(delivery_quote["tax_amount"]) != Decimal("1") or
                        Decimal(delivery_quote["total_amount"]) != Decimal("9")):
                    frappe.throw("ERPNext changed the direct experience tax")
                delivery_data = {"order": migrated_direct.name,
                    "modified": str(migrated_direct.modified),
                    "status": "Delivered",
                    "acceptance": delivery_quote["acceptance"]}
                delivered_direct = suite_api.execute(prop.name,
                    "pms_direct_experience_status",
                    "cutover-direct-deliver-" + suffix, delivery_data)
                if suite_api.execute(prop.name,
                        "pms_direct_experience_status",
                        "cutover-direct-deliver-" + suffix,
                        delivery_data) != delivered_direct:
                    frappe.throw("The direct delivery was not idempotent")
                native_direct = frappe.get_doc("Sales Invoice",
                    delivered_direct["sales_invoice"])
                if (native_direct.docstatus != 1 or
                        native_direct.hs_property != prop.name or
                        native_direct.customer != customer.name or
                        native_direct.hs_folio or native_direct.hs_stay or
                        native_direct.hs_booking or
                        Decimal(str(native_direct.net_total)) != Decimal("8") or
                        Decimal(str(native_direct.total_taxes_and_charges)) !=
                            Decimal("1") or
                        Decimal(str(native_direct.grand_total)) != Decimal("9") or
                        Decimal(str(native_direct.outstanding_amount)) !=
                            Decimal("9") or
                        frappe.db.get_value("HS Experience Order",
                            source_direct.name, "sales_invoice") !=
                            native_direct.name):
                    frappe.throw("The migrated direct delivery did not post its invoice")
                frappe.db.savepoint("hs_direct_foreign_collection_probe")
                try:
                    frappe.get_doc({"doctype": "Currency Exchange",
                        "date": str(today), "from_currency": "USD",
                        "to_currency": "NIO", "exchange_rate": "36.5",
                        "for_buying": 0, "for_selling": 1}).insert(
                            ignore_permissions=True)
                    foreign_method = frappe.get_doc("HS Payment Method",
                        source_foreign_method.name)
                    if (foreign_method.company != target_company.name or
                            foreign_method.account != target_foreign_bank.name or
                            foreign_method.mode_of_payment != target_foreign_mode or
                            foreign_method.currency != "USD" or
                            not any(row.currency == "USD" for row in
                                frappe.get_doc("HS Property", prop.name).accepted_currencies)):
                        frappe.throw("The PMS USD method or accepted currency did not survive cutover")
                    foreign_shift = suite_api.execute(prop.name, "open_shift",
                        "cutover-direct-foreign-shift-" + suffix,
                        {"currency": "USD", "opening_amount": "0"})
                    foreign_request = {"kind": "Payment",
                        "invoice": native_direct.name,
                        "shift": foreign_shift["shift"],
                        "method": foreign_method.name, "amount": "0.20",
                        "reference": "BANK-" + suffix}
                    foreign_quote = suite_api.preview(prop.name,
                        foreign_request, "payment")
                    if (Decimal(foreign_quote["exchange_rate"]) != Decimal("36.5") or
                            Decimal(foreign_quote["property_amount"]) !=
                                Decimal("7.30")):
                        frappe.throw("The USD direct collection changed conversion")
                    foreign_paid = suite_api.execute(prop.name, "payment",
                        "cutover-direct-foreign-payment-" + suffix,
                        {**foreign_request,
                         "fx_acceptance": foreign_quote["acceptance"]})
                    foreign_entry = frappe.get_doc("Payment Entry",
                        foreign_paid["payment_entry"])
                    bank_gl = frappe.db.get_value("GL Entry", {
                        "voucher_type": "Payment Entry",
                        "voucher_no": foreign_entry.name,
                        "account": target_foreign_bank.name},
                        ["debit", "debit_in_account_currency"], as_dict=True)
                    if (foreign_entry.docstatus != 1 or
                            foreign_entry.paid_to != target_foreign_bank.name or
                            Decimal(str(foreign_entry.paid_amount)) !=
                                Decimal("7.30") or
                            Decimal(str(foreign_entry.received_amount)) !=
                                Decimal("0.20") or
                            len(foreign_entry.references) != 1 or
                            foreign_entry.references[0].reference_name !=
                                native_direct.name or
                            Decimal(str(foreign_entry.references[0].allocated_amount)) !=
                                Decimal("7.30") or
                            Decimal(str(frappe.db.get_value("Sales Invoice",
                                native_direct.name, "outstanding_amount"))) !=
                                Decimal("1.70") or
                            not bank_gl or
                            Decimal(str(bank_gl.debit)) != Decimal("7.30") or
                            Decimal(str(bank_gl.debit_in_account_currency)) !=
                                Decimal("0.20")):
                        frappe.throw("The USD direct collection lost invoice or bank value")
                    foreign_credit_data = {"invoice": native_direct.name,
                        "reason": "Devolución de venta directa en USD"}
                    foreign_credit_quote = suite_api.preview(prop.name,
                        foreign_credit_data, "credit_note")
                    foreign_credit = suite_api.execute(prop.name,
                        "credit_note", "cutover-direct-foreign-credit-" + suffix,
                        {**foreign_credit_data,
                         "acceptance": foreign_credit_quote["acceptance"]})
                    foreign_credit_name = foreign_credit["credit_note"]
                    original_due = Decimal(str(frappe.db.get_value(
                        "Sales Invoice", native_direct.name,
                        "outstanding_amount")))
                    credit_due = Decimal(str(frappe.db.get_value(
                        "Sales Invoice", foreign_credit_name,
                        "outstanding_amount")))
                    if original_due != 0 or credit_due != Decimal("-7.30"):
                        frappe.throw("The USD direct credit did not settle the unpaid NIO portion: " +
                                     str((original_due, credit_due)))
                    foreign_refund_data = {"kind": "Refund",
                        "source_payment": foreign_paid["payment"],
                        "credit_note": foreign_credit_name,
                        "shift": foreign_shift["shift"],
                        "method": foreign_method.name, "amount": "0.20",
                        "reference": "BANK-REFUND-" + suffix,
                        "reason": "Devolución de venta directa en USD"}
                    foreign_refund_quote = suite_api.preview(prop.name,
                        foreign_refund_data, "payment")
                    foreign_refund = suite_api.execute(prop.name, "payment",
                        "cutover-direct-foreign-refund-" + suffix,
                        {**foreign_refund_data,
                         "fx_acceptance": foreign_refund_quote["acceptance"]})
                    if (Decimal(str(frappe.db.get_value("Sales Invoice",
                            foreign_credit_name, "outstanding_amount"))) != 0 or
                            frappe.db.get_value("HS Payment",
                                foreign_refund["payment"], "source_payment") !=
                                foreign_paid["payment"]):
                        frappe.throw("The USD direct refund did not settle its credit")
                    foreign_shift_doc = frappe.get_doc("HS Shift",
                        foreign_shift["shift"])
                    if (suite_api.execute(prop.name, "close_shift",
                            "cutover-direct-foreign-close-" + suffix,
                            {"shift": foreign_shift_doc.name,
                             "modified": str(foreign_shift_doc.modified),
                             "denominations": {}})["status"] != "Closed"):
                        frappe.throw("The USD bank collection changed cash count")
                finally:
                    frappe.db.rollback(
                        save_point="hs_direct_foreign_collection_probe")
                direct_shift = suite_api.execute(prop.name, "open_shift",
                    "cutover-direct-shift-" + suffix,
                    {"currency": "NIO", "opening_amount": "0"})
                direct_payment_data = {"kind": "Payment",
                    "invoice": native_direct.name, "shift": direct_shift["shift"],
                    "method": cash_method.name, "amount": "9"}
                direct_payment_quote = suite_api.preview(prop.name,
                    direct_payment_data, "payment")
                direct_payment = suite_api.execute(prop.name, "payment",
                    "cutover-direct-payment-" + suffix,
                    {**direct_payment_data,
                     "fx_acceptance": direct_payment_quote["acceptance"]})
                if suite_api.execute(prop.name, "payment",
                        "cutover-direct-payment-" + suffix,
                        {**direct_payment_data,
                         "fx_acceptance": direct_payment_quote["acceptance"]}) != direct_payment:
                    frappe.throw("Retrying a direct invoice payment duplicated it")
                direct_entry = frappe.get_doc("Payment Entry",
                    direct_payment["payment_entry"])
                if (direct_entry.docstatus != 1 or
                        direct_entry.party != customer.name or
                        direct_entry.hs_property != prop.name or
                        len(direct_entry.references) != 1 or
                        direct_entry.references[0].reference_name != native_direct.name or
                        Decimal(str(direct_entry.references[0].allocated_amount)) != Decimal("9") or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            native_direct.name, "outstanding_amount"))) != 0 or
                        frappe.db.get_value("HS Payment", direct_payment["payment"],
                            "sales_invoice") != native_direct.name):
                    frappe.throw("The direct invoice was not collected through Suite")
                direct_snapshot = suite_api.erp_customer_credits_snapshot(prop.name)
                direct_invoice_view = suite_api.erp_direct_credit_search(
                    prop.name, "invoices", native_direct.name, page_length=1)
                if (not any(row["name"] == native_direct.name for row in
                        direct_invoice_view["rows"]) or
                        not any(row["name"] == direct_shift["shift"] and
                                Decimal(row["expected"]["NIO"]) == Decimal("9")
                                for row in direct_snapshot["shifts"])):
                    frappe.throw("The direct payment is missing from the React view")
                direct_credit_data = {"invoice": native_direct.name,
                    "reason": "Devolución de experiencia directa de prueba"}
                direct_credit_quote = suite_api.preview(prop.name,
                    direct_credit_data, "credit_note")
                direct_credit = suite_api.execute(prop.name, "credit_note",
                    "cutover-direct-credit-" + suffix,
                    {**direct_credit_data,
                     "acceptance": direct_credit_quote["acceptance"]})
                direct_credit_doc = frappe.get_doc("Sales Invoice",
                    direct_credit["credit_note"])
                if (direct_credit_doc.docstatus != 1 or
                        direct_credit_doc.return_against != native_direct.name or
                        Decimal(str(direct_credit_doc.outstanding_amount)) !=
                            Decimal("-9")):
                    frappe.throw("The direct invoice credit was not available for refund")
                direct_note_view = suite_api.erp_direct_credit_search(
                    prop.name, "notes", direct_credit_doc.name, page_length=1)
                direct_source_view = suite_api.erp_direct_credit_search(
                    prop.name, "payments", direct_payment["payment"],
                    direct_credit_doc.name, page_length=1)
                if (not any(row["name"] == direct_credit_doc.name and
                            row["invoice"] == native_direct.name and
                            Decimal(row["available"]) == Decimal("9")
                            for row in direct_note_view["rows"]) or
                        not any(row["name"] == direct_payment["payment"] and
                                row["invoice"] == native_direct.name
                                for row in direct_source_view["rows"])):
                    frappe.throw("The direct credit is missing from the React view")
                direct_refund_data = {"kind": "Refund",
                    "source_payment": direct_payment["payment"],
                    "credit_note": direct_credit_doc.name,
                    "shift": direct_shift["shift"], "method": cash_method.name,
                    "amount": "9", "reason": "Devolución de experiencia directa"}
                direct_refund_quote = suite_api.preview(prop.name,
                    direct_refund_data, "payment")
                direct_refund = suite_api.execute(prop.name, "payment",
                    "cutover-direct-refund-" + suffix,
                    {**direct_refund_data,
                     "fx_acceptance": direct_refund_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-direct-refund-" + suffix,
                        {**direct_refund_data,
                         "fx_acceptance": direct_refund_quote["acceptance"]}) !=
                            direct_refund or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            direct_credit_doc.name, "outstanding_amount"))) != 0 or
                        frappe.db.get_value("HS Payment",
                            direct_refund["payment"], "source_payment") !=
                            direct_payment["payment"] or
                        any(row["name"] == direct_credit_doc.name for row in
                            suite_api.erp_direct_credit_search(
                                prop.name, "notes", direct_credit_doc.name,
                                page_length=1)["rows"])):
                    frappe.throw("The direct invoice refund was not reconciled")
                direct_shift_doc = frappe.get_doc("HS Shift",
                    direct_shift["shift"])
                if not any(row["name"] == direct_shift_doc.name and
                           Decimal(row["expected"]["NIO"]) == 0 for row in
                           suite_api.erp_customer_credits_snapshot(prop.name)["shifts"]):
                    frappe.throw("The direct refund did not restore the cash count")
                closed_direct_shift = suite_api.execute(prop.name, "close_shift",
                    "cutover-direct-close-" + suffix,
                    {"shift": direct_shift_doc.name,
                     "modified": str(direct_shift_doc.modified),
                     "denominations": {}})
                if closed_direct_shift["status"] != "Closed":
                    frappe.throw("The refunded direct shift did not close at zero")
            finally:
                frappe.local.hs_cutover_rehearsal = previous_direct_flag
        finally:
            frappe.db.rollback(save_point="hs_direct_experience_cutover_probe")
            from hospitality_suite.pms_cutover_activation import _clear_cutover_metadata

            _clear_cutover_metadata()
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The direct-experience probe did not restore the source")
        frappe.db.savepoint("hs_counter_sale_cutover_probe")
        try:
            with operation(prop):
                experience_product.reload()
                experience_product.sales_rate = 8
                experience_product.tax_profile = tax_profile.name
                experience_product.save()
                product.reload()
                product.sales_rate = 15
                product.income_account = income.name
                product.expense_account = petty_expense_account.name
                product.tax_profile = tax_profile.name
                product.save()
                frappe.get_doc({"doctype": "HS Exchange Rate",
                    "company": source_company.name, "property": prop.name,
                    "organization": org.name, "from_currency": "USD",
                    "to_currency": "NIO", "rate": "36.5",
                    "effective_at": str(today) + " 00:00:00",
                    "source": "Ensayo de corte"}).insert(ignore_permissions=True)
            counter_shift = suite_api.execute(prop.name, "pms_open_shift",
                "cutover-counter-shift-" + suffix,
                {"opening_by_currency": {"NIO": "0"}})["shift"]
            counter_data = {"customer": party.name,
                "item": experience_product.name, "quantity": "1",
                "method": cash_method.name, "shift": counter_shift,
                "series": fiscal_series, "reference": "COUNTER-" + suffix}
            counter_quote = suite_api.preview(prop.name, counter_data,
                "pms_direct_sale")
            counter_sale = suite_api.execute(prop.name, "pms_direct_sale",
                "cutover-counter-sale-" + suffix,
                {**counter_data, "acceptance": counter_quote["acceptance"]})
            if (counter_quote["total"] != "8.00" or
                    counter_sale["invoice"] != frappe.db.get_value(
                        "HS Service Request", counter_sale["service"],
                        "pms_fiscal_invoice")):
                frappe.throw("The PMS counter sale lost its numbered invoice")
            second_quote = suite_api.preview(prop.name, counter_data,
                "pms_direct_sale")
            second_sale = suite_api.execute(prop.name, "pms_direct_sale",
                "cutover-counter-returned-sale-" + suffix,
                {**counter_data, "acceptance": second_quote["acceptance"]})
            stock_data = {**counter_data, "item": product.name,
                "warehouse": source_warehouse.name,
                "method": source_foreign_method.name, "shift": None,
                "reference": "COUNTER-STOCK-" + suffix}
            stock_quote = suite_api.preview(prop.name, stock_data,
                "pms_direct_sale")
            stock_sale = suite_api.execute(prop.name, "pms_direct_sale",
                "cutover-counter-stock-sale-" + suffix,
                {**stock_data, "acceptance": stock_quote["acceptance"]})
            counter_credit_series = suite_api.execute(prop.name,
                "pms_fiscal_series", "cutover-counter-credit-series-" + suffix,
                {"series_code": "COUNTER-CR-" + suffix + "-",
                 "document_type": "Credit Note", "start_number": 1,
                 "end_number": 10, "padding": 6})["series"]
            counter_return_data = {"service": second_sale["service"],
                "series": counter_credit_series, "shift": counter_shift,
                "reference": "COUNTER-RETURN-" + suffix,
                "reason": "Devolución antes del corte"}
            counter_return_quote = suite_api.pms_direct_sale_return_quote(
                prop.name, counter_return_data)
            counter_return = suite_api.execute(prop.name,
                "pms_direct_sale_return", "cutover-counter-return-" + suffix,
                {**counter_return_data,
                 "acceptance": counter_return_quote["acceptance"]})
            suite_api.execute(prop.name, "pms_close_shift",
                "cutover-counter-shift-close-" + suffix,
                {"shift": counter_shift,
                 "counted_by_currency": {"NIO": "8.00"}})
            from hospitality_suite import standalone_closing
            counter_close = standalone_closing.build(prop)
            with operation(prop):
                frappe.get_doc({"doctype": "HS Daily Close",
                    "company": source_company.name, "property": prop.name,
                    "business_date": str(today), "revision": 1,
                    "status": "Closed", "summary": canonical(counter_close),
                    "closed_at": frappe.utils.now_datetime()}).insert(
                        ignore_permissions=True)
            from hospitality_suite.standalone_accounting import post
            try:
                with operation(prop):
                    post(prop, source_doctype="Smoke", source_name=suffix,
                        purpose="Closed Day Probe", lines=[
                            {"account": cash.name, "debit": "1", "credit": "0"},
                            {"account": equity.name, "debit": "0", "credit": "1"}])
            except frappe.ValidationError as exc:
                if "fecha operativa está cerrada" not in str(exc):
                    raise
            else:
                frappe.throw("A closed PMS day accepted another journal")
            frappe.db.set_value("HS Property", prop.name, "business_date",
                str(today + timedelta(days=1)), update_modified=False)
            prop.reload()
            counter_source = pms_cutover.preflight()
            if not counter_source["ready_for_mapping"]:
                frappe.throw("The historical counter sale blocked cutover: " +
                    frappe.as_json(counter_source["blockers"]))
            counter_map = deepcopy(mapping)
            counter_map["source_sha256"] = counter_source["source_sha256"]
            counter_review = pms_cutover_plan.review(counter_map)
            counter_links = counter_review["link_manifest"]
            continuations = counter_review["plan"]["properties"][0][
                "continuing_direct_sales"]
            continuation_by_sale = {row["source"]: row for row in continuations}
            if (set(continuation_by_sale) != {
                    counter_sale["service"], stock_sale["service"]} or
                    Decimal(continuation_by_sale[counter_sale["service"]][
                        "total_amount"]) != 8 or
                    continuation_by_sale[counter_sale["service"]]["stock"] is not None or
                    Decimal(continuation_by_sale[stock_sale["service"]][
                        "total_amount"]) != 15 or
                    Decimal(continuation_by_sale[stock_sale["service"]]["stock"][
                        "value"]) != 10):
                frappe.throw("The delivered PMS counter sale has no frozen return proof")
            expected_counter_links = {
                ("customer", party.name, customer.name),
                ("item", experience_product.name, experience_item.name),
                ("item", product.name, item.name)}
            found_counter_links = {(row["field"], row["source"], row["target"])
                for row in counter_links["rewrites"]
                if row["doctype"] == "HS Service Request"}
            if (not counter_review["cutover_inputs_consistent"] or
                    not expected_counter_links <= found_counter_links or
                    any(row["doctype"] == "HS Service Request" and
                        row["field"] in ("sales_invoice", "credit_note") and
                        row["source"] == counter_sale["invoice"]
                        for row in counter_links["rewrites"])):
                frappe.throw("The PMS counter sale did not map cleanly: " +
                    frappe.as_json(counter_links["blockers"]))
            from hospitality_suite import pms_cutover_activation
            previous_counter_flag = getattr(frappe.local,
                "hs_cutover_rehearsal", False)
            frappe.local.hs_cutover_rehearsal = True
            try:
                pms_cutover_activation.activate_validated(counter_map,
                    source_sha256=counter_source["source_sha256"],
                    plan_sha256=counter_review["plan"]["plan_sha256"],
                    link_sha256=counter_links["link_sha256"],
                    migration_reference="HS-COUNTER-SALE-" + suffix)
                historical_sale = frappe.get_doc("HS Service Request",
                    counter_sale["service"])
                continuation = frappe.parse_json(
                    historical_sale.erp_cutover_snapshot)
                archive = suite_api.pms_fiscal_archive(prop.name,
                    search=counter_sale["document_number"])
                returned_sale = frappe.get_doc("HS Service Request",
                    second_sale["service"])
                credit_archive = suite_api.pms_fiscal_archive(prop.name,
                    search=counter_return["document_number"])
                if (historical_sale.customer != customer.name or
                        continuation.get("source") != historical_sale.name or
                        continuation.get("source_invoice") !=
                            counter_sale["invoice"] or
                        sha256(historical_sale.erp_cutover_snapshot.encode()).hexdigest()
                            != historical_sale.erp_cutover_sha256 or
                        historical_sale.item != experience_item.name or
                        historical_sale.pms_party != party.name or
                        historical_sale.pms_product != experience_product.name or
                        historical_sale.pms_fiscal_invoice != counter_sale["invoice"] or
                        historical_sale.sales_invoice or
                        not any(row.name == counter_sale["invoice"] for row in
                            archive["documents"]) or
                        returned_sale.status != "Returned" or
                        returned_sale.customer != customer.name or
                        returned_sale.item != experience_item.name or
                        returned_sale.pms_party != party.name or
                        returned_sale.pms_product != experience_product.name or
                        returned_sale.pms_fiscal_invoice != second_sale["invoice"] or
                        returned_sale.pms_fiscal_credit != counter_return["credit_note"] or
                        returned_sale.erp_cutover_snapshot or
                        returned_sale.sales_invoice or returned_sale.credit_note or
                        not any(row.name == counter_return["credit_note"] for row in
                            credit_archive["documents"])):
                    frappe.throw("The cutover changed the historical counter sale")
                historical_sale.notes = "Consulta histórica tras corte"
                with operation(frappe.get_doc("HS Property", prop.name)):
                    historical_sale.save()
                if counter_sale["document_number"] not in frappe.get_print(
                        "HS PMS Fiscal Document", counter_sale["invoice"],
                        print_format="HS Documento fiscal PMS"):
                    frappe.throw("The PMS counter invoice no longer prints")
                available_returns = suite_api.pms_direct_sale_history(
                    prop.name, returnable=1)
                if {row["name"] for row in available_returns["rows"]} != {
                        counter_sale["service"], stock_sale["service"]}:
                    frappe.throw("The migrated counter sales are not available to return")
                historical_sale.reload()
                refund_shift = suite_api.execute(prop.name, "open_shift",
                    "historical-counter-refund-shift-" + suffix,
                    {"currency": prop.currency, "opening_amount": "100"})
                historical_request = {"service": historical_sale.name,
                    "modified": str(historical_sale.modified),
                    "method": cash_method.name,
                    "shift": refund_shift["shift"],
                    "reference": "HIST-COUNTER-RETURN-" + suffix,
                    "reason": "Devolución de venta anterior al corte"}
                historical_quote = suite_api.erp_historical_direct_sale_return_quote(
                    prop.name, canonical(historical_request))
                historical_key = "historical-counter-return-" + suffix
                historical_return = suite_api.execute(prop.name,
                    "erp_historical_direct_sale_return", historical_key,
                    {**historical_request,
                     "acceptance": historical_quote["acceptance"]})
                if (suite_api.execute(prop.name,
                        "erp_historical_direct_sale_return", historical_key,
                        {**historical_request,
                         "acceptance": historical_quote["acceptance"]}) !=
                            historical_return):
                    frappe.throw("The historical counter return retried twice")
                historical_sale.reload()
                native_credit = frappe.get_doc("Sales Invoice",
                    historical_return["credit_note"])
                native_refund = frappe.get_doc("HS Payment",
                    historical_return["refund"])
                native_payment = frappe.get_doc("Payment Entry",
                    native_refund.payment_entry)
                if (historical_sale.status != "Returned" or
                        historical_sale.credit_note != native_credit.name or
                        historical_sale.erp_return_refund != native_refund.name or
                        historical_sale.pms_fiscal_invoice != counter_sale["invoice"] or
                        historical_sale.pms_fiscal_credit or
                        native_credit.docstatus != 1 or
                        Decimal(str(native_credit.grand_total)) != -8 or
                        native_refund.source_payment != counter_sale["payment"] or
                        native_payment.docstatus != 1 or
                        native_payment.references[0].reference_name !=
                            native_credit.name):
                    frappe.throw("The historical counter return did not reconcile")
                stock_service = frappe.get_doc("HS Service Request",
                    stock_sale["service"])
                stock_proof = frappe.parse_json(stock_service.erp_cutover_snapshot)
                stock_before = Decimal(str(frappe.db.get_value("Bin", {
                    "warehouse": target_warehouse, "item_code": item.name},
                    "actual_qty") or 0))
                if (stock_service.status != "Delivered" or
                        stock_service.stock_entry !=
                            stock_proof["stock"]["source_movement"] or
                        stock_service.sales_invoice or
                        Decimal(stock_proof["stock"]["value"]) != 10):
                    frappe.throw("The stock sale was not frozen at cutover")
                stock_request = {"service": stock_service.name,
                    "modified": str(stock_service.modified),
                    "method": source_foreign_method.name,
                    "shift": "",
                    "reference": "HIST-STOCK-RETURN-" + suffix,
                    "reason": "Devolución de artículo anterior al corte"}
                if not frappe.db.exists("Stock Entry Type", "Material Receipt"):
                    frappe.get_doc({"doctype": "Stock Entry Type",
                        "name": "Material Receipt",
                        "purpose": "Material Receipt"}).insert(
                            ignore_permissions=True)
                stock_return_quote = suite_api.erp_historical_direct_sale_return_quote(
                    prop.name, canonical(stock_request))
                if (stock_return_quote["refund_currency"] != "USD" or
                        Decimal(stock_return_quote["refund_amount"]) !=
                        Decimal(str(frappe.db.get_value("HS Payment",
                            stock_sale["payment"], "amount")))):
                    frappe.throw("The bank return changed the original currency")
                stock_return = suite_api.execute(prop.name,
                    "erp_historical_direct_sale_return",
                    "historical-stock-return-" + suffix,
                    {**stock_request,
                     "acceptance": stock_return_quote["acceptance"]})
                if (suite_api.execute(prop.name,
                        "erp_historical_direct_sale_return",
                        "historical-stock-return-" + suffix,
                        {**stock_request,
                         "acceptance": stock_return_quote["acceptance"]}) !=
                            stock_return):
                    frappe.throw("The historical stock return duplicated")
                stock_service.reload()
                restored = frappe.get_doc("Stock Entry",
                    stock_return["stock_entry"])
                stock_after = Decimal(str(frappe.db.get_value("Bin", {
                    "warehouse": target_warehouse, "item_code": item.name},
                    "actual_qty") or 0))
                if (stock_service.status != "Returned" or
                        stock_service.return_stock_entry != restored.name or
                        stock_service.erp_return_refund != stock_return["refund"] or
                        stock_service.pms_fiscal_invoice != stock_sale["invoice"] or
                        restored.docstatus != 1 or
                        restored.stock_entry_type != "Material Receipt" or
                        restored.items[0].item_code != item.name or
                        Decimal(str(restored.items[0].qty)) != 1 or
                        stock_after != stock_before + 1):
                    frappe.throw("The historical stock return did not restore inventory")
                stock_gl = frappe.get_all("GL Entry", filters={
                    "voucher_type": "Stock Entry", "voucher_no": restored.name,
                    "is_cancelled": 0}, fields=["account", "debit", "credit"],
                    limit_page_length=20)
                stock_net = {account: sum((Decimal(str(row.debit)) -
                    Decimal(str(row.credit)) for row in stock_gl
                    if row.account == account), Decimal(0)) for account in (
                        stock_proof["stock"]["inventory_account"],
                        stock_proof["stock"]["expense_account"])}
                if (stock_net[stock_proof["stock"]["inventory_account"]] != 10 or
                        stock_net[stock_proof["stock"]["expense_account"]] != -10):
                    frappe.throw("The historical stock cost was not reversed")
                if suite_api.pms_direct_sale_history(
                        prop.name, returnable=1)["rows"]:
                    frappe.throw("Returned historical sales remain eligible again")
                complete_history = suite_api.pms_direct_sale_history(prop.name)
                by_service = {row["name"]: row for row in
                    complete_history["rows"]}
                if (by_service[historical_sale.name]["native_credit_note"] !=
                        historical_return["credit_note"] or
                        by_service[stock_service.name]["native_credit_note"] !=
                        stock_return["credit_note"]):
                    frappe.throw("Native credits are absent from historical sales")
                from hospitality_suite.security import guard_cancel
                for linked_doc in (native_credit, native_payment, restored):
                    try:
                        guard_cancel(linked_doc)
                    except frappe.ValidationError as exc:
                        if "históric" not in str(exc).lower():
                            raise
                    else:
                        frappe.throw("A historical return document could be cancelled")
            finally:
                frappe.local.hs_cutover_rehearsal = previous_counter_flag
        finally:
            frappe.db.rollback(save_point="hs_counter_sale_cutover_probe")
            from hospitality_suite.pms_cutover_activation import _clear_cutover_metadata
            _clear_cutover_metadata()
            prop.reload()
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The counter sale probe did not restore the source")
        if not manifest["rewrites"]:
            frappe.throw("Synthetic cutover did not exercise link rewriting")
        if {(row["doctype"], row["name"], row["field"]) for row in
                manifest["snapshot_rewrites"]} != {
                    ("HS Booking", booking.name, "quote_snapshot"),
                    ("HS Allocation", reservation.name, "quote_snapshot")}:
            frappe.throw("Open quotes were not included in the cutover manifest")
        if {(row["doctype"], row["name"]) for row in
                manifest["experience_rewrites"]} != {
                    ("HS Experience", experience.name),
                    ("HS Experience Order", experience_order.name)}:
            frappe.throw("Pending booked experiences were not mapped")
        if {(row["doctype"], row["name"]) for row in
                manifest["laundry_rewrites"]} != {
                    ("HS Laundry Rate", laundry_rate.name)}:
            frappe.throw("PMS laundry rates were not mapped")
        frappe.db.savepoint("hs_open_laundry_cutover_probe")
        try:
            probe_guest = frappe.get_doc({"doctype": "HS Guest",
                "name": make_autoname("HUE-.#####"),
                "company": source_company.name, "property": prop.name,
                "customer": party.name, "full_name": "Laundry guest " + suffix})
            probe_guest.db_insert()
            probe_stay = frappe.get_doc({"doctype": "HS Stay",
                "name": make_autoname("EST-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "booking": booking.name, "guest": probe_guest.name,
                "customer": party.name, "room": room.name,
                "rate": rate.name, "starts_at": arrival, "ends_at": departure,
                "status": "Active", "currency": "NIO", "amount": "20.00",
                "quote_snapshot": canonical(accepted_line),
                "service_entitlements": "[]"})
            probe_stay.db_insert()
            frappe.db.set_value("HS Booking", booking.name, "status",
                                "Checked In", update_modified=False)
            frappe.db.set_value("HS Allocation", reservation.name,
                                {"kind": "Stay", "stay": probe_stay.name},
                                update_modified=False)
            frappe.db.set_value("HS Folio", folio.name, "stay", probe_stay.name,
                                update_modified=False)
            with operation(prop):
                open_laundry = frappe.get_doc({"doctype": "HS Laundry Order",
                    "company": source_company.name, "property": prop.name,
                    "stay": probe_stay.name, "room": room.name,
                    "folio": folio.name, "currency": "NIO", "status": "Ready",
                    "total": "6", "counted_at": frappe.utils.now_datetime(),
                    "items": [{"laundry_rate": laundry_rate.name,
                        "garment": "Camisa de corte", "service_type": "Wash & Iron",
                        "pms_product": experience_product.name,
                        "quantity": 1, "returned_quantity": 1,
                        "rate": "6", "amount": "6"}]}).insert(ignore_permissions=True)
            probe_source = pms_cutover.preflight()
            if not probe_source["ready_for_mapping"]:
                frappe.throw("An open PMS laundry order failed source preflight")
            laundry_mapping = deepcopy(mapping)
            laundry_mapping["source_sha256"] = probe_source["source_sha256"]
            laundry_review = pms_cutover_plan.review(laundry_mapping)
            if (not laundry_review["cutover_inputs_consistent"] or
                    {(row["doctype"], row["name"]) for row in
                     laundry_review["link_manifest"]["laundry_rewrites"]} != {
                        ("HS Laundry Rate", laundry_rate.name),
                        ("HS Laundry Order Item", open_laundry.items[0].name)}):
                frappe.throw("An undelivered laundry order lost its item mapping")
            from hospitality_suite import pms_cutover_activation
            previous_probe_flag = getattr(frappe.local,
                "hs_cutover_rehearsal", False)
            frappe.local.hs_cutover_rehearsal = True
            try:
                laundry_activation = pms_cutover_activation.activate_validated(
                    laundry_mapping, source_sha256=probe_source["source_sha256"],
                    plan_sha256=laundry_review["plan"]["plan_sha256"],
                    link_sha256=laundry_review["link_manifest"]["link_sha256"],
                    migration_reference="HS-LAUNDRY-" + suffix)
                if (laundry_activation["links"]["laundry_rows_updated"] != 2 or
                        frappe.db.get_value("HS Laundry Order Item",
                            open_laundry.items[0].name, "item") !=
                            experience_item.name):
                    frappe.throw("The open PMS laundry order lost its ERP item")
                delivered_open = execute(prop.name, "laundry_deliver",
                    "cutover-open-laundry-" + suffix,
                    {"order": open_laundry.name,
                     "modified": str(frappe.db.get_value("HS Laundry Order",
                        open_laundry.name, "modified"))})
                if (Decimal(delivered_open["billed_total"]) != Decimal("6") or
                        not frappe.db.exists("HS Charge", {
                            "folio": folio.name, "item": experience_item.name,
                            "amount": 6, "status": "Pending"})):
                    frappe.throw("The PMS laundry order could not be delivered in ERPNext")
            finally:
                frappe.local.hs_cutover_rehearsal = previous_probe_flag
        finally:
            frappe.db.rollback(save_point="hs_open_laundry_cutover_probe")
            from hospitality_suite.pms_cutover_activation import _clear_cutover_metadata
            _clear_cutover_metadata()
        if (frappe.db.get_value("HS Laundry Rate", laundry_rate.name, "item") or
                frappe.db.get_value("HS Property", prop.name, "company") !=
                    source_company.name):
            frappe.throw("The open-laundry probe did not restore the PMS source")
        if [row["name"] for row in manifest["agent_rewrites"]] != [travel_agent.name]:
            frappe.throw("The travel agent supplier was not mapped")
        if ([row["source_party"] for row in manifest["billing_party_creations"]] !=
                [party.name] or
                Decimal(manifest["billing_party_creations"][0]["terms"][
                    "credit_limit"]) != Decimal("200")):
            frappe.throw("The PMS payer's credit terms were not mapped")
        frappe.db.savepoint("hs_billing_party_conflict_probe")
        try:
            conflicting_party = frappe.get_doc({"doctype": "HS Billing Party",
                "name": make_autoname("PAGADOR-.#####"),
                "company": source_company.name, "property": prop.name,
                "customer": customer.name, "kind": "Individual",
                "credit_authorized": 0, "credit_limit": 0,
                "credit_days": 30, "reason": "Conflicting credit policy"})
            conflicting_party.db_insert()
            conflict = pms_cutover_plan.review(mapping)
            if (conflict["cutover_inputs_consistent"] or
                    not any(row["code"] == "billing_party_policy_conflict"
                            for row in conflict["link_manifest"]["blockers"])):
                frappe.throw("A conflicting ERPNext credit policy passed cutover")
        finally:
            frappe.db.rollback(save_point="hs_billing_party_conflict_probe")
        original_quote = frappe.db.get_value("HS Booking", booking.name,
                                             "quote_snapshot")
        pending_experience_quote = frappe.parse_json(original_quote)
        pending_experience_quote["experiences"] = [
            {"item": "WRONG-ITEM-" + suffix,
             "pms_product": experience_product.name}]
        frappe.db.set_value("HS Booking", booking.name, "quote_snapshot",
                            canonical(pending_experience_quote),
                            update_modified=False)
        experience_mapping = deepcopy(mapping)
        experience_mapping["source_sha256"] = pms_cutover.preflight()["source_sha256"]
        rejected_experience = pms_cutover_plan.review(experience_mapping)
        if (rejected_experience["cutover_inputs_consistent"] or
                not any(row["code"] == "unmapped_pms_experience_snapshot"
                        for row in rejected_experience["link_manifest"]["blockers"])):
            frappe.throw("A pending PMS experience bypassed snapshot mapping")
        frappe.db.set_value("HS Booking", booking.name, "quote_snapshot",
                            original_quote, update_modified=False)
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The unsupported experience probe changed the source")
        frappe.db.savepoint("hs_active_stay_snapshot_probe")
        try:
            guest = frappe.get_doc({"doctype": "HS Guest",
                "name": make_autoname("HUE-.#####"),
                "company": source_company.name, "property": prop.name,
                "customer": party.name, "full_name": "Stay guest " + suffix})
            guest.db_insert()
            stay = frappe.get_doc({"doctype": "HS Stay",
                "name": make_autoname("EST-.YYYY.-.#####"),
                "company": source_company.name, "property": prop.name,
                "booking": booking.name, "guest": guest.name,
                "customer": party.name, "room": room.name,
                "rate": rate.name, "starts_at": arrival, "ends_at": departure,
                "status": "Active", "currency": "NIO", "amount": "20.00",
                "quote_snapshot": canonical(accepted_line),
                "service_entitlements": canonical([
                    {"item": source_service.name, "quantity": "1"}])})
            stay.db_insert()
            frappe.db.set_value("HS Booking", booking.name, "status",
                                "Checked In", update_modified=False)
            frappe.db.set_value("HS Allocation", reservation.name,
                                {"kind": "Stay", "stay": stay.name},
                                update_modified=False)
            frappe.db.set_value("HS Folio", folio.name, "stay", stay.name,
                                update_modified=False)
            stay_mapping = deepcopy(mapping)
            stay_mapping["source_sha256"] = pms_cutover.preflight()["source_sha256"]
            stay_review = pms_cutover_plan.review(stay_mapping)
            if not stay_review["cutover_inputs_consistent"]:
                frappe.throw("A valid active stay cannot be translated")
            from hospitality_suite import pms_cutover_links
            stay_manifest = stay_review["link_manifest"]
            if not {("HS Stay", stay.name, "quote_snapshot"),
                    ("HS Stay", stay.name, "service_entitlements")} <= {
                    (row["doctype"], row["name"], row["field"])
                    for row in stay_manifest["snapshot_rewrites"]}:
                frappe.throw("The active stay snapshots were omitted")
            pms_cutover_links.apply(stay_manifest, stay_manifest["link_sha256"])
            translated_stay = frappe.parse_json(frappe.db.get_value(
                "HS Stay", stay.name, "quote_snapshot"))
            translated_entitlements = frappe.parse_json(frappe.db.get_value(
                "HS Stay", stay.name, "service_entitlements"))
            if (translated_stay["charge_items"]["lodging_item"] != lodging_item.name or
                    translated_entitlements[0]["item"] != lodging_item.name):
                frappe.throw("An active stay kept embedded PMS product references")
        finally:
            frappe.db.rollback(save_point="hs_active_stay_snapshot_probe")
        if pms_cutover.preflight()["source_sha256"] != plan["source_sha256"]:
            frappe.throw("The active stay translation probe changed the source")
        try:
            pms_cutover_rehearsal.run(mapping,
                source_sha256=plan["source_sha256"],
                plan_sha256="0" * 64,
                link_sha256=manifest["link_sha256"])
        except frappe.ValidationError:
            if frappe.db.count("GL Entry", {"company": target_company.name}):
                frappe.throw("Stale plan hash left target postings behind")
        else:
            frappe.throw("Stale cutover plan hash was accepted")
        original_post = pms_cutover_rehearsal.pms_cutover_writer.post_property

        def reject_post(property_plan):
            posted = original_post(property_plan)
            if not frappe.db.count("GL Entry", {"company": target_company.name}):
                frappe.throw("Opening postings were not attempted before failure")
            if frappe.db.get_value("HS Property", prop.name, "company") != target_company.name:
                frappe.throw("Links were not rewritten before opening postings")
            if (not posted["guarantees"] or
                    frappe.db.get_value("HS Payment", guarantee.name,
                        "journal_entry") != posted["guarantees"][0] or
                    frappe.db.get_value("HS Payment", guarantee.name,
                        "customer") != customer.name or
                    frappe.db.get_value("HS Payment", guarantee.name,
                        "booking") != booking.name):
                frappe.throw("Guarantee bridge was not available during cutover")
            from hospitality_suite.accounting import guarantee_balance
            if guarantee_balance(frappe.get_doc("HS Property", prop.name),
                    frappe.get_doc("HS Payment", guarantee.name)).book != 15:
                frappe.throw("Historical guarantee application did not survive cutover")
            if (len(posted["advances"]) != 1 or
                    frappe.db.get_value("HS Payment", advance.name,
                        "payment_entry") != posted["advances"][0] or
                    frappe.db.get_value("HS Payment", advance.name,
                        "customer") != customer.name):
                frappe.throw("Advance bridge was not available during cutover")
            from hospitality_suite.refunds import balance as refund_balance, plan as refund_plan
            target_property = frappe.get_doc("HS Property", prop.name)
            target_advance = frappe.get_doc("HS Payment", advance.name)
            available_advance = refund_balance(target_property, target_advance)
            if (available_advance.remaining != 12 or
                    available_advance.remaining_party != 12 or
                    available_advance.funds.unallocated != 12):
                frappe.throw("Historical advance use did not survive cutover")
            refund = refund_plan(target_property, target_advance, 5,
                                 frappe._dict(currency="NIO"))
            if (refund.party_amount != 5 or
                    refund.proof["mode"] != "Unallocated Advance" or
                    float(refund.proof["remaining"]) != 12):
                frappe.throw("Partial post-cutover advance refund used original funds")
            raise RuntimeError("Injected failure after opening postings")

        pms_cutover_rehearsal.pms_cutover_writer.post_property = reject_post
        try:
            try:
                pms_cutover_rehearsal.run(mapping,
                    source_sha256=plan["source_sha256"],
                    plan_sha256=plan["plan_sha256"],
                    link_sha256=manifest["link_sha256"])
            except RuntimeError as exc:
                if str(exc) != "Injected failure after opening postings":
                    raise
            else:
                frappe.throw("Injected cutover failure was not propagated")
        finally:
            pms_cutover_rehearsal.pms_cutover_writer.post_property = original_post
        if (frappe.db.count("GL Entry", {"company": target_company.name}) or
                frappe.db.get_value("HS Property", prop.name, "company") != source_company.name or
                frappe.db.get_value("HS Payment", guarantee.name, "journal_entry") or
                frappe.db.get_value("HS Payment", guarantee.name, "customer") or
                frappe.db.get_value("HS Payment", guarantee.name, "booking") or
                frappe.db.get_value("HS Payment", advance.name, "payment_entry") or
                frappe.db.get_value("HS Payment", advance.name, "customer")):
            frappe.throw("Failed rehearsal left target or source changes behind")
        result = pms_cutover_rehearsal.run(mapping,
            source_sha256=plan["source_sha256"],
            plan_sha256=plan["plan_sha256"],
            link_sha256=manifest["link_sha256"])
        if frappe.db.get_value("HS Property", prop.name, "company") != source_company.name:
            frappe.throw("Rehearsal did not restore PMS company links")
        if (frappe.db.get_value("HS Booking", booking.name, "customer") != party.name or
                frappe.db.get_value("HS Folio", folio.name, "customer") != party.name or
                frappe.db.count("HS Supplier", {"property": prop.name})):
            frappe.throw("Rehearsal did not restore party links and supplier bindings")
        if frappe.db.count("GL Entry", {"company": target_company.name}):
            frappe.throw("Rehearsal left ERPNext GL entries behind")
        reconciled = result["properties"][0]["reconciliation"]["accounts"]
        if (reconciled.get(cfg["accounts"][cash.name]) != "84" or
                reconciled.get(cfg["accounts"][receivable.name]) != "13" or
                reconciled.get(cfg["accounts"][payable.name]) != "-40" or
                reconciled.get(cfg["accounts"][inventory.name]) != "30" or
                reconciled.get(cfg["accounts"][guarantee_liability.name]) != "-15" or
                reconciled.get(cfg["accounts"][equity.name]) != "-130" or
                reconciled.get(target_petty.name) != "38" or
                reconciled.get(cfg["accounts"][petty_expense_account.name]) != "20" or
                reconciled.get(target_loan.name) != "-36.5" or
                reconciled.get(target_foreign_bank.name) != "36.5" or
                not result["properties"][0]["profit_loss_transfer_journal"]):
            frappe.throw("Rehearsal opening balances did not match PMS")
        if (len(result["properties"][0]["receivables"]) != 1 or
                len(result["properties"][0]["guarantees"]) != 1 or
                len(result["properties"][0]["advances"]) != 1):
            frappe.throw("Rehearsal did not carry the open folio receivable")
        if (len(result["properties"][0]["payables"]) != 1 or
                result["supplier_bindings_created"] != 1):
            frappe.throw("Rehearsal did not bind the open supplier payable")
        if (result["properties"][0]["reconciliation"]["stock_positions"] != 2 or
                result["warehouses_assigned"] != 2 or
                frappe.db.get_value("Warehouse", target_warehouse, "hs_property") or
                frappe.db.get_value("Warehouse", target_laundry.name, "hs_property")):
            frappe.throw("Rehearsal did not restore the stock warehouse")
        from hospitality_suite import pms_cutover_activation
        activated = pms_cutover_activation.rehearse_activation(mapping,
            source_sha256=plan["source_sha256"],
            plan_sha256=plan["plan_sha256"],
            link_sha256=manifest["link_sha256"],
            migration_reference="HS-REHEARSAL-" + suffix)
        if (not activated["activation_rehearsed"] or
                activated["cutover_performed"] or
                frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") or
                frappe.db.get_value("HS Property", prop.name, "company") !=
                    source_company.name or
                frappe.db.count("GL Entry", {"company": target_company.name})):
            frappe.throw("Activation rehearsal did not restore both books")
        without_price_list = deepcopy(mapping)
        without_price_list["properties"][prop.name]["target_settings"].pop(
            "price_list")
        if not any(row["code"] == "missing_target_setting" and
                row.get("kind") == "price_list" for row in
                pms_cutover_mapping.review(without_price_list)["mapping_blockers"]):
            frappe.throw("Map review claimed readiness without a target price list")
        try:
            pms_cutover_activation.rehearse_activation(without_price_list,
                source_sha256=plan["source_sha256"],
                plan_sha256=plan["plan_sha256"],
                link_sha256=manifest["link_sha256"],
                migration_reference="HS-NO-PRICE-LIST-" + suffix)
        except frappe.ValidationError:
            pass
        else:
            frappe.throw("Cutover accepted a property without a sales price list")
        frappe.local.conf.maintenance_mode = 0
        frappe.local.hs_cutover_rehearsal = False
        try:
            pms_cutover_activation.activate_validated(mapping,
                source_sha256=plan["source_sha256"],
                plan_sha256=plan["plan_sha256"],
                link_sha256=manifest["link_sha256"],
                migration_reference="HS-NOT-FROZEN-" + suffix)
        except frappe.PermissionError:
            pass
        else:
            frappe.throw("A live cutover bypassed site maintenance")
        frappe.local.conf.maintenance_mode = 1
        with patch("frappe.utils.doctor.any_job_pending", return_value=True):
            try:
                pms_cutover_activation.activate_validated(mapping,
                    source_sha256=plan["source_sha256"],
                    plan_sha256=plan["plan_sha256"],
                    link_sha256=manifest["link_sha256"],
                    migration_reference="HS-JOBS-PENDING-" + suffix)
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("A live cutover ignored pending background jobs")
        with patch("frappe.utils.doctor.any_job_pending", return_value=False):
            try:
                pms_cutover_activation.activate_validated(mapping,
                    source_sha256=plan["source_sha256"],
                    plan_sha256=plan["plan_sha256"],
                    link_sha256=manifest["link_sha256"],
                    migration_reference="HS-NO-BACKUP-" + suffix)
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("A live cutover did not require a backup manifest")
        backup_dir = TemporaryDirectory(prefix="hs-cutover-backup-")
        backup_root = Path(backup_dir.name)
        live_config = backup_root / "site_config.json"
        saved_config = canonical({"maintenance_mode": 1,
                                  "db_name": frappe.local.conf.get("db_name")})
        live_config.write_text(saved_config, encoding="utf-8")
        prefix = (frappe.utils.now_datetime().strftime("%Y%m%d_%H%M%S") +
                  "-" + frappe.local.site.replace(".", "_"))
        backup_names = {
            "database": prefix + "-database.sql.gz",
            "public_files": prefix + "-files.tar",
            "private_files": prefix + "-private-files.tar",
            "site_config": prefix + "-site_config_backup.json"}
        for role, filename in backup_names.items():
            (backup_root / filename).write_bytes(
                saved_config.encode() if role == "site_config" else
                ("synthetic " + role).encode())
        with (patch("hospitality_suite.pms_cutover_backup._backup_root",
                    return_value=backup_root),
              patch("hospitality_suite.pms_cutover_backup._live_config",
                    return_value=live_config)):
            backup_manifest = pms_cutover_backup.prepare()
            if len(backup_manifest) != 4:
                frappe.throw("The complete backup manifest was not found")
            (backup_root / backup_names["public_files"]).write_bytes(b"changed")
            try:
                pms_cutover_backup.verify(backup_manifest)
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("A changed backup file was accepted")
            (backup_root / backup_names["public_files"]).write_bytes(
                b"synthetic public_files")
            backup_manifest = pms_cutover_backup.prepare()
        reference = "HS-ACTIVATE-" + suffix
        frappe.db.savepoint("hs_cutover_idempotency_probe")
        try:
            from hospitality_suite import pms_cutover_cli

            with TemporaryDirectory(prefix="hs-cutover-cli-") as cli_folder:
                private_root = Path(cli_folder)
                (private_root / "mapping.json").write_text(
                    canonical(mapping), encoding="utf-8")
                with (patch("frappe.utils.doctor.any_job_pending",
                            return_value=False),
                      patch("hospitality_suite.pms_cutover_backup._backup_root",
                            return_value=backup_root),
                      patch("hospitality_suite.pms_cutover_backup._live_config",
                            return_value=live_config),
                      patch("hospitality_suite.pms_cutover_cli._private_root",
                            return_value=private_root),
                      patch("hospitality_suite.pms_cutover_cli._fresh_transaction")):
                    cli_review = pms_cutover_cli.review_file("mapping.json")
                    if (not cli_review["ready"] or
                            cli_review["source_sha256"] !=
                                plan["source_sha256"] or
                            cli_review["plan_sha256"] !=
                                plan["plan_sha256"] or
                            cli_review["link_sha256"] !=
                                manifest["link_sha256"]):
                        frappe.throw("The operator review lost cutover hashes")
                    prepared = pms_cutover_cli.prepare_backup_file(
                        "backup-manifest.json")
                    if not prepared["backup_sha256"]:
                        frappe.throw("The operator manifest lost its digest")
                    arguments = {"source_sha256": cli_review["source_sha256"],
                        "mapping_sha256": cli_review["mapping_sha256"],
                        "plan_sha256": cli_review["plan_sha256"],
                        "link_sha256": cli_review["link_sha256"],
                        "backup_sha256": prepared["backup_sha256"],
                        "migration_reference": reference}
                    try:
                        pms_cutover_cli.activate_file("mapping.json",
                            prepared["backup_file"],
                            **{**arguments, "mapping_sha256": "0" * 64})
                    except frappe.ValidationError:
                        pass
                    else:
                        frappe.throw("The operator command accepted a changed map")
                    try:
                        pms_cutover_cli.activate_file("mapping.json",
                            prepared["backup_file"],
                            **{**arguments, "backup_sha256": "0" * 64})
                    except frappe.ValidationError:
                        pass
                    else:
                        frappe.throw("The operator command accepted another backup")
                    if frappe.db.get_single_value("HS Site Mode", "provider") != "PMS":
                        frappe.throw("A rejected operator command switched providers")
                    lock_trace = []
                    original_lock = pms_cutover_activation._locked_mode
                    original_review = pms_cutover_plan.review

                    def observed_lock():
                        lock_trace.append("lock")
                        return original_lock()

                    def observed_review(*args, **kwargs):
                        lock_trace.append("review")
                        return original_review(*args, **kwargs)

                    with (patch.object(frappe.db, "commit") as committed,
                          patch.object(pms_cutover_activation, "_locked_mode",
                              side_effect=observed_lock),
                          patch.object(pms_cutover_plan, "review",
                              side_effect=observed_review)):
                        cli_result = pms_cutover_cli.activate_file(
                            "mapping.json", prepared["backup_file"],
                            **arguments)
                        first_trace = list(lock_trace)
                        replayed_cli = pms_cutover_cli.activate_file(
                            "mapping.json", prepared["backup_file"],
                            **arguments)
                        if (replayed_cli != cli_result or committed.call_count != 2 or
                                first_trace[:2] != ["lock", "review"] or
                                "review" in lock_trace[len(first_trace):]):
                            frappe.throw("The operator cutover did not serialize review and replay")
                    if (not cli_result["cutover_performed"] or
                            cli_result["migration_reference"] != reference or
                            cli_result["property_count"] != 1):
                        frappe.throw("The operator command did not record the cutover")
                    if frappe.db.get_value("HS Property", prop.name, "tax_policy_confirmed"):
                        frappe.throw("Cutover falsely recorded the operator's tax review")
                    if (frappe.db.get_value("HS Property", prop.name, "warehouse") !=
                            target_warehouse or
                            frappe.db.get_value("HS Property", prop.name,
                                "laundry_warehouse") != target_laundry.name or
                            Decimal(str(frappe.db.get_value("Bin", {
                                "item_code": item.name,
                                "warehouse": target_warehouse}, "actual_qty") or 0)) != 2 or
                            Decimal(str(frappe.db.get_value("Bin", {
                                "item_code": item.name,
                                "warehouse": target_laundry.name}, "actual_qty") or 0)) != 1):
                        frappe.throw("The linen stock did not open in both mapped ERPNext warehouses")
                    from hospitality_suite import api as suite_api
                    health_after_cutover = suite_api.health_snapshot(prop.name)
                    if (health_after_cutover["accounting_provider"] != "erpnext" or
                            next(row for row in health_after_cutover["checks"]
                                if row["key"] == "configuration")["status"] != "OK"):
                        frappe.throw("ERPNext health omitted the activated property configuration")
                    portfolio_after_cutover = suite_api.portfolio_snapshot()
                    portfolio_hotel = next((row for row in
                        portfolio_after_cutover["properties"]
                        if row["property"] == prop.name), None)
                    if (not portfolio_hotel or
                            Decimal(portfolio_hotel["amounts"].get(
                                "NIO", {}).get("receivable", "0")) <= 0):
                        frappe.throw("ERPNext portfolio omitted the hotel's opening receivable")
                    open_incident = suite_api.execute(prop.name, "incident",
                        "reverse-open-incident-" + suffix,
                        {"room": room.name, "kind": "Lost Property",
                         "description": "Objeto pendiente de entrega"})["incident"]
                    incident_evidence_file = frappe.get_doc({
                        "doctype": "File",
                        "file_name": "reverse-incident-" + suffix + ".txt",
                        "content": ("Evidencia de incidencia " + suffix).encode(),
                        "is_private": 1,
                        "attached_to_doctype": "HS Incident",
                        "attached_to_name": open_incident}).insert(
                            ignore_permissions=True)
                    incident_evidence_path = Path(
                        incident_evidence_file.get_full_path())
                    suite_api.execute(prop.name, "incident",
                        "reverse-open-incident-evidence-" + suffix,
                        {"incident": open_incident,
                         "modified": str(frappe.db.get_value(
                             "HS Incident", open_incident, "modified")),
                         "evidence": incident_evidence_file.file_url})
                    evidence_files = frappe.get_all("File", filters={
                        "file_url": incident_evidence_file.file_url},
                        fields=["name", "file_url", "is_private",
                            "attached_to_doctype", "attached_to_name"],
                        limit_page_length=0)
                    if not evidence_files or any(
                            row["attached_to_doctype"] != "HS Incident" or
                            row["attached_to_name"] != open_incident or
                            not row["is_private"] for row in evidence_files):
                        frappe.throw("Incident File fixture is not private")
                    maintenance_start = str(frappe.utils.add_days(
                        frappe.utils.now_datetime(), 35))
                    maintenance_end = str(frappe.utils.add_days(
                        frappe.utils.now_datetime(), 36))
                    reverse_maintenance = suite_api.execute(prop.name,
                        "maintenance", "reverse-returned-maintenance-" + suffix,
                        {"room": room.name, "blocks_room": 0,
                         "title": "Repuesto devuelto antes del corte inverso",
                         "kind": "Preventive", "starts_at": maintenance_start,
                         "ends_at": maintenance_end})["order"]
                    maintenance_evidence_file = frappe.get_doc({
                        "doctype": "File",
                        "file_name": "reverse-maintenance-" + suffix + ".txt",
                        "content": ("Evidencia de mantenimiento " + suffix).encode(),
                        "is_private": 1,
                        "attached_to_doctype": "HS Maintenance Order",
                        "attached_to_name": reverse_maintenance}).insert(
                            ignore_permissions=True)
                    maintenance_evidence_path = Path(
                        maintenance_evidence_file.get_full_path())
                    suite_api.execute(prop.name, "maintenance",
                        "reverse-open-maintenance-evidence-" + suffix,
                        {"order": reverse_maintenance,
                         "modified": str(frappe.db.get_value(
                             "HS Maintenance Order", reverse_maintenance,
                             "modified")),
                         "evidence": maintenance_evidence_file.file_url})
                    maintenance_doc = frappe.get_doc("HS Maintenance Order",
                        reverse_maintenance)
                    if not frappe.db.exists("Stock Entry Type", "Material Issue"):
                        frappe.get_doc({"doctype": "Stock Entry Type",
                            "name": "Material Issue", "purpose": "Material Issue"}).insert(
                                ignore_permissions=True)
                    issued_part = suite_api.execute(prop.name,
                        "maintenance_parts", "reverse-returned-issue-" + suffix,
                        {"order": reverse_maintenance,
                         "modified": str(maintenance_doc.modified),
                         "parts": [{"item": item.name, "quantity": 1},
                                   {"item": item.name, "quantity": 1}]})
                    issued_inventory = suite_api.erp_to_pms_preflight()
                    issued_hotel = next(row for row in issued_inventory["properties"]
                        if row["property"] == prop.name)
                    issued_rows = [row for row in issued_hotel["open_operations"][
                        "maintenance_parts"] if row["parent"] == reverse_maintenance]
                    if (len(issued_rows) != 2 or
                            any(row.get("source_stock_issue", {}).get(
                                "voucher") != issued_part["stock_entry"] or
                                row.get("source_stock_issue", {}).get(
                                    "group_count") != 2 or
                                not row.get("source_stock_issue_sha256")
                                for row in issued_rows) or
                            len({row["source_stock_issue"]["detail"]
                                for row in issued_rows}) != 2 or
                            any(row["code"] == "invalid_open_maintenance_stock_issue"
                                for row in issued_inventory["blockers"])):
                        frappe.throw("El diagnóstico no congeló el costo del repuesto vigente")
                    maintenance_doc.reload()
                    suite_api.execute(prop.name, "maintenance_parts",
                        "reverse-returned-part-" + suffix,
                        {"order": reverse_maintenance,
                         "modified": str(maintenance_doc.modified),
                         "return_entry": issued_part["stock_entry"],
                         "reason": "Pieza no utilizada"})
                    reverse_source = suite_api.erp_to_pms_preflight()
                    reverse_hotel = next((row for row in reverse_source["properties"]
                        if row["property"] == prop.name), None)
                    reverse_checks = {
                        "not_ready": not reverse_source["ready_for_mapping"],
                        "stable_hash": bool(reverse_source["source_sha256"]) and
                            reverse_source["source_sha256"] ==
                                suite_api.erp_to_pms_preflight()["source_sha256"],
                        "hotel": bool(reverse_hotel),
                    }
                    if reverse_hotel:
                        reverse_checks.update({
                            "returned_maintenance": any(
                                row["parent"] == reverse_maintenance and
                                row["status"] == "Returned" and
                                row.get("source_returned_entry", {}).get(
                                    "docstatus") == 2 and
                                row["stock_entry"] == issued_part["stock_entry"]
                                for row in reverse_hotel["open_operations"][
                                    "maintenance_parts"]),
                            "maintenance_evidence": any(
                                row["name"] == reverse_maintenance and
                                row["evidence"] ==
                                    maintenance_evidence_file.file_url and
                                row.get("evidence_sha256") == sha256(
                                    maintenance_evidence_path.read_bytes()
                                    ).hexdigest() for row in
                                reverse_hotel["open_operations"][
                                    "maintenance_orders"]),
                            "ledger": bool(reverse_hotel["ledger"]["matched_entries"]),
                            "receivables": bool(reverse_hotel["open_receivables"]),
                            "guarantee": any(row["source"] == guarantee.name and
                                Decimal(row["base_balance"]) == 15 for row in
                                reverse_hotel["deposits"]["guarantees"]),
                            "advance": any(Decimal(row["available"]) == 12 and
                                any(source["name"] == advance.name for source in
                                    row["sources"]) for row in
                                reverse_hotel["deposits"]["customer_credits"]),
                            "booking": any(row["name"] == booking.name for row in
                                reverse_hotel["open_operations"]["bookings"]),
                            "incident": any(row["name"] == open_incident and
                                row["room"] == room.name and
                                row["kind"] == "Lost Property" and
                                row["evidence"] ==
                                    incident_evidence_file.file_url and
                                row.get("evidence_sha256") == sha256(
                                    incident_evidence_path.read_bytes()
                                    ).hexdigest() for row in
                                reverse_hotel["open_operations"]["incidents"]),
                            "booking_terms": any(
                                row["name"] == booking.name and
                                row["quote_snapshot"] == frappe.db.get_value(
                                    "HS Booking", booking.name, "quote_snapshot") and
                                row["quote_snapshot_sha256"] == sha256(
                                    row["quote_snapshot"].encode()).hexdigest() and
                                row["travel_agent"] == travel_agent.name for row in
                                reverse_hotel["open_operations"]["bookings"]),
                            "booking_room": any(row["name"] == booking_line.name for
                                row in reverse_hotel["open_operations"]["booking_rooms"]),
                            "allocation": any(row["name"] == reservation.name for
                                row in reverse_hotel["open_operations"]["allocations"]),
                            "allocation_terms": any(
                                row["name"] == reservation.name and
                                row["rate"] == rate.name and
                                row["quote_snapshot"] == frappe.db.get_value(
                                    "HS Allocation", reservation.name,
                                    "quote_snapshot") and
                                row["quote_sha256"] == sha256(
                                    row["quote_snapshot"].encode()).hexdigest()
                                for row in reverse_hotel["open_operations"]["allocations"]),
                            "agent_requirement": any(
                                row["name"] == travel_agent.name for row in
                                reverse_hotel["mapping_requirements"]["travel_agents"]),
                            "experience_order": any(
                                row["name"] == experience_order.name and
                                row["experience"] == experience.name and
                                row["item"] == experience_item.name for row in
                                reverse_hotel["open_operations"]["experience_orders"]),
                            "experience_requirement": any(
                                row["name"] == experience.name and
                                row["item"] == experience_item.name for row in
                                reverse_hotel["mapping_requirements"]["experiences"]),
                            "experience_supported": not any(
                                row.get("code") == "unsupported_live_operation" and
                                row.get("doctype") == "HS Experience Order" for row in
                                reverse_source["blockers"]),
                            "folios": bool(reverse_hotel["open_operations"]["folios"]),
                            "native_fiscal": bool(reverse_hotel["fiscal_history"]["native_documents"]),
                            "historical_fiscal": any(
                                row["name"] == historical_fiscal["document"] for row in
                                reverse_hotel["fiscal_history"]["pms_documents"]),
                            "stock": any(row["item"] == item.name and
                                Decimal(row["quantity"]) == 2 for row in
                                reverse_hotel["stock"]["positions"]),
                        })
                    failed_reverse = [name for name, passed in reverse_checks.items()
                                      if not passed]
                    if failed_reverse:
                        frappe.throw("ERPNext-to-PMS source inventory lost: " +
                                     ", ".join(failed_reverse) + " " +
                                     canonical([row for row in
                                         reverse_source["blockers"] if
                                         row.get("source") == open_incident]))
                    frappe.db.savepoint("hs_reverse_live_operation_probe")
                    try:
                        source_guest = frappe.get_doc({"doctype": "HS Guest",
                            "name": "GUEST-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "customer": frappe.db.get_value("HS Booking",
                                booking.name, "customer"),
                            "full_name": "Guest during reverse migration"})
                        source_guest.db_insert()
                        source_stay = frappe.get_doc({"doctype": "HS Stay",
                            "name": "STAY-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "booking": booking.name, "guest": source_guest.name,
                            "customer": source_guest.customer, "room": room.name,
                            "rate": rate.name, "starts_at": arrival,
                            "ends_at": departure, "status": "Active",
                            "currency": "NIO", "amount": "20",
                            "quote_snapshot": canonical(accepted_line),
                            "service_entitlements": canonical([{
                                "item": item.name, "quantity": "1"}])})
                        source_stay.db_insert()
                        source_stay_guest = frappe.get_doc({
                            "doctype": "HS Stay Guest",
                            "name": frappe.generate_hash(length=10),
                            "parent": source_stay.name,
                            "parenttype": "HS Stay", "parentfield": "guests",
                            "idx": 1, "guest": source_guest.name,
                            "relationship": "Principal"})
                        source_stay_guest.db_insert()
                        source_folio = frappe.db.get_value("HS Folio",
                            {"property": prop.name, "booking": booking.name,
                             "status": "Open"},
                            ["name", "customer", "currency"], as_dict=True)
                        if not source_folio:
                            frappe.throw("The reverse service probe has no open folio")
                        source_laundry = frappe.get_doc({
                            "doctype": "HS Laundry Order",
                            "name": "LAUNDRY-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "stay": source_stay.name, "room": room.name,
                            "folio": source_folio.name, "currency": "NIO",
                            "status": "Ready", "total": "6",
                            "billed_total": "0", "ready_by": departure,
                            "collected_by": "Administrator",
                            "collected_at": arrival,
                            "counted_at": arrival})
                        source_laundry.db_insert()
                        source_laundry_item = frappe.get_doc({
                            "doctype": "HS Laundry Order Item",
                            "name": "LAUNDRY-LINE-" + frappe.generate_hash(length=10),
                            "parent": source_laundry.name,
                            "parenttype": "HS Laundry Order",
                            "parentfield": "items", "idx": 1,
                            "laundry_rate": laundry_rate.name,
                            "garment": "Camisa de corte",
                            "service_type": "Wash & Iron",
                            "item": experience_item.name,
                            "quantity": 1, "returned_quantity": 1,
                            "rate": "6", "amount": "6"})
                        source_laundry_item.db_insert()
                        source_service = frappe.get_doc({
                            "doctype": "HS Service Request",
                            "name": "SREQ-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "stay": source_stay.name, "folio": source_folio.name,
                            "customer": source_folio.customer, "item": item.name,
                            "quantity": 1, "included": 0, "amount": "3",
                            "currency": source_folio.currency,
                            "status": "In Progress", "notes": "Guest delivery pending"})
                        source_service.db_insert()
                        cleaning_checklist = canonical({"baño": False,
                            "cama": False, "minibar": False,
                            "superficies": False})
                        source_cleaning = frappe.get_doc({
                            "doctype": "HS Cleaning Task",
                            "name": "CLEAN-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "room": room.name, "stay": source_stay.name,
                            "kind": "Stay", "priority": "High",
                            "assigned_to": "Administrator", "status": "Pending",
                            "checklist": cleaning_checklist,
                            "notes": "Pendiente para el siguiente turno"})
                        source_cleaning.db_insert()
                        frappe.db.set_value("HS Room", room.name,
                            "cleaning_status", "Dirty")
                        source_ticket = frappe.get_doc({
                            "doctype": "HS Guest Ticket",
                            "name": "TICKET-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "room": room.name, "stay": source_stay.name,
                            "subject": "Pending request",
                            "description": "Carry to target PMS",
                            "category": "Guest Request", "priority": "High",
                            "status": "Open", "assigned_to": "Administrator",
                            "due_at": departure, "reopened_count": 0})
                        source_ticket.db_insert()
                        source_ticket_event = frappe.get_doc({
                            "doctype": "HS Ticket Event",
                            "name": "TICKET-EVENT-REVERSE-" +
                                frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "ticket": source_ticket.name, "kind": "Created",
                            "actor": "Administrator", "occurred_at": arrival,
                            "note": source_ticket.description})
                        source_ticket_event.db_insert()
                        source_pass = frappe.get_doc({
                            "doctype": "HS Day Pass",
                            "name": "PASS-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "customer": source_guest.customer, "people": 1,
                            "starts_at": arrival, "ends_at": departure,
                            "status": "Issued", "currency": "NIO",
                            "amount": "5"})
                        source_pass.db_insert()
                        block_start = str(today + timedelta(days=1)) + " 13:00:00"
                        block_end = str(today + timedelta(days=2)) + " 13:00:00"
                        source_block = frappe.get_doc({
                            "doctype": "HS Room Block",
                            "name": "BLOCK-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "room": room.name, "reason": "VIP Hold",
                            "starts_at": block_start, "ends_at": block_end,
                            "status": "Active", "created_by": "Administrator"})
                        source_block.db_insert()
                        source_block_allocation = frappe.get_doc({
                            "doctype": "HS Allocation",
                            "name": "BLOCK-ALLOC-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "room_block": source_block.name,
                            "category": category.name, "room": room.name,
                            "kind": "Room Block", "status": "Active",
                            "starts_at": block_start, "ends_at": block_end})
                        source_block_allocation.db_insert()
                        maintenance_start = str(today + timedelta(days=2)) + " 15:00:00"
                        maintenance_end = str(today + timedelta(days=3)) + " 15:00:00"
                        source_equipment = frappe.get_doc({
                            "doctype": "HS Equipment",
                            "name": "EQUIP-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "equipment_code": "AC-REVERSE", "label": "Equipo de prueba",
                            "room": room.name, "active": 1})
                        source_equipment.db_insert()
                        source_maintenance = frappe.get_doc({
                            "doctype": "HS Maintenance Order",
                            "name": "MAINT-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "room": room.name, "equipment": source_equipment.name,
                            "blocks_room": 1, "title": "Revisión pendiente",
                            "starts_at": maintenance_start,
                            "ends_at": maintenance_end, "kind": "Corrective",
                            "status": "Open", "assigned_to": "Administrator"})
                        source_maintenance.db_insert()
                        source_maintenance_allocation = frappe.get_doc({
                            "doctype": "HS Allocation",
                            "name": "MAINT-ALLOC-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "maintenance": source_maintenance.name,
                            "category": category.name, "room": room.name,
                            "kind": "Maintenance", "status": "Active",
                            "starts_at": maintenance_start,
                            "ends_at": maintenance_end})
                        source_maintenance_allocation.db_insert()
                        portal_experience = frappe.get_doc({
                            "doctype": "HS Experience",
                            "name": "EXPERIENCE-WEB-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "experience_name": "Experiencia solo web",
                            "experience_category": "Activity",
                            "item": experience_item.name, "active": 1})
                        portal_experience.db_insert()
                        portal_extras = canonical([{
                            "experience": portal_experience.name,
                            "quantity": 1}])
                        portal_quote = canonical({"experiences": [{
                            "experience": portal_experience.name,
                            "item": experience_item.name, "quantity": 1,
                            "rate": "8.00", "amount": "8.00"}]})
                        source_portal = frappe.get_doc({
                            "doctype": "HS Portal Request",
                            "name": "WEB-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "status": "Requested", "full_name": "Huésped web",
                            "category": category.name, "rooms": 1, "people": 1,
                            "mode": "Hotel", "starts_at": arrival,
                            "ends_at": departure, "currency": "NIO",
                            "amount": "20.00", "experiences": portal_extras,
                            "quote_snapshot": portal_quote})
                        source_portal.db_insert()
                        live_source = suite_api.erp_to_pms_preflight()
                        live_hotel = next(row for row in live_source["properties"]
                            if row["property"] == prop.name)
                        if (not any(row["name"] == source_stay.name and
                                row["rate"] == rate.name and
                                row["quote_snapshot"] == canonical(accepted_line)
                                for row in live_hotel["open_operations"]["stays"]) or
                                not any(row["parent"] == source_stay.name and
                                    row["guest"] == source_guest.name for row in
                                    live_hotel["open_operations"]["stay_guests"]) or
                                not any(row["name"] == source_service.name and
                                    row["item"] == item.name and
                                    row["status"] == "In Progress" for row in
                                    live_hotel["open_operations"]["service_requests"]) or
                                not any(row["name"] == source_cleaning.name and
                                    row["room"] == room.name and
                                    row["room_cleaning_status"] == "Dirty" and
                                    row["checklist_sha256"] == sha256(
                                        cleaning_checklist.encode()).hexdigest()
                                    for row in live_hotel["open_operations"]
                                        ["cleaning_tasks"]) or
                                any(row.get("code") == "unsupported_live_operation"
                                    and row.get("doctype") == "HS Cleaning Task"
                                    for row in live_source["blockers"]) or
                                not any(row["name"] == item.name for row in
                                    live_hotel["mapping_requirements"]["products"]) or
                                not any(row["name"] == source_ticket.name and
                                    row["room"] == room.name and
                                    row["stay"] == source_stay.name for row in
                                    live_hotel["open_operations"]["guest_tickets"]) or
                                not any(row["name"] == source_ticket_event.name and
                                    row["ticket"] == source_ticket.name and
                                    row["actor"] == "Administrator" for row in
                                    live_hotel["open_operations"]["ticket_events"]) or
                                any(row.get("code") == "unsupported_live_operation"
                                    and row.get("doctype") == "HS Guest Ticket"
                                    for row in live_source["blockers"]) or
                                not any(row.get("code") ==
                                    "invalid_active_day_pass_financial_graph" and
                                    row.get("source") == source_pass.name
                                    for row in live_source["blockers"]) or
                                not any(row["name"] == source_block.name and
                                    row["created_by"] == "Administrator" for row in
                                    live_hotel["open_operations"]["room_blocks"]) or
                                not any(row["room_block"] == source_block.name for
                                    row in live_hotel["open_operations"]["allocations"]) or
                                not any(row["name"] == source_maintenance.name and
                                    row["equipment"] == source_equipment.name for row in
                                    live_hotel["open_operations"]["maintenance_orders"]) or
                                not any(row["maintenance"] == source_maintenance.name
                                    for row in live_hotel["open_operations"]["allocations"]) or
                                not any(row["name"] == source_equipment.name for row in
                                    live_hotel["mapping_requirements"]["equipment"]) or
                                not any(row["name"] == source_laundry.name and
                                    row["stay"] == source_stay.name and
                                    row["status"] == "Ready" for row in
                                    live_hotel["open_operations"]["laundry_orders"]) or
                                not any(row["name"] == source_laundry_item.name and
                                    row["item"] == experience_item.name and
                                    row["laundry_rate"] == laundry_rate.name
                                    for row in live_hotel["open_operations"]
                                        ["laundry_items"]) or
                                not any(row["name"] == laundry_rate.name and
                                    row["item"] == experience_item.name for
                                    row in live_hotel["mapping_requirements"]
                                        ["laundry_rates"]) or
                                any(row.get("code") == "unsupported_live_operation"
                                    and row.get("doctype") == "HS Laundry Order"
                                    for row in live_source["blockers"]) or
                                not any(row["name"] == portal_experience.name and
                                    row["item"] == experience_item.name for row in
                                    live_hotel["mapping_requirements"]["experiences"]) or
                                not any(row["name"] == source_portal.name and
                                    row["experiences"] == portal_extras and
                                    row["experiences_sha256"] == sha256(
                                        portal_extras.encode()).hexdigest() and
                                    row["quote_snapshot_sha256"] == sha256(
                                        portal_quote.encode()).hexdigest() for row in
                                    live_hotel["open_operations"]["portal_requests"]) or
                                not any(row["name"] == "Administrator" for row in
                                    live_hotel["mapping_requirements"]["users"])):
                            frappe.throw("Reverse inventory missed live guest work")
                        frappe.db.set_value("HS Ticket Event",
                            source_ticket_event.name, "property", "HOTEL-AJENO")
                        foreign_ticket_event = suite_api.erp_to_pms_preflight()
                        if not any(row.get("code") ==
                                "cross_property_ticket_event" and
                                row.get("source") == source_ticket.name
                                for row in foreign_ticket_event["blockers"]):
                            frappe.throw("Reverse inventory ignored an event from another hotel")
                        frappe.db.set_value("HS Ticket Event",
                            source_ticket_event.name, "property", prop.name)
                        frappe.db.set_value("HS Room", room.name,
                            "cleaning_status", "Clean")
                        inconsistent_cleaning = suite_api.erp_to_pms_preflight()
                        if not any(row.get("code") ==
                                "invalid_open_cleaning_room_state" and
                                row.get("source") == source_cleaning.name
                                for row in inconsistent_cleaning["blockers"]):
                            frappe.throw("Reverse inventory accepted an inconsistent cleaning room")
                        frappe.db.set_value("HS Room", room.name,
                            "cleaning_status", "Dirty")
                        from hospitality_suite import inventory as service_inventory
                        if not frappe.db.exists("Stock Entry Type", "Material Issue"):
                            frappe.get_doc({"doctype": "Stock Entry Type",
                                "name": "Material Issue",
                                "purpose": "Material Issue"}).insert(ignore_permissions=True)
                        prop.reload()
                        delivered_entry = service_inventory.stock_movement(
                            prop, item.name, 1)
                        delivered_service = frappe.get_doc({
                            "doctype": "HS Service Request",
                            "name": "DELIVERED-REVERSE-" + frappe.generate_hash(length=10),
                            "property": prop.name, "company": target_company.name,
                            "stay": source_stay.name, "folio": source_folio.name,
                            "customer": source_folio.customer, "item": item.name,
                            "quantity": 1, "included": 1, "amount": "0",
                            "currency": source_folio.currency,
                            "status": "Delivered",
                            "stock_entry": delivered_entry.name})
                        delivered_service.db_insert()
                        delivered_preflight = suite_api.erp_to_pms_preflight()
                        delivered_hotel = next(row for row in
                            delivered_preflight["properties"] if row["property"] == prop.name)
                        if (not any(row["name"] == delivered_service.name and
                                row.get("source_stock_issue", {}).get("voucher") ==
                                    delivered_entry.name and
                                Decimal(str(row["source_stock_issue"]["cost"])) > 0
                                for row in delivered_hotel["open_operations"]
                                    ["service_requests"]) or
                                any(row.get("code") ==
                                    "invalid_delivered_service_stock_issue" and
                                    row.get("source") == delivered_service.name
                                    for row in delivered_preflight["blockers"])):
                            frappe.throw("Reverse inventory lost delivered stock cost")
                    finally:
                        frappe.db.rollback(save_point="hs_reverse_live_operation_probe")
                    fiscal_bundle = erp_fiscal_history.export_bundle(
                        reverse_source["source_sha256"])
                    fiscal_bundle_path = Path(frappe.get_site_path("private", "files",
                        fiscal_bundle["file_name"]))
                    with ZipFile(fiscal_bundle_path) as fiscal_zip:
                        fiscal_manifest, fiscal_inventory = (
                            erp_fiscal_history._manifest(fiscal_zip,
                                reverse_source["source_sha256"],
                                fiscal_bundle["manifest_sha256"]))
                        fiscal_sources = {(row["source_doctype"], row["source_name"])
                            for row in fiscal_manifest["documents"]}
                        if (fiscal_bundle["documents"] !=
                                len(fiscal_manifest["documents"]) or
                                fiscal_bundle["evidence"] != 2 or
                                len(fiscal_manifest["evidence"]) != 2 or
                                any(fiscal_zip.read("evidence/" + row[
                                    "source_key"]) != expected_bytes for
                                    row in fiscal_manifest["evidence"] for
                                    expected_doctype, expected_name, expected_bytes in [
                                        ("HS Incident", open_incident,
                                         incident_evidence_path.read_bytes()),
                                        ("HS Maintenance Order", reverse_maintenance,
                                         maintenance_evidence_path.read_bytes())]
                                    if row["source_doctype"] == expected_doctype and
                                    row["source_name"] == expected_name) or
                                fiscal_manifest["inventory_sha256"] !=
                                    reverse_source["source_sha256"] or
                                canonical(fiscal_inventory["properties"]) !=
                                    canonical(reverse_source["properties"]) or
                                ("HS PMS Fiscal Document",
                                 historical_fiscal["document"]) not in fiscal_sources or
                                not any(row[0] == "Sales Invoice" for row in
                                        fiscal_sources) or
                                any(not fiscal_zip.read("pdf/" +
                                    row["source_key"] + ".pdf").startswith(b"%PDF")
                                    for row in fiscal_manifest["documents"])):
                            frappe.throw("The reverse fiscal package lost a printable source")
                    frappe.db.savepoint("hs_reverse_source_incident_probe")
                    try:
                        frappe.db.set_value("HS Incident", open_incident,
                            "evidence", "/private/files/source-evidence.png",
                            update_modified=False)
                        altered = suite_api.erp_to_pms_preflight()
                        if not any(row["code"] ==
                                "invalid_open_incident_evidence" and
                                row["source"] == open_incident for row in
                                altered["blockers"]):
                            frappe.throw("Reverse inventory omitted incident evidence")
                    finally:
                        frappe.db.rollback(save_point="hs_reverse_source_incident_probe")
                    original_evidence = incident_evidence_path.read_bytes()
                    try:
                        incident_evidence_path.write_bytes(
                            original_evidence + b" ALTERADO")
                        altered = suite_api.erp_to_pms_preflight()
                        if altered["source_sha256"] == reverse_source[
                                "source_sha256"]:
                            frappe.throw("Reverse inventory missed changed evidence bytes")
                    finally:
                        incident_evidence_path.write_bytes(original_evidence)
                    frappe.db.savepoint("hs_reverse_source_stock_probe")
                    try:
                        bin_name = frappe.db.get_value("Bin", {
                            "item_code": item.name,
                            "warehouse": target_warehouse}, "name")
                        frappe.db.set_value("Bin", bin_name, "actual_qty", 0,
                                            update_modified=False)
                        altered = suite_api.erp_to_pms_preflight()
                        if (altered["source_sha256"] == reverse_source["source_sha256"] or
                                not any(row["code"] == "stock_value_without_quantity" and
                                    row["item"] == item.name for row in altered["blockers"])):
                            frappe.throw("Reverse inventory missed a changed stock valuation")
                    finally:
                        frappe.db.rollback(save_point="hs_reverse_source_stock_probe")
                    frappe.db.savepoint("hs_reverse_source_booking_probe")
                    try:
                        frappe.db.set_value("HS Booking Room", booking_line.name,
                            "people", 2, update_modified=False)
                        if (suite_api.erp_to_pms_preflight()["source_sha256"] ==
                                reverse_source["source_sha256"]):
                            frappe.throw("Reverse inventory missed a changed booking room")
                    finally:
                        frappe.db.rollback(save_point="hs_reverse_source_booking_probe")
                    frappe.db.savepoint("hs_reverse_source_fiscal_probe")
                    try:
                        archived_invoice = reverse_hotel["fiscal_history"]["native_documents"][0]["name"]
                        archived_line = frappe.db.get_value("Sales Invoice Item",
                            {"parent": archived_invoice}, "name")
                        if not archived_line:
                            frappe.throw("Reverse inventory omitted native fiscal lines")
                        frappe.db.set_value("Sales Invoice Item", archived_line,
                            "description", "Changed archival line " + suffix,
                            update_modified=False)
                        if (suite_api.erp_to_pms_preflight()["source_sha256"] ==
                                reverse_source["source_sha256"]):
                            frappe.throw("Reverse inventory missed a changed fiscal line")
                    finally:
                        frappe.db.rollback(save_point="hs_reverse_source_fiscal_probe")
                    continued_linen = suite_api.linen_board(prop.name, "Receive")
                    if (not continued_linen["configured"] or
                            not any(row["name"] == item.name and
                                    Decimal(str(row["quantity"])) == 1
                                    for row in continued_linen["products"]) or
                            not any(row["name"] == linen_transfer["incident"] and
                                    row["linen_direction"] == "Send" and
                                    row["item"] == item.name and
                                    row["stock_entry"] == linen_transfer["stock_entry"]
                                    for row in continued_linen["history"])):
                        frappe.throw("ERPNext cannot review the historical linen transfer")
                    first = frappe.parse_json(frappe.db.get_value(
                        "HS Cutover Run", cli_result["cutover_run"],
                        "result_json"))
            historical_result = first["properties"][0]
            frappe.db.savepoint("hs_cutover_transfer_account_probe")
            try:
                from hospitality_suite.install import validate_financial_configuration
                frappe.db.set_value("HS Property", prop.name,
                    "cash_transfer_account", target_liability.name,
                    update_modified=False)
                try:
                    validate_financial_configuration(
                        frappe.get_doc("HS Property", prop.name))
                except frappe.ValidationError as exc:
                    if "cuenta de traslado" not in str(exc):
                        raise
                else:
                    frappe.throw("ERPNext accepted a liability for cash transfer")
            finally:
                frappe.db.rollback(save_point="hs_cutover_transfer_account_probe")
            frappe.db.savepoint("hs_cutover_disabled_petty_account_probe")
            try:
                frappe.db.set_value("Account", target_petty.name, "disabled", 1,
                    update_modified=False)
                prop.reload()
                try:
                    with operation(prop):
                        prop.save(ignore_permissions=True)
                except frappe.ValidationError as exc:
                    if "cuenta debe estar habilitada" not in str(exc):
                        raise
                else:
                    frappe.throw("ERPNext accepted a disabled petty cash account")
            finally:
                frappe.db.rollback(save_point="hs_cutover_disabled_petty_account_probe")
                prop.reload()
            if (frappe.db.get_value("HS Property", prop.name, "invoice_print_format") or
                    frappe.db.get_value("HS Property", prop.name, "receipt_print_format")):
                frappe.throw("Legacy pseudo print formats survived ERPNext activation")
            profit_loss_voucher = historical_result["profit_loss_transfer_journal"]
            opening_voucher = historical_result["residual_journal"]
            if (not profit_loss_voucher or not opening_voucher or
                    frappe.db.get_value("Journal Entry", profit_loss_voucher,
                                        "is_opening") != "No" or
                    frappe.db.get_value("Journal Entry", opening_voucher,
                                        "is_opening") != "Yes"):
                frappe.throw("PMS historical results were posted as an opening entry")
            frappe.local.hs_cutover_rehearsal = True
            from hospitality_suite import api as suite_api
            operational = suite_api.bootstrap(prop.name)
            migrated_order = first["properties"][0]["purchase_orders"][0]
            native_order = frappe.get_doc("Purchase Order", migrated_order)
            if (native_order.docstatus != 1 or
                    native_order.supplier != supplier.name or
                    Decimal(str(native_order.grand_total)) != Decimal("12") or
                    Decimal(str(native_order.total_taxes_and_charges)) !=
                        Decimal("2") or
                    len(native_order.items) != 1 or
                    Decimal(str(native_order.items[0].qty)) != Decimal("2")):
                frappe.throw("The approved PMS order did not reach native purchasing")
            frappe.db.savepoint("hs_cutover_purchase_receipt_probe")
            try:
                purchase_board = suite_api.erp_purchases_snapshot(prop.name)
                if (not any(row["name"] == supplier.name for row in
                            purchase_board["suppliers"]) or
                        not any(row["name"] == native_order.name and
                                row["items"] and
                                row["items"][0]["name"] == native_order.items[0].name
                                for row in purchase_board["orders"])):
                    frappe.throw("Migrated ERPNext purchases are not available in React")
                found_order = suite_api.erp_purchase_search(prop.name,
                    "orders", native_order.name)
                if not any(row["name"] == native_order.name and row["items"]
                           for row in found_order["rows"]):
                    frappe.throw("Migrated purchase order cannot be searched")
                receipt_data = {"order": native_order.name,
                    "items": [{"order_item": native_order.items[0].name,
                               "quantity": "1"}],
                    "reason": "Recepción parcial tras el corte"}
                received = suite_api.execute(prop.name, "receive_purchase",
                    "cutover-receive-purchase-" + suffix, receipt_data)
                if suite_api.execute(prop.name, "receive_purchase",
                        "cutover-receive-purchase-" + suffix,
                        receipt_data) != received:
                    frappe.throw("Retrying an ERP purchase receipt duplicated stock")
                native_receipt = frappe.get_doc("Purchase Receipt",
                    received["receipt"])
                if (native_receipt.docstatus != 1 or
                        Decimal(str(native_receipt.grand_total)) != Decimal("6") or
                        Decimal(str(native_receipt.total_taxes_and_charges)) !=
                            Decimal("1") or
                        Decimal(str(native_receipt.items[0].qty)) != Decimal("1")):
                    frappe.throw("A partial ERP receipt lost the approved tax split: " +
                        frappe.as_json({"grand_total": native_receipt.grand_total,
                            "tax": native_receipt.total_taxes_and_charges,
                            "qty": native_receipt.items[0].qty,
                            "tax_rows": [dict(charge_type=row.charge_type,
                                tax_amount=row.tax_amount) for row in
                                native_receipt.taxes]}))
                if not any(row["name"] == native_receipt.name for row in
                           suite_api.erp_purchases_snapshot(prop.name)["receipts"]):
                    frappe.throw("ERPNext receipt is not billable in React")
                if not any(row["name"] == native_receipt.name for row in
                           suite_api.erp_purchase_search(prop.name, "receipts",
                               native_receipt.name)["rows"]):
                    frappe.throw("ERPNext receipt cannot be searched")
                billed_purchase = suite_api.execute(prop.name,
                    "purchase_invoice", "cutover-bill-purchase-" + suffix,
                    {"receipt": native_receipt.name,
                     "bill_no": "BILL-CUTOVER-" + suffix,
                     "bill_date": str(today),
                     "reason": "Facturar recepción tras el corte"})
                native_bill = frappe.get_doc("Purchase Invoice",
                    billed_purchase["invoice"])
                if (native_bill.docstatus != 1 or
                        Decimal(str(native_bill.grand_total)) != Decimal("6") or
                        Decimal(str(native_bill.outstanding_amount)) != Decimal("6") or
                        Decimal(str(native_bill.total_taxes_and_charges)) !=
                            Decimal("1")):
                    frappe.throw("The migrated order could not be partially billed")
                if not any(row["name"] == native_bill.name and
                           Decimal(str(row["outstanding_amount"])) == 6 for row in
                           suite_api.erp_purchases_snapshot(prop.name)["invoices"]):
                    frappe.throw("ERPNext supplier balance is not payable in React")
                if not any(row["name"] == native_bill.name for row in
                           suite_api.erp_purchase_search(prop.name, "invoices",
                               native_bill.bill_no)["rows"]):
                    frappe.throw("Supplier invoice cannot be found by bill number")
                supplier_shift = suite_api.execute(prop.name,
                    "open_shift", "cutover-supplier-shift-" + suffix,
                    {"currency": "NIO", "opening_amount": "10"})
                payment_data = {"invoice": native_bill.name,
                    "method": cash_method.name, "shift": supplier_shift["shift"],
                    "amount": "6", "reason": "Pago de prueba"}
                payment_quote = suite_api.preview(prop.name, payment_data,
                    "supplier_payment")
                supplier_paid = suite_api.execute(prop.name,
                    "supplier_payment", "cutover-supplier-pay-" + suffix,
                    {**payment_data,
                     "acceptance": payment_quote["acceptance"]})
                if (suite_api.execute(prop.name, "supplier_payment",
                        "cutover-supplier-pay-" + suffix,
                        {**payment_data,
                         "acceptance": payment_quote["acceptance"]}) != supplier_paid or
                        Decimal(str(frappe.db.get_value("Purchase Invoice",
                            native_bill.name, "outstanding_amount"))) != 0 or
                        any(row["name"] == native_bill.name for row in
                            suite_api.erp_purchases_snapshot(prop.name)["invoices"])):
                    frappe.throw("ERPNext supplier payment failed in React")
                final_receipt = suite_api.execute(prop.name,
                    "receive_purchase", "cutover-final-purchase-" + suffix,
                    receipt_data)
                final_doc = frappe.get_doc("Purchase Receipt",
                    final_receipt["receipt"])
                if (final_doc.docstatus != 1 or
                        Decimal(str(final_doc.grand_total)) != Decimal("6") or
                        Decimal(str(final_doc.total_taxes_and_charges)) !=
                            Decimal("1") or
                        Decimal(str(frappe.db.get_value("Purchase Order",
                            native_order.name, "per_received"))) != Decimal("100")):
                    frappe.throw("The final receipt repeated or lost fixed tax")
            finally:
                frappe.db.rollback(save_point="hs_cutover_purchase_receipt_probe")
            frappe.db.savepoint("hs_cutover_new_purchase_probe")
            try:
                if not frappe.db.exists("Supplier Group", "All Supplier Groups"):
                    frappe.get_doc({"doctype": "Supplier Group",
                        "supplier_group_name": "All Supplier Groups",
                        "is_group": 1}).insert(ignore_permissions=True)
                if not frappe.db.exists("Supplier Group", "HS Cutover Suppliers"):
                    frappe.get_doc({"doctype": "Supplier Group",
                        "supplier_group_name": "HS Cutover Suppliers",
                        "parent_supplier_group": "All Supplier Groups",
                        "is_group": 0}).insert(ignore_permissions=True)
                registered = suite_api.execute(prop.name,
                    "register_supplier", "cutover-new-supplier-" + suffix,
                    {"supplier_name": "Proveedor nuevo " + suffix})
                order_data = {"supplier": registered["supplier"],
                    "warehouse": target_warehouse,
                    "reason": "Compra nueva tras el corte",
                    "items": [{"item": item.name, "quantity": 1,
                               "rate": "5.00"}]}
                order_quote = suite_api.preview(prop.name, order_data,
                    "purchase_order")
                new_order = suite_api.execute(prop.name, "purchase_order",
                    "cutover-new-order-" + suffix,
                    {**order_data, "acceptance": order_quote["acceptance"]})
                new_board = suite_api.erp_purchases_snapshot(prop.name)
                if (not any(row["name"] == registered["supplier"]
                            for row in new_board["suppliers"]) or
                        not any(row["name"] == new_order["order"] and
                                row["supplier"] == registered["supplier"]
                                for row in new_board["orders"])):
                    frappe.throw("New ERPNext purchase is not available in React")
                first_page = suite_api.erp_purchase_search(prop.name,
                    "orders", "", 0, 1)
                second_page = suite_api.erp_purchase_search(prop.name,
                    "orders", "", 1, 1)
                by_supplier = suite_api.erp_purchase_search(prop.name,
                    "orders", "Proveedor nuevo " + suffix)
                if (not first_page["has_more"] or
                        not second_page["rows"] or
                        first_page["rows"][0]["name"] ==
                            second_page["rows"][0]["name"] or
                        not any(row["name"] == new_order["order"]
                                for row in by_supplier["rows"])):
                    frappe.throw("Purchase search or pagination lost older orders")
            finally:
                frappe.db.rollback(save_point="hs_cutover_new_purchase_probe")
            if (operational["accounting_provider"] != "erpnext" or
                    not any(row.name == prop.name and row.company == target_company.name
                            for row in operational["properties"]) or
                    not any(row.name == folio.name and row.customer == customer.name
                            for row in operational["folios"])):
                frappe.throw("The ERPNext operational dashboard lost migrated hotel links")
            availability_options = suite_api.availability_options(prop.name)
            if (availability_options["property"] != prop.name or
                    availability_options["time_zone"] != prop.time_zone or
                    len(availability_options["categories"]) != frappe.db.count(
                        "HS Category", {"property": prop.name})):
                frappe.throw("The ERPNext availability picker lost hotel categories")
            rate_calendar = suite_api.rate_calendar(prop.name, category.name,
                str(today + timedelta(days=2)), days=1, mode="Hotel")
            if (not rate_calendar["read_only"] or
                    rate_calendar["rows"][0]["rate"] != rate.name or
                    rate_calendar["rows"][0]["amount"] is None):
                frappe.throw("The ERPNext rate calendar lost the migrated rate")
            room_calendar = suite_api.room_calendar(prop.name, str(today), "week")
            if (not room_calendar["read_only"] or
                    not any(row["name"] == room.name for row in room_calendar["rooms"]) or
                    not any(row["booking"] == booking.name for row in
                            room_calendar["allocations"])):
                frappe.throw("The ERPNext room calendar lost the migrated reservation")
            reservation_page = suite_api.reservation_page(prop.name, "current", booking.name)
            if (not reservation_page["rows"] or
                    reservation_page["rows"][0]["name"] != booking.name):
                frappe.throw("The ERPNext reservation list lost the migrated booking")
            booking_workflow = suite_api.booking_detail(booking.name)
            if (booking_workflow["workflow"]["name"] != booking.name or
                    booking_workflow["workflow"]["customer"] != customer.name or
                    not booking_workflow["workflow"]["starts_at_local"] or
                    not booking_workflow["workflow"]["rooms"] or
                    not any(row["booking"] == booking.name for row in
                            booking_workflow["allocations"])):
                frappe.throw("The ERPNext reservation workflow lost its mapped booking")
            reservation_print = frappe.get_print("HS Booking", booking.name,
                print_format="HS Confirmación de reserva")
            if ("CONFIRMACIÓN DE RESERVA" not in reservation_print or
                    frappe.db.get_value("Customer", customer.name,
                        "customer_name") not in reservation_print):
                frappe.throw("The ERPNext booking print lost its mapped customer")
            frappe.db.savepoint("hs_cutover_react_draft_probe")
            try:
                draft_values = {"mode": "Hotel", "customer": customer.name,
                    "channel": "Recepción React"}
                draft = suite_api.execute(prop.name, "save_booking_draft",
                    "cutover-react-draft-" + suffix, {"values": draft_values})
                if (suite_api.reservation_page(prop.name, "draft",
                        draft["booking"])["rows"][0]["customer"] != customer.name or
                        suite_api.booking_detail(draft["booking"])["draft"]["customer"] != customer.name):
                    frappe.throw("The ERPNext draft list lost the property customer")
            finally:
                frappe.db.rollback(save_point="hs_cutover_react_draft_probe")
            room_schedule = suite_api.room_schedule(prop.name, room.name,
                str(today) + "T00:00:00",
                str(today + timedelta(days=7)) + "T00:00:00")
            room_history = suite_api.room_history(prop.name, room.name,
                str(today) + "T00:00:00",
                str(today + timedelta(days=7)) + "T00:00:00", "periods")
            room_insights = suite_api.room_insights(prop.name, 7)
            if (not any(row["booking"] == booking.name for row in room_schedule["rows"]) or
                    not any(row["kind"] == "period" for row in room_history["rows"]) or
                    not any(row["room"] == room.name for row in room_insights["rooms"])):
                frappe.throw("The ERPNext room detail lost its schedule, history or insights")
            archived = suite_api.pms_fiscal_archive(prop.name, 0, 10,
                historical_fiscal["document_number"])
            printed_historical = frappe.get_print(
                "HS PMS Fiscal Document", historical_fiscal["document"],
                print_format="HS Documento fiscal PMS")
            if (archived["total"] != 1 or
                    archived["documents"][0]["name"] != historical_fiscal["document"] or
                    historical_fiscal["document_number"] not in printed_historical or
                    " · RUC" in printed_historical or
                    "<th>Referencia</th>" in printed_historical or
                    frappe.db.get_value("HS PMS Fiscal Document",
                        historical_fiscal["document"], "company") != target_company.name):
                frappe.throw("Historical fiscal printing did not survive cutover")
            credits = suite_api.erp_customer_credits_snapshot(prop.name)
            if not any(row["name"] == advance.name and
                       Decimal(row["available"]) == Decimal("12") for row in
                       credits["advances"]):
                frappe.throw("The ERPNext customer credit screen lost the migrated advance")
            searched_funds = suite_api.erp_customer_credits_snapshot(
                prop.name, advance_search=advance.name,
                guarantee_search=guarantee.name, funds_page_length=1)
            if (len(searched_funds["advances"]) != 1 or
                    searched_funds["advances"][0]["name"] != advance.name or
                    len(searched_funds["guarantees"]) != 1 or
                    searched_funds["guarantees"][0]["name"] != guarantee.name or
                    searched_funds["advance_page"]["has_more"] or
                    searched_funds["guarantee_page"]["has_more"]):
                frappe.throw("React Caja cannot search migrated funds by payment ID")
            missing_funds = suite_api.erp_customer_credits_snapshot(
                prop.name, advance_search="absent-" + suffix,
                guarantee_search="absent-" + suffix)
            if missing_funds["advances"] or missing_funds["guarantees"]:
                frappe.throw("The fund search included unrelated movements")
            from hospitality_suite.accounting import guarantee_balance
            from hospitality_suite.refunds import balance as refund_balance, plan as refund_plan
            migrated_property = frappe.get_doc("HS Property", prop.name)
            translated_booking = frappe.parse_json(frappe.db.get_value(
                "HS Booking", booking.name, "quote_snapshot"))
            translated_allocation = frappe.parse_json(frappe.db.get_value(
                "HS Allocation", reservation.name, "quote_snapshot"))
            from hospitality_suite.item_configuration import bound_item
            if (translated_booking["lines"][0]["charge_items"]["lodging_item"] != lodging_item.name or
                    translated_booking["lines"][0]["amount"] != "20.00" or
                    translated_booking["experiences"][0]["item"] != experience_item.name or
                    translated_booking["experiences"][0]["pms_product"] is not None or
                    translated_allocation["charge_items"]["lodging_item"] != lodging_item.name or
                    bound_item(migrated_property, translated_booking["lines"][0],
                               "lodging_item") != lodging_item.name or
                    frappe.db.get_value("HS Experience", experience.name,
                                        "item") != experience_item.name or
                    frappe.db.get_value("HS Experience Order", experience_order.name,
                                        "item") != experience_item.name or
                    frappe.db.get_value("HS Laundry Rate", laundry_rate.name,
                                        "item") != experience_item.name or
                    frappe.db.get_value("HS Travel Agent", travel_agent.name,
                                        "supplier") != supplier.name or
                    not frappe.db.exists("HS Supplier", {"property": prop.name,
                        "supplier": supplier.name, "active": 1}) or
                    first["links"].get("snapshot_rows_updated") != 2 or
                    first["links"].get("experience_rows_updated") != 2 or
                    first["links"].get("laundry_rows_updated") != 1 or
                    first["links"].get("agent_rows_updated") != 1 or
                    first["links"].get("billing_parties_created") != 1):
                frappe.throw("The accepted room quote kept PMS product identifiers")
            billing_party = frappe.db.get_value("HS Billing Party", {
                "property": prop.name, "customer": customer.name},
                ["company", "credit_authorized", "credit_limit",
                 "credit_days", "valid_until", "reason"], as_dict=True)
            ticket_board = suite_api.ticket_board(prop.name, "open")
            if (not any(row["name"] == legacy_ticket["ticket"] and
                        row["room"] == room.name for row in ticket_board["rows"]) or
                    frappe.db.get_value("HS Guest Ticket", legacy_ticket["ticket"],
                                        "company") != target_company.name):
                frappe.throw("The PMS ticket was not available after cutover")
            ticket_detail = suite_api.ticket_detail(legacy_ticket["ticket"])
            if (ticket_detail["ticket"]["status"] != "Open" or
                    [row["kind"] for row in ticket_detail["events"]] != ["Created"]):
                frappe.throw("The migrated ticket lost its history")
            completed_ticket = suite_api.execute(prop.name, "ticket",
                "cutover-ticket-resolve-" + suffix,
                {"kind": "resolve", "ticket": legacy_ticket["ticket"],
                 "modified": str(ticket_detail["ticket"]["modified"]),
                 "resolution": "Seguimiento completado tras el corte"})
            if (completed_ticket["status"] != "Resolved" or
                    not any(row["name"] == legacy_ticket["ticket"] for row in
                            suite_api.ticket_board(prop.name, "resolved")["rows"]) or
                    [row["kind"] for row in
                     suite_api.ticket_detail(legacy_ticket["ticket"])["events"]] !=
                    ["Created", "Resolved"]):
                frappe.throw("The migrated ticket could not be resolved in ERPNext")
            configured = suite_api.setup_board(prop.name)
            if (configured["property"]["company"] != target_company.name or
                    not any(row["name"] == room.name for row in configured["rooms"]) or
                    not any(row["name"] == rate.name for row in configured["rates"])):
                frappe.throw("React setup lost migrated rooms or rates")
            frappe.db.savepoint("hs_cutover_react_setup_probe")
            try:
                new_category = suite_api.save_setup(prop.name, "category",
                    {"category_name": "Categoría React " + suffix,
                     "capacity": 2}, "cutover-react-category-" + suffix)["name"]
                new_room = suite_api.save_setup(prop.name, "room",
                    {"room_number": "REACT-" + suffix,
                     "category": new_category, "beds": 1, "active": 1},
                    "cutover-react-room-" + suffix)["name"]
                new_rate = suite_api.save_setup(prop.name, "rate",
                    {"title": "Tarifa React " + suffix,
                     "category": new_category, "mode": "Hotel",
                     "currency": "NIO", "amount": 20, "active": 1},
                    "cutover-react-rate-" + suffix)["name"]
                updated_setup = suite_api.setup_board(prop.name)
                if (not any(row["name"] == new_category for row in
                            updated_setup["categories"]) or
                        not any(row["name"] == new_room for row in
                                updated_setup["rooms"]) or
                        not any(row["name"] == new_rate for row in
                                updated_setup["rates"])):
                    frappe.throw("React setup could not add ERPNext masters")
                onboarding = suite_api.onboarding_options()
                if (onboarding["provider"] != "erpnext" or
                        not any(row["name"] == target_company.name for row in
                                onboarding["companies"])):
                    frappe.throw("ERPNext onboarding cannot select its company")
                new_property_data = {"property_name": "Nuevo ERP React " + suffix,
                    "company": target_company.name, "currency": "NIO",
                    "mode": "Mixed", "time_zone": "America/Managua",
                    "close_time": "06:00"}
                new_property = suite_api.create_property(new_property_data,
                    "cutover-react-new-property-" + suffix)
                if (suite_api.create_property(new_property_data,
                        "cutover-react-new-property-" + suffix) != new_property or
                        frappe.db.get_value("HS Property", new_property["property"],
                            "company") != target_company.name):
                    frappe.throw("ERPNext onboarding was not idempotent")
            finally:
                frappe.db.rollback(save_point="hs_cutover_react_setup_probe")
            if (not billing_party or billing_party.company != target_company.name or
                    not billing_party.credit_authorized or
                    Decimal(str(billing_party.credit_limit)) != Decimal("200") or
                    billing_party.credit_days != 10 or
                    str(billing_party.valid_until) !=
                    str(today + timedelta(days=30)) or
                    billing_party.reason != party.credit_reason):
                frappe.throw("The cutover lost the payer's approved credit terms")
            travel_board = suite_api.erp_travel_experiences_snapshot(prop.name)
            if (not any(row["name"] == travel_agent.name and
                        row["supplier"] == supplier.name
                        for row in travel_board["agents"]) or
                    not any(row["name"] == experience.name and
                            row["item"] == experience_item.name
                            for row in travel_board["experiences"]) or
                    not any(row["name"] == supplier.name
                            for row in travel_board["suppliers"]) or
                    not any(row["name"] == experience_order.name
                            for row in travel_board["orders"]) or
                    not any(row["name"] == booking.name
                            for row in travel_board["bookings"])):
                frappe.throw("The ERPNext agencies screen lost migrated work")
            frappe.db.savepoint("hs_cutover_new_travel_setup_probe")
            try:
                new_agent = suite_api.execute(prop.name, "travel_agent",
                    "cutover-new-agent-" + suffix,
                    {"agent_name": "Agencia nueva tras corte", "agent_type": "OTA",
                     "commission_pct": "4", "supplier": supplier.name, "active": 1})
                new_experience = suite_api.execute(prop.name, "experience",
                    "cutover-new-experience-" + suffix,
                    {"experience_name": "Experiencia nueva tras corte",
                     "experience_category": "Tour", "item": experience_item.name,
                     "show_on_booking_page": 1, "active": 1})
                refreshed_travel = suite_api.erp_travel_experiences_snapshot(prop.name)
                if (not any(row["name"] == new_agent["agent"] and
                            row["supplier"] == supplier.name
                            for row in refreshed_travel["agents"]) or
                        not any(row["name"] == new_experience["experience"] and
                                row["item"] == experience_item.name
                                for row in refreshed_travel["experiences"])):
                    frappe.throw("New ERPNext agency or experience is not selectable")
            finally:
                frappe.db.rollback(save_point="hs_cutover_new_travel_setup_probe")
            created_guest = suite_api.create_guest(prop.name,
                {"full_name": "Guest after cutover " + suffix,
                 "customer": customer.name}, "cutover-guest-" + suffix)
            if frappe.db.get_value("HS Guest", created_guest["guest"],
                                   "customer") != customer.name:
                frappe.throw("The migrated payer cannot register a new guest")
            frappe.db.savepoint("hs_cutover_portal_request_probe")
            try:
                pending_web = suite_api.portal_request_queue(prop.name,
                    search=web_data["email"])
                if (pending_web["total"] != 1 or
                        pending_web["rows"][0]["name"] != source_request.name or
                        pending_web["rows"][0]["expired"] or
                        frappe.db.get_value("HS Portal Request",
                            source_request.name, "company") != target_company.name):
                    frappe.throw("The pending web request did not survive cutover")
                conversion = {"portal_request": source_request.name,
                    "guest": created_guest["guest"], "customer": customer.name}
                conversion_quote = suite_api.preview(prop.name, conversion,
                    "convert_portal")
                converted = suite_api.execute(prop.name, "convert_portal",
                    "cutover-convert-portal-" + suffix,
                    {**conversion, "acceptance": conversion_quote["acceptance"]})
                if (suite_api.execute(prop.name, "convert_portal",
                        "cutover-convert-portal-" + suffix,
                        {**conversion, "acceptance": conversion_quote["acceptance"]}) != converted or
                        frappe.db.get_value("HS Booking", converted["booking"],
                            "company") != target_company.name or
                        frappe.db.get_value("HS Portal Request",
                            source_request.name, "status") != "Converted" or
                        portal_service.confirmation(
                            web_confirmation["confirmation_url"].split("token=", 1)[1]
                        )["status"] != "Converted"):
                    frappe.throw("The pre-cutover web request could not be converted")
                pending_hold = suite_api.portal_request_queue(prop.name,
                    search=hold_data["email"])
                if (pending_hold["total"] != 1 or
                        pending_hold["rows"][0]["name"] != source_hold.name or
                        pending_hold["rows"][0]["expired"] or
                        frappe.db.count("HS Allocation", {
                            "portal_request": source_hold.name,
                            "company": target_company.name,
                            "status": "Active"}) != 1):
                    frappe.throw("The pre-cutover web hold lost its allocation")
                hold_conversion = {"portal_request": source_hold.name,
                    "guest": created_guest["guest"], "customer": customer.name}
                accepted_hold = suite_api.preview(prop.name, hold_conversion,
                    "convert_portal")
                converted_hold = suite_api.execute(prop.name, "convert_portal",
                    "cutover-convert-hold-" + suffix,
                    {**hold_conversion, "acceptance": accepted_hold["acceptance"]})
                if (suite_api.execute(prop.name, "convert_portal",
                        "cutover-convert-hold-" + suffix,
                        {**hold_conversion, "acceptance": accepted_hold["acceptance"]}) != converted_hold or
                        frappe.db.count("HS Allocation", {
                            "portal_request": source_hold.name,
                            "status": "Active"}) or
                        frappe.db.count("HS Allocation", {
                            "booking": converted_hold["booking"],
                            "company": target_company.name,
                            "status": "Active"}) != 1 or
                        portal_service.confirmation(
                            hold_confirmation["confirmation_url"].split("token=", 1)[1]
                        )["status"] != "Converted"):
                    frappe.throw("The pre-cutover hold was not converted exactly once")
            finally:
                frappe.db.rollback(save_point="hs_cutover_portal_request_probe")
            reception = suite_api.erp_reception_snapshot(prop.name)
            if (not any(row["name"] == customer.name for row in reception["parties"]) or
                    not any(row["name"] == created_guest["guest"] for row in reception["guests"]) or
                    not any(row["name"] == booking.name for row in reception["bookings"])):
                frappe.throw("The React reception lost migrated customers, guests or reservations")
            frappe.db.savepoint("hs_cutover_new_reception_guest_probe")
            try:
                fresh = suite_api.create_guest(prop.name,
                    {"full_name": "New reception guest " + suffix},
                    "cutover-reception-guest-" + suffix)
                refreshed = suite_api.erp_reception_snapshot(prop.name)
                if (not any(row["name"] == fresh["customer"]
                            for row in refreshed["parties"]) or
                        not any(row["name"] == fresh["guest"] and
                                row["customer"] == fresh["customer"]
                                for row in refreshed["guests"])):
                    frappe.throw("A new ERPNext reception payer is not selectable")
            finally:
                frappe.db.rollback(save_point="hs_cutover_new_reception_guest_probe")
            frappe.db.savepoint("hs_cutover_day_pass_probe")
            try:
                day_shift = suite_api.execute(prop.name, "open_shift",
                    "cutover-day-pass-shift-" + suffix,
                    {"currency": "NIO", "opening_amount": "0"})
                tomorrow = today + timedelta(days=1)
                day_data = {"customer": customer.name,
                    "guest": created_guest["guest"], "people": 2,
                    "starts_at": str(tomorrow) + "T09:00:00",
                    "ends_at": str(tomorrow) + "T17:00:00",
                    "method": cash_method.name, "shift": day_shift["shift"]}
                day_quote = suite_api.preview(prop.name, day_data,
                    "day_pass_no_room")
                day_board = suite_api.erp_day_pass_snapshot(prop.name)
                if (not day_board["item"] or
                        day_board["item"]["name"] != experience_item.name or
                        not any(row["name"] == customer.name
                                for row in day_board["customers"]) or
                        not any(row["name"] == cash_method.name
                                for row in day_board["methods"]) or
                        not any(row["name"] == day_shift["shift"]
                                for row in day_board["shifts"])):
                    frappe.throw("ERPNext Day Pass cannot be issued from React")
                issued_data = {**day_data,
                    "acceptance": day_quote["acceptance"]}
                issued = suite_api.execute(prop.name, "day_pass_no_room",
                    "cutover-day-pass-" + suffix, issued_data)
                if suite_api.execute(prop.name, "day_pass_no_room",
                        "cutover-day-pass-" + suffix,
                        issued_data) != issued:
                    frappe.throw("Retrying the Day Pass created a duplicate")
                sale_invoice = frappe.get_doc("Sales Invoice", issued["invoice"])
                receipt = frappe.get_doc("Payment Entry",
                    frappe.db.get_value("HS Payment", issued["payment"],
                                        "payment_entry"))
                day_pass = frappe.get_doc("HS Day Pass", issued["day_pass"])
                if (sale_invoice.docstatus != 1 or
                        sale_invoice.hs_property != prop.name or
                        sale_invoice.customer != customer.name or
                        sale_invoice.items[0].item_code != experience_item.name or
                        Decimal(str(sale_invoice.grand_total)) != Decimal("16") or
                        receipt.docstatus != 1 or
                        Decimal(str(receipt.received_amount)) != Decimal("16") or
                        day_pass.status != "Issued" or
                        day_pass.sales_invoice != sale_invoice.name or
                        day_pass.payment != issued["payment"]):
                    frappe.throw("Day Pass failed after the accounting cutover")
                active_inventory = suite_api.erp_to_pms_preflight()
                pass_rows = [row for hotel in active_inventory["properties"]
                    if hotel["property"] == prop.name for row in
                    hotel["open_operations"]["day_passes"]
                    if row["name"] == day_pass.name]
                if (len(pass_rows) != 1 or
                        not pass_rows[0].get("source_financial_sha256") or
                        pass_rows[0]["source_financial"]["invoice"] !=
                            sale_invoice.name or
                        pass_rows[0]["source_financial"]["payment"] !=
                            issued["payment"] or
                        not pass_rows[0]["source_financial"]["invoice_gl"] or
                        pass_rows[0]["source_financial"]["invoice_net"] != "16" or
                        pass_rows[0]["source_financial"]["invoice_tax"] != "0" or
                        any(row["code"] ==
                            "invalid_active_day_pass_financial_graph" and
                            row.get("source") == day_pass.name for row in
                            active_inventory["blockers"]) or
                        any(row["code"] == "unsupported_live_operation" and
                            row.get("doctype") == "HS Day Pass" for row in
                            active_inventory["blockers"])):
                    frappe.throw("Reverse inventory lost the paid Day Pass graph")
                frappe.db.savepoint("hs_reverse_day_pass_payment_probe")
                try:
                    frappe.db.set_value("HS Payment", issued["payment"],
                        "base_amount", "15", update_modified=False)
                    altered = suite_api.erp_to_pms_preflight()
                    if not any(row["code"] ==
                            "invalid_active_day_pass_financial_graph" and
                            row.get("source") == day_pass.name for row in
                            altered["blockers"]):
                        frappe.throw("Reverse inventory accepted an altered Day Pass payment")
                finally:
                    frappe.db.rollback(save_point="hs_reverse_day_pass_payment_probe")
                if (frappe.db.get_value("Company", target_company.name, "tax_id") or
                        sale_invoice.name not in frappe.get_print(
                            "Sales Invoice", sale_invoice.name)):
                    frappe.throw("ERPNext invoice printing required a seller tax ID")
                invoice_archive = suite_api.erp_fiscal_archive(prop.name,
                    search=sale_invoice.name)
                if (invoice_archive["total"] != 1 or
                        invoice_archive["documents"][0]["name"] != sale_invoice.name or
                        invoice_archive["documents"][0]["document_type"] != "Invoice" or
                        not invoice_archive["documents"][0]["can_print"]):
                    frappe.throw("ERPNext invoice is missing from the fiscal archive")
                cashier_user = "hs-fiscal-cashier-" + suffix + "@example.invalid"
                with patch("frappe.enqueue", return_value=None):
                    frappe.get_doc({"doctype": "User", "email": cashier_user,
                        "first_name": "Caja fiscal", "enabled": 1,
                        "send_welcome_email": 0,
                        "roles": [{"role": "HS Cashier"}]}).insert(
                            ignore_permissions=True)
                try:
                    frappe.set_user(cashier_user)
                    for read_document in (
                            lambda: suite_api.erp_fiscal_archive(prop.name),
                            lambda: suite_api.pms_fiscal_archive(prop.name),
                            lambda: frappe.get_print("Sales Invoice",
                                                     sale_invoice.name),
                            lambda: frappe.get_print(
                                "HS PMS Fiscal Document", historical_fiscal["document"],
                                print_format="HS Documento fiscal PMS")):
                        try:
                            read_document()
                        except frappe.PermissionError:
                            pass
                        else:
                            frappe.throw("A cashier without property access saw a fiscal document")
                finally:
                    frappe.set_user("Administrator")
                frappe.get_doc({"doctype": "HS Access", "user": cashier_user,
                    "company": target_company.name,
                    "property": prop.name}).insert(ignore_permissions=True)
                try:
                    frappe.set_user(cashier_user)
                    scoped_archive = suite_api.erp_fiscal_archive(prop.name,
                        search=sale_invoice.name)
                    historical_archive = suite_api.pms_fiscal_archive(prop.name,
                        search=historical_fiscal["document_number"])
                    if (scoped_archive["total"] != 1 or
                            sale_invoice.name not in frappe.get_print(
                                "Sales Invoice", sale_invoice.name) or
                            historical_archive["total"] != 1 or
                            historical_archive["documents"][0]["name"] !=
                                historical_fiscal["document"] or
                            historical_fiscal["document_number"] not in frappe.get_print(
                                "HS PMS Fiscal Document", historical_fiscal["document"],
                                print_format="HS Documento fiscal PMS")):
                        frappe.throw("Authorized cashier could not print the invoice")
                finally:
                    frappe.set_user("Administrator")
                issued_board = suite_api.erp_day_pass_snapshot(prop.name)
                if not any(row["name"] == issued["day_pass"] and
                           row["sales_invoice"] == issued["invoice"] and
                           row["can_return"] for row in issued_board["day_passes"]):
                    frappe.throw("Issued ERPNext Day Pass is missing from React")
                returned = suite_api.execute(prop.name, "return_direct_sale",
                    "cutover-day-pass-return-" + suffix,
                    {"service": issued["service"], "shift": day_shift["shift"],
                     "reason": "Reversión de prueba"})
                returned_board = suite_api.erp_day_pass_snapshot(prop.name)
                if (not returned["credit_note"] or
                        not returned["payment"] or
                        not any(row["name"] == issued["day_pass"] and
                                row["status"] == "Cancelled" and
                                not row["can_return"]
                                for row in returned_board["day_passes"])):
                    frappe.throw("ERPNext Day Pass return failed")
                if returned["credit_note"] not in frappe.get_print(
                        "Sales Invoice", returned["credit_note"]):
                    frappe.throw("ERPNext credit note could not be printed")
                credit_archive = suite_api.erp_fiscal_archive(prop.name,
                    search=returned["credit_note"], page_length=1)
                if (credit_archive["total"] != 1 or
                        credit_archive["documents"][0]["name"] != returned["credit_note"] or
                        credit_archive["documents"][0]["document_type"] != "Credit Note" or
                        credit_archive["documents"][0]["source_invoice"] != sale_invoice.name or
                        not credit_archive["documents"][0]["can_print"]):
                    frappe.throw("ERPNext credit note is missing from the fiscal archive")
                archive_first = suite_api.erp_fiscal_archive(prop.name,
                    page_length=1)
                archive_second = suite_api.erp_fiscal_archive(prop.name,
                    offset=1, page_length=1)
                if (archive_first["total"] < 2 or len(archive_second["documents"]) != 1 or
                        archive_first["documents"][0]["name"] ==
                            archive_second["documents"][0]["name"]):
                    frappe.throw("ERPNext fiscal archive pagination repeated a document")
                frappe.db.savepoint("hs_cancelled_fiscal_archive_probe")
                try:
                    frappe.db.set_single_value("Print Settings",
                        "allow_print_for_cancelled", 0)
                    frappe.clear_cache(doctype="Print Settings")
                    frappe.db.set_value("Sales Invoice", returned["credit_note"],
                        "docstatus", 2, update_modified=False)
                    cancelled_row = suite_api.erp_fiscal_archive(prop.name,
                        search=returned["credit_note"])["documents"][0]
                    expected_print = bool(frappe.db.get_single_value(
                        "Print Settings", "allow_print_for_cancelled"))
                    if (cancelled_row["status"] != "Cancelled" or
                            cancelled_row["can_print"] != expected_print):
                        frappe.throw("Cancelled print availability ignores Frappe settings")
                    cancelled_copy = erp_fiscal_history._pdf("Sales Invoice",
                        returned["credit_note"], "Cancelled")
                    if not cancelled_copy.startswith(b"%PDF"):
                        frappe.throw("A cancelled fiscal document lost its archival copy")
                finally:
                    frappe.db.rollback(save_point="hs_cancelled_fiscal_archive_probe")
                    frappe.clear_cache(doctype="Print Settings")
            finally:
                frappe.db.rollback(save_point="hs_cutover_day_pass_probe")
            checkin_data = {"booking": booking.name,
                "guest": created_guest["guest"],
                "modified": str(frappe.db.get_value(
                    "HS Booking", booking.name, "modified"))}
            timing_review = suite_api.preview(prop.name, checkin_data, "check_in")
            entered = suite_api.execute(prop.name, "check_in",
                "cutover-checkin-" + suffix,
                {**checkin_data, "timing_acceptance": timing_review["acceptance"]})
            stay_list = suite_api.stay_page(prop.name, "active", entered["stay"])
            stay_view = suite_api.stay_overview(prop.name, entered["stay"])
            stay_charges = suite_api.stay_charge_page(prop.name, entered["stay"])
            if (not stay_list["rows"] or
                    stay_list["rows"][0]["name"] != entered["stay"] or
                    stay_view["status"] != "Active" or
                    stay_view["folios"][0]["name"] != entered["folio"] or
                    not stay_charges["rows"]):
                frappe.throw("The ERPNext stay history lost the new check-in")
            departure_board = suite_api.erp_departure_snapshot(prop.name)
            departure_detail = suite_api.erp_departure_detail(
                prop.name, entered["stay"])
            if (not any(row["name"] == entered["stay"]
                        for row in departure_board["stays"]) or
                    not any(row["name"] == entered["folio"]
                            for row in departure_detail["folios"]) or
                    not any(row["payment"] == guarantee.name and
                            Decimal(str(row["available"])) == 15
                            for row in departure_detail["guarantees"])):
                frappe.throw("The ERPNext departure screen lost a stay, folio or guarantee")
            checkin_charge = frappe.db.get_value("HS Charge", {
                "folio": entered["folio"], "kind": "Lodging",
                "status": "Pending"}, ["name", "item", "amount"], as_dict=True)
            if (not checkin_charge or checkin_charge.item != lodging_item.name or
                    Decimal(str(checkin_charge.amount)) != Decimal("20")):
                frappe.throw("A migrated reservation cannot generate ERPNext lodging")
            frappe.db.savepoint("hs_cutover_confirmation_link_probe")
            try:
                frappe.db.set_value("HS Property", prop.name, "portal_enabled", 1,
                    update_modified=False)
                if not suite_api.erp_reception_snapshot(prop.name)["portal_enabled"]:
                    frappe.throw("ERPNext reception does not expose the portal state")
                from hospitality_suite import portal as portal_service
                signed = suite_api.execute(prop.name, "portal_link",
                    "cutover-confirmation-link-" + suffix,
                    {"booking": booking.name})
                if (signed != suite_api.execute(prop.name, "portal_link",
                        "cutover-confirmation-link-" + suffix,
                        {"booking": booking.name}) or
                        portal_service.confirmation(
                            signed["url"].split("token=", 1)[1])["status"] != "Checked In"):
                    frappe.throw("ERPNext confirmation link did not survive a retry")
            finally:
                frappe.db.rollback(save_point="hs_cutover_confirmation_link_probe")
            split_folio = suite_api.execute(prop.name, "create_folio",
                "cutover-split-folio-" + suffix, {
                    "stay": entered["stay"],
                    "customer": frappe.db.get_value("HS Folio", entered["folio"], "customer"),
                    "label": "Cuenta separada"})["folio"]
            pending_charges = suite_api.folio_pending_charges(prop.name,
                entered["folio"], 0, 25)
            if (not any(row["name"] == checkin_charge.name for row in
                    pending_charges["rows"]) or
                    split_folio not in [row["name"] for row in
                    suite_api.folio_transfer_targets(prop.name,
                        checkin_charge.name)["targets"]]):
                frappe.throw("ERPNext reception cannot list a pending charge and its target folio")
            moved_charge = {"charge": checkin_charge.name, "folio": split_folio,
                "reason": "Distribución del alojamiento"}
            moved_result = suite_api.execute(prop.name, "move_charge",
                "cutover-move-charge-" + suffix, moved_charge)
            if (moved_result != suite_api.execute(prop.name, "move_charge",
                    "cutover-move-charge-" + suffix, moved_charge) or
                    frappe.db.get_value("HS Charge", checkin_charge.name,
                        "folio") != split_folio):
                frappe.throw("ERPNext charge transfer is not idempotent")
            suite_api.execute(prop.name, "move_charge",
                "cutover-restore-charge-" + suffix, {
                    "charge": checkin_charge.name, "folio": entered["folio"],
                    "reason": "Restablecer la cuenta original"})
            frappe.db.savepoint("hs_cutover_inventory_probe")
            try:
                inventory_board = suite_api.erp_inventory_snapshot(prop.name)
                stock_before = suite_api.inventory_status(
                    prop.name, target_warehouse)
                stock_row = next((row for row in stock_before["items"]
                                  if row["item_code"] == item.name), None)
                if (not any(row["name"] == target_warehouse for row in
                            inventory_board["warehouses"]) or
                        not any(row["name"] == petty_category.name for row in
                                inventory_board["categories"]) or
                        not stock_row or
                        Decimal(str(stock_row["actual_qty"])) != 2):
                    frappe.throw("ERPNext inventory is not available in React")
                new_warehouse = suite_api.execute(prop.name,
                    "create_warehouse", "cutover-inventory-warehouse-" + suffix,
                    {"warehouse_name": "Destino corte " + suffix})["warehouse"]
                if not any(row["name"] == new_warehouse for row in
                           suite_api.erp_inventory_snapshot(prop.name)["warehouses"]):
                    frappe.throw("New ERPNext warehouse is not selectable")
                if not frappe.db.exists("Stock Entry Type", "Material Transfer"):
                    frappe.get_doc({"doctype": "Stock Entry Type",
                        "name": "Material Transfer", "purpose": "Material Transfer",
                        "is_standard": 1}).db_insert()
                movement_data = {"item": item.name,
                    "source_warehouse": target_warehouse,
                    "target_warehouse": new_warehouse,
                    "purpose": "Transfer", "quantity": 1,
                    "reason": "Traslado de prueba"}
                movement = suite_api.execute(prop.name, "move_stock",
                    "cutover-inventory-move-" + suffix, movement_data)
                if (suite_api.execute(prop.name, "move_stock",
                        "cutover-inventory-move-" + suffix,
                        movement_data) != movement or
                        Decimal(str(next(row["actual_qty"] for row in
                            suite_api.inventory_status(prop.name,
                                new_warehouse)["items"]
                            if row["item_code"] == item.name))) != 1):
                    frappe.throw("ERPNext stock transfer was not idempotent")
                count_data = {"item": item.name,
                    "warehouse": new_warehouse, "counted_quantity": 0}
                count_quote = suite_api.preview(prop.name, count_data,
                    "adjust_stock")
                counted = suite_api.execute(prop.name, "adjust_stock",
                    "cutover-inventory-count-" + suffix,
                    {**count_data, "category": petty_category.name,
                     "reason": "Conteo de prueba",
                     "acceptance": count_quote["acceptance"]})
                if (not counted["stock_reconciliation"] or
                        Decimal(str(next(row["actual_qty"] for row in
                            suite_api.inventory_status(prop.name,
                                new_warehouse)["items"]
                            if row["item_code"] == item.name))) != 0):
                    frappe.throw("ERPNext counted stock did not reconcile")
            finally:
                frappe.db.rollback(save_point="hs_cutover_inventory_probe")
            frappe.db.savepoint("hs_cutover_services_probe")
            try:
                services_board = suite_api.erp_service_snapshot(prop.name)
                if not any(row["name"] == entered["stay"] and
                           any(folio["name"] == entered["folio"]
                               for folio in row["folios"])
                           for row in services_board["stays"]):
                    frappe.throw("ERPNext guest services cannot select the migrated folio")
                service_data = {"stay": entered["stay"],
                    "folio": entered["folio"],
                    "item": experience_item.name, "quantity": 1,
                    "included": 0}
                service_quote = suite_api.preview(prop.name, service_data,
                    "request_service")
                if Decimal(service_quote["amount"]) != 8:
                    frappe.throw("ERPNext service review lost the active item price")
                requested_service = suite_api.execute(prop.name,
                    "request_service", "cutover-service-request-" + suffix,
                    {**service_data, "acceptance": service_quote["acceptance"]})
                service_name = requested_service["service"]
                if (Decimal(requested_service["amount"]) != 8 or
                        not any(row["name"] == service_name and
                                row["status"] == "Requested" for row in
                                suite_api.erp_service_snapshot(prop.name)["requests"])):
                    frappe.throw("New ERPNext guest service is not visible in React")
                delivered_service = suite_api.execute(prop.name,
                    "update_service", "cutover-service-deliver-" + suffix,
                    {"service": service_name, "status": "Delivered",
                     "modified": str(frappe.db.get_value(
                         "HS Service Request", service_name, "modified"))})
                if (delivered_service["status"] != "Delivered" or
                        not frappe.db.exists("HS Charge", {
                            "folio": entered["folio"],
                            "item": experience_item.name,
                            "amount": 8, "status": "Pending"})):
                    frappe.throw("ERPNext service delivery lost its folio charge")
                returned_service = suite_api.execute(prop.name,
                    "update_service", "cutover-service-return-" + suffix,
                    {"service": service_name, "status": "Returned",
                     "modified": str(frappe.db.get_value(
                         "HS Service Request", service_name, "modified")),
                     "reason": "Devolución de prueba"})
                if (returned_service["status"] != "Returned" or
                        not any(row["name"] == service_name and
                                row["status"] == "Returned" for row in
                                suite_api.erp_service_snapshot(prop.name)["requests"])):
                    frappe.throw("ERPNext service return is not visible in React")
            finally:
                frappe.db.rollback(save_point="hs_cutover_services_probe")
            frappe.db.savepoint("hs_cutover_laundry_probe")
            try:
                laundry_items = suite_api.catalog_search(
                    prop.name, experience_item.name, "laundry")
                laundry_board = suite_api.erp_laundry_snapshot(prop.name)
                if (not any(row["name"] == experience_item.name
                            for row in laundry_items["items"]) or
                        not any(row["name"] == laundry_rate.name and
                                row["item"] == experience_item.name
                                for row in laundry_board["rates"]) or
                        not any(row["name"] == entered["stay"]
                                for row in laundry_board["stays"])):
                    frappe.throw("The ERPNext laundry screen lost its item, rate or stay")
                new_laundry_rate = suite_api.execute(prop.name,
                    "laundry_rate", "cutover-laundry-rate-" + suffix,
                    {"garment": "Camisa tras corte", "service_type": "Wash & Iron",
                     "item": experience_item.name, "rate": "7.00", "active": 1})
                if not any(row["name"] == new_laundry_rate["rate"] and
                           row["item"] == experience_item.name for row in
                           suite_api.erp_laundry_snapshot(prop.name)["rates"]):
                    frappe.throw("A new ERPNext laundry rate is not selectable")
                requested_laundry = suite_api.execute(prop.name,
                    "laundry_request", "cutover-laundry-request-" + suffix,
                    {"stay": entered["stay"], "folio": entered["folio"]})
                laundry_name = requested_laundry["order"]
                if not any(row["name"] == laundry_name and
                           row["status"] == "Requested" for row in
                           suite_api.erp_laundry_snapshot(prop.name)["orders"]):
                    frappe.throw("The ERPNext laundry request is not visible in React")
                collected_laundry = suite_api.execute(prop.name,
                    "laundry_collect", "cutover-laundry-collect-" + suffix,
                    {"order": laundry_name,
                     "modified": str(frappe.db.get_value("HS Laundry Order",
                        laundry_name, "modified")),
                     "items": [{"rate": laundry_rate.name, "quantity": 1}]})
                if (collected_laundry["total"] != "6.00" or
                        frappe.db.get_value("HS Laundry Order Item", {
                            "parent": laundry_name}, "item") != experience_item.name):
                    frappe.throw("A migrated laundry rate lost its accepted ERP item")
                for status in ("In Process", "Ready"):
                    suite_api.execute(prop.name, "laundry_advance",
                        "cutover-laundry-" + status + suffix,
                        {"order": laundry_name, "status": status,
                         "modified": str(frappe.db.get_value("HS Laundry Order",
                            laundry_name, "modified"))})
                laundry_line = frappe.db.get_value("HS Laundry Order Item", {
                    "parent": laundry_name}, "name")
                suite_api.execute(prop.name, "laundry_return",
                    "cutover-laundry-return-" + suffix,
                    {"order": laundry_name,
                     "modified": str(frappe.db.get_value("HS Laundry Order",
                        laundry_name, "modified")),
                     "counts": {laundry_line: 1}})
                delivery_data = {"order": laundry_name,
                    "modified": str(frappe.db.get_value("HS Laundry Order",
                        laundry_name, "modified"))}
                delivered_laundry = suite_api.execute(prop.name,
                    "laundry_deliver", "cutover-laundry-deliver-" + suffix,
                    delivery_data)
                if (suite_api.execute(prop.name, "laundry_deliver",
                        "cutover-laundry-deliver-" + suffix,
                        delivery_data) != delivered_laundry or
                        Decimal(delivered_laundry["billed_total"]) != Decimal("6") or
                        not frappe.db.exists("HS Charge", {
                            "folio": entered["folio"],
                            "item": experience_item.name,
                            "amount": 6, "status": "Pending"})):
                    frappe.throw("ERPNext did not deliver migrated laundry once")
                if not any(row["name"] == laundry_name and
                           row["status"] == "Delivered" for row in
                           suite_api.erp_laundry_snapshot(prop.name)["orders"]):
                    frappe.throw("The ERPNext laundry delivery is not visible in React")
            finally:
                frappe.db.rollback(save_point="hs_cutover_laundry_probe")
            invoice = suite_api.execute(prop.name, "invoice",
                "cutover-invoice-" + suffix, {"folio": entered["folio"]})
            from hospitality_suite import erp_to_pms_preflight
            reverse_blockers = []
            reverse_invoice_rows = erp_to_pms_preflight._open_invoices(
                prop, "Sales Invoice", "customer", "debit_to", reverse_blockers)
            reverse_invoice = next((row for row in reverse_invoice_rows
                if row["name"] == invoice["invoice"]), None)
            if (reverse_blockers or not reverse_invoice or
                    reverse_invoice["folio"] != entered["folio"] or
                    reverse_invoice["stay"] != entered["stay"] or
                    Decimal(reverse_invoice.get("base_outstanding_amount", "0")) !=
                        Decimal(reverse_invoice["outstanding_amount"])):
                frappe.throw("El inventario inverso perdió el saldo o folio de la factura abierta")
            if (frappe.db.get_value("Sales Invoice", invoice["invoice"],
                    ["company", "customer", "docstatus"], as_dict=True) !=
                    {"company": target_company.name,
                     "customer": customer.name, "docstatus": 1} or
                    frappe.db.get_value("HS Charge", checkin_charge.name,
                        "sales_invoice") != invoice["invoice"]):
                frappe.throw("The migrated stay cannot invoice its new lodging charge")
            opening_invoice = first["properties"][0]["receivables"][0]
            opening_details = frappe.db.get_value("Sales Invoice", opening_invoice,
                ["hs_property", "hs_folio", "customer", "docstatus",
                 "outstanding_amount"], as_dict=True)
            if (not opening_details or opening_details.hs_property != prop.name or
                    opening_details.hs_folio != folio.name or
                    opening_details.customer != customer.name or
                    opening_details.docstatus != 1 or
                    Decimal(str(opening_details.outstanding_amount)) != Decimal("25")):
                frappe.throw("The historical PMS receivable is absent from the shared folio")
            frappe.db.savepoint("hs_cutover_opening_credit_probe")
            try:
                opening_credit_data = {"invoice": opening_invoice,
                    "reason": "Corrección de cartera histórica tras el corte"}
                frappe.db.savepoint("hs_cutover_partial_opening_credit_probe")
                try:
                    opening_item = frappe.db.get_value("Sales Invoice Item",
                        {"parent": opening_invoice}, "name")
                    partial_data = {**opening_credit_data,
                        "items": [{"invoice_item": opening_item,
                                   "quantity": "10"}]}
                    partial_quote = suite_api.preview(prop.name,
                        partial_data, "credit_note")
                    if Decimal(partial_quote["total"]) != Decimal("10"):
                        frappe.throw("A partial opening credit changed the amount")
                    partial_credited = suite_api.execute(prop.name, "credit_note",
                        "cutover-partial-opening-credit-" + suffix,
                        {**partial_data,
                         "acceptance": partial_quote["acceptance"]})
                    if (Decimal(str(frappe.db.get_value("Sales Invoice",
                            opening_invoice, "outstanding_amount"))) != Decimal("15") or
                            Decimal(str(frappe.db.get_value("Sales Invoice",
                                partial_credited["credit_note"],
                                "outstanding_amount"))) != 0):
                        frappe.throw("The partial opening credit lost the residual debt")
                finally:
                    frappe.db.rollback(save_point="hs_cutover_partial_opening_credit_probe")
                opening_credit_quote = suite_api.preview(prop.name,
                    opening_credit_data, "credit_note")
                if Decimal(opening_credit_quote["total"]) != Decimal("25"):
                    frappe.throw("The historical opening credit quote changed its balance")
                credited_opening = suite_api.execute(prop.name, "credit_note",
                    "cutover-opening-credit-" + suffix,
                    {**opening_credit_data,
                     "acceptance": opening_credit_quote["acceptance"]})
                native_credit = frappe.get_doc("Sales Invoice",
                    credited_opening["credit_note"])
                if (native_credit.docstatus != 1 or not native_credit.is_return or
                        native_credit.return_against != opening_invoice or
                        Decimal(str(native_credit.grand_total)) != Decimal("-25") or
                        Decimal(str(native_credit.outstanding_amount)) != 0 or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            opening_invoice, "outstanding_amount"))) != 0):
                    frappe.throw("The migrated receivable cannot be credited: " +
                        frappe.as_json({"status": native_credit.docstatus,
                            "return": native_credit.is_return,
                            "against": native_credit.return_against,
                            "grand_total": native_credit.grand_total,
                            "outstanding": frappe.db.get_value("Sales Invoice",
                                opening_invoice, "outstanding_amount")}))
            finally:
                frappe.db.rollback(save_point="hs_cutover_opening_credit_probe")
            if (frappe.db.get_value("HS Payment Method", cash_method.name,
                    "account") != cfg["accounts"][cash.name] or
                    frappe.db.get_value("HS Payment Method", cash_method.name,
                        "mode_of_payment") != "Cash"):
                frappe.throw("The existing cash method did not reach ERPNext")
            currency_settings = suite_api.erp_property_currency_settings(prop.name)
            if (currency_settings["base_currency"] != "NIO" or
                    not {"NIO", "USD"} <= set(currency_settings["accepted_currencies"])):
                frappe.throw("The property's currencies did not survive cutover")
            frappe.db.savepoint("hs_erp_property_currency_probe")
            try:
                if not frappe.db.exists("Currency", "EUR"):
                    frappe.get_doc({"doctype": "Currency", "currency_name": "Euro",
                        "name": "EUR", "enabled": 1}).insert(ignore_permissions=True)
                else:
                    frappe.db.set_value("Currency", "EUR", "enabled", 1,
                                        update_modified=False)
                expanded = {"currencies": ["NIO", "USD", "EUR"]}
                enabled_result = suite_api.execute(prop.name,
                    "erp_property_currencies", "cutover-currency-add-" + suffix,
                    expanded)
                if (suite_api.execute(prop.name, "erp_property_currencies",
                        "cutover-currency-add-" + suffix, expanded) != enabled_result or
                        set(suite_api.erp_property_currency_settings(prop.name)[
                            "accepted_currencies"]) != {"NIO", "USD", "EUR"}):
                    frappe.throw("The ERPNext currency setting was not idempotent")
                try:
                    suite_api.execute(prop.name, "erp_property_currencies",
                        "cutover-currency-remove-used-" + suffix,
                        {"currencies": ["NIO", "EUR"]})
                except frappe.ValidationError:
                    pass
                else:
                    frappe.throw("A used USD bank method lost its accepted currency")
            finally:
                frappe.db.rollback(save_point="hs_erp_property_currency_probe")
                frappe.clear_document_cache("HS Property", prop.name)
            shift = suite_api.execute(prop.name, "open_shift",
                "cutover-shift-" + suffix,
                {"currency": "NIO", "opening_amount": "0"})
            folio_candidates = suite_api.erp_customer_credits_snapshot(
                prop.name)["folios"]
            if not any(row["name"] == entered["folio"] and
                       row["stay"] == entered["stay"] and
                       Decimal(row["balance"]["outstanding"]) == Decimal("20")
                       for row in folio_candidates):
                frappe.throw("The migrated stay folio is missing from React Caja")
            searched_folios = suite_api.erp_customer_credits_snapshot(
                prop.name, entered["folio"])["folios"]
            if len(searched_folios) != 1 or searched_folios[0]["name"] != entered["folio"]:
                frappe.throw("React Caja could not search the migrated folio")
            named_folios = suite_api.erp_customer_credits_snapshot(
                prop.name, customer.customer_name)["folios"]
            if not any(row["name"] == entered["folio"] for row in named_folios):
                frappe.throw("React Caja could not search by payer name")
            first_folio_page = suite_api.erp_customer_credits_snapshot(
                prop.name, receivable_page_length=1)
            second_folio_page = suite_api.erp_customer_credits_snapshot(
                prop.name, folio_offset=1, receivable_page_length=1)
            if (not first_folio_page["folio_page"]["has_more"] or
                    len(first_folio_page["guarantee_folios"]) != 1 or
                    len(second_folio_page["guarantee_folios"]) != 1 or
                    first_folio_page["guarantee_folios"][0]["name"] ==
                        second_folio_page["guarantee_folios"][0]["name"]):
                frappe.throw("React Caja cannot page older folios")
            searched_invoice = suite_api.erp_customer_credits_snapshot(
                prop.name, invoice_search=opening_invoice,
                receivable_page_length=1)
            if (len(searched_invoice["invoices"]) != 1 or
                    searched_invoice["invoices"][0]["name"] != opening_invoice or
                    searched_invoice["invoice_page"]["has_more"]):
                frappe.throw("React Caja cannot search an old open invoice")
            named_invoices = suite_api.erp_customer_credits_snapshot(
                prop.name, invoice_search=customer.customer_name)["invoices"]
            if not any(row["name"] == opening_invoice for row in named_invoices):
                frappe.throw("React Caja cannot search invoices by payer name")
            first_invoice_page = suite_api.erp_customer_credits_snapshot(
                prop.name, receivable_page_length=1)
            second_invoice_page = suite_api.erp_customer_credits_snapshot(
                prop.name, invoice_offset=1, receivable_page_length=1)
            if (not first_invoice_page["invoice_page"]["has_more"] or
                    len(first_invoice_page["invoices"]) != 1 or
                    len(second_invoice_page["invoices"]) != 1 or
                    first_invoice_page["invoices"][0]["name"] ==
                        second_invoice_page["invoices"][0]["name"]):
                frappe.throw("React Caja cannot page older open invoices")
            payment_data = {"kind": "Payment", "shift": shift["shift"],
                "method": cash_method.name, "booking": booking.name,
                "stay": entered["stay"], "folio": entered["folio"],
                "amount": "20"}
            payment_review = suite_api.preview(prop.name, payment_data, "payment")
            if (payment_review.get("folio", {}).get("name") != entered["folio"] or
                    Decimal(payment_review["folio"]["outstanding"]) !=
                        Decimal("20")):
                frappe.throw("The folio payment preview lost its receivable balance")
            paid = suite_api.execute(prop.name, "payment",
                "cutover-payment-" + suffix,
                {**payment_data, "fx_acceptance": payment_review["acceptance"]})
            if suite_api.execute(prop.name, "payment", "cutover-payment-" + suffix,
                    {**payment_data, "fx_acceptance": payment_review["acceptance"]}) != paid:
                frappe.throw("Retrying the cutover payment produced another receipt")
            payment_entry = frappe.db.get_value("Payment Entry", paid["payment_entry"],
                ["docstatus", "paid_from", "paid_to", "paid_amount",
                 "received_amount"], as_dict=True)
            if (not payment_entry or payment_entry.docstatus != 1 or
                    payment_entry.paid_from != cfg["accounts"][receivable.name] or
                    payment_entry.paid_to != cfg["accounts"][cash.name] or
                    Decimal(str(payment_entry.paid_amount)) != Decimal("20") or
                    Decimal(str(payment_entry.received_amount)) != Decimal("20") or
                    frappe.db.count("Payment Entry", {"hs_shift": shift["shift"]}) != 1 or
                    Decimal(str(frappe.db.get_value("Sales Invoice",
                        opening_invoice, "outstanding_amount"))) != Decimal("25") or
                    Decimal(str(frappe.db.get_value("Sales Invoice",
                        invoice["invoice"], "outstanding_amount"))) != 0 or
                    not frappe.db.exists("HS Payment", {"name": paid["payment"],
                        "folio": entered["folio"], "status": "Posted"})):
                frappe.throw("The migrated stay did not collect its new invoice")
            frappe.db.savepoint("hs_cutover_react_advance_probe")
            try:
                if not any(row["name"] == entered["stay"] and
                           row["customer"] == customer.name for row in
                           suite_api.erp_customer_credits_snapshot(
                               prop.name)["advance_stays"]):
                    frappe.throw("React Caja cannot select the active stay for an advance")
                new_advance_data = {"kind": "Advance",
                    "stay": entered["stay"], "shift": shift["shift"],
                    "method": cash_method.name, "amount": "5"}
                new_advance_quote = suite_api.preview(prop.name,
                    new_advance_data, "payment")
                if (new_advance_quote.get("origin", {}).get("stay") !=
                        entered["stay"] or
                        new_advance_quote["origin"]["customer"] !=
                            customer.name):
                    frappe.throw("The advance preview lost its stay and payer")
                new_advance = suite_api.execute(prop.name, "payment",
                    "cutover-react-advance-" + suffix,
                    {**new_advance_data,
                     "fx_acceptance": new_advance_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-react-advance-" + suffix,
                        {**new_advance_data,
                         "fx_acceptance": new_advance_quote["acceptance"]}) !=
                            new_advance or
                        not any(row["name"] == new_advance["payment"] and
                                Decimal(row["available"]) == Decimal("5")
                                for row in suite_api.erp_customer_credits_snapshot(
                                    prop.name)["advances"])):
                    frappe.throw("The new advance is not available in React Caja")
                first_advance_page = suite_api.erp_customer_credits_snapshot(
                    prop.name, funds_page_length=1)
                older_advance_page = suite_api.erp_customer_credits_snapshot(
                    prop.name, advance_offset=1, funds_page_length=1)
                if (first_advance_page["advances"][0]["name"] !=
                        new_advance["payment"] or
                        not first_advance_page["advance_page"]["has_more"] or
                        older_advance_page["advances"][0]["name"] !=
                            advance.name):
                    frappe.throw("Older refundable advances are hidden behind the first page")
                applied_advance = suite_api.execute(prop.name,
                    "apply_customer_advance",
                    "cutover-react-advance-apply-" + suffix,
                    {"advance": new_advance["payment"],
                     "invoice": opening_invoice, "amount": "5"})
                if (Decimal(applied_advance["remaining_advance"]) != 0 or
                        Decimal(applied_advance["invoice_outstanding"]) !=
                            Decimal("20")):
                    frappe.throw("The newly received advance did not pay the opening invoice")
            finally:
                frappe.db.rollback(save_point="hs_cutover_react_advance_probe")
            frappe.db.savepoint("hs_cutover_react_guarantee_probe")
            try:
                guarantee_data = {"kind": "Guarantee", "booking": booking.name,
                    "shift": shift["shift"], "method": cash_method.name,
                    "amount": "10"}
                guarantee_quote = suite_api.preview(prop.name,
                    guarantee_data, "payment")
                if (guarantee_quote.get("origin", {}).get("booking") !=
                        booking.name or
                        guarantee_quote["origin"]["customer"] !=
                            customer.name):
                    frappe.throw("The guarantee preview lost its booking and payer")
                new_guarantee = suite_api.execute(prop.name, "payment",
                    "cutover-react-guarantee-" + suffix,
                    {**guarantee_data,
                     "fx_acceptance": guarantee_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-react-guarantee-" + suffix,
                        {**guarantee_data,
                         "fx_acceptance": guarantee_quote["acceptance"]}) !=
                            new_guarantee):
                    frappe.throw("Retrying the guarantee duplicated its receipt")
                guarantee_view = suite_api.erp_customer_credits_snapshot(prop.name)
                if (not any(row["name"] == new_guarantee["payment"] and
                            Decimal(row["available"]) == Decimal("10") and
                            row["booking"] == booking.name for row in
                            guarantee_view["guarantees"]) or
                        not any(row["name"] == folio.name and
                            row["booking"] == booking.name for row in
                            guarantee_view["guarantee_folios"])):
                    frappe.throw("React Caja cannot select the received guarantee and folio")
                first_guarantee_page = suite_api.erp_customer_credits_snapshot(
                    prop.name, funds_page_length=1)
                older_guarantee_page = suite_api.erp_customer_credits_snapshot(
                    prop.name, guarantee_offset=1, funds_page_length=1)
                if (first_guarantee_page["guarantees"][0]["name"] !=
                        new_guarantee["payment"] or
                        not first_guarantee_page["guarantee_page"]["has_more"] or
                        older_guarantee_page["guarantees"][0]["name"] !=
                            guarantee.name):
                    frappe.throw("Older guarantees are hidden behind the first page")
                application_data = {"source_payment": new_guarantee["payment"],
                    "folio": folio.name, "shift": shift["shift"],
                    "amount": "4", "reason": "Aplicación parcial al folio"}
                applied_guarantee = suite_api.execute(prop.name,
                    "apply_guarantee", "cutover-react-guarantee-apply-" + suffix,
                    application_data)
                if (suite_api.execute(prop.name, "apply_guarantee",
                        "cutover-react-guarantee-apply-" + suffix,
                        application_data) != applied_guarantee or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            opening_invoice, "outstanding_amount"))) !=
                            Decimal("21") or
                        not any(row["name"] == new_guarantee["payment"] and
                            Decimal(row["available"]) == Decimal("6") for row in
                            suite_api.erp_customer_credits_snapshot(prop.name)[
                                "guarantees"])):
                    frappe.throw("The guarantee application did not settle the folio")
                guarantee_credit_data = {"invoice": opening_invoice,
                    "reason": "Corrección de factura pagada con garantía"}
                guarantee_credit_quote = suite_api.preview(prop.name,
                    guarantee_credit_data, "credit_note")
                guarantee_credit = suite_api.execute(prop.name, "credit_note",
                    "cutover-react-guarantee-credit-" + suffix,
                    {**guarantee_credit_data,
                     "acceptance": guarantee_credit_quote["acceptance"]})
                applied_credit_name = guarantee_credit["credit_note"]
                guarantee_credit_view = suite_api.erp_credit_refund_search(
                    prop.name, credit_note=applied_credit_name,
                    source_search=applied_guarantee["payment"])
                if not any(row["credit_note"] == applied_credit_name and
                           row["source"] == applied_guarantee["payment"] and
                           row["kind"] == "Guarantee Applied" and
                           Decimal(row["available_party"]) == Decimal("4")
                           for row in guarantee_credit_view["sources"]):
                    frappe.throw("React Caja cannot match the applied guarantee to its credit")
                guarantee_applied_refund_data = {"kind": "Refund",
                    "source_payment": applied_guarantee["payment"],
                    "credit_note": applied_credit_name,
                    "shift": shift["shift"], "method": cash_method.name,
                    "amount": "4", "reason": "Devolución de garantía aplicada"}
                guarantee_applied_refund_quote = suite_api.preview(prop.name,
                    guarantee_applied_refund_data, "payment")
                if guarantee_applied_refund_quote["refund"]["mode"] != \
                        "Applied Guarantee":
                    frappe.throw("The applied guarantee refund preview lost its origin")
                applied_refund = suite_api.execute(prop.name, "payment",
                    "cutover-react-guarantee-applied-refund-" + suffix,
                    {**guarantee_applied_refund_data,
                     "fx_acceptance": guarantee_applied_refund_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-react-guarantee-applied-refund-" + suffix,
                        {**guarantee_applied_refund_data,
                         "fx_acceptance": guarantee_applied_refund_quote[
                             "acceptance"]}) != applied_refund or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            applied_credit_name, "outstanding_amount"))) != 0):
                    frappe.throw("The applied guarantee refund was not posted exactly once")
                guarantee_refund_data = {"kind": "Guarantee Refund",
                    "source_payment": new_guarantee["payment"],
                    "shift": shift["shift"], "method": cash_method.name,
                    "amount": "6", "reason": "Devolución del resto de garantía"}
                guarantee_refund_quote = suite_api.preview(prop.name,
                    guarantee_refund_data, "payment")
                if Decimal(guarantee_refund_quote["guarantee"][
                        "available_nominal"]) != Decimal("6"):
                    frappe.throw("The guarantee refund preview lost the remainder")
                guarantee_refund = suite_api.execute(prop.name, "payment",
                    "cutover-react-guarantee-refund-" + suffix,
                    {**guarantee_refund_data,
                     "fx_acceptance": guarantee_refund_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-react-guarantee-refund-" + suffix,
                        {**guarantee_refund_data,
                         "fx_acceptance": guarantee_refund_quote["acceptance"]}) !=
                            guarantee_refund or
                        any(row["name"] == new_guarantee["payment"] for row in
                            suite_api.erp_customer_credits_snapshot(prop.name)[
                                "guarantees"])):
                    frappe.throw("The guarantee refund left a balance or duplicated cash")
            finally:
                frappe.db.rollback(save_point="hs_cutover_react_guarantee_probe")
            frappe.db.savepoint("hs_cutover_react_advance_refund_probe")
            try:
                refundable = suite_api.erp_customer_credits_snapshot(prop.name)[
                    "advance_refunds"]
                if not any(row["name"] == advance.name and
                           Decimal(row["remaining"]) == Decimal("12") and
                           Decimal(row["unallocated"]) == Decimal("12")
                           for row in refundable):
                    frappe.throw("React Caja cannot select the migrated refundable advance")
                advance_refund_data = {"kind": "Refund",
                    "source_payment": advance.name, "shift": shift["shift"],
                    "method": cash_method.name, "amount": "5",
                    "reason": "Devolución parcial de anticipo"}
                advance_refund_quote = suite_api.preview(prop.name,
                    advance_refund_data, "payment")
                if (advance_refund_quote["refund"]["mode"] !=
                        "Unallocated Advance" or
                        Decimal(advance_refund_quote["refund"][
                            "party_amount"]) != Decimal("5")):
                    frappe.throw("The advance refund preview lost its original credit")
                returned_advance = suite_api.execute(prop.name, "payment",
                    "cutover-react-advance-refund-" + suffix,
                    {**advance_refund_data,
                     "fx_acceptance": advance_refund_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-react-advance-refund-" + suffix,
                        {**advance_refund_data,
                         "fx_acceptance": advance_refund_quote["acceptance"]}) !=
                            returned_advance or
                        not any(row["name"] == advance.name and
                            Decimal(row["remaining"]) == Decimal("7") and
                            Decimal(row["unallocated"]) == Decimal("7")
                            for row in suite_api.erp_customer_credits_snapshot(
                                prop.name)["advance_refunds"])):
                    frappe.throw("The migrated advance refund did not retain its balance")
            finally:
                frappe.db.rollback(save_point="hs_cutover_react_advance_refund_probe")
            frappe.db.savepoint("hs_cutover_react_applied_refund_probe")
            try:
                allocated_advance = suite_api.execute(prop.name,
                    "apply_customer_advance",
                    "cutover-react-applied-advance-" + suffix,
                    {"advance": advance.name, "invoice": opening_invoice,
                     "amount": "5"})
                if Decimal(allocated_advance["invoice_outstanding"]) != Decimal("20"):
                    frappe.throw("The migrated advance did not reach the opening invoice")
                applied_credit_data = {"invoice": opening_invoice,
                    "reason": "Anulación de factura pagada con anticipo"}
                applied_credit_quote = suite_api.preview(prop.name,
                    applied_credit_data, "credit_note")
                applied_credit = suite_api.execute(prop.name, "credit_note",
                    "cutover-react-applied-credit-" + suffix,
                    {**applied_credit_data,
                     "acceptance": applied_credit_quote["acceptance"]})
                credit_name = applied_credit["credit_note"]
                applied_view = suite_api.erp_credit_refund_search(
                    prop.name, search=credit_name, page_length=1)
                applied_sources = suite_api.erp_credit_refund_search(
                    prop.name, credit_note=credit_name,
                    source_search=advance.name, page_length=1)
                if (not any(row["name"] == credit_name and
                            Decimal(row["available"]) == Decimal("5")
                            for row in applied_view["notes"]) or
                        not any(row["credit_note"] == credit_name and
                            row["source"] == advance.name and
                            row["kind"] == "Advance" and
                            Decimal(row["available_party"]) == Decimal("5")
                            for row in applied_sources["sources"])):
                    frappe.throw("React Caja cannot match the applied advance to its credit")
                applied_refund_data = {"kind": "Refund",
                    "source_payment": advance.name, "credit_note": credit_name,
                    "shift": shift["shift"], "method": cash_method.name,
                    "amount": "5", "reason": "Devolución de anticipo acreditado"}
                applied_refund_quote = suite_api.preview(prop.name,
                    applied_refund_data, "payment")
                if (applied_refund_quote["refund"]["mode"] != "Applied Advance" or
                        Decimal(applied_refund_quote["refund"]["allocated"]) !=
                            Decimal("5")):
                    frappe.throw("The applied advance refund preview lost its credit")
                returned_applied = suite_api.execute(prop.name, "payment",
                    "cutover-react-applied-refund-" + suffix,
                    {**applied_refund_data,
                     "fx_acceptance": applied_refund_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-react-applied-refund-" + suffix,
                        {**applied_refund_data,
                         "fx_acceptance": applied_refund_quote["acceptance"]}) !=
                            returned_applied or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            credit_name, "outstanding_amount"))) != 0 or
                        any(row["credit_note"] == credit_name for row in
                            suite_api.erp_credit_refund_search(
                                prop.name, search=credit_name)["notes"])):
                    frappe.throw("The credited advance was not refunded exactly once")
            finally:
                frappe.db.rollback(save_point="hs_cutover_react_applied_refund_probe")
            frappe.db.savepoint("hs_cutover_partly_paid_opening_probe")
            try:
                partial_payment_data = {**payment_data, "folio": folio.name,
                                        "amount": "10"}
                partial_payment_quote = suite_api.preview(prop.name,
                    partial_payment_data, "payment")
                partial_payment = suite_api.execute(prop.name, "payment",
                    "cutover-partly-paid-opening-" + suffix,
                    {**partial_payment_data,
                     "fx_acceptance": partial_payment_quote["acceptance"]})
                mixed_credit_data = {"invoice": opening_invoice,
                    "reason": "Anulación de factura histórica parcialmente cobrada"}
                mixed_credit_quote = suite_api.preview(prop.name,
                    mixed_credit_data, "credit_note")
                mixed_credit = suite_api.execute(prop.name, "credit_note",
                    "cutover-partly-paid-opening-credit-" + suffix,
                    {**mixed_credit_data,
                     "acceptance": mixed_credit_quote["acceptance"]})
                original_due = Decimal(str(frappe.db.get_value("Sales Invoice",
                    opening_invoice, "outstanding_amount")))
                credit_due = Decimal(str(frappe.db.get_value("Sales Invoice",
                    mixed_credit["credit_note"], "outstanding_amount")))
                if original_due != 0 or credit_due != Decimal("-10"):
                    frappe.throw("A partly paid opening invoice cannot be corrected: " +
                        frappe.as_json({"invoice": str(original_due),
                                        "credit": str(credit_due)}))
                frappe.db.savepoint("hs_cutover_opening_credit_cancel_probe")
                try:
                    cancelled_credit = frappe.get_doc("Sales Invoice",
                        mixed_credit["credit_note"])
                    cancelled_credit.hs_correction_reason = (
                        "Corrección de nota histórica autorizada")
                    cancelled_credit.cancel()
                    if (frappe.db.get_value("Sales Invoice",
                            cancelled_credit.name, "docstatus") != 2 or
                            Decimal(str(frappe.db.get_value("Sales Invoice",
                                opening_invoice,
                                "outstanding_amount"))) != Decimal("15") or
                            frappe.db.get_value("Payment Entry",
                                partial_payment["payment_entry"], "docstatus") != 1):
                        frappe.throw("Cancelling a historical credit lost the original debt")
                finally:
                    frappe.db.rollback(save_point="hs_cutover_opening_credit_cancel_probe")
                partial_refund_data = {"kind": "Refund",
                    "source_payment": partial_payment["payment"],
                    "credit_note": mixed_credit["credit_note"],
                    "shift": shift["shift"], "method": cash_method.name,
                    "amount": "10", "reason": "Reembolso de cobro parcial"}
                partial_refund_quote = suite_api.preview(prop.name,
                    partial_refund_data, "payment")
                partial_refund = suite_api.execute(prop.name, "payment",
                    "cutover-partly-paid-opening-refund-" + suffix,
                    {**partial_refund_data,
                     "fx_acceptance": partial_refund_quote["acceptance"]})
                if Decimal(str(frappe.db.get_value("Sales Invoice",
                        mixed_credit["credit_note"],
                        "outstanding_amount"))) != 0:
                    frappe.throw("The partial historical collection was not refunded")
                frappe.db.savepoint("hs_cutover_refunded_credit_cancel_probe")
                try:
                    refunded_credit = frappe.get_doc("Sales Invoice",
                        mixed_credit["credit_note"])
                    refunded_credit.hs_correction_reason = (
                        "Corrección posterior al reembolso")
                    try:
                        refunded_credit.cancel()
                    except frappe.ValidationError:
                        pass
                    else:
                        frappe.throw("A refunded historical credit was cancelled")
                    refund_voucher = frappe.get_doc("Payment Entry",
                        partial_refund["payment_entry"])
                    refund_voucher.hs_correction_reason = (
                        "Reversión autorizada del reembolso histórico")
                    refund_voucher.cancel()
                    refunded_credit.reload()
                    refunded_credit.hs_correction_reason = (
                        "Corrección después de revertir el reembolso")
                    refunded_credit.cancel()
                    if (frappe.db.get_value("HS Payment",
                            partial_refund["payment"], "status") != "Cancelled" or
                            frappe.db.get_value("Sales Invoice",
                                refunded_credit.name, "docstatus") != 2 or
                            Decimal(str(frappe.db.get_value("Sales Invoice",
                                opening_invoice,
                                "outstanding_amount"))) != Decimal("15")):
                        frappe.throw("Reversing a historical refund lost the debt")
                finally:
                    frappe.db.rollback(save_point="hs_cutover_refunded_credit_cancel_probe")
            finally:
                frappe.db.rollback(save_point="hs_cutover_partly_paid_opening_probe")
            frappe.db.savepoint("hs_cutover_desk_opening_credit_probe")
            try:
                desk_payment_data = {**payment_data, "folio": folio.name,
                                     "amount": "10"}
                desk_payment_quote = suite_api.preview(prop.name,
                    desk_payment_data, "payment")
                suite_api.execute(prop.name, "payment",
                    "cutover-desk-opening-payment-" + suffix,
                    {**desk_payment_data,
                     "fx_acceptance": desk_payment_quote["acceptance"]})
                from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
                desk_return = make_sales_return(opening_invoice)
                desk_return.flags.ignore_permissions = True
                desk_return.update(dict(hs_property=prop.name,
                    hs_folio=folio.name, update_stock=0,
                    selling_price_list=price_list.name,
                    price_list_currency=prop.currency, plc_conversion_rate=1,
                    update_outstanding_for_self=0,
                    remarks="Corrección administrativa de deuda histórica"))
                for item_row in desk_return.items:
                    item_row.hs_charge = None
                    item_row.hs_charge_sources = None
                desk_return.insert(ignore_permissions=True)
                desk_return.submit()
                if (Decimal(str(frappe.db.get_value("Sales Invoice",
                        opening_invoice, "outstanding_amount"))) != 0 or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            desk_return.name, "outstanding_amount"))) !=
                        Decimal("-10")):
                    frappe.throw("A Desk credit did not reconcile the opening invoice")
            finally:
                frappe.db.rollback(save_point="hs_cutover_desk_opening_credit_probe")
            settlement_data = {**payment_data, "folio": folio.name, "amount": "25"}
            settlement_review = suite_api.preview(prop.name, settlement_data, "payment")
            settled = suite_api.execute(prop.name, "payment",
                "cutover-settlement-" + suffix,
                {**settlement_data, "fx_acceptance": settlement_review["acceptance"]})
            if (not settled["payment_entry"] or
                    frappe.db.count("Payment Entry", {"hs_shift": shift["shift"]}) != 2 or
                    not frappe.db.exists("Payment Entry Reference", {
                        "parent": settled["payment_entry"],
                        "reference_doctype": "Sales Invoice",
                        "reference_name": opening_invoice,
                        "allocated_amount": 25}) or
                    any(Decimal(str(frappe.db.get_value("Sales Invoice", name,
                        "outstanding_amount"))) != 0 for name in
                        (opening_invoice, invoice["invoice"]))):
                frappe.throw("The migrated and new folio invoices were not both settled")
            frappe.db.savepoint("hs_cutover_paid_opening_refund_probe")
            try:
                paid_credit_data = {"invoice": opening_invoice,
                    "reason": "Devolución de cobro histórico después del corte"}
                paid_credit_quote = suite_api.preview(prop.name,
                    paid_credit_data, "credit_note")
                paid_credit = suite_api.execute(prop.name, "credit_note",
                    "cutover-paid-opening-credit-" + suffix,
                    {**paid_credit_data,
                     "acceptance": paid_credit_quote["acceptance"]})
                native_credit = frappe.get_doc("Sales Invoice",
                    paid_credit["credit_note"])
                if (native_credit.docstatus != 1 or not native_credit.is_return or
                        native_credit.return_against != opening_invoice or
                        Decimal(str(native_credit.outstanding_amount)) != Decimal("-25")):
                    frappe.throw("The paid historical receivable has no refundable credit")
                if not any(row["credit_note"] == native_credit.name and
                           row["source"] == settled["payment"] and
                           row["kind"] == "Payment" and
                           Decimal(row["available_party"]) == Decimal("25")
                           for row in suite_api.erp_credit_refund_search(
                               prop.name, credit_note=native_credit.name,
                               source_search=settled["payment"])["sources"]):
                    frappe.throw("React Caja cannot identify the paid folio refund")
                refund_data = {"kind": "Refund", "source_payment": settled["payment"],
                    "credit_note": native_credit.name, "shift": shift["shift"],
                    "method": cash_method.name, "amount": "25",
                    "reason": "Reembolso de cobro histórico"}
                refund_quote = suite_api.preview(prop.name,
                    refund_data, "payment")
                refunded = suite_api.execute(prop.name, "payment",
                    "cutover-paid-opening-refund-" + suffix,
                    {**refund_data,
                     "fx_acceptance": refund_quote["acceptance"]})
                if (suite_api.execute(prop.name, "payment",
                        "cutover-paid-opening-refund-" + suffix,
                        {**refund_data,
                         "fx_acceptance": refund_quote["acceptance"]}) != refunded or
                        not refunded["payment_entry"] or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            native_credit.name, "outstanding_amount"))) != 0):
                    frappe.throw("The paid historical receivable could not be refunded")
            finally:
                frappe.db.rollback(save_point="hs_cutover_paid_opening_refund_probe")
            from hospitality_suite.financial_movements import outstanding as loan_outstanding
            migrated_loan = frappe.get_doc("HS Treasury Movement", historical_loan.name)
            if (migrated_loan.counter_account != target_loan.name or
                    loan_outstanding(migrated_loan) != Decimal("36.5")):
                frappe.throw("The foreign PMS loan principal was not preserved")
            finance_screen = suite_api.erp_financing_snapshot(prop.name)
            if not any(row.name == historical_loan.name and
                    Decimal(row.available) == Decimal("36.5") and
                    Decimal(row.principal_outstanding) == Decimal("36.5")
                    for row in finance_screen["sources"]):
                frappe.throw("The ERPNext financing screen lost migrated principal")
            frappe.db.savepoint("hs_cutover_loan_repayment_probe")
            try:
                loan_request = suite_api.execute(prop.name, "finance_request",
                    "cutover-loan-request-" + suffix,
                    {"kind": "Loan Repayment", "source_movement": historical_loan.name,
                     "amount": "10", "reason": "Abono tras el corte"})["movement"]
                approver = "hs-cutover-manager-" + suffix + "@example.invalid"
                # A rolled-back user must not enqueue contact creation after
                # the rehearsal transaction is discarded.
                with patch("frappe.enqueue", return_value=None):
                    frappe.get_doc({"doctype": "User", "email": approver,
                        "first_name": "Gerencia corte", "enabled": 1,
                        "send_welcome_email": 0,
                        "roles": [{"role": "System Manager"}]}).insert(
                            ignore_permissions=True)
                try:
                    frappe.set_user(approver)
                    suite_api.execute(prop.name, "finance_approve",
                        "cutover-loan-approve-" + suffix,
                        {"movement": loan_request,
                         "reason": "Principal verificado"})
                finally:
                    frappe.set_user("Administrator")
                loan_payment = {"movement": loan_request, "amount": "10",
                    "channel": "Cash", "shift": shift["shift"],
                    "method": cash_method.name, "reason": "Abono de principal"}
                finance_review = suite_api.preview(prop.name, loan_payment,
                    "finance_post")
                if (not finance_review["acceptance"] or
                        finance_review["debit"] != target_loan.name or
                        finance_review["credit"] != frappe.db.get_value(
                            "HS Payment Method", cash_method.name, "account")):
                    frappe.throw("The ERPNext financing review lost its accounts")
                reviewed_payment = {**loan_payment,
                    "acceptance": finance_review["acceptance"]}
                repaid_loan = suite_api.execute(prop.name, "finance_post",
                    "cutover-loan-post-" + suffix, reviewed_payment)
                if (suite_api.execute(prop.name, "finance_post",
                        "cutover-loan-post-" + suffix, reviewed_payment) != repaid_loan or
                        loan_outstanding(migrated_loan) != Decimal("26.5") or
                        frappe.db.get_value("Journal Entry",
                            repaid_loan["journal_entry"], "docstatus") != 1 or
                        Decimal(str(frappe.db.sql(
                            "SELECT COALESCE(SUM(debit-credit),0) "
                            "FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0",
                            (target_loan.name,))[0][0])) != Decimal("-26.5")):
                    frappe.throw("A partial ERPNext repayment lost the historical loan")
                if not any(row.name == historical_loan.name and
                        Decimal(row.available) == Decimal("26.5") for row in
                        suite_api.erp_financing_snapshot(prop.name)["sources"]):
                    frappe.throw("The ERPNext financing screen lost the repayment")
                cancelled_request = suite_api.execute(prop.name,
                    "finance_request", "cutover-loan-cancel-request-" + suffix,
                    {"kind": "Loan Repayment",
                     "source_movement": historical_loan.name,
                     "amount": "1", "reason": "Solicitud para cancelar"})["movement"]
                cancelled_finance = suite_api.execute(prop.name,
                    "finance_cancel_request", "cutover-loan-cancel-" + suffix,
                    {"movement": cancelled_request,
                     "reason": "Solicitud retirada antes del asiento"})
                if (cancelled_finance["status"] != "Cancelled" or
                        loan_outstanding(migrated_loan) != Decimal("26.5")):
                    frappe.throw("Cancelling a request changed the loan principal")
                try:
                    suite_api.execute(prop.name, "finance_request",
                        "cutover-loan-overpay-" + suffix,
                        {"kind": "Loan Repayment",
                         "source_movement": historical_loan.name,
                         "amount": "27", "reason": "Intento sobre el principal"})
                except frappe.ValidationError:
                    pass
                else:
                    frappe.throw("The migrated loan allowed excess principal repayment")
            finally:
                frappe.set_user("Administrator")
                frappe.db.rollback(save_point="hs_cutover_loan_repayment_probe")
            if loan_outstanding(migrated_loan) != Decimal("36.5"):
                frappe.throw("The repayment rehearsal changed the source loan")
            frappe.db.savepoint("hs_cutover_other_income_probe")
            try:
                native_bank = frappe.get_doc({"doctype": "Account",
                    "account_name": "HS Bank Income " + suffix,
                    "parent_account": bank_parent,
                    "company": target_company.name, "account_type": "Bank",
                    "account_currency": "NIO", "is_group": 0}).insert(
                        ignore_permissions=True)
                income_concept = suite_api.save_setup(prop.name,
                    "treasury_concept", {"label": "Ingreso eventual " + suffix,
                        "nature": "Other Income",
                        "account": cfg["accounts"][income.name], "active": 1},
                    "cutover-income-concept-" + suffix)["name"]
                income_data = {"kind": "Other Income", "concept": income_concept,
                    "amount": "7", "channel": "Bank",
                    "bank_account": native_bank.name,
                    "reference": "BAN-ING-" + suffix,
                    "reason": "Ingreso eventual de ensayo"}
                income_review = suite_api.preview(prop.name, income_data,
                    "finance_post")
                if (income_review["debit"] != native_bank.name or
                        income_review["credit"] !=
                            cfg["accounts"][income.name] or
                        not income_review["acceptance"] or
                        not any(row.name == income_concept for row in
                            suite_api.erp_financing_snapshot(prop.name)["concepts"])):
                    frappe.throw("The ERPNext other income review lost its concept")
                try:
                    suite_api.execute(prop.name, "finance_post",
                        "cutover-income-stale-" + suffix,
                        {**income_data, "acceptance": "stale-review"})
                except frappe.ValidationError:
                    pass
                else:
                    frappe.throw("The ERPNext other income accepted an obsolete review")
                reviewed_income = {**income_data,
                    "acceptance": income_review["acceptance"]}
                posted_income = suite_api.execute(prop.name, "finance_post",
                    "cutover-income-post-" + suffix, reviewed_income)
                if (suite_api.execute(prop.name, "finance_post",
                        "cutover-income-post-" + suffix,
                        reviewed_income) != posted_income or
                        frappe.db.get_value("Journal Entry",
                            posted_income["journal_entry"], "docstatus") != 1 or
                        not any(row.name == posted_income["movement"] and
                            row.status == "Posted" for row in
                            suite_api.erp_financing_snapshot(prop.name)["movements"])):
                    frappe.throw("The ERPNext other income was not posted once")
                reversed_income = suite_api.execute(prop.name,
                    "finance_reverse", "cutover-income-reverse-" + suffix,
                    {"doctype": "HS Treasury Movement",
                     "name": posted_income["movement"],
                     "reason": "Reversión del ingreso de ensayo"})
                if (reversed_income["status"] != "Cancelled" or
                        frappe.db.get_value("Journal Entry",
                            posted_income["journal_entry"], "docstatus") != 2):
                    frappe.throw("The ERPNext other income did not reverse")
            finally:
                frappe.db.rollback(save_point="hs_cutover_other_income_probe")
            from hospitality_suite.financial_movements import (
                balance as petty_balance, ledger_balance as petty_ledger_balance)
            if (petty_balance(migrated_property) != Decimal("38") or
                    petty_ledger_balance(migrated_property) != Decimal("38") or
                    frappe.db.get_value("HS Petty Cash Rendition",
                        petty_rendition.name, "status") != "Partially Reimbursed"):
                frappe.throw("The partially replenished PMS petty fund was not preserved")
            petty_screen = suite_api.erp_petty_snapshot(prop.name)
            if (not petty_screen["active"] or not petty_screen["reconciled"] or
                    Decimal(petty_screen["balance"]) != Decimal("38") or
                    Decimal(petty_screen["expected_cash"]) != Decimal("38") or
                    not any(row.name == petty_expense.name for row in petty_screen["expenses"]) or
                    not any(row.name == petty_rendition.name for row in petty_screen["renditions"]) or
                    not any(row.kind == "Replenishment" for row in petty_screen["funds"]) or
                    not any(row.name == migrated_property.petty_cash_account
                            for row in petty_screen["accounts"])):
                frappe.throw("The ERPNext petty cash screen lost migrated balances or history")
            frappe.db.savepoint("hs_cutover_petty_setup_probe")
            try:
                petty_settings = {"petty_cash_account": petty_screen["account"],
                    "petty_cash_responsible": petty_screen["responsible"],
                    "petty_cash_overage_account": petty_screen["overage_account"],
                    "petty_cash_shortage_account": petty_screen["shortage_account"]}
                saved_petty_settings = suite_api.save_setup(prop.name, "property",
                    petty_settings, "cutover-petty-setup-" + suffix,
                    petty_screen["property_modified"])
                if (suite_api.save_setup(prop.name, "property", petty_settings,
                        "cutover-petty-setup-" + suffix,
                        petty_screen["property_modified"]) != saved_petty_settings or
                        not suite_api.erp_petty_snapshot(prop.name)["reconciled"]):
                    frappe.throw("The ERPNext petty cash setup was not idempotent")
            finally:
                frappe.db.rollback(save_point="hs_cutover_petty_setup_probe")
            frappe.db.savepoint("hs_cutover_petty_replenishment_probe")
            try:
                replenish_data = {"kind": "Replenishment",
                    "rendition": petty_rendition.name, "shift": shift["shift"],
                    "method": cash_method.name, "amount": "12",
                    "reference": "Reposición de ensayo",
                    "reason": "Completar rendición histórica"}
                replenished = suite_api.execute(prop.name, "petty_fund",
                    "cutover-petty-replenish-" + suffix, replenish_data)
                if (suite_api.execute(prop.name, "petty_fund",
                        "cutover-petty-replenish-" + suffix,
                        replenish_data) != replenished or
                        frappe.db.get_value("HS Petty Cash Rendition",
                            petty_rendition.name, "status") != "Reimbursed" or
                        petty_balance(migrated_property) != Decimal("50") or
                        petty_ledger_balance(migrated_property) != Decimal("50") or
                        frappe.db.get_value("HS Treasury Movement",
                            replenished["movement"], "reference") !=
                            "Reposición de ensayo" or
                        Decimal(suite_api.erp_petty_snapshot(prop.name)["balance"]) !=
                            Decimal("50")):
                    frappe.throw("ERPNext did not complete the PMS petty reimbursement")
                try:
                    suite_api.execute(prop.name, "petty_fund",
                        "cutover-petty-overpay-" + suffix,
                        {**replenish_data, "amount": "1"})
                except frappe.ValidationError:
                    pass
                else:
                    frappe.throw("The approved PMS expenses were reimbursed twice")
                reversed_replenishment = suite_api.execute(prop.name,
                    "finance_reverse", "cutover-petty-reverse-" + suffix,
                    {"doctype": "HS Treasury Movement",
                     "name": replenished["movement"],
                     "reason": "Deshacer reposición de ensayo"})
                if (reversed_replenishment["status"] != "Cancelled" or
                        frappe.db.get_value("HS Petty Cash Rendition",
                            petty_rendition.name, "status") !=
                            "Partially Reimbursed" or
                        petty_balance(migrated_property) != Decimal("38") or
                        petty_ledger_balance(migrated_property) != Decimal("38")):
                    frappe.throw("Reversing a replenishment lost the approved balance")
            finally:
                frappe.db.rollback(save_point="hs_cutover_petty_replenishment_probe")
            if (petty_balance(migrated_property) != Decimal("38") or
                    frappe.db.get_value("HS Petty Cash Rendition",
                        petty_rendition.name, "status") != "Partially Reimbursed"):
                frappe.throw("The petty cash rehearsal changed the main scenario")
            frappe.db.savepoint("hs_cutover_petty_handover_cancel_probe")
            try:
                incoming = "hs-petty-manager-" + suffix + "@example.invalid"
                with patch("frappe.enqueue", return_value=None):
                    frappe.get_doc({"doctype": "User", "email": incoming,
                        "first_name": "Gerencia Caja Chica", "enabled": 1,
                        "send_welcome_email": 0,
                        "roles": [{"role": "System Manager"}]}).insert(
                            ignore_permissions=True)
                handover = suite_api.execute(prop.name, "petty_handover",
                    "cutover-petty-handover-" + suffix,
                    {"incoming": incoming, "counted_cash": "38",
                     "reason": "Cambio de custodio de ensayo"})["handover"]
                cancel_data = {"handover": handover,
                    "reason": "Traspaso de ensayo cancelado"}
                cancelled = suite_api.execute(prop.name,
                    "petty_handover_cancel", "cutover-petty-handover-cancel-" + suffix,
                    cancel_data)
                if (suite_api.execute(prop.name, "petty_handover_cancel",
                        "cutover-petty-handover-cancel-" + suffix,
                        cancel_data) != cancelled or
                        cancelled["status"] != "Cancelled" or
                        frappe.db.get_value("HS Property", prop.name,
                            "petty_cash_responsible") != "Administrator"):
                    frappe.throw("The pending ERPNext petty handover did not cancel safely")
            finally:
                frappe.db.rollback(save_point="hs_cutover_petty_handover_cancel_probe")
            confirmed_experience = suite_api.execute(prop.name,
                "experience_status", "cutover-experience-" + suffix,
                {"order": experience_order.name,
                 "modified": str(frappe.db.get_value(
                     "HS Experience Order", experience_order.name, "modified")),
                 "status": "Confirmed", "scheduled_at": arrival,
                 "participants": 1})
            if confirmed_experience["status"] != "Confirmed":
                frappe.throw("The booked experience cannot continue after cutover")
            if not any(row["name"] == experience_order.name and
                       row["status"] == "Confirmed" for row in
                       suite_api.erp_travel_experiences_snapshot(prop.name)["orders"]):
                frappe.throw("The ERPNext experiences screen missed a confirmed order")
            frappe.db.savepoint("hs_cutover_experience_delivery_probe")
            try:
                delivered = suite_api.execute(prop.name, "experience_status",
                    "cutover-experience-delivery-" + suffix,
                    {"order": experience_order.name,
                     "modified": confirmed_experience["modified"],
                     "status": "Delivered", "stay": entered["stay"],
                     "folio": entered["folio"]})
                experience_charge = frappe.db.get_value("HS Charge",
                    delivered["charge"], ["item", "amount", "folio", "status"],
                    as_dict=True)
                if (delivered["status"] != "Delivered" or not experience_charge or
                        experience_charge.item != experience_item.name or
                        Decimal(str(experience_charge.amount)) != Decimal("8") or
                        experience_charge.folio != entered["folio"] or
                        experience_charge.status != "Pending"):
                    frappe.throw("The migrated experience did not create its ERPNext charge")
                experience_invoice = suite_api.execute(prop.name, "invoice",
                    "cutover-experience-invoice-" + suffix,
                    {"folio": entered["folio"]})
                if (frappe.db.get_value("Sales Invoice",
                        experience_invoice["invoice"], "docstatus") != 1 or
                        frappe.db.get_value("HS Charge", delivered["charge"],
                            "sales_invoice") != experience_invoice["invoice"] or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            experience_invoice["invoice"],
                            "outstanding_amount"))) != Decimal("8")):
                    frappe.throw("The migrated experience could not be invoiced")
                experience_payment = {**payment_data, "amount": "8"}
                experience_payment_review = suite_api.preview(prop.name,
                    experience_payment, "payment")
                experience_paid = suite_api.execute(prop.name, "payment",
                    "cutover-experience-payment-" + suffix,
                    {**experience_payment,
                     "fx_acceptance": experience_payment_review["acceptance"]})
                if (not experience_paid["payment_entry"] or
                        Decimal(str(frappe.db.get_value("Sales Invoice",
                            experience_invoice["invoice"],
                            "outstanding_amount"))) != 0):
                    frappe.throw("The migrated experience could not be collected")
            finally:
                frappe.db.rollback(save_point="hs_cutover_experience_delivery_probe")
            if (frappe.db.get_value("HS Experience Order", experience_order.name,
                    "status") != "Confirmed" or
                    frappe.db.exists("HS Charge", {"name": delivered["charge"]}) or
                    frappe.db.exists("Sales Invoice", experience_invoice["invoice"])):
                frappe.throw("The delivery probe changed the main cutover scenario")
            from hospitality_suite.travel_experiences import commission_quote
            legacy_booking = frappe.get_doc("HS Booking", booking.name)
            legacy_booking.status = "Completed"
            legacy_booking.pms_agent_commission = "posted-before-cutover"
            with patch("hospitality_suite.travel_experiences.document", return_value=legacy_booking):
                try:
                    commission_quote(migrated_property, {"booking": booking.name})
                except frappe.ValidationError as exc:
                    if "comisión pendiente" not in str(exc):
                        raise
                else:
                    frappe.throw("ERPNext offered a second commission for a settled PMS booking")
            migrated_guarantee = frappe.get_doc("HS Payment", guarantee.name)
            migrated_advance = frappe.get_doc("HS Payment", advance.name)
            if guarantee_balance(migrated_property, migrated_guarantee).book != 15:
                frappe.throw("The active ERPNext guarantee lost its remaining liability")
            if refund_balance(migrated_property, migrated_advance).remaining != 12:
                frappe.throw("The active ERPNext advance lost its refundable balance")
            if refund_plan(migrated_property, migrated_advance, 5,
                           frappe._dict(currency="NIO")).party_amount != 5:
                frappe.throw("The active ERPNext advance cannot plan a partial refund")
            departure_data = {"stay": entered["stay"], "modified": str(
                frappe.db.get_value("HS Stay", entered["stay"], "modified"))}
            try:
                suite_api.execute(prop.name, "check_out",
                    "cutover-experience-block-" + suffix, departure_data)
            except frappe.ValidationError as exc:
                if "experiencias pendientes" not in str(exc):
                    raise
            else:
                frappe.throw("Checkout ignored the pending migrated experience")
            cancelled_experience = suite_api.execute(prop.name,
                "experience_status", "cutover-experience-cancel-" + suffix,
                {"order": experience_order.name,
                 "modified": str(frappe.db.get_value("HS Experience Order",
                     experience_order.name, "modified")),
                 "status": "Cancelled", "reason": "No se realizó la experiencia"})
            if cancelled_experience["status"] != "Cancelled":
                frappe.throw("The migrated experience could not be cancelled")
            try:
                suite_api.execute(prop.name, "check_out",
                    "cutover-guarantee-block-" + suffix, departure_data)
            except frappe.ValidationError as exc:
                if "garantía" not in str(exc):
                    raise
            else:
                frappe.throw("Checkout ignored the migrated guarantee")
            refund_data = {"kind": "Guarantee Refund",
                "source_payment": guarantee.name, "shift": shift["shift"],
                "method": cash_method.name, "amount": "15",
                "reason": "Devolución del remanente de garantía"}
            refund_review = suite_api.preview(prop.name, refund_data, "payment")
            refunded = suite_api.execute(prop.name, "payment",
                "cutover-guarantee-refund-" + suffix,
                {**refund_data, "fx_acceptance": refund_review["acceptance"]})
            if (not refunded["journal_entry"] or
                    frappe.db.get_value("Journal Entry", refunded["journal_entry"],
                        "docstatus") != 1 or
                    guarantee_balance(migrated_property, migrated_guarantee).book != 0):
                frappe.throw("The migrated guarantee could not be refunded")
            if suite_api.erp_departure_detail(prop.name, entered["stay"])["guarantees"]:
                frappe.throw("The ERPNext departure screen kept a settled guarantee")
            checked_out = suite_api.execute(prop.name, "check_out",
                "cutover-checkout-" + suffix, departure_data)
            if (suite_api.execute(prop.name, "check_out",
                    "cutover-checkout-" + suffix, departure_data) != checked_out or
                    frappe.db.get_value("HS Stay", entered["stay"], "status") !=
                        "Checked Out" or
                    frappe.db.get_value("HS Folio", entered["folio"], "status") !=
                        "Closed" or
                    frappe.db.get_value("HS Folio", folio.name, "status") != "Closed" or
                    frappe.db.get_value("HS Booking", booking.name, "status") !=
                        "Completed" or
                    frappe.db.get_value("HS Room", room.name,
                        "cleaning_status") != "Dirty" or
                    not frappe.db.exists("HS Cleaning Task", {
                        "name": checked_out["cleaning_task"],
                        "stay": entered["stay"], "status": "Pending"})):
                frappe.throw("The migrated stay could not complete checkout")
            if any(row["name"] == entered["stay"] for row in
                   suite_api.erp_departure_snapshot(prop.name)["stays"]):
                frappe.throw("The ERPNext departure screen kept a checked-out stay")
            if (suite_api.stay_page(prop.name, "history",
                    entered["stay"])["rows"][0]["status"] != "Checked Out" or
                    suite_api.stay_overview(prop.name,
                        entered["stay"])["status"] != "Checked Out"):
                frappe.throw("The ERPNext stay history lost the completed visit")
            room_work = suite_api.erp_room_operations(prop.name)
            if (not any(row["name"] == room.name for row in room_work["rooms"]) or
                    not any(row["name"] == checked_out["cleaning_task"] and
                            row["status"] == "Pending"
                            for row in room_work["tasks"])):
                frappe.throw("The ERPNext room work screen lost the departure cleaning task")
            frappe.db.savepoint("hs_cutover_room_work_probe")
            try:
                block_start = str(today + timedelta(days=400)) + "T10:00:00"
                block_end = str(today + timedelta(days=400)) + "T11:00:00"
                blocked_room = suite_api.execute(prop.name, "room_block",
                    "cutover-room-block-" + suffix,
                    {"room": room.name, "reason": "House Use",
                     "starts_at": block_start, "ends_at": block_end})
                if not any(row["name"] == blocked_room["block"] for row in
                           suite_api.erp_room_operations(prop.name)["room_blocks"]):
                    frappe.throw("The ERPNext room block is not visible in React")
                suite_api.execute(prop.name, "room_unblock",
                    "cutover-room-unblock-" + suffix,
                    {"block": blocked_room["block"],
                     "modified": blocked_room["modified"],
                     "reason": "Fin de la prueba reversible"})
                if any(row["name"] == blocked_room["block"] for row in
                       suite_api.erp_room_operations(prop.name)["room_blocks"]):
                    frappe.throw("The ERPNext room block remained active after release")
            finally:
                frappe.db.rollback(save_point="hs_cutover_room_work_probe")
            commission_review = suite_api.preview(prop.name,
                {"booking": booking.name}, "agent_commission")
            if (commission_review["supplier"] != supplier.name or
                    Decimal(commission_review["base"]) != Decimal("20") or
                    Decimal(commission_review["amount"]) != Decimal("1")):
                frappe.throw("The migrated agency commission lost its agreed basis")
            commission_data = {"booking": booking.name,
                "modified": commission_review["modified"]}
            settled_commission = suite_api.execute(prop.name,
                "agent_commission", "cutover-agent-commission-" + suffix,
                commission_data)
            if (suite_api.execute(prop.name, "agent_commission",
                    "cutover-agent-commission-" + suffix,
                    commission_data) != settled_commission or
                    frappe.db.get_value("Purchase Invoice",
                        settled_commission["invoice"], "docstatus") != 1 or
                    frappe.db.get_value("HS Booking", booking.name,
                        "agent_commission_invoice") != settled_commission["invoice"] or
                    not frappe.db.exists("Purchase Invoice Item", {
                        "parent": settled_commission["invoice"],
                        "item_code": commission_item.name,
                        "expense_account": commission_review["expense_account"],
                        "amount": 1})):
                frappe.throw("The migrated agency commission was not posted once")
            if not any(row["name"] == booking.name and
                       row["agent_commission_invoice"] ==
                           settled_commission["invoice"] for row in
                       suite_api.erp_travel_experiences_snapshot(prop.name)["bookings"]):
                frappe.throw("The ERPNext agencies screen lost the posted commission")
            from hospitality_suite.cashier import expected as cash_expected
            if Decimal(cash_expected(frappe.get_doc("HS Shift",
                    shift["shift"]))["NIO"]) != Decimal("30"):
                frappe.throw("Cutover payments and guarantee refund did not balance cash")
            frappe.db.savepoint("hs_cutover_cash_transfer_probe")
            try:
                transfer_account = frappe.get_doc({"doctype": "Account",
                    "account_name": "HS Transfer " + suffix,
                    "parent_account": cash_parent,
                    "company": target_company.name, "account_type": "Cash",
                    "account_currency": "NIO", "is_group": 0}).insert(
                        ignore_permissions=True)
                transfer_settings = suite_api.erp_cash_settings(prop.name)
                suite_api.save_setup(prop.name, "property",
                    {"cash_transfer_account": transfer_account.name},
                    "cutover-cash-transfer-account-" + suffix,
                    expected_modified=transfer_settings["property_modified"])
                withdrawn = suite_api.execute(prop.name, "withdrawal",
                    "cutover-cash-withdrawal-" + suffix,
                    {"shift": shift["shift"], "method": cash_method.name,
                     "amount": "5", "reason": "Traspaso de prueba"})
                if (frappe.db.get_value("Journal Entry",
                        withdrawn["journal_entry"], "docstatus") != 1 or
                        Decimal(cash_expected(frappe.get_doc("HS Shift",
                            shift["shift"]))["NIO"]) != Decimal("25")):
                    frappe.throw("The ERPNext cash transfer did not post its journal")
            finally:
                frappe.db.rollback(save_point="hs_cutover_cash_transfer_probe")
            closed_shift = suite_api.execute(prop.name, "close_shift",
                "cutover-close-shift-" + suffix,
                {"shift": shift["shift"], "modified": str(
                    frappe.db.get_value("HS Shift", shift["shift"], "modified")),
                 "denominations": {"NIO": [{"value": "10", "count": 3}]}})
            if (closed_shift["status"] != "Closed" or
                    Decimal(str(closed_shift["differences"]["NIO"])) != 0):
                frappe.throw("The migrated stay's cash shift did not close")
            cash_screen = suite_api.erp_cash_snapshot(prop.name,
                shift["shift"], 0, 2)
            cash_settings = suite_api.erp_cash_settings(prop.name)
            if (cash_screen["selected"]["status"] != "Closed" or
                    Decimal(cash_screen["selected"]["expected"]["NIO"]) != 30 or
                    cash_screen["unmatched"] or not cash_screen["movements"] or
                    cash_screen["offset"] != 0 or
                    cash_settings["base_currency"] != "NIO" or
                    not cash_settings["accounts"]):
                frappe.throw("The ERPNext cash desk lost the reconciled shift")
            try:
                suite_api.execute(prop.name, "open_shift",
                    "cutover-disabled-currency-" + suffix,
                    {"currency": "ZZZ", "opening_amount": "0"})
            except frappe.ValidationError as exc:
                if "moneda del turno no está habilitada" not in str(exc):
                    raise
            else:
                frappe.throw("A shift opened in a disabled currency")
            close_review = suite_api.execute(prop.name, "daily_close",
                "cutover-close-review-" + suffix, {})
            if close_review["status"] != "Review" or close_review["blockers"]:
                frappe.throw("The cutover day cannot be reviewed: " +
                    frappe.as_json(close_review["blockers"]))
            close_screen = suite_api.erp_close_snapshot(prop.name)
            close_history = suite_api.erp_close_history(prop.name, "", 0, 1)
            close_detail = suite_api.erp_close_detail(prop.name,
                close_review["close"])
            if (not close_screen["current"] or
                    close_screen["current"]["name"] != close_review["close"] or
                    close_screen["current"]["snapshot"]["financial"][
                        "business_date"] != str(today) or
                    not close_history["rows"] or
                    close_history["rows"][0].name != close_review["close"] or
                    close_detail["snapshot"]["financial"]["version"] != 2):
                frappe.throw("The ERPNext close screen lost its review snapshot")
            catalog = suite_api.erp_report_catalog(prop.name)
            report_filters = suite_api.report_options(prop.name, "Facturas")
            invoice_report = suite_api.report_page(prop.name, "Facturas",
                {"from_date": str(today), "to_date": str(today)}, 0, 2)
            if ("Facturas" not in catalog["reports"] or
                    not catalog["can_export"] or
                    "date_field" not in report_filters or
                    not invoice_report["rows"] or
                    invoice_report["total"] < len(invoice_report["rows"]) or
                    not invoice_report["columns"]):
                frappe.throw("The ERPNext operational report screen is unavailable")
            financial = close_review["period"]["financial"]
            nio = next((row for row in financial["currencies"] if
                row["currency"] == "NIO"), None)
            if (not nio or Decimal(nio["cutover_opening_receivables"]) != 25 or
                    Decimal(nio["invoices_total"]) != 20 or
                    Decimal(nio["payments"]) != 45 or
                    Decimal(nio["guarantee_refunds"]) != 15 or
                    Decimal(nio["net_customer_receipts"]) != 30 or
                    financial["sources"]["unattributed_movements"]):
                frappe.throw("The close mixed PMS opening balances with new sales or cash")
            from hospitality_suite.reconciliation import differences as reconciliation_differences
            frappe.db.savepoint("hs_cutover_reconciliation_probe")
            try:
                frappe.db.set_value("HS Payment", historical_refund.name,
                    "pms_journal", None, update_modified=False)
                frappe.db.set_value("HS Treasury Movement", historical_loan.name,
                    "pms_journal", None, update_modified=False)
                frappe.db.set_value("Sales Invoice", opening_invoice,
                    "docstatus", 2, update_modified=False)
                detected = reconciliation_differences(migrated_property)
                if (not any(row["type"] == "Payment" and
                        row["source"] == historical_refund.name for row in detected) or
                        not any(row["type"] == "Treasury movement" and
                            row["source"] == historical_loan.name for row in detected) or
                        not any(row["type"] == "Cutover opening" and
                            row["source"] == opening_invoice for row in detected)):
                    frappe.throw("Reconciliation hid an altered PMS origin or opening voucher")
            finally:
                frappe.db.rollback(save_point="hs_cutover_reconciliation_probe")
            try:
                suite_api.execute(prop.name, "daily_close",
                    "cutover-close-unreviewed-" + suffix, {"confirm": True})
            except frappe.ValidationError as exc:
                if "resumen del cierre cambió" not in str(exc):
                    raise
            else:
                frappe.throw("The close accepted confirmation without review")
            confirmed_close = suite_api.execute(prop.name, "daily_close",
                "cutover-close-confirm-" + suffix,
                {"confirm": True, "review_acceptance": close_review["review_acceptance"]})
            if (confirmed_close["status"] != "Closed" or
                    frappe.db.get_value("HS Daily Close", confirmed_close["close"],
                        "status") != "Closed" or
                    str(frappe.db.get_value("HS Property", prop.name,
                        "business_date")) != str(today + timedelta(days=1))):
                frappe.throw("The ERPNext cutover day did not close")
            original_close_summary = frappe.db.get_value("HS Daily Close",
                confirmed_close["close"], "summary")
            frappe.db.savepoint("hs_cutover_close_revision_probe")
            try:
                reopened = suite_api.execute(prop.name, "reopen_day",
                    "cutover-close-reopen-" + suffix,
                    {"close": confirmed_close["close"],
                     "reason": "Revisión adicional del día"})
                second_review = suite_api.execute(prop.name, "daily_close",
                    "cutover-close-second-review-" + suffix, {})
                second_close = suite_api.execute(prop.name, "daily_close",
                    "cutover-close-second-confirm-" + suffix,
                    {"confirm": True,
                     "review_acceptance": second_review["review_acceptance"]})
                first_saved = suite_api.erp_close_detail(prop.name,
                    confirmed_close["close"])
                later_saved = suite_api.erp_close_detail(prop.name,
                    second_close["close"])
                page = suite_api.erp_close_history(prop.name, str(today), 0, 1)
                next_page = suite_api.erp_close_history(prop.name,
                    str(today), 1, 1)
                if (reopened["status"] != "Reopened" or
                        second_review["close"] == confirmed_close["close"] or
                        second_close["close"] == confirmed_close["close"] or
                        first_saved["revision"] != 1 or
                        first_saved["status"] != "Reopened" or
                        later_saved["revision"] != 2 or
                        later_saved["status"] != "Closed" or
                        frappe.db.get_value("HS Daily Close",
                            confirmed_close["close"], "summary") !=
                            original_close_summary or
                        not page["has_more"] or not next_page["rows"] or
                        page["rows"][0].name == next_page["rows"][0].name):
                    frappe.throw("Reopening overwrote an immutable close snapshot")
            finally:
                frappe.db.rollback(save_point="hs_cutover_close_revision_probe")
            opening_gl = frappe.db.count("GL Entry",
                {"company": target_company.name})
            record_name = frappe.db.get_value("HS Cutover Run",
                {"migration_reference": reference}, "name")
            if (not first["cutover_performed"] or not first.get("backup", {}).get("sha256") or
                    not opening_gl or not record_name or
                    frappe.db.count("HS Cutover Run") != 1):
                frappe.throw("Activation did not save one durable cutover receipt")
            replay = pms_cutover_activation.activate_validated(mapping,
                source_sha256=plan["source_sha256"],
                plan_sha256=plan["plan_sha256"],
                link_sha256=manifest["link_sha256"],
                migration_reference=reference,
                backup_manifest=backup_manifest)
            if replay != first:
                frappe.throw("A repeated activation changed its result: " +
                    ", ".join(key for key in first if first[key] != replay.get(key)))
            if (frappe.db.count("GL Entry", {"company": target_company.name}) !=
                    opening_gl or frappe.db.count("HS Cutover Run") != 1):
                frappe.throw("A repeated activation duplicated its opening")
            for override in ({"plan_sha256": "0" * 64},
                             {"migration_reference": reference + "-DIFFERENT"}):
                request = {"source_sha256": plan["source_sha256"],
                    "plan_sha256": plan["plan_sha256"],
                    "link_sha256": manifest["link_sha256"],
                    "migration_reference": reference,
                    "backup_manifest": backup_manifest, **override}
                try:
                    pms_cutover_activation.activate_validated(mapping, **request)
                except frappe.ValidationError:
                    pass
                else:
                    frappe.throw("A conflicting activation request was accepted")
            changed_mapping = deepcopy(mapping)
            changed_mapping["properties"][prop.name]["target_settings"][
                "tax_policy_confirmed"] = True
            try:
                pms_cutover_activation.activate_validated(changed_mapping,
                    source_sha256=plan["source_sha256"],
                    plan_sha256=plan["plan_sha256"],
                    link_sha256=manifest["link_sha256"],
                    migration_reference=reference,
                    backup_manifest=backup_manifest)
            except frappe.ValidationError:
                pass
            else:
                frappe.throw("A changed mapping replay was accepted")
            record = frappe.get_doc("HS Cutover Run", record_name)
            record.result_json = "{}"
            try:
                record.save(ignore_permissions=True)
            except frappe.PermissionError:
                pass
            else:
                frappe.throw("The cutover receipt was editable")
            try:
                frappe.delete_doc("HS Cutover Run", record_name,
                                  ignore_permissions=True)
            except frappe.PermissionError:
                pass
            else:
                frappe.throw("The cutover receipt was deletable")
        finally:
            frappe.db.rollback(save_point="hs_cutover_idempotency_probe")
            pms_cutover_activation._clear_cutover_metadata()
        if (frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                frappe.db.count("HS Cutover Run") or
                frappe.db.count("GL Entry", {"company": target_company.name})):
            frappe.throw("Idempotency probe did not roll back the activation")
        from hospitality_suite.standalone_accounting import provider

        with patch("hospitality_suite.controllers.PMSCutoverRunDocument.validate",
                   side_effect=RuntimeError("Injected receipt failure")):
            try:
                pms_cutover_activation.activate_validated(mapping,
                    source_sha256=plan["source_sha256"],
                    plan_sha256=plan["plan_sha256"],
                    link_sha256=manifest["link_sha256"],
                    migration_reference="HS-RECEIPT-FAIL-" + suffix)
            except RuntimeError as exc:
                if str(exc) != "Injected receipt failure":
                    raise
            else:
                frappe.throw("Receipt failure was not propagated")
        if (frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                frappe.db.count("HS Cutover Run") or
                frappe.db.count("GL Entry", {"company": target_company.name})):
            frappe.throw("Failed receipt insert left an opening behind")

        def reject_after_switch(_property):
            if (provider() != "erpnext" or
                    not frappe.db.count("GL Entry", {"company": target_company.name})):
                frappe.throw("Injected failure happened before activation")
            raise RuntimeError("Injected failure after provider switch")

        with patch("hospitality_suite.install.validate_financial_configuration",
                   side_effect=reject_after_switch):
            try:
                pms_cutover_activation.rehearse_activation(mapping,
                    source_sha256=plan["source_sha256"],
                    plan_sha256=plan["plan_sha256"],
                    link_sha256=manifest["link_sha256"],
                    migration_reference="HS-REHEARSAL-FAIL-" + suffix)
            except RuntimeError as exc:
                if str(exc) != "Injected failure after provider switch":
                    raise
            else:
                frappe.throw("Activation failure was not propagated")
        if (frappe.db.get_single_value("HS Site Mode", "provider") != "PMS" or
                frappe.db.get_single_value("HS Site Mode", "migration_reference") or
                frappe.db.get_value("HS Property", prop.name, "company") !=
                    source_company.name or
                frappe.db.count("GL Entry", {"company": target_company.name})):
            frappe.throw("Failed activation did not restore PMS and ERPNext")
        return {"rehearsal_passed": result["rehearsal_passed"],
                "two_hotel_rehearsed": True,
                "property_count": len(result["properties"]),
                "rewritten_rows": result["links"]["rows_updated"],
                "temporary_account_balance": reconciled.get(
                    cfg["temporary_opening_account"], "0")}
    finally:
        if not source_committed:
            frappe.db.rollback(save_point="hs_mixed_cutover_probe")
            if persistent_mapping_path is not None:
                persistent_mapping_path.unlink(missing_ok=True)
        frappe.local.conf.maintenance_mode = previous_maintenance
        frappe.local.hs_cutover_rehearsal = previous_rehearsal
        if backup_dir is not None:
            backup_dir.cleanup()
        if fiscal_bundle_path is not None:
            fiscal_bundle_path.unlink(missing_ok=True)
        if (incident_evidence_path is not None and
                not frappe.db.exists("File", {
                    "file_url": incident_evidence_file.file_url})):
            incident_evidence_path.unlink(missing_ok=True)
        if (maintenance_evidence_path is not None and
                not frappe.db.exists("File", {
                    "file_url": maintenance_evidence_file.file_url})):
            maintenance_evidence_path.unlink(missing_ok=True)


def run_live_day_pass():
    return run(include_live_day_pass=True)


def run_live_day_pass_with_prior_credit():
    return run(include_live_day_pass=True, prior_day_pass_credit=True)


def run_live_day_pass_with_post_collection():
    return run(include_live_day_pass=True,
        post_cutover_day_pass_collection=True)


def run_live_day_pass_with_prior_credit_and_collection():
    return run(include_live_day_pass=True, prior_day_pass_credit=True,
        post_cutover_day_pass_collection=True)


def seed_persistent_day_pass_cutover():
    return run(include_live_day_pass=True, prior_day_pass_credit=True,
        persist_source=True)
