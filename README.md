# ai-spend

[![CI](https://github.com/AreteDriver/ai-spend/actions/workflows/ci.yml/badge.svg)](https://github.com/AreteDriver/ai-spend/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AreteDriver/ai-spend/actions/workflows/codeql.yml/badge.svg)](https://github.com/AreteDriver/ai-spend/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**Your AI bills, in your terminal. No proxies. No dashboards. No SDK changes.**

`ai-spend` pulls usage data directly from Anthropic and OpenAI's official billing APIs and displays it in your terminal. Your API keys stay on your machine. Your prompts are never seen.

```
$ ai-spend summary

  Provider       This Month    vs Last Month
  ─────────────────────────────────────────
  Anthropic        $47.23       +12%
  OpenAI           $31.88        -4%
  ─────────────────────────────────────────
  Total            $79.11

  Top models:
  claude-opus-4-6       $31.44   (67% of Anthropic)
  gpt-4.1               $18.22   (57% of OpenAI)

$ ai-spend daily --last 7

  Date         Anthropic    OpenAI    Total
  ──────────────────────────────────────────
  2026-02-28     $8.12      $4.33    $12.45
  2026-02-27     $6.88      $5.11    $11.99
  ...
```

## How It's Different

Unlike gateway-based trackers, `ai-spend` never sees your prompts. It reads token counts and costs from your provider's billing API — the same data that appears on your invoice. Nothing more.

| | Reads billing API directly | No proxy/SDK | Prompts stay local | CLI-native |
|---|:---:|:---:|:---:|:---:|
| **ai-spend** | Yes | Yes | Yes | Yes |
| Langfuse | No (intercepts calls) | No | No | No |
| Helicone | No (proxy) | No | No | No |
| OpenAI dashboard | Yes | Yes | Yes | No (web only) |

## Install

```bash
pip install ai-spend
```

## Quick Start

```bash
# Add your providers (keys stored locally with 0600 perms)
ai-spend config add anthropic
ai-spend config add openai

# Pull latest usage data
ai-spend sync

# See your spend
ai-spend summary
ai-spend daily --last 30
```

## Usage

```bash
# Provider management
ai-spend config add <provider>     # Add a provider (anthropic, openai)
ai-spend config remove <provider>  # Remove a provider
ai-spend config list               # List configured providers

# Sync usage data from provider APIs
ai-spend sync

# View spend
ai-spend summary                   # Aggregated totals
ai-spend summary --json            # JSON output
ai-spend daily                     # Daily breakdown
ai-spend daily --last 7            # Last 7 days

# Budgets
ai-spend budget set 100            # Set monthly budget ($100)
ai-spend budget check              # Check against budget

# Manual entries (for providers without billing APIs)
ai-spend manual add 12.50 --provider ollama --note "local GPU costs"

# Export (Pro)
ai-spend export --format csv
ai-spend export --format json

# Status
ai-spend status                    # License tier + system info
```

## How It Works

```
Provider APIs ──→ ai-spend sync ──→ Local SQLite
(Anthropic)                         (~/.ai-spend/spend.db)
(OpenAI)                                  │
                                          ▼
                              ai-spend summary/daily/budget
```

1. **Configure** — Add provider API keys (stored locally in `~/.ai-spend/config.yaml` with `0600` permissions)
2. **Sync** — Pulls usage records from official billing APIs into a local SQLite database
3. **Query** — All read commands (`summary`, `daily`, `budget`, `export`) hit the local database only

No background processes. No network calls except during `sync`. Run it in a cron job, pipe it into monitoring, or check it before standups.

## Free vs Pro

| Feature | Free | Pro |
|---------|:---:|:---:|
| Sync + summary + daily | Yes | Yes |
| Budget tracking | Yes | Yes |
| Manual entries | Yes | Yes |
| JSON output | Yes | Yes |
| CSV/JSON export | -- | Yes |

## License

MIT
