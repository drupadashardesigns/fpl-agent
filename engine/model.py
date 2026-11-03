"""Version 0 expected-points model.

Inputs come only from the official FPL API:
  * team attack from summed player xG, team defence from keeper xG conceded,
    both shrunk toward the league mean
  * per-90 player rates (xG, xA, bonus, saves) blended with positional priors
  * expected minutes from the last four gameweeks, cut by injury flags
  * DefCon chance from defensive_contribution_per_90 (Poisson tail)

Known weaknesses, in priority order (see CLAUDE.md roadmap):
  1. Minutes: no rotation or substitution model.
  2. No betting-market input for team strength.
  3. Premium attackers' hauls are compressed (no finishing skill, no
     separate penalty model).
  4. Bonus is a flat per-90 rate, not a BPS model.
"""
from __future__ import annotations

import math
from collections import defaultdict

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {1: 10, 2: 6, 3: 5, 4: 4}        # 2026/27: keeper goals are worth 10
CS_PTS = {1: 4, 2: 4, 3: 1, 4: 0}
DEFCON_THRESHOLD = {1: 10**9, 2: 10, 3: 12, 4: 12}
PRIOR = {  # per-90 priors: xG, xA, bonus, saves
    1: (0.0, 0.01, 0.12, 2.8),
    2: (0.04, 0.06, 0.15, 0.0),
    3: (0.12, 0.12, 0.18, 0.0),
    4: (0.30, 0.10, 0.22, 0.0),
}
HOME_ADV = 1.12
SHRINK_MINUTES = 450      # prior weight, in minutes, for per-90 rates
TEAM_PRIOR_GAMES = 4      # prior weight, in games, for team strength
RECENT_WEIGHTS = (0.15, 0.20, 0.30, 0.35)  # oldest to newest of last 4 GWs


def _pois_at_least(mu: float, k: int) -> float:
    if mu <= 0:
        return 0.0
    return max(0.0, 1 - sum(math.exp(-mu) * mu**i / math.factorial(i) for i in range(k)))


def _expected_half_conceded(mu: float) -> float:
    """E[floor(G / 2)] for G ~ Poisson(mu): the -1 per two goals conceded."""
    return sum((g // 2) * math.exp(-mu) * mu**g / math.factorial(g) for g in range(12))


def played(f: dict) -> bool:
    """A fixture counts once it has a provisional result. FPL can leave `finished`
    false for a day or more after full time (seen with GW9), which made the model
    treat the last gameweek as unplayed."""
    return bool(f.get("finished") or f.get("finished_provisional"))


def team_strength(bs: dict, fixtures: list) -> tuple[dict, dict, float]:
    done = [f for f in fixtures if played(f)]
    games = defaultdict(int)
    for f in done:
        games[f["team_h"]] += 1
        games[f["team_a"]] += 1
    xgf, xga, gk_mins = defaultdict(float), defaultdict(float), defaultdict(float)
    for p in bs["elements"]:
        xgf[p["team"]] += float(p["expected_goals"])
        if p["element_type"] == 1 and p["minutes"] > 0:
            xga[p["team"]] += float(p["expected_goals_conceded"])
            gk_mins[p["team"]] += p["minutes"]
    league = sum(xgf.values()) / max(sum(games.values()), 1)
    att, dfn = {}, {}
    for t in (team["id"] for team in bs["teams"]):
        g = games[t]
        att[t] = ((xgf[t] + TEAM_PRIOR_GAMES * league) / (g + TEAM_PRIOR_GAMES)) / league
        ga90 = xga[t] / max(gk_mins[t] / 90, 1)
        dfn[t] = ((ga90 * g + TEAM_PRIOR_GAMES * league) / (g + TEAM_PRIOR_GAMES)) / league
    return att, dfn, league


def expected_minutes(p: dict, summary: dict | None, last_gw: int, team_games: int) -> float:
    if not summary:
        return 0.0
    by_gw = defaultdict(int)
    for r in summary.get("history", []):
        if r["round"] > last_gw - 4:
            by_gw[r["round"]] += r["minutes"]
    recent = [by_gw.get(g, 0) for g in range(last_gw - 3, last_gw + 1)]
    m = sum(a * w for a, w in zip(recent, RECENT_WEIGHTS))
    m = 0.75 * m + 0.25 * (p["minutes"] / max(team_games, 1))
    chance = p["chance_of_playing_next_round"]
    if chance is None and p["status"] in ("i", "s", "u", "n"):
        chance = 0
    if chance is not None:
        m *= chance / 100
    return min(m, 90.0)


def _rate(p: dict, field: str, prior: float) -> float:
    return (float(p[field]) + prior * SHRINK_MINUTES / 90) / ((p["minutes"] + SHRINK_MINUTES) / 90)


def fixture_points(p: dict, f: dict, xm: float, att: dict, dfn: dict, league: float) -> dict:
    team, et = p["team"], p["element_type"]
    home = f["team_h"] == team
    opp = f["team_a"] if home else f["team_h"]
    lam_for = league * att[team] * dfn[opp] * (HOME_ADV if home else 1 / HOME_ADV)
    lam_against = league * att[opp] * dfn[team] * (1 / HOME_ADV if home else HOME_ADV)
    mult = lam_for / (league * att[team])
    frac = xm / 90
    p_any = min(1.0, xm / 30) if xm > 0 else 0.0
    p60 = max(0.0, min(1.0, (xm - 25) / 60))

    xg = _rate(p, "expected_goals", PRIOR[et][0]) * frac * mult
    xa = _rate(p, "expected_assists", PRIOR[et][1]) * frac * mult
    p_cs = math.exp(-lam_against)
    parts = {
        "appearance": p_any + p60,
        "goals": GOAL_PTS[et] * xg,
        "assists": 3 * xa,
        "clean_sheet": CS_PTS[et] * p60 * p_cs,
        "conceded": -p60 * _expected_half_conceded(lam_against * frac) if et in (1, 2) else 0.0,
        "defcon": 2 * _pois_at_least(float(p.get("defensive_contribution_per_90") or 0) * frac,
                                     DEFCON_THRESHOLD[et]) if et != 1 else 0.0,
        "saves": (_rate(p, "saves", PRIOR[1][3]) * frac * lam_against / league) / 3 if et == 1 else 0.0,
        "bonus": _rate(p, "bonus", PRIOR[et][2]) * frac * (0.6 + 0.4 * mult),
    }
    return {
        "xp": sum(parts.values()), "parts": parts, "xg": xg, "xa": xa, "cs": p_cs,
        "opp": opp, "home": home, "lam_for": lam_for, "lam_against": lam_against,
    }


def project(bs: dict, fixtures: list, summaries: dict[int, dict], gw_from: int, gw_to: int) -> dict:
    """Return {"players": {id: {...}}, "teams": {...}, "league_xg": float}."""
    att, dfn, league = team_strength(bs, fixtures)
    done = [f for f in fixtures if played(f)]
    last_gw = max((f["event"] for f in done), default=0)
    games = defaultdict(int)
    for f in done:
        games[f["team_h"]] += 1
        games[f["team_a"]] += 1
    short = {t["id"]: t["short_name"] for t in bs["teams"]}
    by_gw = defaultdict(list)
    for f in fixtures:
        if f["event"]:
            by_gw[f["event"]].append(f)

    players = {}
    for p in bs["elements"]:
        xm = expected_minutes(p, summaries.get(p["id"]), last_gw, games[p["team"]])
        weeks = {}
        for g in range(gw_from, gw_to + 1):
            fx = [fixture_points(p, f, xm, att, dfn, league)
                  for f in by_gw[g] if p["team"] in (f["team_h"], f["team_a"])]
            weeks[g] = {
                "xp": round(sum(x["xp"] for x in fx), 2),
                "fixtures": [{"opp": short[x["opp"]], "home": x["home"],
                              "xp": round(x["xp"], 2), "xg": round(x["xg"], 3),
                              "xa": round(x["xa"], 3), "cs": round(x["cs"], 3)} for x in fx],
            }
        players[p["id"]] = {
            "id": p["id"], "name": p["web_name"], "team_id": p["team"], "team": short[p["team"]],
            "pos": POS[p["element_type"]], "et": p["element_type"], "cost": p["now_cost"] / 10,
            "own": float(p["selected_by_percent"]), "xmins": round(xm, 1),
            "status": p["status"], "news": p["news"], "weeks": weeks,
        }
    teams = {t: {"name": short[t], "attack": round(att[t], 3), "defence": round(dfn[t], 3)} for t in att}
    return {"players": players, "teams": teams, "league_xg": league, "gw_from": gw_from, "gw_to": gw_to}
