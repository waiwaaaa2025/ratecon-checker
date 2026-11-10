"""Optional OCR fallback for flattened / image-only PDF pages."""

from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path

OCR_AVAILABLE = False
OCR_ENGINE = None
OCR_ERROR = None

try:
    import pytesseract
    from PIL import Image

    try:
        pytesseract.get_tesseract_version()
        OCR_AVAILABLE = True
        OCR_ENGINE = "tesseract"
    except Exception as exc:  # tesseract binary missing
        OCR_ERROR = str(exc)
except Exception as exc:
    OCR_ERROR = str(exc)
    pytesseract = None  # type: ignore
    Image = None  # type: ignore

# (path, page_index, dpi, psm) -> text
_CACHE: dict[tuple[str, int, int, str], str] = {}

# PSM 4 (single column) read this PaperPort flatten correctly;
# PSM 6 missed the charges row. Try both and prefer the one with more amounts.
_PSM_MODES = ("4", "6")


def ocr_status() -> dict:
    return {
        "available": OCR_AVAILABLE,
        "engine": OCR_ENGINE,
        "error": OCR_ERROR,
        "tesseract_path": shutil.which("tesseract"),
    }


def _ocr_png_bytes(png: bytes, psm: str) -> str:
    if not OCR_AVAILABLE or pytesseract is None:
        return ""
    return pytesseract.image_to_string(Image.open(io.BytesIO(png)), config=f"--psm {psm}") or ""


def ocr_image_bytes(png: bytes) -> str:
    """OCR a PNG (or JPEG) byte string, trying a couple of page-segmentation modes."""
    if not OCR_AVAILABLE:
        return ""
    from .money import find_money

    best = ""
    best_score = -1
    for psm in _PSM_MODES:
        try:
            text = _ocr_png_bytes(png, psm)
        except Exception:
            text = ""
        score = len(find_money(text)) * 1000 + len(text)
        if score > best_score:
            best_score = score
            best = text
    return best


def ocr_page(page, dpi: int = 200) -> str:
    """OCR a pymupdf page. Results are cached per document name + page + dpi."""
    if not OCR_AVAILABLE:
        return ""
    doc = page.parent
    key_name = ""
    try:
        key_name = doc.name or ""
    except Exception:
        key_name = ""
    cache_key = (key_name, int(page.number), int(dpi), "best")
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    pix = page.get_pixmap(dpi=dpi)
    png = pix.tobytes("png")
    text = ocr_image_bytes(png)
    _CACHE[cache_key] = text
    return text


def ocr_pdf_page(pdf_path: str | Path, page_index: int, dpi: int = 200) -> str:
    import pymupdf

    path = Path(pdf_path)
    doc = pymupdf.open(path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return ""
        return ocr_page(doc[page_index], dpi=dpi)
    finally:
        doc.close()
