"""Squad state, transfer search, captaincy and Free Hit timing.

Everything works on player ids. Names are for display only, because FPL
web names are not unique (two "Palmer"s and two "King"s in 2026/27).
"""
from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass, field

DECAY = 0.92          # each later week counts a little less
BENCH_WEIGHT = 0.1    # bench points matter only through autosubs
HIT = 4
FORMATIONS = [(d, m, f) for d in range(3, 6) for m in range(2, 6) for f in range(1, 4) if d + m + f == 10]


# ---- squad state ------------------------------------------------------------

def free_transfers(history: dict) -> int:
    """Free transfers available for the next gameweek.

    Rules (2024/25 onward, unchanged in 2026/27): one new free transfer per
    gameweek, at most five banked. Transfers you already had are kept when
    you play a Wildcard or Free Hit, but you do not earn a new one that week.
    GW1 transfers are unlimited and do not count.
    """
    chips = {c["event"]: c["name"] for c in history.get("chips", [])}
    ft = 1
    for g in history["current"]:
        if g["event"] == 1:
            continue
        if chips.get(g["event"]) in ("wildcard", "freehit"):
            continue
        ft = min(5, max(ft - g["event_transfers"], 0) + 1)
    return ft


def selling_prices(bs: dict, transfers: list, squad: list[int]) -> dict[int, float]:
    """Purchase price plus half of any rise, rounded down to £0.1m; falls count in full."""
    now = {p["id"]: p["now_cost"] for p in bs["elements"]}
    start = {p["id"]: p["now_cost"] - p["cost_change_start"] for p in bs["elements"]}
    bought = {}
    for t in sorted(transfers, key=lambda t: t["event"]):
        bought[t["element_in"]] = t["element_in_cost"]
    out = {}
    for e in squad:
        buy, cur = bought.get(e, start[e]), now[e]
        out[e] = (cur if cur <= buy else buy + (cur - buy) // 2) / 10
    return out


@dataclass
class SquadState:
    squad: list[int]
    bank: float
    free_transfers: int
    sell: dict[int, float]
    chips_used: list[dict] = field(default_factory=list)

    @property
    def budget(self) -> float:
        return round(self.bank + sum(self.sell.values()), 1)


def squad_state(bs, history, transfers, picks) -> SquadState:
    squad = [p["element"] for p in picks["picks"]]
    return SquadState(
        squad=squad,
        bank=picks["entry_history"]["bank"] / 10,
        free_transfers=free_transfers(history),
        sell=selling_prices(bs, transfers, squad),
        chips_used=history.get("chips", []),
    )


# ---- lineup -------------------------------------------------------------------

class Planner:
    def __init__(self, proj: dict, gw_from: int, gw_to: int):
        self.P = {int(k): v for k, v in proj["players"].items()}
        self.gw_from, self.gw_to = gw_from, gw_to

    def xp(self, e: int, g: int) -> float:
        return self.P[e]["weeks"][g]["xp"] if g in self.P[e]["weeks"] else self.P[e]["weeks"][str(g)]["xp"]

    def best_xi(self, squad: list[int], g: int) -> dict:
        by = {"GK": [], "DEF": [], "MID": [], "FWD": []}
        for e in squad:
            by[self.P[e]["pos"]].append((self.xp(e, g), e))
        for k in by:
            by[k].sort(reverse=True)
        best = None
        for d, m, f in FORMATIONS:
            if len(by["DEF"]) < d or len(by["MID"]) < m or len(by["FWD"]) < f or not by["GK"]:
                continue
            xi = by["GK"][:1] + by["DEF"][:d] + by["MID"][:m] + by["FWD"][:f]
            s = sum(x for x, _ in xi)
            if best is None or s > best[0]:
                best = (s, xi, (d, m, f))
        s, xi, form = best
        cap_xp, cap = max(xi)
        xi_ids = [e for _, e in xi]
        bench = sorted((e for e in squad if e not in xi_ids), key=lambda e: -self.xp(e, g))
        return {"xp": s + cap_xp, "xi": xi_ids, "captain": cap, "formation": form,
                "bench": bench, "bench_xp": sum(self.xp(e, g) for e in bench)}

    def value(self, squad: list[int], g0: int | None = None, g1: int | None = None) -> float:
        g0, g1 = g0 or self.gw_from, g1 or self.gw_to
        tot = 0.0
        for i, g in enumerate(range(g0, g1 + 1)):
            b = self.best_xi(squad, g)
            tot += (b["xp"] + BENCH_WEIGHT * b["bench_xp"]) * DECAY**i
        return tot

    def horizon_xp(self, e: int) -> float:
        return sum(self.xp(e, g) * DECAY**i for i, g in enumerate(range(self.gw_from, self.gw_to + 1)))

    # ---- transfers --------------------------------------------------------

    def _legal(self, squad):
        return max(Counter(self.P[e]["team_id"] for e in squad).values()) <= 3

    def search(self, state: SquadState, max_transfers: int = 3, pool_size: int = 14) -> list[dict]:
        base = self.value(state.squad)
        pool = {}
        for pos in ("GK", "DEF", "MID", "FWD"):
            c = [e for e, v in self.P.items() if v["pos"] == pos and e not in state.squad and v["xmins"] >= 45]
            pool[pos] = sorted(c, key=self.horizon_xp, reverse=True)[:pool_size]

        def evaluate(outs, ins):
            sq = [e for e in state.squad if e not in outs] + list(ins)
            spend = sum(self.P[e]["cost"] for e in ins) - sum(state.sell[e] for e in outs)
            if spend > state.bank + 1e-9 or not self._legal(sq):
                return None
            hits = max(0, len(outs) - state.free_transfers) * HIT
            return {"outs": list(outs), "ins": list(ins), "gain": round(self.value(sq) - base - hits, 2),
                    "hits": hits, "bank_after": round(state.bank - spend, 1)}

        results = [{"outs": [], "ins": [], "gain": 0.0, "hits": 0, "bank_after": state.bank}]
        for n in (1, 2):
            for outs in itertools.combinations(state.squad, n):
                need = [self.P[e]["pos"] for e in outs]
                for ins in itertools.product(*[pool[p] for p in need]):
                    if len(set(ins)) < n:
                        continue
                    r = evaluate(outs, ins)
                    if r:
                        results.append(r)
        if max_transfers >= 3:
            doubles = sorted((r for r in results if len(r["outs"]) == 2), key=lambda r: -r["gain"])[:40]
            seen = set()
            for r in doubles:
                for out in (e for e in state.squad if e not in r["outs"]):
                    for inn in pool[self.P[out]["pos"]]:
                        if inn in r["ins"]:
                            continue
                        key = (frozenset(r["outs"] + [out]), frozenset(r["ins"] + [inn]))
                        if key in seen:
                            continue
                        seen.add(key)
                        x = evaluate(r["outs"] + [out], r["ins"] + [inn])
                        if x:
                            results.append(x)
        results.sort(key=lambda r: -r["gain"])
        return results

    # ---- free hit ---------------------------------------------------------

    def free_hit_team(self, g: int, budget: float) -> tuple[float, list[int]]:
        """Greedy Free Hit XI under budget, leaving about £16.5m for a cheap bench."""
        by = {p: sorted((e for e, v in self.P.items() if v["pos"] == p and v["xmins"] >= 45),
                        key=lambda e: -self.xp(e, g))[:40] for p in ("GK", "DEF", "MID", "FWD")}
        limit = budget - 16.5
        best = (0.0, [])
        for d, m, f in FORMATIONS:
            need = {"GK": 1, "DEF": d, "MID": m, "FWD": f}
            team = [e for p, k in need.items() for e in by[p][:k]]
            for _ in range(200):
                cost_ok = sum(self.P[e]["cost"] for e in team) <= limit
                if cost_ok and self._legal(team):
                    break
                swap = None
                for i, e in enumerate(team):
                    for alt in by[self.P[e]["pos"]]:
                        if alt in team or self.P[alt]["cost"] >= self.P[e]["cost"]:
                            continue
                        trial = team[:i] + [alt] + team[i + 1:]
                        ratio = (self.xp(e, g) - self.xp(alt, g)) / (self.P[e]["cost"] - self.P[alt]["cost"])
                        if not self._legal(team) and self._legal(trial):
                            ratio -= 50
                        if swap is None or ratio < swap[0]:
                            swap = (ratio, i, alt)
                        break
                if not swap:
                    break
                team[swap[1]] = swap[2]
            if sum(self.P[e]["cost"] for e in team) > limit or not self._legal(team):
                continue
            s = sum(self.xp(e, g) for e in team) + max(self.xp(e, g) for e in team)
            if s > best[0]:
                best = (s, team)
        return best

    def free_hit_curve(self, state: SquadState, g0: int, g1: int) -> list[dict]:
        out = []
        for g in range(g0, g1 + 1):
            mine = self.best_xi(state.squad, g)["xp"]
            fh, team = self.free_hit_team(g, state.budget)
            out.append({"gw": g, "mine": round(mine, 1), "free_hit": round(fh, 1),
                        "gain": round(fh - mine, 1), "team": team})
        return out
