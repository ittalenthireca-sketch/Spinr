#!/bin/bash
set -euo pipefail

# Only run in Claude Code remote (web) sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)}"

echo "[session-start] Installing backend Python dependencies..."
cd "$REPO/backend"
uv pip install -r requirements.txt --system --quiet

echo "[session-start] Installing admin-dashboard Node dependencies..."
cd "$REPO/admin-dashboard"
npm install --prefer-offline --no-audit --no-fund --loglevel=error

echo "[session-start] Installing rider-app Node dependencies..."
cd "$REPO/rider-app"
npm install --prefer-offline --no-audit --no-fund --loglevel=error

echo "[session-start] Installing driver-app Node dependencies..."
cd "$REPO/driver-app"
npm install --prefer-offline --no-audit --no-fund --loglevel=error

echo "[session-start] Installing frontend Node dependencies..."
cd "$REPO/frontend"
npm install --prefer-offline --no-audit --no-fund --loglevel=error

echo "[session-start] All dependencies installed."
