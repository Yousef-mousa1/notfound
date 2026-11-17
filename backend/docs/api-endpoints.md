# PyroScope API — Endpoint Status

Source of truth for implementation status. Derived from
`PyroScope_API_Endpoints(1).pdf` (83 non-authentication endpoints; the five
`/auth` endpoints are excluded by request). The PDF lists 88 paths in total and
the earlier "81" note in this project was a miscount.

**Global conventions**

- Base prefix: `/api/v1` (configurable via `api.prefix`).
- Success envelope: `{"data": ..., "meta": {...}}`.
- Error envelope: `{"error": {"code", "message", "details"?}}` — never HTML.
- Pagination: `limit` (1–1000, default from config), `offset`; `meta` carries
  `total` and `returned`.
- Timestamps: ISO 8601 with `Z`. The time basis is **UTC (verified against FIRMS
  documentation on 2026-11-17)** and is returned as `meta.time_basis`.
- Confidence classes: VIIRS `l/n/h` follow official FIRMS classes; MODIS numeric
  bands (0–29 / 30–79 / 80–100) are **heuristic** (FIRMS publishes the classes but
  no numeric cut-offs). `POST /processing/normalize?apply_confidence=true` echoes
  the `method` and `source` for each sensor.
- FRP is instantaneous power (MW). It is never summed into "energy".
- `GET /demo` (outside `/api/v1`) is a static page that only calls the endpoints
  below; it is not counted among the 83 API endpoints and computes nothing.

## 1. Data Ingestion — `/api/v1/ingestion` — Slice A ✅

| Method | Endpoint | Status |
|---|---|---|
| POST | `/ingestion/sources/import/modis` | ✅ implemented |
| POST | `/ingestion/sources/import/viirs` | ✅ implemented |
| POST | `/ingestion/files/upload` | ✅ implemented (multipart `file`) |
| GET | `/ingestion/sources` | ✅ implemented |
| GET | `/ingestion/imports` | ✅ implemented |
| GET | `/ingestion/imports/{importId}` | ✅ implemented (includes job log) |
| POST | `/ingestion/sync` | ✅ implemented |

Notes: sensor is detected from the file header, never the file name. Paths must
resolve inside the project / raw / upload directory. Identical content (SHA-256)
is imported once; `force=true` re-runs it idempotently.

## 2. Observations — `/api/v1/observations` — Slice A ✅

| Method | Endpoint | Status |
|---|---|---|
| GET | `/observations` | ✅ implemented (filter + paginate) |
| GET | `/observations/{id}` | ✅ implemented (includes untouched `raw_json`) |
| GET | `/observations/modis` | ✅ implemented |
| GET | `/observations/viirs` | ✅ implemented |
| GET | `/observations/map` | ✅ implemented (bbox + limit) |
| GET | `/observations/statistics` | ✅ implemented (overall + per sensor) |
| GET | `/observations/by-region` | ✅ implemented (data-extent grid, not administrative) |
| GET | `/observations/by-date` | ✅ implemented (`granularity=day\|month\|year`) |
| GET | `/observations/by-sensor` | ✅ implemented |

Query parameters: `sensor, platform, start, end, min_frp, max_frp, daynight,
fire_type, confidence_class, source_id, bbox=min_lon,min_lat,max_lon,max_lat,
sort (whitelist), order, limit, offset`.

## 3. Data Processing — `/api/v1/processing` — Slice B ✅

| Method | Endpoint | Status |
|---|---|---|
| POST | `/processing/clean` | ✅ implemented (dry-run by default; never deletes rows) |
| POST | `/processing/filter` | ✅ implemented (saves a filter selection) |
| POST | `/processing/normalize` | ✅ implemented (reports checks; confidence mapping skipped until verified) |
| POST | `/processing/spatial-matching` | ✅ implemented (haversine, link table only, pair cap) |
| POST | `/processing/temporal-matching` | ✅ implemented (time-only links, distance reported) |
| POST | `/processing/grid/generate` | ✅ implemented (km grid, distortion reported) |
| GET | `/processing/grid` | ✅ implemented (grid + cells / list) |
| POST | `/processing/aggregate` | ✅ implemented (per cell × sensor, optional day/month) |
| POST | `/processing/features/extract` | ✅ implemented (per cell × sensor features) |
| POST | `/processing/jobs` | ✅ implemented (202 + worker thread) |
| GET | `/processing/jobs/{jobId}` | ✅ implemented |

Notes:
- Matching endpoints require explicit thresholds in the request; no scientific
  default is baked in. Results carry a `criteria` string and a `truncated` flag.
- `clean` flags are provisional until Phase 03 verifies the official definitions.
- `aggregate` / `features` keep MODIS and VIIRS rows separate and never sum FRP.

## Map point inspection — `/api/v1/dashboard/inspect` ✅

`GET /dashboard/inspect?lat=&lon=&radius_km=10&limit=20` answers a map click from
**two independent stored sources**: recorded detections within a geodesic radius
(`observations`, count + last date + bounded nearest sample) and the model
estimate for the 1-degree block containing the point (`estimates`, separate run).
The two are never summed. The response note states explicitly that no detection
record is **not** proof that no fire occurred. Clicking a detection dot or a grid
cell still shows the existing, more precise popup; this endpoint only handles
empty-space clicks.

## 4. Sensor Harmonization — `/api/v1/harmonization` — Slice C ✅

| Method | Endpoint | Status |
|---|---|---|
| POST | `/harmonization/run` | ✅ implemented (fit optional calibration, write per-cell results) |
| GET | `/harmonization/methods` | ✅ implemented (describes assumptions per method) |
| POST | `/harmonization/calibrate/ratio` | ✅ implemented (median MODIS/VIIRS ratio) |
| POST | `/harmonization/calibrate/linear-regression` | ✅ implemented (OLS with diagnostics) |
| POST | `/harmonization/calibrate/quantile-mapping` | ✅ implemented (empirical quantile table) |
| POST | `/harmonization/calibrate/random-forest` | ✅ returns `501 not_implemented` with the Phase 08 justification |
| GET | `/harmonization/results` | ✅ implemented (run list, or `run_id` lookup) |
| GET | `/harmonization/results/{resultId}` | ✅ implemented (run + paged per-cell results) |
| GET | `/harmonization/comparison` | ✅ implemented (coverage, counts and index summary) |
| GET | `/harmonization/uncertainty` | ✅ implemented (coverage + per-cell disagreement) |
| GET | `/harmonization/activity-index` | ✅ implemented (formula, scales and ranked cells) |

Notes:
- Calibration fits use matched pairs only. MODIS is not ground truth and every
  response says so; the transform is a cross-sensor mapping, not a physical
  correction.
- `random-forest` needs labelled training data and a validation strategy, which
  this project does not have, so it returns `501` with a machine-readable reason.
- A calibration-only request is stored as a `harmonization_runs` row with
  `status = "calibrated"` so its inputs and fit remain reproducible.
- The harmonized activity index is unitless and relative to each run's own p95
  scales; `sensors_present` is always reported because one-sensor cells can
  reach 1.0. No FRP is summed across sensors and no energy is derived.

## 5. Validation — `/api/v1/validation` — Slice C ✅

| Method | Endpoint | Status |
|---|---|---|
| POST | `/validation/run` | ✅ implemented (stores matched-pair snapshot + metrics) |
| GET | `/validation/results` | ✅ implemented (run list, or `run_id` lookup) |
| GET | `/validation/metrics/mae` | ✅ implemented — **cross-sensor consistency**, not accuracy |
| GET | `/validation/metrics/rmse` | ✅ implemented — same framing |
| GET | `/validation/metrics/bias` | ✅ implemented — same framing |
| GET | `/validation/metrics/correlation` | ✅ implemented — same framing |
| GET | `/validation/distribution` | ✅ implemented (quantiles + KS) |
| GET | `/validation/temporal` | ✅ implemented (buckets by \|Δt\|) |
| GET | `/validation/spatial` | ✅ implemented (buckets by geodesic distance) |

Notes:
- These endpoints compare MODIS to VIIRS on matched pairs; they do not call the
  numbers accuracy against true fire occurrence. Held-out reference validation
  against observed VIIRS for 2013 and 2024 is a separate offline modeling step.
  Every response carries `n_pairs` and a `limitations` list.
- Metrics are reported on `log10(FRP)` (primary) and raw MW. Raw-MW RMSE is
  flagged as tail-sensitive.
- Metrics default to the latest successful run when `run_id` is omitted.

## 6. Anomaly Detection — `/api/v1/anomalies` — Slice D ✅

| Method | Endpoint | Status |
|---|---|---|
| GET | `/anomalies` | ✅ implemented (paged, strongest first; filters: `run_id`, `sensor`, `severity`, dates, bbox) |
| GET | `/anomalies/{anomalyId}` | ✅ implemented (includes the run parameters) |
| POST | `/anomalies/detect` | ✅ implemented (201; robust modified z-score on daily per-cell counts) |
| GET | `/anomalies/by-region` | ✅ implemented (stored grid cells, not administrative boundaries) |
| GET | `/anomalies/by-date` | ✅ implemented (per day and sensor) |
| GET | `/anomalies/map` | ✅ implemented (cell-centre points, bounded by `limit`) |
| GET | `/anomalies/statistics` | ✅ implemented (overall, per sensor, per severity, evaluation counters) |
| GET | `/anomalies/severity` | ✅ implemented (bands and definitions) |

Method (the full parameter set is echoed in every response):

- One time series per `(grid cell, sensor)`; MODIS and VIIRS are never merged.
- Baseline = median; scale = `1.4826 * MAD`; when MAD is 0 the Poisson
  `sqrt(median)` fallback is used; when that is also 0 the series is skipped.
- Robust z = `(count - median) / scale`; a day is flagged when
  `z >= threshold` (default 3.5) and `count >= min_detections` (default 3),
  with at least `min_days` (default 5) days in the series.
- Severity bands: moderate `3.5..5`, high `5..7`, extreme `>=7`.
- Result endpoints without `run_id` use the latest successful run; if none
  exists they return `409 no_anomaly_run`, never invented data.
- `series_total` counts `(cell, sensor)` series, not unique cells. Flagged rows
  are day-level statistical outliers, not confirmed fire events, and detection
  gaps (clouds, overpass timing, outages) propagate into the counts.

Verified on the full sample (25 km grid, `grid_51f411602339483e`): 457 series,
442 evaluated (15 skipped for short series, 0 without scale), 19,277 cell-days,
1,505 flagged anomalies (637 moderate, 413 high, 455 extreme) across 205 cells
and 128 days.

## 7. Analytics — `/api/v1/analytics` — Slice D ✅

| Method | Endpoint | Status |
|---|---|---|
| GET | `/analytics/overview` | ✅ implemented (summary + available downstream runs) |
| GET | `/analytics/hotspot-trends` | ✅ implemented (counts per sensor per bucket) |
| GET | `/analytics/frp-trends` | ✅ implemented (mean/median/min/max FRP in MW; no energy conversion) |
| GET | `/analytics/activity-trends` | ✅ implemented (stored harmonization run; `409` if none) |
| GET | `/analytics/daily` | ✅ implemented (per sensor) |
| GET | `/analytics/monthly` | ✅ implemented (per sensor) |
| GET | `/analytics/yearly` | ⚠️ implemented with `trend_claim: false` (single-year sample) |
| GET | `/analytics/regions` | ✅ implemented (data-extent boxes, not administrative regions) |
| GET | `/analytics/land-cover` | ⚠️ `501 not_implemented` (no land-cover dataset registered) |
| GET | `/analytics/sensor-comparison` | ✅ implemented (side-by-side + latest consistency snapshot) |

Verified on the full sample: 97,580 detections (MODIS 18,432; VIIRS 79,148);
12 monthly buckets per sensor; `activity-trends` on `harm_9baf091980fb4cb4`
returns 289 daily buckets with `viirs_detections = 0` (not null) when a bucket
has only MODIS detections; `regions` returns 4 data-extent boxes.

## 8. Dashboard — `/api/v1/dashboard` — Slice D ✅

| Method | Endpoint | Status |
|---|---|---|
| GET | `/dashboard/overview` | ✅ implemented (reuses stored counts and latest runs) |
| GET | `/dashboard/map` | ✅ implemented (bounded observation sample + anomaly points) |
| GET | `/dashboard/calendar` | ✅ implemented (daily counts per sensor) |
| GET | `/dashboard/anomalies` | ✅ implemented (`available: false` when no run exists) |
| GET | `/dashboard/trends` | ✅ implemented (daily + monthly) |
| GET | `/dashboard/sensor-comparison` | ✅ implemented (reuses the analytics payload) |
| GET | `/dashboard/activity-index` | ✅ implemented (latest harmonization run; `409` if none) |

Panels never recompute a different method: they read the stored anomaly,
harmonization and validation runs. Optional panels return `available: false`
with a reason instead of fabricating a series. Verified against the same runs:
overview reports 1,505 anomalies, 15,337 harmonized cell-days and 25,929
validation pairs; `activity-index` returns the 3 strongest of the stored cells.

## 9. Exports — `/api/v1/exports` — Slice E ✅

| Method | Endpoint | Status |
|---|---|---|
| POST | `/exports/csv` | ✅ implemented (generic CSV of observations or one stored run) |
| GET | `/exports/{exportId}` | ✅ implemented (JSON record; `?download=true` returns the file) |
| GET | `/exports/history` | ✅ implemented (paged, `kind` / `status` filters) |
| POST | `/exports/harmonized-data` | ✅ implemented (CSV + metadata, latest run by default) |
| POST | `/exports/observations` | ✅ implemented (filtered CSV + metadata) |
| POST | `/exports/validation-report` | ✅ implemented (JSON report + optional pair CSV) |

Notes:
- An export writes **new** files under `paths.exports`
  (`data/processed/exports/<exportId>/`) plus one row in the `exports` table.
  Imported observations, stored runs and raw files are never modified.
- Every export also writes `metadata.json` containing the inputs (filters or
  run id), a config snapshot, the processing steps, the known limitations, the
  time basis and the software versions. Each file descriptor records `rows`,
  `byte_size` and `sha256`; downloads return `X-Export-Sha256` so a file can be
  verified after transfer.
- Generic `source` values: `observations` (filters apply) and the run-scoped
  `harmonization-results`, `validation-pairs`, `anomalies` (whole stored run).
  Observation filters are rejected for run-scoped sources (`422`) instead of
  being silently ignored. `run_id` is optional and defaults to the latest
  successful run; the resolved id is stored as `source_run_id`.
- CSV values are written exactly as stored: nothing is rounded, re-coded or
  prefixed. Columns are a fixed documented order; observations order by
  `datetime_utc, observation_id`, run rows by their natural key.
- `raw_json` is opt-in (`include_raw_json`) and only for observations.
- Exports larger than `exports.max_rows` (default 500,000) return
  `413 export_too_large`; nothing partial is kept (the export directory is
  removed and no success record is written).
- A failed write is recorded with `status = "failed"` and the error; the
  record is never presented as a successful export. Downloading a file of a
  failed export returns `409 export_not_ready`, and a file deleted from disk
  returns `410 export_file_missing`.

Verified on the full sample: observations export 18,432 MODIS / 79,148 VIIRS /
97,580 all rows; harmonized export 15,337 cell-days; validation report 25,929
pairs; anomalies export 1,505 rows; history lists all records. `metadata.json`
(4.2 KB) carries 5 limitations, the 12-section config snapshot and library
versions.

## 10. Jobs — `/api/v1/jobs` — Slice A ✅

| Method | Endpoint | Status |
|---|---|---|
| GET | `/jobs` | ✅ implemented |
| GET | `/jobs/{jobId}` | ✅ implemented |
| GET | `/jobs/{jobId}/status` | ✅ implemented |
| GET | `/jobs/{jobId}/logs` | ✅ implemented (`after_seq` polling) |
| POST | `/jobs/{jobId}/cancel` | ✅ implemented (409 for finished jobs) |

Ingestion runs synchronously inside a job record; asynchronous processing jobs
arrive with Slice B.

## 11. Authentication — excluded

Not implemented by request.

## Slice summary

| Slice | Groups | Endpoints | Status |
|---|---|---|---|
| A | ingestion, observations, jobs | 21 | ✅ done |
| B | processing | 11 | ✅ done |
| C | harmonization, validation | 20 | ✅ done |
| D | anomalies, analytics, dashboard | 25 | ✅ done |
| E | exports | 6 | ✅ done |

Counts exclude authentication (5 paths): 83 non-auth endpoints in the PDF.
All 83 are implemented; no authentication endpoints are provided by request.

