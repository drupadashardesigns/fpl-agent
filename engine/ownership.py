"""Rival ownership: who the top 10k and the managers around you actually own.

Samples pages of the overall league (50 managers per page) and reads each
manager's picks for a gameweek. Ownership is the share of sampled teams
holding a player; effective ownership (EO) also counts captaincy, so a
player captained by everyone has EO near 200%.
"""
from __future__ import annotations

import random
from collections import Counter

from . import fpl_api

PAGE_SIZE = 50


def _sample(pages: list[int], gw: int) -> list[dict]:
    ids = [r["entry"] for p in pages for r in fpl_api.standings_page(p)]
    res = fpl_api.get_many([f"entry/{i}/event/{gw}/picks/" for i in ids])
    out = []
    for d in res.values():
        if d:
            out.append({"chip": d.get("active_chip"),
                        "picks": [(p["element"], p["multiplier"]) for p in d["picks"]]})
    return out


def _summarise(rows: list[dict]) -> dict:
    n = max(len(rows), 1)
    own, eo, cap = Counter(), Counter(), Counter()
    for r in rows:
        for e, m in r["picks"]:
            own[e] += 1
            eo[e] += m
            cap[e] += m >= 2
    return {
        "n": len(rows),
        "own": {e: round(c / n, 4) for e, c in own.items()},
        "eo": {e: round(c / n, 4) for e, c in eo.items()},
        "captain": {e: round(c / n, 4) for e, c in cap.items() if c},
        "chips": dict(Counter(r["chip"] for r in rows if r["chip"])),
    }


def sample(gw: int, my_rank: int, pages_per_group: int = 12, seed: int = 7) -> dict:
    """Ownership for the top 10k and for a band of ±5k ranks around my_rank."""
    rnd = random.Random(seed)
    top_pages = sorted(rnd.sample(range(1, 201), pages_per_group))
    centre = max(1, my_rank // PAGE_SIZE)
    lo, hi = max(201, centre - 100), centre + 100
    peer_pages = sorted(rnd.sample(range(lo, hi + 1), pages_per_group))
    return {"gw": gw, "top10k": _summarise(_sample(top_pages, gw)),
            "peers": _summarise(_sample(peer_pages, gw)), "peer_rank": my_rank}


def rank_cutoffs(ranks: tuple[int, ...] = (10_000, 50_000, 100_000)) -> dict[int, int]:
    """Total points at given overall ranks (last manager on the page holding that rank)."""
    return {r: (fpl_api.standings_page(max(1, r // PAGE_SIZE)) or [{}])[-1].get("total") for r in ranks}
