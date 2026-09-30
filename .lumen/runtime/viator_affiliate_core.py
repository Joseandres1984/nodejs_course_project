from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_KEYS = {"pid", "mcid", "medium", "medium_version"}


class ViatorAffiliateError(ValueError):
    """Raised when a URL cannot safely be converted into a Viator affiliate link."""


def _is_viator_host(hostname: str | None) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == "viator.com" or host.endswith(".viator.com")


def build_viator_affiliate_url(
    raw_url: str,
    *,
    pid: str,
    mcid: str = "42383",
    medium: str = "link",
    medium_version: str = "selector",
) -> str:
    """Return a safe Viator URL carrying LUMEN affiliate attribution."""
    raw = (raw_url or "").strip()
    if not raw:
        raise ViatorAffiliateError("A Viator URL is required")
    if not pid.strip():
        raise ViatorAffiliateError("LUMEN_VIATOR_AFFILIATE_PID is not configured")

    if "://" not in raw:
        raw = "https://" + raw.lstrip("/")

    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as exc:
        raise ViatorAffiliateError("Invalid URL") from exc

    if parts.scheme.lower() not in {"http", "https"}:
        raise ViatorAffiliateError("Only http/https Viator URLs are supported")
    if not _is_viator_host(parts.hostname):
        raise ViatorAffiliateError("Only viator.com URLs can be monetized")
    if parts.username or parts.password:
        raise ViatorAffiliateError("Credentials are not allowed in affiliate URLs")
    if port not in {None, 80, 443}:
        raise ViatorAffiliateError("Unexpected port in Viator URL")

    params = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_KEYS
    ]
    params.extend(
        [
            ("pid", pid.strip()),
            ("mcid", mcid.strip() or "42383"),
            ("medium", medium.strip() or "link"),
            ("medium_version", medium_version.strip() or "selector"),
        ]
    )

    host = (parts.hostname or "www.viator.com").lower().rstrip(".")
    path = parts.path or "/"
    return urlunsplit(("https", host, path, urlencode(params, doseq=True), parts.fragment))
