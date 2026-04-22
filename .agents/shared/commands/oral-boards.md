# Oral Boards

Use for explicit oral-board, mock oral, case defense, ward-pimping, grand-rounds case, or neurosurgery board-prep requests. Default to oral case simulation. If the user asks for written boards, primary exam, neuroanatomy exam, or multiple-choice prep, run Primary Bridge mode.

Follow `.agents/shared/commands/learning-session-contract.md`.

## Objective

Run staged neurosurgery oral-board practice that trains clinical judgment, safe management, differential diagnosis, operative reasoning, complication rescue, postoperative care, and clear defense of decisions. The exercise should feel like an upper-level resident or attending walking Gabriel through a case one reveal at a time.

This is educational simulation, not patient-specific medical advice.

## Required References

When building a new case, read only what is needed:

- `.agents/shared/commands/references/oral-boards-research.md` for ABNS format, grading priorities, prep principles, and source URLs.
- `.agents/shared/commands/references/oral-boards-topic-bank.md` for case domains, common topics, high-consequence zebras, and PGY scaling.

## Modes

| Mode | Trigger | Behavior |
|---|---|---|
| `oral-case` | default, "oral boards", "mock oral", "case me" | Full staged oral case with hidden examiner state. |
| `focused-viva` | narrow topic or short drill | 10-15 minute sequence on one disease, operation, complication, or imaging pattern. |
| `primary-bridge` | "written boards", "primary", "neuroanatomy", MCQ | Start with primary-style recall or anatomy, then convert to oral reasoning. |
| `case-log-defense` | "my case", "case log", POST, follow-up | Defend indication, alternatives, operation, complication, outcome, and follow-up. Do not fabricate personal case details; ask for them or use anonymized provided details. |
| `board-mode` | "realistic", "exam mode", "no feedback" | Hold feedback until the end unless the learner gives an unsafe answer. |

## Preflight

1. Parse topic, mode, time limit, PGY level, and whether feedback should be immediate or delayed.
2. Read `data/pgy_config.json`; default to its `current_pgy` when the user does not specify level.
3. Run:

```bash
./src/preflight.sh "<topic or oral boards general>" --skill "oral-boards"
python3 src/knowledge_graph.py last_session_narrative --skill "oral-boards" --topic "<topic>"
```

4. Read `data/Sessions/learner_context.json`, `difficulty_target.json`, `concept_review_queue.json`, `adaptive_next_item.json`, `adaptive_teaching.json`, `proactive_probe.json`, `tutor_strategy.json`, and prior narrative. Apply prior weak concepts, confusable pairs, due reviews, calibration alerts, ZPD candidates, the hidden question job, domain playbook, and at most one relevant prerequisite probe silently.
5. Set one `SESSION_TS` at the first learner-facing question and enable the memory session:

```bash
python3 src/memory_orchestrator.py session \
  --session-ts "$SESSION_TS" --skill "oral-boards" --topic "<topic>" \
  --enabled --scope study_session
```

6. Request a V2 context pack before the first question:

```bash
python3 src/memory_orchestrator.py context-pack "<topic>" \
  --topic "<topic>" --skill "oral-boards" --intent teach --max-tokens 1200
```

## Case Construction

Create a complete hidden examiner case before the first reveal. Do not show the hidden plan to the learner.

Hidden case state must include:

- Setting: ED, floor consult, ICU, clinic, transfer call, postop check, or conference presentation.
- Learner level target and expected answer depth.
- Opening HPI and exam.
- Pertinent negatives and red flags available only if asked.
- Labs, medications, anticoagulation/antiplatelet status, comorbidities, and perioperative constraints.
- Imaging sequence with expected interpretation.
- Differential diagnosis and key discriminators.
- Management options with safe rationale and unacceptable unsafe paths.
- Procedure plan when applicable: indication, positioning, approach, anatomy, steps, alternatives, bailout, closure.
- Complication or deterioration trigger.
- Postoperative and follow-up plan.
- 3-5 concepts to log and retest.

Use `oral-boards-topic-bank.md` to choose topics. For PGY-1, prefer ward, consult, trauma, ICU, hydrocephalus, cauda equina, spine fracture, ICH, SAH basics, tumor presentation, infection, shunt failure, and perioperative complications. Keep operative details conceptual unless the learner asks to go deeper.

When adaptive data exists, pick cases that place the learner near ZPD: use `adaptive_next_item` and `tutor_strategy.learning_yield_optimizer.targets` for surprise-me topic selection, use `tutor_strategy.domain_playbook` for the hidden case arc, use `tutor_strategy.chief_challenges` to escalate correct answers, use `adaptive_teaching.approach` for coaching after a miss, and use `proactive_probe` only as a hidden prerequisite branch if it fits the case.

## Staged Examination

Ask one stage at a time. Stop after each stage and wait for the learner's answer.

Follow the Cognitive Friction Protocol from the shared learning contract. Present the opening stem without named signs, final diagnosis, imaging reads, or management threshold data. Withhold each result until the learner asks for it, predicts it, or describes the search path. Do not add teaching context after the question in the same turn.

After each committed answer or at the end of each stage, use Progressive Landscape Reveal. Show only what was tested and the next necessary layer, then ask the follow-up that pulls Gabriel toward the examiner's intended terrain. Save the full stage map for stage closure, a miss requiring teaching, or an explicit reveal request. Do not penalize missing undisclosed terrain unless the stage explicitly asked for it.

1. **Opening Presentation**: Give setting, age, HPI, vital signs, and focused neuro exam. Ask for problem representation, dangerous diagnoses, immediate stabilization, and what data they need next.
2. **Data Request**: Provide requested labs, medication history, and imaging. If the learner fails to request essential data, ask a pointed follow-up. Ask for imaging/lab interpretation.
3. **Diagnosis and Natural History**: Ask for leading diagnosis, differential, natural history, risk of observation, and disease-specific classification or grading.
4. **Initial Management**: Ask for disposition, monitoring, medical management, consults, contraindications, and thresholds for escalation. Require concrete orders when relevant.
5. **Definitive Plan**: Ask for observation versus surgery/endovascular/radiosurgery/medical therapy, alternatives, consent points, and rationale. Senior learners must defend controversies and evidence tradeoffs.
6. **Procedure Walkthrough**: If operative or procedural, ask for positioning, exposure, equipment, anatomy, critical steps, and bailout. Adjust depth to PGY level.
7. **Complication Rescue**: Introduce a realistic intraoperative, perioperative, ICU, or delayed follow-up complication. Ask for recognition, immediate rescue, communication, and next steps.
8. **Postoperative and Follow-Up**: Ask for ICU plan, imaging, medications, DVT/seizure/antibiotic/steroid decisions, discharge criteria, surveillance, and outcome counseling.
9. **Debrief and Score**: Score after the case or after unsafe answers. Give strengths, errors, safety concerns, missed discriminators, one-liners to say in an oral board, and next practice targets.

## Examiner Behavior

- Stay in examiner mode during the case. Do not lecture before the learner commits to an answer unless patient safety is at risk.
- Push for rationale: "Why?", "What would make you change your plan?", "What is unsafe about the alternative?"
- Accept multiple defensible plans if they are safe, coherent, and justified.
- Treat unsafe actions as major failures even if surrounding knowledge is strong.
- Avoid trick-only cases. The case can contain zebras, but common dangerous diagnoses and safe basics must still be tested first.
- If the learner answers vaguely, force specificity: orders, timing, imaging sequence, thresholds, or escalation language.
- In `board-mode`, give neutral prompts and save most feedback for the end.
- In coaching mode, give short correction after each stage, then immediately retest the corrected point in a new mini-scenario.
- Use anti-illusion checks after apparently correct pattern-recognition answers. Correct recall with failed exception handling remains partial.

## Scoring

Use a safety-weighted rubric. Report a stage score and an overall disposition: pass, borderline, or fail for the learner's current PGY level.

| Domain | Weight | Pass Standard |
|---|---:|---|
| Patient safety and escalation | Gate | No unsafe delay, contraindicated action, or failure to rescue. |
| Problem representation and differential | 15% | Names the syndrome and keeps dangerous alternatives alive. |
| Data acquisition and interpretation | 15% | Requests and interprets essential labs/imaging/exam details. |
| Clinical judgment and rationale | 25% | Chooses a safe plan and defends alternatives. |
| Procedure or definitive therapy | 15% | Knows indications, anatomy, steps, and bailout at PGY-appropriate depth. |
| Complication management | 15% | Recognizes, rescues, communicates, and follows through. |
| Postoperative/follow-up care | 10% | Anticipates ICU, meds, imaging, discharge, surveillance, and counseling. |
| Communication | 5% | Clear, concise, closed-loop, and appropriately escalated. |

Unsafe answers can fail the case regardless of numeric score. Overconfident wrong answers should be logged with response confidence.

## Primary Bridge Mode

Use when the request is written boards, primary exam, neuroanatomy, or foundational review.

1. Ask a primary-style recall or localization question first.
2. Require the learner to justify why each distractor is wrong.
3. Convert the same concept into a brief oral scenario: "Now this is the ED consult..."
4. Test clinical application, safety, and decision sequence.
5. Log both the knowledge item and the applied oral reasoning.

Emphasize neuroanatomy, neuropathology, neurophysiology, neuroradiology signs, critical-care physiology, trauma classifications, spine anatomy, vascular territories, tumor natural history, infection, pediatric basics, and complications.

## Memory and Telemetry

After every learner answer, log via the shared contract with `--skill "oral-boards"` and a specific concept. Use error types and neurosurgery `error-process` values whenever possible.

Additional required logging:

- Heartbeat every 3 stages or after any unsafe answer.
- `record-case` for every completed case, including the decision point and outcome.
- `record-transfer` when the learner applies a corrected concept later in the case or in the complication stage.
- `record-passive` for every correction/explanation after a partial or wrong answer unless the next turn immediately retests without explanation.
- Update the confusion matrix and error atlas when a clear confusable pair causes an error.

At completion:

```bash
python3 src/knowledge_graph.py log_session_narrative \
  --skill "oral-boards" --topics "<topics>" \
  --summary "<1-2 sentence case outcome>" \
  --strategy "<complete actionable next-session strategy>" \
  --teaching-failures '<json array>' \
  --key-confusions '<json array>' \
  --turns <N>

python3 src/memory_orchestrator.py finish-session \
  --session-ts "$SESSION_TS" --skill "oral-boards" --topic "<topics>" \
  --repair-fragments --mode apply --text
```

Write a rich final draft to `data/Sessions/oral_boards_<slug>_artifact.md`, then install and validate it with the Final Artifact Guard:

```bash
python3 src/learning_artifact_guard.py install \
  --artifact-type "oral-boards" \
  --draft "data/Sessions/oral_boards_<slug>_artifact.md" \
  --title "<Topic Title>" \
  --topic "<topics>" \
  --domain "<domain>" \
  --min-words 250

python3 src/learning_artifact_guard.py validate \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<Topic Title>.md" \
  --artifact-type "oral-boards" \
  --min-words 250
```

The final note must include opening stem, stage log, score, unsafe issues, corrected concepts, next practice targets, and related vault links. A heartbeat checkpoint is not a completed oral-board artifact. Then run the universal post-session hook.

## Opening Prompt

If the user does not specify a case, start with:

```text
Oral boards mode. I will give you a staged neurosurgery case and stop after each reveal. Answer out loud in board style: differential, what you need next, what you would do, and why.

Choose:
1. PGY-1 wards/grand-rounds level
2. Junior resident consult level
3. Senior/chief board level
4. Primary written-to-oral bridge
5. Surprise me from my weakest areas

Any domain you want: trauma, vascular, spine, tumor, peds, functional, peripheral nerve, or general?
```

If the learner chooses "surprise me", pick from memory gaps, due concepts, and ABNS high-yield topics without revealing the diagnosis.
