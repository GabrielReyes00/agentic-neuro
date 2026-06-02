# Study Review

Adaptive Socratic study session. Two invocation modes:

- **Doc-anchored**: review an existing vault document — a `Reports/<file>.md` (narrative with reasoning and citations), a `Study Material/<file>.md` (structured question bank), or a `Brain Dumps/<file>.md` (de-identified service-teaching artifact with explicit provenance limits).
- **Memory-driven custom review**: no document supplied — agent composes the session from the learner's memory state (open errors, weak concepts, stale knowledge, cross-topic gaps, learner-requested focus).

Follow `.agents/shared/commands/learning-session-contract.md` for the module map. In particular, use `memory-operations.md` for memory writes, `memory-retrieval.md` for summary interpretation, `adaptive-teaching-doctrine.md` for teaching behavior, and `anki-session-workflow.md` plus `anki-card-quality.md` for cards.

---

## Invocation Modes

Pick the mode at the start of the session and stay in it. Switching modes mid-session is allowed only at a natural pause and only on explicit learner request.

### Doc-anchored mode (default when a document is named or inferable)

Trigger phrases: "review the EVD Management report", "quiz me on the aSAH study material", "continue our session on [doc]", "drill me on [topic]" *when a matching vault doc exists*.

Use the **Pre-Session Setup** block below as written. The vault document is the curriculum boundary.

### Memory-driven custom review

Trigger phrases: "what should I review", "build me a custom session", "drill my weak spots", "go after my open errors", "review my recent gaps", "session based on what I've been getting wrong", "board-style cases on my weakest domain", "intern-style firefight on my open errors". Also: any invocation with no document named and no obvious topic the learner wants to anchor on.

Use the **Memory-Driven Setup** block below instead of the doc-anchored Pre-Session Setup. Persona-shaped sessions (intern-style ICU firefight, oral-board staged cases, ward consult drills) are achievable inside this mode — the agent adjusts question shape, tone, and reveal cadence based on what the learner asks for. There is no separate skill for these personas; this is the one place that runs them.

The reference topic bank at `Reference/Oral Boards Topic Bank.md` in the vault is a curated pool for board-style case selection when memory state alone doesn't pin a topic.

---

## Memory-Driven Setup

When invoked without a document, compose the session from memory state.

### Step 0: Global memory summary

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py startup-recall --global
```

Read the global picture: active `must_retest` cards, due claims, session handoffs, recent repairs, curated cross-session summaries, learner graph signals, model surfaces, and `retrieval_guidance`.

Global startup recall is intentionally compact and returns `startup_recall.ready_to_teach = false`. Read `startup_recall.deferred_high_signal`, then use the per-candidate topic summaries below to load complete high-signal context only for the topics selected for this session. Do not bulk-expand the global envelope or begin teaching directly from it.

If Gabriel names an upcoming case, rotation, service context, or board persona, add `--context "<brief context>"` to summary commands. Use `context_focus` and the reviewed `context_graph_focus` paths during planning when present: they shape thematic order, while urgent safety-critical due claims remain gatekeepers. Verify that a graph path is clinically applicable before using it.

### Step 1: Per-candidate summary

For each candidate topic the status output surfaces (top weak concepts, recent open errors, stale-but-PGY-relevant areas, anything the learner named):

```bash
python3 src/study_memory.py startup-recall --topic "<candidate topic>"
```

Read each summary output per `.agents/shared/commands/memory-retrieval.md`. Note session handoff, active retest cards, recent repairs, and scaffold premises per topic.

### Step 2: Compose the review queue

Order the queue by clinical/educational priority, drawing from:

- **Open errors**: concepts with `correct=0` in recent sessions that have not been retested. Highest priority — these are unfixed misconceptions.
- **Weak concepts**: concepts missed multiple times across sessions with low mastery indicators. If a prior teaching approach failed on the same concept, change strategies.
- **Stale knowledge**: draw only from `due_claims` in the memory summary; these are previously-confirmed conceptual claims whose retrievability has decayed. Schedule changed-frame retention checks, especially for PGY-relevant or safety-critical items.
- **Cross-topic gaps**: concepts surfaced by scouting in one session but never followed up under their own topic.
- **Frontier/blind spots**: untested ACGME catalog regions that are adjacent to mastered material or high-yield for PGY-1 readiness.
- **Shadow interests**: quick answers or generated artifacts that signal possible curiosity or uncertainty; probe lightly before assigning learner state.
- **Learner-requested focus**: if the user names a domain, scenario, persona, or filter ("vascular weak spots", "ICU management", "intern-style firefight on neurotrauma"), filter and shape the queue accordingly.

### Step 3: Present and confirm

Show the proposed composition to the learner in 5–10 lines: what concepts will be retested, what gaps will be probed, why each was selected (open error / stale / requested focus), persona/style if any, and approximate scope. Confirm before executing.

### Step 4: Execute

Run the session under the shared learning modules: cognitive friction and teaching moves from `adaptive-teaching-doctrine.md`, `log-answer` and `end-session` from `memory-operations.md`, Anki enqueue/flush from `anki-session-workflow.md`, and card quality from `anki-card-quality.md`. The teaching loop is identical to doc-anchored mode; only the curriculum source differs.

No vault artifact is written. The memory layer is the durable record.

---

## Pre-Session Setup

Use this block for doc-anchored mode.

### Step 0: Identify the document

Derive the slug from the user's request (e.g., "EVD Management" from "let's review EVD management"). If ambiguous, ask.

Check `Reports/<slug>.md`, `Study Material/<slug>.md`, and `Brain Dumps/<slug>.md`. If multiple exist, follow the user's named source. Otherwise default to the Report for new or deep-dive topics, Study Material for systematic question-bank review, and Brain Dumps when the request refers to teaching learned on service or an encountered correction. If none exists, invoke `/generate-report`, `/study-material`, or `/brain-dump` based on the user's intent.

### Step 1: Read the document

Read the full vault file identified in Step 0. This is your curriculum — you cannot teach from a document you haven't read. Note the document's structure, key sections, and density of material so your question design can cover it systematically.

If the document contains `## Mastery Objectives`, extract them only after reading the full file. Treat them as a coverage checksum for the session plan, not as a substitute curriculum. The questions must still be grounded in the document body and traceable to its actual content.

### Step 2: Retrieve prior memory context (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py startup-recall --topic "<doc topic>" --doc "<folder>/<file>.md"
```

Follow the pre-session verification protocol from `memory-operations.md` before proceeding. `SESSION_TS` is set per `memory-operations.md` at the first learner-facing question.

Use the memory summary output to build your teaching plan per `memory-retrieval.md`. If this is a returning session, open with a one-sentence recap and move directly to questioning — do not re-explain known material. If this is a new topic, start at the beginning of the document.

**Requested-Document Priority**: The requested document is the primary curriculum. Related-topic context and prior memory should inform your question design and probe strategy, but never displace forward progress through the document's material.

### Step 3: Contextual-frontier validation (silent)

Read `planning_brief.contextual_frontier`. It is a bounded candidate set, not a teaching mandate. Candidates may come from learner graph edges, reviewed reference-graph paths, confirmed report-local scaffolds, or cautious cross-topic learner-state overlap.

Validate candidates with your clinical judgment before teaching. Accept only 1-3 candidates that are:

- **Clinically central**: the candidate provides a prerequisite, discriminator, mechanism, or transfer principle that materially affects understanding of the requested content.
- **Scope-compatible**: the probe advances the requested document rather than diverting into a neighboring curriculum.
- **Learner-relevant**: existing evidence suggests a missing foundation, unstable repair, recurring false rule, or useful scaffold for a harder transfer question.

Reject tangential adjacency, generic lexical overlap, and interesting-but-noncentral topics. Distill the accepted and rejected candidate ids into a brief internal teaching note (not shown to the learner): what foundations exist, what gaps could undermine today's material, which 1-2 concepts are worth weaving into the session, and why the first question is the highest-yield opening.

If a validated candidate remains ambiguous, inspect the full summary or run topic-scoped expansion for that canonical related topic. Do not run blind phrase-based `summary --topic` scouting commands: concepts inside an umbrella report topic are not guaranteed to exist as independent topic identities.

When you probe a related concept during the session, log it under the related topic's canonical name, not the primary session topic:

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<related topic>" --concept "<concept>" \
  --question "..." --answer "..." --correct <0|1|2> \
  --skill "study-review" \
  --strict-telemetry --answer-mode "<mode>" \
  --confidence-observed "<observation>" --teaching-move "<move>" \
  [--priority "urgent|high|medium|low"] \
  [--match-claim-state-id <id>] [--new-claim] \
  [--repairs-claim-state-ids "id,id,..."]
```

This builds the cross-topic knowledge graph naturally: a future session on the related topic will find this data, and a future session on the primary topic will find it again through contextual-frontier retrieval.

---

## Session Quality Standard

Regardless of document type or teaching approach, every study-review session must meet these outcomes:

1. **The session tests, it does not lecture.** The majority of session time is spent on the learner answering questions, not the agent explaining material. Teaching happens through corrections and follow-ups after the learner commits, not before.

2. **Questions span multiple mastery operations within the session.** A session that stays at pure recall is too shallow. Within a single session, the agent should probe 2-3 of the operations in `adaptive-teaching-doctrine.md` as performance supports: discrimination, quantification, sequencing, mechanistic explanation, and transfer. The mix is driven by real-time performance and prior memory, not by a fixed template.

3. **Prior errors are addressed before new territory.** Open errors and persistent gaps from recall and scouting are the highest-value targets. A session that ignores known misconceptions to cover new ground is leaving dangerous gaps unfixed.

4. **Every exchange produces a durable, specific memory entry.** No question should be asked without a corresponding `log-answer` call that captures the exact concept tested, the learner's performance, and (for misses) the specific misconception and correction. These entries are the substrate for all future sessions.

5. **The session ends with a specific, actionable handoff.** The `next-strategy` must name concepts, error types, and approaches so a future agent — with no context from this session beyond what's in the database — can pick up exactly where this session left off.

### Document-Type Awareness

The source document shapes how the agent designs questions, not what the session should accomplish.

**Reports** provide narrative context with reasoning, evidence, and clinical integration. The agent should use this rich context to design questions that test understanding of mechanisms, discriminators, management logic, and integration across concepts. The agent designs its own questions from the material rather than following a pre-built list — this allows questions to be responsive to the learner's exact knowledge state and to probe the reasoning and connections that the report's narrative makes explicit.

**Study Material** provides a structured question inventory with atomic facts and pre-designed questions organized by teaching unit. The agent should use the question bank as a coverage scaffold — ensuring systematic testing across all sections — while adapting questions to the learner's current state rather than reading them verbatim. Pre-designed questions are starting points, not scripts: rephrase, combine, contextualize, or replace them based on what recall and real-time performance reveal about where the learner needs to be pushed.

**Brain Dumps** provide compact, de-identified teaching captured from clinical experience. The agent should test whether the learner can apply the operational edge and explain its mechanism while preserving its provenance tier. Points labelled `Service teaching - locally confirm` must be tested as local practice knowledge or clarification targets, not recast as universal standards.

In both cases, the document is the curriculum boundary — the agent's questions should be grounded in and traceable to the document's content, with related-topic probes as targeted supplements rather than tangents.

---

## Session Execution

### Question Design

Use the document's structure as a scaffold, not a script. `adaptive-teaching-doctrine.md` defines what questions should achieve: every question has a purpose, targets a specific mastery operation, and prioritizes the edge of the learner's competence.

Your recall output, scouting notes, and medical knowledge should drive question selection. Prior errors and gaps from this and related topics are high-priority targets. New document sections should be covered. Known concepts should be used as building blocks for deeper questions, not re-drilled.

Ask one question per turn, then stop. Start with active recall or a clinical decision — never lecture before the learner answers.

### Post-Answer Flow

After each answer: grade it, then choose the next teaching move using `adaptive-teaching-doctrine.md`. Cognitive friction, progressive reveal, minimum effective explanation, and correct-but-shallow-as-partial govern how much to reveal and when. Keep responses concise — the goal is to spend session time on the learner's thinking, not the agent's explanations.

### Adaptive Pacing

Let real-time performance compress or expand time-on-concept, but do not create a second local decision tree here. Use `adaptive-teaching-doctrine.md` for wrong, partial, shallow-correct, repaired-miss, and repeated-error behavior.

The goal is to spend the maximum proportion of session time at the learner's frontier — the boundary between what they can and cannot do. Questions below the frontier waste time; questions far above it produce noise instead of learning. Strong performance should move quickly toward harder transfer or uncovered material; unrepaired misses should narrow the session until the false rule is removed.

### Session Length Checkpoint

After 5-6 evaluated exchanges, pause and ask the learner: "Want to wrap up here as a quick review, or keep going?" This is not a formality — it determines the session's trajectory:

- **End here**: Proceed immediately to Session End (synthesis challenge, end-session, Anki flush). This gives the learner a lightweight probe of the topic with full memory persistence.
- **Keep going**: Take this as a signal to increase depth and intensity. Escalate to harder application, transfer, and complication questions. Push toward the learner's frontier aggressively. Continue until the learner says they are done — do not ask again or impose a cap.

### Scope of Probes

Probes beyond the primary document should stay clinically adjacent and management-relevant to the current topic. Use your judgment about what's connected — the validated contextual frontier gives you the map of where knowledge and gaps exist in adjacent areas.

---

## Memory Logging (silent, after every evaluated answer)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<topic>" \
  --concept "<specific concept tested>" \
  --question "<your question, verbatim>" \
  --answer "<Gabriel's answer, verbatim>" \
  --correct <0|1|2> \
  --doc "<folder>/<slug>.md" \
  --skill "study-review" \
  --strict-telemetry \
  --answer-mode "<unaided|prompted|after_hint|after_teaching|self_corrected>" \
  --confidence-observed "<low|medium|high|hesitant|fluent>" \
  --teaching-move "<initial_probe|contrastive_drill|mechanism_first|order_set|premortem|visual_probe|changed_frame_retest|other>" \
  [--correction "<corrected fact>"] \
  [--error-type "<type>"] \
  [--misconception "<specific wrong belief>"] \
  [--tested-claim "<what was tested>"] \
  [--learner-claim "<compact committed answer>"] \
  [--missing-edge "<missing discriminator/threshold/step>"] \
  [--corrected-rule "<replacement rule>"] \
  [--clinical-consequence "<why it matters>"] \
  [--retest-prompt-shape "<future probe shape>"] \
  [--learning-operation "<recall|discrimination|quantification|sequencing|mechanism|transfer>"] \
  [--priority "urgent|high|medium|low"] \
  [--match-claim-state-id <id>] [--new-claim] \
  [--repairs-claim-state-ids "id,id,..."]
```

**Topic assignment**: use the primary doc topic for concepts native to the document. When probing a related concept surfaced through scouting, use the related topic's canonical name instead — this ensures the exchange is discoverable in future sessions on either topic.

When a question is designed from a `must_retest` or `recent_repair` card, pass that card's `claim_state_id` via `--match-claim-state-id`. When an answer repairs other open claims, pass only those explicitly repaired ids via `--repairs-claim-state-ids`. Use `--new-claim` when similar wording is testing a distinct claim.

Correctness: `2` = correct | `1` = partial (right direction, missing key detail) | `0` = wrong or misconception

Follow `.agents/shared/commands/anki-session-workflow.md` after each `log-answer` call. Use `.agents/shared/commands/anki-card-quality.md` when drafting and validating cards.

If `--doc` begins with `Brain Dumps/`, route all cards from that doc-anchored session to `Neurosurgery::Brain Dumps` and tag them `brain-dump` in addition to the usual review/error tags.

---

## Session End

When the learner requests to end the session, the session length checkpoint triggers an end, or the document's key material has been substantially covered:

1. **Synthesis challenge**: Before summarizing, ask the learner to consolidate: "What are the 2-3 most important things from this session, and one thing you're still uncertain about?" This is a teaching move, not a formality — it forces active consolidation, surfaces hidden uncertainty the session may have missed, and gives you one final data point about what actually stuck versus what was performed in-the-moment. Log the response via `log-answer` with concept "session synthesis self-assessment". If the learner's self-identified uncertainty reveals a gap you didn't catch, note it in the next-strategy.

2. **Summarize**: what was retested, what new material was covered, what gaps remain, one learner-pattern insight. Compare your assessment against the learner's synthesis — discrepancies (learner thinks they know X but you scored it partial, or learner flags uncertainty on Y that you marked correct) are the most valuable signal for the next session.

3. **Run end-session** (silent):
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence recap>" \
  --next-strategy "<specific directive for next session>" \
  --json
```
Read the JSON output silently. If `curation.recommended` is `true`, follow `.agents/shared/commands/memory-curation.md` after Anki flush.

`--next-strategy` must be actionable: name the concept, the error type, and the teaching move.
GOOD: "Retest EVD waveform troubleshooting with a new bedside vignette — partial on previous attempt. Then advance to aSAH grading scale distinctions."
BAD: "Continue reviewing EVD management."

4. Follow the post-session integrity verification protocol from `memory-operations.md` before proceeding to Anki flush.

5. Follow `.agents/shared/commands/anki-session-workflow.md` for queue validation and flush.

6. Clean up `data/Sessions/` temps.
