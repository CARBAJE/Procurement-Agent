#!/usr/bin/env bash
# Pre-tool-use security gate for Bash and Write.
# Blocks dangerous shell patterns and suspicious file content.
# Output is the JSON contract Claude Code expects: {"decision": "block"|"allow", "reason": "..."}
set -euo pipefail

INPUT=$(cat)

TOOL=$(echo "$INPUT" | python3 -c "import sys,json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_name', ''))
except Exception:
    print('')" 2>/dev/null || echo "")

CMD=$(echo "$INPUT" | python3 -c "import sys,json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')" 2>/dev/null || echo "")

FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json
try:
    d = json.load(sys.stdin)
    ti = d.get('tool_input', {})
    print(ti.get('file_path', ti.get('path', '')))
except Exception:
    print('')" 2>/dev/null || echo "")

FILE_CONTENT=$(echo "$INPUT" | python3 -c "import sys,json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('content', ''))
except Exception:
    print('')" 2>/dev/null || echo "")

# ── Bash danger patterns ──────────────────────────────────────────────────────
BASH_DANGER=(
  'curl[^|]*\|[[:space:]]*(ba)?sh'
  'wget[^|]*\|[[:space:]]*(ba)?sh'
  'eval[[:space:]]*\$\('
  'base64[[:space:]]+-d[^|]*\|'
  "python[[:space:]]+-c[[:space:]]+[\"']import[[:space:]]+os"
  'rm[[:space:]]+(-[a-zA-Z]*[rRf][a-zA-Z]*[[:space:]]+)+(--[[:space:]]+)?(/|~|\.|\*|\$|"\$|"~)'
  'rm[[:space:]]+(-[a-zA-Z]*[rRf][a-zA-Z]*[[:space:]]+)+(--[[:space:]]+)?\.\.?(/|[[:space:]]|$)'
  'chmod[[:space:]]+[0-7]*7[[:space:]]+(/etc|/usr|/bin|/sbin)'
  '>[[:space:]]*/etc/(passwd|shadow|sudoers|crontab)'
  '__import__\(["'\'']os["'\'']\)'
  'subprocess.*shell=True.*\$\('
  'docker[[:space:]]+system[[:space:]]+prune[[:space:]]+.*-a.*-f'
  'git[[:space:]]+push[[:space:]]+.*--force.*main'
  'git[[:space:]]+push[[:space:]]+.*-f[[:space:]]+.*main'
  'DROP[[:space:]]+DATABASE'
  'TRUNCATE[[:space:]]+TABLE.*procurement_(requests|agent)'
)

# ── Write danger patterns (file content) ──────────────────────────────────────
WRITE_DANGER=(
  'os\.system\s*\([^)]*\$'
  'subprocess\.[a-zA-Z_]+\([^)]*shell=True[^)]*f["'\'']'
  'eval\s*\([^)]*request\.'
  'exec\s*\([^)]*request\.'
  'pickle\.loads\s*\([^)]*request\.'
  'yaml\.load\s*\([^)]*[^=]Loader'
  '__import__\([^)]*os[^)]*\)\.system'
  'ANTHROPIC_API_KEY\s*=\s*["'\''][a-zA-Z0-9_-]{20,}'
  'BAP_API_KEY\s*=\s*["'\''][a-zA-Z0-9_-]{12,}'
  'sk-[a-zA-Z0-9]{20,}'
  'OPENAI_API_KEY\s*=\s*["'\''][a-zA-Z0-9_-]{20,}'
  'Bearer\s+[A-Za-z0-9._-]{20,}'
  'DB_PASSWORD\s*=\s*["'\''][^"'\''$][a-zA-Z0-9!@#%^&*]{6,}'
)

block() {
  reason="${1:-blocked}"
  esc=$(printf '%s' "$reason" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
  echo "{\"decision\": \"block\", \"reason\": $esc}"
  exit 0
}

allow() {
  echo "{\"decision\": \"allow\"}"
  exit 0
}

if [[ "$TOOL" == "Bash" ]] && [[ -n "$CMD" ]]; then
  for pat in "${BASH_DANGER[@]}"; do
    if echo "$CMD" | grep -qE "$pat"; then
      block "Bash blocked by security hook — pattern '$pat' matched. Inspect the command manually."
    fi
  done
fi

if [[ "$TOOL" == "Write" ]] && [[ -n "$FILE_CONTENT" ]]; then
  for pat in "${WRITE_DANGER[@]}"; do
    if echo "$FILE_CONTENT" | grep -qE "$pat"; then
      block "Write blocked by security hook — pattern '$pat' matched in '$FILE_PATH'. Review for secrets or unsafe deserialisation."
    fi
  done
fi

allow
