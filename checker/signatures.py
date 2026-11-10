"""Check for digital signatures and possible changes after signing."""

from __future__ import annotations

from pathlib import Path

import pymupdf


def analyze_signatures(pdf_path: str | Path, incremental: dict | None = None) -> dict:
    path = Path(pdf_path)
    result = {
        "present": False,
        "sig_flags": 0,
        "fields": [],
        "findings": [],
    }
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        result["error"] = str(exc)
        return result
    try:
        flags = 0
        try:
            raw_flags = doc.get_sigflags()
            flags = int(raw_flags) if raw_flags is not None else 0
        except Exception:
            flags = 0
        # MuPDF may return -1 when the file has no signature dictionary.
        if flags < 0:
            flags = 0
        result["sig_flags"] = flags
        result["present"] = bool(flags & 1)

        for i, page in enumerate(doc):
            widgets = list(page.widgets() or [])
            for w in widgets:
                try:
                    ftype = getattr(w, "field_type", None)
                    is_sig = ftype == getattr(pymupdf, "PDF_WIDGET_TYPE_SIGNATURE", 6) or (
                        getattr(w, "field_type_string", "") or ""
                    ).lower() == "signature"
                    if is_sig:
                        result["present"] = True
                        result["fields"].append(
                            {
                                "page": i + 1,
                                "name": getattr(w, "field_name", None),
                                "value_present": bool(getattr(w, "field_value", None)),
                            }
                        )
                except Exception:
                    continue
    finally:
        doc.close()

    findings = []
    if not result["present"]:
        findings.append(
            {
                "id": "no_signature",
                "severity": "info",
                "title": "No digital signature was found",
                "detail": (
                    "This file is not digitally signed. A signature would make later changes easier to spot. "
                    "Most emailed rate confirmations are unsigned."
                ),
            }
        )
    else:
        findings.append(
            {
                "id": "signature_present",
                "severity": "info",
                "title": "A digital signature is present",
                "detail": "This PDF includes a signature field or signature flag. If the signature is invalid, the file may have been changed after it was signed.",
            }
        )
        if incremental and incremental.get("has_incremental_updates"):
            findings.append(
                {
                    "id": "modified_after_signing",
                    "severity": "high",
                    "title": "The file has incremental updates and also a signature",
                    "detail": (
                        "Updates appended after a signature can mean the document was changed after it was signed. "
                        "This checker reports that as a sign of editing; a cryptographer or the original signing service would need to confirm whether the signature is still valid."
                    ),
                }
            )
    result["findings"] = findings
    return result
