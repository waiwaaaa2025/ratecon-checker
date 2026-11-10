"""Detect incremental PDF updates and recover earlier revisions."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pymupdf

from .datesutil import format_dt, parse_pdf_date
from .money import find_money, unusual_rate_field_values, unique_values
from .ocr import OCR_AVAILABLE, ocr_page
from .raster import page_looks_flattened

EOF_RE = re.compile(rb"%%EOF")


def find_eof_offsets(data: bytes) -> list[int]:
    """Return byte offsets at the end of each %%EOF marker."""
    return [m.end() for m in EOF_RE.finditer(data)]


def count_xref_sections(data: bytes) -> int:
    # 'xref' as a line of its own, plus xref-style trailer in newer xref streams
    classic = len(re.findall(rb"(?m)^xref\r?\n", data))
    # Cross-reference streams used by PDF 1.5+: /Type /XRef
    streams = len(re.findall(rb"/Type\s*/XRef\b", data))
    return max(classic + streams, 1 if data else 0)


def _revision_needs_ocr(text: str, page) -> bool:
    if page_looks_flattened(page, text):
        return True
    if len((text or "").strip()) < 40:
        return True
    # Selectable text exists but has no money amounts — the visible rate may
    # only be in a raster layer.
    if not find_money(text or ""):
        return bool(page.get_images())
    return False


def _extract_revision(data: bytes, end: int) -> dict | None:
    chunk = data[:end]
    # Some writers put \n or \r\n after %%EOF; that's already included if end is m.end()
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    try:
        os.write(fd, chunk)
        os.close(fd)
        fd = None
        doc = pymupdf.open(tmp)
        try:
            texts = []
            ocr_texts = []
            fonts = set()
            flattened_pages = []
            used_ocr = False
            for page in doc:
                text = page.get_text() or ""
                texts.append(text)
                for f in page.get_fonts():
                    # tuple: (xref, ext, type, name, basefont, encoding, embedded)
                    name = f[3] or f[4] or ""
                    if name:
                        fonts.add(str(name))
                if page_looks_flattened(page, text):
                    flattened_pages.append(page.number + 1)
                ocr = ""
                if OCR_AVAILABLE and _revision_needs_ocr(text, page):
                    try:
                        ocr = ocr_page(page, dpi=200) or ""
                        if ocr.strip():
                            used_ocr = True
                    except Exception:
                        ocr = ""
                ocr_texts.append(ocr)
            text = "\n".join(texts)
            ocr_text = "\n".join(t for t in ocr_texts if t)
            combined = text
            if ocr_text:
                combined = (text + "\n" + ocr_text).strip()
            meta = doc.metadata or {}
            producer = (meta.get("producer") or "").replace("\x00", "").strip()
            creator = (meta.get("creator") or "").replace("\x00", "").strip()
            return {
                "bytes": end,
                "pages": doc.page_count,
                "text": text,
                "ocr_text": ocr_text,
                "combined_text": combined,
                "used_ocr": used_ocr,
                "fonts": sorted(fonts),
                "amounts": find_money(combined),
                "unusual_fields": unusual_rate_field_values(combined),
                "flattened_pages": flattened_pages,
                "producer": producer or None,
                "creator": creator or None,
                "creation_date_raw": meta.get("creationDate") or None,
                "mod_date_raw": meta.get("modDate") or None,
                "creation_date": format_dt(parse_pdf_date(meta.get("creationDate"))),
                "mod_date": format_dt(parse_pdf_date(meta.get("modDate"))),
            }
        finally:
            doc.close()
    except Exception as exc:
        return {"error": str(exc), "bytes": end}
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _norm_software(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", value.replace("\x00", "")).strip() or None


def _rate_values(amts: list[dict], prefer_keyword: bool = True) -> list[float]:
    """Prefer amounts next to LINE HAUL / TOTAL / RATE labels when present."""
    keyed = [a for a in amts if a["value"] >= 100 and a.get("near_rate_keyword")]
    pool = keyed if (prefer_keyword and keyed) else [a for a in amts if a["value"] >= 100]
    return sorted({round(a["value"], 2) for a in pool})


def _diff_amounts(earlier: list[dict], later: list[dict]) -> list[dict]:
    # Prefer amounts next to LINE HAUL / TOTAL labels when those actually change.
    # Fall back to every $100+ amount so a typed-over total still shows up even
    # if the new number is not sitting next to the word "rate".
    kw_earlier = set(_rate_values(earlier, prefer_keyword=True))
    kw_later = set(_rate_values(later, prefer_keyword=True))
    all_earlier = set(_rate_values(earlier, prefer_keyword=False))
    all_later = set(_rate_values(later, prefer_keyword=False))
    if (kw_earlier or kw_later) and kw_earlier != kw_later:
        earlier_vals, later_vals = kw_earlier, kw_later
    else:
        earlier_vals, later_vals = all_earlier, all_later
    added = sorted(later_vals - earlier_vals)
    removed = sorted(earlier_vals - later_vals)
    changes = []
    leftover = list(added)
    for old in removed:
        if leftover:
            new_v = min(leftover, key=lambda x: abs(x - old))
            leftover.remove(new_v)
            changes.append({"from": f"${old:,.2f}", "to": [f"${new_v:,.2f}"]})
        else:
            changes.append({"from": f"${old:,.2f}", "to": ["(removed or no longer extractable)"]})
    if leftover and earlier_vals:
        # Original amount often remains under a white box, so it is not "removed"
        orig = ", ".join(f"${v:,.2f}" for v in sorted(earlier_vals))
        changes.append(
            {
                "from": orig,
                "to": [f"${a:,.2f}" for a in leftover],
                "note": "The earlier amount is still extractable in the final file; a new amount was added.",
            }
        )
    elif leftover:
        changes.append(
            {
                "from": "(not recoverable from earlier revisions in this file)",
                "to": [f"${a:,.2f}" for a in leftover],
                "note": "The earlier leftover copy does not contain the original line-haul or total as selectable text.",
            }
        )
    return changes


def analyze_incremental(pdf_path: str | Path) -> dict:
    path = Path(pdf_path)
    data = path.read_bytes()
    eof_offsets = find_eof_offsets(data)
    xref_count = count_xref_sections(data)
    startxref_count = len(re.findall(rb"startxref", data))
    extra_saves = max(0, len(eof_offsets) - 1)

    result = {
        "eof_count": len(eof_offsets),
        "xref_count": xref_count,
        "startxref_count": startxref_count,
        "extra_saves": extra_saves,
        "has_incremental_updates": len(eof_offsets) > 1 or startxref_count > 1,
        "revisions": [],
        "recovered_earlier_amounts": [],
        "final_amounts": [],
        "amount_changes": [],
        "fonts_added_in_later_revisions": [],
        "software_by_revision": [],
        "software_changed": False,
        "ocr_used": False,
        "findings": [],
    }

    revisions = []
    for i, end in enumerate(eof_offsets):
        rev = _extract_revision(data, end)
        if rev is None:
            continue
        rev["index"] = i + 1
        rev["is_final"] = i == len(eof_offsets) - 1
        revisions.append(rev)
    result["revisions"] = [
        {
            "index": r.get("index"),
            "is_final": r.get("is_final"),
            "bytes": r.get("bytes"),
            "pages": r.get("pages"),
            "error": r.get("error"),
            "fonts": r.get("fonts", []),
            "amounts": r.get("amounts", []),
            "unusual_fields": r.get("unusual_fields", []),
            "flattened_pages": r.get("flattened_pages", []),
            "producer": r.get("producer"),
            "creator": r.get("creator"),
            "creation_date": r.get("creation_date"),
            "mod_date": r.get("mod_date"),
            "used_ocr": r.get("used_ocr"),
            "text_preview": (r.get("combined_text") or r.get("text") or "")[:2000],
        }
        for r in revisions
    ]

    successful = [r for r in revisions if "text" in r]
    if successful:
        first = successful[0]
        last = successful[-1]
        result["final_amounts"] = last.get("amounts") or []
        result["ocr_used"] = any(r.get("used_ocr") for r in successful)
        software_rows = []
        for r in successful:
            software_rows.append(
                {
                    "index": r.get("index"),
                    "producer": r.get("producer"),
                    "creator": r.get("creator"),
                    "mod_date": r.get("mod_date"),
                }
            )
        result["software_by_revision"] = software_rows
        producers = [_norm_software(r.get("producer")) for r in successful]
        producers = [p for p in producers if p]
        if len(set(producers)) > 1:
            result["software_changed"] = True
            result["software_change"] = {
                "from": producers[0],
                "to": producers[-1],
            }

        if len(successful) > 1:
            result["recovered_earlier_amounts"] = first.get("amounts") or []
            result["amount_changes"] = _diff_amounts(
                first.get("amounts") or [], last.get("amounts") or []
            )
            earlier_fonts = set(first.get("fonts") or [])
            later_fonts = set(last.get("fonts") or [])
            added_fonts = sorted(later_fonts - earlier_fonts)
            result["fonts_added_in_later_revisions"] = added_fonts

    findings = []
    if result["has_incremental_updates"]:
        detail = (
            f"This PDF has {result['eof_count']} end-of-file markers "
            f"and {result['startxref_count']} cross-reference pointers"
        )
        if extra_saves:
            detail += f", which usually means it was saved again {extra_saves} time" + (
                "s" if extra_saves != 1 else ""
            )
        detail += (
            ". Programs that edit an existing PDF often append a new section instead of rewriting the file. "
            "That leftover earlier copy can still be inside the file."
        )
        sev = "high" if result["amount_changes"] else "medium"
        findings.append(
            {
                "id": "incremental_update",
                "severity": sev,
                "title": "The PDF was saved with incremental updates (an earlier version may still be inside)",
                "detail": detail,
            }
        )
    if result.get("software_changed"):
        change = result.get("software_change") or {}
        findings.append(
            {
                "id": "software_change",
                "severity": "high" if extra_saves >= 2 else "medium",
                "title": "A different program wrote a later save of this PDF",
                "detail": (
                    f"An earlier revision lists Producer “{change.get('from')}”, "
                    f"and a later revision lists “{change.get('to')}”. "
                    "A change of software between saves is a strong sign the file was opened and saved in an editor "
                    "after it was originally issued. This is a sign of editing, not proof of fraud."
                ),
            }
        )
    elif result.get("software_by_revision"):
        parts = []
        for row in result["software_by_revision"]:
            who = row.get("producer") or row.get("creator") or "unknown software"
            when = row.get("mod_date") or ""
            parts.append(f"revision {row['index']}: {who}" + (f" ({when})" if when else ""))
        findings.append(
            {
                "id": "revision_software",
                "severity": "info",
                "title": "Software that wrote each revision",
                "detail": "; ".join(parts) + ".",
            }
        )
    if result["amount_changes"]:
        parts = []
        for ch in result["amount_changes"]:
            to = ", ".join(ch["to"]) if isinstance(ch["to"], list) else ch["to"]
            piece = f"{ch['from']} → {to}"
            if ch.get("note"):
                piece += f" ({ch['note']})"
            parts.append(piece)
        ocr_note = ""
        if result.get("ocr_used"):
            ocr_note = (
                " Some figures were read from a flattened page image with OCR, "
                "because the final page no longer has selectable text."
            )
        findings.append(
            {
                "id": "recovered_rate_change",
                "severity": "high",
                "title": "An earlier revision in the file shows different money amounts",
                "detail": (
                    "Comparing earlier and later copies still stored in this PDF, the money amounts changed: "
                    + "; ".join(parts)
                    + "."
                    + ocr_note
                    + " This is a strong sign the visible rate was changed after the original file was created. "
                    "It is still a sign of editing, not by itself proof of fraud."
                ),
            }
        )
    else:
        # If later OCR found a rate but earlier revisions had no recoverable original
        # amount (the first page stream was dropped), say so clearly.
        last_amts = result.get("final_amounts") or []
        if last_amts and extra_saves and not (result.get("recovered_earlier_amounts")):
            shown = ", ".join(sorted({a["normalized"] for a in last_amts if a["value"] >= 100}))
            findings.append(
                {
                    "id": "ocr_amounts_only_in_final",
                    "severity": "medium",
                    "title": "Money amounts were read from the final page image",
                    "detail": (
                        "The final page is an image (or has almost no selectable text). "
                        f"OCR read these amounts: {shown}. "
                        "An earlier copy of the original line-haul or total could not be recovered from leftover text in this file, "
                        "so this tool cannot show the previous figure from the PDF alone. "
                        "Comparing with the broker's original file is the strongest check."
                    ),
                }
            )
    unusual = []
    for r in successful:
        if r.get("is_final"):
            unusual = r.get("unusual_fields") or []
    if unusual:
        bits = ", ".join(f"{u['label']} reads as “{u['value']}”" for u in unusual[:4])
        findings.append(
            {
                "id": "unusual_rate_field",
                "severity": "high",
                "title": "A rate field does not look like a normal dollar amount",
                "detail": (
                    bits
                    + ". A line-haul or total that reads as letters or placeholder text is a sign the field was typed over. "
                    "This is a sign of editing, not proof of fraud."
                ),
            }
        )
    if result["fonts_added_in_later_revisions"]:
        findings.append(
            {
                "id": "fonts_added_later",
                "severity": "medium",
                "title": "New fonts were added in a later revision",
                "detail": (
                    "Fonts that do not appear in the earlier copy: "
                    + ", ".join(result["fonts_added_in_later_revisions"])
                    + ". New fonts are often added when someone types over an existing amount."
                ),
            }
        )
    result["findings"] = findings
    return result
