from __future__ import annotations

"""Materialize Instagram JPEGs from D1 state into the public lumen-zero branch.

The normal Instagram publishing control expects a public HTTPS image. Railway previously served
those generated images. LUMEN Zero instead stores deterministic JPEGs in the public GitHub branch
and serves them through the zero-cost Cloudflare public Worker.
"""

import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageDraw, ImageFont

import d1_persistence_runtime  # patches app persistence
from app import STATE, load_state, save_state

PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: Any) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", str(value or "instagram"))[:180]
    return name or "instagram"


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _headline(job: Dict[str, Any]) -> str:
    for key in ("headline", "title", "hook", "service_name", "audience"):
        value = " ".join(str(job.get(key) or "").split())
        if value:
            return value[:90]
    return "INTELIGENCIA COMERCIAL"


def _body(job: Dict[str, Any]) -> str:
    value = " ".join(str(job.get("copy") or job.get("caption") or job.get("message") or "").split())
    if not value:
        value = "Detectamos oportunidades. Conectamos demanda y oferta. Convertimos información en acción."
    return value[:340]


def _render(job: Dict[str, Any], path: Path) -> None:
    width, height = 1080, 1350
    image = Image.new("RGB", (width, height), (7, 18, 25))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 64, 1016, 1286), radius=48, fill=(12, 31, 40), outline=(34, 63, 74), width=3)
    draw.rounded_rectangle((88, 88, 992, 230), radius=28, fill=(216, 255, 102))
    draw.text((124, 127), "LUMEN B2B", font=_font(62, True), fill=(7, 18, 25))

    headline = _headline(job).upper()
    lines = textwrap.wrap(headline, width=22)[:3]
    y = 345
    for line in lines:
        draw.text((122, y), line, font=_font(67, True), fill=(238, 244, 247))
        y += 78

    body_lines = textwrap.wrap(_body(job), width=42)[:7]
    y = max(y + 70, 650)
    for line in body_lines:
        draw.text((124, y), line, font=_font(34), fill=(202, 218, 226))
        y += 51

    footer = "Inteligencia · Sourcing · Oportunidades B2B"
    draw.text((124, 1128), footer, font=_font(31, True), fill=(216, 255, 102))
    draw.text((124, 1204), "Argentina · @lumen.b2b", font=_font(28), fill=(157, 179, 190))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=90, optimize=True, progressive=True)


def main() -> int:
    report = {"status": "ok", "jobs_seen": 0, "assets_written": 0, "state_urls_repaired": 0}
    if not load_state():
        print({"zero_instagram_assets": {**report, "status": "state_unavailable"}}, flush=True)
        return 1
    changed = False
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for job in STATE.get("distribution_operator_jobs", []) or []:
        if not isinstance(job, dict) or str(job.get("channel") or "") != "instagram":
            continue
        if str(job.get("status") or "") == "verified_published":
            continue
        report["jobs_seen"] += 1
        jid = _safe_name(job.get("id"))
        existing = str(job.get("image_url") or job.get("creative_asset_url") or "").strip()
        needs_zero_media = (not existing) or ("up.railway.app" in existing) or (existing.startswith(PUBLIC_BASE_URL + "/media/instagram/"))
        if not needs_zero_media:
            continue
        path = OUT_DIR / f"{jid}.jpg"
        _render(job, path)
        report["assets_written"] += 1
        desired = f"{PUBLIC_BASE_URL}/media/instagram/{jid}.jpg"
        if str(job.get("image_url") or "") != desired:
            job["image_url"] = desired
            job["media_source"] = "lumen_zero_git_asset_v1"
            job["media_prepared_at"] = _now()
            report["state_urls_repaired"] += 1
            changed = True
    STATE["zero_instagram_assets"] = {**report, "updated_at": _now(), "public_base_url": PUBLIC_BASE_URL}
    if changed:
        save_state()
    print({"zero_instagram_assets": report}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
