#!/usr/bin/env bash
# Open an SSH tunnel to the wiki server so upload scripts can reach the
# MediaWiki API at http://localhost:${LOCAL_PORT}/api.php over an encrypted link.
#
# Usage:  scripts/upload_channel.sh        (Ctrl+C to close)
#
# Settings can be overridden in .env: WIKI_SSH_HOST, WIKI_SSH_PORT,
# WIKI_SSH_USER, WIKI_LOCAL_PORT.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a; source "$REPO_ROOT/.env"; set +a
fi

SSH_HOST="${WIKI_SSH_HOST:-152.66.245.139}"
SSH_PORT="${WIKI_SSH_PORT:-2278}"
SSH_USER="${WIKI_SSH_USER:-ubuntu}"
LOCAL_PORT="${WIKI_LOCAL_PORT:-8080}"

if lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $LOCAL_PORT is already in use (maybe the tunnel is already open)." >&2
  exit 1
fi

echo "Tunnel: http://localhost:$LOCAL_PORT/api.php -> $SSH_USER@$SSH_HOST:$SSH_PORT (wiki port 80)"
echo "Leave this window open while uploading. Ctrl+C closes the tunnel."
echo "If the connection drops, it is reopened after 5 seconds."

trap 'exit 0' INT TERM
while true; do
  ssh -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -o ConnectTimeout=15 \
    -p "$SSH_PORT" \
    -L "$LOCAL_PORT:localhost:80" \
    "$SSH_USER@$SSH_HOST" || true
  echo "$(date '+%H:%M:%S') tunnel closed, reconnecting in 5 s" >&2
  sleep 5
done
