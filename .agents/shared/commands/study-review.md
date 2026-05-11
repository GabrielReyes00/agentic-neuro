# Study Review

Doc-anchored Socratic session from an existing vault document — either a `Reports/<file>.md` (narrative with reasoning and citations) or a `Study Material/<file>.md` (structured question bank with atomic facts).

Follow `.agents/shared/commands/learning-session-contract.md` for all shared pedagogy and memory operations.

---

## Pre-Session Setup

### Step 0: Identify the document

Derive the slug from the user's request (e.g., "EVD Management" from "let's review EVD management"). If ambiguous, ask.

Check both `Reports/<slug>.md` and `Study Material/<slug>.md`. If both exist, default to the Report for new or deep-dive topics and the Study Material for returning reviews with strong prior performance — but follow the user's lead if they specify one. If neither exists, invoke `/generate-report` or `/study-material` based on the user's intent.

### Step 1: Read the document

Read the full vault file identified in Step 0. This is your curriculum — you cannot teach from a document you haven't read. Note the document's structure, key sections, and density of material so your question design can cover it systematically.

### Step 2: Recall prior context (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py recall \
  --doc "<folder>/<slug>.md" \
  --topic "<doc topic>"
```

Follow the **Pre-Session Context Verification** protocol from the shared contract before proceeding. `SESSION_TS` is set per the shared contract at the first learner-facing question.

Use the recall output to build your teaching plan per the **Agent as Memory Intelligence Layer** section of the shared contract. If this is a returning session, open with a one-sentence recap and move directly to questioning — do not re-explain known material. If this is a new topic, start at the beginning of the document.

**Requested-Document Priority**: The requested document is the primary curriculum. Related-topic context and prior memory should inform your question design and probe strategy, but never displace forward progress through the document's material.

### Step 3: Related-topic scouting (silent)

After primary recall, identify 3-5 topics that are clinically prerequisite to, mechanistically intertwined with, or commonly confused with the study topic. Use your medical knowledge — these should be topics where a gap would undermine understanding of the primary material. For EVD management, examples: CPP physiology, hydrocephalus, ICP monitoring, CSF dynamics. For TBI management: cerebral autoregulation, herniation syndromes, ICP treatment tiers.

Run `recall --topic "<related topic>"` for each. Read the output and note:

- **Prior knowledge**: concepts the learner has confirmed — these are scaffolding for transfer questions ("You know CPP targets from our ICP work. This EVD patient's CPP is 52 — what do you do?")
- **Prior errors or gaps**: misconceptions or weak concepts in related areas — these are high-value probe targets because a wrong belief about CPP physiology will produce wrong EVD management decisions
- **No prior data**: the learner has never been tested on this related topic — if the topic is essential to the primary material, plan to probe it during the session and log the result under the related topic name so future sessions on either topic benefit

Distill your scouting into a brief internal teaching note (not shown to the learner): what related knowledge exists, what related gaps could undermine today's material, and 1-2 related concepts worth weaving into the session. This note shapes your question design — it does not replace the primary document as curriculum.

When you probe a related concept during the session, log it under the related topic's canonical name, not the primary session topic:

```bash
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" --topic "<related topic>" --concept "<concept>" \
  --question "..." --answer "..." --correct <0|1|2> \
  --skill "study-review"
```

This builds the cross-topic knowledge graph naturally: a future session on the related topic will find this data, and a future session on the primary topic will find it again through scouting.

---

## Session Quality Standard

Regardless of document type or teaching approach, every study-review session must meet these outcomes:

1. **The session tests, it does not lecture.** The majority of session time is spent on the learner answering questions, not the agent explaining material. Teaching happens through corrections and follow-ups after the learner commits, not before.

2. **Questions span multiple cognitive levels within the session.** A session that stays at pure recall is too shallow. A session that jumps straight to oral-board defense without confirming foundational knowledge is too ambitious. Within a single session, the agent should probe across at least 2-3 levels: recall/mechanism, discrimination/application, and transfer/complication. The mix should be driven by real-time performance — escalate when the learner demonstrates competence, drop back when they reveal gaps.

3. **Prior errors are addressed before new territory.** Open errors and persistent gaps from recall and scouting are the highest-value targets. A session that ignores known misconceptions to cover new ground is leaving dangerous gaps unfixed.

4. **Every exchange produces a durable, specific memory entry.** No question should be asked without a corresponding `log-answer` call that captures the exact concept tested, the learner's performance, and (for misses) the specific misconception and correction. These entries are the substrate for all future sessions.

5. **The session ends with a specific, actionable handoff.** The `next-strategy` must name concepts, error types, and approaches so a future agent — with no context from this session beyond what's in the database — can pick up exactly where this session left off.

### Document-Type Awareness

The source document shapes how the agent designs questions, not what the session should accomplish.

**Reports** provide narrative context with reasoning, evidence, and clinical integration. The agent should use this rich context to design questions that test understanding of mechanisms, discriminators, management logic, and integration across concepts. The agent designs its own questions from the material rather than following a pre-built list — this allows questions to be responsive to the learner's exact knowledge state and to probe the reasoning and connections that the report's narrative makes explicit.

**Study Material** provides a structured question inventory with atomic facts and pre-designed questions organized by teaching unit. The agent should use the question bank as a coverage scaffold — ensuring systematic testing across all sections — while adapting questions to the learner's current state rather than reading them verbatim. Pre-designed questions are starting points, not scripts: rephrase, combine, contextualize, or replace them based on what recall and real-time performance reveal about where the learner needs to be pushed.

In both cases, the document is the curriculum boundary — the agent's questions should be grounded in and traceable to the document's content, with related-topic probes as targeted supplements rather than tangents.

---

## Session Execution

### Question Design

Use the document's structure as a scaffold, not a script. The teaching principles in the shared contract define what your questions should achieve — every question has a purpose, escalate as fast as performance supports, and prioritize the edge of the learner's competence.

Your recall output, scouting notes, and medical knowledge should drive question selection. Prior errors and gaps from this and related topics are high-priority targets. New document sections should be covered. Known concepts should be used as building blocks for deeper questions, not re-drilled.

Ask one question per turn, then stop. Start with active recall or a clinical decision — never lecture before the learner answers.

### Post-Answer Flow

After each answer: grade it, correct or deepen as needed, then move to the next question. The shared contract's teaching principles (cognitive friction, progressive reveal, minimum effective explanation, correct-but-shallow as partial) guide how much to reveal and when. Keep responses concise — the goal is to spend session time on the learner's thinking, not the agent's explanations.

### Adaptive Pacing

Let real-time performance compress or expand time-on-concept:

- **Strong performance** (correct at application/transfer level): skip planned recall or mechanism questions on the same concept — the learner has demonstrated they don't need them. Advance to the next gap, untested section, or a harder transfer scenario. Do not linger on confirmed knowledge.
- **Weak performance** (wrong or partial): do not advance past the concept. Correct minimally, then immediately retest the same concept from a different angle or clinical context before moving on. An unrepaired gap that gets left behind will compound — fix it now.
- **Mixed signals** (correct on recall, partial on application): the concept is understood but not operationalized. Push to the level where the learner breaks — a management consequence, a complication, a contraindication — then repair and move on.

The goal is to spend the maximum proportion of session time at the learner's frontier — the boundary between what they can and cannot do. Questions below the frontier waste time; questions far above it produce noise instead of learning.

### Session Length Checkpoint

After 5-6 evaluated exchanges, pause and ask the learner: "Want to wrap up here as a quick review, or keep going?" This is not a formality — it determines the session's trajectory:

- **End here**: Proceed immediately to Session End (synthesis challenge, end-session, Anki flush). This gives the learner a lightweight probe of the topic with full memory persistence.
- **Keep going**: Take this as a signal to increase depth and intensity. Escalate to harder application, transfer, and complication questions. Push toward the learner's frontier aggressively. Continue until the learner says they are done — do not ask again or impose a cap.

### Scope of Probes

Probes beyond the primary document should stay clinically adjacent and management-relevant to the current topic. Use your judgment about what's connected — the related-topic scouting gives you the map of where knowledge and gaps exist in adjacent areas.

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
  [--correction "<corrected fact>"] \
  [--error-type "<type>"] \
  [--misconception "<specific wrong belief>"]
```

**Topic assignment**: use the primary doc topic for concepts native to the document. When probing a related concept surfaced through scouting, use the related topic's canonical name instead — this ensures the exchange is discoverable in future sessions on either topic.

Correctness: `2` = correct | `1` = partial (right direction, missing key detail) | `0` = wrong or misconception

Follow the Anki Card Generation protocol from the shared learning contract after each log-answer call.

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
  --next-strategy "<specific directive for next session>"
```
`--next-strategy` must be actionable: name the concept, the error type, and the teaching move.
GOOD: "Retest EVD waveform troubleshooting with a new bedside vignette — partial on previous attempt. Then advance to aSAH grading scale distinctions."
BAD: "Continue reviewing EVD management."

4. Follow the **Post-Session Integrity Verification** protocol from the shared contract before proceeding to Anki flush.

5. Follow the **Anki Queue Validation and Flush** protocol from the shared learning contract.

6. Clean up `data/Sessions/` temps.
