#!/usr/bin/env python3
"""Sanity tests for the sample rate confirmations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checker.analyze import analyze_ratecon

SAMPLES = ROOT / "samples"


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_original_passes():
    report = analyze_ratecon(SAMPLES / "original.pdf", lookup_ip=False)
    assert_true(report["score"]["level"] == "none", f"original should pass, got {report['score']}")
    actionable = [f for f in report["findings"] if f["severity"] in {"low", "medium", "high"}]
    assert_true(not actionable, f"original had unexpected findings: {actionable}")


def test_incremental_flagged_and_compare():
    report = analyze_ratecon(
        SAMPLES / "tampered_incremental.pdf",
        original_path=SAMPLES / "original.pdf",
        lookup_ip=False,
    )
    assert_true(report["score"]["level"] == "high", f"incremental should be high, got {report['score']}")
    ids = {f["id"] for f in report["findings"]}
    for needed in (
        "incremental_update",
        "recovered_rate_change",
        "white_overlay",
        "compare_amount_change",
    ):
        assert_true(needed in ids, f"missing finding {needed}: {ids}")
    changes = " ".join(
        f"{c['from']} -> {c['to']}" for c in (report["compare"] or {}).get("amount_changes") or []
    )
    assert_true("2,450.00" in changes and "1,950.00" in changes, f"compare missed rate change: {changes}")


def test_resave_flagged():
    report = analyze_ratecon(SAMPLES / "tampered_resave.pdf", lookup_ip=False)
    assert_true(
        report["score"]["level"] in {"medium", "high"},
        f"resave should be flagged, got {report['score']}",
    )
    ids = {f["id"] for f in report["findings"]}
    assert_true("known_editor" in ids, f"resave should mention a known editor: {ids}")
    assert_true(report["metadata"]["producer"] == "iLovePDF", report["metadata"])


def test_email_ips():
    report = analyze_ratecon(
        SAMPLES / "original.pdf",
        email_path=SAMPLES / "forwarded_ratecon.eml",
        lookup_ip=True,
    )
    ips = [row.get("ip") for row in (report["email"] or {}).get("sending_ips") or []]
    assert_true("1.1.1.1" in ips and "8.8.8.8" in ips, f"expected sample IPs, got {ips}")



FIXTURES = ROOT / "tests" / "fixtures"


def _require_fixture(*names: str) -> None:
    """Skip when private broker PDFs are not in this public repo."""
    missing = [name for name in names if not (FIXTURES / name).is_file()]
    if missing:
        listed = ", ".join(f"tests/fixtures/{name}" for name in missing)
        raise unittest.SkipTest(f"private fixture not included ({listed})")


def _finding_blob(report):
    parts = []
    for f in report.get("findings") or []:
        parts.append(f.get("title") or "")
        parts.append(f.get("detail") or "")
    inc = report.get("incremental") or {}
    for ch in inc.get("amount_changes") or []:
        parts.append(str(ch))
    cmp_ = report.get("compare") or {}
    for ch in cmp_.get("amount_changes") or []:
        parts.append(str(ch))
    preview = report.get("preview") or {}
    parts.append(str(preview.get("amounts")))
    return " ".join(parts)


def test_real_broker_is_none_or_low():
    _require_fixture("broker.pdf")
    report = analyze_ratecon(FIXTURES / "broker.pdf", lookup_ip=False)
    assert_true(
        report["score"]["level"] in {"none", "low"},
        f"broker original should be none/low, got {report['score']} findings={report['findings']}",
    )
    actionable = [f for f in report["findings"] if f["severity"] in {"medium", "high"}]
    assert_true(not actionable, f"broker original had medium/high findings: {actionable}")
    ids = {f["id"] for f in report["findings"]}
    assert_true("known_editor" not in ids, f"Ghostscript should not be treated as an editor: {ids}")


def test_real_edited_standalone_is_high():
    _require_fixture("edited.pdf")
    report = analyze_ratecon(FIXTURES / "edited.pdf", lookup_ip=False)
    assert_true(
        report["score"]["level"] == "high",
        f"edited file without original should be high, got {report['score']} findings={report['findings']}",
    )
    ids = {f["id"] for f in report["findings"]}
    assert_true("page_flattened" in ids, f"expected page flatten finding: {ids}")
    blob = _finding_blob(report)
    assert_true(
        "5,353.00" in blob or "5353.00" in blob,
        f"expected OCR/recovered $5,353.00 in findings: {blob}",
    )
    # Original $1,150.00 is not in leftover objects; do not require it.
    assert_true(
        "signs of editing" in blob.lower() or "sign of editing" in (report["score"].get("summary") or "").lower(),
        "wording should stay signs of editing, not proof of fraud",
    )
    assert_true(
        "fraud" not in (report["score"].get("label") or "").lower(),
        report["score"],
    )


def test_real_edited_compare_is_high():
    _require_fixture("broker.pdf", "edited.pdf")
    report = analyze_ratecon(
        FIXTURES / "edited.pdf",
        original_path=FIXTURES / "broker.pdf",
        lookup_ip=False,
    )
    assert_true(report["score"]["level"] == "high", f"compare should be high, got {report['score']}")
    ids = {f["id"] for f in report["findings"]}
    assert_true("compare_amount_change" in ids, f"missing compare_amount_change: {ids}")
    blob = _finding_blob(report)
    assert_true("1,150.00" in blob or "1150.00" in blob, f"compare should mention original $1,150.00: {blob}")
    assert_true("5,353.00" in blob or "5353.00" in blob, f"compare should mention $5,353.00: {blob}")



if __name__ == "__main__":
    tests = [
        test_original_passes,
        test_incremental_flagged_and_compare,
        test_resave_flagged,
        test_email_ips,
        test_real_broker_is_none_or_low,
        test_real_edited_standalone_is_high,
        test_real_edited_compare_is_high,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except unittest.SkipTest as exc:
            print(f"SKIP {fn.__name__}: {exc}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    sys.exit(1 if failed else 0)
