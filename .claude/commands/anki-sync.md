---
name: anki_sync
description: Seven-step pipeline that extracts Anki flashcards from the current session transcript — deduplicates claims, runs novelty filtering against existing cards, drafts validated cloze/QA cards, and syncs to Anki via AnkiConnect. Always invoke this skill when the user wants to create flashcards or save to Anki — phrases like "save to Anki", "make flashcards", "make cards", "create Anki cards", "sync to Anki", "add this to my deck", "save for later study", or "turn this into cards". Do not attempt to answer inline for these requests.
---

# Anki Sync Command

This command converts the current Claude Code session transcript into high-yield Anki flashcards. You (the agent) handle all LLM reasoning natively. Python is only invoked for local database and AnkiConnect operations.

> **CRITICAL: Working Directory.** ALL shell commands (mkdir, python3, etc.) in this command MUST use absolute paths or be run with `cd /Users/gabrielreyes/agentic-neuro &&` prefixed to the command. The CLI may be running from `~`, not from `~/agentic-neuro/`.

## Step 0: Write the Session Transcript

Before anything else, you MUST capture the full verbatim conversation from this session and write it to disk. This is YOUR responsibility as the agent — the user should not have to do this manually.

1. Compile the complete verbatim transcript of this session (all user messages and your responses, preserving the educational content).
2. Ensure the output directory exists:
   ```
   mkdir -p /Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs
   ```
3. Write the transcript to disk using a **Shell tool with a quiet redirect** — do NOT use WriteFile for this step, as it will dump the entire transcript into the terminal UI:
   ```
   cat > /Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt << 'TRANSCRIPT_EOF'
   [paste full transcript here]
   TRANSCRIPT_EOF
   ```
4. **Do NOT echo** transcript content back to the terminal during this write.
5. **Post-process (Text Wrapping):** To prevent horizontal truncation during Step 1, run this Python one-liner to wrap the transcript to a maximum width of 150 characters:
   ```
   python3 -c "import textwrap; p = '/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt'; content = open(p).read(); wrapped = '\n'.join(['\n'.join(textwrap.wrap(line, width=150, break_long_words=False, replace_whitespace=False)) if len(line) > 150 else line for line in content.split('\n')]); open(p, 'w').write(wrapped)"
   ```

## Step 1: Read & Validate Transcript

Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt`.
- If the file is missing or contains fewer than 200 characters, **stop** and inform the user: "The session transcript is too short to extract meaningful cards."

## Step 2: Resolve Subdeck

Ask the user (output this directly to the terminal — do not use a tool):

> "Would you like to add these cards to an **existing subdeck** or **create a new one**?
> - **Existing** → paste the full deck path (e.g., `Agentic Neurosurgery Review::Intern Bootcamp`)
> - **New** → I'll generate an appropriate subdeck name; just confirm the root deck (default: `Agentic Neurosurgery Review`)"

Wait for the user's reply, then resolve the full deck path:

**If the user provides an existing deck path** (contains `::`):
- Use the full path as-is for `deck`
- Extract the subdeck label (last segment after `::`) as `topic`

**If the user requests a new subdeck:**
- Auto-generate a 1–3 word subdeck title from the session content (acronyms encouraged, e.g., "ICP Physiology", "SAH Management", "ETV Complications")
- No punctuation except spaces/hyphens
- Use the root deck the user specified, or `Agentic Neurosurgery Review` if none given
- Full path: `<root deck>::<generated title>`

Write to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/current_topic.json`:
```json
{"topic": "<subdeck label>", "deck": "<full deck path>"}
```

Example for existing: `{"topic": "Intern Bootcamp", "deck": "Agentic Neurosurgery Review::Intern Bootcamp"}`
Example for new: `{"topic": "ICP Physiology", "deck": "Agentic Neurosurgery Review::ICP Physiology"}`

## Steps 3–4: Claim Extraction & Novelty Filtering (Subagent)

Spawn a `general-purpose` subagent with the following prompt:

> You are extracting factual claims from a neurosurgery study session transcript for Anki flashcard creation.
>
> **Step 1**: Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/current_session_verbatim.txt`.
>
> **Step 2**: Extract atomic factual claims as Subject-Verb-Object (SVO) triples.
> - Merge similar or overlapping facts — zero duplicates.
> - **Aggressively filter fluff:** discard conversational filler, opinions, non-technical observations, and any claim that does not convey a concrete medical/technical fact.
> - Maximize **context coverage** — capture every distinct technical concept without redundancy.
> - Each claim must be a standalone `claim_text` understandable without surrounding context.
> - `claim_id` format: `C###` (e.g., C001, C002).
>
> Write the result as strict JSON to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/current_claims.json`:
> ```json
> {"claims": [{"claim_id": "C001", "subject": "...", "verb": "...", "object": "...", "claim_text": "..."}]}
> ```
>
> **Step 3**: Run novelty filtering:
> ```
> cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py filter_novelty
> ```
>
> **Step 4**: Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/novel_claims.json` and count the novel claims.
>
> **Return** to the main agent: `{total_claims: N, novel_claims: M, topic: "brief topic summary"}`

After the subagent returns:
- If `novel_claims` is 0, **stop** and tell the user: "No novel facts found in this session; all concepts are already in the Anki database."
- Otherwise, report the counts briefly and proceed.

## Steps 5–6: Card Drafting & Validation (Subagent)

Spawn a `general-purpose` subagent with the following prompt:

> You are drafting and validating Anki flashcards from novel neurosurgery claims.
>
> **Step 1**: Read `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/novel_claims.json`.
>
> **Step 2**: For each novel claim, draft exactly ONE Anki card.
>
> **Cloze vs QA Decision Rules:**
> - Use `cloze` for single factual associations: drug names/doses/mechanisms, anatomical landmarks, numerical thresholds, named syndromes, definitions — any fact with ONE specific answer in a known sentence structure. Format: exactly one `{{c1::...}}` deletion targeting the most critical discriminative information.
> - Use `qa` for reasoning or multi-part answers: pathophysiology explanations, differential diagnosis reasoning, procedural steps, comparisons. Provide concise `front` (question) and `back` (answer).
>
> **CRITICAL JSON RULE:** All text fields MUST be valid JSON strings. Newlines within field values MUST be escaped as `\n`, NOT literal newlines.
>
> Write draft cards to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/draft_cards.json`:
> ```json
> {"cards": [{"claim_id": "C001", "card_type": "cloze", "cloze_text": "...", "answer_text": "...", "front": "", "back": ""}]}
> ```
>
> **Step 3: Blind Validation** — For EACH card:
> 1. Hide the answer (cloze deletion target or QA `back`).
> 2. Read ONLY the visible prompt/front.
> 3. Ask: "Is there enough specific, discriminative context for someone to guess the EXACT hidden answer and nothing else?"
> 4. If too vague, refine by adding explicit clinical constraints until only one correct answer is possible.
>    - Example: ❌ `"The treatment for SAH is {{c1::nimodipine}}"` → ✅ `"The calcium channel blocker used for vasospasm prophylaxis after SAH is {{c1::nimodipine}}"`
>
> Write validated cards to `/Users/gabrielreyes/agentic-neuro/data/Sessions/anki_sync_runs/final_cards.json` (same schema).
>
> **Return** to the main agent: `{cards_drafted: N, cards_validated: N, cards_refined: N}`

After the subagent returns, report the counts briefly and proceed to Step 7.

## Step 7: Dispatch to Anki (Python Handoff)

Run the following command:
```
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/anki_sync_cli.py dispatch
```
This pushes the cards to AnkiConnect (localhost:8765) and persists the successful claims into the Anki memory ChromaDB (`data/chromadb_store_anki_memory`) so future runs will filter them as duplicates.

**If the dispatch command fails** with a connection error, inform the user: "AnkiConnect is not running. Please open the Anki desktop app and ensure AnkiConnect is installed, then try again."

After successful dispatch, report the final counts to the user (e.g., "Created 12 cards, 0 duplicates, 0 failures in deck Neuro RAG::SAH Management").

**Note:** The intermediate JSON files (`current_topic.json`, `current_claims.json`, `novel_claims.json`, `draft_cards.json`, `final_cards.json`) are automatically overwritten on each run of this command, so no manual cleanup is needed. They are retained between runs for debugging and inspection.
