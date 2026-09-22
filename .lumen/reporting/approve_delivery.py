#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_PAY_TO = "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28"
EXPECTED_NETWORK = "eip155:8453"
PAID_RECEIPT_STATUSES = {"settled_verified", "redeemed_queued"}
PAID_ORDER_STATUSES = {"x402_paid_queued"}
BLOCK_MARKERS = ("technical canary", "canary", "fixture", "cliente de prueba", "empresa de prueba", "demo-", "qa-")
RESERVED_HOSTS = {"example.com", "www.example.com", "example.org", "www.example.org", "example.net", "www.example.net", "example.invalid", "localhost"}

PRODUCTS = {
    "MP-SUPPLIER-SNAPSHOT": {"slug": "supplier-snapshot", "title": "Supplier Snapshot", "tier": "micro", "service_id": "SRV-SUPPLIERCHECK"},
    "MP-QUOTE-SANITY": {"slug": "quote-sanity", "title": "Quote Sanity Check", "tier": "micro", "service_id": "SRV-QUOTECHECK"},
    "MP-TENDER-SCAN": {"slug": "tender-scan", "title": "Tender Quick Scan", "tier": "micro", "service_id": "SRV-TENDER-HUNTER"},
    "MP-SOURCING-5": {"slug": "sourcing-5", "title": "Supplier Shortlist 5", "tier": "micro", "service_id": "SRV-SOURCING-EXPRESS"},
    "MP-BUYER-SIGNALS": {"slug": "buyer-signals", "title": "Buyer Signal Scan", "tier": "micro", "service_id": "SRV-B2B-PROSPECTING"},
    "MP-EXPORT-PULSE": {"slug": "export-pulse", "title": "Export Market Pulse", "tier": "micro", "service_id": "SRV-EXPORT-SCOUT"},
}
SERVICES = {
    "SRV-QUOTECHECK": {"title": "QuoteCheck Global", "tier": "full"},
    "SRV-SUPPLIERCHECK": {"title": "SupplierCheck", "tier": "full"},
    "SRV-TENDER-HUNTER": {"title": "Tender Hunter Global", "tier": "full"},
    "SRV-SOURCING-EXPRESS": {"title": "Sourcing Express", "tier": "full"},
    "SRV-B2B-PROSPECTING": {"title": "Prospección B2B", "tier": "full"},
    "SRV-EXPORT-SCOUT": {"title": "Export Scout", "tier": "full"},
}


def emit(ok, **payload):
    print(json.dumps({"ok": ok, **payload}, ensure_ascii=False, sort_keys=True))


def fail(code, detail=None):
    emit(False, error=code, detail=detail or "")
    raise SystemExit(1)


def load_json(path, label):
    p = Path(path)
    if not p.exists():
        fail(f"{label}_missing", str(p))
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{label}_invalid_json", str(exc))
    if not isinstance(value, dict):
        fail(f"{label}_root_must_be_object")
    return value


def obj(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def txt(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def truthy(value):
    if value is True or value == 1:
        return True
    return txt(value).casefold() in {"true", "1", "yes", "ok", "verified", "settled"}


def normalize(value):
    return re.sub(r"\s+", " ", txt(value)).casefold()


def require(value, field, minimum=1):
    value = txt(value)
    if len(value) < minimum:
        fail("required_value_missing", {"field": field, "min": minimum, "value": value[:120]})
    return value


def no_test_markers(value, field):
    lowered = normalize(value)
    if any(marker in lowered for marker in BLOCK_MARKERS):
        fail("test_or_fixture_marker_forbidden", {"field": field, "value": txt(value)[:160]})


def valid_delivery_email(raw):
    email = txt(raw).casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        return False
    host = email.rsplit("@", 1)[-1]
    if host in RESERVED_HOSTS or host.endswith(".invalid"):
        return False
    return True


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def page_range_ok(tier, pages):
    if tier == "micro":
        return 1 <= pages <= 3
    return 4 <= pages <= 12


def main():
    ap = argparse.ArgumentParser(description="Fail-closed LUMEN production delivery approval")
    ap.add_argument("--context", required=True, help="JSON produced from authoritative paid-order data")
    ap.add_argument("--report-json", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--quality-json", required=True, help="JSON emitted by validate_pdf.py")
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()

    context = load_json(args.context, "context")
    report = load_json(args.report_json, "report")
    quality = load_json(args.quality_json, "quality")
    pdf = Path(args.pdf).resolve()
    manifest_path = Path(args.manifest).resolve()

    if not pdf.exists() or not pdf.is_file():
        fail("pdf_missing", str(pdf))
    if pdf.stat().st_size < 12000:
        fail("pdf_too_small", pdf.stat().st_size)

    receipt = context.get("receipt") or {}
    order = context.get("order") or {}
    brief = context.get("brief") or {}
    if not all(isinstance(x, dict) and x for x in (receipt, order, brief)):
        fail("authoritative_context_incomplete", {"receipt": bool(receipt), "order": bool(order), "brief": bool(brief)})

    receipt_id = require(receipt.get("id"), "receipt.id", 8)
    order_id = require(order.get("id"), "order.id", 8)
    brief_id = require(brief.get("id"), "brief.id", 8)
    report_id = require(report.get("report_id"), "report.report_id", 8)
    for field, value in (("receipt.id", receipt_id), ("order.id", order_id), ("brief.id", brief_id), ("report.report_id", report_id)):
        no_test_markers(value, field)

    receipt_status = txt(receipt.get("status"))
    if receipt_status not in PAID_RECEIPT_STATUSES:
        fail("payment_not_settled", {"receipt_id": receipt_id, "status": receipt_status})
    if txt(receipt.get("network")) != EXPECTED_NETWORK:
        fail("payment_network_mismatch", {"expected": EXPECTED_NETWORK, "actual": receipt.get("network")})
    if txt(receipt.get("pay_to")).casefold() != EXPECTED_PAY_TO.casefold():
        fail("payment_recipient_mismatch")
    if txt(receipt.get("currency")).upper() != "USD":
        fail("payment_currency_mismatch", receipt.get("currency"))
    if float(receipt.get("amount_usd") or 0) <= 0:
        fail("payment_amount_invalid", receipt.get("amount_usd"))

    receipt_meta = obj(receipt.get("request_metadata"))
    settlement = obj(receipt_meta.get("settlement"))
    if settlement.get("success") is not True:
        fail("settlement_success_evidence_missing", {"receipt_id": receipt_id})
    if not txt(settlement.get("transaction")):
        fail("settlement_transaction_missing", {"receipt_id": receipt_id})
    if txt(settlement.get("network")) and txt(settlement.get("network")) != EXPECTED_NETWORK:
        fail("settlement_network_mismatch", settlement.get("network"))

    order_status = txt(order.get("status"))
    if order_status not in PAID_ORDER_STATUSES:
        fail("order_not_paid_queued", {"order_id": order_id, "status": order_status})
    order_meta = obj(order.get("remote_metadata"))
    if not truthy(order_meta.get("payment_verified")) or not truthy(order_meta.get("payment_settled")):
        fail("order_payment_truth_missing", {"verified": order_meta.get("payment_verified"), "settled": order_meta.get("payment_settled")})
    if txt(order_meta.get("x402_receipt_id")) != receipt_id:
        fail("order_receipt_link_mismatch")
    if txt(order.get("item_id")) != txt(receipt.get("product_id")):
        fail("order_product_receipt_mismatch")
    if txt(order.get("service_id")) != txt(receipt.get("service_id")):
        fail("order_service_receipt_mismatch")
    if abs(float(order.get("amount_usd") or 0) - float(receipt.get("amount_usd") or 0)) > 0.000001:
        fail("order_amount_receipt_mismatch")

    technical_canary = brief.get("technical_canary")
    if truthy(technical_canary):
        fail("technical_canary_forbidden")
    if txt(brief.get("status")) not in {"paid_queued", "paid", "fulfilled", "ready_for_delivery"}:
        fail("brief_not_in_paid_state", brief.get("status"))
    if txt(brief.get("product_id")) != txt(receipt.get("product_id")):
        fail("brief_product_receipt_mismatch")
    if txt(order_meta.get("brief_id")) != brief_id:
        fail("order_brief_link_mismatch")
    conversion = obj(receipt_meta.get("conversion"))
    if txt(conversion.get("brief_id")) != brief_id:
        fail("receipt_brief_link_mismatch")
    details = require(brief.get("details"), "brief.details", 8)
    email = require(brief.get("email"), "brief.email", 6)
    if not valid_delivery_email(email):
        fail("delivery_email_invalid_or_test", email)
    company = txt(brief.get("company"))
    no_test_markers(company, "brief.company")

    item_id = txt(order.get("item_id"))
    item_type = txt(order.get("item_type"))
    product = PRODUCTS.get(item_id)
    service = SERVICES.get(item_id)
    if item_type == "product" and product:
        expected_template = product["slug"]
        expected_tier = product["tier"]
        expected_title = product["title"]
        if txt(order.get("service_id")) != product["service_id"]:
            fail("catalog_service_mapping_mismatch")
    elif item_type == "service" and service:
        expected_template = item_id
        expected_tier = service["tier"]
        expected_title = service["title"]
    else:
        fail("unsupported_paid_item", {"item_type": item_type, "item_id": item_id})

    report_template = txt(report.get("product_or_service_id") or report.get("template_key") or report.get("product_slug") or report.get("service_id"))
    if report_template != expected_template:
        fail("report_template_paid_item_mismatch", {"expected": expected_template, "actual": report_template})
    if normalize(report.get("client_request")) != normalize(details):
        fail("report_request_brief_mismatch")
    if company and normalize(report.get("client") or report.get("company")) != normalize(company):
        fail("report_client_brief_mismatch")
    no_test_markers(report.get("client") or report.get("company"), "report.client")

    # A production report must not contain reserved example/test evidence domains.
    evidence = report.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        fail("report_evidence_missing")
    for idx, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            fail("invalid_report_evidence", idx)
        url = txt(entry.get("url"))
        try:
            host = (urlparse(url).hostname or "").casefold()
        except Exception:
            host = ""
        if not host or host in RESERVED_HOSTS or host.endswith(".invalid"):
            fail("production_evidence_test_domain_forbidden", {"index": idx, "url": url})

    if quality.get("ok") is not True or txt(quality.get("quality_gate")) != "client_delivery_ready":
        fail("pdf_quality_not_approved", {"ok": quality.get("ok"), "quality_gate": quality.get("quality_gate")})
    if txt(quality.get("report_id")) != report_id:
        fail("quality_report_id_mismatch")
    if txt(quality.get("tier")) != expected_tier:
        fail("quality_tier_mismatch", {"expected": expected_tier, "actual": quality.get("tier")})
    pages = int(quality.get("pages") or 0)
    if not page_range_ok(expected_tier, pages):
        fail("quality_page_count_out_of_contract", {"tier": expected_tier, "pages": pages})
    quality_pdf = Path(str(quality.get("pdf") or "")).resolve()
    if quality_pdf != pdf:
        fail("quality_pdf_path_mismatch", {"expected": str(pdf), "actual": str(quality_pdf)})

    pdf_sha256 = sha256_file(pdf)
    file_bytes = pdf.stat().st_size
    delivery_key = hashlib.sha256(f"{order_id}|{receipt_id}|{brief_id}|{report_id}|{pdf_sha256}".encode()).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema": "lumen.delivery-manifest.v1",
        "approval_status": "quality_approved",
        "delivery_status": "ready_for_delivery",
        "delivery_attempted": False,
        "delivery_key": delivery_key,
        "approved_at": now,
        "order": {"id": order_id, "item_type": item_type, "item_id": item_id, "service_id": txt(order.get("service_id")), "amount_usd": float(order.get("amount_usd") or 0)},
        "payment": {"receipt_id": receipt_id, "status": receipt_status, "network": EXPECTED_NETWORK, "recipient": EXPECTED_PAY_TO, "transaction": txt(settlement.get("transaction"))},
        "brief": {"id": brief_id, "delivery_email": email, "company": company},
        "report": {"id": report_id, "template": expected_template, "title": expected_title, "tier": expected_tier, "pages": pages},
        "file": {"path": str(pdf), "bytes": file_bytes, "sha256": pdf_sha256},
        "quality": {"gate": "client_delivery_ready", "visible_source_urls": quality.get("visible_source_urls"), "page_stats": quality.get("page_stats", [])},
        "safety": {"payment_settled": True, "technical_canary": False, "outgoing_spend": False, "test_fixture": False},
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        existing = load_json(manifest_path, "existing_manifest")
        if existing.get("delivery_key") == delivery_key and existing.get("delivery_status") in {"ready_for_delivery", "delivered"}:
            emit(True, duplicateSafe=True, manifest=str(manifest_path), delivery_key=delivery_key, delivery_status=existing.get("delivery_status"))
            return
        fail("delivery_manifest_conflict", {"path": str(manifest_path), "existing_delivery_key": existing.get("delivery_key"), "new_delivery_key": delivery_key})

    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)
    emit(True, manifest=str(manifest_path), delivery_key=delivery_key, delivery_status="ready_for_delivery", sha256=pdf_sha256, pages=pages, outgoing_spend=False)


if __name__ == "__main__":
    main()
