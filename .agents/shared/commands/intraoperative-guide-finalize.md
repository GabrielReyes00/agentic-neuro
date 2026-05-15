# Intraoperative Guide Finalization Module

Use this module only after expert completeness review returns `APPROVED`.

## Purpose

Install the approved guide, run deterministic validation, and complete shared learning-system bookkeeping without altering the expert-approved substance except to fix validation failures.

## Preconditions

- The guide has passed `.agents/shared/commands/intraoperative-guide-review.md` with `APPROVED`.
- The decomposition and operative knowledge-map review are complete.
- Every wikilink in the guide was verified against the real vault scan.
- The guide has no H1 and no top YAML.
- Bottom YAML metadata is present.
- `## Mastery Objectives` and `## Related in This Vault` are present before bottom YAML.

## Write Target

Write the guide to:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md
```

If this is a dry run, do not write to the real vault. Use `data/Sessions/<Title> Dry Run.md` and clearly report that no real vault, memory, or Anki writes occurred.

Before writing, confirm the destination is exactly under `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/`. Do not write real guides into repo-local shadow paths.

## Deterministic Validation

Run:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/operative_guide_validator.py "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md"
```

For dry runs, validate the dry-run path instead.

If validation fails, revise only the issue needed to satisfy the guard, then rerun validation. Do not use the validator as a substitute for expert review.

The validator also rejects unverified wikilinks when the Obsidian vault is available. If it reports broken wikilinks, remove the link syntax or replace the target with an exact verified note title.

## Index, Concepts, Memory, and Anki

For real runs:

1. Update `Operative Guides/INDEX.md`.
2. Extract 2-5 atomic concepts worth future review.
3. Log the guide to memory using the shared learning-session contract.
4. Queue Anki cards only when durable spaced-repetition facts are present.

Operative-guide Anki cards are a deck-routing exception. Every card generated from this guide must use:

```text
Neurosurgery::Procedures::<Title>
```

Do not scatter operative-guide cards into ordinary domain decks.

For dry runs:

- Do not update vault indexes.
- Do not extract/write concept stubs.
- Do not log memory.
- Do not create or flush Anki cards.

## Wikilink Verification

Before final validation, verify all wikilinks:

- Extract every `[[...]]` target from the guide.
- Confirm the target title exactly matches a `.md` filename from the vault scan, without the `.md` suffix.
- Remove or rewrite any unverified wikilink as plain text.
- Ensure `## Related in This Vault` lists only verified targets and explains why each is relevant.

## Scratch Cleanup

For real runs, delete or discard temporary workflow ledgers, decomposition notes, research briefs, operative knowledge maps, expert review memos, and gap-repair memos before skill execution concludes unless Gabriel explicitly asks to preserve them. These files are workflow scaffolding, not vault artifacts.

For dry runs or explicit debugging, preserve the dry-run guide and workflow ledger in `data/Sessions/` so output quality and agent behavior can be inspected.

## User-Facing Summary

Report:

- Final file path or dry-run path.
- Source mix.
- Number of expert review cycles.
- Whether the workflow ledger was completed.
- Whether decomposition and operative knowledge-map review completed.
- Whether targeted RAG or PubMed gap repair was needed.
- Validator result.
- Wikilinks added or reason none were added.
- Whether vault/memory/Anki writes were performed.
- Any intentionally omitted domains and why.
