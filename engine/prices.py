"""Price alerts from the official feed's own price-change projections.

2026/27 exposes, per player, price_change_percent (progress toward the next
change, negative for falls) and price_change_projections (projected percent
at the next three updates, each with a likelihood score). These semantics
are observed from the live feed, not documented by FPL, so thresholds live
here as constants to tune once we log a few weeks of actual changes.

Prices update daily at 00:00 UK time (05:30 IST in winter, 04:30 in summer).
"""
from __future__ import annotations

TONIGHT = 100.0     # projected percent at offset 0 at or beyond this means a change tonight
SOON = 80.0         # within the next couple of updates


def _projection(p: dict, offset: int) -> float | None:
    for x in p.get("price_change_projections") or []:
        if x.get("offset") == offset:
            try:
                return float(x["projected_percent"])
            except (TypeError, ValueError):
                return None
    return None


def alerts(bs: dict, squad: list[int], targets: list[int]) -> list[dict]:
    P = {p["id"]: p for p in bs["elements"]}
    out = []
    for e in set(squad) | set(targets):
        p = P[e]
        now = _projection(p, 0)
        soon = _projection(p, 1)
        if now is None:
            continue
        owned = e in squad
        direction = "rise" if now > 0 else "fall"
        if owned and direction == "rise":
            continue  # a rise on a player you own needs no action
        if not owned and direction == "fall":
            continue
        level = None
        if abs(now) >= TONIGHT:
            level = "tonight"
        elif soon is not None and abs(soon) >= SOON:
            level = "soon"
        if level:
            out.append({"id": e, "name": p["web_name"], "owned": owned, "direction": direction,
                        "when": level, "progress": now, "price": p["now_cost"] / 10})
    order = {"tonight": 0, "soon": 1}
    return sorted(out, key=lambda a: (order[a["when"]], -abs(a["progress"])))
