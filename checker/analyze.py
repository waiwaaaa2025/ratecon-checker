"""Run all rate-confirmation checks and return a single report dict."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from .compare import compare_pdfs
from .datesutil import humanize_delta
from .email_headers import analyze_email
from .fonts import analyze_fonts
from .incremental import analyze_incremental
from .metadata import analyze_metadata
from .money import find_money
from .ocr import OCR_AVAILABLE, ocr_page, ocr_status
from .overlays import analyze_overlays
from .raster import analyze_flattening, page_looks_flattened
from .scoring import score_findings
from .signatures import analyze_signatures


def _extract_preview(pdf_path: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    try:
        texts = []
        ocr_used = False
        ocr_by_page = {}
        for i, page in enumerate(doc):
            text = page.get_text() or ""
            if OCR_AVAILABLE and (page_looks_flattened(page, text) or not (text or "").strip()):
                try:
                    ocr = ocr_page(page, dpi=200) or ""
                except Exception:
                    ocr = ""
                if ocr.strip():
                    ocr_used = True
                    ocr_by_page[i] = ocr
                    text = (text + "\n" + ocr).strip()
            texts.append(text)
        text = "\n".join(texts)
        return {
            "pages": doc.page_count,
            "text_preview": text[:3000],
            "amounts": find_money(text),
            "ocr_used": ocr_used,
            "ocr_pages": sorted(ocr_by_page.keys()),
        }
    finally:
        doc.close()


def _stacked_finding(report: dict) -> dict | None:
    """Combine several medium-strength clues into one high finding when they stack."""
    inc = report.get("incremental") or {}
    meta = report.get("metadata") or {}
    raster = report.get("raster") or {}
    ids = {f.get("id") for f in (report.get("findings") or [])}
    extra = int(inc.get("extra_saves") or max(0, int(inc.get("eof_count") or 1) - 1))
    gap = int(meta.get("date_delta_seconds") or 0)
    software_changed = bool(inc.get("software_changed")) or "software_change" in ids
    flattened = any((p or {}).get("flattened") for p in (raster.get("pages") or [])) or "page_flattened" in ids
    long_gap = gap > 24 * 3600
    many_saves = extra >= 2
    if not (many_saves and long_gap and (software_changed or flattened)):
        return None
    parts = []
    if many_saves:
        parts.append(f"it was saved incrementally at least {extra} extra times")
    if long_gap:
        parts.append(
            f"the modified date is {humanize_delta(gap) or 'much later'} after the creation date"
        )
    if software_changed:
        change = inc.get("software_change") or {}
        if change.get("from") and change.get("to"):
            parts.append(f"the writing software changed from {change['from']} to {change['to']}")
        else:
            parts.append("a later save was written by different software")
    if flattened:
        parts.append("at least one page was flattened into a full-page image")
    return {
        "id": "stacked_edit_evidence",
        "severity": "high",
        "title": "Several independent signs of later editing appear together",
        "detail": (
            "Taken together, "
            + "; ".join(parts)
            + ". Any one of these can have an innocent explanation, but seeing them together is a strong sign the file was changed after it was issued. "
            "These are still signs of editing, not proof of fraud."
        ),
    }


def analyze_ratecon(
    pdf_path: str | Path,
    original_path: str | Path | None = None,
    email_path: str | Path | None = None,
    lookup_ip: bool = True,
) -> dict:
    pdf_path = Path(pdf_path)
    report = {
        "file": pdf_path.name,
        "preview": {},
        "metadata": {},
        "incremental": {},
        "fonts": {},
        "overlays": {},
        "raster": {},
        "signatures": {},
        "compare": None,
        "email": None,
        "ocr": ocr_status(),
        "findings": [],
        "score": {},
    }

    try:
        report["preview"] = _extract_preview(pdf_path)
    except Exception as exc:
        report["error"] = f"Could not open this PDF: {exc}"
        report["score"] = score_findings([])
        return report

    report["metadata"] = analyze_metadata(pdf_path)
    report["incremental"] = analyze_incremental(pdf_path)
    added_fonts = report["incremental"].get("fonts_added_in_later_revisions") or []
    report["fonts"] = analyze_fonts(pdf_path, fonts_added_later=added_fonts)
    report["overlays"] = analyze_overlays(pdf_path)
    # Reuse OCR text already gathered in incremental/preview when describing flattenings
    ocr_texts = {}
    report["raster"] = analyze_flattening(pdf_path, ocr_texts=ocr_texts)
    report["signatures"] = analyze_signatures(pdf_path, incremental=report["incremental"])

    if original_path:
        report["compare"] = compare_pdfs(original_path, pdf_path)
    if email_path:
        report["email"] = analyze_email(email_path, lookup=lookup_ip)

    findings = []
    for section in (
        report["metadata"],
        report["incremental"],
        report["fonts"],
        report["overlays"],
        report["raster"],
        report["signatures"],
        report.get("compare") or {},
        report.get("email") or {},
    ):
        findings.extend(section.get("findings") or [])
    report["findings"] = findings
    stacked = _stacked_finding(report)
    if stacked:
        report["findings"].append(stacked)
        findings = report["findings"]
    report["score"] = score_findings(findings)
    return report
