"""Check the read-only PMS payloads consumed by the React routes on a synthetic site.

Run from the Frappe bench's sites directory with its Python environment.
This checks the top-level API contract and never commits. It does not replace
browser acceptance or financial transaction tests.
"""

import argparse
from pathlib import Path

import frappe

from hospitality_suite import api


REQUIRED = {
    "home_queue_summary": "property date time_zone counts server_time",
    "room_board_snapshot": "property time_zone checked_at rooms counts",
    "pms_cash_snapshot": "base_currency accepted_currencies methods categories concepts customers folios bookings shifts movements refundable deposit_accounts receivables",
    "pms_fiscal_snapshot": "currency documents liability_accounts property_modified seller_name seller_tax_id series tax_policy_confirmed tax_profiles tax_regime",
    "pms_departure_snapshot": "currency property stays",
    "pms_service_snapshot": "currency stays products warehouses balances requests",
    "pms_inventory_snapshot": "currency products warehouses balances movements equity_accounts clearing_accounts expense_accounts income_accounts transfers counts",
    "pms_purchase_snapshot": "currency currencies suppliers products warehouses accounts methods shifts purchases opening_payables opening_supplier_credits orders returns payments",
    "pms_laundry_snapshot": "rates orders stays folios products last_30_days",
    "pms_financing_snapshot": "currency user concepts accounts methods shifts movements sources",
    "pms_petty_snapshot": "active currency user responsible account overage_account shortage_account balance expected_cash pending_expenses reconciled initial_fund_exists accounts categories methods shifts expenses renditions handovers funds users",
    "pms_reception_snapshot": "currency mode guest_id_required portal_enabled parties guests categories rooms rates agents experiences bookings booking_lines allocations stays folios",
    "pms_travel_experiences_snapshot": "currency agents experiences orders property_modified commission_expense_account commission_payable_account commission_accounts methods shifts commissions products suppliers customers receivable_accounts income_accounts tax_profiles bookings stays folios contribution",
    "pms_day_pass_snapshot": "currency time_zone property_modified receivable_account receivable_accounts product day_passes return_series return_methods return_shifts customers guests",
    "setup_board": "property categories rooms rates currencies pms_variance_accounts",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", required=True, help="Synthetic hs-pms-smoke site")
    args = parser.parse_args()
    if not args.site.startswith("hs-pms-smoke") or not Path("common_site_config.json").is_file():
        parser.error("Run only from the synthetic Frappe bench sites directory")

    frappe.init(site=args.site, sites_path=str(Path.cwd()))
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        base = api.bootstrap()
        if base.get("accounting_provider") != "pms" or not base.get("properties"):
            raise AssertionError("The test site must have PMS accounting and at least one property")
        if base.get("user") != "Administrator":
            raise AssertionError("bootstrap must identify the current user for scoped UI preferences")
        for property_row in base["properties"]:
            for method, field_names in REQUIRED.items():
                payload = getattr(api, method)(property_row["name"])
                if not isinstance(payload, dict):
                    raise AssertionError(f"{method} did not return an object")
                missing = set(field_names.split()) - payload.keys()
                if missing:
                    raise AssertionError(f"{method} lacks {sorted(missing)}")
                if method == "home_queue_summary":
                    if payload["property"] != property_row["name"] or set(payload["counts"]) != {
                            "arrivals", "departures", "hosted", "accounts"}:
                        raise AssertionError("Home queues are not scoped or complete")
                if method == "room_board_snapshot":
                    if payload["property"] != property_row["name"] or any(
                            not {"name", "room_number", "category", "category_label", "floor",
                                 "zone", "active", "cleaning_status", "arrival", "departure",
                                 "work", "blocked", "occupied"} <= row.keys()
                            for row in payload["rooms"]):
                        raise AssertionError("Room filters lack their scoped input fields")
        profile = api.my_user_settings()
        profile_fields = {"user", "email", "first_name", "last_name", "language", "time_zone", "modified", "languages"}
        if profile_fields - profile.keys():
            raise AssertionError(f"my_user_settings lacks {sorted(profile_fields - profile.keys())}")
        print(f"PMS React contract OK: {len(base['properties'])} properties, {len(REQUIRED)} snapshots each, personal settings")
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    main()
