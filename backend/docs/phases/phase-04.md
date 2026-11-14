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
