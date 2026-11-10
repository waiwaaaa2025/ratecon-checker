#!/usr/bin/env python3
"""Create a realistic sample rate confirmation and tampered variants."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

import pikepdf
from pikepdf import Name, String
import pymupdf

ROOT = Path(__file__).resolve().parent
NAVY = HexColor("#0b1c33")
ORANGE = HexColor("#f26522")
GRAY = HexColor("#333333")
LIGHT = HexColor("#f4f6f8")

CREATED = datetime(2026, 10, 15, 14, 30, 0, tzinfo=timezone(timedelta(hours=-5)))


def pdf_date(dt: datetime) -> str:
    offset = dt.utcoffset() or timedelta(0)
    sign = "+" if offset >= timedelta(0) else "-"
    minutes = int(abs(offset.total_seconds()) // 60)
    oh, om = divmod(minutes, 60)
    return dt.strftime(f"D:%Y%m%d%H%M%S{sign}{oh:02d}'{om:02d}'")


def draw_rate_con(c: canvas.Canvas, rate_label: str = "$2,450.00"):
    width, height = letter
    c.setFillColor(NAVY)
    c.rect(0, height - 86, width, 86, fill=1, stroke=0)
    c.setFillColor(ORANGE)
    c.rect(0, height - 92, width, 6, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.7 * inch, height - 40, "EXAMPLE LOGISTICS LLC")
    c.setFont("Helvetica", 10)
    c.drawString(0.7 * inch, height - 56, "Property Broker  ·  MC-123456  ·  USDOT 1234567")
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(width - 0.7 * inch, height - 40, "RATE CONFIRMATION")
    c.setFont("Helvetica", 9)
    c.drawRightString(width - 0.7 * inch, height - 56, "RC-88421  ·  October 15, 2026")

    y = height - 130
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 10)
    left = 0.7 * inch
    rows = [
        ("Broker", "Example Logistics LLC"),
        ("Carrier", "Highway Independent LLC  ·  MC-765432"),
        ("Shipper", "Summit Warehouse Co."),
        ("Pickup", "Dallas, TX  ·  October 18, 2026  08:00"),
        ("Delivery", "Atlanta, GA  ·  October 20, 2026  14:00"),
        ("Equipment", "53' Dry Van"),
        ("Commodity", "General Freight"),
        ("Weight", "42,000 lbs"),
        ("Miles", "780"),
        ("Reference", "PO-44119 / PU-7782"),
    ]
    for label, value in rows:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(HexColor("#666666"))
        c.drawString(left, y, label.upper())
        c.setFont("Helvetica", 11)
        c.setFillColor(GRAY)
        c.drawString(left + 1.3 * inch, y, value)
        y -= 18

    y -= 10
    c.setFillColor(LIGHT)
    c.roundRect(left, y - 86, width - 1.4 * inch, 100, 6, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left + 14, y, "Charges")
    y -= 20
    c.setFont("Helvetica", 11)
    c.setFillColor(GRAY)
    c.drawString(left + 14, y, "Line Haul")
    c.drawRightString(width - 0.9 * inch, y, rate_label)
    y -= 18
    c.drawString(left + 14, y, "Fuel Surcharge")
    c.drawRightString(width - 0.9 * inch, y, "$0.00")
    y -= 18
    c.drawString(left + 14, y, "Accessorials")
    c.drawRightString(width - 0.9 * inch, y, "$0.00")
    y -= 22
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(NAVY)
    c.drawString(left + 14, y, "TOTAL RATE")
    c.drawRightString(width - 0.9 * inch, y, rate_label)

    y -= 50
    c.setFont("Helvetica", 9)
    c.setFillColor(GRAY)
    notes = [
        "This rate confirmation is the official tender of load RC-88421.",
        "The agreed rate is all-in unless accessorials are approved in writing by the broker.",
        "Questions: dispatch@examplelogistics.test  ·  (555) 014-2200",
    ]
    for line in notes:
        c.drawString(left, y, line)
        y -= 14

    c.setFillColor(NAVY)
    c.rect(0, 0, width, 36, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 8)
    c.drawString(left, 16, "Example Logistics LLC  ·  100 Broker Way, Chicago, IL 60601")
    c.showPage()
    c.save()


def write_info(path: Path, creator: str, producer: str, created: datetime, modified: datetime, title: str):
    with pikepdf.open(path, allow_overwriting_input=True) as pdf:
        info = pdf.docinfo
        info[Name.Creator] = creator
        info[Name.Producer] = producer
        info[Name.Author] = "Example Logistics LLC"
        info[Name.Title] = title
        info[Name.CreationDate] = String(pdf_date(created))
        info[Name.ModDate] = String(pdf_date(modified))
        try:
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                meta["dc:title"] = title
                meta["pdf:Producer"] = producer
                meta["xmp:CreatorTool"] = creator
                meta["xmp:CreateDate"] = created.isoformat()
                meta["xmp:ModifyDate"] = modified.isoformat()
        except Exception:
            pass
        pdf.save(path)


def make_original(path: Path):
    tmp = path.with_suffix(".raw.pdf")
    c = canvas.Canvas(str(tmp), pagesize=letter)
    c.setTitle("Rate Confirmation RC-88421")
    c.setAuthor("Example Logistics LLC")
    c.setCreator("Example TMS 4.2")
    draw_rate_con(c, "$2,450.00")
    write_info(
        tmp,
        creator="Example TMS 4.2",
        producer="Example TMS 4.2",
        created=CREATED,
        modified=CREATED,
        title="Rate Confirmation RC-88421",
    )
    shutil.move(tmp, path)


def make_tampered_incremental(original: Path, dest: Path):
    shutil.copy(original, dest)
    doc = pymupdf.open(dest)
    page = doc[0]
    # Cover every $2,450.00 occurrence and type a new amount in Times-Roman
    for needle in ("$2,450.00",):
        for rect in page.search_for(needle):
            cover = pymupdf.Rect(rect.x0 - 2, rect.y0 - 1, rect.x1 + 8, rect.y1 + 1)
            page.draw_rect(cover, color=(1, 1, 1), fill=(1, 1, 1), width=0, overlay=True)
            # insert_text uses baseline coordinates
            page.insert_text(
                pymupdf.Point(rect.x0, rect.y1 - 1.2),
                "$1,950.00",
                fontname="tiro",  # Times-Roman — different from Helvetica
                fontsize=11 if "TOTAL" not in page.get_textbox(pymupdf.Rect(rect.x0 - 200, rect.y0, rect.x1, rect.y1)) else 13,
                color=(0.05, 0.11, 0.2),
            )
    doc.saveIncr()
    doc.close()


def make_tampered_resave(original: Path, dest: Path):
    # Full rewrite through a different producer; keep the original $2,450.00 text
    src = pikepdf.open(original)
    src.save(dest)  # rewrite, single revision
    src.close()
    later = CREATED + timedelta(hours=6, minutes=12)
    write_info(
        dest,
        creator="Example TMS 4.2",
        producer="iLovePDF",
        created=CREATED,
        modified=later,
        title="Rate Confirmation RC-88421",
    )


def make_sample_email(path: Path, attachment_note: str = "rate-confirmation-rc-88421.pdf"):
    body = f"""From: dispatch@midwayhauling.test
To: driver@highwayindependent.test
Subject: Rate con RC-88421 — Dallas to Atlanta
Date: Thu, 15 Oct 2026 20:44:11 -0500
Message-ID: <rc88421@midwayhauling.test>
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8

Attached is the rate confirmation for RC-88421.

— Midway Dispatch
"""
    # Typical Received chain: latest first
    raw = f"""Received: from mx.truckermail.test (mx.truckermail.test [8.8.8.8])
	by inbound.truckercamp.test with ESMTPS id ab12
	for <driver@highwayindependent.test>; Thu, 15 Oct 2026 21:44:40 -0400
Received: from mail.midwayhauling.test (mail.midwayhauling.test [1.1.1.1])
	by mx.truckermail.test with ESMTPS id cd34
	for <driver@highwayindependent.test>; Thu, 15 Oct 2026 20:44:18 -0500
{body}"""
    path.write_text(raw, encoding="utf-8")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    original = ROOT / "original.pdf"
    tampered_a = ROOT / "tampered_incremental.pdf"
    tampered_b = ROOT / "tampered_resave.pdf"
    email = ROOT / "forwarded_ratecon.eml"

    make_original(original)
    make_tampered_incremental(original, tampered_a)
    make_tampered_resave(original, tampered_b)
    make_sample_email(email)
    print("Wrote:")
    for p in (original, tampered_a, tampered_b, email):
        print(f"  {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    sys.exit(main() or 0)
