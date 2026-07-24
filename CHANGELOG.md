# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ai-spend health`: operational health checks — DB integrity, WAL mode, config permissions, encryption status, schema version.
- `ai-spend config encrypt`: encrypt all API keys at rest using Fernet (AES-128-CBC + HMAC).
- `ai-spend summary --provider <name>` and `ai-spend daily --provider <name>`: filter by provider.
- `ai-spend prune --older-than N [--dry-run]`: record retention with dry-run preview.
- `ai-spend sync --since YYYY-MM-DD` / `-s`: custom start date for sync window.
- SQLite backup before migrations: `spend.db` copied to timestamped backup before any schema migration runs.
- Config backup before edits: `config.yaml` copied to timestamped backup before `edit_provider` writes.
- Provider name validation: reject empty, whitespace-only, or invalid character names.
- Graceful SIGINT handling during `sync`: close store connection cleanly on interrupt.
- Shell completion support documented (`--install-completion`, `--show-completion`).
- PyPI publish workflow (`.github/workflows/publish.yml`) with OIDC trusted publishing.

### Changed
- README license badge and footer corrected to BSL-1.1.
- Development status bumped from Alpha to Beta in package classifiers.

### Fixed
- **Anthropic adapter schema correction** — aligned with current Anthropic Admin API
  Cost Report endpoint:
  - Date params: `start_date`/`end_date` → `starting_at`/`ending_at` (RFC 3339)
  - Pagination: `cursor`/`next_cursor` → `page`/`next_page` + `has_more`
  - Response array: `models` → `results`
  - Cost field: `cost` → `amount` (cents as decimal string, divided by 100 for USD)
  - Token counts: removed fabricated values; now correctly reported as `0` since
    the Cost Report endpoint does not provide token counts.
- **OpenAI adapter pagination correction** — aligned with current OpenAI Admin API:
  - Pagination query param: `cursor` → `page`
  - Pagination response fields: `next_cursor` → `next_page` + `has_more`
  - Removed dead code branch that tried to read `result.object.id` (the real
    API's `object` field is a string literal, not a dict).
- **OpenRouter adapter complete rewrite** — replaced broken `GET /api/v1/generations`
  (non-existent endpoint with fabricated field names) with the beta Analytics API
  (`POST /api/v1/analytics/query`):
  - Uses daily granularity with `model` dimension
  - Queries `total_usage`, `tokens_prompt`, and `tokens_completion` metrics
  - Defensively parses token counts that may be returned as strings
  - Raises `ProviderError` when `metadata.truncated` is true, advising users to
    narrow their sync date range
  - Requires a **Management API Key** (regular inference keys receive 403)

### Data Integrity Advisory
Anthropic usage data synced **before this release** contains two defects:
1. **Costs are inflated by 100×** — the adapter interpreted cents as dollars
   (e.g. `"1.5"` cents was stored as `$1.50` instead of `$0.015`).
2. **Token counts are fabricated** — the adapter populated `input_tokens` and
   `output_tokens` from non-existent fields, producing random `0` values.

Recommendation: delete Anthropic records from your local database and re-sync:
```bash
ai-spend prune --provider <anthropic-name> --older-than 0 --dry-run
# Verify the preview, then run without --dry-run
ai-spend sync --provider <anthropic-name> --since YYYY-MM-DD
```

## [0.3.0] - 2026-07-19

### Added
- `ai-spend sync --dry-run` / `-n`: preview records without writing to database.
- `ai-spend sync --provider` / `-p <name>`: sync a single provider.
- `ai-spend sync --since YYYY-MM-DD` / `-s`: custom start date for sync window (default 30 days).
- `ai-spend config validate`: test API credentials without syncing data.
- `ai-spend config edit <name> --key <new-key>`: rotate API keys in-place.
- `ai-spend import <file> --format {json,csv}`: round-trip import with atomic transaction.
- `ai-spend stats --json`: structured telemetry output.
- Structured JSON logging via `--verbose` / `-V` and `AI_SPEND_VERBOSE=1`.
- `SpendStore.transaction()` context manager for atomic SQLite operations.
- Schema migration runner with numbered `.sql` files and `schema_version` tracking.
- `mypy` strict mode in CI (new `type-check` job).

### Changed
- **BREAKING**: SQLite schema migration — `cost_usd` and `total_usd` columns changed from `REAL` to `TEXT` for exact `Decimal` arithmetic. Existing databases are auto-migrated on first open.
- Config directory permissions hardened to `0o700` (owner-only).
- AppContext DI refactor: eliminated global mutable singletons (`get_store`, `reset_store`, telemetry singletons). All dependencies injected via `typer.Context.obj`.
- Provider HTTP requests now use exponential backoff retry with 429 `Retry-After` respect, fail-fast on 4xx, and retry on 5xx/connect errors.

### Fixed
- `gates.py` removed stale `track_pro_gate` import that broke export free-tier test.

## [0.2.0] - 2026-02-19

### Added
- Initial release with Anthropic, OpenAI, and OpenRouter provider support.
- Local SQLite WAL storage for usage data.
- Budget tracking with alert thresholds.
- Manual cost entries for providers without billing APIs.
- Pro tier gating via `AI_SPEND_LICENSE` environment variable.
- Telemetry (opt-in via `AI_SPEND_TELEMETRY=1`).

[Unreleased]: https://github.com/AreteDriver/ai-spend/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/AreteDriver/ai-spend/compare/v0.2.0...v0.3.0
