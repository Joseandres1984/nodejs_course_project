import unittest
from urllib.parse import parse_qs, urlsplit

from viator_affiliate_core import ViatorAffiliateError, build_viator_affiliate_url


class ViatorAffiliateCoreTests(unittest.TestCase):
    def build(self, url: str) -> str:
        return build_viator_affiliate_url(url, pid="P00322694")

    def test_adds_expected_tracking(self):
        result = self.build("https://www.viator.com/San-Juan/d903-ttd")
        parts = urlsplit(result)
        params = parse_qs(parts.query)
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(parts.hostname, "www.viator.com")
        self.assertEqual(params["pid"], ["P00322694"])
        self.assertEqual(params["mcid"], ["42383"])
        self.assertEqual(params["medium"], ["link"])
        self.assertEqual(params["medium_version"], ["selector"])

    def test_replaces_tracking_and_preserves_business_query(self):
        result = self.build(
            "https://www.viator.com/foo?pid=OLD&mcid=1&foo=bar&medium=old&medium_version=old"
        )
        params = parse_qs(urlsplit(result).query)
        self.assertEqual(params["pid"], ["P00322694"])
        self.assertEqual(params["foo"], ["bar"])
        self.assertEqual(len(params["pid"]), 1)

    def test_rejects_non_viator_host(self):
        with self.assertRaises(ViatorAffiliateError):
            self.build("https://example.com/trip")

    def test_rejects_lookalike_host(self):
        with self.assertRaises(ViatorAffiliateError):
            self.build("https://viator.com.evil.example/trip")

    def test_rejects_embedded_credentials(self):
        with self.assertRaises(ViatorAffiliateError):
            self.build("https://user:pass@viator.com/trip")


if __name__ == "__main__":
    unittest.main()
