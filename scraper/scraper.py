#!/usr/bin/env python3
"""
UEFA Country Ranking Scraper — v4
Source: football-coefficient.eu

Logique des classes CSS du site:
  el-btn--blue     = club actif en Champions League
  el-btn--orange   = club actif en Europa League ou Conference League
  (aucune couleur) = club actif (compétition moindre)
  club-eliminate   = club ÉLIMINÉ

  comp détecté via:
  - el-btn--blue   → CL
  - el-btn--orange → EL ou ECL (déterminé par position dans NC "X+Y+Z")
  - sinon          → ECL (par défaut)
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
            rank = int(re.sub(r"\D", "", cells[0].get_text(strip=True)) or "0")
            if rank == 0:
                continue

            cname = re.sub(r'\s*\([A-Z]{2,3}\)\s*$', '', cells[1].get_text(strip=True)).strip()
            if not cname:
                continue

            bold = cells[2].find(["b", "strong"])
            total = safe_float((bold or cells[2]).get_text(strip=True))

            y1_raw = safe_float(cells[3].get_text(strip=True)) if len(cells) > 3 else 0.0

            # NC column: "cl_actifs+el_actifs+ecl_actifs"
            cl_active = el_active = ecl_active = 0
            clubs_active_nc = 0
            if len(cells) > 4:
                nc_text = cells[4].get_text(strip=True)
                nc_nums = re.findall(r'\d+', nc_text)
                if len(nc_nums) >= 3:
                    cl_active = int(nc_nums[0])
                    el_active = int(nc_nums[1])
                    ecl_active = int(nc_nums[2])
                    clubs_active_nc = cl_active + el_active + ecl_active
                elif len(nc_nums) == 1:
                    clubs_active_nc = int(nc_nums[0])

            # Parse clubs from last cell
            clubs = []
            if len(cells) >= 6:
                clubs = parse_club_cell(cells[-1])

            clubs_total = len(clubs)
            clubs_active = sum(1 for c in clubs if c["active"])

            # Y1 from site or calculated
            y1 = y1_raw
            if y1 == 0 and clubs and clubs_total > 0:
                y1 = round(sum(c["pts"] for c in clubs) / clubs_total, 3)

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
    Parse les clubs depuis la dernière colonne.

    Logique des classes CSS (confirmée depuis le HTML source) :
      el-btn--blue     → actif, Champions League
      el-btn--orange   → actif, Europa League ou Conference League
      (ni blue ni orange) → actif, compétition ECL par défaut
      club-eliminate   → ÉLIMINÉ (peut avoir n'importe quelle couleur)

    La comp (CL/EL/ECL) est déduite de la classe de couleur :
      blue  → CL
      orange → EL (les clubs EL ont orange ; les ECL actifs sans couleur)
      Cas ambigu orange ECL : si le club est dans la 3e position NC, c'est ECL
      → on affine avec _assign_comps après
    """
    clubs = []
    links = cell.find_all("a")

    for link in links:
        name = link.get_text(strip=True)
        if not name:
            continue

        # Le div à l'intérieur du lien contient les classes
        inner_div = link.find("div", class_="el-btn--team")
        classes = inner_div.get("class", []) if inner_div else []
        class_str = " ".join(classes)

        # CLEF : club-eliminate = éliminé
        is_eliminated = "club-eliminate" in class_str

        # Détection comp depuis la couleur
        if "el-btn--blue" in class_str:
            comp = "CL"
        elif "el-btn--orange" in class_str:
            comp = "EL"  # peut être affiné en ECL si nécessaire
        else:
            comp = "ECL"

        # Nom = 1er div enfant, pts = dernier div enfant
        pts = 0.0
        if inner_div:
            pt_divs = inner_div.find_all("div", recursive=False)
            if len(pt_divs) >= 2:
                name = pt_divs[0].get_text(strip=True)  # nom propre sans pts
                pts = safe_float(pt_divs[-1].get_text(strip=True))
            elif len(pt_divs) == 1:
                name = pt_divs[0].get_text(strip=True)

        if not name:
            continue

        clubs.append({
            "name": name,
            "pts": pts,
            "active": not is_eliminated,
            "comp": comp,
        })

    return clubs


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
        for s in reversed(SEASONS):
            if scrape_season(s):
                ok += 1
            time.sleep(args.delay)
        log.info(f"Done: {ok}/{len(SEASONS)} seasons")
    else:
        sys.exit(0 if scrape_season(args.season) else 1)


if __name__ == "__main__":
    main()
