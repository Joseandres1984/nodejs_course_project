from __future__ import annotations

"""Zero-cost public discovery provider for LUMEN Scout.

Discovery uses Bing's public RSS search representation (no API key, no billing account), while
LUMEN's existing verification/catalog layers remain responsible for validating the underlying
public websites. Failures are fail-open: a feed outage returns no results and never stops a cycle.
"""

import html
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List

import scout_connector

ZERO_PROVIDER = "bing_rss_public"
TIMEOUT = max(4.0, min(20.0, float(os.getenv("LUMEN_ZERO_SEARCH_TIMEOUT", "10"))))
MAX_RESULTS = max(3, min(10, int(os.getenv("LUMEN_ZERO_SEARCH_RESULTS", "8"))))
USER_AGENT = os.getenv(
    "LUMEN_ZERO_SEARCH_USER_AGENT",
    "Mozilla/5.0 (compatible; LUMEN-PublicResearch/1.0; +public-evidence-only)",
).strip()

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _clean(value: str, limit: int) -> str:
    text = html.unescape(_TAG_RE.sub(" ", str(value or "")))
    return _SPACE_RE.sub(" ", text).strip()[:limit]


def _safe_url(value: str) -> str:
    url = str(value or "").strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _rss_search(query: str) -> List[Dict[str, str]]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "rss",
            "mkt": "es-AR",
            "setlang": "es-AR",
        }
    )
    request = urllib.request.Request(
        "https://www.bing.com/search?" + params,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.5",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        raw = response.read(1_500_000)
        ctype = str(response.headers.get("content-type") or "").lower()
        if "xml" not in ctype and b"<rss" not in raw[:800].lower():
            return []

    root = ET.fromstring(raw)
    output: List[Dict[str, str]] = []
    seen = set()
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title") or "", 300)
        url = _safe_url(item.findtext("link") or "")
        snippet = _clean(item.findtext("description") or "", 800)
        if not url or url in seen:
            continue
        seen.add(url)
        output.append({"title": title, "url": url, "snippet": snippet})
        if len(output) >= MAX_RESULTS:
            break
    return output


def zero_search(query: str) -> List[Dict[str, str]]:
    try:
        return _rss_search(query)
    except Exception:
        return []


def zero_status() -> Dict[str, object]:
    return {
        "provider": ZERO_PROVIDER,
        "configured": True,
        "requires_api_key": False,
        "paid_search": False,
        "market": scout_connector.MARKET,
        "country_code": scout_connector.COUNTRY_CODE,
        "language": scout_connector.LANGUAGE,
        "max_queries_per_tick": scout_connector.MAX_QUERIES_PER_TICK,
        "daily_query_budget": scout_connector.DAILY_QUERY_BUDGET,
        "max_new_leads_per_query": scout_connector.MAX_NEW_LEADS_PER_QUERY,
        "validation": "existing_company_verifier_and_public_catalog_crawler",
    }


# scout_tick uses PROVIDER + API_KEY as its legacy configured flag. The sentinel below is local-only
# and is never sent to an external API; search() is replaced entirely by zero_search.
scout_connector.PROVIDER = ZERO_PROVIDER
scout_connector.API_KEY = "zero-cost-no-secret-required"
scout_connector.search = zero_search
scout_connector.status = zero_status

print(
    {
        "zero_scout_runtime": {
            "status": "active",
            "provider": ZERO_PROVIDER,
            "api_key_required": False,
            "paid_search": False,
            "max_results": MAX_RESULTS,
        }
    },
    flush=True,
)
