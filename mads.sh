#!/usr/bin/env bash
# Wrapper to run mads CLI with .env loaded.
# Usage: ./mads.sh query --node act_123456789/campaigns --fields id,name,status
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$DIR/.env" ]; then
    set -a; source "$DIR/.env"; set +a
fi
exec python3 "$DIR/mads" "$@"
