"""Font forensics: inconsistent fonts/sizes on rate-related text."""

from __future__ import annotations

import collections
import re
from pathlib import Path

import pymupdf

from .money import MONEY_RE, looks_like_money_token


def font_family(name: str) -> str:
    """Normalize Helvetica-Bold / TimesNewRomanPS-BoldMT to a family name."""
    if not name:
        return ""
    base = name.split("+")[-1]  # strip subset prefix ABCDEF+Helvetica
    for suffix in (
        "-BoldItalic", "-BoldOblique", "-Italic", "-Oblique", "-Bold",
        "BoldItalic", "BoldOblique", "Italic", "Oblique", "Bold",
        "PS-BoldMT", "PS-ItalicMT", "PS-BoldItalicMT", "PSMT",
        "-Roman",
    ):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.lower()


def _spans_from_page(page) -> list[dict]:
    data = page.get_text("dict")
    spans = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if not text:
                    continue
                spans.append(
                    {
                        "text": text,
                        "font": span.get("font") or "",
                        "size": round(float(span.get("size") or 0), 2),
                        "color": span.get("color"),
                        "bbox": list(span.get("bbox") or []),
                        "flags": span.get("flags"),
                    }
                )
    return spans


def analyze_fonts(pdf_path: str | Path, fonts_added_later: list[str] | None = None) -> dict:
    path = Path(pdf_path)
    doc = pymupdf.open(path)
    try:
        all_spans = []
        page_fonts = []
        for i, page in enumerate(doc):
            spans = _spans_from_page(page)
            for s in spans:
                s["page"] = i + 1
            all_spans.extend(spans)
            fonts = []
            for f in page.get_fonts():
                fonts.append(
                    {
                        "name": f[3],
                        "base": f[4],
                        "type": f[2],
                        "encoding": f[5],
                        "embedded": f[6] if len(f) > 6 else None,
                    }
                )
            page_fonts.append({"page": i + 1, "fonts": fonts})
    finally:
        doc.close()

    # Dominant *family* / size for body text (ignore very large headers)
    body = [s for s in all_spans if 7 <= s["size"] <= 16]
    pool = body or all_spans
    family_counts = collections.Counter(font_family(s["font"]) for s in pool if s["font"])
    size_counts = collections.Counter(s["size"] for s in pool)
    dominant_family = family_counts.most_common(1)[0][0] if family_counts else None
    dominant_font = next((s["font"] for s in pool if font_family(s["font"]) == dominant_family), None)
    dominant_size = size_counts.most_common(1)[0][0] if size_counts else None

    suspects = []
    added = set(fonts_added_later or [])
    added_families = {font_family(a) for a in added}
    for s in all_spans:
        text = s["text"]
        is_money = bool(MONEY_RE.search(text) or looks_like_money_token(text))
        if not is_money:
            # Bold headers like "TOTAL RATE" in Helvetica-Bold are normal.
            continue
        reasons = []
        fam = font_family(s["font"])
        if dominant_family and fam and fam != dominant_family:
            reasons.append(
                f"font “{s['font']}” is a different family than the usual “{dominant_font}”"
            )
        if dominant_size and s["size"] and s["size"] < dominant_size - 1.5:
            reasons.append(
                f"size {s['size']} pt is smaller than the usual {dominant_size} pt body text"
            )
        if added and (
            any(a in (s["font"] or "") or (s["font"] or "") in a for a in added)
            or (fam and fam in added_families)
        ):
            reasons.append("this font was added in a later revision of the file")
        if reasons:
            suspects.append(
                {
                    "page": s["page"],
                    "text": text,
                    "font": s["font"],
                    "size": s["size"],
                    "reasons": reasons,
                    "is_money": is_money,
                }
            )

    findings = []
    if suspects:
        examples = "; ".join(
            f"“{s['text']}” ({', '.join(s['reasons'])})" for s in suspects[:5]
        )
        findings.append(
            {
                "id": "inconsistent_fonts",
                "severity": "high" if any(s["is_money"] for s in suspects) else "medium",
                "title": "Rate-related text uses a font or size that does not match the rest of the page",
                "detail": (
                    "Edited rate fields are often typed in a different font than the original form. "
                    + examples
                ),
            }
        )

    return {
        "dominant_font": dominant_font,
        "dominant_size": dominant_size,
        "page_fonts": page_fonts,
        "suspect_spans": suspects,
        "span_count": len(all_spans),
        "findings": findings,
    }
