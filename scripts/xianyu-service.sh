#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="${XIANYU_AGENT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd -P)}"
VENV_DIR="${XIANYU_AGENT_VENV:-$PROJECT_ROOT/.venv}"
PYTHON_BIN="${XIANYU_AGENT_PYTHON:-$VENV_DIR/bin/python}"
PYTHON_BOOTSTRAP="${XIANYU_AGENT_BOOTSTRAP_PYTHON:-python3}"
LOG_DIR="${XIANYU_AGENT_LOG_DIR:-$PROJECT_ROOT/logs}"
LIVE_SESSION="${XIANYU_AGENT_LIVE_SESSION:-xianyu-seller-agent-live}"
WEB_SESSION="${XIANYU_AGENT_WEB_SESSION:-xianyu-seller-agent-web}"
LIVE_LOG="${XIANYU_AGENT_LIVE_LOG:-$LOG_DIR/live.log}"
WEB_LOG="${XIANYU_AGENT_WEB_LOG:-$LOG_DIR/web.log}"
WEB_LOG_LEVEL="${XIANYU_WEB_LOG_LEVEL:-INFO}"

usage() {
  cat <<'USAGE'
xianyu-service.sh <command>

Commands:
  setup        Create .venv if needed and install requirements
  qr-login     Run QR login in the stable project root
  start        Start live automation and web dashboard
  start-live   Start only the live automation process
  start-web    Start only the local web dashboard
  stop         Stop live automation and web dashboard
  stop-live    Stop only the live automation process
  stop-web     Stop only the local web dashboard
  restart      Stop both processes, then start both processes
  status       Print session, root, venv, and log status
  doctor       Check runtime processes, cwd, .env, and web port health
  logs         Tail both live and web logs

Environment overrides:
  XIANYU_AGENT_ROOT=/absolute/repo/root
  XIANYU_AGENT_VENV=/absolute/path/to/.venv
  XIANYU_AGENT_LOG_DIR=/absolute/path/to/logs
  XIANYU_AGENT_LIVE_SESSION=xianyu-seller-agent-live
  XIANYU_AGENT_WEB_SESSION=xianyu-seller-agent-web
  XIANYU_WEB_LOG_LEVEL=INFO
  LINES=120
USAGE
}

fail() {
  echo "error: $*" >&2
  exit 1
}

quote() {
  printf '%q' "$1"
}

require_project_root() {
  [[ -f "$PROJECT_ROOT/main.py" ]] || fail "PROJECT_ROOT does not contain main.py: $PROJECT_ROOT"
}

ensure_screen() {
  command -v screen >/dev/null 2>&1 || fail "screen is required to manage background sessions"
}

ensure_venv() {
  require_project_root
  if [[ -x "$PYTHON_BIN" ]]; then
    "$PYTHON_BIN" -m pip install -r "$PROJECT_ROOT/requirements.txt"
    return
  fi

  echo "Creating virtualenv: $VENV_DIR"
  "$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$PROJECT_ROOT/requirements.txt"
}

require_env_for_live() {
  if [[ -n "${COOKIES_STR:-}" ]]; then
    return
  fi
  [[ -f "$PROJECT_ROOT/.env" ]] || fail "missing .env; run '$0 qr-login' or copy .env.example to .env"
  if ! grep -Eq '^COOKIES_STR=.+' "$PROJECT_ROOT/.env"; then
    fail "COOKIES_STR is missing in .env; run '$0 qr-login'"
  fi
  if grep -Eq '^COOKIES_STR=["'\'']?your_cookies_here' "$PROJECT_ROOT/.env"; then
    fail "COOKIES_STR is still the placeholder; run '$0 qr-login'"
  fi
}

session_exists() {
  local session="$1"
  { screen -ls 2>/dev/null || true; } | grep -Eq "[0-9]+\\.${session}[[:space:]]"
}

start_session() {
  local session="$1"
  local log_file="$2"
  local command="$3"

  ensure_screen
  mkdir -p "$LOG_DIR" "$PROJECT_ROOT/data"
  if session_exists "$session"; then
    echo "$session already running"
    return
  fi

  screen -dmS "$session" bash -lc "$command"
  echo "started $session"
  echo "log: $log_file"
}

start_live() {
  ensure_venv
  require_env_for_live
  local root_q py_q log_q
  root_q="$(quote "$PROJECT_ROOT")"
  py_q="$(quote "$PYTHON_BIN")"
  log_q="$(quote "$LIVE_LOG")"
  start_session "$LIVE_SESSION" "$LIVE_LOG" "cd $root_q && exec $py_q main.py >> $log_q 2>&1"
}

start_web() {
  ensure_venv
  local root_q py_q log_q level_q
  root_q="$(quote "$PROJECT_ROOT")"
  py_q="$(quote "$PYTHON_BIN")"
  log_q="$(quote "$WEB_LOG")"
  level_q="$(quote "$WEB_LOG_LEVEL")"
  start_session "$WEB_SESSION" "$WEB_LOG" "cd $root_q && LOG_LEVEL=$level_q exec $py_q main.py web >> $log_q 2>&1"
}

stop_session() {
  local session="$1"
  ensure_screen
  if ! session_exists "$session"; then
    echo "$session not running"
    return
  fi
  screen -S "$session" -X quit
  echo "stopped $session"
}

print_session_status() {
  local label="$1"
  local session="$2"
  if session_exists "$session"; then
    echo "$label: running ($session)"
  else
    echo "$label: stopped ($session)"
  fi
}

status() {
  require_project_root
  echo "root: $PROJECT_ROOT"
  echo "venv: $VENV_DIR"
  echo "python: $PYTHON_BIN"
  echo "logs: $LOG_DIR"
  if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo ".env: present"
  else
    echo ".env: missing"
  fi
  print_session_status "live" "$LIVE_SESSION"
  print_session_status "web" "$WEB_SESSION"
  [[ -f "$LIVE_LOG" ]] && echo "live_log: $LIVE_LOG"
  [[ -f "$WEB_LOG" ]] && echo "web_log: $WEB_LOG"
  return 0
}

process_cwd() {
  local pid="$1"
  { lsof -a -p "$pid" -d cwd -Fn 2>/dev/null || true; } | sed -n 's/^n//p' | head -n 1
}

cwd_is_project_root() {
  local cwd="$1"
  [[ "$cwd" == "$PROJECT_ROOT" || "$cwd" == "$PROJECT_ROOT/"* ]]
}

print_runtime_processes() {
  local found=0
  while read -r pid command_line; do
    [[ -n "${pid:-}" ]] || continue
    [[ "$command_line" == *"main.py"* ]] || continue
    found=1
    local cwd
    cwd="$(process_cwd "$pid")"
    if [[ -n "$cwd" ]]; then
      echo "pid $pid cwd: $cwd"
      if ! cwd_is_project_root "$cwd"; then
        echo "warning: pid $pid cwd is outside PROJECT_ROOT: $cwd"
      fi
    else
      echo "pid $pid cwd: unknown"
    fi
    echo "pid $pid command: $command_line"
  done < <(ps -axo pid=,command= 2>/dev/null || true)

  if [[ "$found" == "0" ]]; then
    echo "runtime_processes: none"
  fi
}

print_web_port_status() {
  local pids
  pids="$(lsof -nP -iTCP:8765 -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "web_port_8765: listening pid(s): ${pids//$'\n'/ }"
  else
    echo "web_port_8765: not listening"
  fi
}

doctor() {
  status
  echo "doctor: checking runtime process cwd and web port"
  print_runtime_processes
  print_web_port_status
}

tail_logs() {
  local lines="${LINES:-120}"
  echo "== live: $LIVE_LOG =="
  if [[ -f "$LIVE_LOG" ]]; then
    tail -n "$lines" "$LIVE_LOG"
  else
    echo "missing"
  fi
  echo
  echo "== web: $WEB_LOG =="
  if [[ -f "$WEB_LOG" ]]; then
    tail -n "$lines" "$WEB_LOG"
  else
    echo "missing"
  fi
}

run_qr_login() {
  ensure_venv
  cd "$PROJECT_ROOT"
  exec "$PYTHON_BIN" main.py --qr-login
}

command="${1:-help}"
case "$command" in
  help|--help|-h)
    usage
    ;;
  setup)
    ensure_venv
    ;;
  qr-login)
    run_qr_login
    ;;
  start)
    start_live
    start_web
    ;;
  start-live)
    start_live
    ;;
  start-web)
    start_web
    ;;
  stop)
    stop_session "$LIVE_SESSION"
    stop_session "$WEB_SESSION"
    ;;
  stop-live)
    stop_session "$LIVE_SESSION"
    ;;
  stop-web)
    stop_session "$WEB_SESSION"
    ;;
  restart)
    stop_session "$LIVE_SESSION"
    stop_session "$WEB_SESSION"
    start_live
    start_web
    ;;
  status)
    status
    ;;
  doctor)
    doctor
    ;;
  logs)
    tail_logs
    ;;
  *)
    usage >&2
    fail "unknown command: $command"
    ;;
esac
