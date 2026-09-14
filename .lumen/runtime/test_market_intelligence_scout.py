from __future__ import annotations

import unittest

import market_intelligence_scout as mis


class MarketIntelligenceScoutTests(unittest.TestCase):
    def test_extracts_jsonld_offer_evidence(self):
        blocks = ["""{
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Acme Meter X100",
          "brand": {"@type": "Brand", "name": "Acme"},
          "model": "X100",
          "mpn": "AC-X100",
          "offers": {
            "@type": "Offer",
            "price": "123.45",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }"""]
        rows = mis.extract_jsonld_products(blocks, "https://shop.example/p/x100")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 123.45)
        self.assertEqual(rows[0]["price_currency"], "USD")
        self.assertEqual(rows[0]["availability"], "InStock")
        self.assertEqual(rows[0]["model"], "X100")

    def test_detects_same_currency_price_asymmetry(self):
        state = {"market_intelligence_observations": []}
        for domain, price in (("a.example", 100), ("b.example", 135)):
            mis.capture_catalog_observation(
                state,
                store={"domain": domain},
                product={
                    "title": "Acme Meter X100",
                    "url": f"https://{domain}/p/x100",
                    "brand": "Acme",
                    "model": "X100",
                    "price": price,
                    "price_currency": "USD",
                    "source": "jsonld_product_offer",
                },
            )
        candidates = mis.detect_opportunities(state)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["status"], "shadow_only")
        self.assertFalse(candidates[0]["execution_allowed"])
        self.assertFalse(candidates[0]["outreach_allowed"])
        self.assertAlmostEqual(candidates[0]["spread_pct"], 35.0)

    def test_never_compares_different_currencies(self):
        state = {"market_intelligence_observations": []}
        rows = [
            ("a.example", 100, "USD"),
            ("b.example", 200000, "ARS"),
        ]
        for domain, price, currency in rows:
            mis.capture_catalog_observation(
                state,
                store={"domain": domain},
                product={
                    "title": "Acme Meter X100",
                    "url": f"https://{domain}/p/x100",
                    "brand": "Acme",
                    "model": "X100",
                    "price": price,
                    "price_currency": currency,
                },
            )
        self.assertEqual(mis.detect_opportunities(state), [])

    def test_requires_two_distinct_sellers(self):
        state = {"market_intelligence_observations": []}
        for suffix, price in (("a", 100), ("b", 150)):
            mis.capture_catalog_observation(
                state,
                store={"domain": "same.example"},
                product={
                    "title": "Acme Meter X100",
                    "url": f"https://same.example/p/{suffix}",
                    "brand": "Acme",
                    "model": "X100",
                    "price": price,
                    "price_currency": "USD",
                },
            )
        self.assertEqual(mis.detect_opportunities(state), [])

    def test_terminal_output_has_no_execution_authority(self):
        state = {"market_intelligence_observations": []}
        report = mis.market_intelligence_tick(state)
        self.assertEqual(report["status"], "shadow")
        self.assertIn("no_outreach", report["authority"])
        self.assertIn("no_purchase", report["authority"])


if __name__ == "__main__":
    unittest.main()
