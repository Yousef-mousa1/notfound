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
