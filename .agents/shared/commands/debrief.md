# Debrief

Chief-resident-style tutoring pass triggered after a new patient encounter or workup. The goal is 80% of intern-essential knowledge in 20% of the time, surfacing unknown unknowns so Gabriel is faster at orders, imaging, consults, and management the next time this pathology appears.

Follow `.agents/shared/commands/learning-session-contract.md` for all memory bookkeeping.

## When to use

- Gabriel just saw a patient or opened a consult with a pathology he cannot manage fluently yet
- Explicit triggers: `/debrief`, "debrief me on", "new patient I saw was", "tutor me on this consult", "quick chief sit-down on"
- Not for routine clinical questions — route those to Tier 3 direct answer or `/rag-workflow`

## Hard rules

1. Freeform input is expected. Do not ask for a template. Parse pathology and user-known context from a single dump.
2. RAG is the last resort. Use KG, vault, and internal knowledge first. Only call `lance_retriever.py compare` for slots the assembler flagged `rag_needed=true` AND the user has not declined RAG.
3. Never emit an H1 in the vault file. Filename is the title.
4. YAML metadata at the bottom, always.
5. If a similar `Debriefs/*.md` exists above threshold, append a dated encounter section rather than creating a duplicate.
6. Every committed learner answer goes through `memory_orchestrator.py --quiet record-answer`. Passive teaching goes through `record-passive`.
7. All shell commands are background bookkeeping — never print them, their stdout, or raw JSON to the learner-facing transcript.

## CLI calling conventions (read before calling any script)

`debrief_context_assembler.py`:
- Always pass `--pathology "<phrase>"` as a named flag, not a positional argument.
- Always pass `--output data/Sessions/debrief_context.json --quiet` so the assembler writes silently.
- Read the bundle from the file, not from stdout.

`debrief_writer.py`:
- Uses a flat `--action` flag — NOT subcommands. Always pass `--action create|merge|upsert-index` before other flags.
- Body content uses `--body`. Do NOT use `--content` (alias accepted for robustness, but `--body` is canonical).
- Pass `--quiet` to suppress the JSON success line from terminal output.

## Phase 0: Intake

Ask for exactly one thing:

> What pathology or encounter do you want to debrief? Dump whatever context you already have — patient snippet, what you tried, what's unclear, what labs/imaging/orders you're unsure about.

Parse the reply silently into:
- `pathology` — short phrase naming the pathology or procedure
- `user_context` — everything else the user typed, verbatim

If the pathology is ambiguous (single word, no modifier), ask one clarifying question. Otherwise proceed silently.

## Phase 1: Silent context assembly

Run silently — no output to the chat transcript:

```bash
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)

python3 src/debrief_context_assembler.py \
  --pathology "<pathology>" \
  --context "<user_context>" \
  --output data/Sessions/debrief_context.json \
  --quiet 2>/dev/null

python3 src/memory_orchestrator.py --quiet session \
  --session-ts "$SESSION_TS" --skill "debrief" --topic "<pathology>" \
  --enabled --scope study_session 2>/dev/null

python3 src/knowledge_graph.py last_session_narrative \
  --skill "debrief" --topic "<pathology>" \
  > data/Sessions/debrief_last_narrative.json 2>/dev/null
```

Read `data/Sessions/debrief_context.json`. It contains:
- `kg_context` — learner context for the pathology
- `blocking_gaps` — prerequisite concepts not yet mastered
- `unknown_unknowns` — adjacent curriculum blind spots (save for Phase 5)
- `vault_hits` — Reports, Study Material, Operative Guides, Concepts, Review Sessions, Debriefs that match
- `merge_target` — most similar existing debrief (or null)
- `scaffold_slots` — per-slot `rag_needed` flag
- `rag_needed_slots` — sorted list of slots lacking KG/vault coverage

If `merge_target` is non-null, tell the user once:

> I have an existing debrief on [[Debriefs/{target_title}|{target_title}]] (similarity {score}). I'll append this encounter there — let me know if you want a fresh file instead.

Wait for confirmation or override. Default = merge.

## Phase 2: Targeted RAG (conditional)

For each slot in `rag_needed_slots`, run one scoped RAG query silently. If the slot list is empty, skip entirely. If the user says "skip RAG", skip.

```bash
python3 src/lance_retriever.py compare "<slot-scoped query>" \
  --no-frontier --output "/tmp/debrief_rag_<slot>.md" 2>/dev/null
```

Slot query examples:
- imaging → `"<pathology> preoperative imaging protocol MRI CT"`
- labs → `"<pathology> preoperative labs coagulation workup"`
- intraop_concepts → `"<pathology> operative anatomy key steps"`
- postop_course → `"<pathology> postoperative monitoring expected course"`

## Phase 3: Chief-resident teaching pass

Role: senior chief resident doing a targeted sit-down. Direct, PGY-1-aware, efficient. Do not lecture wall-to-wall — interleave one Socratic check after each substantive slot and apply the Cognitive Friction Protocol from the shared contract.

Walk the ten scaffold slots, skipping any the user clearly covered in their intake:

1. **Pathology one-liner** — core mechanism that matters for management
2. **Mechanism** — the pathophys that explains the next three slots
3. **Imaging** — what to order, why, expected findings, alternatives
4. **Labs** — baseline + pathology-specific + preop requirements
5. **Consults** — who, when, what question to ask them
6. **Preop course** — clearance, meds to hold/continue, positioning implications
7. **Intraop concepts** — anatomic and technical points the intern needs to comprehend the surgery (wikilink existing Operative Guides when present)
8. **Postop course** — orders, monitoring, expected trajectory
9. **Red flags** — deterioration thresholds that require escalation
10. **Intern priorities** — the must-know/must-do list for this pathology

### Per-turn memory and Anki logging

**`record-answer` auto-enqueues Anki candidates.** Every call below writes the exchange to the learning memory AND appends a candidate to `data/Sessions/anki_queue.jsonl`. No separate Anki call is needed per turn — the queue is flushed by the heartbeat (every ~3 turns) and finally by the universal post-session hook.

Log each committed answer silently:

```bash
python3 src/memory_orchestrator.py --quiet record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "debrief" \
  --topic "<pathology>" --concept "<slot concept>" \
  --question "<question>" --answer "<answer>" --correct <0|1|2> \
  [--correction ...] [--error-type ...] [--error-process ...] \
  [--misconception ...] [--root-cause ...] [--remediation ...] \
  [--teaching-approach "chief_tutorial_tour"] [--depth 2] [--domain "<domain>"] \
  2>/dev/null
```

Log passive teaching silently (no Anki enqueue — passive exposure only):

```bash
python3 src/memory_orchestrator.py --quiet record-passive \
  --session-ts "$SESSION_TS" --turn <N> --skill "debrief" \
  --topic "<pathology>" --concept "<slot concept>" \
  --content "<what was taught>" 2>/dev/null
```

### Heartbeat every ~3 turns (triggers Anki flush)

After approximately every 3 learner-facing turns, run a heartbeat checkpoint silently. This flushes the Anki queue (synthesizing queued candidates into cards via Gemini), checkpoints the learning state, and protects against mid-session loss.

```bash
./src/heartbeat.sh --session-mode \
  --skill "debrief" \
  --slug "<pathology-slug>" \
  --topics "<pathology>" \
  --depth 2 \
  --domain "<domain>" \
  --understood "<comma-separated concepts answered correctly so far>" \
  --gaps "<comma-separated concepts missed so far>" \
  --turn-num <N> \
  --status "in-progress" \
  2>/dev/null
```

The heartbeat runs `flush-anki-queue --min-queue 3` internally — no separate flush call needed mid-session.

## Phase 4: Blocking-gap resolution

If `blocking_gaps` is non-empty, briefly teach and retest each prerequisite that directly blocks the pathology. Keep it under two turns per gap. Log each as `record-answer`.

## Phase 5: Unknown-unknowns surfacing

At session end, present `unknown_unknowns` as a short list:

> Next time you see this pathology, a chief would also ask about: {topic_1}, {topic_2}, {topic_3}. Want to drill one now or save for next time?

Do not expand these unless requested. If the user drills one, log it with `record-transfer`.

## Phase 6: Vault write

Assemble the debrief body from the material taught in Phases 3–5. Sections:

```
## Pathology One-Liner

## Mechanism

## Imaging

## Labs

## Consults

## Preop Course

## Intraop Concepts

## Postop Course

## Red Flags

## Intern Priorities

## Unknown Unknowns — Next Chief Quiz

## Related in This Vault
- wikilinks from vault_hits (reports, study material, operative guides, concepts)
```

No H1. YAML at bottom. Before writing, save the rendered body to `data/Sessions/debrief_<slug>_artifact.md` and run the Final Artifact Guard draft check. This catches missing scaffold sections before the note is persisted:

```bash
python3 src/learning_artifact_guard.py check-draft \
  --artifact-type "debrief" \
  --draft "data/Sessions/debrief_<slug>_artifact.md" \
  --min-words 300
```

Use `debrief_writer.py --action create|merge` only after the draft passes. Then validate the final new or merged target:

```bash
python3 src/learning_artifact_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Debriefs/<Pathology Title>.md" \
  --artifact-type "debrief" \
  --min-words 300
```

Run all write commands silently:

**New file** (`merge_target` null or user declined merge):

```bash
python3 src/debrief_writer.py \
  --action create \
  --pathology "<pathology>" \
  --body "<rendered markdown body>" \
  --domain "<domain>" \
  --key-terms "<comma,separated,terms>" \
  --summary "<one-line summary>" \
  --quiet 2>/dev/null
```

**Merge into existing** (`merge_target` non-null):

```bash
python3 src/debrief_writer.py \
  --action merge \
  --target "<merge_target.path>" \
  --body "<rendered markdown body>" \
  --label "<short encounter label>" \
  --key-terms "<comma,separated,new terms>" \
  --summary "<updated one-line summary>" \
  --quiet 2>/dev/null
```

Upsert the index silently:

```bash
python3 src/debrief_writer.py \
  --action upsert-index \
  --title "<title>" --pathology "<pathology>" --domain "<domain>" \
  --last-encounter "$(date -u +%Y-%m-%d)" \
  --encounters <N> --summary "<summary>" \
  --quiet 2>/dev/null
```

## Phase 7: Close the loop

Run all closing hooks silently in this order:

```bash
# 1. Final heartbeat — flushes remaining Anki queue candidates (min-queue 1 at complete)
./src/heartbeat.sh --session-mode \
  --skill "debrief" \
  --slug "<pathology-slug>" \
  --topics "<pathology>" \
  --depth 2 --domain "<domain>" \
  --understood "<all understood concepts>" \
  --gaps "<all missed concepts>" \
  --turn-num <N> \
  --status "complete" \
  --narrative-summary "<one-sentence summary of what was taught>" \
  --next-strategy "<concrete action for next debrief on this pathology>" \
  2>/dev/null

# 2. Log session narrative
python3 src/knowledge_graph.py log_session_narrative \
  --skill "debrief" --topics "<pathology>" \
  --summary "<what was taught>" \
  --strategy "<concrete next action for future debriefs>" \
  --turns <N> 2>/dev/null

# 3. Finish session and capture summary text
FINISH_TEXT=$(python3 src/memory_orchestrator.py finish-session \
  --session-ts "$SESSION_TS" --skill "debrief" --topic "<pathology>" \
  --repair-fragments --mode apply --text 2>/dev/null)

# 4. Universal post-session hook (final Anki queue drain, KG sync, vault rebuild)
python3 src/universal_post_session_hook.py \
  --skill "debrief" --topics "<pathology>" \
  --vault-writes "<path to debrief file>" \
  --report-out /tmp/post_session_hook_report.json 2>/dev/null
```

Cleanup silently:

```bash
rm -f data/Sessions/debrief_context.json \
      data/Sessions/debrief_last_narrative.json \
      /tmp/debrief_rag_*.md \
      /tmp/post_session_hook_report.json 2>/dev/null
```

## Final response to user

Surface only:
- One-line summary of what was covered
- Vault file written (wikilink)
- Unknown-unknowns list if not already drilled
- `$FINISH_TEXT` quality summary if non-empty and meaningful
- Any memory-quality warnings (one line max)

Do not print shell commands, JSON payloads, file paths, or scaffold structure.
