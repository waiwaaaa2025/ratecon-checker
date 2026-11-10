"""PDF date parsing."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

PDF_DATE_RE = re.compile(
    r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?"
    r"(?:([Zz])|([+\-])(\d{2})'?(\d{2})'?)?"
)


def parse_pdf_date(value) -> datetime | None:
    if value is None:
        return None
    s = str(value).strip()
    if s.startswith("b'") or s.startswith('b"'):
        s = s[2:-1]
    s = s.replace("\x00", "").strip()
    m = PDF_DATE_RE.search(s)
    if not m:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    year = int(m.group(1))
    month = int(m.group(2) or 1)
    day = int(m.group(3) or 1)
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    try:
        dt = datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    if m.group(7):
        return dt.replace(tzinfo=timezone.utc)
    if m.group(8):
        sign = 1 if m.group(8) == "+" else -1
        off_h = int(m.group(9) or 0)
        off_m = int(m.group(10) or 0)
        return dt.replace(tzinfo=timezone(sign * timedelta(hours=off_h, minutes=off_m)))
    return dt


def format_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo:
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def humanize_delta(seconds: float | int | None) -> str | None:
    """Plain-English time gap, e.g. 'about 20 months'."""
    if seconds is None:
        return None
    try:
        sec = abs(float(seconds))
    except (TypeError, ValueError):
        return None
    if sec < 120:
        return f"{int(sec)} seconds"
    minutes = sec / 60
    if minutes < 120:
        return f"about {int(round(minutes))} minutes"
    hours = sec / 3600
    if hours < 48:
        return f"about {int(round(hours))} hours"
    days = sec / 86400
    if days < 45:
        n = int(round(days))
        return f"about {n} day" if n == 1 else f"about {n} days"
    months = days / 30.437
    if months < 24:
        n = int(round(months))
        return f"about {n} month" if n == 1 else f"about {n} months"
    years = days / 365.25
    n = round(years, 1)
    if n == int(n):
        n = int(n)
        return f"about {n} year" if n == 1 else f"about {n} years"
    return f"about {n} years"
