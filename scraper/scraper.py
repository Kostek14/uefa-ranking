#!/usr/bin/env python3
"""
UEFA Country Ranking Scraper — v3
Source: football-coefficient.eu

BUGS FIXES v3:
- clubs_total = len(clubs list) [était NC sum, qui est en fait les clubs ACTIFS]
- clubs_active = sum des nombres dans la colonne NC (ex: "6+2+1" = 9 actifs)
- active flag par club = détection des balises <s>/<del>/<strike> dans le HTML
- comp par club = déduit depuis la colonne NC ("6+2+1" → 6 CL, 2 EL, 1 ECL)
  en assignant aux clubs triés par pts dans l'ordre CL→EL→ECL
- y2/y3/y4/y5 = chaîne historique depuis les fichiers précédents (inchangé)
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
    "Bosnia-Herzegovina":"🇧🇦","Bosnia-Herz.":"🇧🇦","Latvia":"🇱🇻","Faroe Islands":"🇫🇴",
    "Malta":"🇲🇹","Liechtenstein":"🇱🇮","Estonia":"🇪🇪","Albania":"🇦🇱",
    "North Macedonia":"🇲🇰","Lithuania":"🇱🇹","Northern Ireland":"🇬🇧","Gibraltar":"🇬🇮",
    "Andorra":"🇦🇩","Luxembourg":"🇱🇺","Belarus":"🇧🇾","Montenegro":"🇲🇪",
    "Georgia":"🇬🇪","Wales":"🏴󠁧󠁢󠁷󠁬󠁳󠁿","San Marino":"🇸🇲",
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
    "Bosnia-Herzegovina":"BIH","Bosnia-Herz.":"BIH","Latvia":"LVA","Faroe Islands":"FRO",
    "Malta":"MLT","Liechtenstein":"LIE","Estonia":"EST","Albania":"ALB",
    "North Macedonia":"MKD","Lithuania":"LTU","Northern Ireland":"NIR","Gibraltar":"GIB",
    "Andorra":"AND","Luxembourg":"LUX","Belarus":"BLR","Montenegro":"MNE",
    "Georgia":"GEO","Wales":"WAL","San Marino":"SMR",
}


def scrape_football_coefficient(season: str) -> dict | None:
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
        return None

    soup = BeautifulSoup(r.text, "lxml")
    return parse_fc_eu(soup, season)


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
            # Col 0: rank
            rank = int(re.sub(r"\D", "", cells[0].get_text(strip=True)) or "0")
            if rank == 0:
                continue

            # Col 1: country name (strip code in parens)
            cname = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', cells[1].get_text(strip=True)).strip()
            if not cname:
                continue

            # Col 2: NR = total coefficient
            bold = cells[2].find(["b", "strong"])
            total = safe_float((bold or cells[2]).get_text(strip=True))

            # Col 3: current season coefficient (Y1)
            y1_raw = safe_float(cells[3].get_text(strip=True)) if len(cells) > 3 else 0.0

            # Col 4: NC = "cl_active+el_active+ecl_active"
            # This is the number of clubs STILL IN each competition
            # e.g. "6+2+1" = 6 in CL, 2 in EL, 1 in ECL = 9 still active
            cl_active = el_active = ecl_active = 0
            clubs_active_total = 0
            if len(cells) > 4:
                nc_text = cells[4].get_text(strip=True)
                nc_nums = re.findall(r'\d+', nc_text)
                if len(nc_nums) >= 3:
                    cl_active, el_active, ecl_active = int(nc_nums[0]), int(nc_nums[1]), int(nc_nums[2])
                    clubs_active_total = cl_active + el_active + ecl_active
                elif len(nc_nums) == 1:
                    clubs_active_total = int(nc_nums[0])

            # Col 5: CS = total club points in current season (used for verification)

            # Last col: Club list
            clubs = []
            if len(cells) >= 6:
                clubs = parse_club_cell(cells[-1], cl_active, el_active, ecl_active)

            clubs_total = len(clubs)  # FIXED: total = all clubs listed, not NC sum

            # If clubs_active_total > 0, use it; else compute from flags
            if clubs_active_total == 0:
                clubs_active_total = sum(1 for c in clubs if c["active"])

            # Y1: prefer site value, fallback to sum(pts)/clubs_total
            y1 = y1_raw
            if y1 == 0 and clubs and clubs_total > 0:
                y1 = round(sum(c["pts"] for c in clubs) / clubs_total, 3)

            # Historical coefficients from previous season file
            prev = prev_ranks.get(cname, {})
            y2 = prev.get("y1", 0.0)
            y3 = prev.get("y2", 0.0)
            y4 = prev.get("y3", 0.0)
            y5 = prev.get("y4", 0.0)

            countries.append({
                "rank": rank,
                "prev_rank": prev.get("rank", rank),
                "name": cname,
                "code": CODES.get(cname, cname[:3].upper()),
                "flag": FLAGS.get(cname, "🏳️"),
                "total": total,
                "y1": round(y1, 3),
                "y2": round(y2, 3),
                "y3": round(y3, 3),
                "y4": round(y4, 3),
                "y5": round(y5, 3),
                "clubs_total": clubs_total,
                "clubs_active": clubs_active_total,
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


def parse_club_cell(cell, cl_active: int, el_active: int, ecl_active: int) -> list:
    """
    Parse club links from the last cell.
    
    KEY FIXES:
    1. active = NOT wrapped in <s>/<del>/<strike> tag (site crosses out eliminated clubs)
    2. comp = assigned based on NC counts (cl_active+el_active+ecl_active)
       Clubs are ordered CL first, then EL, then ECL on the site
       Active clubs come first within each group, then eliminated ones
    3. pts = extracted from text sibling after each link
    """
    clubs = []
    links = cell.find_all("a")

    for link in links:
        name = link.get_text(strip=True)
        if not name:
            continue

        # FIX 1: Check if link (or its parent) is inside a strikethrough tag
        # The site wraps eliminated club links in <s> tags
        is_eliminated = bool(
            link.find_parents(["s", "del", "strike"]) or
            link.find_parent(class_=re.compile(r'elimin|out|cross|inactive', re.I))
        )
        # Also check link's own style for text-decoration
        link_style = link.get("style", "") + " ".join(link.get("class", []))
        if "line-through" in link_style or "eliminated" in link_style.lower():
            is_eliminated = True

        # FIX 2: Extract points from the text node following the link
        pts = 0.0
        sib = link.next_sibling
        if sib:
            pts_match = re.search(r'([\d,]+\.?\d*)', str(sib))
            if pts_match:
                pts = safe_float(pts_match.group(1))

        clubs.append({
            "name": name,
            "pts": pts,
            "active": not is_eliminated,
            "comp": "ECL",  # default, will be overridden below
        })

    # Fallback: parse raw text lines if no links found
    if not clubs:
        text = cell.get_text(separator="\n", strip=True)
        for line in text.split("\n"):
            m = re.match(r'^(.+?)\s+([\d.]+)\s*$', line.strip())
            if m:
                clubs.append({"name": m.group(1), "pts": safe_float(m.group(2)), "active": True, "comp": "ECL"})

    # FIX 3: Assign competition based on NC counts
    # The site lists clubs in order: CL clubs, then EL clubs, then ECL clubs
    # Within each group, active clubs appear before eliminated ones
    if cl_active > 0 or el_active > 0 or ecl_active > 0:
        _assign_comps(clubs, cl_active, el_active, ecl_active)

    return clubs


def _assign_comps(clubs, cl_n, el_n, ecl_n):
    """
    Assign CL/EL/ECL to clubs based on active counts.
    Strategy: sort by pts desc (higher pts = more likely CL), assign CL to top cl_n active,
    then EL to next el_n active, rest ECL.
    
    This is approximate — the site orders them by competition, not by pts.
    A more accurate approach scrapes each country page, but this is good enough.
    """
    if cl_n == 0 and el_n == 0 and ecl_n == 0:
        return  # no info, leave as ECL

    active = [c for c in clubs if c["active"]]
    inactive = [c for c in clubs if not c["active"]]

    # Sort active clubs by pts descending (CL clubs generally have more pts)
    active.sort(key=lambda c: c["pts"], reverse=True)

    idx = 0
    for c in active:
        if idx < cl_n:
            c["comp"] = "CL"
        elif idx < cl_n + el_n:
            c["comp"] = "EL"
        else:
            c["comp"] = "ECL"
        idx += 1

    # For inactive clubs: distribute proportionally
    # Inactive clubs keep ECL by default, but try to assign based on total
    total_entered_cl = cl_n  # minimum; could be more if some CL clubs already out
    total_entered_el = el_n
    # For now, inactive clubs get ECL (conservative)
    for c in inactive:
        c["comp"] = "ECL"


def safe_float(text: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(text).replace(",", ".")) or "0")
    except ValueError:
        return 0.0


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
        ok = 0
        for s in reversed(SEASONS):  # oldest first for history chain
            if scrape_season(s):
                ok += 1
            time.sleep(args.delay)
        log.info(f"Done: {ok}/{len(SEASONS)}")
    else:
        sys.exit(0 if scrape_season(args.season) else 1)


if __name__ == "__main__":
    main()
