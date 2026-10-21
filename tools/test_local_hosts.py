"""Local runtime preflight cases; no system file is changed by these tests."""
import unittest

from configure_local_hosts import missing_aliases, SITES


class TestLocalHosts(unittest.TestCase):
    def test_browser_aliases_do_not_come_from_localhost_line(self):
        self.assertEqual(missing_aliases('127.0.0.1 localhost\n::1 localhost\n'), list(SITES))

    def test_existing_aliases_comments_case_and_unrelated_sites(self):
        self.assertEqual(missing_aliases('10.1.2.3 other.example\n127.0.0.1 HOSPITALITY.LOCALHOST # existing alias\n'
                                        '127.0.0.1 hospitality-acceptance.localhost unrelated.localhost\n'), [])

    def test_ipv6_only_needs_explicit_ipv4_for_the_native_transport(self):
        self.assertEqual(missing_aliases('::1 hospitality.localhost\n127.0.0.1 hospitality-acceptance.localhost\n'), [SITES[0]])

    def test_conflicting_alias_is_rejected_even_after_valid_mapping(self):
        for address in ('192.0.2.10', '127.0.0.2', '2001:db8::1', 'invalid'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                missing_aliases('127.0.0.1 hospitality.localhost\n'+address+' hospitality.localhost\n')

    def test_commented_alias_is_not_a_mapping(self):
        self.assertEqual(missing_aliases('# 127.0.0.1 hospitality.localhost\n127.0.0.1 localhost # hospitality-acceptance.localhost\n'), list(SITES))


if __name__ == '__main__':
    unittest.main(verbosity=2)
