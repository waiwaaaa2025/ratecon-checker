"""Detect pages that have been flattened into a full-page image."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .ocr import OCR_AVAILABLE, ocr_page

# An image covering this much of the page is treated as a full-page flatten.
COVER_RATIO = 0.80


def _page_area(page) -> float:
    r = page.rect
    return max(1.0, abs(r.width * r.height))


def full_page_images(page, cover_ratio: float = COVER_RATIO) -> list[dict]:
    """Return images whose placed box covers most of the page."""
    area = _page_area(page)
    hits = []
    try:
        infos = page.get_image_info(xrefs=True)
    except Exception:
        infos = []
    for info in infos:
        bbox = info.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
        w, h = abs(x1 - x0), abs(y1 - y0)
        ratio = (w * h) / area
        if ratio < cover_ratio:
            continue
        hits.append(
            {
                "xref": info.get("xref"),
                "width": info.get("width"),
                "height": info.get("height"),
                "bpc": info.get("bpc") or info.get("cs-bpc"),
                "colorspace": info.get("cs-name") or info.get("colorspace"),
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "cover_ratio": round(ratio, 3),
            }
        )
    return hits


def page_looks_flattened(page, text: str | None = None, cover_ratio: float = COVER_RATIO) -> bool:
    if full_page_images(page, cover_ratio=cover_ratio):
        return True
    # Contents that are essentially "scale to page and paint one image"
    try:
        contents = page.read_contents() or b""
    except Exception:
        contents = b""
    if b" Do" in contents and contents.count(b" Do") <= 2:
        # very short content stream + almost no extractable text
        body = text if text is not None else (page.get_text() or "")
        if len(contents) < 400 and len((body or "").strip()) < 40:
            return True
    return False


def analyze_flattening(pdf_path: str | Path, ocr_texts: dict[int, str] | None = None) -> dict:
    """Flag pages converted to a full-page raster image."""
    path = Path(pdf_path)
    doc = pymupdf.open(path)
    pages = []
    findings = []
    try:
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            images = full_page_images(page)
            flattened = bool(images) or page_looks_flattened(page, text)
            entry = {
                "page": i + 1,
                "flattened": flattened,
                "extractable_text_chars": len(text.strip()),
                "full_page_images": images,
            }
            if flattened:
                ocr = (ocr_texts or {}).get(i) or ""
                if not ocr and OCR_AVAILABLE:
                    try:
                        ocr = ocr_page(page, dpi=200) or ""
                    except Exception:
                        ocr = ""
                entry["ocr_preview"] = (ocr or "")[:1500]
                pages.append(entry)
                img_bits = []
                for im in images:
                    w, h = im.get("width"), im.get("height")
                    if w and h:
                        img_bits.append(f"{w}×{h}")
                size_txt = ", ".join(img_bits) if img_bits else "a full-page image"
                detail = (
                    f"Page {i + 1} was converted to {size_txt} that covers the whole page. "
                    "Flattening a page into an image is a common way to hide edits, "
                    "because the original text and amounts are no longer in the file as selectable text."
                )
                if not text.strip() and ocr:
                    from .money import find_money
                    amts = find_money(ocr)
                    notable = [a["normalized"] for a in amts if a["value"] >= 100 and a.get("near_rate_keyword")]
                    detail += " The visible wording was read from the image with OCR."
                    if notable:
                        detail += " OCR read these rate amounts: " + ", ".join(dict.fromkeys(notable)) + "."
                elif not text.strip():
                    detail += " Almost no selectable text remains on this page."
                findings.append(
                    {
                        "id": "page_flattened",
                        "severity": "high",
                        "title": "A page was flattened into an image, a common way to hide edits",
                        "detail": detail
                        + " This is a sign of editing, not proof of fraud.",
                    }
                )
            else:
                pages.append(entry)
    finally:
        doc.close()

    return {"pages": pages, "findings": findings}
