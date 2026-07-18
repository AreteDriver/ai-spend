# ai-spend

[![CI](https://github.com/AreteDriver/ai-spend/actions/workflows/ci.yml/badge.svg)](https://github.com/AreteDriver/ai-spend/actions/workflows/ci.yml)
[![CodeQL](https://github.com/AreteDriver/ai-spend/actions/workflows/codeql.yml/badge.svg)](https://github.com/AreteDriver/ai-spend/actions/workflows/codeql.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

**`htop` for AI spend.** Local-first, cross-provider, terminal-native. No proxies. No dashboards. No SDK changes.

`ai-spend` aggregates usage data from **Anthropic and OpenAI** (with OpenRouter coming soon) directly into your terminal. Your API keys stay local. Your prompts are never seen. Your data never leaves your machine.

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
# Add your providers (keys stored locally with 0600 perms)
ai-spend config add anthropic
ai-spend config add openai
# ai-spend config add openrouter  # Coming soon

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

| Feature | Free | Pro ($8/mo) |
|---------|:---:|:---:|
| Sync + summary + daily | Yes | Yes |
| Budget tracking | Yes | Yes |
| Manual entries | Yes | Yes |
| JSON output | Yes | Yes |
| Unlimited providers | 3 max | Yes |
| CSV/JSON export | -- | Yes |

**Get Pro:** [Monthly ($8/mo)](https://buy.stripe.com/28E4gzbphbp9cJC4g7grS04) | [Yearly ($69/yr)](https://buy.stripe.com/7sYcN564Xctd10U5kbgrS05)

**All 5 Tools Bundle:** [Monthly ($29/mo)](https://buy.stripe.com/7sY9AT9h90Kv5ha27ZgrS0a) | [Yearly ($199/yr)](https://buy.stripe.com/9B6fZh9h98cX24YfYPgrS0b) — includes claudemd-forge, agent-lint, ai-spend, promptctl, context-hygiene

**Activate:**
```bash
export AI_SPEND_LICENSE=ASPD-XXXX-XXXX-XXXX
```

## Community

[Discord](https://discord.gg/fdzQkrt8) — Join the community

## License

MIT
