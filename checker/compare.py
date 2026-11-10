"""Compare a broker original PDF with the copy a driver received."""

from __future__ import annotations

import difflib
from pathlib import Path

import pymupdf

from .money import find_money, unique_values
from .ocr import OCR_AVAILABLE, ocr_page
from .raster import page_looks_flattened


def _page_texts(path: Path) -> tuple[str, bool]:
    """Return extractable text, with OCR added for flattened/image pages."""
    doc = pymupdf.open(path)
    used_ocr = False
    try:
        parts = []
        for page in doc:
            text = page.get_text() or ""
            if OCR_AVAILABLE and (page_looks_flattened(page, text) or (not find_money(text) and len(text.strip()) < 80)):
                try:
                    ocr = ocr_page(page, dpi=200) or ""
                except Exception:
                    ocr = ""
                if ocr.strip():
                    used_ocr = True
                    text = (text + "\n" + ocr).strip()
            parts.append(text)
        return "\n".join(parts), used_ocr
    finally:
        doc.close()


def compare_pdfs(original_path: str | Path, received_path: str | Path) -> dict:
    orig = Path(original_path)
    recv = Path(received_path)
    result = {
        "original_name": orig.name,
        "received_name": recv.name,
        "original_amounts": [],
        "received_amounts": [],
        "amount_changes": [],
        "text_changed": False,
        "diff_lines": [],
        "findings": [],
    }
    try:
        orig_text, orig_ocr = _page_texts(orig)
        recv_text, recv_ocr = _page_texts(recv)
        result["ocr_used"] = bool(orig_ocr or recv_ocr)
    except Exception as exc:
        result["error"] = f"Could not compare PDFs: {exc}"
        return result

    orig_amts = find_money(orig_text)
    recv_amts = find_money(recv_text)
    result["original_amounts"] = orig_amts
    result["received_amounts"] = recv_amts

    def rate_vals(amts):
        return sorted({round(a["value"], 2) for a in amts if a["value"] >= 100})

    orig_vals = set(rate_vals(orig_amts))
    recv_vals = set(rate_vals(recv_amts))
    removed = sorted(orig_vals - recv_vals)
    added = sorted(recv_vals - orig_vals)
    changes = []
    unused = list(added)
    for old in removed:
        if unused:
            new = min(unused, key=lambda x: abs(x - old))
            unused.remove(new)
            changes.append({"from": f"${old:,.2f}", "to": f"${new:,.2f}"})
        else:
            changes.append({"from": f"${old:,.2f}", "to": "(not in received copy)"})
    if unused and orig_vals:
        # Overlay edits often leave the original amount in the extractable text
        orig = ", ".join(f"${v:,.2f}" for v in sorted(orig_vals))
        changes.append(
            {
                "from": orig,
                "to": ", ".join(f"${v:,.2f}" for v in unused),
                "note": "The received copy still contains the original amount and also a new amount.",
            }
        )
    else:
        for new in unused:
            changes.append({"from": "(not in original)", "to": f"${new:,.2f}"})
    result["amount_changes"] = changes

    orig_lines = [ln.strip() for ln in orig_text.splitlines() if ln.strip()]
    recv_lines = [ln.strip() for ln in recv_text.splitlines() if ln.strip()]
    diff = list(
        difflib.unified_diff(
            orig_lines, recv_lines, fromfile="broker original", tofile="received copy", lineterm=""
        )
    )
    result["diff_lines"] = diff[:200]
    result["text_changed"] = bool(changes) or any(
        ln.startswith("+") or ln.startswith("-") for ln in diff if not ln.startswith("+++") and not ln.startswith("---") and not ln.startswith("@@")
    )

    findings = []
    if changes:
        pretty_parts = []
        for c in changes:
            bit = f"{c['from']} → {c['to']}"
            if c.get("note"):
                bit += f" ({c['note']})"
            pretty_parts.append(bit)
        pretty = "; ".join(pretty_parts)
        findings.append(
            {
                "id": "compare_amount_change",
                "severity": "high",
                "title": "The received PDF and the broker original show different money amounts",
                "detail": (
                    "Comparing the two files, the amounts do not match: "
                    + pretty
                    + ". This is the strongest check this tool can run, because it uses the broker's original file as a reference. "
                    + ("Some amounts in the received copy were read from a flattened page image with OCR. " if result.get("ocr_used") else "")
                    + "It is still a sign of editing, not by itself proof of fraud."
                ),
            }
        )
    elif result["text_changed"]:
        findings.append(
            {
                "id": "compare_text_change",
                "severity": "medium",
                "title": "The wording of the received PDF differs from the broker original",
                "detail": "The money amounts appear the same, but other text does not match exactly.",
            }
        )
    else:
        findings.append(
            {
                "id": "compare_match",
                "severity": "info",
                "title": "The received PDF matches the broker original on extracted text and amounts",
                "detail": "No money-amount or wording differences were found in this comparison.",
            }
        )
    result["findings"] = findings
    return result
