# Installation Guide

Academic Research Pipeline v2.3.0 -- autonomous paper generation using PydanticAI, AutoGluon, and Docker.

---

## Prerequisites

### Required Software

| Software | Version | Check | Install |
|----------|---------|-------|---------|
| Python | 3.11 -- 3.13 | `python --version` | [python.org](https://www.python.org/downloads/) |
| uv | any | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv` |
| Git | any | `git --version` | [git-scm.com](https://git-scm.com/) |

### Optional Software

| Software | Version | Purpose | Check |
|----------|---------|---------|-------|
| Docker | 24+ | Experiment sandbox for ML code execution | `docker --version` |

### Required API Keys

| Variable | Get it at | Used for |
|----------|-----------|----------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/) | Primary generator (Claude Opus 4.6) -- all 38 agents |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/) | Cross-model evaluator panel (GPT-5.2) |
| `EXA_API_KEY` | [dashboard.exa.ai](https://dashboard.exa.ai/) | Bibliography search, dataset discovery |

### Optional API Keys

| Variable | Get it at | Used for |
|----------|-----------|----------|
| `S2_API_KEY` | [api.semanticscholar.org/my-account](https://api.semanticscholar.org/my-account) | Semantic Scholar (higher rate limits) |
| `LOGFIRE_TOKEN` | [logfire-us.pydantic.dev](https://logfire-us.pydantic.dev/) | Observability / tracing dashboard |

---

## Quick Install

```bash
git clone https://github.com/YZXBiz/academic-research-pipeline.git
cd academic-research-pipeline
make setup        # installs deps + copies .env.example -> .env
# Edit .env -- add your 3 required API keys
```

---

## Step-by-Step Install

### 1. Clone the repository

```bash
git clone https://github.com/YZXBiz/academic-research-pipeline.git
cd academic-research-pipeline
```

### 2. Install dependencies

```bash
uv sync --all-extras
```

`uv sync` reads `pyproject.toml`, resolves all dependencies (PydanticAI, httpx, exa-py, etc.), creates a virtual environment in `.venv/`, and installs everything. `--all-extras` includes optional dependency groups like test and dev tools. No `pip install` needed.

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in your API keys:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...      # Required. All agents run on Claude Opus 4.6.
OPENAI_API_KEY=sk-...             # Required. Cross-model evaluator panel uses GPT-5.2.
EXA_API_KEY=...                   # Required. Bibliography search and dataset discovery.
```

The pipeline uses `pydantic-settings` to load `.env` automatically -- no `load_dotenv()` or manual export needed.

### 4. Verify installation

```bash
uv run python -c "from academic_pipeline.config import get_config; print('OK')"
```

If this prints `OK`, dependencies are installed and configuration loads correctly.

### 5. (Optional) Build Docker sandbox

The experiment phase runs ML code inside a Docker container for isolation. Skip this if you plan to use subprocess fallback (`EXPERIMENT_USE_DOCKER=false`).

```bash
make docker-build
```

Verify the sandbox image:

```bash
docker run --rm academic-pipeline-sandbox:latest python -c "import autogluon; print('OK')"
```

For a larger image that includes PyTorch:

```bash
make docker-build-full
```

---

## Running the Pipeline

### Full run

```bash
uv run python -m academic_pipeline run "your research topic" --output-dir ./output --verbose
```

Or using Make:

```bash
make run TOPIC="your research topic"
```

### Cost Warning

A full pipeline run makes ~100-200 LLM calls across Claude Opus 4.6 and GPT-5.2. Expect **$15-40 per run** depending on topic complexity. Use `run-fast` to skip the evaluation panel and reduce cost.

### Fast mode (no evaluation panel)

```bash
make run-fast TOPIC="your research topic"
```

This sets `ENABLE_NODE_EVALUATION=false`, skipping the multi-model quality gate on each node. Faster and cheaper, but no quality guardrails.

### Individual phases

```bash
make research TOPIC="your topic"    # Research phase only
make write TOPIC="your topic"       # Writing phase only (requires prior research)
make review                         # Review phase only (requires prior write)
```

State persists between phases via `.pipeline_runs/`.

### Resume a crashed run

```bash
make resume THREAD_ID="abc123" TOPIC="your topic"
```

The pipeline uses SQLite-backed checkpointing. If a run crashes, resume from the last completed node.

---

## Configuration Reference

All variables are read from `.env` via `pydantic-settings`. Case-insensitive.

### API Keys

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(none)* | Anthropic API key for Claude models |
| `ANTHROPIC_BASE_URL` | *(empty)* | Custom API endpoint (for proxies/gateways) |
| `ANTHROPIC_MAX_RETRIES` | `3` | Max retries on Anthropic API errors |
| `OPENAI_API_KEY` | *(none)* | OpenAI API key for GPT models |
| `OPENAI_BASE_URL` | *(empty)* | Custom OpenAI endpoint |
| `EXA_API_KEY` | *(none)* | Exa neural search API key |
| `S2_API_KEY` | *(none)* | Semantic Scholar API key (optional, higher rate limits) |

### Model Selection

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_NAME` | `claude-opus-4-7` | Primary model for all agents |
| `CROSS_MODEL_NAME` | `openai:gpt-5.2` | Model for cross-model verification |

### Quality / Evaluation

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_NODE_EVALUATION` | `true` | Enable multi-model evaluator panel on each node |
| `NODE_QUALITY_THRESHOLD` | `7.0` | Minimum score (0-10) to pass a node |
| `MAX_NODE_ITERATIONS` | `2` | Max optimizer retries per node |
| `ENABLE_COMPLIANCE_CHECK` | `true` | Enable plan-alignment verification |

### Experiments

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPERIMENT_ENABLED` | `true` | Enable the experiment subgraph |
| `FORCE_EXPERIMENT` | `false` | Force experiments even if classifier says no |
| `EXPERIMENT_MAX_IMPROVEMENTS` | `2` | Max improvement iterations |
| `EXPERIMENT_TIMEOUT_SECONDS` | `1800` | Timeout per experiment execution (30 min) |
| `EXPERIMENT_SEEDS` | `[42, 123, 456]` | Seeds for multi-seed replication |

### Docker

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPERIMENT_USE_DOCKER` | `true` | Run experiments in Docker sandbox |
| `EXPERIMENT_DOCKER_IMAGE` | `academic-pipeline-sandbox:latest` | Docker image name |
| `EXPERIMENT_DOCKER_MEMORY` | `4g` | Memory limit for container |
| `EXPERIMENT_DOCKER_CPUS` | `2` | CPU limit for container |
| `EXPERIMENT_DOCKER_PASS_API_KEYS` | `false` | Pass API keys into container (security risk) |

### Email Alerts

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPERIMENT_ALERT_EMAIL` | *(empty)* | Email recipient for dataset-not-found alerts |
| `EXPERIMENT_ALERT_SENDER` | *(empty)* | Sender email address |
| `EXPERIMENT_SMTP_SERVER` | *(empty)* | SMTP server hostname |
| `EXPERIMENT_SMTP_PORT` | `25` | SMTP port |

### Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `TOOL_CALL_DELAY_SECONDS` | `10` | Delay between tool calls (set to `0` for no delay) |

### Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `LOGFIRE_TOKEN` | *(empty)* | Pydantic Logfire token (leave blank to skip) |

---

## Disabling Features

Set these in `.env` or pass as environment variables:

```bash
# Skip the multi-model evaluation panel (faster, cheaper, no quality gate)
ENABLE_NODE_EVALUATION=false

# Skip experiments entirely (paper without data/ML section)
EXPERIMENT_ENABLED=false

# Use subprocess instead of Docker for experiments
EXPERIMENT_USE_DOCKER=false
```

---

## Observability

Set `LOGFIRE_TOKEN` in `.env`. The pipeline auto-configures Logfire instrumentation on startup. View traces at [logfire-us.pydantic.dev](https://logfire-us.pydantic.dev/).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `uv: command not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| SSL errors behind proxy | `truststore` is a dependency and auto-injects system certificates. No manual cert config needed. |
| `ANTHROPIC_API_KEY not set` | Check that `.env` exists in the project root and contains the key. |
| Docker sandbox fails to start | Set `EXPERIMENT_USE_DOCKER=false` in `.env` for subprocess fallback. |
| Rate limit errors (429) | Increase `TOOL_CALL_DELAY_SECONDS` in `.env` (default is 10 seconds). |
| Out of memory during experiments | Reduce `EXPERIMENT_DOCKER_MEMORY` or set `EXPERIMENT_USE_DOCKER=false`. |
| `ModuleNotFoundError` | Run `uv sync --all-extras` to reinstall dependencies. |

---

## Corporate / Enterprise

**Behind SSL-intercepting proxy (Zscaler, Netskope):** `truststore` is included as a dependency and injects your system certificate store into Python's SSL context automatically. No manual `REQUESTS_CA_BUNDLE` or cert export needed.

**API gateway / proxy:** Set `ANTHROPIC_BASE_URL` and/or `OPENAI_BASE_URL` in `.env` to route through your corporate API gateway.

**Rate limits:** Increase `ANTHROPIC_MAX_RETRIES` (default: 3) and `TOOL_CALL_DELAY_SECONDS` (default: 10) in `.env` if you hit rate limits frequently.
