from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Dict, List, Tuple

USER_AGENT = os.getenv("LUMEN_CATALOG_USER_AGENT", "LUMEN-PublicCatalogResearch/1.0").strip()
TIMEOUT = max(2.0, min(10.0, float(os.getenv("LUMEN_CATALOG_HTTP_TIMEOUT", "4"))))
MAX_PAGES = max(1, min(20, int(os.getenv("LUMEN_CATALOG_MAX_PAGES_PER_STORE", "6"))))
MAX_BYTES = max(50000, min(2000000, int(os.getenv("LUMEN_CATALOG_MAX_BYTES", "600000"))))
PRODUCT_PATH_HINTS = ("/producto", "/product", "/productos/", "/products/", "/p/", "/shop/", "/tienda/", "/catalogo/", "/catalog/")
BLOCKED_PATH_HINTS = ("/cart", "/carrito", "/checkout", "/login", "/signin", "/account", "/cuenta", "/admin", "/wp-admin")


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.links: List[Tuple[str, str]] = []
        self._href = ""
        self._anchor_text: List[str] = []
        self._in_anchor = False
        self._in_jsonld = False
        self._jsonld: List[str] = []
        self.jsonld_blocks: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_d = dict(attrs)
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() == "a":
            self._href = str(attrs_d.get("href") or "")
            self._anchor_text = []
            self._in_anchor = True
        if tag.lower() == "script" and str(attrs_d.get("type") or "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        if tag.lower() == "a" and self._in_anchor:
            text = " ".join("".join(self._anchor_text).split())
            self.links.append((self._href, text))
            self._in_anchor = False
            self._href = ""
            self._anchor_text = []
        if tag.lower() == "script" and self._in_jsonld:
            self.jsonld_blocks.append("".join(self._jsonld))
            self._in_jsonld = False
            self._jsonld = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_anchor:
            self._anchor_text.append(data)
        if self._in_jsonld:
            self._jsonld.append(data)


def _same_domain(url: str, domain: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def _product_like(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if any(x in path for x in BLOCKED_PATH_HINTS):
        return False
    return any(x in path for x in PRODUCT_PATH_HINTS)


def _robots_allowed(domain: str, url: str) -> bool:
    robots_url = f"https://{domain}/robots.txt"
    req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read(200000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except Exception:
        return False
    rules: List[Tuple[str, str]] = []
    active = False
    for line in raw.splitlines():
        clean = line.split("#", 1)[0].strip()
        if not clean or ":" not in clean:
            continue
        key, value = [x.strip() for x in clean.split(":", 1)]
        key_l = key.lower()
        if key_l == "user-agent":
            active = value in {"*", USER_AGENT}
        elif active and key_l in {"allow", "disallow"}:
            rules.append((key_l, value))
    path = urllib.parse.urlparse(url).path or "/"
    matched: List[Tuple[int, str]] = []
    for kind, prefix in rules:
        if prefix and path.startswith(prefix):
            matched.append((len(prefix), kind))
    if not matched:
        return True
    matched.sort(reverse=True)
    return matched[0][1] == "allow"


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        ctype = str(response.headers.get("content-type") or "").lower()
        if "text/html" not in ctype and "application/xhtml" not in ctype:
            return ""
        return response.read(MAX_BYTES).decode("utf-8", errors="replace")


def _jsonld_products(blocks: List[str], source_url: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    def walk(value):
        if isinstance(value, dict):
            t = value.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "product" for x in types if x):
                name = " ".join(str(value.get("name") or "").split())
                url = str(value.get("url") or source_url)
                if name:
                    out.append({"title": name[:260], "url": url[:900], "source": "jsonld_product"})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for block in blocks:
        try:
            walk(json.loads(block))
        except Exception:
            continue
    return out


def crawl_store_catalog(domain: str, seed_urls: List[str] | None = None) -> Dict[str, object]:
    """Inspect a tiny, same-domain, robots-respecting slice of a public storefront.

    GET only. No login, cart, checkout, form submission, bypass, image copying or verbatim description copying.
    """
    domain = str(domain or "").lower().removeprefix("www.")
    if not domain or "." not in domain:
        return {"status": "invalid_domain", "pages": 0, "products": []}
    homepage = f"https://{domain}/"
    seeds = [homepage]
    for url in seed_urls or []:
        if url and _same_domain(url, domain) and url not in seeds:
            seeds.append(url)
    queue = seeds[:MAX_PAGES]
    seen = set()
    products: List[Dict[str, str]] = []
    discovered_links: List[Tuple[str, str]] = []
    pages = 0
    denied = 0
    errors = 0

    while queue and pages < MAX_PAGES:
        url = queue.pop(0)
        if url in seen or not _same_domain(url, domain):
            continue
        seen.add(url)
        if not _robots_allowed(domain, url):
            denied += 1
            continue
        try:
            body = _fetch(url)
        except Exception:
            errors += 1
            continue
        if not body:
            continue
        pages += 1
        parser = PageParser()
        try:
            parser.feed(body)
        except Exception:
            pass
        title = " ".join(parser.title.split())
        if _product_like(url) and title:
            products.append({"title": title[:260], "url": url[:900], "source": "public_product_page_title"})
        products.extend(_jsonld_products(parser.jsonld_blocks, url))
        for href, text in parser.links:
            absolute = urllib.parse.urljoin(url, href)
            parsed = urllib.parse.urlparse(absolute)
            clean_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
            if not _same_domain(clean_url, domain) or any(x in parsed.path.lower() for x in BLOCKED_PATH_HINTS):
                continue
            if _product_like(clean_url):
                discovered_links.append((clean_url, text))
                if clean_url not in seen and clean_url not in queue and len(queue) < MAX_PAGES * 3:
                    queue.append(clean_url)

    for url, text in discovered_links:
        title = " ".join(text.split())
        if title:
            products.append({"title": title[:260], "url": url[:900], "source": "public_catalog_link"})
    dedup: List[Dict[str, str]] = []
    seen_urls = set()
    for row in products:
        url = row.get("url") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        dedup.append(row)
        if len(dedup) >= 40:
            break
    return {"status": "ok" if pages else "no_pages", "pages": pages, "robots_denied": denied, "errors": errors, "products": dedup}
