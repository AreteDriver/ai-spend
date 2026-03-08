# ai-spend

AI API cost aggregator CLI. Syncs usage data from Anthropic and OpenAI admin APIs into a local SQLite database, then provides summary/daily/budget commands.

## Quick Start

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v --cov=ai_spend --cov-report=term-missing
ruff check src/ tests/ && ruff format --check src/ tests/
```

## Architecture

- `src/ai_spend/` — 18 source modules, src/ layout
- `models.py` — Pydantic v2 models + StrEnums (Python 3.10 backport)
- `store.py` — SQLite WAL (4 tables: providers, usage_records, budgets, sync_log)
- `config.py` — YAML config (~/.ai-spend/config.yaml, 0o600 perms), singleton SpendStore
- `providers/` — BaseProvider ABC + self-registering registry pattern (Anthropic, OpenAI, Manual)
- `cli.py` — Typer app with sub-Typers (config, budget, manual) + stats command
- `licensing.py` — ASPD-XXXX-XXXX-XXXX keys, ai-spend-v1 salt, SHA256 checksum validation
- `gates.py` — `@require_pro(feature)` decorator, tracks Pro gate hits via telemetry
- `telemetry.py` — Local-only usage telemetry (separate telemetry.db, SQLite WAL, opt-in via AI_SPEND_TELEMETRY=1)
- `reporter.py` — Rich table formatters + CSV/JSON export + stats display

## Conventions

- Python 3.10+, type hints throughout
- `from __future__ import annotations` in modules with complex types
- Tests: pytest, respx for httpx mocking, CliRunner for CLI
- Lint: `ruff check . && ruff format .` (BOTH required — check does not verify formatting)
- Coverage: 90%+ (fail_under=90), currently 248 tests at 90%+

## Key Patterns

- Deterministic record IDs: `sha256(provider_id:date:model)[:16]` for INSERT OR REPLACE dedup
- Sync-then-read: `ai-spend sync` hits APIs, all other commands read from local SQLite cache
- Provider registry: `register_provider()` at module import time, `get_provider()` factory
- Config in YAML (keys), data in SQLite (usage records) — keys never touch the database
- Free/Pro gating: `@require_pro(feature)` decorator, ASPD license keys via AI_SPEND_LICENSE env var
- Telemetry: opt-in local counters (AI_SPEND_TELEMETRY=1), `track_command()` in every CLI command, `track_pro_gate()` on free-tier Pro feature attempts. Separate telemetry.db in config dir. Never transmits data
- License key checksum: `SHA256("ai-spend-v1:body")[:4].upper()` — offline validation

## Testing

```bash
pytest tests/ -v --cov=ai_spend --cov-report=term-missing
```

- Test isolation: tmp_path fixtures for DB and config dirs
- Mock providers: respx for httpx (Anthropic/OpenAI API mocking)
- Pro feature tests: `patch.dict("os.environ", {"AI_SPEND_LICENSE": valid_key})`
- Telemetry tests: patch `ai_spend.config.get_config_dir` (not telemetry module — lazy import)

## Commands

- `ai-spend config add/remove/list` — Provider management (max 3 free, unlimited Pro)
- `ai-spend sync` — Fetch usage from provider APIs
- `ai-spend summary [--json] [--days N]` — Aggregated spend (default 30d)
- `ai-spend daily [--last N] [--json]` — Daily breakdown (default 7d)
- `ai-spend budget set/check` — Budget tracking (singleton row)
- `ai-spend manual add` — Manual cost entries
- `ai-spend export [--format json|csv]` — JSON/CSV export (Pro)
- `ai-spend status` — System overview + sync history
- `ai-spend stats [--json]` — Local telemetry dashboard (requires AI_SPEND_TELEMETRY=1)
