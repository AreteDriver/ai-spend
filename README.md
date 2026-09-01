# ai-spend

[![CI](https://github.com/AreteDriver/ai-spend/actions/workflows/ci.yml/badge.svg)](https://github.com/AreteDriver/ai-spend/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AreteDriver/ai-spend/actions/workflows/codeql.yml/badge.svg)](https://github.com/AreteDriver/ai-spend/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/ai-spend.svg)](https://pypi.org/project/ai-spend/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](https://mariadb.com/bsl11/)

**`htop` for AI spend.** Local-first, cross-provider, terminal-native. No proxies. No dashboards. No SDK changes.

`ai-spend` aggregates usage data from **Anthropic, OpenAI, and OpenRouter** directly into your terminal. Your API keys stay local. Your prompts are never seen. Your data never leaves your machine.

![ai-spend summary demo](docs/assets/ai-spend-demo.gif)

```
$ ai-spend summary

  Provider       This Month    vs Last Month
  ─────────────────────────────────────────
  Anthropic        $47.23       +12%
  OpenAI           $31.88        -4%
  OpenRouter        $5.12       +22%
  ─────────────────────────────────────────
  Total            $84.23

  Top models:
  claude-opus-4-6       $31.44   (67% of Anthropic)
  gpt-4.1               $18.22   (57% of OpenAI)
```

## What this demonstrates

- Turning provider billing APIs into a practical operational workflow.
- Adapter design, local data handling, budget visibility, credential-aware configuration, and terminal UX.
- Documentation and controls intended to help users understand spend without proxying their AI traffic.

## Current status and limitations

This is an active independent tool, not an enterprise billing system. Provider coverage and reported fields depend on the APIs each provider exposes; users should verify figures against provider invoices. Data remains local by default. See [Security](SECURITY.md) and [Changelog](CHANGELOG.md).

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## Why ai-spend?

If you use **multiple AI providers** — Anthropic for coding, OpenAI for embeddings, maybe OpenRouter for routing or a local Ollama instance for cheap tasks — each has its own billing dashboard. None of them show the others.

`ai-spend` is the **unified view** — one terminal command to see everything you've spent, everywhere, without routing your traffic through a third-party proxy or changing your code.

## How It's Different

| | Cross-provider | Reads billing API directly | No proxy/SDK | Prompts stay local | CLI-native |
|---|:---:|:---:|:---:|:---:|:---:|
| **ai-spend** | Yes | Yes | Yes | Yes | Yes |
| LangSmith | Yes | No (intercepts calls) | No | No | No |
| OpenLLMetry | Yes | No (proxy) | No | No | No |
| Helicone | Yes | No (proxy) | No | No | No |
| OpenAI dashboard | No | Yes | Yes | Yes | No (web only) |

## Install

```bash
pip install ai-spend
```

## Quick Start

```bash
# Add your providers (keys stored locally with 0700 perms)
ai-spend config add anthropic
ai-spend config add openai
ai-spend config add openrouter

# Validate credentials before syncing
ai-spend config validate

# Pull latest usage data
ai-spend sync

# Preview what would be synced (dry run)
ai-spend sync --dry-run

# Sync only one provider
ai-spend sync --provider openai

# See your spend
ai-spend summary
ai-spend daily --last 30

# Shell completion (zsh/bash/fish)
ai-spend --install-completion
```

## Usage

```bash
# Provider management
ai-spend config add <provider>       # Add a provider (anthropic, openai, openrouter, manual)
ai-spend config remove <provider>  # Remove a provider
ai-spend config list               # List configured providers
ai-spend config edit <name> --key <new-key>    # Rotate API key
ai-spend config edit <name> --type <new-type>  # Change provider type
ai-spend config validate           # Check API keys without syncing
ai-spend config encrypt            # Encrypt all API keys at rest

# Sync usage data from provider APIs
ai-spend sync
ai-spend sync --dry-run            # Preview only
ai-spend sync --provider <name>    # Sync a single provider
ai-spend sync --since 2026-01-01   # Custom start date (default: 30 days)

# View spend
ai-spend summary                   # Aggregated totals
ai-spend summary --json            # JSON output
ai-spend summary --provider <name> # Filter by provider
ai-spend daily                     # Daily breakdown
ai-spend daily --last 7            # Last 7 days
ai-spend daily --provider <name>   # Filter by provider

# Budgets
ai-spend budget set 100            # Set monthly budget ($100)
ai-spend budget check              # Check against budget

# Manual entries (for providers without billing APIs)
ai-spend manual add 12.50 --provider ollama --note "local GPU costs"

# Export
ai-spend export --format csv
ai-spend export --format json

# Import (round-trip your data)
ai-spend import records.json --format json
ai-spend import records.csv --format csv

# Data maintenance
ai-spend prune --older-than 90     # Delete records older than 90 days
ai-spend prune --older-than 90 --dry-run  # Preview deletion

# Status
ai-spend status                    # System info and config health
ai-spend stats                     # Telemetry (set AI_SPEND_TELEMETRY=1)
ai-spend stats --json              # Structured JSON telemetry
```

## How It Works

```
Provider APIs ──→ ai-spend sync ──→ Local SQLite
(Anthropic)                         (~/.ai-spend/spend.db)
(OpenAI)                                  │
(OpenRouter)                              ▼
                              ai-spend summary/daily/budget
```

1. **Configure** — Add provider API keys (stored locally in `~/.ai-spend/config.yaml` with `0700` permissions, optionally encrypted at rest via `ai-spend config encrypt`)
2. **Sync** — Pulls usage records from official billing APIs into a local SQLite database (WAL mode, schema migrations)
3. **Query** — All read commands (`summary`, `daily`, `budget`, `export`) hit the local database only

No background processes. No network calls except during `sync`. Run it in a cron job, pipe it into monitoring, or check it before standups.

## Structured Logging

Set `AI_SPEND_VERBOSE=1` or pass `--verbose` to see structured JSON logs for every sync operation:

```bash
ai-spend sync --verbose
# {"ts": "...", "level": "info", "msg": "sync_start", "fields": {"provider": "..."}}
```

## License

Licensed under BUSL-1.1. See [LICENSE](LICENSE).

## Related Projects

- **[mcp-manager](https://github.com/AreteDriver/mcp-manager)** — MCP server lifecycle manager across agentic IDEs (`pip install arete-mcp`)
- **[agent-lint](https://github.com/AreteDriver/agent-lint)** — Catch expensive agent workflows before they ship (`pip install agentlinter`)
- **[animus](https://github.com/AreteDriver/animus)** — The AI operating environment that uses ai-spend for cost observability

## Community

[Discord](https://discord.gg/fdzQkrt8) — Join the community

## License

Licensed under [BUSL-1.1](https://mariadb.com/bsl11/) (Business Source License 1.1).

- **Free for non-production use** — personal projects, research, evaluation
- **Production use requires a license** after the Change Date (4 years from release)
- See [LICENSE](LICENSE) for full terms
