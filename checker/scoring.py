"""Score signs of editing. Never call the result 'proof of fraud'."""

from __future__ import annotations

SEVERITY_POINTS = {
    "high": 40,
    "medium": 15,
    "low": 6,
    "info": 0,
}

# Caps so a pile of low findings cannot outrun a single clean file with noisy metadata
HIGH_IDS_BOOST = {
    "recovered_rate_change",
    "compare_amount_change",
    "white_overlay",
    "modified_after_signing",
}


def score_findings(findings: list[dict]) -> dict:
    actionable = [f for f in findings if f.get("severity") in {"high", "medium", "low"}]
    points = sum(SEVERITY_POINTS.get(f.get("severity"), 0) for f in actionable)
    has_high = any(f.get("severity") == "high" for f in actionable)
    has_medium = any(f.get("severity") == "medium" for f in actionable)

    if not actionable:
        level = "none"
        label = "No significant signs of editing"
        summary = (
            "This file does not show the usual signs this tool looks for. "
            "That does not prove the rate confirmation is authentic. "
            "A dispatcher who retypes the whole document or uses Print to PDF can produce a clean-looking file."
        )
    elif has_high or points >= 40:
        level = "high"
        label = "High — several signs of editing"
        summary = (
            "This file shows strong signs of editing, such as an earlier revision, a covered rate, "
            "or money amounts that do not match a broker original. These are signs of editing, not proof of fraud."
        )
    elif has_medium or points >= 15:
        level = "medium"
        label = "Medium — some signs of editing"
        summary = (
            "This file shows some signs it was saved or changed after it was first created. "
            "These are signs of editing, not proof of fraud."
        )
    else:
        level = "low"
        label = "Low — limited signs of editing"
        summary = (
            "A few minor signs turned up (for example a later save date). "
            "Taken alone, this is a weak signal. These are signs of editing, not proof of fraud."
        )

    limits = (
        "Limits of this check: if someone retypes the rate confirmation from scratch or prints it to a new PDF, "
        "metadata and font checks may find nothing. Comparing the driver's copy with the original the broker sent "
        "is the strongest test. Email headers can show the sending mail server's approximate location; "
        "a PDF itself usually does not store an IP address. This tool reports signs of editing. "
        "It does not prove fraud, and it is not a legal finding."
    )
    return {
        "level": level,
        "label": label,
        "summary": summary,
        "points": points,
        "limits": limits,
    }
