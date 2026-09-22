#!/usr/bin/env python3
import argparse
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageStat
from pypdf import PdfReader


A4_WIDTH = 595.28
A4_HEIGHT = 841.89
A4_TOLERANCE_PTS = 7.0


def fail(message, detail=None):
    print(json.dumps({"ok": False, "error": message, "detail": detail or ""}, ensure_ascii=False))
    raise SystemExit(1)


def run(*cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        fail("command_failed", {"cmd": list(cmd), "stderr": p.stderr[-1500:]})
    return p.stdout


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


def compact(s):
    # Text extractors can insert line breaks/spaces around punctuation. Compare
    # identifiers on their alphanumeric skeleton while keeping normal text
    # checks for titles and human-readable content.
    return re.sub(r"[^0-9a-záéíóúüñ]+", "", str(s or "").casefold())


def nonwhite_ratio(image_path):
    with Image.open(image_path) as im:
        rgb = im.convert("RGB")
        original_size = rgb.size
        rgb.thumbnail((800, 1200))
        pixels = rgb.load()
        w, h = rgb.size
        nonwhite = 0
        dark = 0
        total = max(1, w * h)
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                if min(r, g, b) < 248:
                    nonwhite += 1
                if max(r, g, b) < 35:
                    dark += 1
        gray = rgb.convert("L")
        stat = ImageStat.Stat(gray)
        extrema = gray.getextrema()
        return {
            "nonwhite_ratio": nonwhite / total,
            "dark_ratio": dark / total,
            "render_size": original_size,
            "sample_size": (w, h),
            "gray_mean": float(stat.mean[0]),
            "gray_extrema": extrema,
        }


def assert_a4(width, height, page=None):
    short, long = sorted((float(width), float(height)))
    if abs(short - A4_WIDTH) > A4_TOLERANCE_PTS or abs(long - A4_HEIGHT) > A4_TOLERANCE_PTS:
        fail("page_not_a4", {"page": page, "width": width, "height": height})
    ratio = short / long
    if abs(ratio - (1 / math.sqrt(2))) > 0.02:
        fail("page_not_a4_ratio", {"page": page, "width": width, "height": height, "ratio": ratio})


def require_sections(text_n, tier):
    common = [
        "pedido del cliente",
        "hallazgos clave",
        "riesgos y gaps",
        "evidencia y fuentes",
        "metodología",
        "limitaciones",
        "próximos pasos",
        "conclusión",
    ]
    executive = "respuesta ejecutiva" if tier == "micro" else "resumen ejecutivo"
    missing = [heading for heading in [executive, *common] if norm(heading) not in text_n]
    if missing:
        fail("required_sections_missing", missing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--report-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--tier", choices=["micro", "full"], required=True)
    ap.add_argument("--preview-dir", default="")
    args = ap.parse_args()

    pdf = Path(args.pdf).resolve()
    if not pdf.exists():
        fail("pdf_missing", str(pdf))
    size_bytes = pdf.stat().st_size
    if size_bytes < 12000:
        fail("pdf_too_small", size_bytes)

    with pdf.open("rb") as fh:
        head = fh.read(5)
        if head != b"%PDF-":
            fail("bad_pdf_signature")
        fh.seek(max(0, size_bytes - 4096))
        tail = fh.read()
        if b"%%EOF" not in tail:
            fail("pdf_eof_marker_missing")

    try:
        reader = PdfReader(str(pdf), strict=True)
    except Exception as exc:
        fail("pypdf_open_failed", str(exc))
    if reader.is_encrypted:
        fail("encrypted_pdf_not_allowed")
    if "/Root" not in reader.trailer:
        fail("pdf_catalog_missing")

    pages = len(reader.pages)
    if pages < 1:
        fail("pdf_has_no_pages")
    max_pages = 3 if args.tier == "micro" else 15
    min_pages = 1 if args.tier == "micro" else 2
    if not min_pages <= pages <= max_pages:
        fail("unexpected_page_count", {"pages": pages, "tier": args.tier, "min": min_pages, "max": max_pages})

    page_sizes = []
    page_text_stats = []
    for index, page in enumerate(reader.pages, 1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        assert_a4(width, height, index)
        page_sizes.append([round(width, 2), round(height, 2)])
        try:
            extracted = norm(page.extract_text() or "")
        except Exception as exc:
            fail("page_text_extraction_failed", {"page": index, "error": str(exc)})
        useful = re.sub(r"[^0-9a-záéíóúüñ]+", "", extracted)
        if len(useful) < 70:
            fail("page_text_too_sparse", {"page": index, "chars": len(useful)})
        page_text_stats.append({"page": index, "chars": len(extracted), "useful_chars": len(useful)})

    meta = reader.metadata or {}
    title_meta = norm(meta.get("/Title", ""))
    subject_meta = norm(meta.get("/Subject", ""))
    author_meta = norm(meta.get("/Author", ""))
    creator_meta = norm(meta.get("/Creator", ""))
    if norm(args.title) not in title_meta and title_meta not in norm(args.title):
        fail("metadata_title_mismatch", {"expected": args.title, "actual": meta.get("/Title")})
    if compact(args.report_id) not in compact(subject_meta):
        fail("metadata_report_id_missing", meta.get("/Subject"))
    if "lumen" not in author_meta:
        fail("metadata_author_missing", meta.get("/Author"))
    if "lumen" not in creator_meta:
        fail("metadata_creator_missing", meta.get("/Creator"))

    text = run("pdftotext", "-layout", str(pdf), "-")
    text_n = norm(text)
    text_compact = compact(text)
    if "lumen" not in text_n:
        fail("required_text_missing", "LUMEN")
    if norm(args.title) not in text_n:
        fail("required_text_missing", args.title)
    if compact(args.report_id) not in text_compact:
        fail("required_text_missing", args.report_id)
    require_sections(text_n, args.tier)

    min_chars = 650 if args.tier == "micro" else 1800
    if len(text_n) < min_chars:
        fail("extracted_text_too_short", {"chars": len(text_n), "min": min_chars})

    min_sources = 2 if args.tier == "micro" else 3
    visible_urls = len(re.findall(r"https?\s*:\s*/\s*/", text, flags=re.I))
    if visible_urls < min_sources:
        # Poppler can occasionally separate the scheme less predictably. A
        # simple 'http' fallback still ensures source URLs survived rendering.
        visible_urls = len(re.findall(r"\bhttp", text, flags=re.I))
    if visible_urls < min_sources:
        fail("insufficient_visible_source_urls", {"count": visible_urls, "min": min_sources})

    forbidden = [
        "�",
        "aw, snap",
        "page crashed",
        "error code: out of memory",
        "lumen-draft",
        "no informado",
        "lorem ipsum",
        "placeholder",
        "revisar los hallazgos y próximos pasos.",
    ]
    for bad in forbidden:
        if norm(bad) in text_n:
            fail("render_corruption_or_placeholder_marker", bad)
    if re.search(r"\b(todo|tbd)\b", text_n, flags=re.I):
        fail("render_placeholder_marker", "TODO/TBD")

    info = run("pdfinfo", str(pdf))
    page_count_match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
    if not page_count_match or int(page_count_match.group(1)) != pages:
        fail("pdfinfo_page_count_mismatch", {"pypdf": pages, "pdfinfo": page_count_match.group(1) if page_count_match else None})
    m = re.search(r"^Page size:\s+([0-9.]+) x ([0-9.]+) pts", info, re.MULTILINE)
    if not m:
        fail("page_size_unreadable")
    assert_a4(float(m.group(1)), float(m.group(2)), 1)

    preview_root = Path(args.preview_dir).resolve() if args.preview_dir else Path(tempfile.mkdtemp(prefix="lumen-pdf-preview-"))
    preview_root.mkdir(parents=True, exist_ok=True)
    prefix = preview_root / pdf.stem
    run("pdftoppm", "-png", "-r", "110", str(pdf), str(prefix))
    images = sorted(preview_root.glob(f"{pdf.stem}-*.png"))
    if len(images) != pages:
        fail("rendered_page_count_mismatch", {"pdf_pages": pages, "png_pages": len(images)})

    page_stats = []
    expected_render_size = None
    for i, image in enumerate(images, 1):
        stats = nonwhite_ratio(image)
        nonwhite = stats["nonwhite_ratio"]
        dark = stats["dark_ratio"]
        render_size = stats["render_size"]
        gray_min, gray_max = stats["gray_extrema"]

        if render_size[0] < 700 or render_size[1] < 1000 or render_size[1] <= render_size[0]:
            fail("unexpected_page_render_dimensions", {"page": i, "pixels": render_size})
        if expected_render_size is None:
            expected_render_size = render_size
        elif abs(render_size[0] - expected_render_size[0]) > 2 or abs(render_size[1] - expected_render_size[1]) > 2:
            fail("inconsistent_page_render_dimensions", {"page": i, "expected": expected_render_size, "actual": render_size})
        if nonwhite < 0.003:
            fail("blank_or_near_blank_page", {"page": i, "nonwhite_ratio": nonwhite})
        if dark > 0.78:
            fail("page_mostly_black", {"page": i, "dark_ratio": dark})
        if gray_max - gray_min < 8:
            fail("flat_or_corrupt_render", {"page": i, "gray_extrema": [gray_min, gray_max]})

        page_stats.append({
            "page": i,
            "nonwhite_ratio": round(nonwhite, 5),
            "dark_ratio": round(dark, 5),
            "gray_mean": round(stats["gray_mean"], 2),
            "gray_extrema": [gray_min, gray_max],
            "pixels": list(render_size),
        })

    print(json.dumps({
        "ok": True,
        "pdf": str(pdf),
        "bytes": size_bytes,
        "pages": pages,
        "tier": args.tier,
        "report_id": args.report_id,
        "page_sizes_pts": page_sizes,
        "text_chars": len(text_n),
        "visible_source_urls": visible_urls,
        "page_text_stats": page_text_stats,
        "previews": [str(p) for p in images],
        "page_stats": page_stats,
        "quality_gate": "client_delivery_ready",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
