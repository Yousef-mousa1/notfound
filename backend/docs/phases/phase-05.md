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
