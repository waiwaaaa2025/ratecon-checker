"""Metadata and known-editor checks for a PDF."""

from __future__ import annotations

from pathlib import Path

import pikepdf
from pikepdf import Name

from .datesutil import format_dt, humanize_delta, parse_pdf_date

KNOWN_EDITORS = [
    ("adobe acrobat", "Adobe Acrobat"),
    ("acrobat distiller", "Adobe Acrobat Distiller"),
    ("acrobat pdfmaker", "Acrobat PDFMaker"),
    ("adobe illustrator", "Adobe Illustrator"),
    ("ilovepdf", "iLovePDF"),
    ("smallpdf", "Smallpdf"),
    ("sejda", "Sejda"),
    ("pdfescape", "PDFescape"),
    ("foxit", "Foxit"),
    ("pdf-xchange", "PDF-XChange"),
    ("pdfxchange", "PDF-XChange"),
    ("nitro", "Nitro PDF"),
    ("sodapdf", "Soda PDF"),
    ("soda pdf", "Soda PDF"),
    ("hipdf", "HiPDF"),
    ("pdf2go", "PDF2Go"),
    ("icutepdf", "CutePDF"),
    ("cutepdf", "CutePDF"),
    ("primopdf", "PrimoPDF"),
    ("bullzip", "Bullzip"),
    ("microsoft word", "Microsoft Word"),
    ("microsoft® word", "Microsoft Word"),
    ("print to pdf", "Print to PDF"),
    ("microsoft: print to pdf", "Microsoft Print to PDF"),
    ("microsoft print to pdf", "Microsoft Print to PDF"),
    ("skia/pdf", "Chrome / Skia (print or re-save)"),
    ("wkhtmltopdf", "wkhtmltopdf"),
    ("ghostscript", "Ghostscript"),
    ("gpl ghostscript", "Ghostscript"),
    ("qpdf", "qpdf / pikepdf"),
    ("pikepdf", "pikepdf"),
    ("pypdf", "pypdf"),
    ("pymupdf", "PyMuPDF"),
    ("macos quartz", "macOS Quartz (print to PDF)"),
    ("quartz pdfcontext", "macOS Quartz (print to PDF)"),
    ("preview.app", "macOS Preview"),
    ("itext", "iText"),
    ("openoffice", "OpenOffice / LibreOffice"),
    ("libreoffice", "LibreOffice"),
    ("wps office", "WPS Office"),
    ("pdf24", "PDF24"),
    ("icerbox", "Icerbox"),
    ("pdf filler", "pdfFiller"),
    ("pdffiller", "pdfFiller"),
    ("docusign", "DocuSign"),
    ("paperport", "PaperPort"),
    ("nuance", "Nuance"),
    ("omnipage", "OmniPage"),
    ("abbyy", "ABBYY"),
    ("scansnap", "ScanSnap"),
    ("kofax", "Kofax"),
    ("readiris", "Readiris"),
]

# Tools that many brokers / TMS systems use to *generate* a PDF. These should
# not, by themselves, be treated as a sign of later editing.
COMMON_GENERATORS = [
    ("gpl ghostscript", "Ghostscript"),
    ("ghostscript", "Ghostscript"),
]



def _clean(s: str | None) -> str | None:
    if not s:
        return None
    s = "".join(ch for ch in s if ch != chr(0)).strip()
    if s in ("", "None"):
        return None
    return s


def _as_text(value) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, pikepdf.String):
            return _clean(str(value))
        if isinstance(value, bytes):
            return _clean(value.decode("latin-1", errors="replace"))
    except Exception:
        pass
    return _clean(str(value))


def _match_list(text: str | None, table: list[tuple[str, str]]) -> list[str]:
    if not text:
        return []
    low = text.lower()
    hits = []
    for needle, label in table:
        if needle in low and label not in hits:
            hits.append(label)
    return hits


def _match_editors(text: str | None) -> list[str]:
    # Ghostscript is a common generator, not an editor, even if listed historically.
    hits = _match_list(text, KNOWN_EDITORS)
    return [h for h in hits if h != "Ghostscript"]


def _match_generators(text: str | None) -> list[str]:
    return _match_list(text, COMMON_GENERATORS)


def _xmp_history(meta) -> list[dict]:
    events = []
    try:
        # pikepdf Metadata supports get/items; history is often in xmpMM:History
        raw = str(meta)
    except Exception:
        raw = ""
    # Pull common XMP fields when present
    keys = [
        "xmp:CreatorTool",
        "pdf:Producer",
        "pdf:Creator",
        "xmp:CreateDate",
        "xmp:ModifyDate",
        "xmpMM:History",
        "photoshop:DocumentAncestors",
    ]
    fields = {}
    for k in keys:
        try:
            val = meta.get(k) if hasattr(meta, "get") else None
            if val:
                fields[k] = str(val)
        except Exception:
            continue
    try:
        # Iterate stEvt elements from the XML if present
        xml = meta.load_from_docinfo and raw  # keep xml string
    except Exception:
        xml = raw
    try:
        import re

        xml = ""
        if hasattr(meta, "_get_xml") or True:
            # metadata object can be serialized
            xml = bytes(meta).decode("utf-8", errors="replace") if hasattr(meta, "__bytes__") else str(meta)
    except Exception:
        xml = raw

    import re

    # Typical XMP: <stEvt:action>converted</stEvt:action> ... softwareAgent, when, instanceID
    block_re = re.compile(
        r"<rdf:li[^>]*>(.*?)</rdf:li>",
        re.DOTALL | re.IGNORECASE,
    )
    field_re = re.compile(
        r"<(?:stEvt:)?(action|softwareAgent|when|instanceID|changed)[^>]*>(.*?)</(?:stEvt:)?\1>",
        re.DOTALL | re.IGNORECASE,
    )
    if xml:
        for block in block_re.findall(xml):
            ev = {}
            for name, val in field_re.findall(block):
                ev[name] = re.sub(r"<[^>]+>", "", val).strip()
            if ev:
                events.append(ev)
    return events, fields, xml


def analyze_metadata(pdf_path: str | Path) -> dict:
    path = Path(pdf_path)
    info = {
        "creator": None,
        "producer": None,
        "author": None,
        "title": None,
        "creation_date_raw": None,
        "mod_date_raw": None,
        "creation_date": None,
        "mod_date": None,
        "dates_differ": False,
        "creator_differs_from_producer": False,
        "known_editors": [],
        "known_generators": [],
        "xmp": {},
        "xmp_history": [],
        "findings": [],
    }
    try:
        with pikepdf.open(path) as pdf:
            docinfo = pdf.docinfo
            info["creator"] = _as_text(docinfo.get("/Creator"))
            info["producer"] = _as_text(docinfo.get("/Producer"))
            info["author"] = _as_text(docinfo.get("/Author"))
            info["title"] = _as_text(docinfo.get("/Title"))
            created_raw = _as_text(docinfo.get("/CreationDate"))
            modified_raw = _as_text(docinfo.get("/ModDate"))
            info["creation_date_raw"] = created_raw
            info["mod_date_raw"] = modified_raw
            created = parse_pdf_date(created_raw)
            modified = parse_pdf_date(modified_raw)
            info["creation_date"] = format_dt(created)
            info["mod_date"] = format_dt(modified)
            if created and modified:
                # Treat differences of more than 2 seconds as a later save
                delta = abs((modified - created).total_seconds()) if created.tzinfo == modified.tzinfo or (created.tzinfo and modified.tzinfo) else 0
                try:
                    delta = abs((modified - created).total_seconds())
                except TypeError:
                    # mix of naive/aware
                    c = created.replace(tzinfo=None)
                    m = modified.replace(tzinfo=None)
                    delta = abs((m - c).total_seconds())
                info["dates_differ"] = delta > 2
                info["date_delta_seconds"] = int(delta)

            if (info["creator"] or "") != (info["producer"] or "") and info["creator"] and info["producer"]:
                # Many genuine files have different creator vs producer.
                # Only highlight when the producer looks like a later editor.
                info["creator_differs_from_producer"] = True

            editors = []
            generators = []
            for field_name in ("producer", "creator"):
                for label in _match_editors(info[field_name]):
                    if label not in editors:
                        editors.append(label)
                for label in _match_generators(info[field_name]):
                    if label not in generators:
                        generators.append(label)
            info["known_editors"] = editors
            info["known_generators"] = generators

            try:
                with pdf.open_metadata() as meta:
                    events, fields, xml = _xmp_history(meta)
                    info["xmp"] = fields
                    info["xmp_history"] = events
                    # Also scan raw XMP for editor names
                    # Only score explicit Creator/Producer/history tools, not
                    # the XMP toolkit stamp (pikepdf writes xmptk="pikepdf").
                    for key in ("pdf:Producer", "xmp:CreatorTool", "pdf:Creator"):
                        for label in _match_editors(fields.get(key)):
                            if label not in info["known_editors"]:
                                info["known_editors"].append(label)
                    for ev in events:
                        for label in _match_editors(ev.get("softwareAgent")):
                            if label not in info["known_editors"]:
                                info["known_editors"].append(label)
                        for label in _match_generators(ev.get("softwareAgent")):
                            if label not in info["known_generators"]:
                                info["known_generators"].append(label)
                    for key in ("pdf:Producer", "xmp:CreatorTool", "pdf:Creator"):
                        for label in _match_generators(fields.get(key)):
                            if label not in info["known_generators"]:
                                info["known_generators"].append(label)
                    xmp_created = fields.get("xmp:CreateDate")
                    xmp_mod = fields.get("xmp:ModifyDate")
                    if xmp_created:
                        info["xmp"]["create_date"] = xmp_created
                    if xmp_mod:
                        info["xmp"]["modify_date"] = xmp_mod
            except Exception as exc:
                info["xmp_error"] = str(exc)
    except Exception as exc:
        info["error"] = f"Could not read PDF metadata: {exc}"
        return info

    findings = []
    if info["known_editors"]:
        findings.append(
            {
                "id": "known_editor",
                "severity": "medium",
                "title": "Document software looks like a PDF editor or print-to-PDF tool",
                "detail": (
                    "The file's Creator or Producer metadata mentions "
                    + ", ".join(info["known_editors"])
                    + ". Brokers often send rate confirmations from a load board or TMS. "
                    "A later save through an editor can be a sign the file was changed after it was issued."
                ),
            }
        )
    elif info.get("known_generators"):
        findings.append(
            {
                "id": "common_generator",
                "severity": "info",
                "title": "This file was produced by software brokers commonly use",
                "detail": (
                    "The file's Producer or Creator mentions "
                    + ", ".join(info["known_generators"])
                    + ". Many brokers and TMS systems generate rate confirmations with Ghostscript. "
                    "That alone is not a sign of later editing."
                ),
            }
        )
    if info["dates_differ"]:
        delta = int(info.get("date_delta_seconds") or 0)
        info["date_delta_human"] = humanize_delta(delta)
        # Scale: a few hours is a weak signal; more than a day is more notable;
        # many months is a strong date signal, but still not proof by itself.
        if delta > 30 * 86400:
            date_sev = "medium"
        elif delta > 24 * 3600:
            date_sev = "medium"
        else:
            date_sev = "low"
        gap = info["date_delta_human"] or "later"
        findings.append(
            {
                "id": "dates_differ",
                "severity": date_sev,
                "title": "Modified date is later than the creation date",
                "detail": (
                    f"Created: {info['creation_date'] or info['creation_date_raw']}. "
                    f"Modified: {info['mod_date'] or info['mod_date_raw']}. "
                    f"The file was saved again {gap} after it was first created. "
                    "That can be a routine re-save, or a sign of editing."
                ),
            }
        )
    if info["creator_differs_from_producer"] and info["known_editors"]:
        findings.append(
            {
                "id": "creator_producer_mismatch",
                "severity": "low",
                "title": "Creator and Producer do not match",
                "detail": (
                    f"Creator is “{info['creator']}” and Producer is “{info['producer']}”. "
                    "This often happens when one program creates a PDF and another program saves it later."
                ),
            }
        )
    if info["xmp_history"]:
        agents = [e.get("softwareAgent") or e.get("action") for e in info["xmp_history"] if e]
        agents = [a for a in agents if a]
        findings.append(
            {
                "id": "xmp_history",
                "severity": "medium" if len(info["xmp_history"]) > 1 else "low",
                "title": "XMP metadata includes an edit history",
                "detail": (
                    f"The file records {len(info['xmp_history'])} history event(s)"
                    + (f": {'; '.join(agents[:6])}" if agents else "")
                    + ". This is a recorded trail of software that touched the document."
                ),
            }
        )
    info["findings"] = findings
    return info
