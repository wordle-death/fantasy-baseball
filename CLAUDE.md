# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Fantasy Baseball Draft Tool

## Project Purpose
Build a system to prepare for and execute my fantasy baseball keeper league draft.

## League Context
- 14-team keeper league (Yahoo platform, but draft occurs externally)
- 5x5 categories: R, HR, RBI, SB, OBP (not AVG) | W, SV, K, ERA, WHIP
- 25-round snake draft
- Keeper rules:
  - Keeper slots determined by previous season standings:
    - 1st-4th place: 6 keepers each
    - 5th-8th place: 8 keepers each
    - 9th-11th place: 7 keepers each
    - 12th-14th place: 6 keepers each
  - Keeper cost for DRAFTED players: previous year's draft round minus 3
  - **Keeper rounds start at Round 18** — this is the latest round a player can be kept at. Players drafted in rounds 19-25 or picked up off waivers are all kept at Round 18 (no -3 discount for waiver pickups).
  - **Players drafted in rounds 1-3 are NOT eligible to be kept** (can't go below round 1)
  - Players can be kept maximum 3 years
  - **Shohei Ohtani exists as two separate players** in Yahoo (hitter and pitcher). The draft board doesn't distinguish, but they are separate draftable entities.
  - **Round conflicts:** If you have multiple keepers at the same round, you must keep one at that round and bump the other(s) to earlier rounds. This commonly happens with round 18 keepers — if you have 4 waiver pickups to keep, they go at rounds 18, 17, 16, 15. Example: Two Round 15 keepers → one stays at 15, one goes to 14.
- Draft process:
  - Asynchronous over 1-2 weeks
  - Picks made via Slack, tracked in Google Sheets
  - Yahoo roster not populated until after draft completes

**Important:** The draft occurs in Google Sheets, NOT Yahoo. Yahoo draft data is inaccurate because the commissioner manually adds rosters after the external draft. Always use Google Sheets as the source of truth for draft rounds and keeper history.

## My Team
- Team name: The Nudes
- 2025 finish: 5th place (8 keepers allowed)
- Yahoo League ID: 27545 (2025 season, game_id: 458)

## 2025 Final Standings & Keeper Slots

| Rank | Team | Keepers |
|------|------|---------|
| 1 | Giant City | 6 |
| 2 | Fire Bad | 6 |
| 3 | Kiki Kankles | 6 |
| 4 | High Falls Heroes | 6 |
| 5 | The Nudes | 8 |
| 6 | Acuna Machado | 8 |
| 7 | Cybulski Tax Service | 8 |
| 8 | K-Nines | 8 |
| 9 | The Phenomenal Smiths | 7 |
| 10 | Jeters Never Win | 7 |
| 11 | Topline Jobbers | 7 |
| 12 | Bowls on Parade | 6 |
| 13 | Hebrew Nationals | 6 |
| 14 | The Funeral Home | 6 |

## Technical Constraints
- User has no Python experience (explain concepts as needed)
- User willing to learn and troubleshoot
- Prefer simple, maintainable code over optimization
- Local execution + Streamlit Cloud for mobile access

## Data Sources
- Fangraphs projections (paid subscription)
  - **Depth Charts** (currently using) - Combines Steamer + ZiPS equally, adjusted for playing time. Updated daily.
  - **Steamer** - Developed by Cross, Rosenbloom, Davidson. Daily updates, includes platoon/percentile projections.
  - **ZiPS** - Dan Szymborski's system. Daily updates during season.
  - **ATC** - Ariel Cohen's weighted blend based on historical accuracy. Weekly updates pre-season.
  - **THE BAT / THE BAT X** - Derek Carty's hitter-focused system. X variant uses Statcast data.
  - Note: Composite systems (Depth Charts, ATC) tend to perform better against actual results.
- Google Sheets API (for live draft monitoring)
- Manual input (current roster, keeper decisions)

## Development Preferences
- Build in phases with working deliverables
- Test with sample data before using real league data
- Prioritize functionality over polish
- Add comments explaining key concepts
- Use standard libraries where possible

## Phases
1. Keeper analysis tool (COMPLETE)
2. Draft day recommendation tool (COMPLETE - testing)
3. In-season roster management (future)

## Commands

```bash
# Activate virtual environment (required before running Python)
source venv/bin/activate

# --- Keeper Analysis ---

# 1. Refresh Yahoo roster data (position eligibility)
python refresh_yahoo_rosters.py

# 2. Merge draft history from Google Sheets export
python merge_draft_history.py

# 3. Run SGP valuation (generates sgp_player_values_v3.csv with per-category stats)
python src/sgp_valuation.py

# 4. Run keeper analysis for The Nudes
python run_keeper_analysis.py
python run_keeper_analysis.py --scan-alerts  # with Statcast alerts

# 5. Run league-wide keeper analysis (all 14 teams)
python run_league_keeper_analysis.py
python run_league_keeper_analysis.py --scan-alerts

# --- Draft Day Tool ---

# 6. Draft recommendations (CLI - offline simulation using 2025 data)
python run_draft_recommendations.py --round 7 --offline
python run_draft_recommendations.py --round 7 --offline -n 10
python run_draft_recommendations.py --round 20 --offline  # late-round keeper focus

# 7. Draft recommendations (CLI - with manual roster)
python run_draft_recommendations.py --round 7 --roster "Player1,Player2,Player3"

# 8. Streamlit web app (local)
streamlit run app.py

# 9. Custom scoring weights (surplus,category,position,keeper)
python run_draft_recommendations.py --round 7 --offline --weights 0.5,0.2,0.2,0.1
```

## Google Sheets Draft Board
- **URL**: https://docs.google.com/spreadsheets/d/17AkutPs6lnXAiBk2Jt7LCjGwmckMcRuqdPcubJYrSaA/
- Tabs: 2026, 2025, 2024, ... back to 2016
- Format: Grid layout (teams as columns, rounds as rows)
- Cell format: `{pick_number} {Player Name}` — number-only = not yet picked
- To enable Google Sheets integration: set up a Google Service Account and save the JSON key as `google_service_account.json`

## Draft Recommendation Scoring
The draft tool ranks available players using 4 weighted components:
| Component | Default Weight | What It Measures |
|-----------|---------------|------------------|
| Surplus value | 40% | SGP dollar value vs draft round cost |
| Category need | 25% | How well player fills your weakest categories |
| Position need | 20% | Whether you need this roster slot filled |
| Keeper upside | 15% | Future keeper value (cost trajectory over 3 years) |

Weights auto-adjust by draft phase: surplus dominates early, keeper upside rises late.

## Statcast & News Integration

The `src/statcast_news.py` module provides real-time Statcast analysis for keeper and draft decisions.

### Features
- **Velocity tracking**: Compares Spring Training fastball velocity to career baseline
- **Spin rate monitoring**: Flags significant changes in spin rate
- **Exit velocity analysis**: Tracks batter contact quality changes
- **Batch analysis**: Scan entire keeper lists for alerts

### Alert Thresholds (customized for this league)
| Metric | Yellow Alert | Red Alert |
|--------|--------------|-----------|
| Fastball velocity | +/- 1.5 mph | +/- 2.5 mph |
| Spin rate | +/- 200 rpm | - |
| Exit velocity | +/- 2.0 mph | - |

### Usage
```python
# In Python/interactive session:
from src.statcast_news import analyze_pitcher, analyze_batter, quick_check

# Full pitcher analysis with Spring Training comparison
analyze_pitcher("Gerrit Cole")

# Quick check for alerts only
alerts = quick_check("Elly De La Cruz")

# Batch analysis of keeper list
from src.statcast_news import analyze_keeper_list
players = [{'Player': 'Bobby Witt Jr.', 'Position': 'SS'}]
results = analyze_keeper_list(players)
```

### News Search Integration
The module generates search queries for player news. Use with Claude Code's WebSearch:
- Injury updates: `"<player> MLB 2026 injury update"`
- Playing time: `"<player> MLB 2026 playing time roster"`
- Velocity news: `"<player> MLB 2026 velocity spring training"`

## Project Structure

```
Fantasy Baseball/
├── app.py                        # Streamlit web app (draft day, phone-accessible)
├── run_draft_recommendations.py  # CLI draft recommendations
├── run_keeper_analysis.py        # Keeper analysis for The Nudes (--scan-alerts)
├── run_league_keeper_analysis.py # League-wide keeper analysis for all 14 teams
├── merge_draft_history.py        # Merge draft history from Google Sheets into Yahoo roster
├── refresh_yahoo_rosters.py      # Refresh Yahoo roster data via API
├── get_standings.py              # Fetch standings from Yahoo API
├── src/
│   ├── sgp_valuation.py          # SGP player valuation with position scarcity
│   ├── draft.py                  # Draft recommendation engine (scoring algorithm)
│   ├── sheets.py                 # Google Sheets integration (draft board reader)
│   ├── statcast_news.py          # Statcast velocity/spin analysis + news queries
│   ├── yahoo_import.py           # Yahoo Fantasy API integration
│   └── projections.py            # Load and normalize projections
├── data/
│   ├── projections/              # Fangraphs CSV exports + generated valuations
│   │   ├── fangraphs-projections-hitters-depthcharts-*.csv
│   │   ├── fangraphs-projections-pitchers-depthcharts-*.csv
│   │   └── sgp_player_values_v3.csv  # Includes per-category stats
│   └── rosters/
│       ├── yahoo_league.csv      # All 14 teams with positions + draft history
│       └── draft_2025_parsed.csv # Draft results from Google Sheets
└── venv/                         # Python virtual environment
```

## Data Sources & Truth

| Data | Source | Notes |
|------|--------|-------|
| Player projections | Fangraphs Depth Charts | Download manually, save to `data/projections/` |
| Position eligibility | Yahoo API | Run `refresh_yahoo_rosters.py` |
| Draft rounds & years kept | Google Sheets | Export to `draft_2025_parsed.csv`, run `merge_draft_history.py` |
| Live draft board | Google Sheets (via API) | `src/sheets.py` reads directly; needs service account credentials |
| Current rosters | Yahoo API | Players may have been traded since the draft |

**Important:** Draft history must be matched by player NAME across ALL teams (not just current team) because players get traded.
