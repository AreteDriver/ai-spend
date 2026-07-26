---
name: Feature Request — `watch` Mode for Live Session Monitoring
title: "feat: Add `ai-spend watch` subcommand for real-time session guard"
labels: ["enhancement", "monitoring", "cli"]
---

## Problem

Claude Code sessions can silently balloon into **marathon runs** — thousands of turns, context-limit continuations, and $50–$650 in unmonitored spend. The `a46f8c87` session on agent-lint (Jul 20–21) hit **3,086 turns**, **3 context-limit hits**, and **$653.80** over 31.8 hours. By the time a human notices, the cost is sunk.

## Proposed Solution

Add a **`watch`** subcommand to `ai-spend` that continuously monitors Claude Code transcript files and alerts when session cost/turn/drift thresholds breach. This extends `ai-spend` from a **post-hoc** spend aggregator to a **real-time** guardrail.

## Design

### CLI Interface

```bash
# Basic: one-shot scan of recent sessions
ai-spend watch --since 30m

# Daemon: continuous monitoring with desktop notifications
ai-spend watch --daemon --interval 300

# With custom thresholds
ai-spend watch --cost-limit 30 --turn-limit 400 --drift-limit 65

# JSON output for automation / CI
ai-spend watch --json
```

### New Models

```python
# src/ai_spend/models.py

class WatchConfig(BaseModel):
    cost_limit_usd: float = 50.0
    turn_limit: int = 500
    drift_limit_pct: int = 70
    context_limit_threshold: int = 1
    wall_active_ratio_limit: float = 5.0
    interval_seconds: int = 300
    transcript_dir: Path = Path.home() / ".claude" / "projects"

class SessionAlert(BaseModel):
    session_id: str
    cwd: str
    date: str
    cost_usd: float
    turns: int
    drift_pct: int
    context_limits: int
    alerts: list[str]
    detected_at: datetime
```

### New Module: `watch.py`

```
src/ai_spend/
  watch.py          # Watch engine: scan, compute, alert
  cli.py            # Add @app.command("watch")
  reporter.py       # Add format_alert_table()
```

**`watch.py` responsibilities:**
- `scan_transcripts(path, since)` — find `*.jsonl` files modified within window
- `compute_signals(file)` — parse JSONL, return cost/turns/drift/context-limits
- `evaluate_thresholds(signals, config)` — return list of breached thresholds
- `notify(alerts)` — desktop notification via `notify-send`, `osascript`, or stdout fallback
- `write_marker(alert, marker_dir)` — persist alert to `~/.local/share/ai-spend/marathons/`

### Integration Points

| Existing Component | How `watch` Uses It |
|---|---|
| `store.py` (SQLite) | Write alert markers; query for "marathon history" dashboard |
| `reporter.py` (Rich) | `format_alert_table()` for terminal output |
| `cli.py` (Typer) | New `watch` command wired into existing `AppContext` |
| `models.py` (Pydantic) | `WatchConfig`, `SessionAlert` validators |
| `telemetry.py` | Track `command` = `watch.daemon` or `watch.oneshot` |

### Cost Computation

The `a46f8c87` session used **kimi-k2.6** via Claude Code. Since transcripts don't carry provider pricing, `watch` should:
1. Accept a `--model-override` or read from `AI_SPEND_WATCH_MODEL` env var
2. Use hardcoded per-model rate cards (Anthropic, OpenAI, local) as fallback
3. Default to a conservative proxy rate (e.g., $3/M input, $12/M output) if unknown

### Daemon Mode

- Graceful SIGINT handling (reuse `_GracefulShutdown` from `cli.py`)
- Sleep between scans, re-check file mtimes to avoid re-parsing unchanged transcripts
- Optional `--fork` background mode for systemd/user service integration

### Output Formats

| Format | Use Case |
|---|---|
| **Table** (default) | Human-in-the-loop terminal session |
| **JSON** (`--json`) | CI pipeline, Animus daemon ingestion, log shipping |
| **Markdown** (`--md`) | Quick paste into `notes/sessions/` for post-mortem |

## Testing Plan

- Unit tests for `compute_signals()` using synthetic JSONL fixtures
- Threshold boundary tests (cost exactly at limit, limit+ε)
- Notification fallback tests (mock `notify-send` absence)
- Daemon loop tests (SIGINT propagation)
- Integration: run against real `a46f8c87` transcript, assert 4 alerts fire

## Stretch / Future Work

- **Portfolio dashboard**: `ai-spend watch --dashboard` opens a live TUI (Textual?) showing all active sessions with color-coded severity
- **Animus MCP integration**: Push alerts directly to `animus_architect_scan` so the Citizen Council backlog auto-populates
- **Slack/Discord webhook**: `AI_SPEND_WATCH_WEBHOOK_URL` for remote teams
- **Auto-kill**: `--kill-pid` option to send SIGTERM to the Claude Code process if cost exceeds emergency threshold (dangerous, behind flag)

## Acceptance Criteria

- [ ] `ai-spend watch --since 30m` runs against `~/.claude/projects/*/*.jsonl` and returns table output
- [ ] `ai-spend watch --daemon --interval 60` stays resident, alerts on breach
- [ ] Desktop notification fires on Linux (`notify-send`) and macOS (`osascript`)
- [ ] Alert markers write to `~/.local/share/ai-spend/marathons/*.json`
- [ ] `--json` output is valid JSON and round-trippable through `SessionAlert.model_validate_json()`
- [ ] Unit tests ≥ 90% coverage on `watch.py`
- [ ] No new dependencies beyond existing stack (typer, rich, pydantic, stdlib)

## Reference

- Session `a46f8c87` analysis: 51 human prompts → 3,086 turns → $653.80. Efficiency drift 67.7%, 3 context-limit continuations.
- Existing script: `scripts/session-guard.sh` (bash prototype, functional today)
- Related memory: [[local-ai-eval-pause-state]], [[animus-session-controller]]
