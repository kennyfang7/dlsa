---
paths:
  - "dlsa/overlays/news_v2/**/*.py"
---

# News Gate v2 Rules — Model Weights Are Data Too

- **Any LLM/embedding model used in a backtest must be vintage-stamped** —
  trained only on text available before the backtest date (ChronoBERT/
  ChronoGPT class, frozen param V8). Standard FinBERT/Llama weights leak
  post-period knowledge through their parameters — a leakage class
  test_lookahead_bias.py cannot see, because it lives outside the data lake.
- Embedding model versions are registry artifacts like any other model:
  pinned, versioned, never "latest".
- Gate behavior remains freeze-not-flatten (O7) and shrink-only (O4) —
  v2 changes the SIGNAL for gating, never the disposition algebra.
