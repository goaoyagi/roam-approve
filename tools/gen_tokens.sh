#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
fi

agent_token="$(openssl rand -hex 32)"
device_token="$(openssl rand -hex 32)"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

sed -e "s|^ROAM_AGENT_TOKEN=.*|ROAM_AGENT_TOKEN=${agent_token}|" \
    -e "s|^ROAM_DEVICE_TOKEN=.*|ROAM_DEVICE_TOKEN=${device_token}|" \
    .env > "$tmp"
mv "$tmp" .env
chmod 600 .env

echo "tokens written to .env"
