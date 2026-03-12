#!/usr/bin/env python3
"""
UEFA Country Ranking Scraper — v6
Source: football-coefficient.eu

NEW v6:
  - Scrapes /team/ID/?season=YYYY for each club → pts per round (CL/EL/ECL)
  - Cache: data/team_rounds_cache.json (keyed by team_id:season)
  - Only re-fetches active clubs; eliminated ones are cached permanently
  - JSON: clubs now include 'rounds', 'team_id', 'team_slug'

CSS logic (country ranking page):
  el-btn--blue     = active Champions League
  el-btn--orange   = active Europa/Conference League
  (no color)       = active ECL
  club-eliminate   = ELIMINATED
"""

import json, re, sys, time, argparse, logging
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "public" / "data"
CACHE_FILE  = OUTPUT_DIR / "team_rounds_cache.json"

SEASONS = [
    "2025-26","2024-25","2023-24","2022-23","2021-22","2020-21",
    "2019-20","2018-19","2017-18","2016-17","2015-16","2014-15",
    "2013-14","2012-13","2011-12","2010-11","2009-10","2008-09",
]

# Ordered columns per competition (new format 2024+)
# CL: up to 8 league phase matchdays + play-off barrage (PO) before R16
# EL/ECL: up to 6 matchdays + play-off (PO) before R16
CL_ROUNDS  = ["FI","SF","QF","R16","PO","G8","G7","G6","G5","G4","G3","G2","G1","Q"]
EL_ROUNDS  = ["FI","SF","QF","R16","PO","G6","G5","G4","G3","G2","G1","Q"]
ECL_ROUNDS = ["FI","SF","QF","R16","PO","G6","G5","G4","G3","G2","G1","Q"]

# football-coefficient.eu round label → our key
ROUND_MAP = {
    "final": "FI", "finale": "FI",
    "semi-final": "SF", "semi final": "SF", "demi-finale": "SF",
    "quarter-final": "QF", "quarter final": "QF", "quart": "QF",
    "round of 16": "R16", "1/8": "R16", "last 16": "R16", "achtelfinal": "R16",
    # Play-off / barrage (between league phase and R16)
    "play-off": "PO", "playoff": "PO", "play off": "PO",
    "knock-out play-off": "PO", "knockout play-off": "PO",
    "intermediate round": "PO", "zwischenrunde": "PO",
    "play-offs": "PO", "playoffs": "PO",
    # League phase matchdays (CL has up to 8, EL/ECL up to 6)
    "league phase matchday 8": "G8", "matchday 8": "G8", "group stage 8": "G8",
    "league phase matchday 7": "G7", "matchday 7": "G7", "group stage 7": "G7",
    "league phase matchday 6": "G6", "matchday 6": "G6", "group stage 6": "G6", "league phase 6": "G6",
    "league phase matchday 5": "G5", "matchday 5": "G5", "group stage 5": "G5", "league phase 5": "G5",
    "league phase matchday 4": "G4", "matchday 4": "G4", "group stage 4": "G4", "league phase 4": "G4",
    "league phase matchday 3": "G3", "matchday 3": "G3", "group stage 3": "G3", "league phase 3": "G3",
    "league phase matchday 2": "G2", "matchday 2": "G2", "group stage 2": "G2", "league phase 2": "G2",
    "league phase matchday 1": "G1", "matchday 1": "G1", "group stage 1": "G1", "league phase 1": "G1",
    "qualifying": "Q", "qualification": "Q", "preliminary": "Q",
    "1st qualifying": "Q", "2nd qualifying": "Q", "3rd qualifying": "Q",
    "q1": "Q", "q2": "Q", "q3": "Q",
}

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
    "Bulgaria":"🇧🇬","Ireland":"🇮🇪","Iceland":"🇮🇸","Armenia":"🇦🇲","Moldova":"🇲🇩",
    "Finland":"🇫🇮","Kosovo":"🇽🇰","Kazakhstan":"🇰🇿","Bosnia-Herzegovina":"🇧🇦",
    "Latvia":"🇱🇻","Faroe Islands":"🇫🇴","Malta":"🇲🇹","Georgia":"🇬🇪","Albania":"🇦🇱",
    "North Macedonia":"🇲🇰","Montenegro":"🇲🇪","Lithuania":"🇱🇹","Estonia":"🇪🇪",
    "Belarus":"🇧🇾","Luxembourg":"🇱🇺","Wales":"🏴󠁧󠁢󠁷󠁬󠁳󠁿","San Marino":"🇸🇲",
    "Liechtenstein":"🇱🇮","Gibraltar":"🇬🇮","Andorra":"🇦🇩",
}
CODES = {
    "England":"ENG","Spain":"ESP","Germany":"GER","Italy":"ITA","France":"FRA",
    "Portugal":"POR","Netherlands":"NED","Belgium":"BEL","Türkiye":"TUR","Turkey":"TUR",
    "Czechia":"CZE","Czech Republic":"CZE","Greece":"GRE","Poland":"POL","Denmark":"DEN",
    "Norway":"NOR","Cyprus":"CYP","Switzerland":"SUI","Austria":"AUT","Scotland":"SCO",
    "Sweden":"SWE","Croatia":"CRO","Israel":"ISR","Hungary":"HUN","Serbia":"SRB",
    "Romania":"ROU","Ukraine":"UKR","Slovenia":"SVN","Azerbaijan":"AZE","Slovakia":"SVK",
    "Bulgaria":"BUL","Ireland":"IRL","Iceland":"ISL","Armenia":"ARM","Moldova":"MDA",
    "Finland":"FIN","Kosovo":"KOS","Kazakhstan":"KAZ","Bosnia-Herzegovina":"BIH",
    "Latvia":"LAT","Faroe Islands":"FRO","Malta":"MLT","Georgia":"GEO","Albania":"ALB",
    "North Macedonia":"MKD","Montenegro":"MNE","Lithuania":"LTU","Estonia":"EST",
    "Belarus":"BLR","Luxembourg":"LUX","Wales":"WAL","San Marino":"SMR",
}

# ── CACHE ──────────────────────────────────────────────────────────────────────

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try: return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except: pass
    return {}

def save_cache(cache: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

def cache_key(team_id: int, season: str) -> str:
    return f"{team_id}:{season}"

# ── HELPERS ────────────────────────────────────────────────────────────────────

def safe_float(s: str) -> float:
    try: return float(re.sub(r"[^\d.\-]", "", s))
    except: return 0.0

def normalize_round(raw: str) -> str:
    s = raw.lower().strip()
    if s in ROUND_MAP: return ROUND_MAP[s]
    for k, v in ROUND_MAP.items():
        if k in s: return v
    return ""

def _empty_rounds() -> dict:
    return {
        "CL":  {k: 0 for k in CL_ROUNDS},
        "EL":  {k: 0 for k in EL_ROUNDS},
        "ECL": {k: 0 for k in ECL_ROUNDS},
        "last_round": {"CL": "", "EL": "", "ECL": ""},
    }

ROUND_ORDER = {"FI":13,"SF":12,"QF":11,"R16":10,"PO":9,
               "G8":8,"G7":7,"G6":6,"G5":5,"G4":4,"G3":3,"G2":2,"G1":1,"Q":0}

def update_last_round(last_round: dict, comp: str, rkey: str):
    cur = last_round.get(comp, "")
    if ROUND_ORDER.get(rkey, -1) > ROUND_ORDER.get(cur, -1):
        last_round[comp] = rkey

# ── TEAM PAGE PARSER ───────────────────────────────────────────────────────────

def detect_comp(elem) -> str:
    """Detect CL/EL/ECL from an img element."""
    alt = (elem.get("alt") or elem.get("title") or "").lower()
    src = (elem.get("src") or "").lower()
    if "champions" in alt or "champions_league" in src: return "CL"
    if "conference" in alt or "conference" in src:      return "ECL"
    if "europa" in alt or "europa_league" in src:       return "EL"
    return ""

def parse_team_page(html: str) -> dict:
    """
    Parse a /team/ID/ page to extract pts per round per competition.

    football-coefficient.eu shows a match history table with columns:
      Date | Competition | Home | Score | Away | Pts

    We accumulate pts per (competition, round).
    Round is read from the img title/alt (e.g. "Matchday 3 Champions League").
    """
    soup = BeautifulSoup(html, "lxml")
    result = _empty_rounds()

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            # Find competition img
            comp = ""
            rkey = ""
            for img in row.find_all("img"):
                c = detect_comp(img)
                if c:
                    comp = c
                    # Round from img alt/title (e.g. "Matchday 3 Champions League")
                    alt = (img.get("alt") or img.get("title") or "")
                    rkey = normalize_round(alt)
                    break

            if not comp:
                continue

            # Round from first cell if not found in img
            if not rkey:
                rkey = normalize_round(cells[0].get_text(strip=True))
            if not rkey:
                # Try all cells
                for cell in cells:
                    rkey = normalize_round(cell.get_text(strip=True))
                    if rkey:
                        break

            if not rkey:
                continue

            # Pts: last numeric cell (should be 0, 0.5, 1, or 2)
            pts = None
            for cell in reversed(cells):
                t = cell.get_text(strip=True)
                if re.match(r"^\d+(\.\d+)?$", t):
                    v = float(t)
                    if v <= 5:   # sanity: match pts max ~2, bonus could be up to 5
                        pts = v
                        break

            if pts is None:
                continue

            # Add to appropriate rounds dict
            comp_rounds = result.get(comp, {})
            if rkey in comp_rounds:
                comp_rounds[rkey] = (comp_rounds[rkey] or 0) + pts
            elif comp == "CL":
                result["CL"][rkey] = pts
            elif comp == "EL":
                result["EL"][rkey] = pts
            else:
                result["ECL"][rkey] = pts

            update_last_round(result["last_round"], comp, rkey)

    return result

def scrape_team_rounds(team_id: int, team_slug: str, season: str, delay: float) -> dict:
    year = season_to_id(season)
    current_year = season_to_id(SEASONS[0])
    url = f"https://www.football-coefficient.eu/team/{team_id}-{team_slug}/"
    params = {} if year == current_year else {"season": year}
    time.sleep(delay)
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
        log.debug(f"  → {r.status_code} {url}")
        return parse_team_page(r.text)
    except Exception as e:
        log.warning(f"Team {team_id} ({team_slug}) failed: {e}")
        return _empty_rounds()

# ── COUNTRY PAGE PARSER ────────────────────────────────────────────────────────

def parse_club_cell(cell) -> list:
    clubs = []
    for link in cell.find_all("a"):
        href = link.get("href", "")
        m = re.match(r"/team/(\d+)-([^/]+)/", href)
        team_id   = int(m.group(1)) if m else None
        team_slug = m.group(2)      if m else ""

        inner = link.find("div", class_="el-btn--team")
        if not inner:
            continue
        classes = " ".join(inner.get("class", []))

        eliminated = "club-eliminate" in classes
        if "el-btn--blue" in classes:   comp = "CL"
        elif "el-btn--orange" in classes: comp = "EL"
        else:                             comp = "ECL"

        divs = inner.find_all("div", recursive=False)
        name = divs[0].get_text(strip=True) if divs else ""
        pts  = safe_float(divs[-1].get_text(strip=True)) if len(divs) >= 2 else 0.0
        if not name:
            continue

        clubs.append({
            "name": name, "pts": pts,
            "active": not eliminated, "comp": comp,
            "team_id": team_id, "team_slug": team_slug,
        })
    return clubs

def load_prev_ranks(season: str) -> dict:
    parts = season.split("-")
    start = int(parts[0])
    prev  = f"{start-1}-{str(start)[-2:]}"
    path  = OUTPUT_DIR / f"ranking_{prev}.json"
    if not path.exists(): return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {c["name"]: c for c in data.get("countries", [])}
    except: return {}

# Inline Y1 history for Y2-Y5 backfill
Y1_HIST = {
    "2024-25": {"Spain":27.928,"England":27.464,"Germany":17.500,"France":13.666,"Italy":18.071,
                "Portugal":13.800,"Netherlands":12.600,"Belgium":8.700,"Scotland":8.000,
                "Austria":8.750,"Türkiye":7.800,"Poland":6.500,"Czechia":6.500,"Greece":5.200,
                "Denmark":5.875,"Ukraine":5.800,"Norway":4.300,"Switzerland":6.350,
                "Croatia":5.400,"Serbia":4.800},
    "2023-24": {"Spain":19.071,"Germany":18.748,"England":19.607,"Italy":20.071,"France":13.333,
                "Portugal":12.400,"Netherlands":12.400,"Belgium":8.700,"Scotland":7.500,
                "Austria":8.000,"Türkiye":7.200,"Poland":5.750,"Czechia":6.500,"Greece":4.800,
                "Denmark":5.750,"Ukraine":3.300,"Norway":9.188,"Switzerland":6.200,
                "Croatia":5.000,"Serbia":4.600},
    "2022-23": {"Spain":21.000,"England":20.892,"Germany":18.000,"Italy":21.071,"France":18.380,
                "Portugal":13.200,"Netherlands":15.300,"Belgium":14.500,"Scotland":6.550,
                "Austria":6.750,"Türkiye":13.500,"Poland":9.250,"Czechia":11.500,"Greece":11.913,
                "Denmark":9.125,"Ukraine":4.000,"Norway":9.700,"Switzerland":7.950,
                "Croatia":5.625,"Serbia":5.600},
    "2021-22": {"Spain":19.071,"England":22.875,"Germany":16.870,"Italy":21.732,"France":19.800,
                "Portugal":13.267,"Netherlands":17.650,"Belgium":18.950,"Scotland":5.000,
                "Austria":6.250,"Türkiye":12.300,"Poland":9.500,"Czechia":13.000,"Greece":12.300,
                "Denmark":9.106,"Ukraine":4.500,"Norway":10.000,"Switzerland":8.000,
                "Croatia":5.100,"Serbia":5.000},
}

def parse_fc_eu(soup, season: str) -> dict | None:
    table = soup.find("table")
    if not table:
        log.warning("No table found"); return None

    prev_ranks = load_prev_ranks(season)
    yb = int(season.split("-")[0])
    countries = []

    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 7: continue
        try:
            rank = int(cells[0].get_text(strip=True))
        except: continue

        img = cells[1].find("img")
        cname = img.get("alt","").strip() if img else ""
        if not cname:
            cname = re.sub(r'\s*\([A-Z]{2,3}\)\s*$','', cells[1].get_text(strip=True)).strip()
        if not cname: continue

        total = safe_float(cells[2].get_text(strip=True))
        y1    = safe_float(cells[3].get_text(strip=True))
        clubs = parse_club_cell(cells[-1])

        # Y2-Y5 from inline history
        y2 = Y1_HIST.get(f"{yb-1}-{str(yb)[-2:]}",{}).get(cname,0.0)
        y3 = Y1_HIST.get(f"{yb-2}-{str(yb-1)[-2:]}",{}).get(cname,0.0)
        y4 = Y1_HIST.get(f"{yb-3}-{str(yb-2)[-2:]}",{}).get(cname,0.0)
        y5 = Y1_HIST.get(f"{yb-4}-{str(yb-3)[-2:]}",{}).get(cname,0.0)

        prev = prev_ranks.get(cname,{}).get("rank", rank)
        countries.append({
            "rank": rank, "prev_rank": prev,
            "name": cname,
            "code": CODES.get(cname, cname[:3].upper()),
            "flag": FLAGS.get(cname,"🏳️"),
            "total": round(total,3), "y1": round(y1,3),
            "y2": round(y2,3), "y3": round(y3,3),
            "y4": round(y4,3), "y5": round(y5,3),
            "clubs_total":  len(clubs),
            "clubs_active": sum(1 for c in clubs if c["active"]),
            "clubs": clubs,
        })

    if not countries: return None

    n = len(countries)
    return {
        "season": season,
        "updated": datetime.now(timezone.utc).isoformat(),
        "zone_thresholds": {
            "cl_direct": min(4,n), "cl_qual": min(10,n),
            "el_direct": min(6,n), "el_qual": min(15,n),
            "ecl_qual":  min(55,n),
        },
        "countries": countries,
    }

# ── FIXTURES (v5, unchanged) ───────────────────────────────────────────────────

def build_club_country_map(ranking: dict) -> dict:
    m = {}
    for c in ranking.get("countries",[]):
        for cl in c.get("clubs",[]):
            m[cl["name"]] = {"country": c["name"], "flag": c["flag"], "code": c["code"]}
    return m

def scrape_fixtures(soup, club_country: dict) -> dict | None:
    upcoming, results = [], []

    def parse_date(raw):
        raw = raw.strip().replace("\n"," ")
        m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw)
        if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
        return ""

    def parse_time(raw):
        m = re.search(r"(\d{1,2}):(\d{2})", raw)
        return f"{m.group(1).zfill(2)}:{m.group(2)}" if m else "20:00"

    def parse_round(img_elem):
        if not img_elem: return "ECL","Unknown"
        alt = img_elem.get("alt") or img_elem.get("title") or ""
        src = img_elem.get("src") or ""
        if "champions" in alt.lower() or "champions_league" in src: comp = "CL"
        elif "conference" in alt.lower() or "conference" in src:    comp = "ECL"
        elif "europa" in alt.lower() or "europa_league" in src:     comp = "EL"
        else: comp = "ECL"
        return comp, alt

    for table in soup.find_all("table", class_="el-table"):
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 5: continue
            date_raw = cells[0].get_text(" ", strip=True)
            date = parse_date(date_raw)
            t    = parse_time(date_raw)
            if not date: continue
            comp, rl = parse_round(cells[1].find("img"))
            home_a = cells[2].find("a"); away_a = cells[4].find("a")
            if not home_a or not away_a: continue
            home = home_a.get_text(strip=True)
            away = away_a.get_text(strip=True)
            sc   = cells[3].get_text(strip=True)
            is_r = bool(re.match(r"\d+\s*[:\-]\s*\d+", sc))
            hi = club_country.get(home,{}); ai = club_country.get(away,{})
            e = {"date":date,"time":t,"comp":comp,"round":rl,
                 "home":home,"homeFlag":hi.get("flag",""),"homeCountry":hi.get("country",""),
                 "away":away,"awayFlag":ai.get("flag",""),"awayCountry":ai.get("country",""),
                 "score": sc if is_r else None}
            (results if is_r else upcoming).append(e)

    upcoming.sort(key=lambda x: x["date"]+x["time"])
    results.sort(key=lambda x: x["date"], reverse=True)
    return {"updated": datetime.now(timezone.utc).isoformat(),
            "upcoming": upcoming[:20], "results": results[:20]}

# ── ROUND ENRICHMENT ───────────────────────────────────────────────────────────

def enrich_clubs_with_rounds(ranking: dict, season: str, delay: float, cache: dict) -> int:
    """Fetch /team/ID/ for each club and store rounds data. Uses cache."""
    requests_made = 0
    total_clubs  = sum(len(c.get("clubs",[])) for c in ranking.get("countries",[]))
    done = 0

    for country in ranking.get("countries",[]):
        for club in country.get("clubs",[]):
            done += 1
            tid   = club.get("team_id")
            tslug = club.get("team_slug","")
            if not tid:
                club["rounds"] = _empty_rounds()
                continue

            key = cache_key(tid, season)

            # Eliminated clubs: use cache permanently
            if key in cache and not club["active"]:
                club["rounds"] = cache[key]
                log.debug(f"[{done}/{total_clubs}] Cache (out): {club['name']}")
                continue

            # Active clubs: always re-fetch (data changes after each matchday)
            log.info(f"[{done}/{total_clubs}] Fetching: {club['name']} ({country['name']}, {club['comp']}, active={club['active']})")
            rounds = scrape_team_rounds(tid, tslug, season, delay=delay)
            requests_made += 1
            club["rounds"] = rounds
            cache[key] = rounds

            # Incremental cache save every 10 requests
            if requests_made % 10 == 0:
                save_cache(cache)
                log.info(f"Cache saved ({requests_made} requests so far)")

    return requests_made

# ── MAIN ───────────────────────────────────────────────────────────────────────

def scrape_football_coefficient(season: str):
    sid = season_to_id(season)
    current_sid = season_to_id(SEASONS[0])
    url = "https://www.football-coefficient.eu/" if sid == current_sid else \
          f"https://www.football-coefficient.eu/?idSeasonChoice={sid}"
    log.info(f"Fetching main page: {season} → {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.warning(f"Main page request failed: {e}"); return None, None, None
    soup = BeautifulSoup(r.text, "lxml")
    ranking = parse_fc_eu(soup, season)
    fixtures = None
    if sid == current_sid and ranking:
        fixtures = scrape_fixtures(soup, build_club_country_map(ranking))
    return ranking, fixtures, soup

def scrape_season(season: str, delay: float = 1.5, skip_rounds: bool = False) -> bool:
    ranking, fixtures, _ = scrape_football_coefficient(season)
    if not ranking or not ranking.get("countries"):
        log.error(f"No data for {season}"); return False

    # Round enrichment only for current season
    if not skip_rounds and season == SEASONS[0]:
        cache = load_cache()
        n = enrich_clubs_with_rounds(ranking, season, delay=delay, cache=cache)
        save_cache(cache)
        log.info(f"Round enrichment complete: {n} HTTP requests")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"ranking_{season}.json"
    path.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"✅ {len(ranking['countries'])} countries → {path}")

    if fixtures:
        fp = OUTPUT_DIR / "fixtures.json"
        fp.write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"✅ {len(fixtures['upcoming'])} upcoming + {len(fixtures['results'])} results → {fp}")

    return True

def main():
    p = argparse.ArgumentParser(description="UEFA Ranking Scraper v6")
    p.add_argument("--season", default=SEASONS[0])
    p.add_argument("--mode", choices=["current","all_seasons"], default="current")
    p.add_argument("--delay", type=float, default=1.5,
                   help="Seconds between team page requests")
    p.add_argument("--skip-rounds", action="store_true",
                   help="Skip per-round scraping (faster, country totals only)")
    p.add_argument("--clear-active-cache", action="store_true",
                   help="Force re-fetch active clubs (clears their cache entries)")
    args = p.parse_args()

    # Optionally clear active club cache entries
    if args.clear_active_cache and CACHE_FILE.exists():
        cache = load_cache()
        rpath = OUTPUT_DIR / f"ranking_{args.season}.json"
        if rpath.exists():
            rdata = json.loads(rpath.read_text())
            cleared = 0
            for c in rdata.get("countries",[]):
                for cl in c.get("clubs",[]):
                    if cl.get("active") and cl.get("team_id"):
                        k = cache_key(cl["team_id"], args.season)
                        if k in cache:
                            del cache[k]; cleared += 1
            save_cache(cache)
            log.info(f"Cleared {cleared} active club cache entries")

    if args.mode == "all_seasons":
        ok = 0
        for s in reversed(SEASONS):
            skip = (s != SEASONS[0]) or args.skip_rounds
            if scrape_season(s, delay=args.delay, skip_rounds=skip):
                ok += 1
            time.sleep(args.delay)
        log.info(f"Done: {ok}/{len(SEASONS)} seasons")
    else:
        sys.exit(0 if scrape_season(args.season, delay=args.delay,
                                     skip_rounds=args.skip_rounds) else 1)

if __name__ == "__main__":
    main()
