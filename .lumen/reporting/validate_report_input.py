#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDER_PATTERNS = [
    re.compile(r"\b(todo|tbd|lorem\s+ipsum|placeholder|fill\s+here|coming\s+soon)\b", re.I),
    re.compile(r"\b(completar\s+aqui|completar\s+acá|pendiente\s+de\s+completar|texto\s+de\s+prueba)\b", re.I),
]
GENERIC_DEFAULTS = {"lumen-draft", "cliente", "no informado", "sin informar", "n/a"}
TEST_MARKERS = ["cliente de prueba", "empresa industrial de prueba", "technical canary", "qa fixture"]
RESERVED_TEST_HOSTS = {
    "example.com", "www.example.com", "example.org", "www.example.org",
    "example.net", "www.example.net", "example.invalid", "localhost",
}


def emit(ok, **payload):
    print(json.dumps({"ok": ok, **payload}, ensure_ascii=False))


def fail(code, detail=None):
    emit(False, error=code, detail=detail or "")
    raise SystemExit(1)


def text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def require_text(value, field, min_len=1):
    value = text(value)
    if not value or value.casefold() in GENERIC_DEFAULTS:
        fail("required_field_missing_or_default", {"field": field, "value": value})
    if len(value) < min_len:
        fail("required_text_too_short", {"field": field, "length": len(value), "min": min_len})
    return value


def parse_date(value, field):
    raw = require_text(value, field, 10)
    try:
        datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            fail("invalid_date", {"field": field, "value": raw})
    return raw


def scan_placeholders(value, path="root", allow_test=False):
    if isinstance(value, dict):
        for key, child in value.items():
            scan_placeholders(child, f"{path}.{key}", allow_test)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            scan_placeholders(child, f"{path}[{idx}]", allow_test)
        return
    if not isinstance(value, str):
        return
    raw = text(value)
    lowered = raw.casefold()
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(raw):
            fail("placeholder_content_detected", {"path": path, "value": raw[:180]})
    if not allow_test and any(marker in lowered for marker in TEST_MARKERS):
        fail("test_content_detected_in_production_input", {"path": path, "value": raw[:180]})


def valid_http_url(raw):
    try:
        u = urlparse(raw)
    except Exception:
        return False, ""
    return u.scheme in {"http", "https"} and bool(u.netloc), (u.hostname or "").casefold()


def validate_item_list(items, field, minimum):
    if not isinstance(items, list) or len(items) < minimum:
        fail("insufficient_items", {"field": field, "count": len(items) if isinstance(items, list) else 0, "min": minimum})
    return items


def main():
    ap = argparse.ArgumentParser(description="Fail-closed LUMEN report input quality gate")
    ap.add_argument("input")
    ap.add_argument("--templates", default=".lumen/contracts/delivery-templates.json")
    ap.add_argument("--allow-test-domains", action="store_true")
    args = ap.parse_args()

    input_path = Path(args.input)
    templates_path = Path(args.templates)
    if not input_path.exists():
        fail("input_missing", str(input_path))
    if not templates_path.exists():
        fail("templates_missing", str(templates_path))

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail("input_json_invalid", str(exc))
    try:
        defs = json.loads(templates_path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail("templates_json_invalid", str(exc))
    if not isinstance(data, dict):
        fail("input_root_must_be_object")

    key = text(data.get("product_or_service_id") or data.get("template_key") or data.get("service_id") or data.get("product_slug"))
    if not key:
        fail("product_or_service_id_missing")

    service_templates = defs.get("service_templates") or {}
    micro_templates = defs.get("micro_templates") or {}
    if key in service_templates:
        tier, tpl = "full", service_templates[key]
    elif key in micro_templates:
        tier, tpl = "micro", micro_templates[key]
    else:
        fail("unknown_delivery_template", key)

    # The contractual identifier must be explicit in production input, rather
    # than inferred later by a renderer fallback.
    explicit_id = require_text(data.get("product_or_service_id"), "product_or_service_id", 3)
    if explicit_id != key:
        fail("product_or_service_id_template_mismatch", {"product_or_service_id": explicit_id, "resolved_template": key})

    report_id = require_text(data.get("report_id"), "report_id", 8)
    if report_id.casefold() == "lumen-draft":
        fail("draft_report_id_forbidden", report_id)
    client = require_text(data.get("client") or data.get("company"), "client", 2)
    request = require_text(data.get("client_request") or data.get("request"), "client_request", 30)
    generated_at = parse_date(data.get("generated_at"), "generated_at")
    evidence_cutoff = parse_date(data.get("evidence_cutoff"), "evidence_cutoff")

    confidence = text(data.get("confidence")).casefold()
    allowed_confidence = {str(x).casefold() for x in (defs.get("delivery_rules", {}).get("confidence_labels") or ["alta", "media", "baja"])}
    if confidence not in allowed_confidence:
        fail("invalid_confidence", {"value": confidence, "allowed": sorted(allowed_confidence)})

    executive = require_text(data.get("executive_summary") or data.get("answer") or data.get("summary"), "executive_summary_or_answer", 50)
    recommendation = require_text(data.get("recommendation") or data.get("conclusion"), "recommendation", 30)

    findings = validate_item_list(data.get("findings") or data.get("key_findings"), "findings", 2 if tier == "micro" else 3)
    for idx, item in enumerate(findings):
        if isinstance(item, str):
            require_text(item, f"findings[{idx}]", 30)
        elif isinstance(item, dict):
            require_text(item.get("title"), f"findings[{idx}].title", 5)
            require_text(item.get("detail"), f"findings[{idx}].detail", 25)
            item_conf = text(item.get("confidence")).casefold()
            if item_conf and item_conf not in allowed_confidence:
                fail("invalid_finding_confidence", {"index": idx, "value": item_conf})
        else:
            fail("invalid_finding", {"index": idx})

    tables = validate_item_list(data.get("tables"), "tables", 1)
    min_rows = 2 if tier == "micro" else 3
    total_rows = 0
    for t_idx, table in enumerate(tables):
        if not isinstance(table, dict):
            fail("invalid_table", {"index": t_idx})
        require_text(table.get("title"), f"tables[{t_idx}].title", 4)
        columns = validate_item_list(table.get("columns"), f"tables[{t_idx}].columns", 2)
        rows = validate_item_list(table.get("rows"), f"tables[{t_idx}].rows", min_rows)
        total_rows += len(rows)
        for r_idx, row in enumerate(rows):
            if isinstance(row, list):
                if len(row) != len(columns):
                    fail("table_row_width_mismatch", {"table": t_idx, "row": r_idx, "expected": len(columns), "actual": len(row)})
                populated = sum(1 for cell in row if text(cell))
                if populated < max(2, len(columns) // 2):
                    fail("table_row_too_sparse", {"table": t_idx, "row": r_idx, "populated": populated})
            elif not isinstance(row, dict):
                fail("invalid_table_row", {"table": t_idx, "row": r_idx})

    allowed_risks = {str(x).casefold() for x in (defs.get("delivery_rules", {}).get("risk_labels") or ["bajo", "medio", "alto", "no_determinado"])}
    risks = validate_item_list(data.get("risks"), "risks", 1)
    for idx, risk in enumerate(risks):
        if not isinstance(risk, dict):
            fail("invalid_risk", {"index": idx})
        level = text(risk.get("level")).casefold()
        if level not in allowed_risks:
            fail("invalid_risk_level", {"index": idx, "value": level, "allowed": sorted(allowed_risks)})
        require_text(risk.get("title"), f"risks[{idx}].title", 5)
        require_text(risk.get("detail"), f"risks[{idx}].detail", 20)

    evidence = validate_item_list(data.get("evidence"), "evidence", 2 if tier == "micro" else 3)
    unique_urls = set()
    for idx, item in enumerate(evidence):
        if not isinstance(item, dict):
            fail("invalid_evidence", {"index": idx})
        require_text(item.get("title") or item.get("source"), f"evidence[{idx}].title", 4)
        url = require_text(item.get("url"), f"evidence[{idx}].url", 10)
        ok_url, host = valid_http_url(url)
        if not ok_url:
            fail("invalid_evidence_url", {"index": idx, "url": url})
        if not args.allow_test_domains and (host in RESERVED_TEST_HOSTS or host.endswith(".invalid")):
            fail("reserved_test_domain_forbidden", {"index": idx, "host": host})
        if url in unique_urls:
            fail("duplicate_evidence_url", {"index": idx, "url": url})
        unique_urls.add(url)
        require_text(item.get("note"), f"evidence[{idx}].note", 15)
        parse_date(item.get("observed_at"), f"evidence[{idx}].observed_at")

    next_steps = validate_item_list(data.get("next_steps"), "next_steps", 1 if tier == "micro" else 2)
    for idx, step in enumerate(next_steps):
        require_text(step if isinstance(step, str) else step.get("text") if isinstance(step, dict) else "", f"next_steps[{idx}]", 15)

    if tier == "full":
        analysis = data.get("analysis")
        if not isinstance(analysis, dict):
            fail("full_service_analysis_missing")
        missing_blocks = []
        for block in tpl.get("analysis_blocks") or []:
            if len(text(analysis.get(block) if isinstance(analysis, dict) else "")) < 25:
                missing_blocks.append(block)
        if missing_blocks:
            fail("full_service_analysis_blocks_missing", missing_blocks)
        hero_metrics = tpl.get("hero_metrics") or []
        populated_metrics = sum(1 for key_name in hero_metrics if text((data.get("metrics") or {}).get(key_name) or data.get(key_name)))
        if hero_metrics and populated_metrics < min(2, len(hero_metrics)):
            fail("insufficient_full_service_metrics", {"populated": populated_metrics, "expected_at_least": min(2, len(hero_metrics))})

    scan_placeholders(data, allow_test=args.allow_test_domains)

    emit(
        True,
        input=str(input_path),
        template=key,
        tier=tier,
        report_id=report_id,
        client=client,
        generated_at=generated_at,
        evidence_cutoff=evidence_cutoff,
        counts={
            "findings": len(findings),
            "tables": len(tables),
            "table_rows": total_rows,
            "risks": len(risks),
            "evidence": len(evidence),
            "next_steps": len(next_steps),
        },
        executive_chars=len(executive),
        recommendation_chars=len(recommendation),
        test_domains_allowed=args.allow_test_domains,
    )


if __name__ == "__main__":
    main()
