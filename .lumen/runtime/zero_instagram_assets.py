from __future__ import annotations

"""Materialize Instagram JPEGs from D1 state into the public lumen-zero branch.

The normal Instagram publishing control expects a public HTTPS image. Railway previously served
those generated images. LUMEN Zero instead stores deterministic JPEGs in the public GitHub branch
and serves them through the zero-cost Cloudflare public Worker.

The renderer is pixel-safe: visible text is measured with Pillow bounding boxes, wrapped only at
word boundaries, reduced in size when necessary, and rejected before materialization if it cannot
fit inside the declared safe area. This prevents source assets from clipping long headlines.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

import d1_persistence_runtime  # patches app persistence
from app import STATE, load_state, save_state

PUBLIC_BASE_URL = (os.getenv("LUMEN_PUBLIC_BASE_URL") or "https://lumen-zero-public.lumen-b2b.workers.dev").rstrip("/")
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"

WIDTH, HEIGHT = 1080, 1350
SAFE_LEFT = 122
SAFE_RIGHT = 958
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT
TITLE_TOP = 345
FOOTER_TOP = 1128
BODY_BOTTOM = 1082
RENDERER_VERSION = "2.0-source-pixel-safe"


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


def _clean(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return int(box[2] - box[0])


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> List[str]:
    words = _clean(text).split()
    if not words:
        return []
    # Never split a visible word in the middle. If even one word cannot fit,
    # the caller must reduce font size or reject the asset.
    if any(_text_width(draw, word, font) > max_width for word in words):
        return []

    lines: List[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
    max_size: int,
    min_size: int,
    bold: bool,
) -> Tuple[Any, List[str], int]:
    cleaned = _clean(text)
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, bold)
        lines = _wrap_pixels(draw, cleaned, font, max_width)
        if not lines or len(lines) > max_lines:
            continue
        if all(_text_width(draw, line, font) <= max_width for line in lines):
            return font, lines, size
    raise ValueError(f"pixel_safe_text_does_not_fit:{cleaned[:100]}")


def _headline(job: Dict[str, Any]) -> str:
    for key in ("headline", "title", "hook", "service_name", "audience"):
        value = _clean(job.get(key), 90)
        if value:
            return value
    return "INTELIGENCIA COMERCIAL"


def _body(job: Dict[str, Any]) -> str:
    value = _clean(job.get("copy") or job.get("caption") or job.get("message"), 340)
    if not value:
        value = "Detectamos oportunidades. Conectamos demanda y oferta. Convertimos información en acción."
    return value


def _render(job: Dict[str, Any], path: Path) -> Dict[str, Any]:
    image = Image.new("RGB", (WIDTH, HEIGHT), (7, 18, 25))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((64, 64, 1016, 1286), radius=48, fill=(12, 31, 40), outline=(34, 63, 74), width=3)
    draw.rounded_rectangle((88, 88, 992, 230), radius=28, fill=(216, 255, 102))
    draw.text((124, 127), "LUMEN B2B", font=_font(62, True), fill=(7, 18, 25))

    headline = _headline(job).upper()
    title_font, title_lines, title_size = _fit_text(
        draw,
        headline,
        max_width=SAFE_WIDTH,
        max_lines=4,
        max_size=67,
        min_size=40,
        bold=True,
    )
    title_step = max(int(title_size * 1.17), title_size + 8)
    y = TITLE_TOP
    for line in title_lines:
        draw.text((SAFE_LEFT, y), line, font=title_font, fill=(238, 244, 247))
        y += title_step

    body = _body(job)
    body_font, body_lines, body_size = _fit_text(
        draw,
        body,
        max_width=SAFE_WIDTH,
        max_lines=7,
        max_size=34,
        min_size=22,
        bold=False,
    )
    y = max(y + 54, 650)
    body_step = max(int(body_size * 1.48), body_size + 10)
    body_end = y + len(body_lines) * body_step
    if body_end > BODY_BOTTOM:
        raise ValueError(f"pixel_safe_vertical_overflow:body_end={body_end}:limit={BODY_BOTTOM}")
    for line in body_lines:
        draw.text((SAFE_LEFT, y), line, font=body_font, fill=(202, 218, 226))
        y += body_step

    footer = "Inteligencia · Sourcing · Oportunidades B2B"
    footer_font, footer_lines, footer_size = _fit_text(
        draw,
        footer,
        max_width=SAFE_WIDTH,
        max_lines=1,
        max_size=31,
        min_size=24,
        bold=True,
    )
    contact = "Argentina · @lumen.b2b"
    contact_font, contact_lines, contact_size = _fit_text(
        draw,
        contact,
        max_width=SAFE_WIDTH,
        max_lines=1,
        max_size=28,
        min_size=22,
        bold=False,
    )
    draw.text((SAFE_LEFT, FOOTER_TOP), footer_lines[0], font=footer_font, fill=(216, 255, 102))
    draw.text((SAFE_LEFT, 1204), contact_lines[0], font=contact_font, fill=(157, 179, 190))

    overflow = []
    measured_blocks = (
        ("headline", title_lines, title_font),
        ("body", body_lines, body_font),
        ("footer", footer_lines, footer_font),
        ("contact", contact_lines, contact_font),
    )
    for block, lines, font in measured_blocks:
        for line in lines:
            width = _text_width(draw, line, font)
            if width > SAFE_WIDTH:
                overflow.append({"block": block, "line": line, "width": width, "safe_width": SAFE_WIDTH})
    if overflow:
        raise ValueError(f"pixel_safe_horizontal_overflow:{overflow}")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=92, optimize=True, progressive=True, subsampling=0)
    return {
        "status": "PASS",
        "version": RENDERER_VERSION,
        "safe_left": SAFE_LEFT,
        "safe_right": SAFE_RIGHT,
        "safe_width": SAFE_WIDTH,
        "headline": headline,
        "headline_lines": title_lines,
        "headline_size": title_size,
        "headline_max_width": max((_text_width(draw, line, title_font) for line in title_lines), default=0),
        "body_lines": body_lines,
        "body_size": body_size,
        "footer_size": footer_size,
        "contact_size": contact_size,
        "overflow_blocks": overflow,
    }


def main() -> int:
    report = {"status": "ok", "jobs_seen": 0, "assets_written": 0, "state_urls_repaired": 0, "renderer_version": RENDERER_VERSION}
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
        render_report = _render(job, path)
        report["assets_written"] += 1
        desired = f"{PUBLIC_BASE_URL}/media/instagram/{jid}.jpg"
        if str(job.get("image_url") or "") != desired or str(job.get("media_source") or "") != "lumen_zero_git_asset_v2_pixel_safe":
            job["image_url"] = desired
            job["media_source"] = "lumen_zero_git_asset_v2_pixel_safe"
            job["media_renderer_version"] = render_report["version"]
            job["media_layout_qa"] = {
                "status": render_report["status"],
                "safe_width": render_report["safe_width"],
                "headline_size": render_report["headline_size"],
                "headline_max_width": render_report["headline_max_width"],
                "overflow_blocks": render_report["overflow_blocks"],
            }
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
