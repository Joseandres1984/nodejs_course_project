from __future__ import annotations

"""Premium art-direction layer for LUMEN Instagram.

Replaces dashboard-like card compositions with restrained editorial layouts:
large typography, negative space, asymmetric abstract visuals and one clear CTA.
The underlying content, QA and explicit human publication approval remain unchanged.
"""

import hashlib
import io
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw

import instagram_publish_control as ipc
import instagram_pro_editorial_runtime as pro


VERSION = "1.0-instagram-premium-art-direction"
ART_VERSION = "3.0-editorial-minimal"

BG = (5, 14, 19)
BG_SOFT = (9, 25, 31)
TEXT = (243, 247, 248)
MUTED = (153, 174, 181)
FAINT = (39, 60, 67)
ACCENT = (215, 255, 100)
ACCENT_SOFT = (171, 205, 78)
INK = (6, 15, 20)

_ORIGINAL_FINGERPRINT = ipc._content_fingerprint


def _clean(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _premium_fingerprint(job: Dict[str, Any]) -> str:
    base = _ORIGINAL_FINGERPRINT(job)
    return hashlib.sha256(f"{base}|{ART_VERSION}".encode("utf-8")).hexdigest()


ipc._content_fingerprint = _premium_fingerprint


def _base_canvas(width: int = 1080, height: int = 1350) -> Image.Image:
    image = Image.new("RGB", (width, height), BG)
    # Soft depth without a visible UI-card frame.
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse((650, -180, 1320, 490), fill=(215, 255, 100, 18))
    od.ellipse((-360, 820, 420, 1600), fill=(79, 126, 141, 18))
    od.rectangle((0, 0, width, height), fill=(5, 14, 19, 24))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: Any) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_width: int, max_lines: int) -> List[str]:
    words = _clean(text, 500).split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _text_width(draw, trial, font) <= max_width or not current:
            current = trial
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    source = " ".join(words)
    shown = " ".join(lines)
    if len(lines) == max_lines and len(shown) < len(source):
        last = lines[-1]
        while last and _text_width(draw, last + "…", font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = last + "…"
    return lines


def _brand(draw: ImageDraw.ImageDraw) -> None:
    draw.ellipse((78, 75, 96, 93), fill=ACCENT)
    draw.text((116, 66), "LUMEN", font=ipc._font(31, True), fill=TEXT)
    draw.text((234, 76), "B2B", font=ipc._font(15, True), fill=MUTED)
    draw.line((78, 122, 1002, 122), fill=(28, 46, 52), width=1)


def _section_label(draw: ImageDraw.ImageDraw, label: str) -> None:
    label = _clean(label, 48).upper()
    draw.line((78, 166, 118, 166), fill=ACCENT, width=4)
    draw.text((138, 150), label, font=ipc._font(18, True), fill=MUTED)


def _headline_and_subtitle(draw: ImageDraw.ImageDraw, headline: str, subtitle: str) -> int:
    headline = _clean(headline, 130)
    if len(headline) <= 48:
        size = 82
    elif len(headline) <= 72:
        size = 72
    else:
        size = 64
    font = ipc._font(size, True)
    lines = _wrap(draw, headline, font, 900, 3)
    y = 216
    for line in lines:
        draw.text((78, y), line, font=font, fill=TEXT)
        y += int(size * 1.08)

    y += 18
    subtitle_font = ipc._font(27, False)
    sub_lines = _wrap(draw, _clean(subtitle, 300), subtitle_font, 820, 2)
    for line in sub_lines:
        draw.text((80, y), line, font=subtitle_font, fill=MUTED)
        y += 39
    return y


def _dot(draw: ImageDraw.ImageDraw, x: int, y: int, radius: int = 9, accent: bool = False) -> None:
    fill = ACCENT if accent else (109, 137, 147)
    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill)


def _visual_radar(draw: ImageDraw.ImageDraw, top: int) -> None:
    cx, cy = 790, max(825, top + 215)
    # Cropped radar creates scale and asymmetry rather than a boxed diagram.
    for r, alpha_color in ((250, FAINT), (180, (48, 74, 82)), (110, (61, 90, 99))):
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=alpha_color, width=2)
    draw.line((cx-310, cy, 1030, cy), fill=(33, 55, 62), width=1)
    draw.line((cx, cy-300, cx, cy+300), fill=(33, 55, 62), width=1)
    # Sweep wedge feel.
    draw.line((cx, cy, cx+205, cy-145), fill=ACCENT_SOFT, width=3)
    for x, y, label in [
        (650, cy-115, "01"),
        (870, cy-45, "02"),
        (735, cy+135, "03"),
    ]:
        _dot(draw, x, y, 10, accent=label == "02")
        draw.text((x+18, y-12), label, font=ipc._font(16, True), fill=MUTED)
    draw.text((78, cy+170), "ALTERNATIVAS", font=ipc._font(18, True), fill=MUTED)
    draw.text((78, cy+202), "COMPARABLES", font=ipc._font(48, True), fill=TEXT)


def _visual_evidence(draw: ImageDraw.ImageDraw, top: int) -> None:
    y = max(760, top + 130)
    cols = [(78, "01", "SEÑAL"), (378, "02", "FUENTE"), (678, "03", "CRITERIO")]
    for x, num, title in cols:
        draw.text((x, y), num, font=ipc._font(20, True), fill=ACCENT)
        draw.text((x, y+52), title, font=ipc._font(30, True), fill=TEXT)
        draw.line((x, y+108, x+220, y+108), fill=FAINT, width=1)
        draw.line((x, y+154, x+180, y+154), fill=(57, 79, 86), width=8)
        draw.line((x, y+188, x+132, y+188), fill=(42, 65, 73), width=8)
        draw.line((x, y+222, x+198, y+222), fill=(49, 72, 80), width=8)
    draw.text((78, y+305), "EVIDENCIA", font=ipc._font(72, True), fill=(32, 53, 60))
    draw.text((533, y+305), "→", font=ipc._font(72, False), fill=ACCENT)
    draw.text((650, y+305), "DECISIÓN", font=ipc._font(72, True), fill=TEXT)


def _visual_matching(draw: ImageDraw.ImageDraw, top: int) -> None:
    cy = max(850, top + 220)
    left, right = (285, cy), (795, cy)
    draw.line((left[0]+110, cy, right[0]-110, cy), fill=(60, 86, 94), width=2)
    draw.ellipse((left[0]-118, cy-118, left[0]+118, cy+118), outline=(72, 99, 108), width=3)
    draw.ellipse((right[0]-118, cy-118, right[0]+118, cy+118), outline=(72, 99, 108), width=3)
    draw.text((left[0]-72, cy-18), "OFERTA", font=ipc._font(24, True), fill=TEXT)
    draw.text((right[0]-88, cy-18), "DEMANDA", font=ipc._font(24, True), fill=TEXT)
    draw.ellipse((500, cy-54, 580, cy+26), fill=ACCENT)
    draw.text((515, cy-37), "↔", font=ipc._font(34, True), fill=INK)
    draw.text((78, cy+190), "EL VALOR ESTÁ EN EL ENCAJE.", font=ipc._font(42, True), fill=TEXT)
    draw.line((78, cy+257, 515, cy+257), fill=ACCENT, width=5)


def _visual_steps(draw: ImageDraw.ImageDraw, top: int) -> None:
    y = max(740, top + 100)
    steps = [("01", "ESPECIFICACIÓN"), ("02", "CONDICIONES"), ("03", "ENTREGA")]
    for idx, (num, title) in enumerate(steps):
        yy = y + idx * 140
        draw.text((78, yy), num, font=ipc._font(64, True), fill=(42, 66, 73))
        draw.text((224, yy+18), title, font=ipc._font(34, True), fill=TEXT)
        draw.line((224, yy+76, 1000, yy+76), fill=FAINT, width=1)
        if idx == 1:
            draw.line((224, yy+76, 472, yy+76), fill=ACCENT, width=4)


def _visual_partner(draw: ImageDraw.ImageDraw, top: int) -> None:
    y = max(760, top + 120)
    # Editorial catalogue sheets; overlapping planes instead of UI cards.
    draw.rounded_rectangle((132, y+36, 830, y+350), radius=28, fill=(11, 29, 35), outline=(37, 60, 67), width=2)
    draw.rounded_rectangle((192, y, 900, y+330), radius=28, fill=(14, 35, 42), outline=(49, 73, 80), width=2)
    draw.rounded_rectangle((252, y-34, 962, y+296), radius=28, fill=(18, 42, 49), outline=(60, 86, 94), width=2)
    # Product-like abstract modules.
    for i, x in enumerate((302, 505, 708)):
        draw.rounded_rectangle((x, y+30, x+150, y+180), radius=18, fill=(8, 24, 30))
        draw.ellipse((x+40, y+58, x+110, y+128), outline=ACCENT if i == 1 else (81, 110, 119), width=3)
        draw.line((x+28, y+215, x+122, y+215), fill=(71, 98, 107), width=7)
        draw.line((x+28, y+244, x+94, y+244), fill=(47, 72, 80), width=7)
    draw.text((78, y+395), "CATÁLOGO", font=ipc._font(26, True), fill=MUTED)
    draw.text((78, y+435), "→ OPORTUNIDAD", font=ipc._font(52, True), fill=TEXT)


def _draw_art(draw: ImageDraw.ImageDraw, style: str, top: int) -> None:
    if style == "procurement_radar":
        _visual_radar(draw, top)
    elif style == "matching_network":
        _visual_matching(draw, top)
    elif style == "education_steps":
        _visual_steps(draw, top)
    elif style == "partner_channel":
        _visual_partner(draw, top)
    else:
        _visual_evidence(draw, top)


def _footer(draw: ImageDraw.ImageDraw, cta: str) -> None:
    y = 1228
    draw.line((78, y, 1002, y), fill=(28, 48, 55), width=1)
    cta = _clean(cta, 56).upper()
    draw.text((78, y+35), cta, font=ipc._font(19, True), fill=ACCENT)
    # Small arrow acts as a restrained CTA marker rather than a button.
    draw.text((920, y+25), "→", font=ipc._font(34, True), fill=ACCENT)
    draw.text((78, 1310), "lumen.b2b", font=ipc._font(15, True), fill=(96, 120, 128))


def _render_premium(job: Dict[str, Any]) -> bytes:
    image = _base_canvas()
    draw = ImageDraw.Draw(image)
    meta = pro._fallback_metadata(job)

    _brand(draw)
    _section_label(draw, str(meta.get("label") or "INTELIGENCIA COMERCIAL"))
    text_bottom = _headline_and_subtitle(
        draw,
        str(meta.get("headline") or "Inteligencia comercial B2B."),
        str(meta.get("subtitle") or "Información útil para decisiones comerciales con más contexto."),
    )
    _draw_art(draw, str(meta.get("style") or "evidence_grid"), text_bottom)
    _footer(draw, str(meta.get("cta") or "CONOCÉ LUMEN"))

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95, optimize=True, progressive=True, subsampling=0)
    return output.getvalue()


ipc._render_job_jpeg = _render_premium

print({
    "instagram_art_direction": {
        "version": VERSION,
        "status": "active",
        "render_version": ART_VERSION,
        "design_language": "editorial_minimal_b2b_premium",
        "outer_dashboard_frame": False,
        "negative_space": True,
        "asymmetric_visuals": True,
        "single_cta": True,
        "human_approval_unchanged": True,
    }
}, flush=True)
