from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from main import STATE, load_state, save_state


router = APIRouter()


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _offer(token: str) -> Optional[Dict[str, Any]]:
    target = str(token or "").strip().upper()
    return next(
        (
            x for x in STATE.get("partner_referral_offers", []) or []
            if str(x.get("token") or "").upper() == target
        ),
        None,
    )


def _partner(partner_id: str) -> Optional[Dict[str, Any]]:
    target = str(partner_id or "")
    return next((x for x in STATE.get("partner_stores", []) or [] if str(x.get("id") or "") == target), None)


def _destination(offer: Dict[str, Any], partner: Dict[str, Any]) -> str:
    source_url = str(offer.get("source_url") or "").strip()
    template = str(partner.get("affiliate_url_template") or "").strip()
    token = str(offer.get("token") or "")
    offer_id = str(offer.get("id") or "")

    if template:
        # Supported placeholders let a real affiliate/partner agreement define the merchant URL shape.
        return template.replace("{url}", urllib.parse.quote(source_url, safe="")).replace("{ref}", token).replace("{offer_id}", offer_id)

    if not bool(partner.get("append_ref_param")):
        return source_url

    parsed = urllib.parse.urlsplit(source_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({
        "utm_source": "lumen",
        "utm_medium": "referral",
        "utm_campaign": offer_id,
        "lumen_ref": token,
    })
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment))


@router.get("/go/{token}", include_in_schema=False)
def partner_redirect(token: str, request: Request):
    """Record a LUMEN-originated click, then redirect to the authorized original merchant.

    This endpoint never takes payment or places an order. The buyer transacts with the store. LUMEN's
    role is attribution/intermediation and commission collection under an already-authorized agreement.
    """
    load_state()
    offer = _offer(token)
    if not offer or str(offer.get("status") or "").lower() != "active":
        raise HTTPException(status_code=404, detail="referral_offer_not_available")

    partner = _partner(str(offer.get("partner_id") or ""))
    if not partner or not partner.get("commission_authorized") or partner.get("commercial_status") != "active_partner":
        raise HTTPException(status_code=410, detail="partner_agreement_not_active")

    destination = _destination(offer, partner)
    parsed = urllib.parse.urlparse(destination)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=409, detail="invalid_partner_destination")

    events = STATE.setdefault("partner_attribution_events", [])
    event = {
        "id": f"PAT-{len(events)+1:06d}",
        "event": "referral_click",
        "token": str(offer.get("token") or ""),
        "offer_id": offer.get("id"),
        "partner_id": offer.get("partner_id"),
        "partner_domain": offer.get("partner_domain"),
        "product_key": offer.get("product_key"),
        "created_at": utcnow(),
        "referrer": str(request.headers.get("referer") or "")[:500],
        "user_agent": str(request.headers.get("user-agent") or "")[:300],
        "destination_host": parsed.hostname,
    }
    events.append(event)
    STATE["partner_attribution_events"] = events[-3000:]

    offer["clicks"] = int(offer.get("clicks") or 0) + 1
    offer["last_click_at"] = utcnow()
    partner["referral_clicks"] = int(partner.get("referral_clicks") or 0) + 1
    partner["last_referral_at"] = utcnow()
    STATE.setdefault("activity", []).insert(0, {
        "ts": utcnow(),
        "msg": f"Partner referral: LUMEN derivó una visita atribuible a {partner.get('domain')} mediante {offer.get('id')}."
    })
    STATE["activity"] = STATE["activity"][:100]
    if not save_state():
        raise HTTPException(status_code=503, detail="referral_tracking_persistence_unavailable")

    return RedirectResponse(destination, status_code=302)
