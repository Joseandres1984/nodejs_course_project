from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app import app, auth
from viator_affiliate_core import ViatorAffiliateError, build_viator_affiliate_url

VIATOR_AFFILIATE_PID = os.getenv("LUMEN_VIATOR_AFFILIATE_PID", "P00322694")
VIATOR_MCID = os.getenv("LUMEN_VIATOR_MCID", "42383")
VIATOR_MEDIUM = os.getenv("LUMEN_VIATOR_MEDIUM", "link")
VIATOR_MEDIUM_VERSION = os.getenv("LUMEN_VIATOR_MEDIUM_VERSION", "selector")


class ViatorLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4000)


class ViatorBatchRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)


def monetized_link(url: str) -> str:
    try:
        return build_viator_affiliate_url(
            url,
            pid=VIATOR_AFFILIATE_PID,
            mcid=VIATOR_MCID,
            medium=VIATOR_MEDIUM,
            medium_version=VIATOR_MEDIUM_VERSION,
        )
    except ViatorAffiliateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/health/viator-affiliate", include_in_schema=False)
def viator_affiliate_health():
    return {
        "ok": bool(VIATOR_AFFILIATE_PID),
        "provider": "viator",
        "mode": "affiliate-link-generation",
        "network_calls": 0,
    }


@app.get("/api/affiliate/viator/config")
def viator_config(_=Depends(auth)):
    return {
        "ok": True,
        "provider": "viator",
        "enabled": bool(VIATOR_AFFILIATE_PID),
        "pid": VIATOR_AFFILIATE_PID,
        "mcid": VIATOR_MCID,
        "medium": VIATOR_MEDIUM,
        "medium_version": VIATOR_MEDIUM_VERSION,
        "disclosure": "Affiliate link: LUMEN may earn a commission if a booking is completed.",
    }


@app.post("/api/affiliate/viator/link")
def viator_link(payload: ViatorLinkRequest, _=Depends(auth)):
    link = monetized_link(payload.url)
    return {
        "ok": True,
        "provider": "viator",
        "original_url": payload.url,
        "affiliate_url": link,
        "monetized": True,
    }


@app.post("/api/affiliate/viator/batch")
def viator_batch(payload: ViatorBatchRequest, _=Depends(auth)):
    results = []
    for url in payload.urls:
        try:
            results.append(
                {
                    "original_url": url,
                    "affiliate_url": build_viator_affiliate_url(
                        url,
                        pid=VIATOR_AFFILIATE_PID,
                        mcid=VIATOR_MCID,
                        medium=VIATOR_MEDIUM,
                        medium_version=VIATOR_MEDIUM_VERSION,
                    ),
                    "monetized": True,
                }
            )
        except ViatorAffiliateError as exc:
            results.append(
                {
                    "original_url": url,
                    "affiliate_url": None,
                    "monetized": False,
                    "error": str(exc),
                }
            )
    return {"ok": True, "provider": "viator", "results": results}


@app.get("/go/viator", include_in_schema=False)
def viator_redirect(url: str = Query(min_length=1, max_length=4000)):
    """Public redirect used by LUMEN recommendations; only validated Viator hosts are allowed."""
    return RedirectResponse(url=monetized_link(url), status_code=307)
