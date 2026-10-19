from datetime import datetime
from zoneinfo import ZoneInfo
import unittest

from hospitality_suite.pricing import calculate, money
from hospitality_suite.reports import union_seconds


class TestPricing(unittest.TestCase):
    def setUp(self):
        self.rate = dict(mode="Motel", amount="450", currency="NIO", block_hours=3,
                         extra_hour_rate="150", grace_minutes=10, rounding_minutes=60,
                         included_people=2, additional_person_rate=50)
        self.start = datetime(2026, 12, 31, 23, 0, tzinfo=ZoneInfo("America/Managua"))

    def test_midnight_and_year_boundary(self):
        end = datetime(2027, 1, 1, 2, 0, tzinfo=self.start.tzinfo)
        self.assertEqual(calculate(self.rate, self.start, end)["amount"], "450.00")

    def test_grace_exact_limit_and_fraction(self):
        from datetime import timedelta
        self.assertEqual(calculate(self.rate, self.start, self.start + timedelta(minutes=190))["amount"], "450.00")
        self.assertEqual(calculate(self.rate, self.start, self.start + timedelta(minutes=190, seconds=1))["amount"], "600.00")

    def test_hotel_nights_and_extra_people(self):
        from datetime import timedelta
        self.rate.update(mode="Hotel", amount="1500")
        result = calculate(self.rate, self.start, self.start + timedelta(days=3), people=3)
        self.assertEqual(result["amount"], "4650.00")

    def test_dst_uses_elapsed_instant(self):
        self.rate.update(block_hours=1, grace_minutes=0)
        zone = ZoneInfo("America/New_York")
        # Fall-back spans three wall hours, four elapsed hours.
        start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        end = datetime(2026, 11, 1, 3, 30, tzinfo=zone)
        self.assertEqual(calculate(self.rate, start, end)["amount"], "900.00")

    def test_decimal_rounding(self):
        self.assertEqual(str(money("1.005")), "1.01")

    def test_snapshot_copies_rules(self):
        from datetime import timedelta
        snapshot = calculate(self.rate, self.start, self.start + timedelta(hours=3))
        self.rate["amount"] = 800
        self.assertEqual(snapshot["rules"]["amount"], "450")

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            calculate(self.rate, self.start, self.start)

    def test_union_never_double_counts(self):
        from datetime import timedelta
        self.assertEqual(union_seconds([(self.start, self.start+timedelta(hours=2)),
                                        (self.start+timedelta(hours=1), self.start+timedelta(hours=3))]), 10800)
