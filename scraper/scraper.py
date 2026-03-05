#!/usr/bin/env python3
"""
UEFA Country Ranking Scraper — v2
Source principale : football-coefficient.eu (données fiables, toutes saisons)
Source secours   : kassiesa.net
"""

import json, re, sys, time, argparse, logging
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"

SEASONS = [
    "2025-26","2024-25","2023-24","2022-23","2021-22","2020-21",
    "2019-20","2018-19","2017-18","2016-17","2015-16","2014-15",
    "2013-14","2012-13","2011-12","2010-11","2009-10","2008-09",
]

# Map season "2025-26" → idSeasonChoice param for football-coefficient.eu
# The site uses the END year as parameter (2026 for 2025-26)
def season_to_id(season):
    return int(season.split("-")[0]) + 1

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

FLAGS = {
    "England":"🏴󠁧󠁢󠁥󠁮󠁧󠁿","Spain":"🇪🇸","Germany":"🇩🇪","Italy":"🇮🇹","France":"🇫🇷",
    "Portugal":"🇵🇹","Netherlands":"🇳🇱","Belgium":"🇧🇪","Türkiye":"🇹🇷","Turkey":"🇹🇷",
    "Czechia":"🇨🇿","Czech Republic":"🇨🇿","Greece":"🇬🇷","Poland":"🇵🇱","Denmark":"🇩🇰",
    "Norway":"🇳🇴","Cyprus":"🇨🇾","Switzerland":"🇨🇭","Austria":"🇦🇹","Scotland":"🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Sweden":"🇸🇪","Croatia":"🇭🇷","Israel":"🇮🇱","Hungary":"🇭🇺","Serbia":"🇷🇸",
    "Romania":"🇷🇴","Ukraine":"🇺🇦","Slovenia":"🇸🇮","Azerbaijan":"🇦🇿","Slovakia":"🇸🇰",
    "Bulgaria":"🇧🇬","Ireland":"🇮🇪","Russia":"🇷🇺","Iceland":"🇮🇸","Armenia":"🇦🇲",
    "Moldova":"🇲🇩","Finland":"🇫🇮","Kosovo":"🇽🇰","Kazakhstan":"🇰🇿",
    "Bosnia-Herzegovina":"🇧🇦","Bosnia-Herz.":"🇧🇦","Latvia":"🇱🇻","Faroe Islands":"🇫🇴",
    "Malta":"🇲🇹","Liechtenstein":"🇱🇮","Estonia":"🇪🇪","Albania":"🇦🇱",
    "North Macedonia":"🇲🇰","Lithuania":"🇱🇹","Northern Ireland":"🇬🇧","Gibraltar":"🇬🇮",
    "Andorra":"🇦🇩","Luxembourg":"🇱🇺","Belarus":"🇧🇾","Montenegro":"🇲🇪",
    "Georgia":"🇬🇪","Wales":"🏴󠁧󠁢󠁷󠁬󠁳󠁿","San Marino":"🇸🇲",
}


# ── SCRAPER FOOTBALL-COEFFICIENT.EU ──────────────────────────────────────────

def scrape_football_coefficient(season: str) -> dict | None:
    sid = season_to_id(season)
    # Current season has no param, older seasons need idSeasonChoice
    if sid == season_to_id(SEASONS[0]):
        url = "https://www.football-coefficient.eu/"
    else:
        url = f"https://www.football-coefficient.eu/?idSeasonChoice={sid}"

    log.info(f"Fetching football-coefficient.eu for {season}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Request failed: {e}")
        return None

    soup = BeautifulSoup(r.text, "lxml")
    return parse_fc_eu(soup, season)


def parse_fc_eu(soup, season: str) -> dict | None:
    """
    Parse the main ranking table from football-coefficient.eu
    Table has columns: rank, country, total (NR), CL pts, NC (clubs), CS (club total pts), club list
    """
    table = soup.find("table")
    if not table:
        log.warning("No table found")
        return None

    rows = table.find_all("tr")
    if len(rows) < 2:
        log.warning("Table has no data rows")
        return None

    countries = []

    # Try to get previous rankings for change calculation
    # We'll look for a prev_rank from last saved file
    prev_ranks = load_prev_ranks(season)

    for row in rows[1:]:  # skip header
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue

        try:
            # Col 0: rank
            rank_text = cells[0].get_text(strip=True)
            rank = int(re.sub(r"\D", "", rank_text) or "0")
            if rank == 0:
                continue

            # Col 1: country name (may include flag image, link text)
            country_cell = cells[1]
            cname = country_cell.get_text(strip=True)
            # Clean up — remove trailing country code in parens
            cname = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', cname).strip()
            if not cname:
                continue

            # Col 2: NR = total coefficient
            total_text = cells[2].get_text(strip=True).replace(",", ".")
            # Bold text inside
            bold = cells[2].find("b") or cells[2].find("strong")
            if bold:
                total_text = bold.get_text(strip=True).replace(",", ".")
            total = safe_float(total_text)

            # Col 3: CL coefficient this season (current year)
            y1 = safe_float(cells[3].get_text(strip=True).replace(",", ".")) if len(cells) > 3 else 0.0

            # Col 4: NC = clubs entered + active
            clubs_total, clubs_active = 0, 0
            if len(cells) > 4:
                nc_text = cells[4].get_text(strip=True)
                # Format is usually "active+total" or "W+L+D" for competitions
                nc_match = re.findall(r'\d+', nc_text)
                if nc_match:
                    # Sum the numbers like "6+2+1" = 9 clubs
                    clubs_total = sum(int(x) for x in nc_match)

            # Col 6 (or last): Club list with names and points
            clubs = []
            club_cell = cells[-1] if len(cells) >= 6 else None
            if club_cell:
                clubs = parse_club_cell(club_cell)
                if clubs:
                    clubs_total = max(clubs_total, len(clubs))
                    clubs_active = sum(1 for c in clubs if c["active"])

            # Calculate y1 from clubs if available
            if clubs and clubs_total > 0:
                total_pts = sum(c["pts"] for c in clubs)
                y1_calc = total_pts / clubs_total
                if y1 == 0:
                    y1 = round(y1_calc, 3)

            # Previous year coefficients — we don't have them directly from this page
            # Try to read from previously saved data for this season
            prev = prev_ranks.get(cname, {})
            y2 = prev.get("y1", 0.0)  # last season's y1 becomes this season's y2
            y3 = prev.get("y2", 0.0)
            y4 = prev.get("y3", 0.0)
            y5 = prev.get("y4", 0.0)

            # If we have total and y1, but not historical, try to estimate from total
            # total = y1 + y2 + y3 + y4 + y5
            # If we have no history, show 0s (will fill on next scrape iteration)

            countries.append({
                "rank": rank,
                "prev_rank": prev_ranks.get(cname, {}).get("rank", rank),
                "name": cname,
                "code": country_name_to_code(cname),
                "flag": FLAGS.get(cname, "🏳️"),
                "total": total,
                "y1": round(y1, 3),
                "y2": round(y2, 3),
                "y3": round(y3, 3),
                "y4": round(y4, 3),
                "y5": round(y5, 3),
                "clubs_total": clubs_total,
                "clubs_active": clubs_active,
                "clubs": clubs,
            })

        except Exception as e:
            log.debug(f"Row parse error: {e}")
            continue

    if not countries:
        return None

    return {
        "season": season,
        "updated": datetime.now(timezone.utc).isoformat(),
        "countries": sorted(countries, key=lambda x: x["rank"]),
        "zone_thresholds": {"cl_direct":4,"cl_qual":10,"el_direct":6,"el_qual":15,"ecl_qual":55},
    }


def parse_club_cell(cell) -> list:
    """
    Parse the club list cell from football-coefficient.eu.
    Format: "Club Name  pts" repeated, with links or spans.
    """
    clubs = []
    text = cell.get_text(separator="\n", strip=True)
    links = cell.find_all("a")

    # Determine competition context from cell or parent row class/color
    # football-coefficient.eu uses different cell backgrounds for CL/EL/ECL
    # or we infer from points and context

    for link in links:
        club_text = link.get_text(strip=True)
        # Points are usually in the text following the link
        # Pattern: "Arsenal  29.5" or similar
        if not club_text:
            continue

        # Try to find the pts sibling text
        pts = 0.0
        next_sib = link.next_sibling
        if next_sib:
            pts_match = re.search(r'([\d.,]+)', str(next_sib))
            if pts_match:
                pts = safe_float(pts_match.group(1))

        # Check if club is active — football-coefficient shows active clubs in color
        # We'll mark all as active initially and let periodic re-scrape correct
        comp = "ECL"  # default, will be refined below

        clubs.append({
            "name": club_text,
            "pts": pts,
            "active": pts > 0,  # rough proxy: if has pts, likely entered
            "comp": comp,
        })

    # Fallback: parse raw text if no links
    if not clubs:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        for line in lines:
            m = re.match(r'^(.+?)\s+([\d.]+)\s*$', line)
            if m:
                clubs.append({"name": m.group(1), "pts": safe_float(m.group(2)), "active": True, "comp": "ECL"})

    return clubs


def country_name_to_code(name: str) -> str:
    codes = {
        "England":"ENG","Spain":"ESP","Germany":"GER","Italy":"ITA","France":"FRA",
        "Portugal":"POR","Netherlands":"NED","Belgium":"BEL","Türkiye":"TUR","Turkey":"TUR",
        "Czechia":"CZE","Czech Republic":"CZE","Greece":"GRE","Poland":"POL","Denmark":"DEN",
        "Norway":"NOR","Cyprus":"CYP","Switzerland":"SUI","Austria":"AUT","Scotland":"SCO",
        "Sweden":"SWE","Croatia":"CRO","Israel":"ISR","Hungary":"HUN","Serbia":"SRB",
        "Romania":"ROU","Ukraine":"UKR","Slovenia":"SVN","Azerbaijan":"AZE","Slovakia":"SVK",
        "Bulgaria":"BUL","Ireland":"IRL","Russia":"RUS","Iceland":"ISL","Armenia":"ARM",
        "Moldova":"MDA","Finland":"FIN","Kosovo":"KOS","Kazakhstan":"KAZ",
        "Bosnia-Herzegovina":"BIH","Bosnia-Herz.":"BIH","Latvia":"LVA","Faroe Islands":"FRO",
        "Malta":"MLT","Liechtenstein":"LIE","Estonia":"EST","Albania":"ALB",
        "North Macedonia":"MKD","Lithuania":"LTU","Northern Ireland":"NIR","Gibraltar":"GIB",
        "Andorra":"AND","Luxembourg":"LUX","Belarus":"BLR","Montenegro":"MNE",
        "Georgia":"GEO","Wales":"WAL","San Marino":"SMR",
    }
    return codes.get(name, name[:3].upper())


def safe_float(text: str) -> float:
    try:
        return float(re.sub(r"[^\d.,]", "", str(text)).replace(",", ".") or "0")
    except ValueError:
        return 0.0


def load_prev_ranks(season: str) -> dict:
    """Load previous season data to compute year-over-year changes."""
    parts = season.split("-")
    start = int(parts[0])
    prev_season = f"{start-1}-{str(start)[-2:]}"
    path = OUTPUT_DIR / f"ranking_{prev_season}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {c["name"]: c for c in data.get("countries", [])}
    except Exception:
        return {}


# ── MAIN ────────────────────────────────────────────────────────────────────

def scrape_season(season: str) -> bool:
    data = scrape_football_coefficient(season)
    if not data or not data.get("countries"):
        log.error(f"No data scraped for {season}")
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"ranking_{season}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"✅ {len(data['countries'])} countries → {path}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=SEASONS[0])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    if args.all:
        # Scrape oldest first so historical data is available for change calculation
        ok = 0
        for s in reversed(SEASONS):
            if scrape_season(s):
                ok += 1
            time.sleep(args.delay)
        log.info(f"Done: {ok}/{len(SEASONS)}")
    else:
        sys.exit(0 if scrape_season(args.season) else 1)


if __name__ == "__main__":
    main()
