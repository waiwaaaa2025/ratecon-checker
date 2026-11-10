"""Helpers for finding money amounts and rate-related labels in text."""

from __future__ import annotations

import re

# Amounts written with a dollar sign.
MONEY_RE = re.compile(
    r"\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+\.\d{2})"
)

# Broker rate cons often print "1150.00" or "5,353.00" with no dollar sign.
PLAIN_MONEY_RE = re.compile(
    r"(?<![\d$])(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})(?![\d.])"
)

KEYWORD_RE = re.compile(
    r"\b(rate|total|line\s*haul|linehaul|amount|agreed\s*rate|"
    r"pay|compensation|freight\s*charge|all\sin)\b",
    re.IGNORECASE,
)

LINE_HAUL_VALUE_RE = re.compile(
    r"\bLINE\s*HAUL(?:\s*RATE)?\s*[:\-]?\s*(\S+)",
    re.IGNORECASE,
)
TOTAL_RATE_VALUE_RE = re.compile(
    r"\bTOTAL(?:\s*RATE)?\s*[:\-]?\s*(\S+)",
    re.IGNORECASE,
)


def normalize_amount(raw: str) -> str:
    digits = re.sub(r"[^\d.]", "", raw)
    if not digits:
        return raw
    try:
        return f"{float(digits):,.2f}"
    except ValueError:
        return raw


def parse_amount(raw: str) -> float | None:
    digits = re.sub(r"[^\d.]", "", raw or "")
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def looks_like_money_token(text: str) -> bool:
    """True if a short text span looks like a dollar amount."""
    t = (text or "").strip()
    if not t:
        return False
    if MONEY_RE.search(t):
        return True
    return bool(PLAIN_MONEY_RE.fullmatch(t) or PLAIN_MONEY_RE.search(t))


def _append_match(found: list[dict], text: str, raw: str, start: int, end: int, source: str) -> None:
    value = parse_amount(raw)
    if value is None:
        return
    # Skip tiny decimals that are almost certainly not a rate (e.g. 0.12).
    if value < 1:
        return
    ctx_start = max(0, start - 40)
    ctx = re.sub(r"\s+", " ", text[ctx_start : end + 20]).strip()
    found.append(
        {
            "raw": raw if raw.startswith("$") else text[start:end],
            "value": value,
            "normalized": f"${value:,.2f}",
            "context": ctx,
            "near_rate_keyword": bool(KEYWORD_RE.search(ctx)),
            "source": source,
        }
    )


def find_money(text: str) -> list[dict]:
    found: list[dict] = []
    seen_spans: set[tuple[int, int]] = set()
    body = text or ""
    for m in MONEY_RE.finditer(body):
        seen_spans.add((m.start(), m.end()))
        _append_match(found, body, m.group(0), m.start(), m.end(), "dollar")
    for m in PLAIN_MONEY_RE.finditer(body):
        span = (m.start(), m.end())
        # Skip if this number was already captured as part of a $ amount.
        if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
            continue
        seen_spans.add(span)
        _append_match(found, body, m.group(0), m.start(), m.end(), "plain")
    return found


def unique_values(amounts: list[dict]) -> list[float]:
    vals = sorted({round(a["value"], 2) for a in amounts})
    return vals


def unusual_rate_field_values(text: str) -> list[dict]:
    """Find LINE HAUL / TOTAL RATE values that are not money amounts (e.g. TTTTTT)."""
    hits = []
    body = text or ""
    for label, cre in (("LINE HAUL RATE", LINE_HAUL_VALUE_RE), ("TOTAL RATE", TOTAL_RATE_VALUE_RE)):
        for m in cre.finditer(body):
            raw = m.group(1).strip().rstrip(".,;:")
            if not raw:
                continue
            if looks_like_money_token(raw) or parse_amount(raw) is not None:
                continue
            # Ignore trailing labels if OCR glued the next word on.
            if re.fullmatch(r"[A-Za-z]{3,}", raw) or re.search(r"[A-Za-z]{3,}", raw):
                hits.append({"label": label, "value": raw})
    return hits
