#!/usr/bin/env python3
"""session-guard-analyze.py — Analysis engine for session-guard v3.

Implements the 6 novel differentiators:
1. Hybrid cloud + local unified view
2. Daily digest output
3. Context limit forecasting
4. Electricity cost estimation for local inference
5. Session-to-session cost comparison
6. Model mix shift detection

Usage:
    python3 session-guard-analyze.py [OPTIONS]
    Prints JSON to stdout.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

# --- Configuration ---
TRANSCRIPT_BASE = Path.home() / ".claude" / "projects"
MARKER_DIR = Path.home() / ".local" / "share" / "ai-spend" / "marathons"
STATE_DIR = Path.home() / ".local" / "share" / "ai-spend" / "session-guard"

def _load_pricing() -> dict[str, tuple[Decimal, Decimal]]:
    """Load model pricing from external JSON config.
    Falls back to built-in defaults if file missing or invalid.
    """
    pricing_path = Path.home() / ".config" / "session-guard" / "pricing.json"
    defaults: dict[str, tuple[Decimal, Decimal]] = {
        "claude-opus-4": (Decimal("0.000015"), Decimal("0.000075")),
        "claude-opus-4-20250514": (Decimal("0.000015"), Decimal("0.000075")),
        "claude-sonnet-4": (Decimal("0.000003"), Decimal("0.000015")),
        "claude-sonnet-4-20250514": (Decimal("0.000003"), Decimal("0.000015")),
        "claude-haiku-4": (Decimal("0.0000008"), Decimal("0.000004")),
        "gpt-4o": (Decimal("0.000005"), Decimal("0.000015")),
        "gpt-4o-mini": (Decimal("0.00000015"), Decimal("0.0000006")),
        "kimi-k2.6": (Decimal("0.000002"), Decimal("0.000008")),
        "kimi-k2.6:cloud": (Decimal("0.000002"), Decimal("0.000008")),
        "synthetic": (Decimal("0"), Decimal("0")),
    }
    if not pricing_path.exists():
        return defaults
    try:
        raw = json.loads(pricing_path.read_text(encoding="utf-8"))
        result: dict[str, tuple[Decimal, Decimal]] = {}
        for model, rates in raw.items():
            result[model] = (
                Decimal(str(rates.get("input", 0))),
                Decimal(str(rates.get("output", 0))),
            )
        return result if result else defaults
    except (json.JSONDecodeError, KeyError, TypeError):
        return defaults

# GPU TDP table (Watts) — used for electricity estimation
GPU_TDP = {
    "rx 7900 xtx": 355,
    "rx 7900 xt": 300,
    "rx 7800 xt": 263,
    "rtx 4090": 450,
    "rtx 4080": 320,
    "rtx 3090": 350,
    "rtx 3080": 320,
}

# kWh rate (USD) — rough US average
KWH_RATE = Decimal("0.14")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Session Guard Analysis Engine")
    parser.add_argument(
        "--plan-type",
        type=str,
        default="metered",
        choices=["metered", "flat"],
        help="Pricing model: metered (per-token) or flat (subscription)",
    )
    parser.add_argument(
        "--monthly-token-limit",
        type=int,
        default=1_000_000_000,
        help="Monthly token cap for flat plans (default 1B)",
    )
    parser.add_argument("--max-cost", type=float, default=50)
    parser.add_argument("--max-turns", type=int, default=500)
    parser.add_argument("--max-context-limits", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="Print JSON without writing markers")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Cloud (Claude Code transcript) analysis
# ---------------------------------------------------------------------------

def _detect_dominant_model(lines: list[str]) -> str:
    models = []
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("type") == "assistant":
                model = entry.get("message", {}).get("model", "")
                if model and model != "synthetic":
                    models.append(model)
        except json.JSONDecodeError:
            pass
    if not models:
        return "unknown"
    return Counter(models).most_common(1)[0][0]


def _get_pricing(model: str) -> tuple[Decimal, Decimal]:
    pricing = _load_pricing()
    for prefix, rates in pricing.items():
        if model.startswith(prefix) or model == prefix:
            return rates
    return Decimal("0.000003"), Decimal("0.000015")  # default to Sonnet-like


def _parse_transcript(file_path: Path) -> dict[str, Any]:
    raw_content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = raw_content.splitlines()
    model = _detect_dominant_model(lines)
    input_rate, output_rate = _get_pricing(model)

    input_tokens = 0
    output_tokens = 0
    turn_count = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    context_limits = raw_content.count("session is being continued")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts_str = entry.get("timestamp", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            except ValueError:
                pass

        if entry.get("type") == "assistant":
            turn_count += 1
            usage = entry.get("message", {}).get("usage", {})
            input_tokens += usage.get("input_tokens", 0)
            output_tokens += usage.get("output_tokens", 0)

    cost = Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate

    return {
        "session_id": file_path.stem,
        "model": model,
        "cost": cost,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "turns": turn_count,
        "context_limits": context_limits,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "lines": len(lines),
    }


def _scan_cloud_sessions(verbose: bool) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    if not TRANSCRIPT_BASE.exists():
        return sessions

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    for jsonl_path in TRANSCRIPT_BASE.rglob("*.jsonl"):
        if "subagents" in jsonl_path.parts:
            continue
        mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            continue
        sess = _parse_transcript(jsonl_path)
        sess["mtime"] = mtime
        sessions.append(sess)

    if verbose:
        for s in sessions:
            print(
                f"CLOUD: {s['session_id']} | {s['model']} | cost={s['cost']:.2f} | "
                f"turns={s['turns']} | input={s['input_tokens']} | output={s['output_tokens']}",
                file=sys.stderr,
            )
    return sessions


# ---------------------------------------------------------------------------
# Ollama local analysis
# ---------------------------------------------------------------------------

def _poll_ollama() -> dict[str, Any]:
    """Poll Ollama /api/ps and /api/tags."""
    result = {"models": [], "error": None}
    try:
        import urllib.request
        with urllib.request.urlopen(
            "http://localhost:11434/api/ps", timeout=5
        ) as resp:
            data = json.loads(resp.read())
            result["models"] = [
                {
                    "name": m.get("name", "?"),
                    "size_vram": m.get("size_vram", 0),
                }
                for m in data.get("models", [])
            ]
    except Exception as e:
        result["error"] = str(e)
    return result


def _count_ollama_requests(hours: int = 24) -> tuple[int, dict[str, int]]:
    """Count Ollama POST requests via journalctl.
    Returns (total_requests, {model_name: count}) using loaded-model heuristic.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        proc = subprocess.run(
            ["journalctl", "-u", "ollama", "--since", since, "--no-pager"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            # journalctl failed (e.g., service not found, log rotated)
            return 0, {}
        lines = proc.stdout.splitlines()
        if not lines:
            return 0, {}
        # Validate format: expect at least some GIN-style log lines
        gin_lines = [l for l in lines if "GIN" in l and "POST" in l]
        total = len(gin_lines)
    except Exception:
        return 0, {}

    # Heuristic: if exactly one model is loaded, attribute all requests to it
    ps = _poll_ollama()
    loaded = ps.get("models", [])
    if len(loaded) == 1:
        return total, {loaded[0]["name"]: total}
    if not loaded:
        return total, {}

    # Use 1-hour distribution as proxy for 24-hour if available
    # (avoids naive even-split when models have asymmetric usage)
    if hours > 1:
        _, by_model_1h = _count_ollama_requests(1)
    else:
        by_model_1h = {}
    if by_model_1h and len(loaded) > 1:
        # Scale 1h ratios to 24h total
        total_1h = sum(by_model_1h.values())
        if total_1h > 0:
            result: dict[str, int] = {}
            allocated = 0
            for i, m in enumerate(loaded):
                name = m["name"]
                ratio = by_model_1h.get(name, 0) / total_1h
                count = int(total * ratio)
                result[name] = count
                allocated += count
            # Distribute remainder by 1h ratio priority
            remainder = total - allocated
            if remainder > 0:
                sorted_models = sorted(
                    loaded,
                    key=lambda m: by_model_1h.get(m["name"], 0),
                    reverse=True,
                )
                for i in range(remainder):
                    result[sorted_models[i % len(sorted_models)]["name"]] += 1
            return total, result

    # Fallback: distribute evenly
    n = len(loaded)
    base = total // n
    remainder = total % n
    result: dict[str, int] = {}
    for i, m in enumerate(loaded):
        result[m["name"]] = base + (1 if i < remainder else 0)
    return total, result


def _detect_gpu() -> tuple[str, int]:
    """Detect GPU name and TDP. Returns (name_lower, tdp_w)."""
    # Try nvidia-smi
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            name = proc.stdout.strip().split("\n")[0].lower()
            for key, tdp in GPU_TDP.items():
                if key in name:
                    return name, tdp
            return name, 300  # default TDP
    except FileNotFoundError:
        pass

    # Try rocm-smi
    try:
        proc = subprocess.run(
            ["rocm-smi", "--showproductname"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            name = proc.stdout.strip().split("\n")[0].lower()
            for key, tdp in GPU_TDP.items():
                if key in name:
                    return name, tdp
            return name, 250
    except FileNotFoundError:
        pass

    # Check /proc for AMD GPU
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if "model name" in line.lower() and "amd" in line.lower():
                # Check PCI for GPU
                pci = subprocess.run(
                    ["lspci"], capture_output=True, text=True, timeout=5
                )
                if "amd" in pci.stdout.lower() and "vga" in pci.stdout.lower():
                    return "amd gpu", 250
    except Exception:
        pass

    return "unknown", 200


def _estimate_ollama_electricity(models: list[dict[str, Any]], reqs_24h: int) -> Decimal:
    """Estimate electricity cost for Ollama usage."""
    if not models:
        return Decimal("0")

    _, gpu_tdp = _detect_gpu()

    # Heuristic: model size in GB affects power draw
    # Rough: each loaded model draws proportional to its VRAM footprint
    total_vram = sum(m.get("size_vram", 0) for m in models)
    if total_vram == 0:
        return Decimal("0")

    # Assume model stays loaded for ~avg session time.
    # Simpler: estimate per-request energy.
    # Average request takes ~3s (from logs), GPU at ~60% load during inference.
    avg_request_seconds = 3.0
    load_fraction = 0.6
    hours_active = (reqs_24h * avg_request_seconds) / 3600

    # Idle power: ~10% TDP when loaded but not processing
    idle_fraction = 0.1
    hours_idle = 24 - hours_active
    if hours_idle < 0:
        hours_idle = 0

    energy_kwh = (
        (hours_active * gpu_tdp * load_fraction)
        + (hours_idle * gpu_tdp * idle_fraction)
    ) / 1000

    cost = Decimal(str(energy_kwh)) * KWH_RATE
    return cost.quantize(Decimal("0.01"))


def _fmt_num(n: int | float) -> str:
    """Human-readable large number: 10B, 436M, 1.2K."""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


# ---------------------------------------------------------------------------
# Feature 3: Context limit forecasting
# ---------------------------------------------------------------------------

def _forecast_context_limit(session: dict[str, Any]) -> str | None:
    """Predict when next context limit continuation will occur."""
    limits = session.get("context_limits", 0)
    first_ts = session.get("first_ts")
    last_ts = session.get("last_ts")
    if limits <= 0 or not first_ts or not last_ts:
        return None

    duration_hours = (last_ts - first_ts).total_seconds() / 3600
    if duration_hours < 0.1:
        return None

    rate = limits / duration_hours  # continuations per hour
    if rate < 0.01:
        return None

    # Suppress forecast for very high rates (>10/hour = marathon mode, no useful prediction)
    if rate > 10:
        return None

    minutes_to_next = 60 / rate
    if minutes_to_next < 10:
        return f"⚠️ {session['session_id'][:8]}: next context limit in ~{minutes_to_next:.0f} min ({limits} in {duration_hours:.1f}h)"
    elif minutes_to_next < 30:
        return f"{session['session_id'][:8]}: next context limit in ~{minutes_to_next:.0f} min"
    return None


# ---------------------------------------------------------------------------
# Feature 5: Session-to-session cost comparison
# ---------------------------------------------------------------------------

def _load_historical_markers(days: int = 7) -> list[dict[str, Any]]:
    """Load past marker files for comparison."""
    markers: list[dict[str, Any]] = []
    if not MARKER_DIR.exists():
        return markers

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for mf in MARKER_DIR.glob("*.json"):
        try:
            data = json.loads(mf.read_text())
            detected_at = data.get("detected_at", "")
            if detected_at:
                ts = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    data["_detected_ts"] = ts
                    markers.append(data)
        except (json.JSONDecodeError, ValueError):
            pass
    return markers


def _compare_sessions(current: list[dict[str, Any]], historical: list[dict[str, Any]]) -> str | None:
    """Compare today's sessions to historical average."""
    if not current or not historical:
        return None

    # Group historical by model, compute average cost
    by_model: dict[str, list[Decimal]] = defaultdict(list)
    for h in historical:
        model = h.get("model", "unknown")
        cost = Decimal(str(h.get("cost_usd", "0")))
        by_model[model].append(cost)

    messages = []
    for sess in current:
        model = sess.get("model", "unknown")
        if model not in by_model or len(by_model[model]) < 1:
            continue
        avg_cost = sum(by_model[model]) / len(by_model[model])
        current_cost = sess.get("cost", Decimal("0"))
        if avg_cost == 0:
            continue

        delta = current_cost - avg_cost
        pct = float(delta / avg_cost * 100) if avg_cost else 0

        if abs(pct) > 30:  # Report meaningful deltas (lowered from 50% to catch portfolio-scale drift)
            direction = "↑" if pct > 0 else "↓"
            messages.append(
                f"{sess['session_id'][:8]}: {direction} {abs(pct):.0f}% vs avg ({current_cost:.2f} vs {avg_cost:.2f})"
            )

    if messages:
        return "Session deltas vs 7-day avg:\n" + "\n".join(messages[:3])
    return None


# ---------------------------------------------------------------------------
# Feature 6: Model mix shift detection
# ---------------------------------------------------------------------------

def _detect_model_mix_shift(current: list[dict[str, Any]], historical: list[dict[str, Any]]) -> str | None:
    """Detect if model usage has shifted compared to last 7 days."""
    if not historical:
        return None

    # Count tokens by model for historical period
    hist_tokens: Counter[str] = Counter()
    hist_costs: Counter[str] = Counter()
    for h in historical:
        model = h.get("model", "unknown")
        # We don't have token counts in markers, use cost as proxy
        cost = float(h.get("cost_usd", 0))
        hist_costs[model] += cost

    # Current period
    curr_costs: Counter[str] = Counter()
    for sess in current:
        model = sess.get("model", "unknown")
        curr_costs[model] += float(sess.get("cost", 0))

    if not curr_costs or not hist_costs:
        return None

    total_hist = sum(hist_costs.values())
    total_curr = sum(curr_costs.values())
    if total_hist == 0 or total_curr == 0:
        return None

    shifts = []
    for model in set(list(hist_costs.keys()) + list(curr_costs.keys())):
        hist_pct = hist_costs[model] / total_hist * 100
        curr_pct = curr_costs[model] / total_curr * 100
        delta = curr_pct - hist_pct
        if abs(delta) > 15:  # 15% shift threshold
            direction = "↑" if delta > 0 else "↓"
            shifts.append(f"{model}: {direction} {abs(delta):.0f}% ({hist_pct:.0f}% → {curr_pct:.0f}%)")

    if shifts:
        return "Model mix shift:\n" + "\n".join(shifts[:3])
    return None


def _forecast_monthly_limit(
    total_tokens: int, monthly_limit: int, first_ts: datetime | None
) -> str | None:
    """Estimate days remaining until monthly token limit."""
    if monthly_limit <= 0 or total_tokens <= 0:
        return None
    if first_ts is None:
        return None

    elapsed = (datetime.now(timezone.utc) - first_ts).total_seconds()
    if elapsed < 3600:  # Need at least 1h of data
        return None

    rate_per_day = total_tokens / elapsed * 86400
    if rate_per_day <= 0:
        return None

    remaining = monthly_limit - total_tokens
    days_left = remaining / rate_per_day

    if days_left < 1:
        return f"⚠️ Monthly limit exhausted in <1 day ({_fmt_num(total_tokens)} / {_fmt_num(monthly_limit)})"
    if days_left < 7:
        return f"Monthly limit in ~{days_left:.0f} days ({_fmt_num(total_tokens)} / {_fmt_num(monthly_limit)})"
    return f"Monthly limit: ~{days_left:.0f} days remaining"


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    # ---- Cloud analysis ----
    cloud_sessions = _scan_cloud_sessions(args.verbose)
    total_cloud_cost = sum(s.get("cost", Decimal("0")) for s in cloud_sessions)
    total_cloud_turns = sum(s.get("turns", 0) for s in cloud_sessions)
    total_cloud_tokens = sum(s.get("input_tokens", 0) + s.get("output_tokens", 0) for s in cloud_sessions)

    # ---- Ollama analysis ----
    ollama_state = _poll_ollama()
    ollama_reqs_24h, ollama_by_model_24h = _count_ollama_requests(24)
    ollama_reqs_1h, ollama_by_model_1h = _count_ollama_requests(1)
    ollama_electricity = _estimate_ollama_electricity(
        ollama_state.get("models", []), ollama_reqs_24h
    )

    # ---- Feature 3: Forecasting ----
    forecasts = []
    for sess in cloud_sessions:
        f = _forecast_context_limit(sess)
        if f:
            forecasts.append(f)
    forecast_message = "\n".join(forecasts[:3]) if forecasts else ""

    # ---- Monthly token limit forecast ----
    first_ts = min(
        (s.get("first_ts") for s in cloud_sessions if s.get("first_ts")),
        default=None,
    )
    monthly_forecast = _forecast_monthly_limit(
        total_cloud_tokens, args.monthly_token_limit, first_ts
    )

    # ---- Feature 5 & 6: Historical comparison ----
    historical = _load_historical_markers(days=7)
    comparison_message = _compare_sessions(cloud_sessions, historical)
    model_mix_shift = _detect_model_mix_shift(cloud_sessions, historical)

    # ---- Plan type handling (metered vs flat) ----
    is_flat = args.plan_type == "flat"
    usage_pct = float(
        Decimal(str(total_cloud_tokens)) / Decimal(str(args.monthly_token_limit)) * 100
    ) if args.monthly_token_limit else 0.0
    if is_flat:
        for sess in cloud_sessions:
            sess["cost"] = Decimal("0")
        total_cloud_cost = Decimal("0")

    # ---- Breach detection + marker writing ----
    breach = False
    alerts: list[str] = []
    for sess in cloud_sessions:
        s_cost = float(sess.get("cost", 0))
        s_turns = sess.get("turns", 0)
        s_limits = sess.get("context_limits", 0)
        if not is_flat and s_cost > args.max_cost:
            breach = True
            alerts.append(f"cost>{args.max_cost}({s_cost:.2f})")
        if s_turns > args.max_turns:
            breach = True
            alerts.append(f"turns>{args.max_turns}({s_turns})")
        if s_limits > args.max_context_limits:
            breach = True
            alerts.append(f"context_limits>{args.max_context_limits}({s_limits})")

        # Write marker for every session scanned (skipped in dry-run)
        if not args.dry_run:
            _write_marker(sess, args, alerts)
        alerts = []  # reset per-session

    # ---- Ollama breach detection + marker ----
    ollama_alerts: list[str] = []
    if ollama_reqs_24h > 2000:
        breach = True
        ollama_alerts.append(f"ollama_reqs>2000({ollama_reqs_24h})")
    if not args.dry_run:
        _write_ollama_marker(
            args, ollama_reqs_24h, ollama_by_model_24h,
            ollama_reqs_1h, ollama_by_model_1h,
            ollama_state, ollama_electricity, ollama_alerts,
        )

    # ---- Output JSON ----
    result = {
        "plan_type": args.plan_type,
        "monthly_token_limit": args.monthly_token_limit,
        "usage_pct": round(usage_pct, 1),
        "total_cloud_cost": float(total_cloud_cost.quantize(Decimal("0.01"))),
        "total_cloud_turns": total_cloud_turns,
        "total_cloud_tokens": total_cloud_tokens,
        "cloud_sessions": len(cloud_sessions),
        "ollama_requests_24h": ollama_reqs_24h,
        "ollama_by_model_24h": ollama_by_model_24h,
        "ollama_requests_1h": ollama_reqs_1h,
        "ollama_by_model_1h": ollama_by_model_1h,
        "ollama_models_loaded": len(ollama_state.get("models", [])),
        "ollama_electricity_cost": float(ollama_electricity),
        "forecast_message": forecast_message,
        "monthly_forecast": monthly_forecast or "",
        "comparison_message": comparison_message or "",
        "model_mix_shift": model_mix_shift or "",
        "breach": breach,
    }

    print(json.dumps(result, indent=2))


def _write_ollama_marker(
    args: argparse.Namespace,
    reqs_24h: int,
    by_model_24h: dict[str, int],
    reqs_1h: int,
    by_model_1h: dict[str, int],
    state: dict[str, Any],
    electricity: Decimal,
    alerts: list[str],
) -> None:
    """Write an Ollama-specific marker for local inference tracking."""
    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Use a fixed session ID so today's Ollama marker is overwritten each run
    marker_path = MARKER_DIR / f"{date_str}_ollama.json"

    marker = {
        "session_id": "ollama",
        "date": date_str,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "model": "ollama-aggregate",
        "plan_type": args.plan_type,
        "monthly_token_limit": args.monthly_token_limit,
        "cost_usd": 0.0,  # flat plan assumption
        "turns": reqs_24h,
        "input_tokens": reqs_24h,   # Store requests as tokens for queryability in SpendStore
        "output_tokens": 0,
        "context_limits": 0,
        "alerts": alerts,
        "thresholds": {
            "max_cost_usd": args.max_cost,
            "max_turns": args.max_turns,
            "max_context_limits": args.max_context_limits,
        },
        "ollama": {
            "requests_24h": reqs_24h,
            "by_model_24h": by_model_24h,
            "requests_1h": reqs_1h,
            "by_model_1h": by_model_1h,
            "models_loaded": [m["name"] for m in state.get("models", [])],
            "electricity_cost_usd": float(electricity),
        },
    }

    # Overwrite each run (no idempotent skip for Ollama — counters change)
    marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")


def _write_marker(sess: dict[str, Any], args: argparse.Namespace, alerts: list[str]) -> None:
    """Write a session marker JSON for ai-spend ingestion."""
    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    session_id = sess.get("session_id", "unknown")
    date_str = sess.get("first_ts")
    if date_str:
        date_str = date_str.strftime("%Y-%m-%d")
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")

    marker_path = MARKER_DIR / f"{date_str}_{session_id}.json"

    marker = {
        "session_id": session_id,
        "date": date_str,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "model": sess.get("model", "unknown"),
        "plan_type": args.plan_type,
        "monthly_token_limit": args.monthly_token_limit,
        "cost_usd": float(sess.get("cost", Decimal("0")).quantize(Decimal("0.01"))),
        "turns": sess.get("turns", 0),
        "input_tokens": sess.get("input_tokens", 0),
        "output_tokens": sess.get("output_tokens", 0),
        "context_limits": sess.get("context_limits", 0),
        "alerts": alerts,
        "thresholds": {
            "max_cost_usd": args.max_cost,
            "max_turns": args.max_turns,
            "max_context_limits": args.max_context_limits,
        },
    }

    # Skip write if content hasn't changed (excluding detected_at timestamp)
    if marker_path.exists():
        try:
            old = json.loads(marker_path.read_text(encoding="utf-8"))
            # Compare everything except detected_at
            old_copy = {k: v for k, v in old.items() if k != "detected_at"}
            new_copy = {k: v for k, v in marker.items() if k != "detected_at"}
            if old_copy == new_copy:
                return
        except (json.JSONDecodeError, OSError):
            pass

    marker_path.write_text(json.dumps(marker, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
