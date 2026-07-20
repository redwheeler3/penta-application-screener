#!/usr/bin/env bash
# PreToolUse(Bash) guard for the local SQLite database.
#
# Two tiers, per .clinerules ("NEVER reset or delete the local DB without asking Jeff"):
#   ASK   — table-dropping / db-file-destroying commands. These are how an "unauthorized
#           reset" happens (a python -c with drop_all slipped past a narrower guard once
#           and wiped real runs). Surfaced as a confirmation prompt so Jeff decides — the
#           model can't run one silently, but an approved command still goes through.
#   ASK   — git commit (per the separate commit-confirm rule).
#
# Reads the tool-call JSON on stdin, emits a PreToolUse permission decision on stdout.
# Fails OPEN (allow) only on unexpected internal error, never on a matched destructive
# command — a matched command always prompts even if jq is odd.
set -euo pipefail

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""')"

ask() {
  printf '%s' "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"ask\",\"permissionDecisionReason\":\"$1\"}}"
  exit 0
}

# --- ASK: destroys the DB or its tables (confirm before running) ------------------
# SQLAlchemy metadata table drops (the exact gap that caused data loss):
if printf '%s' "$cmd" | grep -Eq 'drop_all|create_all|DROP[[:space:]]+TABLE'; then
  ask "Confirm: drops/recreates DB tables (drop_all/create_all/DROP TABLE) — this destroyed real runs before. Approve only if you intend to reset the DB (irreversible, no backup)."
fi
# The reset script, or deleting/moving/truncating the sqlite file or its data/ dir:
if printf '%s' "$cmd" | grep -Eq 'reset-db\.(sh|ps1)'; then
  ask "Confirm: reset-db is irreversible (real Bedrock spend, no backup)."
fi
if printf '%s' "$cmd" | grep -Eq '(rm|unlink|shred|mv|truncate|:>|>[[:space:]]*)[^|;&]*(\.db|\.sqlite3?|penta_screener|/data/|data/penta)'; then
  ask "Confirm: deletes/overwrites the SQLite DB or data/ dir. Irreversible — approve only if intended."
fi

# --- ASK: commit confirmation (kept from the prior guard) -------------------------
if printf '%s' "$cmd" | grep -Eq 'git[[:space:]]+commit'; then
  ask "Confirm: commit? (.clinerules — only when your last message asked)."
fi

# No match: allow (emit nothing).
exit 0
