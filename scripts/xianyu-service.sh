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
  local runtime_kind="${2:-}"
  ensure_screen
  if ! session_exists "$session"; then
    echo "$session not running"
    if [[ -n "$runtime_kind" ]]; then
      terminate_runtime_processes "$runtime_kind"
    fi
    return
  fi
  screen -S "$session" -X quit
  echo "stopped $session"
  if [[ -n "$runtime_kind" ]]; then
    terminate_runtime_processes "$runtime_kind"
  fi
}

runtime_process_matches() {
  local runtime_kind="$1"
  local command_line="$2"
  local cwd="$3"

  [[ "$command_line" == *"main.py"* ]] || return 1
  case "$runtime_kind" in
    live)
      [[ "$command_line" != *"main.py web"* ]] || return 1
      ;;
    web)
      [[ "$command_line" == *"main.py web"* ]] || return 1
      ;;
    *)
      return 1
      ;;
  esac

  [[ "$cwd" == "$PROJECT_ROOT" || "$command_line" == *"$PROJECT_ROOT"* ]]
}

terminate_runtime_processes() {
  local runtime_kind="$1"
  local pids=()
  local pid command_line cwd

  while read -r pid command_line; do
    [[ -n "${pid:-}" ]] || continue
    [[ "$pid" != "$$" ]] || continue
    cwd="$(process_cwd "$pid")"
    if runtime_process_matches "$runtime_kind" "$command_line" "$cwd"; then
      pids+=("$pid")
    fi
  done < <(ps -axo pid=,command= 2>/dev/null || true)

  if [[ "${#pids[@]}" == "0" ]]; then
    return
  fi

  for pid in "${pids[@]}"; do
    kill "$pid" 2>/dev/null || true
    echo "terminated stale $runtime_kind process pid $pid"
  done

  sleep 1
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
      echo "force-killed stale $runtime_kind process pid $pid"
    fi
  done
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

cwd_is_stable_project_root() {
  local cwd="$1"
  [[ "$cwd" == "$PROJECT_ROOT" ]]
}

env_file_value() {
  local key="$1"
  [[ -f "$PROJECT_ROOT/.env" ]] || return 0
  local line value
  line="$(grep -E "^[[:space:]]*${key}=" "$PROJECT_ROOT/.env" 2>/dev/null | tail -n 1 || true)"
  [[ -n "$line" ]] || return 0
  value="${line#*=}"
  value="${value%%#*}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value%$'\r'}"
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s\n' "$value"
}

configured_web_port() {
  if [[ -n "${WEB_PORT:-}" ]]; then
    printf '%s\n' "$WEB_PORT"
    return
  fi
  local port
  port="$(env_file_value WEB_PORT)"
  if [[ -n "$port" ]]; then
    printf '%s\n' "$port"
  else
    printf '8765\n'
  fi
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
      if ! cwd_is_stable_project_root "$cwd"; then
        echo "warning: pid $pid cwd is not stable PROJECT_ROOT: $cwd"
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
  local port
  local pids
  port="$(configured_web_port)"
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "web_port_$port: listening pid(s): ${pids//$'\n'/ }"
  else
    echo "web_port_$port: not listening"
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
    stop_session "$LIVE_SESSION" live
    stop_session "$WEB_SESSION" web
    ;;
  stop-live)
    stop_session "$LIVE_SESSION" live
    ;;
  stop-web)
    stop_session "$WEB_SESSION" web
    ;;
  restart)
    stop_session "$LIVE_SESSION" live
    stop_session "$WEB_SESSION" web
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
