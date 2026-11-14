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
