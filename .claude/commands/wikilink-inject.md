# Wikilink Injection

Scans a written Case Log note, identifies concepts/procedures/anatomy that match existing vault notes, and rewrites the note with Obsidian wikilinks inserted inline.

## Trigger Phrases

- `"Inject wikilinks into my [procedure] case log"`
- `"Add wikilinks to the [procedure] case"`
- `"Link up my [procedure] case log"`
- `/wikilink-inject`

## Pipeline

### Step 1 — Locate the Case Log

The user will either name a procedure or provide a path. Resolve to the full path:

```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Case Log/"
```

If ambiguous, ask the user to clarify before proceeding.

### Step 2 — Read the Case Log

Read the full note content using the Read tool.

### Step 3 — Build the Vault Index

Run the following to collect all linkable notes across the relevant folders:

```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md 2>/dev/null
```

For each matched file, strip `.md` and extract the folder-relative path (e.g., `Concepts/Peripheral Nerve Injury Classifications (Seddon & Sunderland)`).

Also read the `aliases:` field from the YAML frontmatter of each candidate file to build an alias → path mapping.

### Step 4 — Identify Linkable Terms

Read the case log and identify every phrase in the note body (not YAML frontmatter, not the Agent Commands section) that matches — exactly or as a substring — a vault note title or alias. Matching rules:

- Case-insensitive
- Match whole words or anatomical phrases (avoid matching single generic words like "approach" or "closure")
- Prefer longer / more specific matches over shorter ones
- Do NOT link terms that are already wikilinked

### Step 5 — Confirm With User

Before writing, present a compact table of proposed links:

| Term Found in Note | Links To | Folder |
|--------------------|----------|--------|
| Peripheral nerve injury | Peripheral Nerve Injury Classifications (Seddon & Sunderland) | Concepts |
| Anterior choroidal artery aneurysm | anterior_choroidal_artery_aneurysms | Reports |

Ask: **"Found [N] linkable terms. Apply all, select specific ones, or cancel?"**

Do not proceed without explicit approval.

### Step 6 — Rewrite the Note

On approval, use the Edit tool to replace each bare term with its wikilink. Format:

```
[[Folder/Note Title|Display Term]]
```

Where `Display Term` is the exact text as it appeared in the note (preserving case).

Apply only the **first occurrence** of each term per section — do not link every repetition.

### Step 7 — Confirm Completion

Report: "Injected [N] wikilinks into `Case Log/<note name>.md`."

## Constraints

- Never modify the YAML frontmatter
- Never modify the Agent Commands section
- Never create wikilinks to notes that do not exist in the vault — no ghost links
- Never modify the note without user approval from Step 5
- If no linkable terms are found, report that clearly rather than making up links
