# fpl-agent

Personal FPL agent for AlooSoul. Pulls the official FPL data, projects points, plans transfers and chips, and publishes a weekly three-layer edition in a web app.

```bash
python -m engine run                 # weekly run for the entry in config.json
python -m engine run --no-ownership  # faster, skips the rival sample
python -m engine snapshot            # archive today's data (runs nightly in GitHub Actions)
```

Standard library only, Python 3.11+. See `CLAUDE.md` for the product brief, rules and roadmap.
