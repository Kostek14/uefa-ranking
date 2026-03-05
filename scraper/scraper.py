#!/usr/bin/env python3
"""
UEFA Country Ranking Scraper
============================
Fetches the UEFA country coefficient ranking from UEFA.com and generates
JSON files consumed by the static frontend.

Usage:
    python scraper.py                   # Scrape current season
    python scraper.py --season 2024-25  # Scrape specific season
    python scraper.py --all             # Scrape all available seasons

Output: ../data/ranking_{season}.json
"""

import json
import re
import sys
import time
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── CONFIG ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE_URL    = "https://www.uefa.com/nationalassociations/uefarankings/country/"
FALLBACK_URL = "https://www.footballseeding.com/uefa/country-ranking/{season}/"

SEASONS = [
    "2025-26","2024-25","2023-24","2022-23","2021-22","2020-21",
    "2019-20","2018-19","2017-18","2016-17","2015-16","2014-15",
    "2013-14","2012-13","2011-12","2010-11","2009-10","2008-09",
]

COUNTRY_FLAGS = {
    "Spain": "🇪🇸", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Germany": "🇩🇪", "France": "🇫🇷",
    "Portugal": "🇵🇹", "Italy": "🇮🇹", "Netherlands": "🇳🇱", "Belgium": "🇧🇪",
    "Austria": "🇦🇹", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Türkiye": "🇹🇷", "Turkey": "🇹🇷",
    "Czech Republic": "🇨🇿", "Switzerland": "🇨🇭", "Denmark": "🇩🇰",
    "Ukraine": "🇺🇦", "Croatia": "🇭🇷", "Greece": "🇬🇷", "Serbia": "🇷🇸",
    "Russia": "🇷🇺", "Norway": "🇳🇴", "Sweden": "🇸🇪", "Poland": "🇵🇱",
    "Romania": "🇷🇴", "Hungary": "🇭🇺", "Israel": "🇮🇱", "Cyprus": "🇨🇾",
    "Bulgaria": "🇧🇬", "Slovakia": "🇸🇰", "Albania": "🇦🇱", "Slovenia": "🇸🇮",
    "Finland": "🇫🇮", "Azerbaijan": "🇦🇿", "Kazakhstan": "🇰🇿", "Belarus": "🇧🇾",
    "Iceland": "🇮🇸", "Bosnia and Herzegovina": "🇧🇦", "North Macedonia": "🇲🇰",
    "Kosovo": "🇽🇰", "Moldova": "🇲🇩", "Georgia": "🇬🇪", "Armenia": "🇦🇲",
    "Latvia": "🇱🇻", "Lithuania": "🇱🇹", "Estonia": "🇪🇪", "Montenegro": "🇲🇪",
    "Luxembourg": "🇱🇺", "Malta": "🇲🇹", "Faroe Islands": "🇫🇴",
    "Gibraltar": "🇬🇮", "Liechtenstein": "🇱🇮", "Andorra": "🇦🇩",
    "San Marino": "🇸🇲",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_DIR = Path(__file__).parent.parent / "data"


# ─── SCRAPER ──────────────────────────────────────────────────────────────────

def fetch_from_uefa(season: str) -> dict | None:
    """Try to fetch ranking data from UEFA.com official rankings page."""
    url = BASE_URL
    log.info(f"Fetching from UEFA.com: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return parse_uefa_page(r.text, season)
    except Exception as e:
        log.warning(f"UEFA.com fetch failed: {e}")
        return None


def fetch_from_footballseeding(season: str) -> dict | None:
    """Fallback: scrape footballseeding.com (now mostly static data)."""
    url = FALLBACK_URL.format(season=season)
    log.info(f"Fetching from footballseeding: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return parse_footballseeding_page(r.text, season)
    except Exception as e:
        log.warning(f"footballseeding fetch failed: {e}")
        return None


def parse_uefa_page(html: str, season: str) -> dict | None:
    """Parse UEFA.com country rankings page."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr") or soup.select(".ranking-table tr")

    if not rows:
        log.warning("No rows found on UEFA.com page")
        return None

    countries = []
    for i, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue
        try:
            text = [c.get_text(strip=True) for c in cells]
            rank = int(re.sub(r"\D", "", text[0]) or str(i + 1))
            name = text[1] if len(text) > 1 else "Unknown"
            total = float(text[2].replace(",", ".")) if len(text) > 2 else 0.0
            countries.append({
                "rank": rank,
                "prev_rank": rank,  # prev_rank requires historical data
                "name": name,
                "code": name[:3].upper(),
                "flag": COUNTRY_FLAGS.get(name, "🏳️"),
                "total": total,
                "y1": float(text[3].replace(",", ".")) if len(text) > 3 else 0.0,
                "y2": float(text[4].replace(",", ".")) if len(text) > 4 else 0.0,
                "y3": float(text[5].replace(",", ".")) if len(text) > 5 else 0.0,
                "y4": float(text[6].replace(",", ".")) if len(text) > 6 else 0.0,
                "y5": float(text[7].replace(",", ".")) if len(text) > 7 else 0.0,
                "clubs": 0,
                "active_clubs": 0,
                "competitions": [],
            })
        except (ValueError, IndexError) as e:
            log.debug(f"Skipping row {i}: {e}")
            continue

    if not countries:
        return None

    return build_output(countries, season)


def parse_footballseeding_page(html: str, season: str) -> dict | None:
    """Parse footballseeding.com country ranking page."""
    soup = BeautifulSoup(html, "html.parser")

    # footballseeding loads table via JS — look for embedded JSON
    scripts = soup.find_all("script")
    for script in scripts:
        src = script.string or ""
        # look for JSON data patterns
        m = re.search(r'var\s+rankingData\s*=\s*(\[.*?\]);', src, re.DOTALL)
        if not m:
            m = re.search(r'rankingData\s*=\s*(\[.*?\])', src, re.DOTALL)
        if m:
            try:
                raw = json.loads(m.group(1))
                return transform_raw(raw, season)
            except json.JSONDecodeError:
                pass

    # Fallback: parse visible table
    table = soup.find("table")
    if not table:
        log.warning("No table found on footballseeding page")
        return None

    rows = table.find_all("tr")[1:]  # skip header
    countries = []
    for i, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        try:
            text = [c.get_text(strip=True) for c in cells]
            rank_str = re.sub(r"\D", "", text[0])
            if not rank_str:
                continue
            rank = int(rank_str)
            name = cells[3].get_text(strip=True) if len(cells) > 3 else "Unknown"
            total_str = text[4] if len(text) > 4 else "0"
            total = float(total_str.replace(",", ".").replace(" ", "") or "0")
            countries.append({
                "rank": rank,
                "prev_rank": rank,
                "name": name,
                "code": name[:3].upper(),
                "flag": COUNTRY_FLAGS.get(name, "🏳️"),
                "total": total,
                "y1": safe_float(text, 5),
                "y2": safe_float(text, 6),
                "y3": safe_float(text, 7),
                "y4": safe_float(text, 8),
                "y5": safe_float(text, 9),
                "clubs": 0,
                "active_clubs": 0,
                "competitions": [],
            })
        except Exception as e:
            log.debug(f"Row {i} parse error: {e}")
            continue

    if not countries:
        return None

    return build_output(countries, season)


def safe_float(lst: list, idx: int) -> float:
    try:
        return float(lst[idx].replace(",", ".").replace(" ", "") or "0")
    except (IndexError, ValueError):
        return 0.0


def transform_raw(raw: list, season: str) -> dict:
    """Transform raw JSON from embedded scripts."""
    countries = []
    for i, item in enumerate(raw):
        countries.append({
            "rank": i + 1,
            "prev_rank": item.get("prev_rank", i + 1),
            "name": item.get("country", item.get("name", "Unknown")),
            "code": item.get("code", "???"),
            "flag": COUNTRY_FLAGS.get(item.get("country", ""), "🏳️"),
            "total": float(item.get("total", item.get("points", 0))),
            "y1": float(item.get("y1", item.get("year1", 0))),
            "y2": float(item.get("y2", item.get("year2", 0))),
            "y3": float(item.get("y3", item.get("year3", 0))),
            "y4": float(item.get("y4", item.get("year4", 0))),
            "y5": float(item.get("y5", item.get("year5", 0))),
            "clubs": int(item.get("clubs", 0)),
            "active_clubs": int(item.get("active_clubs", 0)),
            "competitions": item.get("competitions", []),
        })
    return build_output(countries, season)


def build_output(countries: list, season: str) -> dict:
    return {
        "season": season,
        "updated": datetime.now(timezone.utc).isoformat(),
        "countries": sorted(countries, key=lambda x: x["rank"]),
        "zone_thresholds": {
            "cl_direct": 4,
            "cl_qual": 10,
            "el_direct": 6,
            "el_qual": 15,
            "ecl_qual": 55,
        },
    }


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def scrape_season(season: str) -> bool:
    log.info(f"Scraping season: {season}")

    data = fetch_from_uefa(season)
    if not data or not data.get("countries"):
        log.info("UEFA.com returned no data, trying fallback…")
        data = fetch_from_footballseeding(season)

    if not data or not data.get("countries"):
        log.error(f"Could not scrape data for {season}")
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"ranking_{season}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"✅ Saved {len(data['countries'])} countries → {out_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="UEFA Country Ranking Scraper")
    parser.add_argument("--season", default=SEASONS[0], help="Season to scrape (e.g. 2025-26)")
    parser.add_argument("--all", action="store_true", help="Scrape all seasons")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between requests (s)")
    args = parser.parse_args()

    if args.all:
        ok = 0
        for s in SEASONS:
            if scrape_season(s):
                ok += 1
            time.sleep(args.delay)
        log.info(f"Done: {ok}/{len(SEASONS)} seasons scraped")
    else:
        success = scrape_season(args.season)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
