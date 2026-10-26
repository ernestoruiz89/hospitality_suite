"""Financial invariants that can run before a Frappe test site is available."""

import unittest

from hospitality_suite.ledger_rules import (LedgerValidationError, currency_line,
                                             inverse_lines, normalize_lines,
                                             rate_for_base)


class TestLedgerRules(unittest.TestCase):
    def test_balanced_entry_and_exact_reversal(self):
        lines, total = normalize_lines([
            {"account": "cash", "debit": "115.00", "credit": 0},
            {"account": "revenue", "debit": 0, "credit": "100.00"},
            {"account": "tax", "debit": 0, "credit": "15.00"},
        ])
        self.assertEqual(total, "115.00")
        reversed_lines, reversed_total = normalize_lines(inverse_lines(lines))
        self.assertEqual(reversed_total, total)
        self.assertEqual(sum(float(line["credit"]) for line in reversed_lines), 115)

    def test_reject_unbalanced_or_one_sided_entry(self):
        for lines in (
            [{"account": "cash", "debit": 10, "credit": 0}],
            [{"account": "cash", "debit": 10, "credit": 0}, {"account": "revenue", "debit": 0, "credit": 9}],
            [{"account": "cash", "debit": 10, "credit": 10}, {"account": "revenue", "debit": 0, "credit": 10}],
        ):
            with self.subTest(lines=lines), self.assertRaises(LedgerValidationError):
                normalize_lines(lines)

    def test_reject_invalid_money_and_subcent_values(self):
        for invalid in ("NaN", "Infinity", "-1", "0.001", True, "1e999999"):
            with self.subTest(invalid=invalid), self.assertRaises(LedgerValidationError):
                normalize_lines([{"account": "cash", "debit": invalid, "credit": 0},
                                 {"account": "revenue", "debit": 0, "credit": "1.00"}])

    def test_foreign_account_amount_rate_and_reversal(self):
        line = currency_line({"account": "usd", "debit": "365.00", "credit": "0",
                              "debit_in_account_currency": "10.00", "credit_in_account_currency": "0",
                              "exchange_rate": "36.500000000"}, "USD", "NIO")
        self.assertEqual(line["account_currency"], "USD")
        self.assertEqual(line["debit_in_account_currency"], "10.00")
        reversed_line = inverse_lines([line])[0]
        self.assertEqual(reversed_line["credit_in_account_currency"], "10.00")
        self.assertEqual(reversed_line["credit"], "365.00")
        with self.assertRaises(LedgerValidationError):
            currency_line({**line, "exchange_rate": "36.60"}, "USD", "NIO")
        with self.assertRaises(LedgerValidationError):
            currency_line({**line, "account_currency": "EUR"}, "USD", "NIO")

    def test_historical_rate_reproduces_booked_base_to_the_cent(self):
        rate = rate_for_base("3.00", "100.00")
        line = currency_line({"account": "payable", "debit": "100.00",
            "credit": "0", "debit_in_account_currency": "3.00",
            "credit_in_account_currency": "0", "exchange_rate": rate},
            "USD", "NIO")
        self.assertEqual(line["debit"], "100.00")
        with self.assertRaises(LedgerValidationError):
            rate_for_base("100000000000.00", "0.01")


if __name__ == "__main__":
    unittest.main()
