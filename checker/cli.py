"""Command-line interface for the rate confirmation checker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m checker.cli` from the project root
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checker.analyze import analyze_ratecon


def format_text(report: dict) -> str:
    lines = []
    score = report.get("score") or {}
    lines.append("Trucker College — Rate Confirmation Checker (prototype)")
    lines.append(f"File: {report.get('file')}")
    lines.append(f"Score: {score.get('label') or score.get('level')}")
    lines.append(score.get("summary") or "")
    lines.append("")
    lines.append("Findings")
    lines.append("--------")
    findings = report.get("findings") or []
    if not findings:
        lines.append("No findings.")
    for f in findings:
        lines.append(f"- [{f.get('severity')}] {f.get('title')}")
        if f.get("detail"):
            lines.append(f"  {f['detail']}")
    inc = report.get("incremental") or {}
    if inc.get("amount_changes"):
        lines.append("")
        lines.append("Amounts recovered from earlier revisions:")
        for ch in inc["amount_changes"]:
            to = ", ".join(ch["to"]) if isinstance(ch["to"], list) else ch["to"]
            lines.append(f"  {ch['from']} → {to}")
    cmp_ = report.get("compare")
    if cmp_ and cmp_.get("amount_changes"):
        lines.append("")
        lines.append("Compare mode (broker original vs received copy):")
        for ch in cmp_["amount_changes"]:
            lines.append(f"  {ch['from']} → {ch['to']}")
    email = report.get("email")
    if email and email.get("sending_ips"):
        lines.append("")
        lines.append("Email sending IPs (approximate location):")
        for row in email["sending_ips"]:
            place = row.get("approximate_place") or row.get("error") or ""
            lines.append(f"  {row.get('ip')} {place}".rstrip())
    lines.append("")
    lines.append(score.get("limits") or "")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a rate confirmation PDF for signs of editing."
    )
    parser.add_argument("pdf", help="Rate confirmation PDF to check")
    parser.add_argument("--original", help="Optional broker-original PDF for compare mode")
    parser.add_argument("--email", help="Optional raw .eml email the rate con arrived in")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON")
    parser.add_argument("--no-ip-lookup", action="store_true", help="Do not call the IP geolocation API")
    args = parser.parse_args(argv)

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"File not found: {pdf}", file=sys.stderr)
        return 2

    report = analyze_ratecon(
        pdf,
        original_path=args.original,
        email_path=args.email,
        lookup_ip=not args.no_ip_lookup,
    )
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
