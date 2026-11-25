#!/usr/bin/env python3
"""Refresh NIGHTLY public Tallinn events without API keys or paid services.

Sources: Viidad Tallinn JSON directory. Facebook labels are used ONLY when
an original Facebook event URL is supplied by the data source.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BASE = "https://viidad.ee/tallinn/events/day/"
DAYS = 10
MAX_EVENTS = 250
ALLOWED = {"nightlife", "music", "comedy", "food", "other", "workshops", "family", "theatre"}
CATEGORIES = {"nightlife": "Pidu", "music": "Kontsert", "comedy": "Muu", "food": "Muu", "workshops": "Muu", "family": "Muu", "theatre": "Muu", "other": "Muu"}
DISTRICTS = {
    "Põhja-Tallinn": ["telliskivi", "kopli", "paavli", "põhja-tallinn", "noblessner", "kalamaja", "balti jaam", "volta", "peetri 6", "marati"],
    "Lasnamäe": ["lasnamäe", "pae tn", "läänemere tee", "laagna"],
    "Mustamäe": ["mustamäe", "akadeemia tee", "sõpruse pst 200"],
    "Kristiine": ["kristiine", "tulika", "kotka", "lilleküla"],
    "Haabersti": ["haabersti", "roc al mare", "õismäe", "paldiski maantee 96"],
    "Nõmme": ["nõmme", "pääsküla", "hiiu", "vabaduse puiestee"],
    "Pirita": ["pirita", "merivälja", "kose tee"],
}
FB_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.me"}

def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "NIGHTLY-events/1.0 (+https://github.com/nightly-estonia/nightly)", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=22) as response:
        return json.load(response)

def district(address, venue):
    combined = ((address or "") + " " + (venue or "")).lower()
    for name, matches in DISTRICTS.items():
        if any(word in combined for word in matches):
            return name
    return "Kesklinn"

def source_url(row):
    sources = row.get("sources") or []
    for item in sources:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() in FB_HOSTS:
            return url, "Facebook"
    for item in sources:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.hostname and not parsed.hostname.endswith("viidad.ee"):
            return url, item.get("name", "Korraldaja")[:60]
    return row.get("url") or "", "Viidad"

def transform(row, today):
    if not isinstance(row, dict) or row.get("status") not in (None, "scheduled"):
        return None
    if row.get("category") not in ALLOWED:
        return None
    title = row.get("title")
    start = row.get("start_date")
    if not isinstance(title, str) or not title.strip() or not isinstance(start, str):
        return None
    end = row.get("end_date")
    # A recurring event spanning today is valid, but its start date must not
    # be presented as a new event today.
    if start < today and (not isinstance(end, str) or end < today):
        return None
    display_date = start if start >= today else today
    url, seller = source_url(row)
    if not url.startswith("https://"):
        return None
    time = row.get("time") or ""
    if not re.fullmatch(r"\d\d:\d\d", time):
        time = ""
    return {
        "id": "auto-" + str(abs(__import__("zlib").crc32((url + "|" + title + "|" + start).encode("utf-8")))),
        "title": title.strip()[:180],
        "date": display_date,
        "time": time,
        "venue": str(row.get("venue") or "Tallinn")[:150],
        "address": str(row.get("address") or "")[:180],
        "district": district(row.get("address"), row.get("venue")),
        "category": CATEGORIES.get(row.get("category"), "Muu"),
        "price": str(row.get("price") or "Hind teadmata")[:70],
        "url": url,
        "seller": seller,
        "age": "Kontrolli korraldajalt",
        "directTicket": False,
        "soldOut": False,
        "unverified": True,
    }

def save_json(path, contents):
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(contents, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)

def main():
    today = date.today()
    unique = {}
    success = 0
    for offset in range(DAYS):
        day = (today + timedelta(days=offset)).isoformat()
        try:
            payload = get_json(BASE + day + ".json")
            if not isinstance(payload.get("events"), list):
                raise ValueError("invalid events payload")
            success += 1
            for entry in payload["events"]:
                event = transform(entry, today.isoformat())
                if event is not None:
                    unique.setdefault(event["url"] + "|" + event["date"], event)
        except Exception as exc:
            print(f"Warning: cannot download {day}: {exc}", file=sys.stderr)
    if not success:
        print("No source requests succeeded; keeping last known data.", file=sys.stderr)
        return 1
    events = sorted(unique.values(), key=lambda e: (e["date"], e["time"], e["title"]))[:MAX_EVENTS]
    payload = {"updatedAt": datetime.now(timezone.utc).isoformat(), "source": "Viidad public Tallinn events listings", "events": events}
    save_json(DATA / "events.json", payload)
    facebook = [e for e in events if e["seller"] == "Facebook"]
    save_json(DATA / "facebook-events.json", {"updatedAt": payload["updatedAt"], "events": facebook})
    print(f"Saved {len(events)} Tallinn events, {len(facebook)} with original Facebook event URLs from source. Days fetched: {success}/{DAYS}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
