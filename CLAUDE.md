# ai-spend

AI API cost aggregator CLI. Syncs usage data from Anthropic and OpenAI admin APIs into a local SQLite database, then provides summary/daily/budget commands.

## Quick Start

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/ && ruff format --check src/ tests/
```

## Architecture

- `src/ai_spend/` — 17 source modules, src/ layout
- `models.py` — Pydantic v2 models + StrEnums
- `store.py` — SQLite WAL (4 tables)
- `config.py` — YAML config (~/.ai-spend/config.yaml, 0o600 perms)
- `providers/` — BaseProvider ABC + registry pattern (Anthropic, OpenAI, Manual)
- `cli.py` — Typer app with sub-Typers (config, budget, manual)
- `licensing.py` — ASPD-XXXX-XXXX-XXXX keys, ai-spend-v1 salt

## Conventions

- Python 3.10+, type hints throughout
- `from __future__ import annotations` in modules with complex types
- Tests: pytest, respx for httpx mocking, CliRunner for CLI
- Lint: `ruff check . && ruff format .`
- Coverage: 90%+ (fail_under=90)

## Key Patterns

- Deterministic record IDs: `sha256(provider_id:date:model)[:16]` for INSERT OR REPLACE dedup
- Sync-then-read: `ai-spend sync` hits APIs, all other commands read from local SQLite cache
- Provider registry: `register_provider()` at module import time, `get_provider()` factory
- Config in YAML (keys), data in SQLite (usage records) — keys never touch the database
- Free/Pro gating: `@require_pro(feature)` decorator, ASPD license keys

## Testing

```bash
pytest tests/ -v --cov=ai_spend --cov-report=term-missing
```

## Commands

- `ai-spend config add/remove/list` — Provider management
- `ai-spend sync` — Fetch usage from provider APIs
- `ai-spend summary [--json]` — Aggregated spend
- `ai-spend daily [--last N] [--json]` — Daily breakdown
- `ai-spend budget set/check` — Budget tracking
- `ai-spend manual add` — Manual cost entries
- `ai-spend export` — JSON/CSV export (Pro)
- `ai-spend status` — System overview
