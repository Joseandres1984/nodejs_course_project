from __future__ import annotations

"""Private, fail-closed delivery controller for paid LUMEN reports.

The research lane writes ``report_ready`` rows. This controller atomically claims one,
revalidates its authoritative settlement/order/brief context, and later records approval
and sends the exact QA-approved PDF as a private email attachment.

It never retries an ambiguous send automatically and never performs outgoing payments.
"""

import argparse
import base64
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import d1_persistence_runtime as d1

VERSION = "1.0-private-paid-delivery"
EXPECTED_PAY_TO = "0x04285DE6A083CEb28fb0C254a2ed0F5fdB2eeD28"
EXPECTED_NETWORK = "eip155:8453"

BREVO_API_KEY = os.getenv("LUMEN_BREVO_API_KEY", "").strip()
BREVO_FROM_EMAIL = os.getenv("LUMEN_BREVO_FROM_EMAIL", "").strip()
BREVO_FROM_NAME = os.getenv("LUMEN_BREVO_FROM_NAME", "LUMEN B2B").strip() or "LUMEN B2B"
RESEND_API_KEY = os.getenv("LUMEN_RESEND_API_KEY", "").strip()
RESEND_FROM = os.getenv("LUMEN_RESEND_FROM", "").strip()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: Any, limit: int = 8000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def rows(result: Any, index: int = 0) -> List[Dict[str, Any]]:
    statements = d1._result_statements(result)
    return d1._statement_rows(statements[index]) if len(statements) > index else []


def ensure_schema() -> None:
    d1._request({"batch": [
        {"sql": "CREATE TABLE IF NOT EXISTS lumen_paid_deliveries (order_id TEXT PRIMARY KEY, delivery_key TEXT UNIQUE, receipt_id TEXT NOT NULL, brief_id TEXT NOT NULL, report_id TEXT, pdf_sha256 TEXT, status TEXT NOT NULL, approved_at TEXT, send_started_at TEXT, delivered_at TEXT, provider TEXT, provider_message_id TEXT, manifest_json TEXT, last_error TEXT, updated_at TEXT NOT NULL)", "params": []},
        {"sql": "CREATE INDEX IF NOT EXISTS idx_lumen_paid_deliveries_status ON lumen_paid_deliveries(status,updated_at)", "params": []},
    ]})


def _authoritative_context(order_id: str) -> Dict[str, Any]:
    sql = """
    SELECT
      o.id AS order_id,o.item_type,o.item_id,o.service_id,o.amount_usd,o.status AS order_status,o.remote_metadata AS order_metadata,
      r.id AS receipt_id,r.product_id,r.service_id AS receipt_service_id,r.amount_usd AS receipt_amount_usd,r.currency,r.network,r.pay_to,r.status AS receipt_status,r.request_metadata,
      b.id AS brief_id,b.product_id AS brief_product_id,b.product_slug,b.email,b.company,b.details,b.status AS brief_status,b.technical_canary
    FROM lumen_machine_orders o
    JOIN lumen_x402_receipts r ON r.id=json_extract(o.remote_metadata,'$.x402_receipt_id')
    JOIN lumen_conversion_leads b ON b.id=json_extract(o.remote_metadata,'$.brief_id')
    WHERE o.id=? LIMIT 1
    """
    found = rows(d1._request({"sql": sql, "params": [order_id]}))
    if not found:
        raise RuntimeError("authoritative_order_context_not_found")
    row = found[0]
    om = parse_obj(row.get("order_metadata"))
    rm = parse_obj(row.get("request_metadata"))
    settlement = parse_obj(rm.get("settlement"))
    if text(row.get("receipt_status")) not in {"settled_verified", "redeemed_queued"}:
        raise RuntimeError("receipt_not_settled")
    if settlement.get("success") is not True or not text(settlement.get("transaction")):
        raise RuntimeError("settlement_evidence_missing")
    if text(row.get("network")) != EXPECTED_NETWORK or text(row.get("pay_to")).casefold() != EXPECTED_PAY_TO.casefold():
        raise RuntimeError("settlement_destination_mismatch")
    if text(row.get("order_status")) != "x402_paid_queued":
        raise RuntimeError("order_not_paid_queued")
    if text(om.get("payment_verified")).lower() != "true" or text(om.get("payment_settled")).lower() != "true":
        raise RuntimeError("order_payment_truth_missing")
    if int(row.get("technical_canary") or 0) != 0 or text(row.get("brief_status")) != "paid_queued":
        raise RuntimeError("brief_not_real_paid_request")
    if text(om.get("x402_receipt_id")) != text(row.get("receipt_id")) or text(om.get("brief_id")) != text(row.get("brief_id")):
        raise RuntimeError("order_lineage_mismatch")
    return {
        "receipt": {
            "id": row.get("receipt_id"), "product_id": row.get("product_id"), "service_id": row.get("receipt_service_id"),
            "amount_usd": row.get("receipt_amount_usd"), "currency": row.get("currency"), "network": row.get("network"),
            "pay_to": row.get("pay_to"), "status": row.get("receipt_status"), "request_metadata": rm,
        },
        "order": {
            "id": row.get("order_id"), "item_type": row.get("item_type"), "item_id": row.get("item_id"),
            "service_id": row.get("service_id"), "amount_usd": row.get("amount_usd"), "status": row.get("order_status"),
            "remote_metadata": om,
        },
        "brief": {
            "id": row.get("brief_id"), "product_id": row.get("brief_product_id"), "product_slug": row.get("product_slug"),
            "email": row.get("email"), "company": row.get("company"), "details": row.get("details"),
            "status": row.get("brief_status"), "technical_canary": row.get("technical_canary"),
        },
    }


def claim(output_dir: Path) -> Dict[str, Any]:
    ensure_schema()
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = now()
    sql = """
    UPDATE lumen_paid_fulfillment_jobs
    SET status='rendering', claimed_at=?, updated_at=?, last_error=NULL
    WHERE order_id=(
      SELECT order_id FROM lumen_paid_fulfillment_jobs
      WHERE status='report_ready' AND report_json IS NOT NULL AND evidence_count>=2
      ORDER BY created_at ASC LIMIT 1
    ) AND status='report_ready'
    RETURNING *
    """
    got = rows(d1._request({"sql": sql, "params": [ts, ts]}))
    if not got:
        return {"ok": True, "has_job": False, "status": "idle", "outgoing_spend": False}
    job = got[0]
    order_id = text(job.get("order_id"), 100)
    try:
        context = _authoritative_context(order_id)
        report = json.loads(str(job.get("report_json") or "{}"))
        if not isinstance(report, dict) or not report.get("report_id"):
            raise RuntimeError("report_json_invalid")
        fulfillment = report.get("fulfillment") if isinstance(report.get("fulfillment"), dict) else {}
        if text(fulfillment.get("order_id")) != order_id or text(fulfillment.get("receipt_id")) != text(context["receipt"]["id"]) or text(fulfillment.get("brief_id")) != text(context["brief"]["id"]):
            raise RuntimeError("report_lineage_mismatch")
        (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "has_job": True, "status": "rendering", "order_id": order_id, "report_id": report.get("report_id"), "outgoing_spend": False}
    except Exception as exc:
        d1._request({"sql": "UPDATE lumen_paid_fulfillment_jobs SET status='delivery_blocked', claimed_at=NULL, updated_at=?, last_error=? WHERE order_id=? AND status='rendering'", "params": [now(), text(f"{type(exc).__name__}: {exc}", 600), order_id]})
        raise


def approve(order_id: str, manifest_path: Path) -> Dict[str, Any]:
    ensure_schema()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("delivery_status") != "ready_for_delivery" or manifest.get("approval_status") != "quality_approved":
        raise RuntimeError("manifest_not_quality_approved")
    if text(manifest.get("order", {}).get("id")) != order_id:
        raise RuntimeError("manifest_order_mismatch")
    delivery_key = text(manifest.get("delivery_key"), 128)
    receipt_id = text(manifest.get("payment", {}).get("receipt_id"), 100)
    brief_id = text(manifest.get("brief", {}).get("id"), 100)
    report_id = text(manifest.get("report", {}).get("id"), 120)
    pdf_sha = text(manifest.get("file", {}).get("sha256"), 128)
    if not all((delivery_key, receipt_id, brief_id, report_id, pdf_sha)):
        raise RuntimeError("manifest_fields_missing")
    context = _authoritative_context(order_id)
    if receipt_id != text(context["receipt"]["id"]) or brief_id != text(context["brief"]["id"]):
        raise RuntimeError("manifest_authoritative_lineage_mismatch")
    serialized = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
    d1._request({"batch": [
        {"sql": "INSERT INTO lumen_paid_deliveries(order_id,delivery_key,receipt_id,brief_id,report_id,pdf_sha256,status,approved_at,manifest_json,updated_at) VALUES(?,?,?,?,?,?,'ready_for_delivery',?,?,?) ON CONFLICT(order_id) DO UPDATE SET delivery_key=excluded.delivery_key,receipt_id=excluded.receipt_id,brief_id=excluded.brief_id,report_id=excluded.report_id,pdf_sha256=excluded.pdf_sha256,status=CASE WHEN lumen_paid_deliveries.status='delivered' THEN 'delivered' ELSE 'ready_for_delivery' END,approved_at=excluded.approved_at,manifest_json=excluded.manifest_json,updated_at=excluded.updated_at WHERE lumen_paid_deliveries.delivery_key=excluded.delivery_key", "params": [order_id, delivery_key, receipt_id, brief_id, report_id, pdf_sha, now(), serialized, now()]},
        {"sql": "UPDATE lumen_paid_fulfillment_jobs SET status='ready_for_delivery', claimed_at=NULL, updated_at=?, last_error=NULL WHERE order_id=? AND status='rendering'", "params": [now(), order_id]},
    ]})
    return {"ok": True, "order_id": order_id, "delivery_key": delivery_key, "status": "ready_for_delivery", "outgoing_spend": False}


def _post(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int = 35) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read(16000).decode("utf-8", errors="replace")
            if not 200 <= int(resp.status) < 300:
                raise RuntimeError(f"mail_http_{resp.status}:{raw[:500]}")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read(16000).decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"mail_http_{exc.code}:{raw[:700]}") from exc


def _send_attachment(target: str, subject: str, body: str, pdf_path: Path, delivery_key: str) -> tuple[str, str]:
    encoded = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    filename = "LUMEN-Informe.pdf"
    # Prefer the existing production Brevo route. A timeout/unknown result is not auto-retried.
    if BREVO_API_KEY and BREVO_FROM_EMAIL:
        payload = {
            "sender": {"email": BREVO_FROM_EMAIL, "name": BREVO_FROM_NAME},
            "to": [{"email": target}],
            "subject": subject,
            "textContent": body,
            "htmlContent": "<p>Hola,</p><p>Adjuntamos el informe LUMEN correspondiente a tu solicitud.</p><p>El documento incluye alcance, evidencia pública, conclusiones, límites y próximos pasos.</p><p>Saludos,<br><strong>LUMEN B2B</strong></p>",
            "attachment": [{"content": encoded, "name": filename}],
            "headers": {"X-LUMEN-Delivery-Key": delivery_key},
        }
        result = _post("https://api.brevo.com/v3/smtp/email", payload, {"api-key": BREVO_API_KEY, "accept": "application/json"})
        return "brevo", text(result.get("messageId") or result.get("message_id"), 200)
    if RESEND_API_KEY and RESEND_FROM:
        payload = {
            "from": RESEND_FROM,
            "to": [target],
            "subject": subject,
            "text": body,
            "html": "<p>Hola,</p><p>Adjuntamos el informe LUMEN correspondiente a tu solicitud.</p><p>El documento incluye alcance, evidencia pública, conclusiones, límites y próximos pasos.</p><p>Saludos,<br><strong>LUMEN B2B</strong></p>",
            "attachments": [{"filename": filename, "content": encoded}],
        }
        result = _post("https://api.resend.com/emails", payload, {"Authorization": f"Bearer {RESEND_API_KEY}", "Idempotency-Key": delivery_key})
        return "resend", text(result.get("id"), 200)
    raise RuntimeError("no_https_mail_provider_configured")


def send(order_id: str, pdf_path: Path, manifest_path: Path) -> Dict[str, Any]:
    ensure_schema()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    delivery_key = text(manifest.get("delivery_key"), 128)
    pdf_sha = text(manifest.get("file", {}).get("sha256"), 128)
    if text(manifest.get("order", {}).get("id")) != order_id or not delivery_key or not pdf_sha:
        raise RuntimeError("send_manifest_invalid")
    context = _authoritative_context(order_id)
    target = text(context["brief"].get("email"), 180).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", target) or target.endswith(".invalid"):
        raise RuntimeError("delivery_email_invalid")
    current = rows(d1._request({"sql": "SELECT * FROM lumen_paid_deliveries WHERE order_id=? LIMIT 1", "params": [order_id]}))
    if not current:
        raise RuntimeError("approved_delivery_row_missing")
    row = current[0]
    if text(row.get("delivery_key")) != delivery_key or text(row.get("pdf_sha256")) != pdf_sha:
        raise RuntimeError("approved_pdf_identity_mismatch")
    if text(row.get("status")) == "delivered":
        return {"ok": True, "duplicateSafe": True, "status": "delivered", "order_id": order_id, "provider": row.get("provider"), "provider_message_id": row.get("provider_message_id"), "outgoing_spend": False}
    # At-most-once automatic send: only ready_for_delivery can transition to sending.
    claimed = rows(d1._request({"sql": "UPDATE lumen_paid_deliveries SET status='sending',send_started_at=?,updated_at=?,last_error=NULL WHERE order_id=? AND delivery_key=? AND status='ready_for_delivery' RETURNING *", "params": [now(), now(), order_id, delivery_key]}))
    if not claimed:
        raise RuntimeError(f"delivery_not_sendable_current_status:{row.get('status')}")
    subject = f"Tu informe LUMEN · {text(manifest.get('report', {}).get('title'), 120) or 'Inteligencia B2B'}"
    body = "Hola,\n\nAdjuntamos el informe LUMEN correspondiente a tu solicitud. El documento incluye la evidencia pública utilizada, conclusiones, límites y próximos pasos.\n\nSaludos,\nLUMEN B2B"
    try:
        provider, message_id = _send_attachment(target, subject, body, pdf_path, delivery_key)
        d1._request({"batch": [
            {"sql": "UPDATE lumen_paid_deliveries SET status='delivered',provider=?,provider_message_id=?,delivered_at=?,updated_at=?,last_error=NULL WHERE order_id=? AND delivery_key=? AND status='sending'", "params": [provider, message_id or None, now(), now(), order_id, delivery_key]},
            {"sql": "UPDATE lumen_paid_fulfillment_jobs SET status='delivered',updated_at=?,last_error=NULL WHERE order_id=? AND status='ready_for_delivery'", "params": [now(), order_id]},
            {"sql": "UPDATE lumen_conversion_leads SET status='fulfilled' WHERE id=? AND status='paid_queued'", "params": [text(context['brief'].get('id'), 100)]},
        ]})
        return {"ok": True, "status": "delivered", "order_id": order_id, "provider": provider, "provider_message_id": message_id, "delivery_email": target, "outgoing_spend": False}
    except Exception as exc:
        # A network timeout can be ambiguous. Never automatically transition back to ready.
        d1._request({"sql": "UPDATE lumen_paid_deliveries SET status='delivery_ambiguous',updated_at=?,last_error=? WHERE order_id=? AND delivery_key=? AND status='sending'", "params": [now(), text(f"{type(exc).__name__}: {exc}", 700), order_id, delivery_key]})
        d1._request({"sql": "UPDATE lumen_paid_fulfillment_jobs SET status='delivery_ambiguous',updated_at=?,last_error=? WHERE order_id=? AND status='ready_for_delivery'", "params": [now(), text(f"{type(exc).__name__}: {exc}", 700), order_id]})
        raise


def block(order_id: str, error: str) -> Dict[str, Any]:
    d1._request({"sql": "UPDATE lumen_paid_fulfillment_jobs SET status='delivery_blocked',claimed_at=NULL,updated_at=?,last_error=? WHERE order_id=? AND status IN ('rendering','ready_for_delivery')", "params": [now(), text(error, 700), order_id]})
    return {"ok": True, "status": "delivery_blocked", "order_id": order_id, "outgoing_spend": False}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("claim"); p.add_argument("--out-dir", required=True)
    p = sub.add_parser("approve"); p.add_argument("--order-id", required=True); p.add_argument("--manifest", required=True)
    p = sub.add_parser("send"); p.add_argument("--order-id", required=True); p.add_argument("--pdf", required=True); p.add_argument("--manifest", required=True)
    p = sub.add_parser("block"); p.add_argument("--order-id", required=True); p.add_argument("--error", required=True)
    args = ap.parse_args()
    ensure_schema()
    if args.cmd == "claim": result = claim(Path(args.out_dir))
    elif args.cmd == "approve": result = approve(text(args.order_id, 100), Path(args.manifest))
    elif args.cmd == "send": result = send(text(args.order_id, 100), Path(args.pdf), Path(args.manifest))
    else: result = block(text(args.order_id, 100), args.error)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
