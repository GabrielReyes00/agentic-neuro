# Refactor Manual Note

Convert a raw manual study note from reading, grand rounds, lecture, or clinical
discussion into a polished, active-recall-friendly Obsidian note without
changing its clinical meaning or file identity. Optional capability modes may
answer author-marked questions, expand or verify knowledge, distill the review
surface, or add high-value visuals.

## Modes And Arguments

The default is **refactor only**. It reorganizes and clarifies supplied material
but does not import new factual content.

Accept these bare words or their `--flag` forms:

- `answer` resolves explicit author questions into cohesive note prose;
- `expand` adds selected high-value context beyond the draft;
- `verify` checks and corrects factual claims at the appropriate evidence level;
- `distill` creates a concise review layer without discarding useful detail;
- `visualize` adds only visuals that materially improve understanding or recall.

The modes may be combined. Accept an optional target `audience`, `depth`, or
`focus` in natural language or as `key=value`; do not require rigid syntax.

When `answer`, `expand`, `verify`, or `distill` is active, read and follow
`refactor-manual-note-augmentation.md`. Also read
`.agents/shared/commands/rag-routing.md` when `answer`, `expand`, or `verify`
requires factual retrieval. When `visualize` is active, read and follow
`refactor-manual-note-visualize.md`.

When modes are combined, resolve questions, expand selected gaps, verify the
resulting knowledge, distill the final content, and then visualize it. Integrate
all modes into one flowing note; do not create sections or callouts whose only
purpose is to distinguish the author's draft from retrieved or generated work.
Without `answer`, preserve question markers verbatim.

## Authority And Output

- Resolve one source note and read it completely before editing.
- Rewrite that note in place. Preserve its filename and path; never create a
  `(Refactored)`, dated, or versioned copy.
- Preserve every clinical point, uncertainty, and attachment reference. Tighten
  and reorganize prose, but never fabricate facts or silently delete material.
- Do not add an H1. The filename is the title.
- Metadata is native Obsidian frontmatter only: it opens on line 1 and closes
  before the body. Never emit bottom YAML.

If the user supplies pasted text without a destination, ask for the target path
before writing.

## Existing Polished Notes

When new raw material has been appended to an already-refactored note, treat the
existing polished body as a fixed scaffold:

1. Identify only the newly added material.
2. Merge each new point into the most specific existing section.
3. Open a new heading only for a genuinely new subject.
4. Preserve existing prose, diagrams, tables, callouts, embeds, and visual order
   unless the new material directly corrects or extends them.
5. Search the full note before inserting anything and merge with an existing
   point instead of duplicating it.

Widen `summary`, `aliases`, or tags only when the note's actual scope changed.

## Structure

Use a subject-first hierarchy. Let headings emerge from the content's anatomy,
physiology, pathology, evidence, or decision structure. Do not force a global
template or organize around procedures unless the source note is itself
procedural.

Prefer concise prose and bullets. Add an active-recall surface only when it
improves discrimination or application:

- comparison table for confusable entities or approaches;
- spatial table for a true two-dimensional relationship;
- Mermaid for a branching mechanism or decision path;
- inline arrows for a short linear sequence;
- warning callout for a high-risk hazard, dangerous exception, or safety
  threshold;
- tip callout for a durable mnemonic or association.

Do not diagram or tabulate ordinary prose merely for visual variety. Place
tables directly in the note body, not inside callouts or narrow columns.

## Rendering Guardrails

- Quote Mermaid labels containing spaces or punctuation.
- Do not begin Mermaid labels with `1.` or `1)`, which Obsidian may parse as a
  list. Use `1:` or omit numbering.
- Use shortest-path attachment embeds such as `![[Image Name.png|450]]`; do not
  add attachment subfolder prefixes to otherwise unambiguous embeds.
- Preserve source images and add a concise caption only when it clarifies what
  the learner should inspect.
- Use standard Obsidian callouts. Do not add per-note `<style>` blocks. Shared
  presentation belongs in the vault CSS snippets selected through `cssclasses`.

## Native Frontmatter

Preserve valid existing properties and normalize the canonical fields:

```yaml
---
artifact_type: study_material
status: current
domain: anatomy
summary: One-line description of the note's durable scope.
aliases: []
tags: [type/reference, domain/anatomy, source/user]
cssclasses: [table-wide, row-highlight, table-small]
---
```

Use only canonical lowercase domain slugs:

`vascular`, `skull-base`, `tumor`, `spine`, `trauma`,
`neurocritical-care`, `functional`, `pediatric`, `peripheral-nerve`,
`anatomy`, `general`.

Retain a more specific existing `artifact_type` when appropriate. Do not replace
useful lineage or context properties.

## Related Content

Search the vault for directly related notes before writing. Add only verified,
high-value wikilinks, using the shortest unambiguous vault-relative target:

`[[folder/note|Display Title]]`

Do not manufacture a crosslink merely to satisfy a count.

## Final Verification

Before completion:

1. Compare the rewritten note against the original and confirm that no clinical
   point, uncertainty, or embed was lost.
2. Confirm there is one native frontmatter block at the top, no bottom metadata,
   and no H1.
3. Confirm Mermaid, tables, callouts, wikilinks, and image embeds are valid
   Obsidian Markdown.
4. Confirm new material was merged rather than duplicated.
5. When a knowledge capability was used, confirm every imported or corrected
   claim is within the requested scope, calibrated to the target audience, and
   supported at the appropriate evidence level.
6. When `visualize` was used, inspect every new visual at full size, confirm
   embed and attribution validity, and—if a binary changed—refresh the managed
   binary catalog with zero integrity failures.
7. Regenerate the domain index only for agent-indexed folders: Reports,
   Operative Guides, Concepts, Consults, and Reference. Guard-managed folders
   regenerate their own indexes.

Report the edited path and the meaningful structural changes. Do not claim
clinical verification beyond the supplied content unless `answer`, `expand`,
`verify`, or a separate research workflow authorized and supported it. Report
which modes ran, the number of questions resolved, major expansions or
corrections, distilled surfaces, visuals added, unresolved ambiguity, and
evidence classes used. Keep process metadata out of the note itself.
