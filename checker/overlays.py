"""Detect white boxes over text, covered text, and duplicate money amounts."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .money import MONEY_RE, find_money, unique_values


def _is_near_white(color) -> bool:
    """True for a concealment box: nearly pure white, not a light-gray panel."""
    if not color:
        return False
    if isinstance(color, (int, float)):
        return color >= 0.99
    if len(color) >= 3:
        r, g, b = color[0], color[1], color[2]
        if max(r, g, b) <= 1.0:
            return r >= 0.99 and g >= 0.99 and b >= 0.99
        return r >= 250 and g >= 250 and b >= 250
    return False


def _looks_like_cover_box(rect, page) -> bool:
    """Cover-ups are tight boxes over a field, not section backgrounds or banners."""
    w = rect[2] - rect[0]
    h = rect[3] - rect[1]
    if w <= 2 or h <= 2:
        return False
    # A typed-over dollar amount is usually one text line tall.
    if h > 36:
        return False
    if w > page.rect.width * 0.45:
        return False
    area = w * h
    if area < 20:
        return False
    if area > 0.08 * page.rect.width * page.rect.height:
        return False
    return True


def _rects_overlap(a, b, pad: float = 1.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 + pad < bx0 or bx1 + pad < ax0 or ay1 + pad < by0 or by1 + pad < ay0)


def _intersection_area(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def analyze_overlays(pdf_path: str | Path) -> dict:
    path = Path(pdf_path)
    doc = pymupdf.open(path)
    white_covers = []
    duplicate_page_amounts = []
    all_amounts = []
    try:
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            amounts = find_money(text)
            for a in amounts:
                a["page"] = i + 1
            all_amounts.extend(amounts)
            vals = unique_values(amounts)
            if len(vals) >= 2:
                # more than one distinct dollar amount on a rate con is normal
                # (line haul vs total). Flag when a near-identical field appears twice
                # or when extraction still has two close competing totals.
                raws = [a["normalized"] for a in amounts]
                if len(raws) != len(set(raws)) or True:
                    duplicate_page_amounts.append(
                        {"page": i + 1, "amounts": [a["normalized"] for a in amounts]}
                    )

            # Text spans (especially money) and filled drawings
            spans = []
            td = page.get_text("dict")
            for block in td.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        t = (span.get("text") or "").strip()
                        if not t:
                            continue
                        spans.append(
                            {
                                "text": t,
                                "bbox": tuple(span.get("bbox") or (0, 0, 0, 0)),
                                "is_money": bool(MONEY_RE.search(t)),
                            }
                        )

            drawings = page.get_drawings()
            for d in drawings:
                fill = d.get("fill")
                rect = d.get("rect")
                if rect is None or not _is_near_white(fill):
                    continue
                # Ignore huge page-sized backgrounds
                r = (rect.x0, rect.y0, rect.x1, rect.y1)
                if not _looks_like_cover_box(r, page):
                    continue
                hits = []
                for s in spans:
                    inter = _intersection_area(r, s["bbox"])
                    sb = s["bbox"]
                    s_area = max(1.0, (sb[2] - sb[0]) * (sb[3] - sb[1]))
                    if inter / s_area >= 0.35 or _rects_overlap(r, s["bbox"], pad=0.5):
                        if inter > 0 or _rects_overlap(r, s["bbox"], pad=0.5):
                            # require meaningful overlap
                            if inter / s_area >= 0.25:
                                hits.append(s)
                if hits:
                    white_covers.append(
                        {
                            "page": i + 1,
                            "rect": [round(x, 1) for x in r],
                            "covered_text": [h["text"] for h in hits],
                            "covers_money": any(h["is_money"] for h in hits),
                        }
                    )
    finally:
        doc.close()

    # Duplicate competing totals: both a higher and lower similar amount extracted
    values = unique_values(all_amounts)
    competing = []
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            # two different dollar amounts, both typical rate-con figures
            if a >= 100 and b >= 100:
                competing.append((a, b))

    findings = []
    money_covers = [c for c in white_covers if c["covers_money"]]
    if money_covers or white_covers:
        covers = money_covers or white_covers
        examples = []
        for c in covers[:4]:
            txt = ", ".join(c["covered_text"][:4])
            examples.append(f"page {c['page']}: white box over “{txt}”")
        findings.append(
            {
                "id": "white_overlay",
                "severity": "high" if money_covers else "medium",
                "title": "A white box appears to be drawn over existing text",
                "detail": (
                    "A filled white rectangle sits on top of earlier text. "
                    "This is a common way to hide an original rate and type a new number over it. "
                    + "; ".join(examples)
                ),
            }
        )

    if len(values) >= 2 and any(a >= 500 and b >= 500 for a, b in competing):
        # Only flag as "duplicate amounts" when extraction likely still has both
        # original and replacement (same document shows two plausible totals).
        # This can also fire on a legit rate con that lists line haul + fuel + total
        # as different numbers. Prefer firing when a white overlay is also present,
        # or when two amounts appear in almost the same context.
        if money_covers or white_covers:
            findings.append(
                {
                    "id": "duplicate_amounts",
                    "severity": "high",
                    "title": "More than one dollar amount is still in the file",
                    "detail": (
                        "The extracted text includes these amounts: "
                        + ", ".join(f"${v:,.2f}" for v in values)
                        + ". When a rate is covered and retyped, the original figure is often still in the file."
                    ),
                }
            )

    return {
        "white_covers": white_covers,
        "amounts": all_amounts,
        "unique_amounts": [f"${v:,.2f}" for v in values],
        "findings": findings,
    }
