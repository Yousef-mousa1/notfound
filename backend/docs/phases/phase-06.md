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
