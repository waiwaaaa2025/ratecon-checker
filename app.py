"""Simple Flask UI for the rate confirmation checker."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import Flask, render_template, request

from checker.analyze import analyze_ratecon

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_PDF = {".pdf"}
ALLOWED_EMAIL = {".eml", ".eml.txt", ".txt"}
MAX_BYTES = 15 * 1024 * 1024

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES


def _save(upload, allowed: set[str]) -> Path | None:
    if upload is None or not upload.filename:
        return None
    name = upload.filename
    suffix = Path(name).suffix.lower()
    if suffix not in allowed and not any(name.lower().endswith(ext) for ext in allowed):
        raise ValueError(f"Unsupported file type for {name}. Use PDF or .eml.")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix or '.bin'}"
    upload.save(dest)
    return dest


@app.get("/")
def index():
    return render_template("index.html", report=None, error=None)


@app.post("/analyze")
def analyze():
    error = None
    report = None
    saved = []
    try:
        pdf_upload = request.files.get("pdf")
        orig_upload = request.files.get("original")
        email_upload = request.files.get("email")
        pdf = _save(pdf_upload, ALLOWED_PDF)
        if pdf is None:
            raise ValueError("Please upload a rate confirmation PDF.")
        saved.append(pdf)
        original = _save(orig_upload, ALLOWED_PDF)
        if original:
            saved.append(original)
        email = _save(email_upload, ALLOWED_EMAIL)
        if email:
            saved.append(email)
        report = analyze_ratecon(pdf, original_path=original, email_path=email, lookup_ip=True)
        if pdf_upload and pdf_upload.filename:
            report["file"] = Path(pdf_upload.filename).name
        if report.get("compare"):
            if orig_upload and orig_upload.filename:
                report["compare"]["original_name"] = Path(orig_upload.filename).name
            if pdf_upload and pdf_upload.filename:
                report["compare"]["received_name"] = Path(pdf_upload.filename).name
        if report.get("email") and email_upload and email_upload.filename:
            report["email"]["filename"] = Path(email_upload.filename).name
    except ValueError as exc:
        error = str(exc)
    except Exception as exc:
        error = f"Could not analyze this file: {exc}"
    finally:
        for path in saved:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return render_template("index.html", report=report, error=error)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
