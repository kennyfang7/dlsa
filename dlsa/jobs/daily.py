"""
Full daily pipeline entrypoint (make daily).

Usage: python -m dlsa.jobs.daily --config configs/daily.yaml --mode dry|paper|live

Defaults to dry-run. MODE=live additionally requires DLSA_CONFIRM_LIVE=yes
in the environment — two explicit steps between a fat-fingered make command
and a live order.

Pipeline: ingest → validate → compute_returns → factor model → signal ensemble
  → shrink → policy → overlays → build_portfolio → execution → reconcile → digest
"""
