"""Pipeline entry point.

    python -m engine snapshot            archive today's bootstrap + fixtures (nightly job)
    python -m engine run                 full weekly run for the entry in config.json
    python -m engine run --no-ownership  skip the rival sample (faster, for testing)

A run writes data/runs/gwNN/ with one file per stage, plus facts.json: the
compact bundle the weekly editor reads to write the edition.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import fpl_api, model, ownership, planner, prices

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config.json").read_text())


def snapshot() -> None:
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out = ROOT / "data" / "archive" / day
    fpl_api.save_json(fpl_api.bootstrap(), out / "bootstrap.json", compress=True)
    fpl_api.save_json(fpl_api.fixtures(), out / "fixtures.json", compress=True)
    print(f"archived {out}")


def last_gw_review(bs: dict, gw: int, squad_picks: dict) -> dict:
    lv = fpl_api.live(gw) or {"elements": []}
    pts = {e["id"]: e["stats"]["total_points"] for e in lv["elements"]}
    name = {p["id"]: p["web_name"] for p in bs["elements"]}
    team = {p["id"]: p["team"] for p in bs["elements"]}
    short = {t["id"]: t["short_name"] for t in bs["teams"]}
    ev = next(e for e in bs["events"] if e["id"] == gw)
    top = sorted(pts.items(), key=lambda kv: -kv[1])[:10]
    mine = [{"id": p["element"], "name": name[p["element"]], "points": pts.get(p["element"], 0),
             "multiplier": p["multiplier"]} for p in squad_picks["picks"]]
    return {
        "gw": gw, "average": ev.get("average_entry_score"), "highest": ev.get("highest_score"),
        "most_captained": name.get(ev.get("most_captained")),
        "top_scorers": [{"id": e, "name": name[e], "team": short[team[e]], "points": p} for e, p in top],
        "my_players": mine,
        "chip_plays": {c["chip_name"]: c["num_played"] for c in ev.get("chip_plays", [])},
    }


HIT_MARGIN = 2.0  # a hit must beat the best no-hit plan by this much over the horizon


def recommend(options: list[dict]) -> dict:
    """Best plan, but a plan with hits only wins if it clears HIT_MARGIN over the best free plan."""
    free = max((o for o in options if o["hits"] == 0), key=lambda o: o["gain"])
    hit = max((o for o in options if o["hits"] > 0), key=lambda o: o["gain"], default=None)
    return hit if hit and hit["gain"] - free["gain"] >= HIT_MARGIN else free


def run(entry_id: int, horizon: int, with_ownership: bool) -> Path:
    bs, fx = fpl_api.bootstrap(), fpl_api.fixtures()
    cur, nxt = fpl_api.current_and_next_gw(bs)
    out = ROOT / "data" / "runs" / f"gw{nxt:02d}"
    ent, hist, trs = fpl_api.entry(entry_id), fpl_api.history(entry_id), fpl_api.transfers(entry_id)
    pk = fpl_api.picks(entry_id, cur)
    state = planner.squad_state(bs, hist, trs, pk)

    ids = [p["id"] for p in bs["elements"] if p["minutes"] >= 90]
    summaries = fpl_api.element_summaries(ids)
    proj = model.project(bs, fx, summaries, nxt, min(38, nxt + 9))
    fpl_api.save_json(proj, out / "projections.json", compress=True)

    pl = planner.Planner(proj, nxt, min(38, nxt + horizon - 1))
    options = pl.search(state)[:25]
    first_half_end = 19 if nxt <= 19 else 38
    used = {c["name"] for c in state.chips_used if (c["event"] <= 19) == (nxt <= 19)}
    fh_curve = pl.free_hit_curve(state, nxt, first_half_end) if "freehit" not in used else []

    own = ownership.sample(cur, ent["summary_overall_rank"]) if with_ownership else None
    if own:
        fpl_api.save_json(own, out / "ownership.json")
    cutoffs = ownership.rank_cutoffs()

    targets = sorted({e for o in options[:10] for e in o["ins"]})
    alerts = prices.alerts(bs, state.squad, targets)
    nm = lambda e: pl.P[e]["name"] + f" ({pl.P[e]['team']})"

    deadline = next(e["deadline_time"] for e in bs["events"] if e["id"] == nxt)
    facts = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "gw": nxt, "deadline_utc": deadline,
        "manager": {"entry_id": entry_id, "team_name": ent["name"], "overall_rank": ent["summary_overall_rank"],
                    "total_points": ent["summary_overall_points"], "last_gw_points": ent["summary_event_points"]},
        "rank_cutoffs": cutoffs,
        "state": {"free_transfers": state.free_transfers, "bank": state.bank, "budget": state.budget,
                  "chips_used": [{"name": c["name"], "gw": c["event"]} for c in state.chips_used]},
        "squad": [{"id": e, "name": nm(e), "pos": pl.P[e]["pos"], "cost": pl.P[e]["cost"], "sell": state.sell[e],
                   "xmins": pl.P[e]["xmins"], "news": pl.P[e]["news"],
                   "xp": {g: pl.xp(e, g) for g in range(nxt, min(38, nxt + 9) + 1)},
                   "own_top10k": own["top10k"]["own"].get(e, 0) if own else None,
                   "own_peers": own["peers"]["own"].get(e, 0) if own else None} for e in state.squad],
        "lineup": {k: (v if not isinstance(v, list) else [nm(e) for e in v]) if k != "captain" else nm(v)
                   for k, v in pl.best_xi(state.squad, nxt).items()},
        "transfer_options": [{"outs": [nm(e) for e in o["outs"]], "ins": [nm(e) for e in o["ins"]],
                              "gain": o["gain"], "hits": o["hits"], "bank_after": o["bank_after"]} for o in options[:12]],
        "free_hit_curve": [{**f, "team": [nm(e) for e in f["team"]]} for f in fh_curve],
        "price_alerts": alerts,
        "last_gw": last_gw_review(bs, cur, pk),
        "captaincy_top10k": sorted(((v, nm(e)) for e, v in own["top10k"]["captain"].items()), reverse=True)[:5] if own else None,
        "template_gaps": [{"name": nm(e), "own_top10k": v, "own_peers": own["peers"]["own"].get(e, 0),
                           "horizon_xp": round(pl.horizon_xp(e), 1)}
                          for e, v in sorted(own["top10k"]["own"].items(), key=lambda kv: -kv[1])
                          if e not in state.squad and v >= 0.25] if own else None,
        "model": {"version": "v0", "horizon": [nxt, min(38, nxt + horizon - 1)], "decay": planner.DECAY},
    }
    facts["recommended"] = recommend(facts["transfer_options"])
    fpl_api.save_json(facts, out / "facts.json")
    print(f"wrote {out} | GW{nxt} | FT {state.free_transfers} | bank £{state.bank}m | best: "
          f"{facts['transfer_options'][0]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    r = sub.add_parser("run")
    r.add_argument("--entry", type=int, default=CONFIG["entry_id"])
    r.add_argument("--horizon", type=int, default=CONFIG.get("horizon", 6))
    r.add_argument("--no-ownership", action="store_true")
    a = ap.parse_args()
    if a.cmd == "snapshot":
        snapshot()
    else:
        run(a.entry, a.horizon, not a.no_ownership)


if __name__ == "__main__":
    main()
