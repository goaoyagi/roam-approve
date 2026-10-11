#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  tracked="$(git ls-files)"
  bad="$(printf '%s\n' "$tracked" | grep -E '(^|/)\.env($|\.)|(^|/)include/config\.h$' | grep -v '^\.env\.example$' || true)"
  if [ -n "$bad" ]; then
    echo "check-secrets: secret files are tracked by git:" >&2
    printf '%s\n' "$bad" >&2
    exit 1
  fi
else
  echo "check-secrets: not a git repo; scanning working tree for secret files" >&2
  bad="$(find . -type f \( -name '.env' -o -name '.env.*' -o -name 'config.h' -path '*/include/*' \) \
    -not -path './.venv/*' -not -name '.env.example' || true)"
  if [ -n "$bad" ]; then
    echo "check-secrets: secret files found in working tree:" >&2
    printf '%s\n' "$bad" >&2
    exit 1
  fi
fi

command -v gitleaks >/dev/null || { echo "gitleaks not installed: brew install gitleaks" >&2; exit 1; }

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  gitleaks detect --source . --redact
else
  gitleaks detect --no-git --source . --redact
fi

echo "check-secrets: OK"
