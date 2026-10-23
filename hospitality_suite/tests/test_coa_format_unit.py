"""ERPNext CoA eight-column interchange without a Frappe runtime."""

import unittest

from hospitality_suite.coa_format import ChartFormatError, HEADERS, export_csv, parse_csv


class TestCoAFormat(unittest.TestCase):
    def test_numberless_roots_foreign_currency_and_roundtrip(self):
        lines = [",".join(HEADERS)]
        for name, root in (("Assets", "Asset"), ("Liabilities", "Liability"),
                           ("Equity", "Equity"), ("Income", "Income"), ("Expenses", "Expense")):
            lines.append(f"{name},,,,1,,{root},")
        lines.append("Dollar Bank,Assets,101,,0,Bank,Asset,USD")
        parsed = parse_csv("\n".join(lines).encode(), "NIO")
        self.assertEqual(len(parsed), 6)
        bank = parsed[-1]
        self.assertEqual(bank["account_currency"], "USD")
        self.assertEqual(bank["parent_key"], ("Assets", ""))
        accounts = []
        names = {}
        for row in parsed:
            name = str(row["row"])
            accounts.append({**row, "name": name,
                             "parent_account": names.get(row["parent_key"])})
            names[row["key"]] = name
        again = parse_csv(export_csv(accounts, "NIO").encode("utf-8"), "NIO")
        self.assertEqual([(row["account_name"], row["account_number"], row["account_currency"])
                          for row in again],
                         [(row["account_name"], row["account_number"], row["account_currency"])
                          for row in parsed])

    def test_reject_missing_roots_and_unknown_parent(self):
        with self.assertRaises(ChartFormatError):
            parse_csv((",".join(HEADERS) + "\nAssets,,,,1,,Asset,NIO").encode(), "NIO")
        rows = [",".join(HEADERS)]
        for name, root in (("Assets", "Asset"), ("Liabilities", "Liability"),
                           ("Equity", "Equity"), ("Income", "Income"), ("Expenses", "Expense")):
            rows.append(f"{name},,,,1,,{root},")
        rows.append("Orphan,Not Here,101,,0,Bank,Asset,USD")
        with self.assertRaises(ChartFormatError):
            parse_csv("\n".join(rows).encode(), "NIO")
