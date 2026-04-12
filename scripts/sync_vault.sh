#!/usr/bin/env bash
# sync_vault.sh — commit and push all vault changes to GitHub
# Called silently at the end of every agent session that writes to Obsidian.
# Does nothing if there are no changes (clean working tree).
set -euo pipefail

VAULT="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro"

if [[ ! -d "$VAULT/.git" ]]; then
  echo "sync_vault: vault is not a git repository: $VAULT" >&2
  exit 1
fi

cd "$VAULT"

if [[ -z "$(git status --porcelain --untracked-files=all)" ]]; then
  exit 0
fi

git add -A
if git diff --cached --quiet; then
  exit 0
fi

if ! git commit -m "vault sync: $(date '+%Y-%m-%d %H:%M:%S')" >/dev/null 2>&1; then
  # A concurrent sync may consume the staged diff before commit is created.
  if git diff --cached --quiet; then
    exit 0
  fi
  echo "sync_vault: git commit failed" >&2
  exit 1
fi

git push --quiet
