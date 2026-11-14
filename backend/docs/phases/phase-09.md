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
