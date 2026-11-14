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
