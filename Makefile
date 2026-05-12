.DEFAULT_GOAL := help

# Put src/ on PYTHONPATH for every target. Bypasses hatchling's editable
# install which is broken under Python 3.13 (underscore-prefixed .pth files
# are silently skipped by site.py for security). This works regardless of
# uv / hatchling / Python version.
export PYTHONPATH := $(CURDIR)/src$(if $(PYTHONPATH),:$(PYTHONPATH))

help: ## Show this help message
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$|^##@' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

##@ Setup

.PHONY: help setup install

setup: ## First-time setup (copy .env + install deps)
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")
	@test -f .env && echo ".env already exists, skipping copy" || true
	uv sync --frozen --all-extras
	@echo ""
	@echo "Setup complete. Next steps:"
	@echo "  1. Edit .env and fill in your API keys"
	@echo "  2. Run 'make test' to verify everything works"
	@echo "  3. Run 'make docker-build' to build the experiment sandbox (required for experiments)"
	@echo "  4. Run 'make run TOPIC=\"your topic\"' to generate a paper"
	@echo ""

install: ## Install all dependencies
	uv sync --frozen --all-extras

##@ Pipeline

.PHONY: run run-fast run-experiment run-experiment-debug run-experiment-fast watchdog resume resume-bare list-runs open-report

run: ## Run full pipeline — make run TOPIC="your topic"
	uv run --frozen python -m academic_pipeline run "$(TOPIC)" --output-dir ./output --verbose

run-experiment: ## Force experiment phase, supervised — make run-experiment TOPIC="your topic"
	uv run --frozen python -m academic_pipeline supervised-run "$(TOPIC)" --force-experiment --output-dir ./output

run-experiment-debug: ## Force experiment, NO watchdog (for debugging) — make run-experiment-debug TOPIC="..."
	uv run --frozen python -m academic_pipeline supervised-run "$(TOPIC)" --force-experiment --no-watchdog --output-dir ./output

watchdog: ## Run watchdog standalone — make watchdog THREAD_ID=run-XXXX
	uv run --frozen python -m academic_pipeline watchdog "$(THREAD_ID)" --auto-resume --output-dir ./output

run-experiment-fast: ## Force experiment, skip eval panel — make run-experiment-fast TOPIC="your topic"
	ENABLE_NODE_EVALUATION=false uv run --frozen python -m academic_pipeline run "$(TOPIC)" --output-dir ./output --verbose --force-experiment

run-fast: ## Run without evaluation panel — make run-fast TOPIC="your topic"
	ENABLE_NODE_EVALUATION=false uv run --frozen python -m academic_pipeline run "$(TOPIC)" --output-dir ./output --verbose

open-report: ## Open the latest experiment HTML report in browser
	@test -f output/latest/02-experiment/index.html && open output/latest/02-experiment/index.html || echo "No experiment report found. Run a pipeline with --force-experiment first."

resume: ## Resume a crashed run, supervised — make resume THREAD_ID="run-0430-1123_c4f7"
	uv run --frozen python -m academic_pipeline supervised-resume "$(THREAD_ID)" --output-dir ./output

resume-bare: ## Resume WITHOUT supervisor (no hang recovery) — for debugging only
	uv run --frozen python -m academic_pipeline resume "$(THREAD_ID)" --output-dir ./output --verbose

list-runs: ## List previous runs with their thread IDs
	@sqlite3 .pipeline_runs/pipeline.sqlite \
		"SELECT s.run_id, json_extract(p.state_json, '$$.topic') AS topic, COUNT(*) AS nodes, MAX(s.created_at) AS last_active FROM snapshots s LEFT JOIN pipeline_state p ON s.run_id = p.run_id GROUP BY s.run_id ORDER BY last_active DESC;" \
		-header -column 2>/dev/null || echo "No runs found (.pipeline_runs/pipeline.sqlite does not exist)"

##@ Quality

.PHONY: test test-integration test-all test-e2e cov lint format typecheck check

test: ## Run unit tests (small only, < 30s)
	AGENT_CALL_DELAY_SECONDS=0 TOOL_CALL_DELAY_SECONDS=0 uv run --frozen pytest tests/ -x -q

test-integration: ## Run Docker integration tests (medium, ~3 min)
	uv run --frozen pytest -m medium -v

test-all: ## Run small + medium tests
	AGENT_CALL_DELAY_SECONDS=0 TOOL_CALL_DELAY_SECONDS=0 uv run --frozen pytest -m 'not large' -v

test-e2e: ## Run real API tests (large, requires API keys)
	uv run --frozen pytest -m large -v

test-traceability: ## Run SCI traceability layer unit tests
	uv run --frozen pytest tests/unit/traceability/ -x -q

test-traceability-medium: ## Run traceability medium tests (PDF audit if fixture present)
	uv run --frozen pytest tests/medium/traceability/ -m medium -v

test-traceability-regressions: ## Run validator regression suite (historical fabrications)
	uv run --frozen pytest tests/unit/traceability/test_validator_regressions.py -x -v

cov: ## Run tests with coverage
	AGENT_CALL_DELAY_SECONDS=0 TOOL_CALL_DELAY_SECONDS=0 uv run --frozen pytest tests/ -v --cov=academic_pipeline --cov-report=term-missing

lint: ## Ruff lint check
	uv run --frozen ruff check src/academic_pipeline/ tests/

format: ## Auto-format code
	uv run --frozen ruff format src/academic_pipeline/ tests/
	uv run --frozen ruff check --fix src/academic_pipeline/ tests/

typecheck: ## Basedpyright type check
	npx basedpyright src/academic_pipeline/

version-check: ## Verify VERSION / pyproject.toml / README badges agree (PRD §6.12.T6)
	uv run --frozen python tools/check_version_consistency.py

check: version-check lint typecheck test ## Full quality gate (version + lint + types + tests)
	@echo "=== All checks PASSED ==="

##@ Cleanup

.PHONY: clean clean-db clean-old

clean: ## Remove caches and ALL output
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache htmlcov .coverage output/ .pipeline_runs/

clean-db: ## Reset pipeline SQLite database (keeps state JSON files)
	rm -f .pipeline_runs/pipeline.sqlite
	@echo "Pipeline database reset"

clean-old: ## Remove old runs, keep only latest
	@if [ -L output/latest ]; then \
		latest=$$(readlink output/latest); \
		for d in output/*/; do \
			name=$$(basename "$$d"); \
			if [ "$$name" != "$$latest" ] && [ "$$name" != "latest" ]; then \
				rm -rf "$$d"; \
				echo "Removed output/$$name"; \
			fi; \
		done; \
		echo "Kept output/$$latest"; \
	else \
		echo "No latest symlink found — nothing to clean"; \
	fi

##@ Docker

.PHONY: docker-build docker-build-full

docker-build: ## Build experiment sandbox Docker image (required for experiments)
	cd docker/experiment && docker build -t academic-pipeline-sandbox:latest .

docker-build-full: ## Build sandbox with PyTorch (larger image)
	cd docker/experiment && docker build -t academic-pipeline-sandbox:latest --build-arg INSTALL_TORCH=true .
