"""Source inventory must reconcile each hotel's warehouse value to its GL."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hospitality_suite.erp_to_pms_preflight import (
    _delivered_service_issue, _stock_ledger_valuation)


class TestReverseStockPreflight(unittest.TestCase):
    def setUp(self):
        self.property = SimpleNamespace(name="HOTEL-A", company="COMPANY-A")
        self.warehouses = {
            "WAREHOUSE-A": SimpleNamespace(account="STOCK-A"),
            "WAREHOUSE-B": SimpleNamespace(account="STOCK-B"),
        }

    def test_matching_balances_do_not_query_transfers(self):
        ledger = {"lines": [
            {"account": "STOCK-A", "account_type": "Stock", "debit": "10", "credit": "0"},
            {"account": "STOCK-B", "account_type": "Stock", "debit": "20", "credit": "0"},
        ]}
        stock = {"warehouses": list(self.warehouses), "positions": [
            {"warehouse": "WAREHOUSE-A", "stock_value": "10"},
            {"warehouse": "WAREHOUSE-B", "stock_value": "20"},
        ]}
        blockers = []
        with patch("erpnext.stock.get_warehouse_account_map",
                   return_value=self.warehouses), patch(
                   "hospitality_suite.erp_to_pms_preflight.frappe.db.sql") as sql:
            _stock_ledger_valuation(self.property, ledger, stock, blockers)
        self.assertEqual(blockers, [])
        sql.assert_not_called()

    def test_offsetting_accounts_still_block_and_identify_transfer(self):
        ledger = {"lines": [
            {"account": "STOCK-A", "account_type": "Stock", "debit": "0", "credit": "10"},
            {"account": "STOCK-B", "account_type": "Stock", "debit": "30", "credit": "0"},
        ]}
        stock = {"warehouses": list(self.warehouses), "positions": [
            {"warehouse": "WAREHOUSE-A", "stock_value": "10"},
            {"warehouse": "WAREHOUSE-B", "stock_value": "10"},
        ]}
        transfer = SimpleNamespace(voucher="STE-001", voucher_property="HOTEL-A",
            source_warehouse="WAREHOUSE-B", source_property="HOTEL-B",
            target_warehouse="WAREHOUSE-A", target_property="HOTEL-A",
            item_code="ITEM-001", qty=2, basic_amount=20)
        blockers = []
        with patch("erpnext.stock.get_warehouse_account_map",
                   return_value=self.warehouses), patch(
                   "hospitality_suite.erp_to_pms_preflight.frappe.db.sql",
                   return_value=[transfer]) as sql:
            _stock_ledger_valuation(self.property, ledger, stock, blockers)
        self.assertEqual([(row["account"], row["difference"]) for row in blockers],
                         [("STOCK-A", "20"), ("STOCK-B", "-20")])
        self.assertEqual(blockers[0]["cross_property_transfers"][0]["voucher"],
                         "STE-001")
        self.assertEqual(sql.call_count, 1)
        self.assertIn("LIMIT 20", sql.call_args.args[0])

    def test_missing_warehouse_account_is_explicit(self):
        stock = {"warehouses": ["UNKNOWN"], "positions": []}
        with patch("erpnext.stock.get_warehouse_account_map", return_value={}):
            blockers = []
            _stock_ledger_valuation(self.property, {"lines": []}, stock, blockers)
        self.assertEqual(blockers, [{"property": "HOTEL-A",
            "code": "property_stock_account_unresolved", "warehouse": "UNKNOWN"}])

    def test_delivered_service_from_another_hotels_warehouse_blocks_cutover(self):
        entry = SimpleNamespace(company="COMPANY-A", hs_property="HOTEL-A",
            docstatus=1, stock_entry_type="Material Issue")
        line = SimpleNamespace(item_code="ITEM-A", warehouse="WAREHOUSE-B",
            actual_qty=-1, stock_value_difference=-10)
        warehouse = SimpleNamespace(company="COMPANY-A",
            hs_property="HOTEL-B", is_group=0)
        row = {"name": "SERVICE-A", "stock_entry": "STE-A",
            "item": "ITEM-A", "quantity": 1}
        blockers = []
        with patch("hospitality_suite.erp_to_pms_preflight.frappe.db.get_value",
                   side_effect=[entry, warehouse]), patch(
                   "hospitality_suite.erp_to_pms_preflight.frappe.get_all",
                   side_effect=[[line], [SimpleNamespace(account="STOCK-A",
                       debit=0, credit=10)] ]):
            issue = _delivered_service_issue(self.property, row, blockers)
        self.assertIsNone(issue)
        self.assertEqual(blockers, [{"property": "HOTEL-A",
            "code": "delivered_service_warehouse_scope_invalid",
            "source": "SERVICE-A", "stock_entry": "STE-A",
            "warehouse": "WAREHOUSE-B"}])


if __name__ == "__main__":
    unittest.main()
