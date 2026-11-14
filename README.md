# SAT-SCOPE — Earth System Trend Detective

**Hackathon profile:** the default archive now loads only the five pilot countries
(Sri Lanka, US, UK, Australia, India). This is a historical prototype, not real-time
monitoring. Sri Lanka has no sample in the existing coarse archive and is shown
as unavailable. The archive's soil-wetness indicator is not MODIS NDVI.
See [scope and vegetation plan](docs/HACKATHON_SCOPE.md). The global-archive
description below documents the retained source archive; it is no longer the default.

The working checkout targets `Dinyyyd/terra-signal`. The earlier local checkout,
download lists and validation ZIPs are preserved in `_local_archive/` and ignored
by Git. Do not upload that folder or add it with `git add -f`.
The NDVI candidate is an offline review feature, not a completed production
integration; see [proposal review](docs/NDVI_PROPOSAL_REVIEW.md).

NASA Space Apps Challenge · *Be An Earth System Trend Detective!*
© TerraSignal

React + Leaflet + Plotly dashboard, FastAPI backend, scikit-learn analytics (temperature Z-scores, vegetation deltas, precipitation quantiles, fire-detection DBSCAN, Isolation Forest) and SQLite. No Docker.

## Login
| Username | Password (default) |
|---|---|
| `sarujan` | `password` |

Change it in the app: **Settings → Change password** (min. 8 characters; other sessions are signed out). A banner reminds you while the default is still active. Users and password hashes (PBKDF2-SHA256) live in `data/sat_scope.sqlite`. To reset a forgotten password, delete that file and restart the API.

## Run
```bash
# terminal 1 – API
cd backend
python3 -m venv .venv && source .venv/bin/activate      # Windows: py -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000                    # docs: http://127.0.0.1:8000/docs

# terminal 2 – UI
cd frontend && npm install && npm run dev                # http://localhost:5173
```
Tests: `cd backend && pytest -q`

## Global NASA historical data
The default provider reads `data/history/nasa_power_global_monthly_2011_2025.json`, a bundled archive of monthly NASA POWER values sampled at global 5-degree cell centers. It contains complete 2011–2025 records for 2 m air temperature (`T2M`), corrected precipitation rate (`PRECTOTCORR`) and root-zone soil wetness (`GWETROOT`), when all three variables are available for a cell. Natural Earth boundaries attach country and local administrative-area names. The first selector switches between Global and every country; the dependent area selector lists that country's districts, states, provinces or other available local areas. Areas with no NASA grid sample remain selectable and are shown as unavailable. Charts use a same-calendar-month 2011–2020 baseline.

The archive is downloaded with:
```bash
cd backend
python scripts/download_nasa_power_history.py
```
The downloader is resumable and stores a temporary checkpoint under `data/history/` until it completes. It does not need NASA credentials. NASA POWER reports these meteorological variables as MERRA-2 reanalysis, **not direct satellite observations**. The grid consists of point samples at 5-degree spacing, not area-averages; Natural Earth land, country and 1:10m administrative boundaries select land cells and provide area names. The coarse grid will not cover every district or city. Historical fire detections are not included and are shown as unavailable rather than zero.
Root-zone wetness status thresholds are simple dashboard heuristics against the same-month baseline, not NASA-issued drought classifications.

## Data providers
Everything reads data through **`backend/data_provider.py`**.

| Option | How |
|---|---|
| Global historical archive (default) | `DATA_SOURCE=archive uvicorn main:app` |
| Replace the 4 demo JSON files | Overwrite `data/mock/*.json` using the schema documented at the top of `data_provider.py`, then set `DATA_SOURCE=mock`. |
| Use the built-in live adapters | `DATA_SOURCE=live NASA_FIRMS_MAP_KEY=<key> uvicorn main:app` |
| Your own pipeline | Subclass `DataProvider`, return the 4 datasets, register it in `PROVIDERS`. |

The optional live adapters use **FIRMS** VIIRS fires (key needed) and **NASA POWER** daily temperature and precipitation; MODIS NDVI remains a plug-in hook. In live mode, an indicator that fails falls back to the Sri Lanka mock file and is labelled *MOCK (fallback)* in Settings → Data source. Data is validated, so malformed files produce a clear error. If a source fails entirely, the last good result is served from the SQLite cache.

> POWER `TS` in live mode is reanalysis skin temperature, not MODIS LST. The bundled monthly archive instead uses `T2M` (2 m air temperature).

## What the app does
- Login, session tokens, password change, lockout after 5 failed attempts
- Country filter with Global and all countries, plus a dependent searchable local-area selector; areas without sampled data are explicitly marked unavailable
- Leaflet map: click a grid cell to load its local area; temperature, root-zone soil wetness, precipitation, and Isolation Forest outliers are shown for the archive
- Monthly historical charts (2011–2025) with 7-day, 1-month, 1-year, 5-year and 10-year windows, year/month selection, date filters, and interactive zoom
- Same-month baseline comparisons and an Isolation Forest using the indicators available in the selected source
- Regional hotspot ranking, plain-language explanation, auto-refresh every 5 minutes

## API (all but `/api/health` need `Authorization: Bearer <token>`)
`POST /api/auth/login` · `GET /api/auth/me` · `POST /api/auth/change-password` · `GET /api/locations` · `GET /api/dashboard/{location}` · `GET /api/{temperature|vegetation|precipitation|fire}/{location}` · `GET /api/cache/{location}` · `GET /api/data-source` · `POST /api/data/refresh`

## Notes
- The default archive covers land grid centers with complete values for all three NASA POWER variables; grid points are 5-degree samples, not area averages.
- NASA POWER's bundled meteorological variables are MERRA-2 reanalysis, not direct satellite observations. Root-zone soil wetness is not NDVI, and historical fire detections are unavailable in this archive.
- Trend windows only display records supplied by the active source. The optional Sri Lanka mock/live sources have shorter histories than the global archive.
- Isolation Forest flags the top 8% most isolated cells by design; a *compound anomaly* additionally needs ≥ 2 indicator flags.
- The token-signing secret is generated per database; set `CORS_ORIGINS` if you host the UI elsewhere.
