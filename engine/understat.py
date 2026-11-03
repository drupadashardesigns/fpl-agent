"""Understat layer. Standard library only.

Understat stopped embedding JSON in its pages in late 2025. Data now comes from
AJAX endpoints that need "X-Requested-With: XMLHttpRequest" and a browser
User-Agent:

    getLeagueData/EPL/{season}   -> {teams, players, dates}   (season = start year)
    getMatchData/{match_id}      -> {rosters, shots, tmpl}
    getPlayerData/{player_id}    -> {player, matches, shots, groups}   (not used yet)

The fetch runs once a night in GitHub Actions (nightly.yml), up to 3 attempts.
Understat has been down for everyone since about 2 Nov 2026; a failed fetch is
recorded in data/sources.json (status "offline", with "offline_since") and the
command still exits 0, so it never fails the nightly job. The first successful
fetch flips the source to "healthy". Everything else here works offline from
the cache.

    python -m engine understat            fetch league data + new finished matches, then derive
    python -m engine understat --offline  derive only, from data/understat/ on disk

Files:
    data/understat/league_EPL_<season>.json   latest league payload (overwritten each run)
    data/understat/matches/<id>.json.gz       one per finished match, fetched once
    data/understat/derived.json               player and team stats keyed by FPL id
    data/id_map.json                          FPL element id -> Understat player id
    data/id_map_unmatched.json                players we would not match (for review)
    data/sources.json                         health record for "understat"

Understat's xG is its own model. It is kept apart from FPL's xG (Opta) all
the way to the screen: different keys here, different columns in the app.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import time
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "understat"
SOURCES = ROOT / "data" / "sources.json"
ID_MAP = ROOT / "data" / "id_map.json"
UNMATCHED = ROOT / "data" / "id_map_unmatched.json"
BASE = "https://understat.com/"
LEAGUE = "EPL"
SEASON = 2026  # start year: 2026 means 2026/27
PAUSE = 3.0  # seconds between requests
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
ON_TARGET = {"Goal", "SavedShot"}
SHOT_CODE = {"Goal": "G", "SavedShot": "S", "MissedShots": "M", "BlockedShot": "B", "ShotOnPost": "P"}

_last = 0.0


# ---- fetching ----------------------------------------------------------------

def ajax(endpoint: str, retries: int = 3) -> dict:
    """GET one AJAX endpoint, at most one request every PAUSE seconds."""
    global _last
    err = None
    for attempt in range(retries):
        wait = PAUSE - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        req = urllib.request.Request(BASE + endpoint, headers={
            "X-Requested-With": "XMLHttpRequest", "User-Agent": UA, "Accept": "application/json, text/javascript, */*",
            "Referer": BASE + f"league/{LEAGUE}/{SEASON}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:  # network, HTTP or JSON error
            err = e
            time.sleep(PAUSE * (attempt + 1))
    raise RuntimeError(f"{endpoint}: {err}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def record_health(ok: bool, detail: str, stats: dict | None = None) -> None:
    src = json.loads(SOURCES.read_text()) if SOURCES.exists() else {"sources": {}}
    s = src["sources"].setdefault("understat", {"name": "Understat"})
    if ok:
        s.update(status="healthy", last_success=_now(), last_error=None, detail=detail)
        s.pop("offline_since", None)
        if stats:
            s.update(stats)
    else:
        # keep the last good data and its date; the app shows it with that date.
        # "offline" = never fetched successfully; "stale" = last good data exists.
        s.update(status="offline" if not s.get("last_success") else "stale",
                 last_error={"at": _now(), "message": detail[:300]})
        s.setdefault("offline_since", _now()[:10])
    src["updated_at"] = _now()
    SOURCES.write_text(json.dumps(src, indent=2, ensure_ascii=False) + "\n")


def match_path(mid) -> Path:
    return DIR / "matches" / f"{mid}.json.gz"


def fetch(season: int = SEASON) -> dict:
    """League data once, then getMatchData for finished matches not yet stored."""
    DIR.mkdir(parents=True, exist_ok=True)
    league = ajax(f"getLeagueData/{LEAGUE}/{season}")
    dates = league.get("dates") or []
    if not dates or not league.get("players"):
        raise RuntimeError(f"getLeagueData/{LEAGUE}/{season} returned no dates or players")
    first = min(d["datetime"] for d in dates)
    if not first.startswith(str(season)):
        raise RuntimeError(f"season {season} starts {first}: not {season}/{(season + 1) % 100:02d}")
    league["fetched_at"] = _now()
    (DIR / f"league_{LEAGUE}_{season}.json").write_text(json.dumps(league, ensure_ascii=False))
    done = [d for d in dates if d.get("isResult")]
    new = [d for d in done if not match_path(d["id"]).exists()]
    (DIR / "matches").mkdir(exist_ok=True)
    for i, d in enumerate(new, 1):
        m = ajax(f"getMatchData/{d['id']}")
        m = {"id": d["id"], "datetime": d["datetime"], "h": d["h"], "a": d["a"], "goals": d["goals"], "xG": d["xG"],
             "shots": m.get("shots", {}), "rosters": m.get("rosters", {}), "fetched_at": _now()}
        match_path(d["id"]).write_bytes(gzip.compress(json.dumps(m, ensure_ascii=False).encode()))
        print(f"  match {d['id']} {d['h']['title']} v {d['a']['title']} ({i}/{len(new)})")
    print(f"understat: season {season} starts {first[:10]}, {len(dates)} fixtures, {len(done)} finished, "
          f"{len(new)} new matches fetched, {len(league['players'])} players")
    return {"season_start": first[:10], "finished": len(done), "new_matches": len(new)}


# ---- loading -----------------------------------------------------------------------

def _load(path: Path):
    if not path.exists():
        return None
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def load_league(season: int = SEASON) -> dict | None:
    return _load(DIR / f"league_{LEAGUE}_{season}.json")


def load_matches() -> list[dict]:
    return sorted((_load(p) for p in (DIR / "matches").glob("*.json.gz")), key=lambda m: m["datetime"])


# ---- names and the ID map -----------------------------------------------------------

def norm(s: str) -> str:
    """Lower case, accents off, punctuation to spaces: 'Ødegaard' -> 'odegaard'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ø", "o").replace("Ø", "o").replace("ß", "ss").replace("ł", "l").replace("đ", "d").replace("æ", "ae")
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower().replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


# Understat team titles that do not normalise to the FPL name or short name.
TEAM_ALIASES = {
    "manchester city": "man city", "manchester united": "man utd", "newcastle united": "newcastle",
    "nottingham forest": "nottm forest", "tottenham": "spurs", "tottenham hotspur": "spurs",
    "wolverhampton wanderers": "wolves", "west ham united": "west ham", "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton", "leeds united": "leeds", "leicester city": "leicester",
    "afc bournemouth": "bournemouth", "coventry": "coventry city", "hull": "hull city", "ipswich": "ipswich town",
    "sheffield united": "sheffield utd", "luton town": "luton", "norwich city": "norwich", "cardiff city": "cardiff",
    "stoke city": "stoke", "swansea city": "swansea", "west bromwich albion": "west brom",
}


def team_map(bs: dict, league: dict) -> tuple[dict, list]:
    """Understat team id -> FPL team id. Returns the map and any titles left over."""
    fpl = {}
    for t in bs["teams"]:
        fpl[norm(t["name"])] = t["id"]
        fpl[norm(t["short_name"])] = t["id"]
    out, missing = {}, []
    for uid, t in league["teams"].items():
        n = norm(t["title"])
        tid = fpl.get(n) or fpl.get(TEAM_ALIASES.get(n, ""))
        if tid:
            out[str(t["id"])] = tid
        else:
            missing.append(t["title"])
    return out, missing


def build_id_map(bs: dict, league: dict) -> dict:
    """Map FPL element ids to Understat player ids by team plus normalised name.

    Tiers, strongest first. A tier only matches when it finds exactly one
    Understat player on the team, and that player is not claimed by another
    FPL player at the same tier. Looser tiers also need the minutes to agree.
    Anything else goes to the unmatched list: we never guess.
      1 full name ("Bukayo Saka" = first + second name)
      2 first word of first name + last word of second name
      3 web name equals the Understat name ("Gabriel", "Rodri")
      4 every Understat word appears in the FPL names (short forms of long names)
      5 every web-name word appears in the Understat name ("Salah" in "Mohamed Salah")
    """
    tmap, missing_teams = team_map(bs, league)
    title_to_fpl = {t["title"]: tmap[str(t["id"])] for t in league["teams"].values() if str(t["id"]) in tmap}
    manual = {}
    if ID_MAP.exists():
        manual = {int(k): str(v) for k, v in json.loads(ID_MAP.read_text()).get("manual", {}).items()}
    us_by_team = defaultdict(list)
    us_by_id = {}
    for u in league["players"]:
        us_by_id[str(u["id"])] = u
        for title in u["team_title"].split(","):
            if title.strip() in title_to_fpl:
                us_by_team[title_to_fpl[title.strip()]].append(u)

    def keys(p):
        first, second, web = norm(p["first_name"]), norm(p["second_name"]), norm(p["web_name"])
        fw, sw = first.split(), second.split()
        return {
            1: f"{first} {second}",
            2: f"{fw[0]} {sw[-1]}" if fw and sw else None,
            3: web,
        }, set(fw + sw + web.split()), set(web.split())

    def minutes_ok(p, u):
        a, b = p["minutes"], int(u["time"])
        return abs(a - b) <= max(90, 0.15 * max(a, b))

    candidates = {}  # fpl id -> (tier, us id)
    players = [p for p in bs["elements"] if p["minutes"] > 0]
    for p in players:
        if p["id"] in manual:
            candidates[p["id"]] = (0, manual[p["id"]])
            continue
        exact, words, webw = keys(p)
        pool = us_by_team.get(p["team"], [])
        for tier in (1, 2, 3, 4, 5):
            if tier <= 3:
                hit = [u for u in pool if exact[tier] and norm(u["player_name"]) == exact[tier]]
            elif tier == 4:
                hit = [u for u in pool if set(norm(u["player_name"]).split()) <= words and minutes_ok(p, u)]
            else:
                hit = [u for u in pool if webw and webw <= set(norm(u["player_name"]).split()) and minutes_ok(p, u)]
            if len(hit) == 1:
                candidates[p["id"]] = (tier, str(hit[0]["id"]))
                break
            if len(hit) > 1:
                candidates[p["id"]] = (tier, None, [u["player_name"] for u in hit])
                break
    # an Understat id claimed twice is ambiguous: keep it only for the single strongest claim
    claims = defaultdict(list)
    for e, c in candidates.items():
        if c[1]:
            claims[c[1]].append((c[0], e))
    mapping, tiers, unmatched = {}, defaultdict(int), []
    for uid, cl in claims.items():
        cl.sort()
        if len(cl) == 1 or cl[0][0] < cl[1][0]:
            e = cl[0][1]
            mapping[e] = uid
            tiers[cl[0][0]] += 1
    short = {t["id"]: t["short_name"] for t in bs["teams"]}
    for p in players:
        if p["id"] in mapping:
            continue
        c = candidates.get(p["id"])
        reason = ("more than one Understat player fits: " + ", ".join(c[2])) if c and not c[1] else \
                 "claimed by another FPL player" if c else "no Understat player on the team with a matching name"
        unmatched.append({"id": p["id"], "web_name": p["web_name"], "name": f"{p['first_name']} {p['second_name']}",
                          "team": short[p["team"]], "minutes": p["minutes"], "reason": reason})
    claimed = set(mapping.values())
    us_left = [{"id": u["id"], "name": u["player_name"], "team": u["team_title"], "minutes": int(u["time"])}
               for u in league["players"] if str(u["id"]) not in claimed and int(u["time"]) > 0]
    rate = round(100 * len(mapping) / max(1, len(players)), 1)
    doc = {
        "built_at": _now(), "season": SEASON,
        "note": "FPL element id -> Understat player id. Built by engine/understat.py from team plus normalised name. "
                "Add reviewed pairs under 'manual' (FPL id -> Understat id); they win over the automatic match.",
        "match_rate": {"matched": len(mapping), "of": len(players), "pct": rate,
                       "basis": "FPL players with minutes this season", "by_tier": dict(sorted(tiers.items()))},
        "teams": {str(v): int(k) for k, v in tmap.items()},
        "manual": {str(k): v for k, v in manual.items()},
        "players": {str(k): int(v) for k, v in sorted(mapping.items())},
    }
    ID_MAP.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    UNMATCHED.write_text(json.dumps({"built_at": doc["built_at"], "missing_teams": missing_teams,
                                     "fpl_unmatched": sorted(unmatched, key=lambda r: -r["minutes"]),
                                     "understat_unclaimed": sorted(us_left, key=lambda r: -r["minutes"])},
                                    indent=1, ensure_ascii=False) + "\n")
    print(f"id map: {len(mapping)}/{len(players)} matched ({rate}%), {len(unmatched)} unmatched, "
          f"teams missing: {missing_teams or 'none'}")
    return doc


# ---- derived stats --------------------------------------------------------------------

def _f(x) -> float:
    return float(x or 0)


def _r(x, n=2):
    return round(float(x), n)


def per90(v, mins):
    return _r(v * 90 / mins, 2) if mins else None


def derive(bs: dict, fixtures: list) -> dict:
    """Player and team stats keyed by FPL id, from the cached league data and matches."""
    league = load_league()
    if not league:
        raise RuntimeError("no Understat league data on disk")
    idm = build_id_map(bs, league)
    tmap = {int(us): fpl for fpl, us in idm["teams"].items()}  # understat team id -> fpl team id
    p_us = {int(v): int(k) for k, v in idm["players"].items()}  # understat player id -> fpl id
    matches = load_matches()

    # FPL gameweek of each Understat match, found by the two teams
    fx_gw = {(f["team_h"], f["team_a"]): f["event"] for f in fixtures if f.get("event")}

    def gw_of(m):
        return fx_gw.get((tmap.get(int(m["h"]["id"])), tmap.get(int(m["a"]["id"]))))

    # ---- players: season totals from the league list --------------------------------
    players = {}
    for u in league["players"]:
        e = p_us.get(int(u["id"]))
        if not e:
            continue
        mins = int(u["time"])
        s = {"games": int(u["games"]), "min": mins, "goals": int(u["goals"]), "npg": int(u["npg"]),
             "shots": int(u["shots"]), "kp": int(u["key_passes"]), "xg": _r(_f(u["xG"])), "npxg": _r(_f(u["npxG"])),
             "xa": _r(_f(u["xA"])), "xgchain": _r(_f(u["xGChain"])), "xgbuildup": _r(_f(u["xGBuildup"]))}
        s.update({k + "90": per90(s[k], mins) for k in ("shots", "kp", "npxg", "xgchain", "xgbuildup")})
        players[str(e)] = {"us_id": int(u["id"]), "season": s}

    # ---- players: per match from rosters and shots -----------------------------------
    apps = defaultdict(list)
    shots = defaultdict(list)
    t_shots = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # fpl team -> match id -> [for, against]
    for m in matches:
        gw = gw_of(m)
        for side in ("h", "a"):
            for r in (m["rosters"].get(side) or {}).values():
                e = p_us.get(int(r["player_id"]))
                if e and int(r["time"]) > 0:
                    apps[e].append({"mid": int(m["id"]), "date": m["datetime"][:10], "gw": gw, "min": int(r["time"]),
                                    "shots": int(r["shots"]), "kp": int(r["key_passes"]), "xg": _f(r["xG"]),
                                    "xa": _f(r["xA"]), "xgchain": _f(r["xGChain"]), "xgbuildup": _f(r["xGBuildup"])})
            team_for = tmap.get(int(m[side]["id"]))
            team_vs = tmap.get(int(m["a" if side == "h" else "h"]["id"]))
            for s in m["shots"].get(side) or []:
                t_shots[team_for][m["id"]][0] += 1
                t_shots[team_vs][m["id"]][1] += 1
                e = p_us.get(int(s["player_id"]))
                if e:
                    pen = s.get("situation") == "Penalty"
                    shots[e].append([round(_f(s["X"]), 3), round(_f(s["Y"]), 3), round(_f(s["xG"]), 3),
                                     SHOT_CODE.get(s["result"], "M"), 1 if pen else 0, gw])
    for e, rows in apps.items():
        rec = players.setdefault(str(e), {"us_id": None, "season": None})
        rows.sort(key=lambda r: r["date"])
        last = rows[-4:]
        mins = sum(r["min"] for r in last)
        l4 = {"games": len(last), "min": mins, "gws": [r["gw"] for r in last],
              "minutes": [r["min"] for r in last]}
        for k in ("shots", "kp", "xg", "xa", "xgchain", "xgbuildup"):
            l4[k] = _r(sum(r[k] for r in last))
        l4.update({k + "90": per90(l4[k], mins) for k in ("shots", "kp", "xg", "xgchain", "xgbuildup")})
        rec["last4"] = l4
    for e, sh in shots.items():
        rec = players.setdefault(str(e), {"us_id": None, "season": None})
        rec["shots_on_target"] = sum(1 for s in sh if s[3] in ("G", "S"))
        rec["shot_map"] = sh  # [x, y, xG, result, penalty, gw]; x runs 0 -> 1 toward goal

    # ---- teams ------------------------------------------------------------------------------
    teams = {}
    for t in league["teams"].values():
        fpl = tmap.get(int(t["id"]))
        if not fpl:
            continue
        hist = sorted(t["history"], key=lambda h: h["date"])

        def agg(rows):
            n = len(rows)
            if not n:
                return None
            att = sum(_f(h["ppda"]["att"]) for h in rows)
            de = sum(_f(h["ppda"]["def"]) for h in rows)
            att_a = sum(_f(h["ppda_allowed"]["att"]) for h in rows)
            de_a = sum(_f(h["ppda_allowed"]["def"]) for h in rows)
            o = {"games": n, "xg": _r(sum(_f(h["xG"]) for h in rows)), "xga": _r(sum(_f(h["xGA"]) for h in rows)),
                 "npxg": _r(sum(_f(h["npxG"]) for h in rows)), "npxga": _r(sum(_f(h["npxGA"]) for h in rows)),
                 "deep": sum(int(h["deep"]) for h in rows), "deep_allowed": sum(int(h["deep_allowed"]) for h in rows),
                 "scored": sum(int(h["scored"]) for h in rows), "missed": sum(int(h["missed"]) for h in rows),
                 "ppda": _r(att / de) if de else None, "ppda_allowed": _r(att_a / de_a) if de_a else None,
                 "xpts": _r(sum(_f(h["xpts"]) for h in rows))}
            for k in ("xg", "xga", "npxg", "npxga", "deep", "deep_allowed"):
                o[k + "_pg"] = _r(o[k] / n)
            return o

        season, last4 = agg(hist), agg(hist[-4:])
        # shots for and against, summed from the stored match data
        per = t_shots.get(fpl, {})
        mids = [m["id"] for m in matches if fpl in (tmap.get(int(m["h"]["id"])), tmap.get(int(m["a"]["id"])))]
        for blk, ids in ((season, mids), (last4, mids[-4:])):
            if blk is None:
                continue
            n = len(ids)
            blk["shots"] = sum(per.get(i, [0, 0])[0] for i in ids) if n else None
            blk["shots_against"] = sum(per.get(i, [0, 0])[1] for i in ids) if n else None
            blk["shot_games"] = n
            blk["shots_pg"] = _r(blk["shots"] / n) if n else None
            blk["shots_against_pg"] = _r(blk["shots_against"] / n) if n else None
        teams[str(fpl)] = {"us_id": int(t["id"]), "title": t["title"], "season": season, "last4": last4,
                           "last4_dates": [h["date"][:10] for h in hist[-4:]]}

    latest = max((m["datetime"] for m in matches), default=None)
    out = {
        "source": "Understat", "season": SEASON, "built_at": _now(),
        "league_fetched_at": league.get("fetched_at"),
        "data_to": latest[:10] if latest else None,
        "matches": len(matches),
        "id_map": idm["match_rate"],
        "players": players, "teams": teams,
    }
    (DIR / "derived.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"derived: {len(players)} players, {len(teams)} teams, {len(matches)} matches, data to {out['data_to']}")
    return out


def run(offline: bool = False) -> None:
    from . import appdata  # newest snapshot, by its stamped fetch time
    snap, bs = appdata.newest_snapshot()
    fx = appdata._load(snap / "fixtures.json.gz")
    stats = {}
    if not offline:
        try:
            stats = fetch()
        except Exception as e:
            record_health(False, str(e))
            print(f"understat: fetch failed, recorded in data/sources.json: {e}")
            if not load_league():
                return  # nothing cached yet: the app shows the offline note
            offline = True  # derive from the last good cache
    d = derive(bs, fx)
    if not offline:
        record_health(True, f"{d['matches']} matches to {d['data_to']}; id map {d['id_map']['pct']}%",
                      {"data_to": d["data_to"], **stats})
