"""FotMob layer. Standard library only.

Unofficial JSON endpoints (verified 3 Nov 2026, all 200 from GitHub Actions):

    https://www.fotmob.com/api/data/leagues?id=47
        fixtures.allMatches (match ids, status.finished); stats.players and
        stats.teams list every stat table with its fetchAllUrl
    https://data.fotmob.com/stats/47/season/<season id>/<stat>.json
        TopLists[0].StatList: ParticipantName, ParticiantId (FotMob's spelling),
        TeamId, StatValue, SubStatValue, MinutesPlayed, MatchesPlayed
    https://www.fotmob.com/api/data/matchDetails?matchId=<id>
        content.playerStats (groups Top stats, Attack, Defense, Duels, Physical
        metrics), content.stats (team stats), content.shotmap.shots, content.heatmapUrl
    https://www.fotmob.com<heatmapUrl>
        {"players": {"p<Opta id>": "<circle cx= cy= .../>..."}, "template": svg}
        Heatmap points are on a 105 x 68 pitch, every player attacking left to right.

Sent with a browser User-Agent and gzip accepted. One request every 2 seconds.
The nightly job (nightly.yml) runs this once; a failure is recorded in
data/sources.json and never fails the job.

    python -m engine fotmob             fetch league, stat tables, new finished matches; then derive
    python -m engine fotmob --offline   derive only, from data/fotmob/ on disk

Files:
    data/fotmob/league_47.json          fixtures and stat-table links (overwritten each run)
    data/fotmob/stats/<stat>.json       the season stat tables we read (overwritten each run)
    data/fotmob/matches/<id>.json.gz    one per finished match: player stats, team stats,
                                        shots and heatmap points. Fetched once.
    data/fotmob/derived.json            player and team stats keyed by FPL id, plus heatmaps
    data/id_map.json                    "fotmob" section: FPL element id -> FotMob player id
    data/id_map_unmatched.json          "fotmob" section: who was not matched, and why
    data/sources.json                   health record for "fotmob"

FotMob's numbers (its xG and xGOT come from Opta, but its own feed and timing)
stay under their own keys all the way to the screen: never in a column with
FPL's or Understat's numbers.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from . import idmap

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "fotmob"
SOURCES = ROOT / "data" / "sources.json"
LEAGUE_ID = 47
SEASON = "2026/2027"
WWW = "https://www.fotmob.com"
PAUSE = 2.0  # seconds between requests
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Season stat tables we keep. The app's numbers are summed from match data (so
# season, per 90 and last four share one basis); these tables are what
# fotmob.com shows, and derive() checks our sums against them.
PLAYER_TABLES = ["mins_played", "total_att_assist", "big_chance_created", "won_contest", "interception",
                 "ball_recovery", "expected_goalsontarget", "lbp_total", "phys_tdc", "phys_sprints", "phys_ts"]
TEAM_TABLES = ["phys_tdc_team", "expected_goals_conceded_team", "big_chance_team", "touches_in_opp_box_team",
               "_set_piece_goals_team", "_set_piece_goals_conceded_team", "possession_percentage_team"]

_last = 0.0


# ---- fetching ----------------------------------------------------------------

def get(url: str, retries: int = 3, missing_ok: bool = False):
    """GET JSON, at most one request every PAUSE seconds. 404 returns None when missing_ok."""
    global _last
    err = None
    for attempt in range(retries):
        wait = PAUSE - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json, text/plain, */*", "Accept-Encoding": "gzip",
            "Referer": f"{WWW}/leagues/{LEAGUE_ID}/overview/premier-league"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing_ok:
                return None
            err = e
        except Exception as e:  # network or JSON error
            err = e
        time.sleep(PAUSE * (attempt + 1))
    raise RuntimeError(f"{url}: {err}")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def record_health(ok: bool, detail: str, stats: dict | None = None) -> None:
    src = json.loads(SOURCES.read_text()) if SOURCES.exists() else {"sources": {}}
    s = src["sources"].setdefault("fotmob", {"name": "FotMob"})
    if ok:
        s.update(status="healthy", last_success=_now(), last_error=None, detail=detail)
        s.pop("offline_since", None)
        if stats:
            s.update(stats)
    else:
        # keep the last good data and its date; the app shows it with that date
        s.update(status="offline" if not s.get("last_success") else "stale",
                 last_error={"at": _now(), "message": detail[:300]})
        s.setdefault("offline_since", _now()[:10])
    src["updated_at"] = _now()
    SOURCES.write_text(json.dumps(src, indent=2, ensure_ascii=False) + "\n")


def match_path(mid) -> Path:
    return DIR / "matches" / f"{mid}.json.gz"


def _num(v):
    """'565 (92%)' -> 565, '1.88' -> 1.88, 64 -> 64, None -> None."""
    if v is None or isinstance(v, (int, float)):
        return v
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)", str(v))
    if not m:
        return None
    x = float(m.group(1))
    return int(x) if x.is_integer() and "." not in m.group(1) else x


def compact_match(mid: str, d: dict, hm: dict | None) -> dict:
    """Keep what derive() needs from matchDetails plus the heatmap points."""
    c, g = d["content"], d["general"]
    players = {}
    for p in (c.get("playerStats") or {}).values():
        s = {}
        for grp in p.get("stats") or []:
            for item in grp["stats"].values():
                k, st = item.get("key"), item.get("stat") or {}
                if not k or k in s or st.get("type") == "boolean":
                    continue
                v = st.get("value")
                s[k] = [v, st["total"]] if "total" in st and st.get("type") == "fractionWithPercentage" else v
        if not s.get("minutes_played"):
            continue  # unused substitute
        players[str(p["id"])] = {"n": p["name"], "opta": p.get("optaId"), "team": p["teamId"],
                                 "gk": bool(p.get("isGoalkeeper")), "s": s}
    team = {}
    for grp in (((c.get("stats") or {}).get("Periods") or {}).get("All") or {}).get("stats") or []:
        for item in grp.get("stats") or []:
            k, v = item.get("key"), item.get("stats")
            if k and v and v[0] is not None and k not in team:
                team[k] = [_num(v[0]), _num(v[1])]
    shots = [[s.get("playerId"), s.get("teamId"), s.get("x"), s.get("y"), round(s.get("expectedGoals") or 0, 4),
              round(s.get("expectedGoalsOnTarget") or 0, 4), s.get("eventType"), s.get("situation"),
              bool(s.get("isOwnGoal")), s.get("min")] for s in (c.get("shotmap") or {}).get("shots") or []]
    heat = None
    if hm and hm.get("players"):
        heat = {}
        for k, svg in hm["players"].items():
            pts = re.findall(r'cx="([\d.]+)" cy="([\d.]+)"', svg)
            heat[k.lstrip("p")] = [[round(float(x), 1), round(float(y), 1)] for x, y in pts]
    return {"id": int(mid), "round": g.get("matchRound"), "utc": d["header"]["status"].get("utcTime"),
            "home": {"id": g["homeTeam"]["id"], "name": g["homeTeam"]["name"]},
            "away": {"id": g["awayTeam"]["id"], "name": g["awayTeam"]["name"]},
            "score": d["header"]["status"].get("scoreStr"),
            "players": players, "team": team, "shots": shots,
            "shot_cols": ["player", "team", "x", "y", "xg", "xgot", "event", "situation", "own_goal", "min"],
            "heatmap": heat, "heatmap_modified": (hm or {}).get("lastModified"), "fetched_at": _now()}


def fetch() -> dict:
    """League file, the stat tables, then matchDetails + heatmap for finished matches not yet stored."""
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "matches").mkdir(exist_ok=True)
    (DIR / "stats").mkdir(exist_ok=True)
    lg = get(f"{WWW}/api/data/leagues?id={LEAGUE_ID}")
    det = lg.get("details") or {}
    if det.get("selectedSeason") != SEASON:
        raise RuntimeError(f"league {LEAGUE_ID} season is {det.get('selectedSeason')}, not {SEASON}")
    allm = (lg.get("fixtures") or {}).get("allMatches") or []
    links = {s["name"]: s["fetchAllUrl"] for grp in ("players", "teams") for s in (lg.get("stats") or {}).get(grp) or []
             if isinstance(s, dict) and s.get("fetchAllUrl")}
    sid = next((re.search(r"/season/(\d+)/", u).group(1) for u in links.values() if "/season/" in u), None)
    if not allm or not sid:
        raise RuntimeError("league file has no fixtures or no stat links")
    league = {"league_id": LEAGUE_ID, "season": SEASON, "season_id": int(sid), "fetched_at": _now(),
              "matches": [{"id": int(m["id"]), "round": m.get("round"), "home": m["home"], "away": m["away"],
                           "utc": m["status"].get("utcTime"), "finished": bool(m["status"].get("finished")),
                           "cancelled": bool(m["status"].get("cancelled")), "score": m["status"].get("scoreStr")}
                          for m in allm],
              "stat_links": links}
    (DIR / f"league_{LEAGUE_ID}.json").write_text(json.dumps(league, ensure_ascii=False, indent=0))

    tables = 0
    for name in PLAYER_TABLES + TEAM_TABLES:
        url = links.get(name) or f"https://data.fotmob.com/stats/{LEAGUE_ID}/season/{sid}/{name}.json"
        t = get(url)
        tl = (t.get("TopLists") or [{}])[0]
        rows = [{k: r.get(k) for k in ("ParticipantName", "ParticiantId", "TeamId", "TeamName", "StatValue",
                                        "SubStatValue", "MinutesPlayed", "MatchesPlayed")} for r in tl.get("StatList") or []]
        (DIR / "stats" / f"{name}.json").write_text(json.dumps(
            {"stat": name, "title": tl.get("Title"), "subtitle": tl.get("Subtitle"), "fetched_at": _now(),
             "rows": rows}, ensure_ascii=False, separators=(",", ":")))
        tables += 1

    done = [m for m in league["matches"] if m["finished"] and not m["cancelled"]]
    new = [m for m in done if not match_path(m["id"]).exists()]
    for i, m in enumerate(new, 1):
        d = get(f"{WWW}/api/data/matchDetails?matchId={m['id']}")
        hurl = (d.get("content") or {}).get("heatmapUrl")
        hm = get(WWW + hurl, missing_ok=True) if hurl else None
        cm = compact_match(str(m["id"]), d, hm)
        match_path(m["id"]).write_bytes(gzip.compress(json.dumps(cm, ensure_ascii=False, separators=(",", ":")).encode()))
        print(f"  match {m['id']} {m['home']['name']} v {m['away']['name']} ({i}/{len(new)})"
              f"{'' if cm['heatmap'] else ', no heatmap'}")
    print(f"fotmob: season {SEASON} (id {sid}), {len(allm)} fixtures, {len(done)} finished, "
          f"{len(new)} new matches fetched, {tables} stat tables")
    return {"season_id": int(sid), "finished": len(done), "new_matches": len(new)}


# ---- loading -------------------------------------------------------------------

def _load(path: Path):
    if not path.exists():
        return None
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def load_league() -> dict | None:
    return _load(DIR / f"league_{LEAGUE_ID}.json")


def load_matches() -> list[dict]:
    return sorted((_load(p) for p in (DIR / "matches").glob("*.json.gz")), key=lambda m: m["utc"])


def load_table(name: str) -> dict | None:
    return _load(DIR / "stats" / f"{name}.json")


# ---- the ID map ----------------------------------------------------------------------

def build_id_map(bs: dict, league: dict, matches: list[dict]) -> dict:
    """FPL element id -> FotMob player id, by team plus normalised name (engine/idmap.py).
    FotMob also gives each player's Opta id, which FPL calls "code": a name match
    whose Opta id disagrees is refused, and the Opta id alone matches the rest."""
    names = {}
    for m in league["matches"]:
        for side in ("home", "away"):
            names[str(m[side]["id"])] = [m[side]["name"], m[side].get("shortName") or m[side]["name"]]
    tmap, missing_teams = idmap.team_map(bs, names)
    pool, seen = defaultdict(dict), {}
    for m in matches:
        for pid, p in m["players"].items():
            fpl_team = tmap.get(str(p["team"]))
            if not fpl_team:
                continue
            r = pool[fpl_team].setdefault(pid, {"id": int(pid), "name": p["n"], "minutes": 0, "opta": p.get("opta")})
            r["minutes"] += int(p["s"].get("minutes_played") or 0)
            seen[pid] = (p["n"], p["team"])
    manual = {int(k): str(v) for k, v in idmap.load("fotmob").get("manual", {}).items()}
    mapping, tiers, unmatched = idmap.match_players(bs, {t: list(v.values()) for t, v in pool.items()}, manual, "FotMob")
    players = [p for p in bs["elements"] if p["minutes"] > 0]
    claimed = set(mapping.values())
    tname = {str(k): v[0] for k, v in names.items()}
    mins = defaultdict(int)
    for t in pool.values():
        for pid, r in t.items():
            mins[pid] += r["minutes"]
    left = sorted(({"id": int(pid), "name": n, "team": tname.get(str(t), str(t)), "minutes": mins[pid]}
                   for pid, (n, t) in seen.items() if pid not in claimed and mins[pid] > 0), key=lambda r: -r["minutes"])
    rate = round(100 * len(mapping) / max(1, len(players)), 1)
    by_name = sum(v for k, v in tiers.items() if 1 <= k <= 5)
    doc = {
        "built_at": _now(), "season": SEASON,
        "match_rate": {"matched": len(mapping), "of": len(players), "pct": rate,
                       "by_name": by_name, "by_name_pct": round(100 * by_name / max(1, len(players)), 1),
                       "basis": "FPL players with minutes this season", "by_tier": tiers},
        "teams": {str(v): int(k) for k, v in tmap.items()},
        "manual": {str(k): v for k, v in manual.items()},
        "players": {str(k): int(v) for k, v in sorted(mapping.items())},
    }
    idmap.save("fotmob", doc, {"built_at": doc["built_at"], "missing_teams": missing_teams,
                               "fpl_unmatched": unmatched, "fotmob_unclaimed": left})
    print(f"id map (fotmob): {len(mapping)}/{len(players)} matched ({rate}%; {by_name} by name), "
          f"{len(unmatched)} unmatched, teams missing: {missing_teams or 'none'}")
    return doc


# ---- derived stats ----------------------------------------------------------------------

# Our key -> FotMob match stat key. Fractions are [won, total].
COUNT = {"cc": "chances_created", "bcc": "big_chance_created_team_title", "tib": "touches_opp_box",
         "int": "interceptions", "rec": "recoveries", "disp": "dispossessed", "lbp": "line_breaking_passes",
         "pf3": "passes_into_final_third"}
FRAC = {"drb": "dribbles_succeeded", "gd": "ground_duels_won", "ad": "aerials_won"}
PER90 = ["cc", "bcc", "tib", "int", "rec", "disp", "lbp", "pf3", "xgot", "drb", "gd", "ad"]
SET_PIECE = {"FromCorner", "SetPiece", "FreeKick", "ThrowInSetPiece", "IndirectFreeKick"}

# heatmap grid: 21 x 14 cells of 5 m x 4.86 m on a 105 x 68 pitch, attacking left to right
GX, GY = 21, 14
B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def grid(points: list) -> list[int]:
    g = [0] * (GX * GY)
    for x, y in points:
        i = min(GX - 1, max(0, int(x / 105 * GX)))
        j = min(GY - 1, max(0, int(y / 68 * GY)))
        g[j * GX + i] += 1
    return g


def enc(g: list[int]) -> str:
    """One base-36 character per cell, row by row (counts above 35 clamp to 35)."""
    return "".join(B36[min(35, v)] for v in g)


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def _per90(v, mins):
    return _r(v * 90 / mins, 2) if mins and v is not None else None


def _pct(a, b):
    return round(100 * a / b) if b else None


def _player_block(rows: list[dict]) -> dict:
    """Totals, per 90 and percentages over a list of per-match rows."""
    mins = sum(r["min"] for r in rows)
    pmin = sum(r["min"] for r in rows if r["dist"] is not None)  # minutes with tracking data
    o = {"games": len(rows), "min": mins}
    for k in COUNT:
        o[k] = sum(r[k] for r in rows)
    o["xgot"] = _r(sum(r["xgot"] for r in rows))
    for k in FRAC:
        o[k] = [sum(r[k][0] for r in rows), sum(r[k][1] for r in rows)]
        o[k + "_pct"] = _pct(*o[k])
    o["dist"] = _r(sum(r["dist"] for r in rows if r["dist"] is not None) / 1000, 1) if pmin else None  # km
    o["spr"] = sum(r["spr"] for r in rows if r["spr"] is not None) if pmin else None
    o["top"] = _r(max((r["top"] for r in rows if r["top"] is not None), default=None), 1)
    o["phys_min"] = pmin
    p90 = {k: _per90(o[k][0] if k in FRAC else o[k], mins) for k in PER90}
    p90["dist"] = _per90(o["dist"], pmin)
    p90["spr"] = _per90(o["spr"], pmin)
    o["p90"] = p90
    return o


def _team_block(rows: list[dict]) -> dict | None:
    n = len(rows)
    if not n:
        return None
    o = {"games": n}
    for k in ("xg", "xga", "bc", "bca", "tib", "tiba", "spg", "spga"):
        vals = [r[k] for r in rows if r[k] is not None]
        o[k] = _r(sum(vals)) if vals else None
        o[k + "_pg"] = _r(sum(vals) / len(vals)) if vals else None
    d = [r["dist"] for r in rows if r["dist"] is not None]
    o["dist_pg"] = _r(sum(d) / len(d) / 1000, 1) if d else None  # km per match
    o["dist_games"] = len(d)
    p = [r["poss"] for r in rows if r["poss"] is not None]
    o["poss"] = _r(sum(p) / len(p), 1) if p else None
    return o


def checks(players: dict, teams: dict, idm: dict, matches: list[dict]) -> dict:
    """Our season sums against FotMob's own season tables (what fotmob.com shows)."""
    fm_to_fpl = {int(v): k for k, v in idm["players"].items()}
    out = {}

    def cmp(name, ours, field="StatValue", tol=0.011):
        t = load_table(name)
        if not t:
            return
        n = ok = 0
        worst = None
        for r in t["rows"]:
            k = fm_to_fpl.get(r["ParticiantId"]) if not name.endswith("_team") else fm_team.get(r["TeamId"])
            if k is None or ours(k) is None or r.get(field) is None:
                continue
            a, b = float(ours(k)), float(r[field])
            n += 1
            if abs(a - b) <= max(tol * abs(b), 0.051):
                ok += 1
            elif not worst or abs(a - b) > abs(worst[1] - worst[2]):
                worst = [r["ParticipantName"], round(a, 2), round(b, 2)]
        out[name] = {"compared": n, "agree": ok, "worst": worst}

    fm_team = {int(v): str(k) for k, v in idm["teams"].items()}
    P = lambda k, f: (players.get(k) or {}).get("s", {}).get(f) if players.get(k) else None  # noqa: E731
    cmp("mins_played", lambda k: P(k, "min"))
    cmp("total_att_assist", lambda k: P(k, "cc"))
    cmp("big_chance_created", lambda k: P(k, "bcc"))
    cmp("expected_goalsontarget", lambda k: P(k, "xgot"))
    cmp("phys_tdc", lambda k: P(k, "dist") * 1000 if P(k, "dist") is not None else None)
    cmp("phys_sprints", lambda k: P(k, "spr"))
    cmp("phys_ts", lambda k: P(k, "top"))
    # per-90 tables: SubStatValue is the season total
    cmp("interception", lambda k: P(k, "int"), field="SubStatValue")
    cmp("ball_recovery", lambda k: P(k, "rec"), field="SubStatValue")
    cmp("lbp_total", lambda k: P(k, "lbp"), field="SubStatValue")
    cmp("won_contest", lambda k: (P(k, "p90") or {}).get("drb"))  # per 90 (SubStatValue is the success %)
    T = lambda k, f: ((teams.get(k) or {}).get("s") or {}).get(f)  # noqa: E731
    cmp("phys_tdc_team", lambda k: T(k, "dist_pg") * 1000 if T(k, "dist_pg") is not None else None, tol=0.02)
    cmp("expected_goals_conceded_team", lambda k: T(k, "xga"))
    cmp("big_chance_team", lambda k: T(k, "bc"))
    cmp("touches_in_opp_box_team", lambda k: T(k, "tib"))
    cmp("_set_piece_goals_team", lambda k: T(k, "spg"))
    cmp("_set_piece_goals_conceded_team", lambda k: T(k, "spga"))
    cmp("possession_percentage_team", lambda k: T(k, "poss"), tol=0.02)
    return out


def derive(bs: dict, fixtures: list) -> dict:
    """Player and team stats keyed by FPL id, from the cached league file and matches."""
    league = load_league()
    if not league:
        raise RuntimeError("no FotMob league data on disk")
    matches = load_matches()
    idm = build_id_map(bs, league, matches)
    tmap = {int(fm): int(fpl) for fpl, fm in idm["teams"].items()}  # FotMob team id -> FPL team id
    p_fm = {int(v): int(k) for k, v in idm["players"].items()}  # FotMob player id -> FPL id
    fx_gw = {(f["team_h"], f["team_a"]): f["event"] for f in fixtures if f.get("event")}

    apps = defaultdict(list)
    team_rows = defaultdict(list)
    for m in matches:
        th, ta = tmap.get(m["home"]["id"]), tmap.get(m["away"]["id"])
        gw = fx_gw.get((th, ta))
        date = m["utc"][:10]
        heat = m.get("heatmap") or {}
        for pid, p in m["players"].items():
            e = p_fm.get(int(pid))
            s = p["s"]
            mins = int(s.get("minutes_played") or 0)
            if not e or mins <= 0:
                continue
            home = tmap.get(p["team"]) == th
            row = {"mid": m["id"], "date": date, "gw": gw, "opp": ta if home else th, "home": home, "min": mins,
                   "xgot": float(s.get("expected_goals_on_target_variant") or 0),
                   "dist": s.get("physical_metrics_distance_covered"),
                   "spr": s.get("physical_metrics_number_of_sprints"),
                   "top": s.get("physical_metrics_topspeed")}
            for k, fk in COUNT.items():
                row[k] = int(s.get(fk) or 0)
            for k, fk in FRAC.items():
                v = s.get(fk)
                row[k] = [int(v[0] or 0), int(v[1] or 0)] if isinstance(v, list) else [0, 0]
            pts = heat.get(str(p.get("opta"))) if p.get("opta") else None
            row["heat"] = grid(pts) if pts else None
            apps[e].append(row)
        # teams: one row per side
        t = m["team"]
        own_goals = defaultdict(lambda: [0, 0])  # fotmob team -> [set-piece goals, ...]
        for sh in m["shots"]:
            if sh[6] == "Goal" and sh[7] in SET_PIECE:
                own_goals[sh[1]][0] += 1
        for side, i in (("home", 0), ("away", 1)):
            fpl = tmap.get(m[side]["id"])
            if not fpl:
                continue
            opp = m["away" if side == "home" else "home"]["id"]
            g = lambda k, j: (t.get(k) or [None, None])[j]  # noqa: E731
            team_rows[fpl].append({
                "date": date, "gw": gw, "xg": g("expected_goals", i), "xga": g("expected_goals", 1 - i),
                "bc": g("big_chance", i), "bca": g("big_chance", 1 - i),
                "tib": g("touches_opp_box", i), "tiba": g("touches_opp_box", 1 - i),
                "spg": own_goals[m[side]["id"]][0], "spga": own_goals[opp][0],
                "dist": g("physical_metrics_distance_covered", i), "poss": g("BallPossesion", i)})

    players = {}
    for e, rows in apps.items():
        rows.sort(key=lambda r: r["date"])
        last = rows[-4:]
        l4 = _player_block(last)
        l4["gws"] = [r["gw"] for r in last]
        l4["minutes"] = [r["min"] for r in last]
        season_heat = [0] * (GX * GY)
        n_heat = 0
        for r in rows:
            if r["heat"]:
                season_heat = [a + b for a, b in zip(season_heat, r["heat"])]
                n_heat += 1
        players[str(e)] = {
            "fm_id": int(idm["players"][str(e)]),
            "s": _player_block(rows), "l4": l4,
            "heat": {"grid": [GX, GY], "season": season_heat if n_heat else None, "season_games": n_heat,
                     "matches": [[r["gw"], r["opp"], 1 if r["home"] else 0, r["min"], r["date"], enc(r["heat"])]
                                 for r in rows if r["heat"]]},
        }

    teams = {}
    for fpl, rows in team_rows.items():
        rows.sort(key=lambda r: r["date"])
        teams[str(fpl)] = {"s": _team_block(rows), "l4": _team_block(rows[-4:]),
                           "l4_dates": [r["date"] for r in rows[-4:]]}

    latest = max((m["utc"] for m in matches), default=None)
    out = {
        "source": "FotMob", "season": SEASON, "built_at": _now(),
        "league_fetched_at": league.get("fetched_at"),
        "data_to": latest[:10] if latest else None,
        "matches": len(matches), "heatmap_matches": sum(1 for m in matches if m.get("heatmap")),
        "id_map": idm["match_rate"],
        "heat_cols": ["gw", "opp", "home", "min", "date", "grid"],
        "players": players, "teams": teams,
    }
    out["checks"] = checks(players, teams, idm, matches)
    (DIR / "derived.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    agree = sum(c["agree"] for c in out["checks"].values())
    comp = sum(c["compared"] for c in out["checks"].values())
    print(f"derived: {len(players)} players, {len(teams)} teams, {len(matches)} matches, data to {out['data_to']}; "
          f"{agree}/{comp} season values agree with FotMob's tables")
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
            print(f"fotmob: fetch failed, recorded in data/sources.json: {e}")
            if not load_league():
                return  # nothing cached yet: the app shows the offline note
            offline = True  # derive from the last good cache
    d = derive(bs, fx)
    if not offline:
        record_health(True, f"{d['matches']} matches to {d['data_to']}; id map {d['id_map']['pct']}%",
                      {"data_to": d["data_to"], **stats})
