# Wikilink Injection

Use when the user asks to add Obsidian wikilinks to an existing case log.

## Workflow

1. Resolve the target note in `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log/`. Ask one clarification if ambiguous.
2. Read the full note.
3. Build an index from `Concepts/`, `Reports/`, `Operative Guides/`, and `Study Material/`, including YAML aliases.
4. Find link candidates:
   - case-insensitive title or alias match
   - prefer longer and more specific phrases
   - skip generic single words
   - skip already-linked terms
   - never edit YAML frontmatter or the Agent Commands section
5. Present a compact approval table: term, target note, folder.
6. Write only after explicit approval.
7. Replace with `[[Folder/Note Title|Display Term]]`, preserving display text and case.
8. Link first occurrence per section only.
9. Report count and target file.

No ghost links, no fabricated matches, and no write if nothing linkable is found.
