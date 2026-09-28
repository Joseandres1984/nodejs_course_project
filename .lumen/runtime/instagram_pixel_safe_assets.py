from __future__ import annotations

"""Materialize pixel-safe Instagram assets for LUMEN's legacy/control posts.

The original legacy renderer wrapped headlines by character count. A line could therefore
fit the character limit while exceeding the real pixel width of the 1080px canvas. This
module wraps and fits text using Pillow text bounding boxes, then writes a static asset for
each legacy Instagram job. Premium IGPRO/IGTHEME assets are left untouched when already
materialized.

This module only prepares image files. It does not approve or publish posts and does not
change canonical commercial state.
"""

import io
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from PIL import Image, ImageDraw, ImageFont


VERSION = "1.0-pixel-safe-static-assets"
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "instagram"
WIDTH = HEIGHT = 1080
SAFE_LEFT = 92
SAFE_RIGHT = 988
SAFE_WIDTH = SAFE_RIGHT - SAFE_LEFT


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


def _split_oversize_word(draw: ImageDraw.ImageDraw, word: str, font: Any, max_width: int) -> List[str]:
    if _text_width(draw, word, font) <= max_width:
        return [word]
    chunks: List[str] = []
    current = ""
    for ch in word:
        trial = current + ch
        if current and _text_width(draw, trial, font) > max_width:
            chunks.append(current)
            current = ch
        else:
            current = trial
    if current:
        chunks.append(current)
    return chunks


def _wrap_pixels(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int) -> List[str]:
    words: List[str] = []
    for raw in _clean(text).split():
        words.extend(_split_oversize_word(draw, raw, font, max_width))
    lines: List[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if _text_width(draw, trial, font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_lines: int,
    max_size: int,
    min_size: int,
    bold: bool,
) -> Tuple[Any, List[str], int]:
    for size in range(max_size, min_size - 1, -2):
        font = _font(size, bold)
        lines = _wrap_pixels(draw, text, font, max_width)
        if lines and len(lines) <= max_lines and all(_text_width(draw, line, font) <= max_width for line in lines):
            return font, lines, size
    raise ValueError(f"pixel_safe_text_does_not_fit:{_clean(text, 80)}")


def _headline(job: Dict[str, Any]) -> str:
    direct = _clean(job.get("headline"), 220)
    if direct:
        return direct
    raw = _clean(job.get("copy") or job.get("caption"), 1000)
    if raw:
        return raw.split(". ", 1)[0].strip()[:220]
    return "Oportunidades B2B con más evidencia."


def render_legacy_asset(job: Dict[str, Any]) -> Tuple[Path, Dict[str, Any]]:
    image = Image.new("RGB", (WIDTH, HEIGHT), (6, 17, 23))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((58, 58, 1022, 1022), radius=54, fill=(11, 29, 37), outline=(35, 64, 75), width=3)
    draw.rounded_rectangle((80, 80, 1000, 188), radius=32, fill=(215, 255, 100))
    draw.text((112, 108), "LUMEN B2B", font=_font(48, True), fill=(7, 16, 24))

    audience = _clean(job.get("audience") or "B2B", 80).upper()
    draw.text((SAFE_LEFT, 235), audience, font=_font(28, True), fill=(170, 191, 200))

    title = _headline(job)
    title_font, title_lines, title_size = _fit_text(draw, title, SAFE_WIDTH, 5, 62, 42, True)
    y = 300
    title_step = int(title_size * 1.24)
    for line in title_lines:
        draw.text((SAFE_LEFT, y), line, font=title_font, fill=(238, 245, 248))
        y += title_step

    body = _clean(job.get("visual_subtitle"), 350) or "LUMEN investiga, compara y organiza oportunidades comerciales para compradores y proveedores."
    body_font, body_lines, body_size = _fit_text(draw, body, SAFE_WIDTH, 4, 34, 24, False)
    y = max(y + 34, 700)
    body_step = int(body_size * 1.42)
    for line in body_lines:
        draw.text((SAFE_LEFT, y), line, font=body_font, fill=(183, 203, 211))
        y += body_step

    draw.text((SAFE_LEFT, 952), "lumen.b2b", font=_font(30, True), fill=(215, 255, 100))

    overflow = []
    for line in title_lines:
        width = _text_width(draw, line, title_font)
        if width > SAFE_WIDTH:
            overflow.append({"block": "headline", "line": line, "width": width})
    for line in body_lines:
        width = _text_width(draw, line, body_font)
        if width > SAFE_WIDTH:
            overflow.append({"block": "body", "line": line, "width": width})
    if overflow:
        raise ValueError(f"pixel_overflow:{overflow}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    job_id = _clean(job.get("id"), 180)
    if not job_id:
        raise ValueError("missing_job_id")
    path = OUT_DIR / f"{job_id}.jpg"
    image.save(path, "JPEG", quality=95, optimize=True, progressive=True, subsampling=0)
    return path, {
        "status": "PASS",
        "version": VERSION,
        "job_id": job_id,
        "headline": title,
        "headline_lines": title_lines,
        "headline_size": title_size,
        "safe_width": SAFE_WIDTH,
        "max_headline_width": max((_text_width(draw, x, title_font) for x in title_lines), default=0),
        "overflow_blocks": overflow,
    }


def materialize_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rendered = []
    skipped = []
    failures = []
    for job in state.get("distribution_operator_jobs", []) or []:
        if not isinstance(job, dict) or str(job.get("channel") or "") != "instagram":
            continue
        job_id = _clean(job.get("id"), 180)
        if not job_id:
            continue
        target = OUT_DIR / f"{job_id}.jpg"
        premium = bool(job.get("editorial_pro_v3")) or str(job.get("content_mode") or "") == "thematic_on_demand" or job_id.startswith("IGTHEME-")
        pro = bool(job.get("editorial_pro_v1")) or job_id.startswith("IGPRO-")
        if premium or pro:
            if target.exists():
                skipped.append({"job_id": job_id, "reason": "premium_asset_already_materialized"})
            else:
                skipped.append({"job_id": job_id, "reason": "premium_asset_requires_premium_renderer"})
            continue
        try:
            path, report = render_legacy_asset(job)
            rendered.append({"job_id": job_id, "path": str(path), **report})
        except Exception as exc:
            failures.append({"job_id": job_id, "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    return {
        "version": VERSION,
        "status": "PASS" if not failures else "PARTIAL",
        "rendered": rendered,
        "skipped": skipped,
        "failures": failures,
        "rendered_count": len(rendered),
        "failure_count": len(failures),
    }


def main() -> int:
    import d1_persistence_runtime  # noqa: F401
    import zero_watchdog_runtime  # noqa: F401
    import app as lumen_app

    if not lumen_app.load_state():
        raise RuntimeError("lumen_zero_state_unavailable")
    report = materialize_from_state(lumen_app.STATE)
    print({"instagram_pixel_safe_assets": report}, flush=True)
    if report["failure_count"]:
        raise RuntimeError(f"pixel_safe_asset_failures:{report['failure_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
