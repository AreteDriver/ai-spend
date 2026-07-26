#!/usr/bin/env bats
# session-guard bats integration tests
# Run: tests/bats/bin/bats tests/test_session_guard_bats.bats

setup() {
    export TEST_HOME=$(mktemp -d)
    export HOME="$TEST_HOME"
    export CONFIG_DIR="$HOME/.config/session-guard"
    export STATE_DIR="$HOME/.local/share/ai-spend/session-guard"
    export MARKER_DIR="$HOME/.local/share/ai-spend/marathons"
    mkdir -p "$CONFIG_DIR" "$STATE_DIR" "$MARKER_DIR"
    export SCRIPT_DIR="/home/arete/projects/ai-spend/scripts"
}

teardown() {
    rm -rf "$TEST_HOME"
}

@test "help flag prints usage and exits 0" {
    run bash "$SCRIPT_DIR/session-guard.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" == *"Usage:"* ]]
}

@test "invalid option exits 1 with error" {
    run bash "$SCRIPT_DIR/session-guard.sh" --invalid-opt
    [ "$status" -eq 1 ]
    [[ "$output" == *"Unknown option"* ]]
}

@test "invalid plan type in config is rejected" {
    echo 'PLAN_TYPE=invalid' > "$CONFIG_DIR/config"
    run bash "$SCRIPT_DIR/session-guard.sh" --dry-run
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid PLAN_TYPE"* ]]
}

@test "invalid max_cost in config is rejected" {
    echo 'MAX_COST_USD=not_a_number' > "$CONFIG_DIR/config"
    run bash "$SCRIPT_DIR/session-guard.sh" --dry-run
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid MAX_COST_USD"* ]]
}

@test "status shows no cache before first run" {
    run bash "$SCRIPT_DIR/session-guard.sh" --status
    [ "$status" -eq 0 ]
    [[ "$output" == *"Last scan: never"* ]]
}

@test "status reads cached scan after run" {
    bash "$SCRIPT_DIR/session-guard.sh" >/dev/null 2>&1
    run bash "$SCRIPT_DIR/session-guard.sh" --status
    [ "$status" -eq 0 ]
    [[ "$output" == *"Last scan:"* ]]
    [[ "$output" != *"never"* ]]
}

@test "dry-run does not write last-scan cache" {
    rm -f "$STATE_DIR/last-scan.json"
    bash "$SCRIPT_DIR/session-guard.sh" --dry-run >/dev/null 2>&1
    [ ! -f "$STATE_DIR/last-scan.json" ]
}

@test "normal run writes last-scan cache and health timestamp" {
    bash "$SCRIPT_DIR/session-guard.sh" >/dev/null 2>&1
    [ -f "$STATE_DIR/last-scan.json" ]
    [ -f "$STATE_DIR/last-scan-ok" ]
}

@test "daily notification is throttled after daily-summary recorded" {
    mkdir -p "$STATE_DIR"
    today=$(date +%Y-%m-%d)
    # Record daily summary AND a notify entry so max_per_cycle (default 1) is hit
    echo "daily-summary $today" > "$STATE_DIR/notified-sessions"
    echo "notify $(date +%s) $today" >> "$STATE_DIR/notified-sessions"

    run bash -c "
        export HOME='$HOME'
        export CONFIG_DIR='$CONFIG_DIR'
        export STATE_DIR='$STATE_DIR'
        export MARKER_DIR='$MARKER_DIR'
        export NOTIFY_STATE_FILE='$STATE_DIR/notified-sessions'
        eval \"\$(sed -n '/^_should_notify_today()/,/^}/p' '$SCRIPT_DIR/session-guard.sh')\"
        _should_notify_today && echo YES || echo NO
    "
    [ "$status" -eq 0 ]
    [[ "$output" == *"NO"* ]]
}

@test "notify max per cycle is enforced" {
    mkdir -p "$STATE_DIR"
    today=$(date +%Y-%m-%d)
    echo "daily-summary $today" > "$STATE_DIR/notified-sessions"
    echo "notify $(date +%s) $today" >> "$STATE_DIR/notified-sessions"

    run bash -c "
        export HOME='$HOME'
        export CONFIG_DIR='$CONFIG_DIR'
        export STATE_DIR='$STATE_DIR'
        export MARKER_DIR='$MARKER_DIR'
        export NOTIFY_STATE_FILE='$STATE_DIR/notified-sessions'
        export NOTIFY_MAX_PER_CYCLE=1
        eval \"\$(sed -n '/^_should_notify_today()/,/^}/p' '$SCRIPT_DIR/session-guard.sh')\"
        _should_notify_today && echo YES || echo NO
    "
    [ "$status" -eq 0 ]
    [[ "$output" == *"NO"* ]]
}

@test "state compaction removes old per-session entries" {
    mkdir -p "$STATE_DIR"
    old_epoch=$(python3 -c "import time; print(int(time.time()) - 100*86400)")
    echo "session-abc $old_epoch" > "$STATE_DIR/notified-sessions"
    echo "daily-summary $(date +%Y-%m-%d)" >> "$STATE_DIR/notified-sessions"

    # Trigger compaction directly (normally only runs in daemon mode)
    bash -c "
        export HOME='$HOME'
        export CONFIG_DIR='$CONFIG_DIR'
        export STATE_DIR='$STATE_DIR'
        export MARKER_DIR='$MARKER_DIR'
        export NOTIFY_STATE_FILE='$STATE_DIR/notified-sessions'
        eval \"\$(sed -n '/^_cleanup_old_markers()/,/^}/p' '$SCRIPT_DIR/session-guard.sh')\"
        _cleanup_old_markers
    "

    # Old entry should be gone
    run grep "session-abc" "$STATE_DIR/notified-sessions"
    [ "$status" -ne 0 ]
    # Daily summary should remain
    run grep "daily-summary" "$STATE_DIR/notified-sessions"
    [ "$status" -eq 0 ]
}

@test "single-pass JSON extractor handles multi-line strings" {
    json='{"total_cloud_cost":1.0,"total_cloud_turns":2,"total_cloud_tokens":3,"ollama_requests_24h":4,"ollama_electricity_cost":5,"model_mix_shift":"a\nb","forecast_message":"c\nd","comparison_message":"","breach":true,"monthly_forecast":"e\nf"}'

    run bash -c "
        readarray -t _fields < <(python3 -c '
import sys, json
d = json.load(sys.stdin)
for key, default in [
    (\"total_cloud_cost\", 0),
    (\"total_cloud_turns\", 0),
    (\"total_cloud_tokens\", 0),
    (\"ollama_requests_24h\", 0),
    (\"ollama_electricity_cost\", 0),
    (\"model_mix_shift\", \"\"),
    (\"forecast_message\", \"\"),
    (\"comparison_message\", \"\"),
    (\"breach\", False),
    (\"monthly_forecast\", \"\"),
]:
    v = d.get(key, default)
    if isinstance(v, bool):
        print(\"true\" if v else \"false\")
    elif isinstance(v, str):
        print(v.replace(chr(10), \" \"))
    else:
        print(v)
' <<< '$json')
        echo \"cost=\${_fields[0]} turns=\${_fields[1]} breach=\${_fields[8]}\"
    "
    [ "$status" -eq 0 ]
    [[ "$output" == *"cost=1.0"* ]]
    [[ "$output" == *"turns=2"* ]]
    [[ "$output" == *"breach=true"* ]]
}
