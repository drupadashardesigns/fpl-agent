"""Player and team ID map shared by every outside source. Standard library only.

data/id_map.json holds one section per source:

    {"understat": {built_at, season, match_rate, teams, manual, players},
     "fotmob":    {built_at, season, match_rate, teams, manual, players}}

"players" maps FPL element id -> the source's player id. Reviewed pairs go under
that source's "manual" (FPL id -> source id) and win over the automatic match.
data/id_map_unmatched.json has the same sections and lists who was not matched,
with the reason, for review.

Matching is by team plus normalised name. A tier only matches when it finds
exactly one player on the team, and that player is not claimed by another FPL
player at the same tier. Looser tiers also need the minutes to agree. Anything
else goes to the review list: we never guess.
  1 full name ("Bukayo Saka" = first + second name)
  2 first word of first name + last word of second name
  3 web name equals the source name ("Gabriel", "Rodri")
  4 every source-name word appears in the FPL names (short forms of long names)
  5 every web-name word appears in the source name ("Salah" in "Mohamed Salah")
  6 the source gives the Opta player id and it equals FPL's "code" (FPL's Opta
    id), on the same team. An exact shared key, not a guess.
When a source gives Opta ids, a name match whose Opta id disagrees with FPL's
code is refused and sent to review.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_MAP = ROOT / "data" / "id_map.json"
UNMATCHED = ROOT / "data" / "id_map_unmatched.json"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def norm(s: str) -> str:
    """Lower case, accents off, punctuation to spaces: 'Ødegaard' -> 'odegaard'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ø", "o").replace("Ø", "o").replace("ß", "ss").replace("ł", "l").replace("đ", "d").replace("æ", "ae")
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower().replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


# Source team names that do not normalise to the FPL name or short name.
TEAM_ALIASES = {
    "manchester city": "man city", "manchester united": "man utd", "newcastle united": "newcastle",
    "nottingham forest": "nottm forest", "tottenham": "spurs", "tottenham hotspur": "spurs",
    "wolverhampton wanderers": "wolves", "west ham united": "west ham", "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton", "leeds united": "leeds", "leicester city": "leicester",
    "afc bournemouth": "bournemouth", "coventry": "coventry city", "hull": "hull city", "ipswich": "ipswich town",
    "sheffield united": "sheffield utd", "luton town": "luton", "norwich city": "norwich", "cardiff city": "cardiff",
    "stoke city": "stoke", "swansea city": "swansea", "west bromwich albion": "west brom",
    "nottm forest": "nottm forest", "man united": "man utd", "newcastle utd": "newcastle", "west ham utd": "west ham",
}


def team_map(bs: dict, titles: dict) -> tuple[dict, list]:
    """Source team id -> FPL team id, from {source id: [names]}. Returns the map and names left over."""
    fpl = {}
    for t in bs["teams"]:
        fpl[norm(t["name"])] = t["id"]
        fpl[norm(t["short_name"])] = t["id"]
    out, missing = {}, []
    for sid, names in titles.items():
        names = [names] if isinstance(names, str) else names
        tid = None
        for n in names:
            n = norm(n)
            tid = fpl.get(n) or fpl.get(TEAM_ALIASES.get(n, ""))
            if tid:
                break
        if tid:
            out[str(sid)] = tid
        else:
            missing.append(names[0])
    return out, missing


def load(source: str) -> dict:
    """This source's section of data/id_map.json ({} if none)."""
    if not ID_MAP.exists():
        return {}
    doc = json.loads(ID_MAP.read_text())
    return doc.get(source) or {}


def _minutes_ok(a: int, b: int) -> bool:
    return abs(a - b) <= max(90, 0.15 * max(a, b))


def match_players(bs: dict, pool_by_team: dict, manual: dict, src_label: str) -> tuple[dict, dict, list]:
    """Match FPL players with minutes to source players.

    pool_by_team: FPL team id -> [{"id", "name", "minutes", "opta" (optional)}].
    Returns (mapping FPL id -> source id, count by tier, unmatched rows).
    """
    by_id = {}
    for pool in pool_by_team.values():
        for u in pool:
            by_id[str(u["id"])] = u

    def keys(p):
        first, second, web = norm(p["first_name"]), norm(p["second_name"]), norm(p["web_name"])
        fw, sw = first.split(), second.split()
        return {1: f"{first} {second}", 2: f"{fw[0]} {sw[-1]}" if fw and sw else None, 3: web}, \
            set(fw + sw + web.split()), set(web.split())

    candidates = {}  # fpl id -> (tier, source id) or (tier, None, [names]) or (tier, None, reason)
    players = [p for p in bs["elements"] if p["minutes"] > 0]
    for p in players:
        if p["id"] in manual:
            candidates[p["id"]] = (0, str(manual[p["id"]]))
            continue
        exact, words, webw = keys(p)
        pool = pool_by_team.get(p["team"], [])
        for tier in (1, 2, 3, 4, 5, 6):
            if tier <= 3:
                hit = [u for u in pool if exact[tier] and norm(u["name"]) == exact[tier]]
            elif tier == 4:
                hit = [u for u in pool if set(norm(u["name"]).split()) <= words and _minutes_ok(p["minutes"], u["minutes"])]
            elif tier == 5:
                hit = [u for u in pool if webw and webw <= set(norm(u["name"]).split())
                       and _minutes_ok(p["minutes"], u["minutes"])]
            else:
                hit = [u for u in pool if u.get("opta") and str(u["opta"]) == str(p["code"])]
            if len(hit) == 1:
                u = hit[0]
                if tier < 6 and u.get("opta") and str(u["opta"]) != str(p["code"]):
                    candidates[p["id"]] = (tier, None, f"name matches {u['name']} but the Opta id differs "
                                                       f"({u['opta']} against FPL code {p['code']})")
                else:
                    candidates[p["id"]] = (tier, str(u["id"]))
                break
            if len(hit) > 1:
                candidates[p["id"]] = (tier, None, [u["name"] for u in hit])
                break
    # a source id claimed twice is ambiguous: keep it only for the single strongest claim
    claims = defaultdict(list)
    for e, c in candidates.items():
        if c[1]:
            claims[c[1]].append((c[0], e))
    mapping, tiers = {}, defaultdict(int)
    for sid, cl in claims.items():
        cl.sort()
        if len(cl) == 1 or cl[0][0] < cl[1][0]:
            mapping[cl[0][1]] = sid
            tiers[cl[0][0]] += 1
    short = {t["id"]: t["short_name"] for t in bs["teams"]}
    unmatched = []
    for p in players:
        if p["id"] in mapping:
            continue
        c = candidates.get(p["id"])
        if c and not c[1]:
            reason = c[2] if isinstance(c[2], str) else f"more than one {src_label} player fits: " + ", ".join(c[2])
        elif c:
            reason = f"claimed by another FPL player"
        else:
            reason = f"no {src_label} player on the team with a matching name"
        unmatched.append({"id": p["id"], "web_name": p["web_name"], "name": f"{p['first_name']} {p['second_name']}",
                          "team": short[p["team"]], "minutes": p["minutes"], "reason": reason})
    return mapping, dict(sorted(tiers.items())), sorted(unmatched, key=lambda r: -r["minutes"])


def save(source: str, section: dict, review: dict) -> None:
    """Write this source's section into data/id_map.json and data/id_map_unmatched.json."""
    doc = json.loads(ID_MAP.read_text()) if ID_MAP.exists() else {}
    if "players" in doc and "understat" not in doc:  # older single-source layout: it was Understat's
        doc = {"understat": doc}
    doc["note"] = ("FPL element id -> each source's player id, one section per source. Built from team plus "
                   "normalised name (engine/idmap.py). Add reviewed pairs under that source's 'manual' "
                   "(FPL id -> source id); they win over the automatic match.")
    doc[source] = section
    ID_MAP.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    rv = json.loads(UNMATCHED.read_text()) if UNMATCHED.exists() else {}
    if "fpl_unmatched" in rv and "understat" not in rv:
        rv = {"understat": rv}
    rv[source] = review
    UNMATCHED.write_text(json.dumps(rv, indent=1, ensure_ascii=False) + "\n")
