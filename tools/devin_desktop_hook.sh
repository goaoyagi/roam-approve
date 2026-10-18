#!/usr/bin/env bash
# Wrapper so Devin Desktop (GUI) can run the hook without inheriting a login-shell env.
# Loads repo .env (gitignored) and execs roam-approve-hook. Intended for hooks.v1.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${TMPDIR:-/tmp}/roam-approve-desktop-hook.log"
{
  echo "$(date '+%Y-%m-%dT%H:%M:%S%z') invoke cwd=$(pwd) path=$PATH"
} >>"$LOG" 2>/dev/null || true

if [[ ! -f "$ROOT/.env" ]]; then
  echo "roam-approve-hook: missing $ROOT/.env (run make gen-tokens)" >&2
  echo "$(date '+%Y-%m-%dT%H:%M:%S%z') missing .env" >>"$LOG" 2>/dev/null || true
  exit 0
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

export PATH="${HOME}/.local/bin:/opt/homebrew/bin:${PATH}"
exec roam-approve-hook devin-cli
