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
  understat.py     Understat AJAX client (nightly in Actions), FPL-to-Understat ID map, derived player and team stats
  appdata.py       builds data/runs/gwNN/app.json, the app's data bundle (offline, from files on disk)
  cli.py           python -m engine snapshot | run | appdata | understat [--offline]
config.json        entry id, horizon, timezone
data/archive/      nightly bootstrap + fixtures snapshots (GitHub Actions); bootstrap carries `fetched_at`
data/runs/gwNN/    one weekly run: facts.json (editor input), projections, ownership,
                   entry_history.json, history.json.gz (per-player match rows), app.json
data/sources.json  per-source health; a source flips from "pending" to "healthy" to replace its "Connects in v1" box
                   ("offline" = never fetched, app says so with `offline_since`; "stale" = last fetch
                   failed, app shows the last good numbers with their date)
data/understat/    league_EPL_2026.json (latest league payload), matches/<id>.json.gz (one per finished
                   match, fetched once), derived.json (stats keyed by FPL id; appdata merges it as "us")
data/id_map.json   FPL element id -> Understat id; reviewed pairs go under "manual" and win.
                   data/id_map_unmatched.json lists who was not matched, with the reason
editions/gwNN.json the published edition (written by the editor, read by the app)
editions/index.json list of editions; "current" is the one the app opens
app/               the web app: index.html, app.css, app.js (no build step, hash routing)
design/system/     design system: tokens, components, usage rules
design/mockups/    final screen mockups, click map, parameter list
```

### Where things run

- **GitHub Actions, nightly** (`.github/workflows/nightly.yml`): archives the bootstrap and fixtures after the 00:00 UK price update, then tries Understat once (`python -m engine understat`, up to 3 attempts; a failure is recorded in `data/sources.json` and never fails the job) and rebuilds the newest run's `app.json`. Builds the history the backtest needs.
- **Claude scheduled task, daily 08:39 IST** ("AlooSoul weekly editor"): if the next deadline is within 48 hours and no edition exists for it, run `python -m engine run`, write `editions/gwNN.json` from `facts.json` following the editorial rules, commit and push straight to main, and republish the app at the same artifact link. On deadline day it re-checks the edition (see the runbook). On other days, refresh price alerts only.
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

Additive fields the app reads: `title` and `edition` at the top; `update` (`{at, text}`, set on deadline day when the call changes, shown as a flag at the top); `out_id`/`in_id`, `captain_id`, `vice_id`, `bank_after` in `call`; per headline a `tone` (review, decision, template, chip, fixtures, injury) and an `evidence` block `{src, facts: [{k, v}], action: {kind, label}}` for the data room Stories tab (action kinds: planner, captain, gw9, players-own, freehit, team). A data room entry with `bottom_line` (plus `intro`, `confidence`, `recommended`, `fallback`) renders as the Free Hit story page. A headline with no read shows Headline and Data room in its depth switch.

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

Every stat in the app shows its source and when it was last updated. If a source fails, show the last good value with its date. Never show a blank, and never fill a gap with an estimate presented as data.

| Source | Status | What it fills | How |
|---|---|---|---|
| Official FPL API | Live | Players (xG, xA, xGC, DefCon, CBI, tackles, recoveries, ICT, BPS, set-piece order, news, price-change progress), fixtures, managers, standings | `engine/fpl_api.py` |
| Understat | Built 3 Nov 2026. **Offline since about 2 Nov 2026**, retrying nightly | Shots, shots on target, key passes, npxG, xGChain, xGBuildup (season, per 90, last four), shot maps; team xG, npxG, xGA, shots for and against, PPDA, deep completions (season and last four) | The pages no longer embed JSON (changed late 2025). Data comes from AJAX endpoints on `https://understat.com/`, sent with `X-Requested-With: XMLHttpRequest` and a browser User-Agent: `getLeagueData/EPL/{season}` (teams, players, dates), `getMatchData/{id}` (shots, rosters), `getPlayerData/{id}` (a player's shots and matches). Season is the start year (2026 = 2026/27, checked on every fetch). `engine/understat.py`, nightly in Actions. **Outage:** Understat has been down for everyone since about 2 Nov 2026 (GitHub runners, Apify residential proxies and a home connection all fail; other FPL projects report the same), so this is not a block on us. `sources.json` holds `status: "offline"` and `offline_since`; the app's Understat boxes say "Understat is offline since 2 Nov. Retrying nightly." until the first successful fetch flips it to healthy. Understat's xG is its own model: never put it in a column with FPL's (Opta) xG |
| FotMob | v1, second | Chances created, big chances, dribbles attempted and completed, duels and aerial duels won, interceptions, touches in the box, dispossessed, xGOT | Unofficial match JSON, one request per finished match |
| The Odds API | v1, third | Match odds and over/unders to calibrate team strength; EPL scorer props exist but only from US bookmakers | Official API, free plan 500 credits a month. Pull once per gameweek, never daily |
| Sofascore | v1, last | Player touch heatmaps, season and per match | `LanusStats` (unofficial). Sofascore often blocks cloud IPs. If Actions is blocked, fall back to a local run on Drupad's Mac or a paid scraper (Apify is connected) |
| FBref | Not usable | | Advanced stats removed January 2026 after the Opta deal ended |
| Distance covered, sprints | No free source | | 2026/27 figures in the press come from Gradient Sports (paid). Use PPDA as the team intensity ranking. Do not show distance until a feed exists |
| Carries, through balls | No confirmed source | | Check Sofascore's stat list during the build; if absent, remove them from the screens |

Rules for the unofficial sources: one request every few seconds, cache everything, only fetch finished matches not yet stored, and keep a per-source health record in `data/sources.json` (last success, last error) that the app reads.

**Player ID map.** Each source names players differently. Keep `data/id_map.json` linking FPL element ID to Understat, FotMob and Sofascore IDs. Built by team plus normalised name (accents stripped, full name, first plus last word, web name, word subsets with a minutes check); a match must be unique in both directions, otherwise the player goes to `data/id_map_unmatched.json` for manual review. Never guess: add reviewed pairs under `manual`. Rebuilt on every Understat run, so new players are picked up.

**Historical:** `vaastav/Fantasy-Premier-League` has past seasons but stopped weekly updates after 2024/25, so our nightly archive is the record from now on.
**Benchmarks:** `daniegr/OpenFPL` (needs retraining for DefCon) and `sertalpbilal/FPL-Optimization-Tools` (HiGHS solver taking a projections CSV).

## Known gaps in the v0 model

1. Minutes: blended recent minutes only, no rotation or substitution model. Biggest source of error.
2. No betting-market input for team strength.
3. Compresses premium attackers' hauls (Haaland projects too low) and leans toward DefCon defenders. Captaincy must not be taken from the model raw.
4. Bonus is a flat per-90 rate, not a BPS model.
5. `picks` shows the squad at the last deadline. Transfers already made for the upcoming gameweek are invisible without login, so confirm with Drupad if he has moved early.
6. Price-change projection fields are observed, not documented. Thresholds in `prices.py` are provisional.
7. Fixed 3 Nov: fixtures can stay `finished: false` for a day or more after full time, which made the model treat GW9 as unplayed. `model.played()` now also accepts `finished_provisional`. The GW10 numbers in the mockups were computed before this fix, so live numbers will differ slightly.

## Weekly runbook

- **Nightly 07:15 IST** (GitHub Actions): FPL snapshot, then Understat once (league data, then `getMatchData` only for finished matches not yet stored, one request every 3 seconds, up to 3 attempts; failure is recorded, never fatal), then rebuild `app.json`. Commit to `data/`. FotMob, odds and Sofascore join this job as they are built.
- **Daily 08:39 IST** (Claude scheduled task, the editor): when the next deadline is within 48 hours and no edition exists, run `python -m engine run`, read `facts.json`, write `editions/gwNN.json` following the edition contract and editorial rules, commit and push to main, republish the app. With a Friday or Saturday deadline this lands the morning before deadline day.
- **Deadline day** (the daily run when the deadline is under 24 hours away and the edition exists): re-check injury news (status, chance of playing, news) for the squad and every player in the call, and the price feed. If the call changes, update the edition, set its `update` field (`{"at": ISO time, "text": "what changed and why, one or two sentences"}`, shown at the top of the edition), push to main and republish. If nothing changes, leave the edition alone.
- **Price alerts:** freshness comes from `fetched_at` inside the snapshot's `bootstrap.json`, never from the archive folder's date. Rebuild alerts only when that time is newer than `meta.prices_fetched_at` in the current `app.json`.
- **After the gameweek:** score last week's projections against actual points and append to the prediction log. The data room Model tab shows this record.

## Roadmap

1. Done 3 Nov: `app/` built from the mockups and published as a private artifact; `editions/gw10.json` written. Next: set up the scheduled task (after `engine run`, publish `app/` with `editions/`, `data/sources.json` and the run's `app.json`).
2. Gaps the GW10 build could not fill (FPL API blocked from the sandbox; the run predates `history.json.gz`): minutes in the last four games, points by gameweek on the profile, home/away splits, and team last-four xG. The next `engine run` saves the per-player rows; team last-four splits come from diffing nightly snapshots once four weeks exist (GW13).
3. Built 3 Nov, waiting on the first fetch: Understat client, player ID map, derived stats, and the app screens (players: Shots & chances group, profile card with shot map; teams: Attack and Defence tables, team profile). Understat is offline for everyone since about 2 Nov; the nightly job retries and the screens say so until `data/understat/derived.json` exists. When it lands: check the ID map's unmatched list and compare three players and two teams against the site. Not used by the model: that waits for the backtest. Next: FotMob, then odds, then Sofascore heatmaps.
4. Prediction log and backtest.
5. Minutes model, then odds in team strength.
6. Multi-week solver with chip planning (second-half set: forecast Blank GW30, Double GW32, Blank GW33, Double GW35/36).

## App design

The design is final. Build from these, do not restyle:

- `design/system/`: the "AlooSoul Floodlight Day" design system. `tokens.json` holds every colour, type style, space and radius; `components/*/preview.html` show each component; `README.md` gives the usage rules. Use the tokens by name, never retype hex values.
- `design/mockups/*.dc.html`: one file per screen, 390 wide (phone first). Each is HTML plus a small `DCLogic` class whose `renderVals()` holds the sample data and interaction state. Treat the markup and styles as the spec and the sample data as the shape of the real data. Templates use `{{value}}`, `<sc-for list= as=>` for loops and `<sc-if>` for conditions; translate these to the app's framework.
- `design/mockups/ClickMap.dc.html`: every tap on every screen and where it goes. This is binding: no other click targets, no clashing gestures.
- `design/mockups/Params.dc.html`: every parameter the app shows, which screen shows it, and its source.

**Look:** bright cool ground (#F2F5FB), white cards, deep navy (#0F1A3D) for emphasis panels and the bottom nav, one orange accent (#FF8A2B) for the primary action and selected states. Type is Plus Jakarta Sans for display and numbers, Atkinson Hyperlegible Next for everything you read. Sentence case, generous sizes (body 16, never below 13), no condensed faces. Avoid the generic AI look (cream ground, elegant serif, brass accent).

**Screens:** bottom nav of Edition, Squad, Planner, Ask, Alerts.
- Edition (`Day.dc.html`): the weekly edition, three depths per story (headline, The read, data room teaser). Links to Archive, Planner, Data room, Alerts.
- Squad: now / after the call; cards or a 10-gameweek points heatmap. Players open the profile.
- Planner, four tabs: Transfers (plans plus a build-your-own), Captain (candidates with haul, blank and swing against rivals), Chips (season calendar, best window per chip), Finder (position and price filters).
- Data room, six tabs: Stories, Players (8 metric groups), Teams (5 metric groups), Fixtures (20 x 10 heatmap), Ownership, Model.
- Player profile, Team profile, Free Hit story, Ask, Alerts, Archive.

**Placeholders:** any stat whose source is not live yet renders the "Connects in v1" box from the mockups, naming the source (for a source that is built but offline, the box title says so, for example "Understat is offline since 2 Nov. Retrying nightly."). It switches to real data automatically when `data/sources.json` reports that source healthy.

**Hosting:** a private Claude artifact page reading the repo's `data/` and `editions/`; Ask uses the artifact's `sample` capability. Interactions must be keyboard reachable with visible focus.
