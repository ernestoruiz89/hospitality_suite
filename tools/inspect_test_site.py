import frappe


def inspect():
    return dict(
        now=str(frappe.utils.now_datetime()),
        settings=frappe.db.get_single_value("System Settings", "time_zone"),
        stock=frappe.get_all("Stock Ledger Entry", filters={"item_code":"HS-DEMO-WATER"}, fields=["posting_date","posting_time","actual_qty","qty_after_transaction","warehouse","is_cancelled"]),
        allocations=frappe.db.count("HS Allocation"),
        bins=frappe.get_all("Bin", filters={"item_code":"HS-DEMO-WATER"}, fields=["warehouse","actual_qty"]),
    )


if __name__ == "__main__":
    import json
    import os
    os.chdir("/home/frappe/benches/hospitality-bench/sites")
    frappe.init(site="hospitality.localhost", sites_path="/home/frappe/benches/hospitality-bench/sites")
    frappe.connect()
    try:
        print(json.dumps(inspect(), default=str, indent=2))
    finally:
        frappe.destroy()
