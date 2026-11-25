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
DAYS = 30
MAX_EVENTS = 400
ALLOWED = {"nightlife", "music"}
CATEGORIES = {"nightlife": "Ööklubi", "music": "Kontsert"}
DJ_WORDS = ("dj ", "dj-", "dj:", " dj", "disc jockey", "rave", "techno", "house night", "drum & bass", "dnb", "diskor")
FESTIVAL_WORDS = ("festival", "fest", "õllesummer", "jazzkaar", "tallinn music week")
EXCLUDE_WORDS = ("muuseum", "museum", "näitus", "exhibition", "töötuba", "workshop", "koolitus", "seminar", "konverents", "conference", "kodanikunädal", "loeng", "lecture", "ekskursioon", "tour", "kino", "cinema", "film screening", "jooga", "yoga", "teenistus", "jumalateenistus")
# Keep the feed focused on actual evening entertainment, not museum / civic listings.
BLOCKED_VENUES = (
    "kumu", "kunstimuuseum", "muuseum", "museum", "kirik",
    "kogudus", "synagogue", "sünagoog", "raamatukogu",
    "muusika- ja balletikool", "muba", "muusika- ja teatriakadeemia",
    "kool", "university", "ülikool", "galerii", "gallery",
    "kadrioru loss", "niguliste", "toomkirik", "hopneri maja",
    "raekoda", "kunstikeskus", "parkla"
)
BLOCKED_TITLES = (
    "jõulukontsert", "jõululaat", "jõuluturg", "koorikontsert",
    "heategevus", "koolikontsert", "gala-show", "kammersaal",
    "klassikaline", "kammerkoor", "harfi helirännak",
    "gong", "helirännak", "heliseanss", "meditatsioon",
    "helilõdvestus", "kontsertrännak", "pilates",
    "cuddle party", "birthday party @ morii", "jazz pesulad",
    "ekskursioon", "ühisaerutamine", "muusikaajaloo",
    "vilistlaste kokkutulek", "drum art school", "kodanikunädal",
    "näitus", "muuseum", "museum", "workshop", "töötuba",
    "etendus", "teatraliseeritud", "театрализованное",
    "performance art", "sünnipäevakontsert", "advent",
    "jõulugala", "õpilaskontsert", "õpilaste kontsert",
)
NIGHTLIFE_WORDS = (
    "party", "pidu", "klubi", "club", "night", "rave", "disco",
    "dj", "live", "festival", "fest", "techno", "house",
    "dance", "tants", "after", "metal", "rock", "jazz",
    "album", "kontsert", "concert", "karaoke", "dnb",
    "drum & bass", "hip-hop", "indie", "electronic"
)

def nightlife_relevant(row):
    title = str(row.get("title") or "").casefold()
    venue = str(row.get("venue") or "").casefold()
    if any(word in venue for word in BLOCKED_VENUES):
        return False
    if any(word in title for word in BLOCKED_TITLES):
        return False
    time = str(row.get("time") or "")
    if re.fullmatch(r"\d{2}:\d{2}", time) and time < "17:00":
        return False
    if row.get("category") == "nightlife":
        return True
    return row.get("category") == "music" and (
        any(word in title for word in NIGHTLIFE_WORDS)
        or any(word in venue for word in (
            "hall", "helitehas", "paavli", "uus laine",
            "terminal", "veino", "von krahli", "pub",
            "bar", "kultuurikatel", "tap­per", "saar cult"
        ))
    )

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
    if row.get("category") not in ALLOWED or not nightlife_relevant(row):
        return None
    title = row.get("title")
    start = row.get("start_date")
    if not isinstance(title, str) or not title.strip() or not isinstance(start, str):
        return None
    title_low = title.casefold()
    if any(word in title_low for word in EXCLUDE_WORDS):
        return None
    if any(word in title_low for word in FESTIVAL_WORDS):
        category = "Festival"
    elif any(word in title_low for word in DJ_WORDS):
        category = "DJ-õhtu"
    else:
        category = CATEGORIES[row["category"]]
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
        "id": 1000000 + (__import__("zlib").crc32((url + "|" + title + "|" + start).encode("utf-8")) & 0xffffffff),
        "title": title.strip()[:180],
        "date": display_date,
        "time": time,
        "venue": str(row.get("venue") or "Tallinn")[:150],
        "address": str(row.get("address") or "")[:180],
        "district": district(row.get("address"), row.get("venue")),
        "category": category,
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
    today = datetime.now(__import__('zoneinfo').ZoneInfo('Europe/Tallinn')).date()
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
