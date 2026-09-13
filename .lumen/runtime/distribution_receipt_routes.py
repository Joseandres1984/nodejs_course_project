from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse

from app import auth
from distribution_proof import record_distribution_receipt
from main import STATE, load_state, save_state


router = APIRouter()


@router.post('/api/distribution-receipt', include_in_schema=False)
def distribution_receipt_submit(
    campaign_id: str = Form(...),
    variant_id: str = Form(...),
    channel: str = Form(...),
    provider: str = Form(''),
    external_post_id: str = Form(''),
    external_url: str = Form(''),
    published_at: str = Form(''),
    impressions: int = Form(0),
    clicks: int = Form(0),
    status: str = Form('published'),
    _=Depends(auth),
):
    load_state()
    if not campaign_id.strip() or not variant_id.strip() or not channel.strip():
        raise HTTPException(status_code=400, detail='campaign_variant_channel_required')
    if not external_post_id.strip() and not external_url.strip():
        raise HTTPException(status_code=400, detail='external_publication_evidence_required')
    record_distribution_receipt(
        STATE,
        campaign_id=campaign_id.strip(),
        variant_id=variant_id.strip(),
        channel=channel.strip(),
        provider=provider.strip(),
        external_post_id=external_post_id.strip(),
        external_url=external_url.strip(),
        published_at=published_at.strip(),
        impressions=max(0, impressions),
        clicks=max(0, clicks),
        status=status.strip() or 'published',
        source='authenticated_receipt_ingestion',
    )
    if not save_state():
        raise HTTPException(status_code=503, detail='receipt_received_but_persistence_unavailable')
    return RedirectResponse('/distribution-proof', status_code=303)
