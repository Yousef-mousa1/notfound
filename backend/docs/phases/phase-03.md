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
