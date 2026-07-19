.PHONY: setup test test-leakage backtest daily lint broker-smoke digest select sleeve-b backup

setup:            ## create venv + install pinned deps
	uv sync

lint:
	uv run ruff check . && uv run ruff format --check .

test:             ## full suite — MUST pass before any commit
	uv run pytest -q

test-leakage:     ## look-ahead/survivorship tests only (<~2 min via test_min.yaml)
	uv run pytest tests/test_lookahead_bias.py -v

backtest:         ## CONFIG overridable: make backtest CONFIG=configs/experiment_x.yaml
	uv run python -m dlsa.backtest.run --config $(or $(CONFIG),configs/backtest.yaml)

select:           ## V4 CPCV model selection — candidates via CANDIDATES=configs/candidates/*.yaml
	uv run python -m dlsa.selection.run --candidates $(or $(CANDIDATES),configs/candidates)

sleeve-b:         ## V9a OSAP ridge composite through the SAME engine (G1.4: a signal config, never a
		  ## second simulator). configs/sleeve_b.yaml is created at Phase 2 as a backtest.yaml
		  ## derivative — only signal wiring + run.name may differ; its hash is its own V1 trial.
		  ## Records the G2.8 sleeve-correlation evidence C9's trigger needs. Dormant before Phase 2.
	uv run python -m dlsa.backtest.run --config configs/sleeve_b.yaml

daily:            ## full daily pipeline, DRY-RUN unless MODE=paper|live is explicit
	uv run python -m dlsa.jobs.daily --config configs/daily.yaml --mode $(or $(MODE),dry)

broker-smoke:     ## fetch account, fetch a bar, place+cancel one paper limit order; verifies
		  ## on-close (cls) entitlement and fractional/on-close interaction (E6, C6)
	uv run python -m dlsa.execution.smoke

digest:           ## render yesterday's daily digest to stdout
	uv run python -m dlsa.monitoring.digest

backup:           ## N11 (E2/V1 durability riders, page 04): off-machine copy of data_lake/journal.sqlite
		  ## + data_lake/runs/ (restic/rclone acceptable; destination via BACKUP_REMOTE in .env).
		  ## Run nightly by the systemd timer alongside `daily` — a disk loss must not silently
		  ## reset n_trials or destroy the order audit trail. Cheap from Phase 0; REQUIRED before Phase 3.
	uv run python -m dlsa.ops.backup
