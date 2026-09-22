#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageStat
from pypdf import PdfReader


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


def nonwhite_ratio(image_path):
    with Image.open(image_path) as im:
        rgb = im.convert("RGB")
        # Downsample for a stable and cheap blank-page test.
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
        return nonwhite / total, dark / total, (w, h)


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
    if pdf.stat().st_size < 12000:
        fail("pdf_too_small", pdf.stat().st_size)
    with pdf.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            fail("bad_pdf_signature")

    try:
        reader = PdfReader(str(pdf), strict=True)
    except Exception as exc:
        fail("pypdf_open_failed", str(exc))
    pages = len(reader.pages)
    if pages < 1:
        fail("pdf_has_no_pages")
    max_pages = 6 if args.tier == "micro" else 20
    if pages > max_pages:
        fail("unexpected_page_count", {"pages": pages, "tier": args.tier, "max": max_pages})

    meta = reader.metadata or {}
    title_meta = norm(meta.get("/Title", ""))
    subject_meta = norm(meta.get("/Subject", ""))
    if norm(args.title) not in title_meta and title_meta not in norm(args.title):
        fail("metadata_title_mismatch", {"expected": args.title, "actual": meta.get("/Title")})
    if norm(args.report_id) not in subject_meta:
        fail("metadata_report_id_missing", meta.get("/Subject"))

    text = run("pdftotext", "-layout", str(pdf), "-")
    text_n = norm(text)
    for required in ["lumen", args.report_id, args.title]:
        if norm(required) not in text_n:
            fail("required_text_missing", required)
    if not any(token in text_n for token in ["conclusión", "conclusion"]):
        fail("conclusion_missing")
    if len(text_n) < (450 if args.tier == "micro" else 900):
        fail("extracted_text_too_short", len(text_n))

    info = run("pdfinfo", str(pdf))
    m = re.search(r"^Page size:\s+([0-9.]+) x ([0-9.]+) pts", info, re.MULTILINE)
    if not m:
        fail("page_size_unreadable")
    width, height = float(m.group(1)), float(m.group(2))
    ratio = min(width, height) / max(width, height)
    if abs(ratio - (1 / math.sqrt(2))) > 0.035:
        fail("page_not_a4_like", {"width": width, "height": height, "ratio": ratio})

    preview_root = Path(args.preview_dir).resolve() if args.preview_dir else Path(tempfile.mkdtemp(prefix="lumen-pdf-preview-"))
    preview_root.mkdir(parents=True, exist_ok=True)
    prefix = preview_root / pdf.stem
    run("pdftoppm", "-png", "-r", "110", str(pdf), str(prefix))
    images = sorted(preview_root.glob(f"{pdf.stem}-*.png"))
    if len(images) != pages:
        fail("rendered_page_count_mismatch", {"pdf_pages": pages, "png_pages": len(images)})

    page_stats = []
    for i, image in enumerate(images, 1):
        nonwhite, dark, size = nonwhite_ratio(image)
        # A truly blank/broken page is normally near zero. This leaves ample
        # room for intentionally sparse pages while catching empty output.
        if nonwhite < 0.0015:
            fail("blank_or_near_blank_page", {"page": i, "nonwhite_ratio": nonwhite})
        page_stats.append({"page": i, "nonwhite_ratio": round(nonwhite, 5), "dark_ratio": round(dark, 5), "pixels": size})

    # PDF text should not contain Unicode replacement glyphs or obvious browser error pages.
    for bad in ["�", "aw, snap", "page crashed", "error code: out of memory"]:
        if norm(bad) in text_n:
            fail("render_corruption_marker", bad)

    print(json.dumps({
        "ok": True,
        "pdf": str(pdf),
        "bytes": pdf.stat().st_size,
        "pages": pages,
        "tier": args.tier,
        "report_id": args.report_id,
        "page_size_pts": [width, height],
        "text_chars": len(text_n),
        "previews": [str(p) for p in images],
        "page_stats": page_stats,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
