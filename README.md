# TX '26 Tracker

Live tracker for the **November 3, 2026 Texas midterms**: statewide races and all 38 U.S. House districts.

**Live site:** https://absinthe-007.github.io/Texas-Midterm-Tracker/

| Tab | What it shows |
|---|---|
| 📍 **Trail** | Map of where candidates are campaigning. Tap a pin or a candidate's face to open their **loadout**: bio, poll average, money raised, upcoming stops and latest headlines. |
| 📊 **Polls** | Polling average, 30-day trend and every public poll for each race. You can hide partisan-sponsored polls. |
| 🗺️ **Red/Blue** | County or district map (toggle). Layers: 2026 projection from current polls, 2024 results, 2020→24 and 2016→24 shifts, and House race ratings. |
| 🏁 **Races** | Every matchup with forecaster rating, polls and fundraising. |

## How it updates
A GitHub Action (`.github/workflows/update.yml`) runs **every 6 hours**. It scrapes fresh data, commits it to `data/live/` and redeploys GitHub Pages. You can also run it any time from **Actions → Scrape & deploy → Run workflow**.

## Sources (picked for reliability)
- **Polls, nominees, ratings, FEC fundraising:** Wikipedia's 2026 Texas race pages. Every poll row there links to the pollster's own release, and the site keeps that link.
- **Past results by county:** official county canvass results (via `tonmcg/US_County_Level_Election_Results_08-24`).
- **Past results by 2025 district lines + district shapes:** Texas Legislative Council (`data.capitol.texas.gov`, plan PLANC2333).
- **Scheduled events:** Mobilize public events API. Democratic campaigns, county parties and allied groups post here.
- **Reported stops + headlines:** Google News RSS, filtered to an allow-list of established outlets: AP, Reuters, the Texas Tribune, major Texas papers, public radio, local TV, and national outlets on both sides. The list is in `scraper/campaign.py`.

Republican campaigns don't use a public event API, so GOP stops mostly come from news reports. Those pins are dashed and show the outlet name.

## Projection math (Red/Blue tab)
`2026 projection = baseline margin in that place + (current statewide poll average − statewide baseline margin)`

This is a uniform swing, so it's a quick "what if the polls are right everywhere equally" view, not a forecast.

## Run locally
```bash
pip install -r requirements.txt
python scripts/build_static.py      # one-time: maps + past results
cd scraper && python run_all.py     # live data
cd .. && python -m http.server      # open http://localhost:8000
```
