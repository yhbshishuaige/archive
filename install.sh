#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=${1:-/usr/bin/archive}

install -m 755 "$SCRIPT_DIR/local_archive.py" "$TARGET"
printf 'installed: %s\n' "$TARGET"
