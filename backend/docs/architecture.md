# Architecture

## 1. Principle

**Flask is a thin API layer. The science lives in a standalone Python package.**
Why: the same code must run from Colab/notebooks and from the API without duplication, and the science must be testable without a running server.

## 2. Layout

```
project/
├── AGENTS.md
├── config/
│   └── default.yaml            # grid_km, time_window_h, match_radius_m, confidence mapping...
├── data/
│   ├── interim/                # uploads + working files
│   └── processed/              # pyroscope.duckdb + run outputs
├── dataSets/                   # READ-ONLY originals (paths.raw)
├── src/harmonizer/             # pure Python, NO Flask imports
│   ├── io/                     # loaders, file registry
│   ├── schema/                 # unified schema, column mapping
│   ├── store/                  # DuckDB schema, job records, SQL builders
│   ├── audit/                  # schema + stats + quality report
│   ├── validate/               # qc flags
│   ├── temporal/               # UTC parsing, overlap, windows
│   ├── spatial/                # common grid, point-to-grid
│   ├── observation/            # observation-opportunity representation
│   ├── matching/               # cross-sensor matching
│   ├── harmonization/          # calibration fits + activity index
│   ├── anomaly/                # robust z-score on daily per-cell counts
│   ├── frp/                    # FRP analysis
│   ├── quality/                # cross-sensor consistency metrics
│   ├── viz/                    # maps/charts
│   └── export/                 # output datasets + reports
├── app/                        # Flask application factory
│   ├── __init__.py
│   ├── db.py                   # DuckDB wiring
│   ├── errors.py               # structured JSON errors
│   ├── serialization.py        # JSON-safe timestamps/NaN
│   ├── schemas/                # pydantic request models
│   ├── routes/
│   │   └── v1/                 # ingestion, observations, jobs, ...
│   ├── services/               # call into src/harmonizer + shape responses
│   ├── templates/demo.html     # static demo page (no CDN, no build step)
│   └── jobs.py                 # simple background runner (Slice B)
├── scripts/
│   └── demo_run.py             # one-command end-to-end demo (calls the API)
├── tests/
├── notebooks/                  # thin, call the package only
└── docs/
    ├── api-endpoints.md        # 83 non-auth endpoints + status
    ├── dataset-facts.md
    ├── architecture.md
    ├── decisions.md
    └── phases/
```

## 2.1 Data flow (Slice A, implemented)

```
raw CSV (read-only)
   -> harmonizer.io.loaders (unified schema, raw_json preserved)
   -> DuckDB `observations` table
   -> harmonizer.store.sql (whitelisted, parameterised queries)
   -> app.services (shape JSON) -> app.routes.v1 (HTTP)
```

Ingestion is synchronous and recorded as a job with logs. Raw files are never
modified, and re-importing identical content is idempotent (SHA-256).

## 3. Flask API (added incrementally, per phase)

| Endpoint | Purpose | Added in |
|---|---|---|
| `GET /health` | liveness | Phase 00 |
| `GET /demo` | single-page read-only dashboard (calls the API) | Slice E |
| `POST /api/datasets` | register/upload a file (never modifies it) | Phase 01 |
| `GET /api/datasets` | list registered datasets | Phase 01 |
| `GET /api/datasets/<id>/audit` | schema, stats, quality flags | Phase 02 |
| `POST /api/runs` | start a pipeline run with a config | Phase 05+ |
| `GET /api/runs/<id>` | status + exact parameters used | Phase 05+ |
| `GET /api/runs/<id>/results` | harmonized output (CSV / GeoJSON) | Phase 09 |
| `GET /api/runs/<id>/metrics` | real validation metrics only | Phase 07 |

## 4. Deliberate decisions (scope control)

- **Jobs:** simple background thread with status stored on disk. No Celery/Redis (over-engineering for this scope).
- **Storage:** a single DuckDB analytical store for imported observations, runs, results and jobs (implemented).
- **Frontend:** one static page (`GET /demo`, vanilla JS) that reads the API; no CDN, no build step.
- **Libraries:** start with pandas, numpy, pyyaml, flask, pytest. Add GeoPandas/Shapely/PyProj/SciPy/scikit-learn **only when a phase needs them**, with justification.
- **Config:** every run saves a snapshot of its config next to its outputs.
- **Errors:** API returns structured JSON errors; never silently drops rows.

---
