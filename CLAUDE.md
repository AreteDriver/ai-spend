# ai-spend

## Project Overview

AI API cost aggregator CLI. Syncs usage data from Anthropic and OpenAI admin APIs into a local SQLite database, then provides summary / daily / budget commands.

**Type**: Freemium CLI (BSL-1.1, PyPI: `ai-spend`)
**Version**: 0.2.0
**Language**: Python 3.10+
**Monetization**: Free tier + Pro ($ via ASPD-XXXX-XXXX-XXXX license keys, Stripe-automated fulfillment)

---

## Architecture

```
ai-spend/
├── src/ai_spend/           # Package (src/ layout)
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py              # Typer app with sub-Typers (config, budget, manual) + stats
│   ├── models.py           # Pydantic v2 models + StrEnums
│   ├── store.py            # SQLite WAL — 4 tables: providers, usage_records, budgets, sync_log
│   ├── config.py           # YAML config (~/.ai-spend/config.yaml, 0o600), singleton SpendStore
│   ├── providers/          # BaseProvider ABC + self-registering registry (Anthropic, OpenAI, Manual)
│   ├── budget.py           # Budget tracking (singleton row)
│   ├── reporter.py         # Rich tables + CSV/JSON export + stats display
│   ├── licensing.py        # ASPD license keys, SHA256 checksum, offline validation
│   ├── gates.py            # @require_pro(feature) decorator
│   ├── telemetry.py        # Opt-in local counters (AI_SPEND_TELEMETRY=1), separate telemetry.db
│   └── exceptions.py
├── tests/                  # 248 tests, 90%+ coverage
├── pyproject.toml
└── README.md
```

### Key Design

- **Sync-then-read**: `ai-spend sync` hits APIs, all other commands read from local SQLite cache
- **Deterministic record IDs**: `sha256(provider_id:date:model)[:16]` for `INSERT OR REPLACE` dedup
- **Provider registry**: `register_provider()` at module import time, `get_provider()` factory
- **Config vs data separation**: YAML stores keys, SQLite stores usage records — keys never touch the database
- **Free/Pro gating**: `@require_pro(feature)` decorator, ASPD license keys via `AI_SPEND_LICENSE` env var
- **License checksum**: `SHA256("ai-spend-v1:{body}")[:4].upper()` — offline validation, no network call required
- **Telemetry**: opt-in (`AI_SPEND_TELEMETRY=1`), `track_command()` in every CLI command, `track_pro_gate()` on free-tier Pro feature attempts. Separate `telemetry.db` in config dir. Never transmits data.

---

## Common Commands

### Setup

```bash
# Dev environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### CLI Usage

```bash
# Provider management (max 3 free, unlimited Pro)
ai-spend config add
ai-spend config remove
ai-spend config list

# Sync from provider APIs
ai-spend sync

# Reports (read from local cache)
ai-spend summary --json --days 30
ai-spend daily --last 7 --json

# Budget tracking
ai-spend budget set
ai-spend budget check

# Manual entries
ai-spend manual add

# Export (Pro)
ai-spend export --format json
ai-spend export --format csv

# System + telemetry
ai-spend status
ai-spend stats --json   # requires AI_SPEND_TELEMETRY=1
```

### Testing

```bash
# Run full suite with coverage
pytest tests/ -v --cov=ai_spend --cov-report=term-missing

# Specific test file
pytest tests/test_providers.py -v
```

### Lint + Format

```bash
# Always run BOTH — ruff check does not verify formatting
ruff check src/ tests/
ruff format src/ tests/

# CI-style verification
ruff check src/ tests/ && ruff format --check src/ tests/
```

### Build + Publish

```bash
# Build wheel + sdist
python3 -m build

# Publish to PyPI (via trusted publisher / OIDC in CI)
twine upload dist/*
```

---

## Coding Standards

- **Python**: 3.10+, type hints throughout, `from __future__ import annotations` in modules with complex types
- **Quote style**: double quotes
- **Naming**: `snake_case` functions/vars, `PascalCase` classes, `UPPER_SNAKE` constants
- **Imports**: absolute, stdlib → third-party → local, alphabetized within groups
- **Path handling**: `pathlib.Path` everywhere — no `os.path`
- **Errors**: custom exceptions in `exceptions.py`, `raise ... from exc` in re-raises
- **Line length**: ruff default (88)
- **Testing**: pytest, `respx` for httpx mocking, `CliRunner` for CLI, `tmp_path` for DB and config isolation
- **Coverage**: 90%+ (`fail_under = 90` in pyproject); new code must carry tests

---

## Anti-Patterns

- **Secrets in CLAUDE.md or commits** — API keys belong only in `~/.ai-spend/config.yaml` (0o600). Never hardcode.
  ```python
  # BAD
  client = Anthropic(api_key="sk-ant-abc123")
  # GOOD
  client = Anthropic(api_key=config.get_provider_key("anthropic"))
  ```
- **`os.path` usage** — use `pathlib.Path` everywhere
- **Bare `except:`** — catch specific exceptions
- **Mutable default arguments** — `def f(x=[])` is a bug magnet
- **`print()` for logging** — use the `logging` module
- **Plaintext license keys in DB** — never store; validate via checksum + env var
- **Modifying pricing without approval** — Stripe products/prices are source of truth, not code
- **Skipping `ruff format`** — `ruff check` alone doesn't verify formatting; CI will fail
- **Re-running `ai-spend sync` without rate-limit awareness** — deterministic IDs prevent duplication, but each sync still burns provider API quota

---

## Dependencies

### Core (pyproject `[project] dependencies`)
- `typer>=0.9.0` — CLI framework
- `rich>=13.0.0` — terminal rendering
- `pydantic>=2.0.0` — models + validation
- `pyyaml>=6.0` — config file
- `httpx>=0.27.0` — async HTTP to provider APIs

### Dev (pyproject `[project.optional-dependencies] dev`)
- `pytest>=8.0`
- `pytest-cov>=5.0`
- `ruff>=0.8.0`
- `respx>=0.22.0` — httpx mocking

### External Services
- **Anthropic Admin API**: usage pull (requires admin-scoped key)
- **OpenAI Admin API**: usage pull (requires admin-scoped key)
- **License server** (Pro only): `https://cmdf-license.fly.dev` — validates ASPD keys

---

## Git Conventions

- **Commit style**: conventional commits enforced — `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`
- **Branch**: work directly on `main` (or feature branches for non-trivial changes)
- **Dependabot**: enabled for GitHub Actions
- **No secrets**: gitleaks runs in CI; verify `.venv/` and `~/.ai-spend/` never staged
- **Release flow**: bump `version` in pyproject → tag `v{version}` → CI publishes via OIDC trusted publisher

---

## Domain Context

### What ai-spend Is
A single CLI that answers "how much am I spending on AI this month, across all providers, without opening N dashboards?" Free tier covers up to 3 providers and core aggregation. Pro unlocks unlimited providers, exports, and advanced reporting.

### What It's NOT
- Not a usage-capping tool (does not block API calls — reporting only)
- Not a real-time cost tracker (pull-based; syncs when you run `ai-spend sync`)
- Not a dashboard web app (terminal-only by design; Rich tables + JSON/CSV export)
- Not provider-specific — pluggable via `BaseProvider` ABC

### Monetization
- **Free**: 3 providers, summary / daily / budget / manual / sync
- **Pro**: unlimited providers, `export`, advanced stats (`@require_pro` gated)
- **License key format**: `ASPD-XXXX-XXXX-XXXX`
- **Validation**: local checksum first, optional server call (5s timeout), 24h cache, fail-open to local-only
- **Store**: SHA-256 hash only — plaintext keys never persisted

### Pricing
- Do NOT modify Stripe products or pricing tiers from code — pricing lives in Stripe dashboard
- Bundle pricing (with other tools): $29/mo or $199/yr — see README for current links

---

## Security

- `~/.ai-spend/config.yaml` created with mode `0o600` — verify on startup
- API keys load from config, never env vars (avoid shell history leaks)
- License server validation has 5s timeout and 24h cache — fail-open to offline mode
- Telemetry is local-only (`telemetry.db`) and opt-in via `AI_SPEND_TELEMETRY=1` — nothing ever transmitted
- Pre-commit: gitleaks scans for `sk-ant-*`, `sk-*`, `ASPD-*` patterns
