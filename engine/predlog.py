"""Prediction log: freeze each gameweek's projections before the deadline, then
score them, and every decision in the edition, against what actually happened.
Standard library only.

    python -m engine predlog                 capture the next gameweek (if its run exists and the
                                             deadline has not passed), then score every captured
                                             gameweek that has finished
    python -m engine predlog capture [--gw N]   capture only
    python -m engine predlog score [--gw N]     score only (fetches actual points from FPL)
    python -m engine predlog --offline       score from actuals already on disk, no network

Files:
    data/predlog/gwNN.json          "capture": every player's projected points, expected minutes
                                    and haul/blank chances for GWNN, plus the decisions (the call,
                                    the alternatives, the captain candidates, the Free Hit advice).
                                    Frozen once the deadline passes. "result": the scoring, added
                                    after the gameweek and refreshed until FPL marks it final.
    data/predlog/actuals/gwNN.json  actual points and minutes for every player, and Drupad's own
                                    picks, transfers and score for that gameweek
    data/predlog/summary.json       every scored gameweek plus the season record (the app reads it)

The capture reads the weekly run (data/runs/gwNN/app.json, which carries the projections and the
haul/blank simulation, and facts.json) and the edition, so it must run after the edition is
written and again after any deadline-day change. The nightly job and the editor task both run it.

Scoring rules (kept simple and stated in the app):
- Player error: projected points minus actual, over every player whose team played and who either
  had projected minutes or played. Positive bias means the model projected too high.
- Plans (the call and its alternatives) are scored as points of the players bought minus points of
  the players sold, minus the hit, summed over the gameweeks of the horizon scored so far. Bench
  and lineup effects are ignored, the same way the projected gain is reported.
- Captain: the pick's actual points against every candidate the edition considered, the model's own
  pick and the top 10k's most-captained player.
- Free Hit: the Free Hit eleven's actual points against the call's eleven, captain not counted,
  for the gameweek it was weighed.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path

from . import fpl_api

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "predlog"
CONFIG = json.loads((ROOT / "config.json").read_text())
HAUL, BLANK = 10, 2  # keep in step with appdata
POS = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
POSN = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
BANDS = [(0.0, 5.0, "Under £5m"), (5.0, 7.0, "£5m to £6.9m"), (7.0, 10.0, "£7m to £9.9m"), (10.0, 99.0, "£10m and up")]
PCOLS = ["xp", "xmins", "haul", "blank", "cost", "pos", "team", "fixtures"]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _load(path: Path):
    if not path.exists():
        return None
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text(encoding="utf-8"))


def _save(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


def log_path(gw: int) -> Path:
    return DIR / f"gw{gw:02d}.json"


def actuals_path(gw: int) -> Path:
    return DIR / "actuals" / f"gw{gw:02d}.json"


# ---- capture ----------------------------------------------------------------------

def _band(cost: float) -> str:
    return next(b[2] for b in BANDS if b[0] <= cost < b[1])


def capture(gw: int | None = None, force: bool = False) -> Path | None:
    """Freeze GW's projections and decisions. Refreshes until the deadline, then never again."""
    runs = sorted((ROOT / "data" / "runs").glob("gw*"))
    run = ROOT / "data" / "runs" / f"gw{gw:02d}" if gw else (runs[-1] if runs else None)
    if not run or not (run / "app.json").exists():
        print("predlog: no weekly run to capture")
        return None
    app, facts = _load(run / "app.json"), _load(run / "facts.json")
    gw = facts["gw"]
    deadline = _parse(facts["deadline_utc"])
    out = log_path(gw)
    old = _load(out)
    now = _now()
    if now >= deadline and not force:
        if old:
            print(f"predlog: GW{gw} capture is frozen (deadline {facts['deadline_utc']} has passed)")
            return None
        if _parse(facts["generated_at"]) >= deadline:
            print(f"predlog: GW{gw} run was made after the deadline, so it is not a fair capture")
            return None
    ed = _load(ROOT / "editions" / f"gw{gw:02d}.json")
    P = app["players"]
    g = str(gw)

    players = {}
    for k, p in P.items():
        wk = p.get("w", {}).get(g)
        nfx = len(wk[1]) if wk else 0
        if not nfx and not p.get("xm"):
            continue
        players[k] = [round(wk[0], 2) if wk else 0.0, round(p.get("xm") or 0, 1), p.get("haul"), p.get("blank"),
                      p["cost"], POS[p["pos"]], p["tid"], nfx]

    # decisions ----------------------------------------------------------------------
    sq = app["squad"]
    by_name = {}
    for k in sq["after"]["ids"]:
        by_name.setdefault(P[str(k)]["n"], int(k))
    call = (ed or {}).get("call") or {}
    xi = [by_name.get(n) for n in (call.get("lineup") or {}).get("xi", [])]
    bench = [by_name.get(n) for n in (call.get("lineup") or {}).get("bench", [])]
    if not xi or None in xi:
        xi, bench = sq["after"]["xi"], sq["after"]["bench"]
    name_team = {f"{p['n']} ({p['t']})": int(k) for k, p in P.items()}
    fh = next((r for r in app.get("free_hit", []) if r["gw"] == gw), None)
    fh_room = next((d for d in (ed or {}).get("data_room", []) if d.get("bottom_line")), None)
    template_cap = app["ownership"]["captain_top"][0][1] if app.get("ownership") and app["ownership"].get("captain_top") else None
    plans = [{"id": p["id"], "name": p["name"], "outs": p["outs"], "ins": p["ins"], "hits": p["hits"], "gain": p["gain"]}
             for p in app.get("plans", [])]
    cands = list(dict.fromkeys([c for c in [call.get("captain_id"), sq["after"].get("captain"), template_cap]
                                + list(app.get("captain_pool", [])) if c]))
    horizon = facts["model"]["horizon"]
    need = set(sq["ids"]) | set(sq["after"]["ids"]) | set(cands) | {e for p in plans for e in p["outs"] + p["ins"]}
    fh_ids = [name_team.get(n) for n in (fh or {}).get("team", [])]
    need |= {e for e in fh_ids if e}
    weeks = {str(e): {w: round(v[0], 2) for w, v in P[str(e)]["w"].items() if horizon[0] <= int(w) <= horizon[1]}
             for e in need if str(e) in P}

    doc = {
        "gw": gw, "deadline_utc": facts["deadline_utc"],
        "captured_at": _iso(now), "captured_after_deadline": now >= deadline,
        "run_generated_at": facts["generated_at"], "model": facts["model"],
        "edition": {"published_at": (ed or {}).get("published_at"), "update": (ed or {}).get("update"),
                    "exists": ed is not None},
        "cols": PCOLS,
        "players": players,
        "weeks": weeks,
        "decisions": {
            "transfers": [{"out": t.get("out_id"), "in": t.get("in_id")} for t in call.get("transfers", [])],
            "captain": call.get("captain_id") or sq["after"].get("captain"),
            "vice": call.get("vice_id"),
            "model_captain": sq["after"].get("captain"),
            "template_captain": template_cap,
            "captain_candidates": cands,
            "chip": call.get("chip"),
            "xi": xi, "bench": bench,
            "squad_before": sq["ids"], "xi_before": sq["now"]["xi"],
            "plans": plans, "call_plan": "call",
            "projected_gain": call.get("projected_gain"), "horizon": horizon,
            "free_hit": ({"gw": gw, "team": fh_ids, "projected_mine": fh["mine"], "projected_fh": fh["free_hit"],
                          "projected_gain": fh["gain"], "played": call.get("chip") == "freehit",
                          "advice": (fh_room or {}).get("bottom_line"), "recommended_gw": (fh_room or {}).get("recommended")}
                         if fh else None),
        },
    }
    if old and old.get("result"):
        doc["result"] = old["result"]
    _save(doc, out)
    print(f"predlog: captured GW{gw}, {len(players)} players, {len(plans)} plans, {len(cands)} captain candidates"
          f"{' (edition not written yet)' if not ed else ''}")
    return out


# ---- actual points ----------------------------------------------------------------

def played(gw: int, bs: dict, fixtures: list | None) -> bool:
    """FPL's "finished" can lag full time by a day or more, so every fixture being
    provisionally finished also counts. The result stays provisional until data_checked."""
    ev = next(e for e in bs["events"] if e["id"] == gw)
    if ev.get("finished"):
        return True
    fx = [f for f in fixtures or [] if f.get("event") == gw]
    return bool(fx) and all(f.get("finished") or f.get("finished_provisional") for f in fx)


def fetch_actuals(gw: int, bs: dict, fixtures: list | None = None) -> dict | None:
    ev = next(e for e in bs["events"] if e["id"] == gw)
    if not played(gw, bs, fixtures):
        return None
    lv = fpl_api.live(gw)
    if not lv:
        raise RuntimeError(f"event/{gw}/live/ unavailable")
    entry = CONFIG["entry_id"]
    pk = fpl_api.picks(entry, gw) or {}
    trs = [t for t in (fpl_api.transfers(entry) or []) if t.get("event") == gw]
    hist = next((h for h in (fpl_api.history(entry) or {}).get("current", []) if h["event"] == gw), None)
    doc = {
        "gw": gw, "fetched_at": _iso(_now()), "final": bool(ev.get("data_checked")),
        "average": ev.get("average_entry_score"), "highest": ev.get("highest_score"),
        "players": {str(e["id"]): [e["stats"]["total_points"], e["stats"]["minutes"]] for e in lv["elements"]},
        "manager": {
            "picks": [{"id": p["element"], "mult": p["multiplier"], "c": p["is_captain"], "v": p["is_vice_captain"]}
                      for p in pk.get("picks", [])],
            "chip": pk.get("active_chip"),
            "transfers": [{"in": t["element_in"], "out": t["element_out"]} for t in trs],
            "points": hist["points"] if hist else None, "hit": hist["event_transfers_cost"] if hist else None,
            "rank": hist["overall_rank"] if hist else None,
        },
    }
    _save(doc, actuals_path(gw))
    return doc


# ---- scoring ------------------------------------------------------------------------

def _err(rows: list[tuple]) -> dict | None:
    """rows: (projected, actual, xmins, mins)."""
    n = len(rows)
    if not n:
        return None
    d = [p - a for p, a, _, _ in rows]
    return {"n": n, "mae": round(sum(abs(x) for x in d) / n, 2), "bias": round(sum(d) / n, 2),
            "rmse": round(math.sqrt(sum(x * x for x in d) / n), 2),
            "projected": round(sum(p for p, _, _, _ in rows) / n, 2), "actual": round(sum(a for _, a, _, _ in rows) / n, 2),
            "mins_mae": round(sum(abs(x - m) for _, _, x, m in rows) / n, 1)}


def _calib(rows: list[tuple]) -> dict | None:
    """rows: (haul%, blank%, actual)."""
    rows = [r for r in rows if r[0] is not None]
    n = len(rows)
    if not n:
        return None
    hp = sum(r[0] for r in rows) / n
    bp = sum(r[1] for r in rows) / n
    ha = sum(1 for r in rows if r[2] >= HAUL) / n
    ba = sum(1 for r in rows if r[2] <= BLANK) / n
    brier_h = sum((r[0] / 100 - (r[2] >= HAUL)) ** 2 for r in rows) / n
    brier_b = sum((r[1] / 100 - (r[2] <= BLANK)) ** 2 for r in rows) / n
    return {"n": n, "haul_projected": round(hp, 1), "haul_actual": round(100 * ha, 1),
            "blank_projected": round(bp, 1), "blank_actual": round(100 * ba, 1),
            "brier_haul": round(brier_h, 3), "brier_blank": round(brier_b, 3)}


def _rows(cap: dict, act: dict) -> list[dict]:
    """One row per player who counts: his team played and he had projected minutes or played."""
    out = []
    ap = act["players"]
    for k, v in cap["players"].items():
        r = dict(zip(cap["cols"], v))
        pts, mins = ap.get(k, [0, 0])
        if not r["fixtures"]:
            continue
        if r["xmins"] <= 0 and mins <= 0:
            continue
        out.append({"id": int(k), **r, "pts": pts, "mins": mins})
    return out


def _pts(act_by_gw: dict, e: int, g: int) -> int:
    a = act_by_gw.get(g)
    return a["players"].get(str(e), [0, 0])[0] if a else 0


def score(gw: int, act_by_gw: dict, names: dict) -> dict | None:
    """Score one captured gameweek against the actuals on disk."""
    cap = _load(log_path(gw))
    act = act_by_gw.get(gw)
    if not cap or not act:
        return None
    rows = _rows(cap, act)
    tup = lambda rs: [(r["xp"], r["pts"], r["xmins"], r["mins"]) for r in rs]  # noqa: E731
    by_pos = {POSN[p]: _err(tup([r for r in rows if r["pos"] == p])) for p in (1, 2, 3, 4)}
    by_band = {b[2]: _err(tup([r for r in rows if b[0] <= r["cost"] < b[1]])) for b in BANDS}
    regulars = [r for r in rows if r["xmins"] >= 60]
    diffs = sorted(rows, key=lambda r: r["pts"] - r["xp"])
    miss = lambda r: {"id": r["id"], "name": names.get(r["id"], str(r["id"])), "projected": r["xp"], "actual": r["pts"],  # noqa: E731
                      "xmins": r["xmins"], "mins": r["mins"]}
    model = {"all": _err(tup(rows)), "regulars": _err(tup(regulars)), "by_position": by_pos, "by_price": by_band,
             "calibration": _calib([(r["haul"], r["blank"], r["pts"]) for r in rows if r["xmins"] > 0]),
             "over": [miss(r) for r in diffs[:5]], "under": [miss(r) for r in diffs[::-1][:5]]}

    D = cap["decisions"]
    P = lambda e: act["players"].get(str(e), [0, 0])[0]  # noqa: E731
    M = lambda e: act["players"].get(str(e), [0, 0])[1]  # noqa: E731
    xp = lambda e, g=gw: cap["weeks"].get(str(e), {}).get(str(g), 0)  # noqa: E731

    # captain ------------------------------------------------------------------------
    c = D["captain"]
    cands = [{"id": e, "name": names.get(e, str(e)), "projected": xp(e), "actual": P(e), "mins": M(e)}
             for e in D["captain_candidates"]]
    best = max(cands, key=lambda x: x["actual"]) if cands else None
    others = [x for x in cands if x["id"] != c]
    captain = {
        "pick": c, "name": names.get(c, str(c)), "actual": P(c), "mins": M(c), "projected": xp(c),
        "candidates": cands, "best": best["id"] if best else None, "best_actual": best["actual"] if best else None,
        "beat": sum(1 for x in others if P(c) > x["actual"]), "tied": sum(1 for x in others if P(c) == x["actual"]),
        "of": len(others),
        "model_pick": D["model_captain"], "model_actual": P(D["model_captain"]) if D["model_captain"] else None,
        "template": D["template_captain"], "template_actual": P(D["template_captain"]) if D["template_captain"] else None,
        "override": D["model_captain"] is not None and D["model_captain"] != c,
    }

    # plans over the horizon scored so far --------------------------------------------
    h0, h1 = D["horizon"]
    done = [g for g in range(h0, h1 + 1) if g in act_by_gw]
    plans = []
    for p in D["plans"]:
        real = sum(_pts(act_by_gw, e, g) for g in done for e in p["ins"]) - \
            sum(_pts(act_by_gw, e, g) for g in done for e in p["outs"]) - p["hits"]
        proj = sum(xp(e, g) for g in done for e in p["ins"]) - sum(xp(e, g) for g in done for e in p["outs"]) - p["hits"]
        plans.append({"id": p["id"], "name": p["name"], "hits": p["hits"], "projected": round(proj, 1), "actual": real,
                      "projected_horizon": p["gain"]})
    callp = next((p for p in plans if p["id"] == D.get("call_plan", "call")), None)
    alts = [p for p in plans if callp and p["id"] != callp["id"]]
    call = None
    if callp:
        call = {"actual": callp["actual"], "projected": callp["projected"], "gws": done, "horizon": D["horizon"],
                "beat": sum(1 for p in alts if callp["actual"] > p["actual"]),
                "tied": sum(1 for p in alts if callp["actual"] == p["actual"]), "of": len(alts),
                "transfers": [{"out": t["out"], "in": t["in"], "out_name": names.get(t["out"]), "in_name": names.get(t["in"]),
                               "out_pts": sum(_pts(act_by_gw, t["out"], g) for g in done),
                               "in_pts": sum(_pts(act_by_gw, t["in"], g) for g in done)} for t in D["transfers"]]}
    free = [p for p in plans if p["hits"] == 0]
    best_free = max(free, key=lambda p: p["actual"]) if free else None
    hits = [{"id": p["id"], "name": p["name"], "hits": p["hits"], "actual": p["actual"],
             "best_free": best_free["actual"] if best_free else None, "best_free_name": best_free["name"] if best_free else None,
             "paid": bool(best_free) and p["actual"] > best_free["actual"],
             "advised": p["id"] == D.get("call_plan", "call")} for p in plans if p["hits"] > 0]

    # Free Hit ------------------------------------------------------------------------------
    fh = None
    if D.get("free_hit") and D["free_hit"]["team"] and None not in D["free_hit"]["team"]:
        F = D["free_hit"]
        fh_act = sum(P(e) for e in F["team"])
        xi_act = sum(P(e) for e in D["xi"])
        fh_proj = sum(xp(e) for e in F["team"])
        xi_proj = sum(xp(e) for e in D["xi"])
        fh = {"played": F["played"], "advice": F["advice"], "recommended_gw": F["recommended_gw"],
              "fh_actual": fh_act, "xi_actual": xi_act, "gain_actual": fh_act - xi_act,
              "gain_projected": round(fh_proj - xi_proj, 1)}

    # the eleven, and what Drupad did ------------------------------------------------------------
    cap_pts = P(c) if M(c) > 0 else P(D["vice"]) if D["vice"] else 0
    team = {"xi_actual": sum(P(e) for e in D["xi"]), "captain_bonus": cap_pts,
            "total": sum(P(e) for e in D["xi"]) + cap_pts,
            "projected": round(sum(xp(e) for e in D["xi"]) + xp(c), 1)}
    man = act["manager"]
    mine_cap = next((p["id"] for p in man["picks"] if p["c"]), None)
    made = {(t["out"], t["in"]) for t in man["transfers"]}
    rec = {(t["out"], t["in"]) for t in D["transfers"]}
    rec_in, made_in = {t["in"] for t in D["transfers"]}, {t["in"] for t in man["transfers"]}
    followed = {"transfers_made": [{"out": o, "in": i, "out_name": names.get(o), "in_name": names.get(i)} for o, i in made],
                "transfers_matched": len(rec & made) or len(rec_in & made_in), "transfers_recommended": len(rec),
                "captain": mine_cap, "captain_name": names.get(mine_cap), "captain_followed": mine_cap == c,
                "chip": man["chip"], "points": man["points"], "hit": man["hit"], "rank": man["rank"]}

    res = {"gw": gw, "scored_at": _iso(_now()), "final": act["final"], "average": act["average"],
           "model": model, "captain": captain, "call": call, "plans": plans, "hits": hits, "free_hit": fh,
           "team": team, "followed": followed}
    cap["result"] = res
    _save(cap, log_path(gw))
    return res


# ---- grading text and the edition --------------------------------------------------------

def _s(x: float, d: int = 0) -> str:
    v = round(x, d)
    return ("+" if v > 0 else "") + (f"{v:.{d}f}" if d else str(int(v)))


def grade_text(r: dict) -> dict:
    """Plain sentences for the edition's grading field. No em dashes."""
    lines = []
    c, call, m = r["captain"], r["call"], r["model"]["all"]
    if call:
        through = f"GW{call['gws'][0]}" if len(call["gws"]) == 1 else f"GW{call['gws'][0]} to GW{call['gws'][-1]}"
        moves = ", ".join(f"{t['in_name']} {t['in_pts']} for {t['out_name']} {t['out_pts']}" for t in call["transfers"])
        moves = f" ({moves})" if moves else ""
        tied = f" and tied {call['tied']}" if call["tied"] else ""
        lines.append(f"The call netted {_s(call['actual'])} points over {through} against {_s(call['projected'], 1)} projected"
                     f"{moves}. It beat {call['beat']} of {call['of']} alternatives{tied}.")
    if c:
        rank = 1 + sum(1 for x in c["candidates"] if x["id"] != c["pick"] and x["actual"] > c["actual"])
        best = next((x for x in c["candidates"] if x["id"] == c["best"]), None)
        s = f"Captain {c['name']} scored {c['actual']}, {_ord(rank)} of {len(c['candidates'])} candidates"
        s += "." if rank == 1 or not best else f"; {best['name']} was best with {best['actual']}."
        if c["override"] and c["model_actual"] is not None:
            s += f" The edition overrode the model's pick, {_name(c, c['model_pick'])}, who scored {c['model_actual']}."
        lines.append(s)
    for h in r["hits"]:
        lines.append(f"The hit option ({h['name']}) would have netted {_s(h['actual'])} against {_s(h['best_free'])} for the best "
                     f"free plan, so skipping it {'cost points' if h['paid'] else 'was right'}.")
    fh = r["free_hit"]
    if fh and not fh["played"]:
        cost = (f"cost {fh['gain_actual']} points this week" if fh["gain_actual"] > 0
                else "was right this week" if fh["gain_actual"] < 0 else "made no difference this week")
        lines.append(f"Holding the Free Hit: its eleven scored {fh['fh_actual']} against {fh['xi_actual']} for the call's eleven "
                     f"({_s(fh['gain_actual'])}, projected {_s(fh['gain_projected'], 1)}), so waiting {cost}.")
    if m:
        lines.append(f"Projections missed by {m['mae']:.1f} points a player on average across {m['n']} players "
                     f"({'too high' if m['bias'] > 0 else 'too low'} by {abs(m['bias']):.1f} on balance).")
    f = r["followed"]
    if f["points"] is not None:
        hit = f" with a {f['hit']}-point hit" if f["hit"] else ""
        lines.append(f"You scored {f['points']}{hit}, "
                     f"against an average of {r['average']}; the call's eleven with its captain would have scored {r['team']['total']}.")
    return {"summary": _short(r), "lines": lines}


def _name(c: dict, e: int) -> str:
    return next((x["name"] for x in c["candidates"] if x["id"] == e), str(e))


def _ord(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _short(r: dict) -> str:
    """One line for the archive card."""
    parts = []
    if r["call"]:
        parts.append(f"Call {_s(r['call']['actual'])} against {_s(r['call']['projected'], 1)} projected")
    if r["captain"]:
        parts.append(f"captain {r['captain']['name']} {r['captain']['actual']}")
    if r["model"]["all"]:
        parts.append(f"model off by {r['model']['all']['mae']:.1f} a player")
    s = ", ".join(parts)
    return (s[0].upper() + s[1:] + ".") if s else "Graded."


def grade_edition(gw: int, r: dict) -> bool:
    path = ROOT / "editions" / f"gw{gw:02d}.json"
    ed = _load(path)
    if not ed:
        return False
    t = grade_text(r)
    ed["grading"] = {
        "gw": gw, "scored_at": r["scored_at"], "final": r["final"], "summary": t["summary"], "lines": t["lines"],
        "call": r["call"], "captain": {k: v for k, v in r["captain"].items() if k != "candidates"},
        "captain_candidates": r["captain"]["candidates"], "hits": r["hits"], "free_hit": r["free_hit"],
        "team": r["team"], "followed": r["followed"],
        "model": {k: r["model"][k] for k in ("all", "regulars", "calibration")},
    }
    path.write_text(json.dumps(ed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    idx_path = ROOT / "editions" / "index.json"
    idx = _load(idx_path)
    for e in idx["editions"]:
        if e["gw"] == gw:
            e["graded"] = True
            e["grade_summary"] = t["summary"]
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


# ---- season summary ---------------------------------------------------------------------

def summarise() -> dict:
    weeks, pooled = [], []
    caps = []
    for path in sorted(DIR.glob("gw*.json")):
        d = _load(path)
        gw = d["gw"]
        caps.append({"gw": gw, "captured_at": d["captured_at"], "players": len(d["players"]),
                     "deadline_utc": d["deadline_utc"], "scored": bool(d.get("result"))})
        r = d.get("result")
        if not r:
            continue
        act = _load(actuals_path(gw))
        if act:
            pooled += _rows(d, act)
        weeks.append({"gw": gw, "final": r["final"], "model": r["model"]["all"], "regulars": r["model"]["regulars"],
                      "calibration": r["model"]["calibration"],
                      "captain": {k: r["captain"][k] for k in ("pick", "name", "actual", "best", "best_actual", "beat", "tied",
                                                               "of", "override", "model_actual", "template_actual")},
                      "call": {k: r["call"][k] for k in ("actual", "projected", "beat", "tied", "of", "gws")} if r["call"] else None,
                      "hits": r["hits"], "free_hit": r["free_hit"], "team": r["team"],
                      "followed": {k: r["followed"][k] for k in ("points", "hit", "captain_followed", "transfers_matched",
                                                                  "transfers_recommended")},
                      "over": r["model"]["over"][:3], "under": r["model"]["under"][:3]})
    tup = lambda rs: [(r["xp"], r["pts"], r["xmins"], r["mins"]) for r in rs]  # noqa: E731
    season = None
    if weeks:
        cw = [w["captain"] for w in weeks]
        calls = [w["call"] for w in weeks if w["call"]]
        hits = [h for w in weeks for h in w["hits"]]
        fhs = [w["free_hit"] for w in weeks if w["free_hit"]]
        season = {
            "weeks": len(weeks),
            "model": _err(tup(pooled)),
            "by_position": {POSN[p]: _err(tup([r for r in pooled if r["pos"] == p])) for p in (1, 2, 3, 4)},
            "by_price": {b[2]: _err(tup([r for r in pooled if b[0] <= r["cost"] < b[1]])) for b in BANDS},
            "calibration": _calib([(r["haul"], r["blank"], r["pts"]) for r in pooled if r["xmins"] > 0]),
            "captain": {"weeks": len(cw), "best": sum(1 for c in cw if c["actual"] >= (c["best_actual"] or 0)),
                        "beat_template": sum(1 for c in cw if c["template_actual"] is not None and c["actual"] > c["template_actual"]),
                        "tied_template": sum(1 for c in cw if c["template_actual"] is not None and c["actual"] == c["template_actual"]),
                        "overrides": sum(1 for c in cw if c["override"]),
                        "overrides_won": sum(1 for c in cw if c["override"] and c["actual"] > (c["model_actual"] or 0)),
                        "points": sum(c["actual"] for c in cw)},
            "call": {"weeks": len(calls), "actual": sum(c["actual"] for c in calls), "projected": round(sum(c["projected"] for c in calls), 1),
                     "beat": sum(c["beat"] for c in calls), "tied": sum(c["tied"] for c in calls), "of": sum(c["of"] for c in calls)},
            "hits": {"considered": len(hits), "would_have_paid": sum(1 for h in hits if h["paid"]),
                     "taken": sum(1 for h in hits if h["advised"]),
                     "net_vs_best_free": sum(h["actual"] - (h["best_free"] or 0) for h in hits)},
            "free_hit": {"weeks_held": sum(1 for f in fhs if not f["played"]),
                         "cost_of_holding": sum(f["gain_actual"] for f in fhs if not f["played"]),
                         "projected_cost": round(sum(f["gain_projected"] for f in fhs if not f["played"]), 1)},
        }
    out = {"built_at": _iso(_now()), "captures": caps, "weeks": weeks, "season": season,
           "rules": {"haul": HAUL, "blank": BLANK, "bands": [b[2] for b in BANDS]}}
    _save(out, DIR / "summary.json")
    return out


# ---- entry point ------------------------------------------------------------------------

def run(mode: str = "all", gw: int | None = None, offline: bool = False) -> None:
    if mode in ("all", "capture") and not offline:
        try:
            capture(gw if mode == "capture" else None)
        except Exception as e:  # never fail the nightly job on the log
            print(f"predlog: capture failed: {e}")
    if mode == "capture":
        summarise()
        return
    bs = None if offline else fpl_api.bootstrap()
    fixtures = None if offline else fpl_api.fixtures()
    if bs is None:
        from . import appdata
        _, bs = appdata.newest_snapshot()
        offline = True
    names = {p["id"]: p["web_name"] for p in bs["elements"]}
    todo = [gw] if gw else [int(p.stem[2:]) for p in sorted(DIR.glob("gw*.json"))]
    # actuals for every gameweek a capture's horizon reaches, refreshed until FPL marks them final
    needed = set()
    for g in todo:
        cap = _load(log_path(g))
        if cap:
            h0, h1 = cap["decisions"]["horizon"]
            needed |= set(range(g, h1 + 1))
    act_by_gw = {}
    for g in sorted(needed):
        a = _load(actuals_path(g))
        if not offline and (not a or not a.get("final")):
            try:
                a = fetch_actuals(g, bs, fixtures) or a
            except Exception as e:
                print(f"predlog: GW{g} actuals failed: {e}")
        if a:
            act_by_gw[g] = a
    for g in todo:
        if g not in act_by_gw:
            continue
        r = score(g, act_by_gw, names)
        if r:
            graded = grade_edition(g, r)
            m = r["model"]["all"]
            print(f"predlog: scored GW{g}{' (final)' if r['final'] else ' (provisional)'}: MAE {m['mae']} over {m['n']} players, "
                  f"captain {r['captain']['name']} {r['captain']['actual']}, call {r['call']['actual'] if r['call'] else '-'}"
                  f"{', edition graded' if graded else ''}")
    s = summarise()
    print(f"predlog: {len(s['captures'])} captured, {len(s['weeks'])} scored")
