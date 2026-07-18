---
paths:
  - "dlsa/jobs/**/*.py"
  - "dlsa/execution/**/*.py"
---

# Shadow Book Rules — The Fence Is One-Directional

When `shadow.enabled` is true (post-G2, frozen param V6), the daily job
computes TWO books. Only one of them is real.

- **A `book='shadow'` order must be structurally unable to reach `submit()`.**
  The fence lives AT the submit boundary (Test 17), not in the caller — do not
  "refactor" it into the daily job where a code path can route around it.
- Shadow fills are counterfactual: priced through the X1/X2 cost model, never
  broker records. `reconcile()` never sees shadow rows.
- The G3.7 comparison (shadow vs. live over the same ≥ 60 trading days) is
  written to the V1 registry; do not compute ad-hoc versions in notebooks.
- κ (partial-adjustment rate) is frozen from V4 CPCV evidence at adoption —
  never tuned against live or shadow results.
- If `shadow.enabled` is false, this rule is a reminder, not a license to
  build the feature early: V6's trigger is G2 passing, nothing sooner.
