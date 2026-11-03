"""Build the app's data bundle for one weekly run: data/runs/gwNN/app.json.

The app is static HTML that reads this file plus editions/gwNN.json. Everything
here is computed from inputs already on disk, so it runs without network:

  data/archive/<date>/bootstrap.json.gz, fixtures.json.gz   (nightly snapshot;
      bootstrap carries "fetched_at", the time it was read from FPL)
  data/runs/gwNN/facts.json, projections.json.gz, ownership.json   (weekly run)
  data/runs/gwNN/entry_history.json    (optional: rank history for the archive)
  data/runs/gwNN/history.json.gz       (optional: per-player gameweek rows)
  data/understat/derived.json          (optional: Understat stats keyed by FPL id,
      from `python -m engine understat`; kept under "us" keys, never mixed with FPL's xG)

    python -m engine appdata             newest run, newest snapshot
    python -m engine appdata --gw 10

Numbers labelled "calc" in design/mockups/Params.dc.html are computed here.
Nothing is estimated to fill a gap: a missing input leaves its field null and
the app says what is missing.
"""
from __future__ import annotations

import gzip
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from . import model, planner

ROOT = Path(__file__).resolve().parents[1]
SIMS = 20000
HAUL, BLANK = 10, 2
HIT_MARGIN = 2.0  # keep in step with cli.HIT_MARGIN
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# Chip calendar. First-half facts are from the live feed; second-half blanks
# and doubles are forecasts from the cup schedules (CLAUDE.md roadmap item 6).
CHIP_PLAN = {
    "festive": [17, 18, 19],
    "forecast": {"30": "BGW", "32": "DGW", "33": "BGW", "35": "DGW?", "36": "DGW?"},
    "chips": [
        {"id": "fh1", "label": "Free Hit (first set)", "win": [18, 19], "when": "GW18 or GW19, decided on 26 Dec",
         "why": "No blanks before GW19, so it is about cover for the festive run, when three deadlines fall in seven days."},
        {"id": "wc2", "label": "Wildcard", "win": [31], "when": "Around GW31, just before the forecast doubles",
         "why": "Builds a squad with double-gameweek players for GW32 and GW35 or 36, then rides it into the Bench Boost."},
        {"id": "bb2", "label": "Bench Boost", "win": [32, 35, 36], "when": "The biggest double: GW32, or GW35 or 36",
         "why": "All 15 players count, so it pays most when most of your squad plays twice."},
        {"id": "fh2", "label": "Free Hit", "win": [30, 33], "when": "A blank: GW33, or GW30",
         "why": "Fields a full eleven in a week when many teams have no game, without wrecking your squad."},
        {"id": "tc2", "label": "Triple Captain", "win": [32, 35, 36], "when": "A premium with two good fixtures in one double",
         "why": "Two games at triple points. Pick it once the doubles are confirmed and you can see the fixtures."},
    ],
}


def _load(path: Path):
    if not path.exists():
        return None
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def _r(x, n=2):
    return None if x is None else round(float(x), n)


# ---- simulation -------------------------------------------------------------

def _pois(rng: random.Random, mu: float) -> int:
    if mu <= 0:
        return 0
    L, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def simulate(p: dict, fixtures: list[dict], xm: float, att, dfn, league, sims: int = SIMS, seed: int = 0):
    """Chance of 10+ and of 2 or fewer points in one gameweek, by Monte Carlo on
    the same inputs as model.fixture_points. Bonus is drawn as 1 to 3 points
    with the model's expected bonus; this is the v0 model, not a BPS model."""
    if not fixtures or xm <= 0:
        return None, None
    et = p["element_type"]
    rng = random.Random(seed or p["id"])
    specs = []
    for f in fixtures:
        x = model.fixture_points(p, f, xm, att, dfn, league)
        pa = min(1.0, xm / 30)
        p60 = max(0.0, min(1.0, (xm - 25) / 60))
        if pa <= 0:
            continue
        specs.append({
            "pa": pa, "p60c": p60 / pa, "g": x["xg"] / pa, "a": x["xa"] / pa, "cs": x["cs"],
            "lam": x["lam_against"], "dc": min(1.0, x["parts"]["defcon"] / 2 / pa),
            "sv": x["parts"]["saves"] * 3 / pa, "b": x["parts"]["bonus"] / pa,
        })
    haul = blank = 0
    for _ in range(sims):
        tot = 0
        for s in specs:
            if rng.random() >= s["pa"]:
                continue
            sixty = rng.random() < s["p60c"]
            pts = 2 if sixty else 1
            pts += model.GOAL_PTS[et] * _pois(rng, s["g"]) + 3 * _pois(rng, s["a"])
            if sixty and et in (1, 2, 3) and rng.random() < s["cs"]:
                pts += model.CS_PTS[et]
            if sixty and et in (1, 2):
                pts -= _pois(rng, s["lam"]) // 2
            if et != 1 and rng.random() < s["dc"]:
                pts += 2
            if et == 1:
                pts += _pois(rng, s["sv"]) // 3
            if rng.random() < min(0.9, s["b"] / 2):
                pts += rng.randint(1, 3)
            tot += pts
        haul += tot >= HAUL
        blank += tot <= BLANK
    return round(100 * haul / sims), round(100 * blank / sims)


# ---- builders -----------------------------------------------------------------

def team_table(bs: dict, fixtures: list) -> dict:
    short = {t["id"]: t["short_name"] for t in bs["teams"]}
    rows = {t["id"]: {"id": t["id"], "short": t["short_name"], "name": t["name"], "gp": 0, "w": 0, "d": 0, "l": 0,
                      "gf": 0, "ga": 0, "cs": 0, "pts": 0, "hp": 0, "hg": 0, "ap": 0, "ag": 0, "res": []}
            for t in bs["teams"]}
    done = sorted((f for f in fixtures if model.played(f)), key=lambda f: f["kickoff_time"] or "")
    for f in done:
        for side, opp in (("h", "a"), ("a", "h")):
            t = rows[f[f"team_{side}"]]
            gf, ga = f[f"team_{side}_score"], f[f"team_{opp}_score"]
            res = "W" if gf > ga else "D" if gf == ga else "L"
            p = {"W": 3, "D": 1, "L": 0}[res]
            t["gp"] += 1
            t[res.lower()] += 1
            t["gf"] += gf
            t["ga"] += ga
            t["cs"] += ga == 0
            t["pts"] += p
            t["hp" if side == "h" else "ap"] += p
            t["hg" if side == "h" else "ag"] += 1
            t["res"].append(res)
    order = sorted(rows.values(), key=lambda t: (-t["pts"], -(t["gf"] - t["ga"]), -t["gf"], t["short"]))
    for i, t in enumerate(order):
        t["pos"] = i + 1
        t["form"] = "".join(t["res"][-5:])
        t["hppg"] = _r(t["hp"] / t["hg"]) if t["hg"] else None
        t["appg"] = _r(t["ap"] / t["ag"]) if t["ag"] else None
        for k in ("res", "hp", "hg", "ap", "ag"):
            t.pop(k)
    # season xG for and against per game, the same inputs the model uses
    xgf, xga, gkm = defaultdict(float), defaultdict(float), defaultdict(float)
    for p in bs["elements"]:
        xgf[p["team"]] += float(p["expected_goals"])
        if p["element_type"] == 1 and p["minutes"] > 0:
            xga[p["team"]] += float(p["expected_goals_conceded"])
            gkm[p["team"]] += p["minutes"]
    for t in rows.values():
        t["xgf"] = _r(xgf[t["id"]] / t["gp"]) if t["gp"] else None
        t["xga"] = _r(xga[t["id"]] / max(gkm[t["id"]] / 90, 1))
        t["xg_total"] = _r(xgf[t["id"]])
    for key, rev in (("xgf", True), ("xga", False)):
        for i, t in enumerate(sorted(rows.values(), key=lambda t: t[key] or 0, reverse=rev)):
            t[key + "_rank"] = i + 1
    return {str(k): v for k, v in rows.items()}, short


def team_fixtures(bs, fixtures, att, dfn, league, short, g0, g1) -> dict:
    out = {str(t["id"]): {} for t in bs["teams"]}
    for f in fixtures:
        if not f["event"] or not (g0 <= f["event"] <= g1):
            continue
        for side in ("h", "a"):
            t, o = f[f"team_{side}"], f["team_a" if side == "h" else "team_h"]
            home = side == "h"
            lf = league * att[t] * dfn[o] * (model.HOME_ADV if home else 1 / model.HOME_ADV)
            la = league * att[o] * dfn[t] * (1 / model.HOME_ADV if home else model.HOME_ADV)
            out[str(t)].setdefault(str(f["event"]), []).append(
                {"opp": short[o], "home": home, "g": _r(lf), "cs": round(100 * math.exp(-la))})
    return out


def newest_snapshot(look_back: int = 4):
    """The freshest snapshot by the fetch time stamped inside bootstrap.json, not by
    folder name. Snapshots from before the stamp existed sort last among equals
    and report no fetch time rather than a guessed one."""
    folders = sorted((ROOT / "data" / "archive").glob("20*"))[-look_back:]
    best = None
    for f in folders:
        b = _load(f / "bootstrap.json.gz")
        if b is None:
            continue
        key = (b.get("fetched_at") or "", f.name)
        if best is None or key > best[0]:
            best = (key, f, b)
    return best[1], best[2]


def build(gw: int | None = None, snapshot: str | None = None) -> Path:
    runs = sorted((ROOT / "data" / "runs").glob("gw*"))
    run = ROOT / "data" / "runs" / f"gw{gw:02d}" if gw else runs[-1]
    if snapshot:
        snap = ROOT / "data" / "archive" / snapshot
        bs = _load(snap / "bootstrap.json.gz")
    else:
        snap, bs = newest_snapshot()
    fx = _load(snap / "fixtures.json.gz")
    facts = _load(run / "facts.json")
    proj = _load(run / "projections.json.gz")
    own = _load(run / "ownership.json")
    ehist = _load(run / "entry_history.json")
    phist = _load(run / "history.json.gz")

    gw = facts["gw"]
    g0, g1 = facts["model"]["horizon"]
    gmax = proj["gw_to"]
    att, dfn, league = model.team_strength(bs, fx)
    teams, short = team_table(bs, fx)
    tfx = team_fixtures(bs, fx, att, dfn, league, short, gw, gmax)
    for tid, t in teams.items():
        t["att"] = proj["teams"][tid]["attack"]
        t["dfn"] = proj["teams"][tid]["defence"]
        t["next"] = tfx[tid]

    pl = planner.Planner(proj, g0, g1)
    squad = [s["id"] for s in facts["squad"]]
    sell = {s["id"]: s["sell"] for s in facts["squad"]}
    state = planner.SquadState(squad=squad, bank=facts["state"]["bank"],
                               free_transfers=facts["state"]["free_transfers"], sell=sell)
    by_name = {}
    for e, v in pl.P.items():
        by_name.setdefault(f"{v['name']} ({v['team']})", e)
    ids = lambda names: [by_name[n] for n in names]

    def h6(e):  # plain sum over the horizon, the number the screens show
        return round(sum(pl.xp(e, g) for g in range(g0, g1 + 1)), 1)

    # ---- plans ------------------------------------------------------------
    rec = facts["recommended"]
    call_out, call_in = ids(rec["outs"]), ids(rec["ins"])
    after = [e for e in squad if e not in call_out] + call_in
    base = pl.value(squad)

    def evaluate(outs, ins):
        sq = [e for e in squad if e not in outs] + list(ins)
        spend = sum(pl.P[e]["cost"] for e in ins) - sum(sell[e] for e in outs)
        hits = max(0, len(outs) - state.free_transfers) * planner.HIT
        return {"outs": list(outs), "ins": list(ins), "gain": round(pl.value(sq) - base - hits, 2), "hits": hits,
                "bank_after": round(state.bank - spend, 1), "legal": pl._legal(sq),
                "affordable": spend <= state.bank + 1e-9}

    def ft_next(n):
        return min(5, state.free_transfers - n + 1) if n <= state.free_transfers else 1

    peer = lambda e: round(100 * own["peers"]["own"].get(str(e), 0)) if own else None
    opts = [{**o, "outs": ids(o["outs"]), "ins": ids(o["ins"])} for o in facts["transfer_options"]]
    nm = lambda e: pl.P[e]["name"]
    plans = [{"id": "call", "name": "The call", **{k: rec[k] for k in ("gain", "hits", "bank_after")},
              "outs": call_out, "ins": call_in,
              "verdict": "Best plan that costs no hit. Sells the two players in your squad with the lowest expected minutes."
              if sorted(call_out, key=lambda e: pl.P[e]["xmins"]) == sorted(squad, key=lambda e: pl.P[e]["xmins"])[:2]
              else "Best plan that costs no hit."}]
    hit = max((o for o in opts if o["hits"] > 0), key=lambda o: o["gain"], default=None)
    if hit:
        extra = [e for e in hit["ins"] if e not in call_in]
        d = hit["gain"] - rec["gain"]
        plans.append({"id": "hit", "name": f"Add {', '.join(nm(e) for e in extra)} for -{hit['hits']}", **hit,
                      "verdict": f"Projects {d:+.1f} against the call after the -{hit['hits']}. A hit needs to beat the best "
                                 f"free plan by {HIT_MARGIN:g} points to be worth it, so this one "
                                 f"{'does' if d >= HIT_MARGIN else 'does not'}."})
    alt = next((o for o in opts if o["hits"] == 0 and set(o["outs"]) == set(call_out) and set(o["ins"]) != set(call_in)), None)
    if alt:
        new = [e for e in alt["ins"] if e not in call_in][0]
        old = [e for e in call_in if e not in alt["ins"]][0]
        plans.append({"id": "alt", "name": f"{nm(new)} instead of {nm(old)}", **alt,
                      "verdict": f"{rec['gain'] - alt['gain']:.1f} behind the call over six gameweeks. {nm(new)} is in "
                                 f"{peer(new)}% of teams near your rank against {peer(old)}% for {nm(old)}, so it is the "
                                 f"more differential version."})
    singles = [evaluate([o], [i]) for o, i in zip(call_out, call_in)]
    one = max(singles, key=lambda r: r["gain"])
    kept = [e for e in call_out if e not in one["outs"]][0]
    plans.append({"id": "one", "name": f"{nm(one['ins'][0])} only, roll one", **one,
                  "verdict": f"Keeps a second free transfer for GW{gw + 1}, but keeps {nm(kept)}, who expects "
                             f"{pl.P[kept]['xmins']:.0f} minutes a game, for another week. "
                             f"{rec['gain'] - one['gain']:.1f} behind the call."})
    plans.append({"id": "roll", "name": "Roll both" if state.free_transfers == 2 else "Roll", "outs": [], "ins": [],
                  "gain": 0.0, "hits": 0, "bank_after": state.bank,
                  "verdict": f"Gives up about {rec['gain']:.0f} projected points over six gameweeks for "
                             f"{ft_next(0)} free transfers in GW{gw + 1}."})
    for p in plans:
        p["ft_next"] = ft_next(len(p["outs"]))
        p["gain"] = round(p["gain"], 1)

    # ---- builder: one move from the current squad -------------------------------
    outfield = sorted((e for e in squad if pl.P[e]["pos"] != "GK"), key=h6)
    b_outs = outfield[:6]
    b_ins = {}
    for pos in sorted({pl.P[e]["pos"] for e in b_outs}):
        cands = sorted((e for e, v in pl.P.items() if v["pos"] == pos and e not in squad and v["xmins"] >= 45),
                       key=pl.horizon_xp, reverse=True)[:5]
        b_ins[pos] = cands
    b_gain = {}
    for o in b_outs:
        for i in b_ins[pl.P[o]["pos"]]:
            r = evaluate([o], [i])
            b_gain[f"{o}>{i}"] = {"gain": round(r["gain"], 1), "bank": r["bank_after"],
                                  "ok": r["legal"] and r["affordable"], "legal": r["legal"]}

    # ---- line-ups and captain ------------------------------------------------------
    now_xi = pl.best_xi(squad, gw)
    aft_xi = pl.best_xi(after, gw)

    # ---- players ------------------------------------------------------------------
    B = {p["id"]: p for p in bs["elements"]}
    fx_gw = defaultdict(list)
    for f in fx:
        if f["event"]:
            fx_gw[f["event"]].append(f)
    template = [by_name[t["name"]] for t in (facts.get("template_gaps") or [])]
    watch = set(squad) | set(call_in) | {e for p in plans for e in p["ins"]} | set(template[:3])
    cap_pool = sorted(aft_xi["xi"], key=lambda e: -pl.xp(e, gw))[:6]
    hero = max(after, key=lambda e: (own["top10k"]["captain"].get(str(e), 0) if own else 0))
    if hero not in cap_pool:
        cap_pool.append(hero)
    players = {}
    for e, v in pl.P.items():
        p = B.get(e)
        if not p or (p["minutes"] == 0 and v["xmins"] == 0 and e not in watch):
            continue
        projs = {x["offset"]: float(x["projected_percent"]) for x in p.get("price_change_projections") or []}
        row = {
            "id": e, "n": p["web_name"], "first": p["first_name"], "last": p["second_name"],
            "t": short[p["team"]], "tid": p["team"], "pos": POSN[p["element_type"]],
            "cost": p["now_cost"] / 10, "chg": p["cost_change_start"] / 10,
            "status": p["status"], "news": p["news"], "chance": p["chance_of_playing_next_round"],
            "min": p["minutes"], "starts": p["starts"], "g": p["goals_scored"], "a": p["assists"],
            "xg": float(p["expected_goals"]), "xa": float(p["expected_assists"]),
            "xgi": float(p["expected_goal_involvements"]), "xgc": float(p["expected_goals_conceded"]),
            "cs": p["clean_sheets"], "gc": p["goals_conceded"], "saves": p["saves"],
            "bonus": p["bonus"], "bps": p["bps"], "inf": float(p["influence"]), "cre": float(p["creativity"]),
            "thr": float(p["threat"]), "ict": float(p["ict_index"]),
            "cbi": p["clearances_blocks_interceptions"], "tck": p["tackles"], "rec": p["recoveries"],
            "dc": p["defensive_contribution"], "dc90": float(p.get("defensive_contribution_per_90") or 0),
            "pts": p["total_points"], "ppg": float(p["points_per_game"]), "form": float(p["form"]),
            "sel": float(p["selected_by_percent"]), "tin": p["transfers_in_event"], "tout": p["transfers_out_event"],
            "pcp": float(p.get("price_change_percent") or 0), "pc0": projs.get(0), "pc1": projs.get(1),
            "locked": p.get("price_change_locked_until"),
            "pen": p["penalties_order"], "cor": p["corners_and_indirect_freekicks_order"],
            "dfk": p["direct_freekicks_order"],
            "xm": v["xmins"], "h6": h6(e),
            "w": {g: [v["weeks"][g]["xp"], [[x["opp"], 1 if x["home"] else 0, x["xp"]] for x in v["weeks"][g]["fixtures"]]]
                  for g in v["weeks"]},
        }
        if own:
            for k, src in (("o_top", own["top10k"]["own"]), ("o_peer", own["peers"]["own"]),
                           ("eo_top", own["top10k"]["eo"]), ("eo_peer", own["peers"]["eo"]),
                           ("cap_top", own["top10k"]["captain"])):
                row[k] = round(100 * src.get(str(e), 0), 1)
        if v["xmins"] > 0:
            fxs = [f for f in fx_gw[gw] if p["team"] in (f["team_h"], f["team_a"])]
            parts = defaultdict(float)
            for f in fxs:
                for k, x in model.fixture_points(p, f, v["xmins"], att, dfn, league)["parts"].items():
                    parts[k] += x
            row["parts"] = {k: round(x, 2) for k, x in parts.items()}
            row["haul"], row["blank"] = simulate(p, fxs, v["xmins"], att, dfn, league)
        players[str(e)] = row

    if phist:  # per-player gameweek rows saved by the weekly run
        for e, rows in phist.items():
            if e in players:
                players[e]["hist"] = rows

    # ---- Understat: a separate provider, kept under "us" --------------------------------
    us = _load(ROOT / "data" / "understat" / "derived.json")
    us_meta = None
    if us:
        top60 = sorted((k for k in players), key=lambda k: -players[k]["h6"])[:60]
        maps = {str(e) for e in watch} | set(top60)  # squad, the call, plans, template, top 60
        for k, ur in us["players"].items():
            if k not in players:
                continue
            row = {"s": ur.get("season"), "l4": ur.get("last4"), "sot": ur.get("shots_on_target")}
            if k in maps and ur.get("shot_map"):
                row["map"] = ur["shot_map"]
            players[k]["us"] = row
        for k, ur in us["teams"].items():
            if k in teams:
                teams[k]["us"] = {"s": ur["season"], "l4": ur["last4"], "l4_dates": ur.get("last4_dates")}
        src = _load(ROOT / "data" / "sources.json") or {}
        h = (src.get("sources") or {}).get("understat", {})
        us_meta = {"data_to": us.get("data_to"), "fetched_at": us.get("league_fetched_at"), "matches": us.get("matches"),
                   "season": us.get("season"), "status": h.get("status"), "last_success": h.get("last_success"),
                   "id_map": us.get("id_map"), "shot_maps": len(maps & set(us["players"]))}

    # ---- price alerts ----------------------------------------------------------------
    alerts = []
    for e in sorted(watch, key=lambda e: -abs(players[str(e)]["pcp"])):
        r = players[str(e)]
        up = r["pcp"] > 0
        mine = e in squad
        if mine and up and e not in call_out:
            continue  # a rise on a player you own needs no action
        if abs(r["pcp"]) < 20:
            continue
        tonight = (r["pc0"] or 0) >= 100 if up else (r["pc0"] or 0) <= -100
        alerts.append({"id": e, "dir": "up" if up else "down", "pct": round(abs(r["pcp"])),
                       "tonight": tonight, "owned": mine, "selling": e in call_out, "buying": e in call_in})

    # ---- rank history -------------------------------------------------------------------
    hist = [{"gw": h["event"], "points": h["points"], "rank": h["overall_rank"], "gw_rank": h["rank"],
             "bench": h["points_on_bench"], "transfers": h["event_transfers"]} for h in (ehist or {}).get("current", [])]

    # FPL's history feed can keep a stale rank for the latest gameweek after bonus
    # is finalised; the entry summary is current, so it wins for that gameweek.
    if hist and hist[-1]["gw"] == facts["last_gw"]["gw"]:
        hist[-1]["rank"] = facts["manager"]["overall_rank"]

    events = [{"gw": ev["id"], "deadline": ev["deadline_time"]} for ev in bs["events"]]
    data = {
        "meta": {"gw": gw, "deadline_utc": facts["deadline_utc"], "pulled_at": facts["generated_at"],
                 "snapshot": snap.name, "prices_fetched_at": bs.get("fetched_at"), "model": facts["model"], "sims": SIMS, "built_from": run.name,
                 "history_source": (ehist or {}).get("source"), "player_history": bool(phist),
                 "understat": us_meta},
        "manager": {**facts["manager"], "history": hist, "chips_used": facts["state"]["chips_used"]},
        "cutoffs": facts["rank_cutoffs"],
        "state": facts["state"],
        "squad": {"ids": squad, "sell": {str(k): v for k, v in sell.items()},
                  "now": {"xi": now_xi["xi"], "bench": now_xi["bench"], "captain": now_xi["captain"]},
                  "after": {"ids": after, "xi": aft_xi["xi"], "bench": aft_xi["bench"], "captain": aft_xi["captain"],
                            "bank": rec["bank_after"], "ft_left": max(0, state.free_transfers - len(call_out))}},
        "plans": plans,
        "builder": {"outs": b_outs, "ins": b_ins, "gain": b_gain},
        "captain_pool": cap_pool,
        "ownership": ({"n_top": own["top10k"]["n"], "n_peer": own["peers"]["n"], "peer_rank": own["peer_rank"],
                       "sample_gw": own["gw"], "chips_top": own["top10k"]["chips"],
                       "captain_top": sorted(([round(100 * v, 1), int(k)] for k, v in own["top10k"]["captain"].items()),
                                             reverse=True)[:5]} if own else None),
        "watch": sorted(watch, key=lambda e: -players[str(e)]["h6"]),
        "template": template,
        "teams": teams,
        "free_hit": facts.get("free_hit_curve", []),
        "last_gw": facts["last_gw"],
        "alerts": alerts,
        "events": events,
        "chip_plan": CHIP_PLAN,
        "players": players,
    }
    out = run / "app.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(players)} players)")
    return out
