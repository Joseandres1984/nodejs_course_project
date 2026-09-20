from __future__ import annotations

import importlib
import os
import sys
import types
import unittest
from unittest import mock


class LumenZeroPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_app = sys.modules.get("app")
        self.original_d1 = sys.modules.pop("d1_persistence_runtime", None)
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "LUMEN_ZERO_COST_MODE": "true",
                "LUMEN_D1_ACCOUNT_ID": "account-test",
                "LUMEN_D1_DATABASE_ID": "db-test",
                "LUMEN_D1_API_TOKEN": "token-test",
                "LUMEN_D1_CHUNK_CHARS": "100000",
            },
            clear=False,
        )
        self.env_patch.start()

        fake = types.ModuleType("app")
        fake.STATE = {
            "buyers": [{"name": "Comprador de prueba", "need": "instrumentación"}],
            "activity": [{"msg": "áéíóú ñ"}],
            "large": "x" * 250000,
        }
        fake.DB_STATUS = {}
        fake.DATABASE_URL = "legacy-postgres"
        fake.default_state = lambda: {"buyers": [], "activity": []}
        fake.ensure_commerce_state = lambda state: None
        fake.ensure_db = lambda: False
        fake.load_state = lambda: False
        fake.save_state = lambda: False
        sys.modules["app"] = fake
        self.fake_app = fake
        self.d1 = importlib.import_module("d1_persistence_runtime")

    def tearDown(self):
        self.env_patch.stop()
        sys.modules.pop("d1_persistence_runtime", None)
        if self.original_app is None:
            sys.modules.pop("app", None)
        else:
            sys.modules["app"] = self.original_app
        if self.original_d1 is not None:
            sys.modules["d1_persistence_runtime"] = self.original_d1

    def test_state_round_trip_is_lossless_and_chunked(self):
        chunks, digest, raw_bytes = self.d1._encode_state()
        decoded = self.d1._decode_state(chunks, digest)
        self.assertGreater(raw_bytes, 250000)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(decoded, self.fake_app.STATE)

    def test_adapter_replaces_only_persistence_surface(self):
        self.assertIs(self.fake_app.load_state, self.d1.load_state)
        self.assertIs(self.fake_app.save_state, self.d1.save_state)
        self.assertIs(self.fake_app.ensure_db, self.d1.ensure_db)
        self.assertEqual(self.fake_app.DB_STATUS.get("backend"), "cloudflare_d1")
        self.assertEqual(self.fake_app.DATABASE_URL, "")


class LumenZeroScoutTests(unittest.TestCase):
    def test_rss_parser_normalizes_public_results(self):
        import zero_scout_runtime as zero_scout

        rss = b'''<?xml version="1.0"?><rss><channel>
          <item><title>Proveedor &amp; Industrial</title><link>https://example.com/catalogo?a=1#frag</link><description><![CDATA[<b>Stock</b> y catalogo publico]]></description></item>
          <item><title>Segundo</title><link>https://example.org/licitacion</link><description>Compra publica</description></item>
        </channel></rss>'''

        class Response:
            headers = {"content-type": "application/rss+xml"}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit=-1): return rss

        with mock.patch("urllib.request.urlopen", return_value=Response()):
            rows = zero_scout._rss_search('"instrumentación" proveedor Argentina')

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "Proveedor & Industrial")
        self.assertEqual(rows[0]["url"], "https://example.com/catalogo?a=1")
        self.assertIn("Stock", rows[0]["snippet"])
        self.assertFalse(zero_scout.zero_status()["paid_search"])
        self.assertFalse(zero_scout.zero_status()["requires_api_key"])


if __name__ == "__main__":
    unittest.main()
