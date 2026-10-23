import unittest

from hospitality_suite.stock_rules import StockValidationError, issue, receipt


class TestStockRules(unittest.TestCase):
    def test_average_cost_and_final_issue_clear_rounding_residue(self):
        first = receipt(0, 0, 3, "10.00")
        second = receipt(first["balance_quantity"], first["balance_value"], 1, "4.00")
        self.assertEqual((second["balance_quantity"], second["balance_value"]), ("4", "14.00"))
        partial = issue(second["balance_quantity"], second["balance_value"], 1)
        self.assertEqual(partial["value_delta"], "-3.50")
        final = issue(partial["balance_quantity"], partial["balance_value"], 3)
        self.assertEqual((final["balance_quantity"], final["balance_value"]), ("0", "0.00"))

    def test_reject_negative_stock_and_invalid_quantity(self):
        for bad in (0, -1, "NaN", "0.0000001", True):
            with self.subTest(bad=bad), self.assertRaises(StockValidationError):
                issue(2, 10, bad)
        with self.assertRaises(StockValidationError):
            issue(2, 10, 3)


if __name__ == "__main__":
    unittest.main()
