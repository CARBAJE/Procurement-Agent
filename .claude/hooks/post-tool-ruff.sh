#!/usr/bin/env bash
# PostToolUse hook for Write/Edit on .py files.
# Reads the tool-call JSON from stdin (same protocol as pre-tool-security.sh)
# and runs `ruff check --fix` on the affected file when ruff is installed.
# Always exits 0 — never blocks.
set -u

INPUT=$(cat)

FILE_PATH=$(printf '%s' "$INPUT" | python3 -c "import sys,json
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    print(ti.get('file_path', ti.get('path', '')))
except Exception:
    print('')" 2>/dev/null || echo "")

# Only act on .py files when ruff is on PATH
case "$FILE_PATH" in
    *.py)
        if command -v ruff >/dev/null 2>&1 && [[ -f "$FILE_PATH" ]]; then
            ruff check --fix --quiet "$FILE_PATH" >/dev/null 2>&1 || true
            ruff format --quiet "$FILE_PATH" >/dev/null 2>&1 || true
        fi
        ;;
esac

exit 0
