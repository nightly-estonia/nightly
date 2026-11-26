#!/usr/bin/env python3
"""Refresh NIGHTLY public Tallinn events from public feeds and optional Apify.

Sources: Viidad Tallinn JSON directory and SKENE.INFO public events JSON feed.
Facebook labels are used ONLY for an original Facebook event URL from the source.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
BASE = "https://viidad.ee/tallinn/events/day/"
SKENE_FEED = "https://www.skene.info/feed/events.json"
DAYS = 30
MAX_EVENTS = 400
ALLOWED = {"nightlife", "music", "theatre", "other", "festival"}
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
    explicit_dj = any(word in title for word in ("dj ", "dj-", "dj:", "dj-set", "dj set", "rave", "techno", "club night", "klubiöö", "disco", "drum & bass", "dnb"))
    if explicit_dj:
        return True
    if row.get("category") == "nightlife":
        return True
    return row.get("category") in {"music", "festival"} and (
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
        category = CATEGORIES.get(row["category"], "DJ-õhtu")
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

def skene_facebook_events(today):
    """Import public SKENE.INFO Tallinn listings with original Facebook event links.

    SKENE.INFO is an independent, curated public feed, not Facebook's own API.
    Keep its attribution and original event URL. Never invent missing fields.
    """
    payload = get_json(SKENE_FEED)
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("invalid SKENE.INFO entries payload")
    found = []
    end = (date.fromisoformat(today) + timedelta(days=DAYS)).isoformat()
    for row in entries:
        if not isinstance(row, dict) or row.get("tba"):
            continue
        event_date = str(row.get("d") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date) or not today <= event_date < end:
            continue
        city = " ".join(str(row.get(k) or "") for k in ("c", "linn")).casefold()
        if "tallinn" not in city:
            continue
        kind = str(row.get("t") or "").casefold()
        if kind not in {"kontsert", "festival", "klubi"}:
            continue
        title = str(row.get("n") or "").strip()
        venue = str(row.get("v") or "").strip()
        if not title or any(word in title.casefold() for word in EXCLUDE_WORDS):
            continue
        # Both source and organiser links are documented by SKENE.INFO.
        facebook_url = ""
        for key in ("ou", "su"):
            candidate = str(row.get(key) or "")
            parsed = urlparse(candidate)
            if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() in FB_HOSTS:
                facebook_url = candidate
                break
        if not facebook_url:
            continue
        category = ("Festival" if kind == "festival" else
                    "DJ-õhtu" if any(word in title.casefold() for word in DJ_WORDS) else
                    "Ööklubi" if kind == "klubi" else "Kontsert")
        entry = {
            "id": 2000000000 + (__import__("zlib").crc32((facebook_url + "|" + event_date).encode("utf-8")) & 0xffffffff),
            "title": title[:180], "date": event_date, "time": "",
            "venue": venue[:150] or "Tallinn", "address": "",
            "district": district("", venue), "category": category,
            "price": "Kontrolli korraldajalt",
            "url": facebook_url, "seller": "Facebook",
            "source": "SKENE.INFO", "sourceUrl": "https://klubi.skene.info/",
            "age": "Kontrolli korraldajalt", "directTicket": False,
            "soldOut": False, "unverified": True,
        }
        if nightlife_relevant({"title": title, "venue": venue, "category": "nightlife" if kind == "klubi" else "music", "time": ""}):
            found.append(entry)
    return found

def apify_facebook_events(today):
    """Fetch directly from public Facebook Events via Apify, with a hard per-run cap.

    Only called when APIFY_TOKEN exists. Each call processes up to 20 paid items
    with a configured charge ceiling of USD 0.04 per scheduled run.
    The public Apify actor is independent of Facebook.
    """
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        print("Apify skipped: APIFY_TOKEN GitHub secret not configured.")
        return [], False

    actor = "dami_studio~facebook-events-scraper"
    url = ("https://api.apify.com/v2/acts/" + actor +
           "/run-sync-get-dataset-items?maxItems=20&maxTotalChargeUsd=0.04&timeout=120")
    settings = {
        "searchTerms": ["nightclub", "DJ", "concert", "party"],
        "location": "Tallinn",
        "maxEvents": 20,
        "startingFrom": today,
        "startingBefore": (date.fromisoformat(today) + timedelta(days=DAYS)).isoformat(),
    }
    request = urllib.request.Request(
        url, data=json.dumps(settings).encode("utf-8"), method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "NIGHTLY-events/1.1",
        })
    with urllib.request.urlopen(request, timeout=160) as response:
        entries = json.load(response)
    if not isinstance(entries, list):
        raise ValueError("Apify returned no completed dataset; preserving previous Facebook entries.")

    local_tz = ZoneInfo("Europe/Tallinn")
    end = (date.fromisoformat(today) + timedelta(days=DAYS)).isoformat()
    events = []
    for row in entries:
        if not isinstance(row, dict) or row.get("ok") is False:
            continue
        if row.get("_sample") or row.get("_diagnostic") or row.get("recordType") not in (None, "event"):
            continue
        if row.get("isCanceled") or row.get("isPast") or row.get("isOnline"):
            continue
        original_url = str(row.get("eventUrl") or "")
        parsed = urlparse(original_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in FB_HOSTS:
            continue
        title = str(row.get("name") or "").strip()
        venue = str(row.get("venueName") or "Tallinn").strip()
        address = str(row.get("venueAddress") or "").strip()
        city = str(row.get("venueCity") or "").strip()
        # Search location is Tallinn; reject events explicitly listed in other cities.
        if city and "tallinn" not in city.casefold():
            continue
        if not title or any(word in title.casefold() for word in EXCLUDE_WORDS + BLOCKED_TITLES):
            continue
        if any(word in venue.casefold() for word in BLOCKED_VENUES):
            continue
        try:
            start = str(row.get("startTime") or "")
            if not start:
                continue
            start_local = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if start_local.tzinfo is None:
                continue
            start_local = start_local.astimezone(local_tz)
        except (ValueError, TypeError):
            continue
        event_date = start_local.date().isoformat()
        if event_date < today or event_date >= end:
            continue
        time = start_local.strftime("%H:%M")
        words = title.casefold() + " " + str(row.get("description") or "")[:300].casefold()
        cats = " ".join(
            c.get("label", "") if isinstance(c, dict) else str(c)
            for c in (row.get("categories") or []) if isinstance(c, (dict, str))
        ).casefold()
        is_dj = any(w in words for w in DJ_WORDS)
        is_festival = any(w in words for w in FESTIVAL_WORDS)
        is_club = any(w in words for w in ("klubi", "club", "nightclub", "party", "pidu", "rave"))
        is_music = any(w in words or w in cats for w in NIGHTLIFE_WORDS)
        if not (is_dj or is_club or is_music or is_festival):
            continue
        if time < "17:00" and not is_festival:
            continue
        category = ("Festival" if is_festival else
                    "DJ-õhtu" if is_dj else "Ööklubi" if is_club else "Kontsert")
        event_id = 3000000000 + (__import__("zlib").crc32((original_url + event_date).encode("utf-8")) & 0xffffffff)
        events.append({
            "id": event_id, "title": title[:180], "date": event_date,
            "time": time, "venue": venue[:150], "address": address[:180],
            "district": district(address, venue), "category": category,
            "price": str(row.get("priceRange") or "Kontrolli korraldajalt")[:70],
            "url": original_url, "seller": "Facebook",
            "source": "Apify public Facebook Events",
            "age": "Kontrolli korraldajalt", "directTicket": False,
            "soldOut": False, "unverified": True,
        })
    print(f"Apify public Facebook Events: received {len(entries)} rows, {len(events)} Tallinn nightlife events.")
    return events, True

def save_json(path, contents):
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(contents, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)

def main():
    today = datetime.now(__import__('zoneinfo').ZoneInfo('Europe/Tallinn')).date()
    unique = {}
    curated_path = DATA / "verified-dj-events.json"
    if curated_path.exists():
        for entry in json.loads(curated_path.read_text(encoding="utf-8")).get("events", []):
            if (isinstance(entry, dict) and entry.get("date", "") >= today.isoformat()
                and entry.get("category") in {"DJ-õhtu", "Ööklubi", "Festival", "Kontsert"}
                and isinstance(entry.get("url"), str) and entry["url"].startswith("https://")):
                unique[entry["url"] + "|" + entry["date"]] = entry
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
    # Include Facebook-origin events discovered in SKENE.INFO's public feed.
    # A temporary source outage must never delete previously imported Viidad events.
    skene_count = 0
    try:
        for event in skene_facebook_events(today.isoformat()):
            unique.setdefault(event["url"] + "|" + event["date"], event)
            skene_count += 1
    except Exception as exc:
        print(f"Warning: SKENE.INFO Facebook feed unavailable: {exc}", file=sys.stderr)
    # Apify runs at the same two daily times as the existing importer.
    # Preserve last-known Facebook listings on upstream failure.
    apify_added = 0
    apify_success = False
    try:
        apify_events, apify_success = apify_facebook_events(today.isoformat())
        known = {(re.sub(r"\\W+", "", e.get("title", "").casefold()),
                  e.get("date", ""), re.sub(r"\\W+", "", e.get("venue", "").casefold()))
                 for e in unique.values()}
        for event in apify_events:
            identity = (re.sub(r"\\W+", "", event["title"].casefold()),
                        event["date"], re.sub(r"\\W+", "", event["venue"].casefold()))
            if identity in known:
                continue
            known.add(identity)
            unique.setdefault(event["url"] + "|" + event["date"], event)
            apify_added += 1
    except Exception as exc:
        print(f"Warning: Apify Facebook import failed: {exc}", file=sys.stderr)
    if not apify_success:
        old_fb_file = DATA / "facebook-events.json"
        if old_fb_file.exists():
            try:
                previous = json.loads(old_fb_file.read_text(encoding="utf-8")).get("events", [])
                for event in previous:
                    if (isinstance(event, dict) and event.get("date", "") >= today.isoformat()
                        and event.get("source") == "Apify public Facebook Events"):
                        unique.setdefault(event["url"] + "|" + event["date"], event)
            except Exception as exc:
                print(f"Warning: cannot recover last Apify events: {exc}", file=sys.stderr)
    if not success and not unique:
        print("No source requests succeeded; keeping last known data.", file=sys.stderr)
        return 1
    events = sorted(unique.values(), key=lambda e: (e["date"], e["time"], e["title"]))[:MAX_EVENTS]
    payload = {"updatedAt": datetime.now(timezone.utc).isoformat(), "source": "Viidad + SKENE.INFO + Apify Facebook public Tallinn event listings", "events": events}
    save_json(DATA / "events.json", payload)
    facebook = [e for e in events if e["seller"] == "Facebook"]
    save_json(DATA / "facebook-events.json", {"updatedAt": payload["updatedAt"], "events": facebook})
    print(f"Saved {len(events)} Tallinn events, {len(facebook)} with original Facebook event URLs (SKENE.INFO imported: {skene_count}, Apify imported: {apify_added}). Days fetched: {success}/{DAYS}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
