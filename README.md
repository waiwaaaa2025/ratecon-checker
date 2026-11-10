# Rate Confirmation Checker (prototype)

A Trucker College prototype for Vaiva Grama (Trucking Godmother). A driver uploads a rate confirmation PDF — and optionally the broker’s original PDF and/or the raw `.eml` email it arrived in — and gets a plain-English report of **signs of editing**.

**Disclaimer:** Results are signs of editing, not proof of fraud or a legal finding. A dispatcher who retypes a rate confirmation or uses Print to PDF may leave no signs. Compare mode (broker original vs received copy) is the strongest check.

## What it checks

1. **Metadata** — Creator vs Producer, creation vs modified dates, XMP history, and known editor signatures (Adobe Acrobat, iLovePDF, PaperPort, Smallpdf, Sejda, PDFescape, Foxit, Word / Print to PDF, and others). Ghostscript is treated as a common broker/TMS generator, not as an editor by itself. A modified date far after creation is weighted more heavily than a same-day re-save.
2. **Incremental updates** — counts `%%EOF` / `startxref` sections; if more than one, it opens earlier revisions, notes the Producer/software of each save, and diffs money amounts (the original rate can sometimes still be recovered). Several extra saves plus a software change plus a late modification date are stacked into a high finding.
3. **Font forensics** — flags dollar amounts set in a different font family than the rest of the page, and fonts added only in a later revision.
4. **Overlays and flattened pages** — tight white rectangles over text, and pages that were converted to a full-page image (a common way to hide edits).
5. **OCR fallback** — when a page has no selectable text, Tesseract is used to read visible amounts from a rendered image. On Windows, install Tesseract with the optional [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) and make sure `tesseract` is on your PATH; `pytesseract` alone is not enough.
6. **Digital signatures** — reports if a signature is present, and flags incremental updates after a signature.
7. **Compare mode** — text and money-amount diff between the broker original and the received copy (including OCR of flattened pages).
8. **Email headers** — parses `Received` headers on a raw `.eml`, lists public sending IPs, and looks up an **approximate** city-level location (tries ip-api.com, then ipwho.is if that endpoint is blocked). This is the location of a mail server, not a person.
9. **Score** — none / low / medium / high **signs of editing**, plus a limits note.

ExifTool is optional and not required; metadata is read with pikepdf.

## How to run

From this directory, using the project virtualenv:

```bash
# Web UI (http://127.0.0.1:8080)
./.venv/bin/python app.py

# CLI
./.venv/bin/python -m checker.cli samples/tampered_incremental.pdf --original samples/original.pdf
./.venv/bin/python -m checker.cli samples/tampered_resave.pdf --email samples/forwarded_ratecon.eml
./.venv/bin/python -m checker.cli path/to/file.pdf --json

# Regenerate sample PDFs
./.venv/bin/python samples/generate_samples.py

# Tests
./.venv/bin/python tests/test_checker.py
```

If you need a fresh virtualenv:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

The server listens on `127.0.0.1` and port `8080` by default. Set `HOST` or `PORT` to override either one.

### Windows

```bat
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

Then open http://127.0.0.1:8080

Optional OCR: if a page has no selectable text, install Tesseract with the [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) and make sure `tesseract` is on your PATH. The `pytesseract` package does not include the OCR engine.

## Sample files

- `samples/original.pdf` — untouched broker rate confirmation from “Example Logistics LLC,” total rate **$2,450.00**, Creator/Producer “Example TMS 4.2.”
- `samples/tampered_incremental.pdf` — incremental edit: white boxes over the amounts, **$1,950.00** typed in Times-Roman.
- `samples/tampered_resave.pdf` — full rewrite, Producer set to **iLovePDF**, later modified date, rate unchanged.
- `samples/forwarded_ratecon.eml` — sample forwarded message with `Received` IPs.

## Limits

- Retyped or print-to-PDF documents may show no signs of editing.
- If a dispatcher flattens a page to an image and drops the original text objects, the earlier rate may not be recoverable from that file alone. Compare mode with the broker original is then the strongest check.
- OCR needs a system install of Tesseract. On Windows, use the optional [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki); the Python package `pytesseract` will not work without it.
- Most PDFs do not store an IP address or a location; use the email header when you have it.
- Results are signs of editing, not proof of fraud or a legal finding. This is a prototype, not legal advice.
