# Wikilink Injection Command

Inject Obsidian wikilinks into an existing Case Log note using only real vault notes.

## Triggers

- `/wikilink-inject`
- "Inject/add/link wikilinks into my <case/procedure> case log"

## Workflow

1. **Resolve target note**
   - Locate file in `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log/`.
   - If ambiguous, ask one clarification question.

2. **Read source note**
   - Load full content.

3. **Build linkable index**
   - Index notes from `Concepts/`, `Reports/`, `Operative Guides/`, `Study Material/`.
   - Include YAML `aliases` mappings.

4. **Find link candidates**
   - Match case-insensitively against note titles/aliases.
   - Prefer longer/specific phrases.
   - Skip generic single-word matches and already-linked terms.
   - Never edit YAML frontmatter or Agent Commands section.

5. **User approval gate**
   - Present compact table: term -> target note -> folder.
   - Ask: apply all, select subset, or cancel.
   - Do not write before explicit approval.

6. **Rewrite note on approval**
   - Replace with `[[Folder/Note Title|Display Term]]`.
   - Preserve original display text/case.
   - Link first occurrence per section only (avoid over-linking).

7. **Report result**
   - Return count and target file name.

## Constraints

- No ghost links (target file must exist).
- No fabricated matches.
- If nothing linkable is found, report that directly.
