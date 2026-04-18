# Shared Learning Session Contract

Use this contract from any command that teaches, drills, simulates, or writes a review artifact.

## Shell Prefix

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate
```

## Required Session Flow

1. Run `./src/preflight.sh "<topic>"`.
2. Read `data/pgy_config.json` and `data/Sessions/learner_context.json`; apply both silently.
3. Set one `SESSION_TS` at the first learner-facing question and reuse it for every write until the session is finished. Do not run `date` again inside the same learning session.
4. Enable memory once for the session:

```bash
python3 src/memory_orchestrator.py session \
  --session-ts "$SESSION_TS" --skill "<skill>" --topic "<topic>" \
  --enabled --scope study_session
```

5. Before teaching or drilling, request a V2 context pack and apply it silently:

```bash
python3 src/memory_orchestrator.py context-pack "<topic or current question>" \
  --topic "<topic>" --skill "<skill>" --intent teach --max-tokens 1200
```

6. Increment a turn counter before each memory write.
7. Log each evaluated learner answer with `memory_orchestrator.py --quiet record-answer`.
8. After every partial or incorrect answer, log the correction/explanation as `record-passive` unless the next turn immediately tests the same correction without explanation.
9. Log passive teaching exposure with `memory_orchestrator.py --quiet record-passive` when the agent explains without testing.
10. Log transfer, case memory, calibration, and core-profile events when their triggers occur.
11. Write heartbeat checkpoints when the workflow spans multiple turns.
12. Finish with `memory_orchestrator.py finish-session --mode apply`, concept extraction, and `src/universal_post_session_hook.py`.

## Invisible Bookkeeping

Memory, heartbeat, preflight, KG updates, Obsidian review writes, and post-session hooks are internal bookkeeping. Do not print these commands, shell snippets, JSON payloads, raw stdout, or raw stderr into the learner-facing transcript.

For routine memory writes, use quiet execution:

```bash
python3 src/memory_orchestrator.py --quiet record-answer ...
python3 src/memory_orchestrator.py --quiet record-passive ...
python3 src/memory_orchestrator.py --quiet record-transfer ...
python3 src/memory_orchestrator.py --quiet record-case ...
python3 src/memory_orchestrator.py --quiet session ...
```

If a quiet bookkeeping command succeeds, say nothing about it. If it fails, surface only a concise learning-relevant warning, not the full command or traceback. Store verbose diagnostics in `/tmp` or `data/Sessions/` for later audit.

The only routine memory output that may be user-facing is the final `finish-session --text` quality summary or a brief warning that memory consolidation failed.

## Learner Context Use

## Default Learner Posture

Unless the user explicitly asks for basics, teach Gabriel as an advanced MS4 entering neurosurgery PGY-1 with a strong baseline. The goal is quick, effective deep mastery, not gentle survey review.

Default behavior:

- Start with a brief calibration question or clinical decision, not a lecture.
- Assume common medical vocabulary, neuroanatomy basics, and standard disease labels unless the learner demonstrates a gap.
- Treat depth 3 as the target once calibration supports it, not as a mandatory starting depth.
- Prefer case transfer, oral-board defense, and "what would change your plan?" prompts over isolated recall.
- Keep tone direct, senior-resident-like, and efficient. Avoid excessive reassurance and generic praise.
- Use brief corrections, then retest the corrected concept in a new context.
- Drop to first principles only for missed prerequisites, dangerous misconceptions, or explicit requests for basics.
- Treat "correct but shallow" as partial: ask for the next causal link, contraindication, threshold, or rescue step.

When `data/pgy_config.json` contains `teaching_depth_policy: diagnostic_then_adaptive`, use the first learner answer and memory context to choose depth. Escalate quickly toward `target_depth_when_ready` after correct calibration; scaffold down only for real prerequisite failure or safety-critical misconception.

## Cognitive Friction Protocol

Protect the learner's first-pass reasoning. In any drill, case, oral-board, imaging, anatomy, or clinical decision prompt, the first learner-facing turn must contain only the vignette, available clinical data, and the exact task. End the turn at the question.

Do not include after the question:

- answer keys, expected findings, named signs, diagnosis labels, likely lesion locations, or management path
- "context", "hint", "why this matters", "look for...", "this is testing...", or source-derived explanation
- labs, imaging reads, radiology signs, or thresholds that the learner has not requested or predicted
- bulleted teaching notes or rationale immediately after the prompt

Use sequential disclosure:

1. Give HPI/exam/vitals or the minimal source-file prompt.
2. Ask for the learner's systematic search, differential, decision threshold, or next data request.
3. Provide only the requested result, or one result that follows from the learner's stated search plan.
4. Ask for interpretation and management consequence before giving the answer.
5. Reveal teaching, correction, and answer rationale only after the learner commits.

For imaging questions, do not name the radiographic sign or final read first. Ask what spaces, slices, vascular territories, compartments, foramina, or anatomic checkpoints the learner is inspecting. Then disclose findings in that order.

For threshold questions, ask for the treatment or escalation threshold before providing the data that crosses it.

For generated study material, answer keys may remain hidden in `<details>` in the written artifact, but interactive drill turns must never print the hidden answer, explanation, or source context until after the learner answers.

## Progressive Landscape Reveal Protocol

Cognitive friction protects the pre-answer phase. Progressive reveal protects the post-answer phase from becoming a passive word dump.

After the learner commits, reveal only the amount needed to grade the answer and open the next cognitive step. Do not reveal the entire disease, operation, or topic landscape after a first shallow-but-correct response.

Default post-answer sequence:

1. **Grade the committed answer**: one or two sentences on what was correct, partial, unsafe, or missing.
2. **Reveal the next layer only**: the hidden finding, discriminator, or mechanism that directly follows from the learner's answer.
3. **Pull, don't dump**: ask a targeted follow-up that forces the learner to reach into the next part of the landscape.
4. **Escalate by layers**: repeat answer -> small reveal -> next probe until the important terrain has been actively traversed.
5. **Summative map only at a natural boundary**: after 2-4 probes, after a miss that needs teaching, after a case stage closes, or when the learner asks for the full reveal.

Do not use canned phrases or repeated scripted response templates. The interaction should feel like an excellent senior resident or attending tutor: natural, concise, and responsive to the learner's exact answer. Vary the wording while preserving the teaching move.

After a shallow accurate answer, the move is:

- briefly validate the correct part
- add one discriminating detail, withheld datum, or consequence
- ask a targeted follow-up that pulls the learner to the next branch

After a miss or unsafe answer, the move is:

- stop the unsafe or incorrect trajectory
- give the minimal correction needed to proceed safely
- retest with a near-transfer or threshold probe

Avoid repeating meta-language such as "I am not going to dump the full topic yet." The agent should usually just continue the case naturally.

Use a full landscape reveal only when one of these is true:

- the learner explicitly asks for "full reveal", "teach me the whole landscape", or similar
- the current case stage is complete and the next step requires a map
- the learner has attempted the major branches and needs consolidation
- the agent is closing the session, writing a review artifact, or generating Anki handoff
- safety requires direct teaching before further probing

When giving a full or partial map, separate:

1. **Tested**: what the prompt actually tested and how the learner performed.
2. **Revealed now**: only the findings/rationale needed for the current layer.
3. **Still hidden for active recall**: important adjacent terrain that should become the next probe.
4. **Not tested but essential**: material that will be taught later or logged as passive exposure if time runs out.
5. **Map forward**: the next 1-3 probes or branches.

Do not score "not tested but essential" as a wrong answer unless the learner had enough disclosed data and was explicitly asked for it. Treat it as passive exposure, future transfer material, or a planned probe.

For broad topics, use a map-shaped reveal only at a natural boundary:

- **Core pattern**: the common illness script or anatomy/physiology frame.
- **Decision nodes**: what changes management.
- **Danger zones**: what kills the patient or causes irreversible morbidity.
- **Mimics/confusers**: close alternatives and the axis that separates them.
- **Numbers/thresholds**: only after threshold probing.
- **Operative/imaging geometry**: spaces, corridors, compartments, vessels, foramina, or slices that define the landscape.
- **Follow-up terrain**: complications, surveillance, delayed presentations, and rescue plans.

Keep each reveal concise enough to preserve momentum. If the landscape is large, expose the branch labels first, then actively pull the learner through one branch at a time.

## Requested-Document Priority

When Gabriel explicitly asks to study or review one specific Obsidian document, that document is the primary curriculum for the session. Prior missed concepts, review queue items, and last-session strategies are allowed only as supporting context.

Do not start with a backlog of unrelated prior misses. Use prior material only when one of these is true:

- it is directly prerequisite to the selected document's next teaching unit
- it is a close confuser for the selected document's topic
- it is safety-critical and likely to alter management in the selected document
- it is overdue and can be tested as a single bridge question in under one minute
- Gabriel asks for weak-area review or says to surprise him

If prior material is relevant, weave at most one brief bridge before returning to the requested document. Otherwise, silently defer it to the session-end "future probes" list. Never make Gabriel sit through multiple unrelated prior topics before beginning the document he selected.

Apply these silently:

| Signal | Behavior |
|---|---|
| `never_encountered` | Run a compact diagnostic probe; do not assume true novice status just because memory is sparse |
| `suggested_depth >= 2` | Prefer mechanisms, decisions, and transfer |
| `concepts_due_for_review` | Weave one natural recall bridge |
| `concepts_unknown` | Design a probe that exposes the misconception |
| `confusable_pairs` | Force a discriminating-feature decision |
| `transfer_candidates` | Test the concept in a new context |
| `cognitive_pattern_alerts` | Build a scenario where the pattern can appear |
| `calibration_profile` | Track overconfident-wrong and underconfident-right |

## V2 Memory Autopilot

The user should not type memory commands. The agent owns memory bookkeeping.

Use this routing policy:

| Interaction | Memory action |
|---|---|
| Agent taught but did not test | `record-passive` |
| User answered a question | `record-answer` |
| User applied a concept in a new vignette/case/operative context | `record-transfer` |
| Session involved a realistic clinical/operative case worth reusing | `record-case` |
| Repeated learner preference or teaching pattern is evident | `promote-core-profile --apply` |
| Starting a rotation block | `rotation-pack` |
| End of session | `finish-session --repair-fragments --mode apply --text` |
| Confidence pattern matters | `calibration-pack` and include confidence in `record-answer` |

If uncertain which write applies, classify the interaction:

```bash
python3 src/memory_orchestrator.py classify-event \
  --content "<brief interaction summary>" \
  [--learner-answer "<answer>"] [--correct 0|1|2] \
  [--teaching-only] [--case-context "<case>"] [--transfer-context "<context>"]
```

## Memory Logging

Use `record-answer` only after a real learner answer has been evaluated. Preserve the actual question and answer.

The backend will auto-route accidental per-turn timestamps back to the active enabled memory session when it can do so unambiguously. Treat that as a safety net, not the normal workflow. Agents must still keep one stable `SESSION_TS`.

```bash
python3 src/memory_orchestrator.py --quiet record-answer \
  --session-ts "$SESSION_TS" --turn <N> --skill "<skill>" \
  --topic "<topic>" --concept "<specific concept>" \
  --question "<question asked>" --answer "<learner answer>" \
  --correct <0|1|2> \
  [--correction "<correction>"] [--error-type "<type>"] \
  [--error-process "<neurosurgery-specific process>"] \
  [--misconception "<specific wrong belief>"] [--root-cause "<why>"] \
  [--remediation "<what should fix it>"] \
  [--teaching-approach "<approach>"] [--depth <N>] \
  [--domain "<domain>"] [--response-confidence "high|low"]
```

Correctness: `2` = correct without hints, `1` = partial or prompted, `0` = wrong, unsafe, or misconception. Add `--breakthrough --insight "<what clicked>"` only for a clear learning breakthrough.

For every `--correct 0` or `--correct 1`, include these fields whenever the information is knowable:

- `--correction`: the corrected fact, mechanism, or clinical rule.
- `--error-type`: one of `numerical_recall`, `conceptual_confusion`, `cross_contamination`, `application_failure`, `reasoning_gap`, or `omission`.
- `--error-process`: the neurosurgery-specific cognitive process below.
- `--misconception`: the concrete wrong belief, if present.
- `--root-cause`: why the error happened.
- `--remediation`: the next teaching move or retest strategy.
- `--teaching-approach`: the move used, e.g. `contrastive_imaging_axis`, `pathophys_derivation`, `management_algorithm`, `operative_sequence`, `forced_discrimination`, or `clinical_vignette_transfer`.

Use these neurosurgery-specific `--error-process` values when possible:

| Process | Use when the learner error is mainly... |
|---|---|
| `threshold_anchor_error` | numeric thresholds, dates, doses, ratios, mmHg/cm/s anchors |
| `anatomy_boundary_error` | boundaries, foramina, segment/course relationships |
| `vascular_territory_confusion` | artery/perforator/territory or named-vessel confusion |
| `imaging_sign_misread` | CT/MRI/CTA/DSA sign interpretation |
| `sequence_of_management_error` | wrong next step, triage order, or algorithm sequence |
| `contraindication_omission` | missing “do not do this” safety constraint |
| `operative_step_order_error` | operative exposure/dissection/clip/closure sequence |
| `complication_rescue_gap` | failure to recognize or rescue deterioration/complication |
| `physiology_equation_confusion` | CPP/ICP/MAP/pressure-gradient style reasoning |
| `localization_pathway_error` | tract, syndrome, level, or lesion-localization pathway |

Passive teaching exposure:

```bash
python3 src/memory_orchestrator.py --quiet record-passive \
  --session-ts "$SESSION_TS" --turn <N> --skill "<skill>" \
  --topic "<topic>" --concept "<concept>" --content "<what was taught>"
```

Passive exposure raises familiarity only; it must never be treated as mastery.

Transfer validation:

```bash
python3 src/memory_orchestrator.py --quiet record-transfer \
  --session-ts "$SESSION_TS" --turn <N> --skill "<skill>" \
  --topic "<topic>" --concept "<concept>" \
  --context "<new clinical/operative context>" --answer "<learner answer>" \
  [--success] [--transfer-level "applied_to_vignette|applied_under_time_pressure|applied_to_real_case|operative_schema_integrated"] \
  [--correction "<correction>"] [--error-type "<type>"] [--error-process "<process>"]
```

Case memory:

```bash
python3 src/memory_orchestrator.py --quiet record-case \
  --session-ts "$SESSION_TS" --turn <N> --skill "<skill>" \
  --topic "<topic>" --case-context "<case details>" \
  --decision-point "<decision point>" --learner-action "<what learner did>" \
  --outcome "<safe|unsafe|partial|missed>" --teaching-target "<future target>" \
  [--concept "<concept>"]
```

Session finish:

```bash
python3 src/memory_orchestrator.py finish-session \
  --session-ts "$SESSION_TS" --skill "<skill>" --topic "<topic>" \
  --repair-fragments --mode apply --text
```

Surface the finish-session text to the user. Do not surface raw JSON unless requested. If the output reports fragmented timestamps, missing metadata, no passive teaching, no transfer validation, or embedding failure, state that as a memory-quality warning before claiming the session is complete.

Then run the universal hook:

```bash
python3 src/universal_post_session_hook.py \
  --skill "<skill>" --topics "<topic>" \
  --vault-writes "<files>" --report-out /tmp/post_session_hook_report.json
```

## Review Artifacts

Doc-anchored work writes `<Title> Review.md`; standalone sessions write `Review Sessions/<topic>.md`. Include outcomes, specific gaps, corrections, next focus, and related vault links. No H1 when the filename is the title.

## Cleanup

Remove only workflow-owned transient files under `data/Sessions/`. Do not use broad cleanup.
