# mor-p — sports total-score analyzer

Python package `sports_total` (stdlib only) + a mobile web page `web/index.html` published as a
claude.ai artifact: https://claude.ai/artifact/CaNq5YNoTF9QCZRRgTYHnx

Data sources (both allowed in the "mor-p" cloud environment):
- ESPN public API `site.api.espn.com` — everything except EuroLeague/EuroCup. Soccer scoreboards
  reject date ranges (fetched day by day); cups/national teams use `soccer/all` for team history.
- EuroLeague official API `api-live.euroleague.net/v2/competitions/{E|U}/seasons/{E|U}{year}/games`
  (`sports_total/euroleague.py`) — no bookmaker odds.
- Tennis (`atp`, `wta`): ESPN `tennis/{atp|wta}/scoreboard?dates=` per day; history = every Wednesday
  for 52 weeks (cached). ESPN's `format.periods` is wrong for ATP (always 5) — best-of is inferred.
  Joint events list both draws, so filter Men's/Women's Singles by tour. Calibration constants
  (ELO_SCALE, TOTAL_DMULT, TOTAL_SHIFT) in `tennis.py` are mirrored in the page (TENNIS_DMULT/SHIFT).

Winner (moneyline) analysis for every sport lives in `sports_total/winner.py`; the page ports the
same maths (evaluateWinner, tennis Markov chain) — keep Python and JS in sync.

## Refresh the web page ("อัปเดตป้ายสกอร์รวม")
1. `python -m sports_total export --out-dir <scratchpad>/web_data` (≈3 min; one JSON per league).
2. `ArtifactData` `list` collection `slates` on the artifact URL to get each doc's `version`.
3. `ArtifactData` `batch` with one `set` per league: collection `slates`, doc_id = league key,
   `file_path` = the exported JSON, `if_version` = version from step 2 (omit for new leagues).
   Write empty leagues too, so finished matches disappear.

## Change the page
Edit `web/index.html`, publish with the Artifact tool using that file path (keep the URL).
The page's `LEAGUES` table mirrors `sports_total/leagues.py` — keep them in sync.

## Tests
`python -m unittest discover -s tests`
