# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ai-spend sync --since YYYY-MM-DD` / `-s`: custom start date for sync window.
- SQLite backup before migrations: `spend.db` copied to timestamped backup before any schema migration runs.

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
