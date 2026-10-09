#!/bin/bash
set -euo pipefail

WIKI_DIR="${WIKI_DIR:-$HOME/.claude/wiki}"
find "$WIKI_DIR" -maxdepth 1 -type f -name '*.md' \
  ! -name '_schema.md' \
  ! -name 'index.md' \
  ! -name 'log.md' \
  -print | sort
