from __future__ import annotations

"""Direct official-procurement document enrichment.

When LUMEN already owns a current official procurement URL, fetch a very small bounded number of
those public documents directly (no search-provider query), extract text, and feed exact fields back
into the procurement requirement bridge. Public GET only; no login, form, cart or mutation.
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, List
import html
import re
import urllib.request

from pypdf import PdfReader

import commercial_truth_repair_runtime as truth
import interlocutor_engine

VERSION = "1.0-procurement-document-enrichment"
MAX_DOCS_PER_CYCLE = 2
MAX_BYTES = 6 * 1024 * 1024
MAX_PDF_PAGES = 12
CACHE_TTL_HOURS = 24

_ORIGINAL_INTERLOCUTOR_TICK = interlocutor_engine.interlocutor_tick
_ORIGINAL_SIGNAL_TEXT = truth._signal_text


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clean_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>|<style.*?>.*?</style>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())[:50000]


def _extract_pdf(raw: bytes) -> str:
    reader = PdfReader(BytesIO(raw), strict=False)
    chunks: List[str] = []
    for page in list(reader.pages)[:MAX_PDF_PAGES]:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            chunks.append(text)
    return " ".join(" ".join(chunks).split())[:50000]


def _fetch_public_document(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LUMEN-B2B-Research/1.0 public-procurement-evidence",
            "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.3",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        content_type = str(resp.headers.get("Content-Type") or "").lower()
        raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {"status": "too_large", "content_type": content_type, "bytes": len(raw)}
        if "pdf" in content_type or url.lower().split("?", 1)[0].endswith(".pdf"):
            text = _extract_pdf(raw)
        else:
            decoded = raw.decode("utf-8", errors="replace")
            text = _clean_html(decoded)
        return {
            "status": "ok" if text else "no_extractable_text",
            "content_type": content_type,
            "bytes": len(raw),
            "text": text,
        }


def _linked_current_urls(state: Dict[str, Any]) -> List[str]:
    signals = truth._signal_map(state)
    opportunities = {
        str(x.get("id") or ""): x
        for x in state.get("market_opportunities", []) or []
        if isinstance(x, dict)
    }
    urls: List[str] = []
    for case in state.get("interlocution_cases", []) or []:
        if not isinstance(case, dict) or case.get("supplier_rfq_ready"):
            continue
        opp = opportunities.get(str(case.get("opportunity_id") or ""), {})
        if not opp:
            continue
        for url in truth._candidate_urls(state, case, opp):
            if url in signals:
                urls.append(url)
    return list(dict.fromkeys(urls))


def _cache_index(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = state.setdefault("public_procurement_document_cache", [])
    return {str(x.get("url") or ""): x for x in rows if isinstance(x, dict) and x.get("url")}


def _due(row: Dict[str, Any]) -> bool:
    fetched = _parse(row.get("fetched_at"))
    if not fetched:
        return True
    return _now_dt() - fetched >= timedelta(hours=CACHE_TTL_HOURS)


def _enrich(state: Dict[str, Any]) -> Dict[str, int]:
    signal_map = truth._signal_map(state)
    cache = _cache_index(state)
    rows = state.setdefault("public_procurement_document_cache", [])
    stats = {"eligible": 0, "fetched": 0, "text_extracted": 0, "errors": 0, "skipped_cached": 0}

    urls = _linked_current_urls(state)
    stats["eligible"] = len(urls)
    for url in urls:
        if stats["fetched"] >= MAX_DOCS_PER_CYCLE:
            break
        existing = cache.get(url)
        if existing and not _due(existing):
            stats["skipped_cached"] += 1
            if existing.get("status") == "ok" and existing.get("text_excerpt"):
                signal_map[url]["document_text_excerpt"] = existing.get("text_excerpt")
            continue

        row = existing or {"url": url}
        try:
            result = _fetch_public_document(url)
            row.update({
                "status": result.get("status"),
                "content_type": result.get("content_type"),
                "bytes": result.get("bytes"),
                "fetched_at": _now(),
                "source_policy": "public_official_get_only_no_auth_no_mutation",
            })
            text = str(result.get("text") or "")
            if text:
                row["text_excerpt"] = text[:50000]
                signal_map[url]["document_text_excerpt"] = text[:50000]
                stats["text_extracted"] += 1
            stats["fetched"] += 1
        except Exception as exc:
            row.update({
                "status": "fetch_error",
                "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                "fetched_at": _now(),
                "source_policy": "public_official_get_only_no_auth_no_mutation",
            })
            stats["fetched"] += 1
            stats["errors"] += 1
        if existing is None:
            rows.append(row)
            cache[url] = row

    state["public_procurement_document_cache"] = rows[-120:]
    state["procurement_document_enrichment"] = {
        "version": VERSION,
        "status": "active",
        **stats,
        "max_docs_per_cycle": MAX_DOCS_PER_CYCLE,
        "search_provider_queries_used": 0,
        "updated_at": _now(),
    }
    return stats


def _enriched_signal_text(signal: Dict[str, Any]) -> str:
    base = _ORIGINAL_SIGNAL_TEXT(signal)
    doc = " ".join(str(signal.get("document_text_excerpt") or "").split())[:30000]
    return f"{base} {doc}".strip()


truth._signal_text = _enriched_signal_text


def _interlocutor_with_document_enrichment(state: Dict[str, Any]) -> Dict[str, Any]:
    enrichment = _enrich(state)
    report = dict(_ORIGINAL_INTERLOCUTOR_TICK(state) or {})
    report["official_documents_fetched"] = enrichment["fetched"]
    report["official_document_text_extracted"] = enrichment["text_extracted"]
    report["official_document_fetch_errors"] = enrichment["errors"]
    return report


interlocutor_engine.interlocutor_tick = _interlocutor_with_document_enrichment

print(
    {
        "procurement_document_enrichment_runtime": {
            "version": VERSION,
            "status": "active",
            "max_docs_per_cycle": MAX_DOCS_PER_CYCLE,
            "search_provider_queries_used": 0,
            "public_official_get_only": True,
            "binding_authority_changed": False,
        }
    },
    flush=True,
)
