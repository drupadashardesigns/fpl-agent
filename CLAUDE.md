# FPL Agent

A personal Fantasy Premier League agent for Drupad (team **AlooSoul**, entry `2469496`). Every gameweek it pulls the data, projects points, plans transfers and chips, and publishes a weekly edition in a web app that reads like a well-edited newsletter.

Read this file at the start of every session. It is the product brief and the rulebook.

## The product

### The weekly edition: three layers of depth

The reader picks how deep to go. Every layer must stand on its own.

1. **Headlines.** 5 to 7 items. Each is a headline of 10 words or fewer plus a paragraph of 2 or 3 sentences. Always includes *the call* (transfers, captain, chip) and one item on what happened last gameweek. Everything else earns its place by changing a decision or explaining one.
2. **The read.** Medium depth, 300 to 600 words, for at most 4 headlines that deserve it. May carry one chart or one small table. Explains the why: fixtures, form against underlying numbers, ownership, price pressure.
3. **The data room.** Full analysis for at most 1 or 2 decisions a week: method, numbers, alternatives considered, how confident we are and why. Charts and tables welcome.

Each headline links down to its read; each read links down to its data room entry when there is one. No layer repeats the one above it word for word.

### Also in the app

- **Your squad**: projected points per gameweek with fixtures, minutes risk, rival ownership.
- **Transfer planner**: try transfers and see the projected impact over the horizon, with free transfers, hits and bank accounted for.
- **Price alerts**: players you own likely to fall, targets likely to rise, before the 00:00 UK update.
- **Ask the agent**: questions about players, fixtures or the plan, answered from this week's data.
- **Archive**: every past edition, with what was recommended and how it turned out.

### Editorial rules

- Plain, direct language. Short sentences. **No em dashes anywhere** (use commas, colons or separate sentences).
- Keep facts (what happened) apart from projections (what the model expects). Label projections as projections.
- Every number comes with context: over how many gameweeks, against what baseline.
- Never "will score" or "will rise". Use "projects", "likely", "the model expects".
- The model is v0 and has known biases (below). Editorial judgement may override it, and must say why in one sentence.
- Curate. If a headline would not change what Drupad does this week or how he understands it, cut it.

## Architecture

```
engine/            Python, standard library only
  fpl_api.py       public FPL API client (no login needed for anything we read)
  model.py         v0 expected points per player per fixture
  planner.py       squad state, free transfers, selling prices, transfer search, Free Hit curve
  ownership.py     samples top 10k and managers around Drupad's rank
  prices.py        price alerts from the feed's own price-change projections
  cli.py           python -m engine snapshot | run
config.json        entry id, horizon, timezone
data/archive/      nightly bootstrap + fixtures snapshots (GitHub Actions)
data/runs/gwNN/    one weekly run: facts.json (editor input), projections, ownership
editions/gwNN.json the published edition (written by the editor, read by the app)
app/               the web app (to build)
```

### Where things run

- **GitHub Actions, nightly** (`.github/workflows/nightly.yml`): archives the bootstrap and fixtures after the 00:00 UK price update. Builds the history the backtest needs.
- **Claude scheduled task, daily 09:00 IST**: if the next deadline is within 36 hours and no edition exists for it, run `python -m engine run`, write `editions/gwNN.json` from `facts.json` following the editorial rules, commit, and republish the app. On other days, refresh price alerts only.
- **The app** is published as a private Claude artifact: static HTML, CSS and JS with no build step, loading the edition and projections as data files. "Ask the agent" uses the artifact `sample` capability, so no API key or server is needed.

### Edition contract (`editions/gwNN.json`)

```json
{
  "gw": 10,
  "deadline_utc": "2026-11-06T18:30:00Z",
  "published_at": "ISO time",
  "status": {"overall_rank": 98216, "gap_top10k": 30, "free_transfers": 2, "bank": 4.3, "chips_left": ["freehit"]},
  "call": {
    "transfers": [{"out": "Calafiori", "in": "Gabriel", "why": "one sentence"}],
    "captain": "Haaland", "vice": "Gabriel",
    "lineup": {"xi": [], "bench": []},
    "chip": null,
    "projected_gain": 14.4, "horizon": [10, 15]
  },
  "headlines": [{"id": "h1", "kicker": "The call", "title": "", "dek": "", "read": "r1"}],
  "reads": [{"id": "r1", "title": "", "body": "markdown", "figure": null, "deep": "d1"}],
  "data_room": [{"id": "d1", "title": "", "body": "markdown", "figures": []}],
  "alerts": [{"kind": "price", "text": ""}],
  "grading": null
}
```

`figure` objects: `{"type": "bar" | "line" | "table" | "heatmap", "title": "", "data": ...}`. `grading` is filled in the following week: recommended moves against what actually happened.

## FPL rules for 2026/27 (verified against the live feed, 3 Nov 2026)

- Two sets of chips (Wildcard, Free Hit, Bench Boost, Triple Captain). The first set expires at the GW19 deadline, which the feed lists as 1 Jan 2027 18:30 UK. No Assistant Manager chip.
- **Free transfers**: one per gameweek, at most 5 banked. Banked transfers are kept through a Wildcard or Free Hit, but **no new one is earned in that week**. (Getting this wrong cost us a bad first recommendation; `planner.free_transfers` encodes it.)
- Selling price: purchase price plus half of any rise, rounded down.
- Prices change daily at 00:00 UK. Max £0.3m per gameweek either way.
- Goalkeeper goals are worth 10. DefCon unchanged: defenders 2 points for 10+ CBIT, midfielders and forwards 2 points for 12+ including recoveries.
- BPS rebalance: no penalty for being tackled; CBI earns 1 BPS per 3 (was per 2); new keeper save buckets.
- Drupad's 2026/27 chips: Bench Boost GW1, Wildcard GW3, Triple Captain GW4. **Free Hit unused** (first set).

## Risk framework

Starting thresholds, to tune once the backtest has a few weeks of data:

- **Template** when a player is 60%+ owned near Drupad's rank and the alternative projects under 2 points better over 6 gameweeks. Captain the premium with 70%+ peer captaincy unless the alternative projects 1.5+ better that week.
- **Aggressive** when an option is 4+ points better over 4 gameweeks and under 15% owned near his rank, when a fixture swing is 1 to 2 weeks out before prices move, or in a double gameweek with a chip.
- **Save** when the best move is worth under 2 points over the horizon, or ahead of an international break or the festive run (go in with 2 free transfers). Take a -4 only when it beats the best free plan by 2+ over the horizon (`cli.HIT_MARGIN`) and clears 6 over 4 gameweeks.
- Context as of GW9: rank 98,216, 30 points behind the top 10k cutoff, 10 behind 50k. The field is compressed, so small repeatable edges matter more than big swings.

## Data sources

- **Official FPL API** (primary): players with xG, xA, xGC, DefCon, set-piece order, injury news, price-change projections; fixtures; any manager's history, transfers and picks; overall standings.
- **Understat** (planned): shot-level xG. Reachable from GitHub Actions, blocked from Claude's cloud sandbox, so fetch it in Actions.
- **Not usable**: FBref removed its advanced stats in January 2026 after Opta ended its data deal. Old scrapers that rely on it are broken.
- **Historical**: `vaastav/Fantasy-Premier-League` has past seasons; it stopped weekly updates after 2024/25, so our own nightly archive is the record from now on.
- **Benchmarks**: `daniegr/OpenFPL` (MIT, XGBoost/RF ensemble, trained before DefCon existed so it needs retraining) and `sertalpbilal/FPL-Optimization-Tools` (HiGHS solver that takes a projections CSV).

## Known gaps in the v0 model

1. Minutes: blended recent minutes only, no rotation or substitution model. Biggest source of error.
2. No betting-market input for team strength.
3. Compresses premium attackers' hauls (Haaland projects too low) and leans toward DefCon defenders. Captaincy must not be taken from the model raw.
4. Bonus is a flat per-90 rate, not a BPS model.
5. `picks` shows the squad at the last deadline. Transfers already made for the upcoming gameweek are invisible without login, so confirm with Drupad if he has moved early.
6. Price-change projection fields are observed, not documented. Thresholds in `prices.py` are provisional.

## Roadmap

1. Build `app/` (edition reader, squad, planner, price alerts, ask the agent, archive).
2. Write `editions/gw10.json` as the first edition, then set up the scheduled task.
3. Prediction log and backtest: store every projection, score against actual points each week.
4. Minutes model, then betting odds, then Understat.
5. Multi-week solver with chip planning (second-half set: forecast Blank GW30, Double GW32, Blank GW33, Double GW35/36).

## App design direction

Phone first. Reads like a matchday sheet, not a dashboard: cool neutral ground, a deep pitch-green accent, a condensed display face for headlines and numbers, a clean sans for reading. Avoid the generic AI look (cream ground, elegant serif, brass accent). Headlines are scannable in under a minute; depth opens in place.
