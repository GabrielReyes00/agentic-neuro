#!/usr/bin/env bash
# sync_vault.sh — commit and push all vault changes to GitHub
# Called silently at the end of every agent session that writes to Obsidian.
# Does nothing if there are no changes (clean working tree).

VAULT="/Users/gabrielreyes/Documents/Obsidian/agentic-neuro"

cd "$VAULT" || exit 1

if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  exit 0
fi

git add -A
git commit -m "vault sync: $(date '+%Y-%m-%d %H:%M:%S')"
git push
