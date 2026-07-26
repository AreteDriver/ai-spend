#!/usr/bin/env bash
# session-guard.sh — Unified AI spend + Ollama monitor (v3)
#
# Features:
#   1. Hybrid cloud/local unified view
#   2. Daily digest notifications (not per-session spam)
#   3. Context limit forecasting
#   4. Electricity cost estimation for local inference
#   5. Session-to-session cost comparison
#   6. Model mix shift detection
#
# Architecture: bash wrapper + Python analysis engine

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${HOME}/.config/session-guard"
MARKER_DIR="${HOME}/.local/share/ai-spend/marathons"
STATE_DIR="${HOME}/.local/share/ai-spend/session-guard"
ANALYZER="${SCRIPT_DIR}/session-guard-analyze.py"

# --- Defaults ---
PLAN_TYPE=${PLAN_TYPE:-metered}
MONTHLY_TOKEN_LIMIT=${MONTHLY_TOKEN_LIMIT:-1000000000}
MAX_COST_USD=${MAX_COST_USD:-50}
MAX_TURNS=${MAX_TURNS:-500}
MAX_CONTEXT_LIMITS=${MAX_CONTEXT_LIMITS:-1}
INTERVAL=${INTERVAL:-3600}
TRANSCRIPT_DIR=${TRANSCRIPT_DIR:-"${HOME}/.claude/projects"}
DAEMON=${DAEMON:-false}
VERBOSE=${VERBOSE:-false}
DRY_RUN=${DRY_RUN:-false}
SHOW_STATUS=${SHOW_STATUS:-false}
NOTIFY_COOLDOWN_SECONDS=${NOTIFY_COOLDOWN_SECONDS:-86400}
NOTIFY_STATE_FILE="${STATE_DIR}/notified-sessions"

# --- Load user config if present ---
if [[ -f "${CONFIG_DIR}/config" ]]; then
    # shellcheck source=/dev/null
    source "${CONFIG_DIR}/config"
fi

# --- Validate config ---
if [[ "$PLAN_TYPE" != "metered" && "$PLAN_TYPE" != "flat" ]]; then
    echo "ERROR: Invalid PLAN_TYPE='$PLAN_TYPE'. Must be 'metered' or 'flat'." >&2
    exit 1
fi
if ! [[ "$MAX_COST_USD" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "ERROR: Invalid MAX_COST_USD='$MAX_COST_USD'. Must be a number." >&2
    exit 1
fi
if ! [[ "$MAX_TURNS" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Invalid MAX_TURNS='$MAX_TURNS'. Must be an integer." >&2
    exit 1
fi

# --- Ensure analyzer exists ---
if [[ ! -f "$ANALYZER" ]]; then
    echo "ERROR: Analyzer not found: $ANALYZER" >&2
    exit 1
fi

# --- CLI parsing ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --daemon)       DAEMON=true; shift ;;
        --interval)     INTERVAL="$2"; shift 2 ;;
        --verbose)      VERBOSE=true; shift ;;
        --dry-run)      DRY_RUN=true; shift ;;
        --status)       SHOW_STATUS=true; shift ;;
        --help|-h)
            cat <<'EOF'
Usage: session-guard.sh [OPTIONS]

Options:
  --daemon          Run continuously, checking every --interval seconds
  --interval N      Seconds between checks (default: 3600)
  --verbose         Print all sessions, not just alerts
  --dry-run         Preview scan output without writing markers or sending notifications
  --status          Show daemon health and last scan state
  --help            Show this message

Config: ~/.config/session-guard/config
EOF
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# --- Utilities ---
_notify() {
    local title="$1" body="$2" urgency="${3:-normal}"
    if command -v notify-send &>/dev/null; then
        notify-send -u "$urgency" -a "session-guard" "$title" "$body"
    elif command -v osascript &>/dev/null; then
        osascript -e "display notification \"$body\" with title \"$title\""
    else
        echo "[ALERT] $title: $body" >&2
    fi

    if [ -n "${DISCORD_WEBHOOK_ALERTS:-}" ]; then
        local color; [ "$urgency" = "critical" ] && color=15158332 || color=3066993
        curl -s -X POST "$DISCORD_WEBHOOK_ALERTS" \
            -H "Content-Type: application/json" \
            -d "{\"embeds\":[{\"title\":\"$title\",\"description\":\"$body\",\"color\":$color,\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}]}" >/dev/null 2>&1 &
    fi
}

_should_notify_today() {
    local today; today=$(date +%Y-%m-%d)
    [[ ! -f "$NOTIFY_STATE_FILE" ]] && return 0
    local last_day; last_day=$(grep "^daily-summary " "$NOTIFY_STATE_FILE" 2>/dev/null | awk '{print $2}' || echo "")
    [[ -z "$last_day" || "$last_day" != "$today" ]] && return 0
    return 1
}

_record_daily_notification() {
    local today; today=$(date +%Y-%m-%d)
    mkdir -p "$STATE_DIR"
    touch "$NOTIFY_STATE_FILE"
    grep -v "^daily-summary " "$NOTIFY_STATE_FILE" > "${NOTIFY_STATE_FILE}.tmp" 2>/dev/null || true
    echo "daily-summary $today" >> "${NOTIFY_STATE_FILE}.tmp"
    mv "${NOTIFY_STATE_FILE}.tmp" "$NOTIFY_STATE_FILE"
}

_cleanup_old_markers() {
    # Retention: keep only last 30 days of markers
    local retention_days=${MARKER_RETENTION_DAYS:-30}
    if [[ -d "$MARKER_DIR" ]]; then
        find "$MARKER_DIR" -name "*.json" -type f -mtime +"$retention_days" -delete
    fi
    # Compact notified-sessions state: keep only last 90 days of per-session entries
    if [[ -f "$NOTIFY_STATE_FILE" ]]; then
        local cutoff_epoch
        cutoff_epoch=$(date -d '90 days ago' +%s 2>/dev/null || echo "0")
        grep -v "^daily-summary " "$NOTIFY_STATE_FILE" | while read -r sess_id epoch; do
            [[ "$epoch" =~ ^[0-9]+$ ]] || continue
            if (( epoch > cutoff_epoch )); then
                echo "$sess_id $epoch"
            fi
        done > "${NOTIFY_STATE_FILE}.tmp"
        grep "^daily-summary " "$NOTIFY_STATE_FILE" >> "${NOTIFY_STATE_FILE}.tmp"
        mv "${NOTIFY_STATE_FILE}.tmp" "$NOTIFY_STATE_FILE"
    fi
}

_show_status() {
    echo "session-guard status"
    echo "===================="
    echo "  Config: ${CONFIG_DIR}/config"
    echo "  Plan type: ${PLAN_TYPE}"
    echo "  Max cost: ${MAX_COST_USD}"
    echo "  Max turns: ${MAX_TURNS}"
    echo "  Interval: ${INTERVAL}s"
    echo ""

    # Service state
    if systemctl --user is-active session-guard.service >/dev/null 2>&1; then
        echo "  Service: active"
        systemctl --user show session-guard.service --property=MainPID,MemoryCurrent,ExecMainStartTimestamp --value 2>/dev/null | \
            while IFS= read -r line; do echo "    $line"; done
    else
        echo "  Service: inactive"
    fi

    # Last notification
    if [[ -f "$NOTIFY_STATE_FILE" ]]; then
        local last_notify
        last_notify=$(grep "^daily-summary " "$NOTIFY_STATE_FILE" 2>/dev/null | tail -1 || echo "never")
        echo "  Last digest: ${last_notify#daily-summary }"
    else
        echo "  Last digest: never"
    fi

    # Marker count
    if [[ -d "$MARKER_DIR" ]]; then
        local marker_count
        marker_count=$(find "$MARKER_DIR" -name "*.json" -type f | wc -l)
        echo "  Markers: ${marker_count} files"
    else
        echo "  Markers: 0 files"
    fi

    # Quick scan preview
    echo ""
    echo "  Last scan preview:"
    local scan_err
    scan_err=$(mktemp)
    if _scan_once >/dev/null 2>"$scan_err"; then
        echo "    (scan succeeded — see above for details)"
    else
        echo "    (scan failed — last stderr lines:)"
        tail -5 "$scan_err" | sed 's/^/      /'
    fi
    rm -f "$scan_err"
}

# --- Scan logic ---
_scan_once() {
    local analysis_json
    local analyzer_stderr
    analyzer_stderr=$(mktemp)
    analysis_json=$(AI_SPEND_TRANSCRIPT_DIR="$TRANSCRIPT_DIR" python3 "$ANALYZER" \
        --plan-type "$PLAN_TYPE" \
        --monthly-token-limit "$MONTHLY_TOKEN_LIMIT" \
        --max-cost "$MAX_COST_USD" \
        --max-turns "$MAX_TURNS" \
        --max-context-limits "$MAX_CONTEXT_LIMITS" \
        $([[ "$DRY_RUN" == true ]] && echo --dry-run) \
        $([[ "$VERBOSE" == true ]] && echo --verbose) 2>"$analyzer_stderr") || {
        echo "$(date -Iseconds) ERROR: Analyzer failed (see $analyzer_stderr)" >&2
        cat "$analyzer_stderr" >&2
        rm -f "$analyzer_stderr"
        return 1
    }
    rm -f "$analyzer_stderr"

    local total_cloud_cost total_cloud_turns total_cloud_tokens
    local ollama_reqs_24h ollama_electricity_cost model_mix_shift
    local forecast_message comparison_message breach

    total_cloud_cost=$(echo "$analysis_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_cloud_cost',0))")
    total_cloud_turns=$(echo "$analysis_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_cloud_turns',0))")
    total_cloud_tokens=$(echo "$analysis_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total_cloud_tokens',0))")
    ollama_reqs_24h=$(echo "$analysis_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ollama_requests_24h',0))")
    ollama_electricity_cost=$(echo "$analysis_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ollama_electricity_cost',0))")
    model_mix_shift=$(echo "$analysis_json" | python3 -c "import sys,json; d=json.load(sys.stdin).get('model_mix_shift',''); print(d)")
    forecast_message=$(echo "$analysis_json" | python3 -c "import sys,json; d=json.load(sys.stdin).get('forecast_message',''); print(d)")
    comparison_message=$(echo "$analysis_json" | python3 -c "import sys,json; d=json.load(sys.stdin).get('comparison_message',''); print(d)")
    breach=$(echo "$analysis_json" | python3 -c "import sys,json; print('true' if json.load(sys.stdin).get('breach',False) else 'false')")

    # Format numbers
    local cloud_cost_fmt tokens_fmt elec_fmt
    cloud_cost_fmt=$(python3 -c "print(f'{float('$total_cloud_cost'):.2f}')")
    tokens_fmt=$(python3 -c "
t=$total_cloud_tokens
if t >= 1_000_000:
    print(f'{t/1_000_000:.1f}M')
elif t >= 1_000:
    print(f'{t/1_000:.0f}K')
else:
    print(str(t))
")
    elec_fmt=$(python3 -c "print(f'{float('$ollama_electricity_cost'):.2f}')")

    # Parse monthly forecast from JSON
    local monthly_forecast
    monthly_forecast=$(echo "$analysis_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('monthly_forecast',''))")

    # Build digest body (metered vs flat)
    local body=""
    if [[ "$PLAN_TYPE" == "flat" ]]; then
        local usage_pct limit_fmt
        usage_pct=$(python3 -c "pct=$total_cloud_tokens/$MONTHLY_TOKEN_LIMIT*100; print(f'{pct:.1f}')")
        limit_fmt=$(python3 -c "
n=$MONTHLY_TOKEN_LIMIT
if n >= 1_000_000_000:
    print(f'{n/1_000_000_000:.0f}B')
elif n >= 1_000_000:
    print(f'{n/1_000_000:.0f}M')
else:
    print(str(n))
")
        body="Flat Plan: ${usage_pct}% used (${tokens_fmt} / ${limit_fmt}, ${total_cloud_turns} turns)"
    else
        body="Metered: \$${cloud_cost_fmt} (${total_cloud_turns} turns, ${tokens_fmt} tokens)"
    fi
    # Use python3 for float comparison (bc not guaranteed on all platforms)
    if python3 -c "import sys; sys.exit(0 if float('$ollama_electricity_cost') > 0 else 1)" 2>/dev/null; then
        body="${body} | Local: ~\$${elec_fmt} electricity (${ollama_reqs_24h} reqs)"
    fi

    # Append novel insights
    if [[ -n "$monthly_forecast" ]]; then
        body="${body}\n${monthly_forecast}"
    fi
    if [[ -n "$forecast_message" ]]; then
        body="${body}\n${forecast_message}"
    fi
    if [[ -n "$comparison_message" ]]; then
        body="${body}\n${comparison_message}"
    fi
    if [[ -n "$model_mix_shift" ]]; then
        body="${body}\n${model_mix_shift}"
    fi

    # Determine urgency
    local urgency="normal"
    if [[ "$breach" == "true" ]]; then
        urgency="critical"
    fi

    if [[ "$DRY_RUN" == true ]]; then
        echo "$(date -Iseconds) DRY-RUN: $body (breach=$breach)"
        return 0
    fi

    if [[ "$breach" == "true" ]] && _should_notify_today; then
        _notify "Daily AI Spend Digest" "$body" "$urgency"
        _record_daily_notification
        echo "$(date -Iseconds) NOTIFY: $body"
    elif [[ "$VERBOSE" == true ]]; then
        echo "$(date -Iseconds) SCAN: $body (breach=$breach)"
    fi
}

# --- Main ---
if [[ "${SHOW_STATUS:-false}" == true ]]; then
    _show_status
    exit 0
fi

if [[ "$DAEMON" == true ]]; then
    echo "session-guard daemon started. PID $$"
    echo "  interval: ${INTERVAL}s"
    echo "  analyzer: $ANALYZER"
    # Graceful shutdown: finish current iteration before exiting
    _running=true
    _shutdown() {
        echo "$(date -Iseconds) SIGTERM received, shutting down after current iteration..."
        _running=false
    }
    trap _shutdown SIGTERM SIGINT
    while [[ "$_running" == true ]]; do
        _cleanup_old_markers
        _scan_once || true
        sleep "$INTERVAL"
    done
    echo "$(date -Iseconds) Daemon exiting cleanly"
else
    _scan_once
fi
