# Intraoperative Guide Crosslink Module

Use this module after the vault scan and again before finalization.

## Purpose

Connect the operative guide to real Obsidian vault knowledge without inventing wikilinks. Crosslinks should help a resident move from the procedure to related anatomy, pathology, consults, reports, study material, and other operative guides.

## Vault Target

All real operative guides write to:

```text
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/<Title>.md
```

The relative Obsidian path is:

```text
Operative Guides/<Title>.md
```

Do not write real operative guides to repo-local `data/Sessions/`, `Documents/`, or any shadow vault. `data/Sessions/` is only for dry runs, ledgers, and debugging artifacts.

## Discovery

Scan the real Obsidian vault for candidate notes:

```bash
cd /Users/gabrielreyes/agentic-neuro && \
find "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Consults" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material" \
     "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts" \
     -type f -name "*.md" 2>/dev/null
```

Use only exact filenames returned by the scan. Strip `.md` for wikilinks. If a filename contains spaces, use the exact note title inside `[[...]]`.

## Selection Rules

Prefer links that help operative study:

- Same or adjacent procedure.
- Anatomy that changes the operation.
- Pathology/indication reports.
- Complication management notes.
- Relevant consults or study material.
- Concepts that explain a danger structure, corridor, bailout, or postoperative signature.

Avoid links that are merely keyword matches. Do not link every possible related note. A small set of high-signal links is better than a long generic list.

## Placement Rules

Use wikilinks in two places:

- **Inline at point of relevance** when the linked note deepens or avoids duplicating a concept.
- **`## Related in This Vault`** near the end, with one short explanation of why each link matters.

Examples:

```markdown
The anterior cervical corridor should be planned against the patient's sagittal alignment and ventral compression pattern, which overlaps with [[Cervical Spondylotic Myelopathy]].

## Related in This Vault

- [[Cervical Spondylotic Myelopathy]] - indication and alignment logic relevant to choosing ACDF versus posterior decompression.
- [[Recurrent Laryngeal Nerve]] - anatomy-risk relationship for anterior cervical exposure and postoperative hoarseness.
```

## Dry Runs

Dry runs may scan the vault and list candidate links in the ledger, but should not add speculative links. If the scan is skipped or unavailable, state `No verified dry-run wikilinks were added.`
