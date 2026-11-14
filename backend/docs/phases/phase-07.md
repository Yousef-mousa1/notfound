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
