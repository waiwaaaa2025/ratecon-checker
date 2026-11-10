"""Parse .eml Received headers and look up approximate IP geolocation."""

from __future__ import annotations

import email
import ipaddress
import json
import re
import urllib.error
import urllib.request
from email.policy import default
from pathlib import Path

IP_RE = re.compile(
    r"(?:\[|\(|\s)((?:\d{1,3}\.){3}\d{1,3})(?:\]|\)|\s)"
)
IPV6_RE = re.compile(
    r"\[?(IPv6:)?([0-9a-fA-F:]{2,})\]?"
)


def _public_ipv4(text: str) -> list[str]:
    found = []
    for m in IP_RE.finditer(" " + text + " "):
        ip = m.group(1)
        try:
            obj = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if obj.version == 4 and obj.is_global:
            if ip not in found:
                found.append(ip)
    return found


def _http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "TruckerCollege-RateConChecker/0.1"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def geolocate(ip: str) -> dict:
    """Look up an approximate city-level location.

    Tries ip-api.com first (free HTTP endpoint). Some networks block it;
    in that case we fall back to ipwho.is. Results are approximate only.
    """
    errors = []
    # ip-api.com free tier is HTTP-only
    try:
        data = _http_json(
            f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,isp,org,query"
        )
        if data.get("status") == "success":
            place = ", ".join(p for p in (data.get("city"), data.get("regionName"), data.get("country")) if p)
            return {
                "ip": ip,
                "approximate_place": place or None,
                "isp": data.get("isp"),
                "org": data.get("org"),
                "source": "ip-api.com",
                "disclaimer": (
                    "Approximate location of a mail server, not a person's address. "
                    "This is a rough, city- or region-level estimate from a public IP lookup."
                ),
            }
        errors.append(f"ip-api.com: {data.get('message') or 'lookup failed'}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
        errors.append(f"ip-api.com: {exc}")

    try:
        data = _http_json(f"https://ipwho.is/{ip}")
        if data.get("success"):
            place = ", ".join(
                p for p in (data.get("city"), data.get("region"), data.get("country")) if p
            )
            conn = data.get("connection") or {}
            return {
                "ip": ip,
                "approximate_place": place or None,
                "isp": conn.get("isp") or conn.get("org"),
                "org": conn.get("org"),
                "source": "ipwho.is (fallback; ip-api.com was unavailable)",
                "disclaimer": (
                    "Approximate location of a mail server, not a person's address. "
                    "This is a rough, city- or region-level estimate from a public IP lookup."
                ),
            }
        errors.append(f"ipwho.is: {data.get('message') or 'lookup failed'}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
        errors.append(f"ipwho.is: {exc}")

    return {"ip": ip, "error": "Geolocation lookup failed: " + "; ".join(errors)}


def analyze_email(email_path: str | Path, lookup: bool = True) -> dict:
    path = Path(email_path)
    result = {
        "filename": path.name,
        "subject": None,
        "from": None,
        "to": None,
        "date": None,
        "received": [],
        "sending_ips": [],
        "findings": [],
    }
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=default)
    except Exception as exc:
        result["error"] = f"Could not parse this email file: {exc}"
        return result

    result["subject"] = msg.get("Subject")
    result["from"] = msg.get("From")
    result["to"] = msg.get("To")
    result["date"] = msg.get("Date")

    received = msg.get_all("Received") or []
    # Headers are listed top (latest) to bottom (earliest). Reverse so hop 1 is first received.
    hops = list(reversed(received))
    sending_ips = []
    hop_rows = []
    for i, header in enumerate(hops, start=1):
        text = " ".join(str(header).split())
        ips = _public_ipv4(text)
        for ip in ips:
            if ip not in sending_ips:
                sending_ips.append(ip)
        hop_rows.append({"hop": i, "header": text[:500], "ips": ips})
    result["received"] = hop_rows

    lookups = []
    if lookup:
        for ip in sending_ips:
            lookups.append(geolocate(ip))
    else:
        lookups = [{"ip": ip, "skipped": True} for ip in sending_ips]
    result["sending_ips"] = lookups

    if sending_ips:
        parts = []
        for row in lookups:
            if row.get("approximate_place"):
                parts.append(f"{row['ip']} ≈ {row['approximate_place']}")
            else:
                parts.append(row["ip"] + (f" ({row.get('error')})" if row.get("error") else ""))
        result["findings"].append(
            {
                "id": "email_ips",
                "severity": "info",
                "title": "Sending IP addresses from the email headers",
                "detail": (
                    "These public IP addresses appear in the email's Received headers (approximate location only): "
                    + "; ".join(parts)
                    + ". The first hops are closer to the sender's mail server. "
                    "A forwarded email may show the forwarder's server, not the original broker's."
                ),
            }
        )
    else:
        result["findings"].append(
            {
                "id": "email_no_public_ip",
                "severity": "info",
                "title": "No public IP address was found in the email headers",
                "detail": "The Received headers did not contain a public IPv4 address, or the file may be a partial paste rather than a raw .eml message.",
            }
        )
    return result
