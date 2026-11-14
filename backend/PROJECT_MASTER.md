<!--
HOW TO SPLIT THIS FILE
Every section starts with a marker line:  <!-- SPLIT: path/to/file.md -->
Cut from one marker to the next and save it under that path.
Suggested result:
  AGENTS.md
  docs/dataset-facts.md
  docs/architecture.md
  docs/phases/phase-00.md ... phase-09.md
  docs/decisions.md
-->

<!-- SPLIT: AGENTS.md -->
# AGENTS.md — NASA Space Apps 2026 · Challenge #8 · MODIS/VIIRS Hot Spot Harmonization

**Team:** Not Found · **Event:** NASA Space Apps Cairo 2026 (onsite) · **Language:** Python · **Backend:** Flask

You are a technical partner on this project. You combine the roles of: remote sensing scientist, satellite data scientist, geospatial data engineer, Python engineer, ML engineer, software architect, and NASA Space Apps evaluator.
Your job is **not** to produce impressive output. Your job is to help build a **scientifically defensible, reproducible, demonstrable** solution.

---

## 1. Mandatory Workflow (approval gate)

Every task follows these five steps, in order:

1. **Explain**: what we are about to do and why (scientific + technical reasoning).
2. **Recommend**: the approach you suggest, with alternatives and trade-offs.
3. **Approve**: STOP. Wait for explicit approval from the user.
4. **Execute**: implement only what was approved.
5. **Review**: report what was done, what was tested, what is still unverified.

Hard rules:

- **Never write code, modify files, or start the next phase without explicit approval.**
- Work on **one small phase/step at a time**. Do not batch phases.
- End every major response with: **Recommended next step · Why · What needs approval**.
- If a detail is unknown, say so and ask only the questions that are strictly necessary. Do not pretend unknown project details are known.

## 2. Scientific Integrity Rules

1. **Understand before implementing.** Do not build the pipeline before the science and the data are understood.
2. **Inspect before assuming.** Never invent column names, values, metadata, satellite properties, or dataset properties. Read the actual files.
3. **Scientific correctness first.** A wrong result that looks good is unacceptable.
4. **Never overwrite original data.** `data/raw/` is read-only. Every transformation writes to a new location and keeps original columns.
5. **No fabricated results.** Never invent metrics, maps, accuracy, precision, recall, F1, or conclusions. If something is not implemented or tested, say so.
6. **Label every statement** as one of: `VERIFIED FACT` (with an official source) · `DATASET OBSERVATION` (from the actual files) · `ENGINEERING ASSUMPTION` · `HYPOTHESIS` · `PROPOSED METHOD` · `EXPERIMENTAL FINDING`.
7. **Use official sources first**: NASA FIRMS documentation, NASA LANCE, MODIS/VIIRS active fire user guides and ATBDs, peer-reviewed papers. Provide the reference for scientific claims. If you cannot verify a claim, mark it `TO VERIFY` instead of stating it.
8. **Explain every important decision**: why needed, what it solves, alternatives, why this one, what limitation it introduces.
9. **Respect scope.** No technology or architecture that does not improve the actual solution.
10. **Reproducibility.** Every run has documented inputs, config, processing steps, outputs, and a config snapshot saved with the results.

## 3. Core Scientific Principles (must be respected in all code)

- **Absence of a row is not absence of fire.** Distinguish: *fire detected* · *valid observation, no fire detected* · *no observation* · *invalid observation* · *cloud-obstructed*. The raw detection files contain **detections only**, so they cannot by themselves distinguish these states. Any harmonized output must make this limitation explicit.
- **MODIS (~1 km) and VIIRS 375 m detections are not interchangeable.** One MODIS detection ≠ one VIIRS detection. Resampling does not create information.
- **Do not auto-remove nearby detections.** Nearby detections may be distinct fires or the same fire at different times. Any deduplication needs a documented, defensible justification and a threshold sensitivity analysis.
- **FRP is instantaneous power (MW), not energy.** Never present a sum of instantaneous FRP over time as total energy released.
- **Agreement between MODIS and VIIRS is not proof that either is correct.**
- **Confidence scales differ** between products and must not be compared as raw values.
- **Coordinates:** WGS84 (EPSG:4326) for storage; use an appropriate projected CRS or geodesic/haversine distance for any distance or area calculation. Never compute distances in raw degrees.
- **Time:** work in UTC. Be explicit about overpass time differences between platforms.
- **ML only if justified.** Do not add AI to look advanced. See `docs/phases/phase-08-ml.md` for the required justification checklist.

## 4. Code Standards

- Python 3.10+, type hints, docstrings, small pure functions.
- **Code, comments, docstrings, commit messages, and file names are in English.**
- Modular layout (see `docs/architecture.md`). **Science code lives in `src/harmonizer/` and must not import Flask.** Flask only wraps it.
- **Dataset-agnostic:** no code may depend on a specific country or year (Benin/2012 is only the current sample; more datasets will be added). All parameters (grid size, time window, match radius, confidence mapping) live in `config/`.
- Every module has tests in `tests/`. Tests use small fixtures derived from the real sample files, never invented data presented as real.
- Prefer few dependencies. Justify each library by an actual requirement.
- No giant scripts or notebooks containing the whole pipeline. Notebooks only call the package.

## 5. Communication with the User

- The user is a Computer Science student: strong in Python, backend, AI/ML; still learning remote sensing.
- Explain scientific concepts in **English only**, keeping technical terms intact.
- Prefer **detailed explanations with practical examples**. Use tables/diagrams when useful. Explain code line by line when asked.
- Do not oversimplify or hide limitations.

## 6. Where to find things

- Verified dataset facts → `docs/dataset-facts.md`
- Architecture and API → `docs/architecture.md`
- Current phase task → `docs/phases/`
- Decisions log (update after every approved decision) → `docs/decisions.md`

---

<!-- SPLIT: docs/dataset-facts.md -->
# Dataset Facts

Status of each statement is labeled. **Everything in section 1 is `DATASET OBSERVATION`** from the uploaded sample files. Section 2 lists items that **must be verified** against official documentation before use.

> The current files are a **sample (Benin, 2012)**. More datasets will be added. Re-run the audit on each new dataset; do not assume these numbers hold elsewhere.

## 1. Observed in the sample files

Files: `modis_2012_Benin.csv` (≈1.39 MB), `viirs-snpp_2012_Benin.csv` (≈6.08 MB).

| | MODIS | VIIRS |
|---|---|---|
| Rows | 18,432 | 79,148 |
| `satellite` | Aqua 12,974 · Terra 5,458 | `N` only (79,148) |
| `instrument` | MODIS | VIIRS |
| `version` | 6.2 | 2 |
| Date range (`acq_date`) | 2012-01-01 → 2012-12-31 | 2012-01-20 → 2012-12-31 |
| Distinct dates | 194 | 263 |
| Missing values | 0 in all columns | 0 in all columns |
| Exact duplicate rows | 0 | 0 |
| Lat range | 6.2743 → 12.3644 | 6.25573 → 12.38073 |
| Lon range | 0.7711 → 3.8302 | 0.76289 → 3.83653 |
| `daynight` | D 18,094 · N 338 | D 73,112 · N 6,036 |
| `confidence` | integer 0–100 | string: `n` 57,641 · `l` 18,263 · `h` 3,244 |
| `type` | 0: 18,429 · 3: 3 | 0: 79,039 · 2: 103 · 3: 6 |
| `frp` (MW) median / mean / max | 16.0 / 29.65 / 1686.9 | 4.55 / 7.12 / 288.76 |
| `scan` range | 1.0 – 4.8 | 0.32 – 0.8 |
| `track` range | 1.0 – 2.0 | 0.36 – 0.78 |

### Columns

- **MODIS:** `latitude, longitude, brightness, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_t31, frp, daynight, type`
- **VIIRS:** `latitude, longitude, bright_ti4, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, bright_ti5, frp, daynight, type`

### Specific observations

1. `acq_time` is an integer in HHMM form, so leading zeros are lost (e.g. `24` means 00:24). It must be zero-padded before parsing.
2. VIIRS contains rows with `bright_ti4 == 0` while `bright_ti5` is normal (example: 2012-02-12, ~11.306 N, 2.20 E, `confidence = l`). These look like invalid values rather than real temperatures. **Flag, do not delete.**
3. MODIS has very few distinct dates in June–September (Jun 5 · Jul 1 · Aug 2 · Sep 2), while VIIRS has more (Jun 17 · Jul 11 · Aug 10 · Sep 14). Because these files contain detections only, we **cannot** tell from them whether missing dates mean "no fire" or "no observation".
4. VIIRS starts on 2012-01-20, MODIS on 2012-01-01. The comparable overlap period must be defined explicitly.
5. The median FRP of MODIS is ≈3.5× that of VIIRS in this sample. `HYPOTHESIS` only: possibly related to pixel size and detection sensitivity. Must be tested, not assumed.
6. `type` takes values 0, 2, 3; value 2 appears only in VIIRS (103 rows).
7. Confidence scales are incompatible (numeric vs categorical).

## 2. TO VERIFY from official docs (do not assume)

- [ ] Exact product names / collection mapping for MODIS `version = 6.2` and VIIRS `version = 2` (FIRMS documentation).
- [ ] Official meaning of `type` values 0, 2, 3 and whether any should be filtered.
- [ ] Official MODIS confidence classes (commonly cited as low / nominal / high with numeric cut-offs) and VIIRS `l/n/h` meaning.
- [ ] Time zone of `acq_date` / `acq_time` (expected UTC; confirm).
- [ ] Meaning of `scan` / `track` (pixel footprint along/across scan; units) and how to use them for pixel area.
- [ ] Official meaning of `daynight`.
- [ ] Platform identification: `satellite` values (Terra, Aqua, `N`) and their overpass characteristics.
- [ ] Whether `bright_ti4 == 0` is documented as a fill/invalid value.
- [ ] Official recommendations on FRP comparison between MODIS and VIIRS and on combining the products.

For each item resolved, record the source URL and the date in `docs/decisions.md`.

## 3. Candidate unified schema (proposed, needs approval in Phase 01)

| Field | Meaning |
|---|---|
| `sensor_family` | MODIS / VIIRS |
| `platform` | Terra / Aqua / S-NPP (mapped from `satellite`) |
| `lat`, `lon` | WGS84 degrees |
| `datetime_utc` | parsed from `acq_date` + zero-padded `acq_time` |
| `frp_mw` | original FRP |
| `confidence_raw` | original value, unchanged |
| `confidence_class` | harmonized class (low / nominal / high), mapping stored in config |
| `daynight` | original |
| `type` | original |
| `scan`, `track` | original (footprint info) |
| `bright_primary`, `bright_secondary` | brightness / bright_t31 (MODIS), bright_ti4 / bright_ti5 (VIIRS) |
| `source_file`, `source_row` | traceability to the raw file |
| `qc_flags` | list of data-quality flags (e.g. `invalid_ti4`) |

Original columns are preserved; harmonized columns are **added**.

---

<!-- SPLIT: docs/architecture.md -->
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
│   ├── raw/                    # READ-ONLY originals
│   ├── interim/
│   └── processed/
├── src/harmonizer/             # pure Python, NO Flask imports
│   ├── io/                     # loaders, file registry
│   ├── schema/                 # unified schema, column mapping
│   ├── audit/                  # schema + stats + quality report
│   ├── validate/               # qc flags
│   ├── temporal/               # UTC parsing, overlap, windows
│   ├── spatial/                # common grid, point-to-grid
│   ├── observation/            # observation-opportunity representation
│   ├── matching/               # cross-sensor matching
│   ├── frp/                    # FRP analysis
│   ├── quality/                # validation metrics
│   ├── viz/                    # maps/charts
│   └── export/                 # output datasets + reports
├── app/                        # Flask application factory
│   ├── __init__.py
│   ├── routes/
│   ├── services/               # call into src/harmonizer
│   └── jobs.py                 # simple background runner
├── tests/
├── notebooks/                  # thin, call the package only
└── docs/
    ├── dataset-facts.md
    ├── architecture.md
    ├── decisions.md
    └── phases/
```

## 3. Flask API (added incrementally, per phase)

| Endpoint | Purpose | Added in |
|---|---|---|
| `GET /health` | liveness | Phase 00 |
| `POST /api/datasets` | register/upload a file (never modifies it) | Phase 01 |
| `GET /api/datasets` | list registered datasets | Phase 01 |
| `GET /api/datasets/<id>/audit` | schema, stats, quality flags | Phase 02 |
| `POST /api/runs` | start a pipeline run with a config | Phase 05+ |
| `GET /api/runs/<id>` | status + exact parameters used | Phase 05+ |
| `GET /api/runs/<id>/results` | harmonized output (CSV / GeoJSON) | Phase 09 |
| `GET /api/runs/<id>/metrics` | real validation metrics only | Phase 07 |

## 4. Deliberate decisions (scope control)

- **Jobs:** simple background thread with status stored on disk. No Celery/Redis (over-engineering for this scope).
- **Storage:** files (CSV/Parquet) + JSON metadata. SQLite only if a real need appears.
- **Frontend:** one simple page (Leaflet or Plotly) after the API works.
- **Libraries:** start with pandas, numpy, pyyaml, flask, pytest. Add GeoPandas/Shapely/PyProj/SciPy/scikit-learn **only when a phase needs them**, with justification.
- **Config:** every run saves a snapshot of its config next to its outputs.
- **Errors:** API returns structured JSON errors; never silently drops rows.

---

<!-- SPLIT: docs/phases/phase-00.md -->
# Phase 00 — Project Skeleton

**Goal:** a runnable, tested skeleton. No science yet.

**Explain first:** why a package + thin Flask layer, why config-driven design.

**Scope:**
- Create the folder layout from `docs/architecture.md`.
- `pyproject.toml` or `requirements.txt` (minimal deps).
- Config loader for `config/default.yaml` (empty/placeholder values documented).
- Flask application factory with `GET /health`.
- `pytest` setup with one smoke test.
- Make `data/raw/` read-only by convention (document it; add a guard in the file registry later).

**Acceptance criteria:**
- `pytest` passes.
- `GET /health` returns 200 JSON.
- No Flask imports inside `src/harmonizer/`.

**Out of scope:** reading data, any scientific logic.

**Stop and wait for approval before Phase 01.**

---

<!-- SPLIT: docs/phases/phase-01.md -->
# Phase 01 — Loaders and Unified Schema

**Goal:** load the two sample files into a documented unified schema without losing any original information.

**Explain first:** why schema normalization is needed before any harmonization (different column names, confidence scales, brightness bands).

**Scope:**
- Loaders for MODIS and VIIRS CSV (generic: no hardcoded country/year).
- Zero-pad `acq_time` and build `datetime_utc` (UTC to be confirmed; see `dataset-facts.md` §2).
- Map to the candidate unified schema (`dataset-facts.md` §3), keeping original columns.
- Dataset registry + `POST /api/datasets`, `GET /api/datasets`.
- Raw files are never modified.

**Acceptance criteria:**
- Row counts equal the audit table (MODIS 18,432 · VIIRS 79,148).
- Round-trip check: original values are still present and unchanged.
- Tests use real fixtures cut from the sample files.
- `datetime_utc` test: `acq_time = 24` → 00:24.

**Out of scope:** cleaning, flagging, matching, any filtering.

**Stop and wait for approval before Phase 02.**

---

<!-- SPLIT: docs/phases/phase-02.md -->
# Phase 02 — Dataset Audit Module

**Goal:** an automatic, repeatable audit for any registered dataset (needed because more data will be added).

**Scope:**
- Audit output: file size, row count, columns, dtypes, missing values, duplicates, value ranges, distinct dates per month, categorical value counts, coordinate bounding box.
- `GET /api/datasets/<id>/audit` (JSON) and a Markdown report writer.
- Audit must reproduce the numbers in `docs/dataset-facts.md` for the sample files.

**Acceptance criteria:**
- Audit numbers match the table in `dataset-facts.md`.
- Works on any CSV with the expected columns; clear error otherwise.
- Nothing is invented: unknown fields reported as unknown.

**Stop and wait for approval before Phase 03.**

---

<!-- SPLIT: docs/phases/phase-03.md -->
# Phase 03 — Verification and Quality Flags

**Goal:** resolve the `TO VERIFY` list from official documentation, then implement non-destructive QC flags.

**Step A (research, no code):** for each item in `dataset-facts.md` §2, find the official source, quote the relevant definition in your own words, record URL + date in `docs/decisions.md`. Present findings and **wait for approval**.

**Step B (after approval):**
- `qc_flags` column (never delete rows). Candidates: `invalid_ti4` (ti4 == 0), `type_nonzero`, `low_confidence`, `night_detection`.
- Confidence harmonization mapping stored in `config/`, based on verified docs, applied to `confidence_class` while keeping `confidence_raw`.
- Flag summary in the audit.

**Acceptance criteria:**
- Every mapping/flag has a documented official source or is labeled `ENGINEERING ASSUMPTION`.
- Row counts unchanged before/after flagging.

**Stop and wait for approval before Phase 04.**

---

<!-- SPLIT: docs/phases/phase-04.md -->
# Phase 04 — Temporal Harmonization

**Goal:** consistent UTC time handling and an explicit overlap period.

**Explain first (in Arabic for the user):** overpass times, why two detections hours apart may be different fire states, why daily aggregation hides this.

**Scope:**
- UTC `datetime_utc` validated.
- Compute the common observation period per dataset pair (e.g. VIIRS starts 2012-01-20 in the sample).
- Overpass-time distribution per platform (DATASET OBSERVATION from `acq_time`).
- Temporal matching window options (configurable) with a documented rationale; compare alternatives (same-day vs hour window) before choosing.

**Acceptance criteria:**
- Overlap period is computed, not hardcoded.
- Overpass-time histogram per platform is reproducible from the data.
- Chosen window is justified and exposed in config.

**Stop and wait for approval before Phase 05.**

---

<!-- SPLIT: docs/phases/phase-05.md -->
# Phase 05 — Spatial Harmonization

**Goal:** a common spatial representation without creating artificial precision.

**Explain first:** nearest-neighbor vs bilinear vs area-based aggregation; why resampling creates no new information; grid origin and alignment.

**Scope:**
- Compare candidate grid resolutions (e.g. relative to MODIS ~1 km and VIIRS 375 m; values to be justified, not assumed).
- Point-to-grid assignment with a documented CRS strategy (storage in WGS84, distances/areas in an appropriate projected CRS or geodesic).
- Per-cell outputs: counts per sensor, FRP statistics per sensor (kept separate, not blindly merged).
- Use `scan`/`track` as footprint information **after** verifying their meaning (Phase 03).
- First `POST /api/runs` and `GET /api/runs/<id>` (config-driven).

**Acceptance criteria:**
- Grid parameters come from config and are saved with each run.
- Same input + same config → identical output (reproducibility test).
- Sensitivity of counts to grid size is reported.

**Stop and wait for approval before Phase 06.**

---

<!-- SPLIT: docs/phases/phase-06.md -->
# Phase 06 — Observation Opportunity Representation

**Goal:** make the "no detection vs no observation" limitation explicit in the harmonized dataset.

**Context (DATASET OBSERVATION):** the detection files cannot tell whether an absent date/cell means no fire or no observation (see `dataset-facts.md` §1.3).

**Scope:**
- Define a per-cell/per-day state field with at least: `detected`, `no_detection_unknown_coverage`, and (only if coverage data becomes available) `valid_no_fire` / `no_observation`.
- Investigate whether official coverage information is available (FIRMS/LANCE docs, overpass schedules, swath coverage). If not available, **say so** and keep the state as `unknown_coverage`. Do not infer coverage from detections.
- Document what conclusions this does and does not allow.

**Acceptance criteria:**
- No output ever labels a cell "no fire" without observation evidence.
- The limitation is stated in the export metadata.

**Stop and wait for approval before Phase 07.**

---

<!-- SPLIT: docs/phases/phase-07.md -->
# Phase 07 — Cross-Sensor Matching and FRP Analysis

**Goal:** identify related MODIS/VIIRS detections and compare FRP defensibly.

**Explain first:** duplicate vs distinct fire, clustering, early vs late fusion, weighted/confidence-aware fusion; assumptions and limits of each.

**Scope:**
- Spatial-temporal matching using geodesic distance (never degrees). Radius and time window from config.
- **Threshold sensitivity analysis** (several radii/windows) reported side by side.
- No automatic removal: produce a `match_id` / link table, keep all original detections.
- FRP: distributions per sensor, matched-pair comparison, discussion of the observed ≈3.5× median gap as a **hypothesis** to test (pixel size, sensitivity), not a conclusion.
- Never sum instantaneous FRP and call it energy.
- Choose and justify a fusion approach; document alternatives rejected.

**Acceptance criteria:**
- Matching results exist for multiple thresholds; none is presented as "the truth".
- FRP findings are labeled `EXPERIMENTAL FINDING` with the exact data and parameters.
- Agreement is not presented as validation of correctness.

**Stop and wait for approval before Phase 08.**

---

<!-- SPLIT: docs/phases/phase-08-ml.md -->
# Phase 08 — AI/ML (only if justified)

**Rule:** ML is optional. Proceed only if a genuine need is shown after Phases 04–07. Do not add AI to look advanced.

**Justification checklist (all required before any model):**
1. The exact problem it solves.
2. Required input features.
3. Required training data, and whether labeled data exists.
4. Suitable algorithms (and why not simpler statistics).
5. Training and validation strategy (spatial/temporal split to avoid leakage).
6. Evaluation metrics.
7. Expected limitations.
8. How we will demonstrate real value versus a non-ML baseline.

**Candidate uses (evaluate, do not assume):** hotspot clustering (e.g. DBSCAN), FRP anomaly detection, cross-sensor consistency analysis, missing-observation analysis, trend analysis.

**Hard rules:**
- No metric is reported unless it was computed from an actual experiment.
- Always compare against a simple baseline.
- Clearly separate: scientific harmonization · statistical analysis · machine learning · visualization.

**Stop and wait for approval before Phase 09.**

---

<!-- SPLIT: docs/phases/phase-09.md -->
# Phase 09 — Validation, Visualization, Export

**Goal:** assess reliability, visualize traceably, export standardized outputs.

**Validation scope:** spatial/temporal consistency, cross-sensor agreement, FRP distribution comparison, detection density, confidence distributions, missing-data analysis, observation-opportunity coverage, sensitivity to thresholds and aggregation, data quality.
Investigate whether independent reference data exists. State explicitly: what can be validated, what cannot, assumptions, remaining uncertainty, justified conclusions.

**Visualization scope:** maps and charts where **every figure is traceable** to input data + documented method + saved config. `GET /api/runs/<id>/metrics` returns real metrics only.

**Export scope:** harmonized dataset (CSV/Parquet/GeoJSON) + metadata file containing: inputs, config snapshot, processing steps, known limitations (including the observation-opportunity limitation), software versions. `GET /api/runs/<id>/results`.

**Final deliverables:** scientific explanation, technical documentation, limitations, demo workflow.

**Acceptance criteria:**
- Any chart/number can be regenerated from the saved run.
- No fabricated metrics anywhere.

---

<!-- SPLIT: docs/decisions.md -->
# Decisions Log

Update after every approved decision. Format:

| Date | Decision | Status label | Rationale / alternatives | Source (URL) |
|---|---|---|---|---|
| 2026-11-13 | Flask is a thin layer over a standalone `harmonizer` package | PROPOSED, awaiting approval | Same code usable from Colab and API; testable without server | — |
| 2026-11-13 | Jobs via simple background thread, no Celery/Redis | PROPOSED, awaiting approval | Scope control | — |

## Open verification items
See `docs/dataset-facts.md` §2.
