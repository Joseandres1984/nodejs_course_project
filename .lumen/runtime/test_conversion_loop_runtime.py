import conversion_loop_runtime as loop


def test_catalog_has_six_products_and_tracking():
    state = {"runtime_config": {"conversion_base_url": "https://example.test"}}
    out = loop.build_conversion_catalog(state)
    assert len(out["products"]) == 6
    assert out["autonomy"]["paid_media_spend"] is False
    assert out["autonomy"]["autonomous_outgoing_payment"] is False
    expected_slugs = {"supplier-snapshot", "quote-sanity", "tender-scan", "sourcing-5", "buyer-signals", "export-pulse"}
    assert {row["slug"] for row in out["products"]} == expected_slugs
    for row in out["products"]:
        assert row["landing_url"].startswith("https://example.test/offer/")
        assert "campaign=machine-" in row["landing_url"]
        assert row["price_usd"] > 0
