#!/usr/bin/env python3
"""
UEFA Country Ranking Scraper — v5
Source: football-coefficient.eu

CSS logic:
  el-btn--blue     = club active in Champions League
  el-btn--orange   = club active in Europa League or Conference League
  (no color class) = club active (ECL default)
  club-eliminate   = club ELIMINATED

FIX v5: country name from img alt (not get_text which returns empty)
NEW v5: scrapes fixtures + results to fixtures.json
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
    "Bosnia-Herzegovina":"🇧🇦","Latvia":"🇱🇻","Faroe Islands":"🇫🇴","Malta":"🇲🇹",
    "Liechtenstein":"🇱🇮","Estonia":"🇪🇪","Albania":"🇦🇱","North Macedonia":"🇲🇰",
    "Lithuania":"🇱🇹","Northern Ireland":"🇬🇧","Gibraltar":"🇬🇮","Andorra":"🇦🇩",
    "Luxembourg":"🇱🇺","Belarus":"🇧🇾","Montenegro":"🇲🇪","Georgia":"🇬🇪",
    "Wales":"🏴󠁧󠁢󠁷󠁬󠁳󠁿","San Marino":"🇸🇲",
}

CODES = {
    "England":"ENG","Spain":"ESP","Germany":"GER","Italy":"ITA","France":"FRA",
    "Portugal":"POR","Netherlands":"NED","Belgium":"BEL","Türkiye":"TUR","Turkey":"TUR",
    "Czechia":"CZE","Czech Republic":"CZE","Greece":"GRE","Poland":"POL","Denmark":"DEN",
    "Norway":"NOR","Cyprus":"CYP","Switzerland":"SUI","Austria":"AUT","Scotland":"SCO",
    "Sweden":"SWE","Croatia":"CRO","Israel":"ISR","Hungary":"HUN","Serbia":"SRB",
    "Romania":"ROU","Ukraine":"UKR","Slovenia":"SVN","Azerbaijan":"AZE","Slovakia":"SVK",
    "Bulgaria":"BUL","Ireland":"IRL","Russia":"RUS","Iceland":"ISL","Armenia":"ARM",
    "Moldova":"MDA","Finland":"FIN","Kosovo":"KOS","Kazakhstan":"KAZ",
    "Bosnia-Herzegovina":"BIH","Latvia":"LVA","Faroe Islands":"FRO","Malta":"MLT",
    "Liechtenstein":"LIE","Estonia":"EST","Albania":"ALB","North Macedonia":"MKD",
    "Lithuania":"LTU","Northern Ireland":"NIR","Gibraltar":"GIB","Andorra":"AND",
    "Luxembourg":"LUX","Belarus":"BLR","Montenegro":"MNE","Georgia":"GEO",
    "Wales":"WAL","San Marino":"SMR",
}


def safe_float(text: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(text).replace(",", ".")) or "0")
    except ValueError:
        return 0.0


def parse_club_cell(cell) -> list:
    """
    Parse clubs from last table column.
    CSS logic:
      el-btn--blue   -> active, CL
      el-btn--orange -> active, EL (or ECL by position)
      (neither)      -> active, ECL
      club-eliminate -> ELIMINATED (any color)
    
    Name = first child div, pts = last child div of el-btn--team.
    """
    clubs = []
    for link in cell.find_all("a"):
        inner_div = link.find("div", class_="el-btn--team")
        if not inner_div:
            continue
        classes = " ".join(inner_div.get("class", []))

        is_eliminated = "club-eliminate" in classes
        if "el-btn--blue" in classes:
            comp = "CL"
        elif "el-btn--orange" in classes:
            comp = "EL"
        else:
            comp = "ECL"

        pt_divs = inner_div.find_all("div", recursive=False)
        name = pt_divs[0].get_text(strip=True) if pt_divs else ""
        pts = safe_float(pt_divs[-1].get_text(strip=True)) if len(pt_divs) >= 2 else 0.0

        if not name:
            continue

        clubs.append({
            "name": name,
            "pts": pts,
            "active": not is_eliminated,
            "comp": comp,
        })
    return clubs


def load_prev_ranks(season: str) -> dict:
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


def parse_fc_eu(soup, season: str) -> dict | None:
    table = soup.find("table")
    if not table:
        log.warning("No table found")
        return None

    rows = table.find_all("tr")
    if len(rows) < 2:
        return None

    countries = []
    prev_ranks = load_prev_ranks(season)

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        try:
            rank = int(re.sub(r"\D", "", cells[0].get_text(strip=True)) or "0")
            if rank == 0:
                continue

            # v5 FIX: country name from img alt, not get_text (which returns empty)
            img = cells[1].find("img")
            if img and img.get("alt"):
                cname = img.get("alt").strip()
            else:
                cname = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', cells[1].get_text(strip=True)).strip()
            if not cname:
                continue

            bold = cells[2].find(["b", "strong"])
            total = safe_float((bold or cells[2]).get_text(strip=True))

            y1_raw = safe_float(cells[3].get_text(strip=True)) if len(cells) > 3 else 0.0

            clubs = []
            if len(cells) >= 6:
                clubs = parse_club_cell(cells[-1])

            clubs_total = len(clubs)
            y1 = y1_raw
            if y1 == 0 and clubs and clubs_total > 0:
                y1 = round(sum(c["pts"] for c in clubs) / clubs_total, 3)

            prev = prev_ranks.get(cname, {})
            countries.append({
                "rank": rank,
                "prev_rank": prev.get("rank", rank),
                "name": cname,
                "code": CODES.get(cname, cname[:3].upper()),
                "flag": FLAGS.get(cname, "🏳️"),
                "total": total,
                "y1": round(y1, 3),
                "y2": round(prev.get("y1", 0.0), 3),
                "y3": round(prev.get("y2", 0.0), 3),
                "y4": round(prev.get("y3", 0.0), 3),
                "y5": round(prev.get("y4", 0.0), 3),
                "clubs_total": clubs_total,
                "clubs_active": sum(1 for c in clubs if c["active"]),
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


def build_club_country_map(data: dict) -> dict:
    m = {}
    for c in data.get("countries", []):
        for cl in c.get("clubs", []):
            m[cl["name"]] = c["name"]
    return m


def get_flag(country: str) -> str:
    return FLAGS.get(country, "🏳️")


def scrape_fixtures(soup, club_country: dict) -> dict | None:
    """Parse upcoming matches + recent results from homepage."""
    def detect_comp(img_elem):
        if img_elem is None:
            return "CL"
        title = (img_elem.get("title", "") + img_elem.get("alt", "")).lower()
        if "champion" in title:
            return "CL"
        if "europa" in title:
            return "EL"
        if "conference" in title:
            return "ECL"
        return "CL"

    def parse_date(raw):
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", raw)
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""

    def parse_time(raw):
        m = re.search(r"(\d{2}):(\d{2})", raw)
        return f"{m.group(1)}:{m.group(2)}" if m else "TBD"

    def parse_round(img_elem):
        if not img_elem:
            return ""
        title = img_elem.get("title", "")
        for kw in ["Champions League", "Europa League", "Conference League"]:
            title = title.replace(kw, "")
        return title.strip("- ").strip() or ""

    upcoming, results = [], []
    sections = soup.select(".col-12.col-xl-6")

    for section in sections:
        table = section.find("table")
        if not table:
            continue
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            raw_date = cells[0].get_text(strip=True)
            date_str = parse_date(raw_date)
            time_str = parse_time(raw_date)
            comp_img = cells[1].find("img")
            comp = detect_comp(comp_img)
            round_text = parse_round(comp_img)

            home = cells[2].get_text(strip=True)
            away = cells[-1].get_text(strip=True)
            if not home or not away:
                continue

            mid_text = cells[3].get_text(strip=True) if len(cells) == 5 else ""
            is_score = bool(re.match(r"\d+[:\-]\d+", mid_text))

            entry = {
                "date": date_str,
                "time": time_str,
                "comp": comp,
                "round": round_text,
                "home": home,
                "homeFlag": get_flag(club_country.get(home, "")),
                "homeCountry": club_country.get(home, ""),
                "away": away,
                "awayFlag": get_flag(club_country.get(away, "")),
                "awayCountry": club_country.get(away, ""),
            }
            if is_score:
                entry["score"] = mid_text
                results.append(entry)
            else:
                entry["score"] = None
                upcoming.append(entry)

    if not upcoming and not results:
        return None

    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "upcoming": upcoming,
        "results": results,
    }


def scrape_football_coefficient(season: str):
    sid = season_to_id(season)
    current_sid = season_to_id(SEASONS[0])
    url = "https://www.football-coefficient.eu/" if sid == current_sid else \
          f"https://www.football-coefficient.eu/?idSeasonChoice={sid}"
    log.info(f"Fetching {season}: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Request failed: {e}")
        return None, None

    soup = BeautifulSoup(r.text, "lxml")
    ranking = parse_fc_eu(soup, season)

    # Also scrape fixtures for current season
    fixtures = None
    if sid == current_sid and ranking:
        club_country = build_club_country_map(ranking)
        fixtures = scrape_fixtures(soup, club_country)

    return ranking, fixtures


def scrape_season(season: str) -> bool:
    ranking, fixtures = scrape_football_coefficient(season)
    if not ranking or not ranking.get("countries"):
        log.error(f"No data scraped for {season}")
        return False

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"ranking_{season}.json"
    path.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"✅ {len(ranking['countries'])} countries → {path}")

    if fixtures:
        fpath = OUTPUT_DIR / "fixtures.json"
        fpath.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"✅ {len(fixtures['upcoming'])} upcoming + {len(fixtures['results'])} results → {fpath}")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default=SEASONS[0])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()

    if args.all:
        ok = 0
        for s in reversed(SEASONS):
            if scrape_season(s):
                ok += 1
            time.sleep(args.delay)
        log.info(f"Done: {ok}/{len(SEASONS)} seasons")
    else:
        sys.exit(0 if scrape_season(args.season) else 1)


if __name__ == "__main__":
    main()
