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
