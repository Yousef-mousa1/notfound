# PyroScope — MODIS/VIIRS Hot Spot Harmonization

NASA Space Apps Cairo 2026 · Challenge #8 · Team **Not Found**

Harmonization of MODIS (~1 km) and VIIRS (375 m) active-fire detections without
inventing information. Read `AGENTS.md` first, then:

- `docs/api-endpoints.md` — 83 non-auth endpoints, implementation status per slice
- `docs/dataset-facts.md` — what the sample data actually contains (and what still needs verification)
- `docs/architecture.md` — package layout, data flow and API plan
- `docs/decisions.md` — decision log
- `docs/phases/` — one file per phase

## Current status

**Slices A + B + C + D + E implemented and verified against the full sample
files**: ingestion, observations, processing, harmonization, validation,
anomalies, analytics, dashboard, exports and jobs (83 non-auth endpoints),
backed by DuckDB. No authentication endpoints (excluded by request). A
dependency-free demo page at `GET /demo` renders the live API in the browser.

| Verified on the real files | Value |
|---|---|
| MODIS rows imported | 18,432 |
| VIIRS rows imported | 79,148 |
| Observations total | 97,580 |
| MODIS median FRP | 16.0 MW |
| VIIRS median FRP | 4.55 MW |
| QC flags (provisional) | invalid_ti4 3 · low_confidence 18,263 · night_detection 6,374 · type_nonzero 112 |
| 25 km grid | 28 × 14 = 392 cells, area distortion 1.77% |
| Aggregation | 457 cell×sensor rows, all 97,580 detections assigned |
| Spatial links (1.5 km, 2 h, cap 10) | 25,929 pairs, not truncated |
| Ratio calibration (1.5 km, 2 h) | factor 3.045, RMSE 79.6 MW on 25,929 pairs |
| Linear calibration | slope 1.034, intercept 32.43 MW, R² 0.060 |
| Harmonization run (25 km, daily, ratio) | 15,337 cell×day rows, 3,967 with both sensors |
| Cross-sensor log10 FRP | MAE 0.555 dex · RMSE 0.670 dex · bias +0.503 dex |
| Activity index | mean 0.309, max 1.0 (unitless, run-relative) |
| Anomaly run (25 km grid, defaults) | 457 cell×sensor series · 442 evaluated · 19,277 cell-days |
| Flagged anomalies | 1,505 (637 moderate · 413 high · 455 extreme) in 205 cells, 128 days |
| Analytics | 12 monthly buckets per sensor · 4 data-extent regions · yearly `trend_claim: false` |
| Dashboard | reads the stored runs above (1,505 anomalies · 15,337 cell-days · 25,929 pairs) |
| Exports | 97,580 observations · 15,337 harmonized rows · 25,929 pairs · 1,505 anomalies as CSV + `metadata.json` |
| Demo page (`/demo`) | reads the live API: sensor cards, lon/lat sample (1,000 points), severity bands, top cells, export history |

The low R² and the +0.50 dex bias are real sample properties, not tuning
failures: MODIS and VIIRS do not agree on this dataset. No scientific parameter
is decided yet: every value in `config/default.yaml` that needs justification is
still `null`. FRP is reported as instantaneous power (MW) and never summed into
energy. Time is labelled as UTC **assumed** until Phase 03 verifies it.

## Layout

```
config/default.yaml     configuration (placeholders + infrastructure paths)
dataSets/               READ-ONLY raw sample files (never modified)
data/interim/           uploads, working outputs
data/processed/         pyroscope.duckdb + run outputs + exports
src/harmonizer/         science + storage package (no Flask imports)
app/                    Flask app factory (thin layer)
app/templates/demo.html demo page (static, no build step, no CDN)
scripts/demo_run.py     one-command end-to-end demo (API-only)
tests/                  pytest (127 tests)
docs/                   endpoints, facts, architecture, phases, decisions
```

## Setup

```bash
pip install -e ".[dev]"
```

## Run

```bash
python -m flask --app app run
```

Then:

```bash
curl http://127.0.0.1:5000/health
```

Open <http://127.0.0.1:5000/demo> for the dashboard. It needs no internet
connection and no build step: the page is static HTML/CSS/JS and only calls the
local API. Every panel shows the endpoint it reads, and a panel with no stored
run says so instead of inventing values.

### One-command demo run

```bash
python -m scripts.demo_run
```

This rebuilds the demonstrable state through the public API only:
`ingest -> grid -> harmonize (ratio) -> validate -> detect anomalies -> export`.
It reuses an existing grid with the same cell size, imports are idempotent by
SHA-256, and every run/export is a new record. A manifest with the created ids
and the applicable limitations is written to `data/processed/demo_manifest.json`.

Useful flags: `--grid-km`, `--radius-m`, `--time-window-h`, `--file` (repeatable),
`--new-grid`, `--no-exports`, `--manifest`, `--config`.

```bash
curl -X POST http://127.0.0.1:5000/api/v1/ingestion/sources/import/modis \
  -H "Content-Type: application/json" \
  -d '{"path": "dataSets/modis_2012_Benin.csv"}'

curl -X POST http://127.0.0.1:5000/api/v1/ingestion/sources/import/viirs \
  -H "Content-Type: application/json" \
  -d '{"path": "dataSets/viirs-snpp_2012_Benin.csv"}'

curl "http://127.0.0.1:5000/api/v1/observations/statistics"
curl "http://127.0.0.1:5000/api/v1/observations?min_frp=100&limit=10"
curl "http://127.0.0.1:5000/api/v1/observations/by-region"
curl "http://127.0.0.1:5000/api/v1/jobs"

# Processing (non-destructive)
curl -X POST http://127.0.0.1:5000/api/v1/processing/clean \
  -H "Content-Type: application/json" -d '{"dry_run": false}'

curl -X POST http://127.0.0.1:5000/api/v1/processing/grid/generate \
  -H "Content-Type: application/json" -d '{"cell_km": 25, "name": "benin-25km"}'

curl -X POST http://127.0.0.1:5000/api/v1/processing/aggregate \
  -H "Content-Type: application/json" \
  -d '{"grid_id": "<grid_id>", "time_bucket": "day"}'

curl -X POST http://127.0.0.1:5000/api/v1/processing/spatial-matching \
  -H "Content-Type: application/json" \
  -d '{"radius_m": 1500, "time_window_h": 2}'

# Harmonization (cross-sensor mapping, never ground truth)
curl -X POST http://127.0.0.1:5000/api/v1/harmonization/calibrate/ratio \
  -H "Content-Type: application/json" \
  -d '{"radius_m": 1500, "time_window_h": 2}'

curl -X POST http://127.0.0.1:5000/api/v1/harmonization/run \
  -H "Content-Type: application/json" \
  -d '{"grid_id": "<grid_id>", "time_bucket": "day", "method": "ratio", "radius_m": 1500, "time_window_h": 2}'

curl "http://127.0.0.1:5000/api/v1/harmonization/activity-index?limit=10"

# Validation (cross-sensor consistency, not accuracy)
curl -X POST http://127.0.0.1:5000/api/v1/validation/run \
  -H "Content-Type: application/json" \
  -d '{"radius_m": 1500, "time_window_h": 2}'

curl "http://127.0.0.1:5000/api/v1/validation/metrics/mae"
curl "http://127.0.0.1:5000/api/v1/validation/temporal"

# Anomalies (statistical outliers on daily per-cell counts, per sensor)
curl -X POST http://127.0.0.1:5000/api/v1/anomalies/detect \
  -H "Content-Type: application/json" \
  -d '{"grid_id": "<grid_id>"}'

curl "http://127.0.0.1:5000/api/v1/anomalies/statistics"
curl "http://127.0.0.1:5000/api/v1/anomalies/severity"
curl "http://127.0.0.1:5000/api/v1/anomalies/by-date"

# Analytics and dashboard (sensors stay separate; FRP stays MW)
curl "http://127.0.0.1:5000/api/v1/analytics/overview"
curl "http://127.0.0.1:5000/api/v1/analytics/frp-trends?granularity=month"
curl "http://127.0.0.1:5000/api/v1/dashboard/overview"
curl "http://127.0.0.1:5000/api/v1/dashboard/activity-index?limit=10"

# Exports (new files + metadata.json; stored data is never modified)
curl -X POST http://127.0.0.1:5000/api/v1/exports/observations \
  -H "Content-Type: application/json" -d '{"sensor": "modis"}'

curl -X POST http://127.0.0.1:5000/api/v1/exports/harmonized-data \
  -H "Content-Type: application/json" -d '{}'

curl -X POST http://127.0.0.1:5000/api/v1/exports/validation-report \
  -H "Content-Type: application/json" -d '{"include_pairs": true}'

curl -X POST http://127.0.0.1:5000/api/v1/exports/csv \
  -H "Content-Type: application/json" -d '{"source": "anomalies"}'

curl "http://127.0.0.1:5000/api/v1/exports/history"
curl -OJ "http://127.0.0.1:5000/api/v1/exports/<export_id>?download=true"
```

## Test

```bash
python -m pytest
```
