from unittest import TestCase
from unittest.mock import patch

import frappe

from hospitality_suite.time import business_window


class TestBusinessWindow(TestCase):
    def window(self,day,zone,cutoff):
        with patch('hospitality_suite.time.get_system_timezone',return_value='UTC'):
            return business_window(frappe._dict(business_date=day,time_zone=zone,close_time=cutoff))

    def test_midnight_cutoff_is_not_replaced_by_default(self):
        value=self.window('2026-12-31','America/Managua','00:00:00')
        self.assertEqual(str(value['starts_at']),'2026-12-31 06:00:00')
        self.assertEqual(str(value['ends_at']),'2027-01-01 06:00:00')
        self.assertEqual(value['close_time'],'00:00:00')

    def test_dst_boundaries_have_23_or_25_elapsed_hours(self):
        for day,hours in [('2026-03-28',23),('2026-10-24',25)]:
            value=self.window(day,'Europe/Berlin','06:00:00')
            self.assertEqual((value['ends_at']-value['starts_at']).total_seconds()/3600,hours)
            self.assertIn('T06:00:00',value['local_starts_at'])
            self.assertIn('T06:00:00',value['local_ends_at'])
