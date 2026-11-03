"""Thin client for the public FPL API. Standard library only.

Every read here is public and needs no login. Responses are cached per run
so one pipeline run never fetches the same URL twice.
"""
from __future__ import annotations

import concurrent.futures as cf
import gzip
import json
import time
import urllib.request
from pathlib import Path

BASE = "https://fantasy.premierleague.com/api"
OVERALL_LEAGUE = 314
UA = "fpl-agent (personal research)"

_cache: dict[str, dict] = {}


def get(path: str, retries: int = 3, pause: float = 1.0) -> dict | None:
    """GET a path under the API base and return parsed JSON, or None on failure."""
    url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
    if url in _cache:
        return _cache[url]
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read())
                _cache[url] = data
                return data
        except Exception:
            time.sleep(pause * (attempt + 1))
    return None


def get_many(paths: list[str], workers: int = 8) -> dict[str, dict | None]:
    with cf.ThreadPoolExecutor(workers) as ex:
        return dict(zip(paths, ex.map(get, paths)))


# ---- convenience readers -------------------------------------------------

def bootstrap() -> dict:
    return get("bootstrap-static/")


def fixtures() -> list:
    return get("fixtures/")


def entry(entry_id: int) -> dict:
    return get(f"entry/{entry_id}/")


def history(entry_id: int) -> dict:
    return get(f"entry/{entry_id}/history/")


def transfers(entry_id: int) -> list:
    return get(f"entry/{entry_id}/transfers/")


def picks(entry_id: int, gw: int) -> dict:
    return get(f"entry/{entry_id}/event/{gw}/picks/")


def live(gw: int) -> dict:
    return get(f"event/{gw}/live/")


def element_summaries(ids: list[int]) -> dict[int, dict]:
    res = get_many([f"element-summary/{i}/" for i in ids])
    return {i: res[f"element-summary/{i}/"] for i in ids}


def standings_page(page: int, league: int = OVERALL_LEAGUE) -> list[dict]:
    d = get(f"leagues-classic/{league}/standings/?page_standings={page}")
    return d["standings"]["results"] if d else []


def current_and_next_gw(bs: dict) -> tuple[int, int]:
    cur = next((e["id"] for e in bs["events"] if e["is_current"]), 0)
    nxt = next((e["id"] for e in bs["events"] if e["is_next"]), cur + 1)
    return cur, nxt


def save_json(obj, path: Path, compress: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()
    if compress:
        path = path.with_suffix(path.suffix + ".gz")
        path.write_bytes(gzip.compress(raw))
    else:
        path.write_bytes(raw)
    return path
