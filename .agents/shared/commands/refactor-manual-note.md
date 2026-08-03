# Refactor Manual Note

Convert a raw manual study note from grand rounds, lecture, or clinical
discussion into a polished, active-recall-friendly Obsidian note without
changing its clinical meaning or file identity.

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
5. Regenerate the domain index only for agent-indexed folders: Reports,
   Operative Guides, Concepts, Consults, and Reference. Guard-managed folders
   regenerate their own indexes.

Report the edited path and the meaningful structural changes. Do not claim
clinical verification beyond the supplied content unless a separate research
workflow was requested.
