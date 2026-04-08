---
name: study_material
description: Reads a PDF or PPTX file, extracts content, generates a comprehensive study document with mixed question types, then runs an interactive drill session with feedback and knowledge graph logging. Invoke via /study-material or when the user explicitly requests file-based study material — "make study material from [file]", "quiz me on this file", "prep me for [file]", "test me on these slides". For general study questions not tied to a specific file, answer from model knowledge instead.
---

# Agent Skill: Study Material Generator & Interactive Drill

## Objective

Read a user-provided file (PDF or PPTX), extract all content, generate a comprehensive study document with questions matched to content complexity, then interactively drill the user — providing feedback, Socratic correction, and logging performance to the knowledge graph.

The study document is the artifact. The interactive drill is the learning engine. Both matter.

## Critical Anti-Patterns (NEVER DO THESE)

1. **NEVER generate ad-hoc surgical scenarios, simulations, or "gym sessions".** This skill is NOT intern-bootcamp. The drill engine uses the structured TU-XX / Q# question bank from the study material document — not improvised clinical vignettes.
2. **NEVER ask the user to self-rate their confidence on a numeric scale.** The agent silently tags confidence from linguistic cues (hedging, qualifiers, declarative tone). The user is never asked "how confident are you?" or "rate your understanding 1-10".
3. **NEVER use emojis in any output** — no emoji in session logs, Obsidian files, terminal output, or user-facing messages. Plain text only.
4. **NEVER create a file named `YYYY-MM-DD_study-session.md`** for a document-anchored session. Document-anchored sessions use `<slug>_review.md` (one file per source document, appended over time).
5. **NEVER log shallow notes to the knowledge graph.** Every `--gap-details` entry MUST include `error_type`, `misconception` (what the user specifically got wrong), and `remediation` (what to review). "User was unsure" is not a valid misconception.

## When This Skill Triggers

User provides a file path (PDF, PPTX, or vault `.md`) and wants study material, review questions, or to be tested on it. Phrases like:
- "make study material from [filepath]"
- "review this file [filepath]"
- "create review questions for [filepath]"
- "prep me for [filepath]"
- "quiz me on these slides"
- "test me on this file"

**Vault `.md` files** (Reports, Operative Guides) are valid input sources. For these, skip PPTX/PDF extraction (Step 1) and read the vault document directly using the Obsidian CLI or Read tool. Treat each `##` heading as a slide/page and each bullet as a body item. Proceed from Step 2 onward identically.

---

## Phase 1: Generate Study Material

### Step 0 — Pre-Flight (Silent)

Infer the topic from the filename and any user context. Run pre-flight:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "<inferred topic>"
```

Read `data/Sessions/learner_context.json`. If `case_log_sync.txt` lists new files, run Case Log Proactive Sync per CLAUDE.md. Use context to identify known concepts (don't over-test), gaps/confusable pairs (extra discrimination questions), and calibration alerts. Do not narrate.

### Step 1 — Extract Content

**Sanitize the topic name** from the filename: strip dates, "edited", "AM/PM", version numbers, file extensions. Example: `"Lab 1 - Gross anatomy brain structures_3-24-26 (AM edited).pptx"` → `brain_anatomy_lab_1`. This sanitized name is `<topic_slug>` used in all output filenames.

**For PPTX files:**
- Use the `pptx` skill infrastructure to read the file
- Extract per-slide: slide number, title, body text, speaker notes, image descriptions
- For slides with images: describe what the image shows (labeled diagram, cross-section, clinical photo, imaging study) — this description becomes the basis for image-reference questions

**For PDF files:**
- Use the `pdf` skill infrastructure to read the file
- Extract per-page: page number, headers, body text, figure captions, table contents
- For pages with figures: describe the visual content

**Write extraction to a uniquely named file:**
```
data/Sessions/slide_extraction_<topic_slug>_<YYYYMMDD>.json
```

Structure:
```json
{
  "source_file": "original_filename.pptx",
  "topic": "Brain Anatomy Lab 1",
  "topic_slug": "brain_anatomy_lab_1",
  "extraction_date": "2026-03-25",
  "total_slides": 42,
  "slides": [
    {
      "number": 1,
      "title": "Circle of Willis",
      "body": "...",
      "speaker_notes": "...",
      "has_image": true,
      "image_description": "Inferior view of brain showing arterial circle with labeled vessels..."
    }
  ]
}
```

### Step 2 — Concept Chunking & Classification

Spawn a **`general-purpose` subagent** (use `model: "sonnet"`) to analyze the extraction and produce a concept map. The subagent prompt:

> Read `data/Sessions/slide_extraction_<topic_slug>_<YYYYMMDD>.json`. Group the content into logical teaching units (a teaching unit may span multiple slides if they cover the same concept, or a single dense slide may contain multiple teaching units). For each teaching unit, extract individual testable concepts and classify each by complexity.
>
> **Complexity classification rules — match question type to what the concept ACTUALLY requires:**
>
> | Content Pattern | Complexity Tag | Question Type | Rationale |
> |---|---|---|---|
> | A named structure, definition, list membership, or single fact | `recall` | **Short answer / fill-in-the-blank** | Pure retrieval — MC would make this too easy by providing recognition cues |
> | "X is lateral/medial/superior/deep to Y", a pathway course, or spatial relationship | `spatial` | **Anatomical relationship question** or **image-reference question** | Spatial reasoning requires mental visualization, not recognition |
> | Two structures/conditions that share features but differ in one key way | `discrimination` | **Multiple choice (4-5 options with close distractors)** | MC is ONLY appropriate when the pedagogical value is forcing a choice between genuinely confusable options |
> | A causal chain: "because X → Y → Z", pathophysiology, mechanism | `mechanism` | **Two-step reasoning** ("If X is damaged, what happens to Y, and what deficit results?") | Tests whether the learner can trace the causal chain, not just name endpoints |
> | Requires combining anatomy + physiology + clinical presentation | `integration` | **Clinical vignette → localization / diagnosis** | The hardest type — tests whether knowledge is functional, not inert |
> | A labeled diagram, cross-section, or imaging study is central to the concept | `visual` | **Image-reference question** ("On the figure from slide N, identify structure X") | Tests visual identification — reference the specific slide |
>
> **Critical rule**: Do NOT default to MC. MC is a crutch that tests recognition, not retrieval. Reserve it ONLY for `discrimination` concepts where close distractors are the teaching tool. A simple vocabulary term tested as MC is pedagogically worthless.
>
> **Scale with content**: Extract ALL testable concepts. Do not cap or skip. A 40-slide deck on brain anatomy may generate 60+ questions. A 15-slide overview may generate 20. Let the content dictate.
>
> Write output to `data/Sessions/concept_map_<topic_slug>_<YYYYMMDD>.json`:
> ```json
> {
>   "teaching_units": [
>     {
>       "unit_id": "TU-01",
>       "title": "Circle of Willis — Component Arteries",
>       "slides": [4, 5, 6],
>       "concepts": [
>         {
>           "id": "C-001",
>           "claim": "The anterior communicating artery connects the two ACAs",
>           "complexity": "recall",
>           "question_type": "short_answer",
>           "visual_dependent": false
>         },
>         {
>           "id": "C-002",
>           "claim": "The PCA courses through the ambient cistern lateral to the midbrain",
>           "complexity": "spatial",
>           "question_type": "anatomical_relationship",
>           "visual_dependent": false
>         }
>       ],
>       "clinical_correlations": ["AComm aneurysm is the most common location for aneurysmal SAH"]
>     }
>   ],
>   "total_concepts": 64,
>   "complexity_distribution": {"recall": 22, "spatial": 15, "discrimination": 10, "mechanism": 8, "integration": 5, "visual": 4}
> }
> ```

### Step 3 — RAG Enrichment (Supplemental Only)

**RAG is a supplement, not the main course.** The slide content is the primary source. RAG adds depth to explanations and generates richer clinical correlations — it does NOT replace or overshadow the slide material.

**Rules for RAG usage:**
1. Only run RAG for teaching units tagged `mechanism` or `integration`, OR where the slide content is thin (< 30 words per concept in that unit)
2. RAG content is used ONLY for:
   - **Answer explanations** — adding textbook depth to why an answer is correct
   - **Clinical pearls** — 1-2 sentence additions that connect anatomy to clinical relevance
   - **Generating integration-level questions** that the slides alone couldn't support
3. RAG content is NEVER used to generate `recall` or `spatial` questions — those come entirely from the slides
4. In the final study document, slide-sourced content must be ≥70% of each question's explanation. RAG adds the remaining ≤30% as enrichment, clearly attributed.

For each eligible teaching unit, run:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/lance_retriever.py compare "<teaching unit title>" --no-learner --no-frontier
```

Use `--no-frontier` to keep it fast. Use `--no-learner` because the learner context is already captured in Step 0.

Read the output from `data/Sessions/scratch_context.md`. Extract only the passages relevant to deepening explanations — do not let retrieved passages become the basis for new questions that aren't grounded in the slides.

### Step 4 — Generate Study Document

Write the study document to:
```
/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/<topic_slug>_<YYYYMMDD>.md
```

**Document structure:**

```markdown
# <Topic Name> — Study Material
**Source**: <original filename> | **Generated**: <date> | **Total Questions**: <N>
**Complexity Mix**: <recall>R / <spatial>S / <discrimination>D / <mechanism>M / <integration>I / <visual>V

---

## Concept Summary

### <Teaching Unit 1 Title> (Slides X-Y)
- [Dense teaching-point bullets — not a slide transcript, but a distilled summary of what you need to know]
- [Each bullet is a testable claim]

### <Teaching Unit 2 Title> (Slides X-Y)
- ...

---

## Questions

### Q1 [recall] (Slides 4-6) — TU-01
**Name the five paired and three unpaired arteries that form the Circle of Willis.**

<details><summary>Answer</summary>

[Full answer]

**Explanation**: [Primarily from slides. If RAG-enriched, the enrichment is clearly a secondary addition]:
- From slides: [core explanation]
- Clinical pearl (Rhoton, Ch. 3): [1-2 sentence RAG enrichment with source attribution]

**Slide reference**: Slides 4-6
</details>

---

### Q2 [discrimination] (Slides 8-9) — TU-03
**A patient has a stroke affecting the anterior thalamus. Which perforating artery is most likely involved?**
- A) Lenticulostriate arteries
- B) Thalamoperforating arteries (P1 segment)
- C) Anterior choroidal artery
- D) Thalamogeniculate arteries (P2 segment)

<details><summary>Answer</summary>

**B) Thalamoperforating arteries (P1 segment)**

**Why each distractor is wrong** (this is the teaching value of MC):
- A) Lenticulostriates supply basal ganglia + internal capsule, NOT thalamus
- C) AChA has limited thalamic territory — supplies posterior limb IC, LGN, medial temporal
- D) Thalamogeniculates supply lateral/posterior thalamus, not anterior

**Slide reference**: Slides 8-9
**Clinical pearl (Winn, Ch. 12)**: [brief RAG enrichment]
</details>

---

### Q3 [visual] (Slide 12 — Figure) — TU-05
**Referring to the labeled diagram on Slide 12: Structure C courses through the ambient cistern. Name this structure and state what it supplies.**

<details><summary>Answer</summary>

[Answer with anatomical detail]

**Slide reference**: Slide 12, Figure
</details>
```

**Formatting rules:**
- Every question tagged with complexity type, slide reference, and teaching unit ID
- Every MC question includes "why each distractor is wrong" — that's where the learning happens
- Every answer includes slide reference so the user can go back to the source
- RAG enrichment is always labeled and attributed — never blended invisibly into slide content
- `<details>` tags for offline self-testing

### Step 5 — Notify User

After the document is written, present:

> **Study material generated**: <N> questions from <M> slides across <K> teaching units.
> Written to `Obsidian → agentic-neuro/Study Material/<topic_slug>_<YYYYMMDD>.md`
>
> **Complexity breakdown**: <recall>R / <spatial>S / <discrimination>D / <mechanism>M / <integration>I / <visual>V
>
> Ready to drill? I'll test you interactively — one question at a time, with feedback and explanations. Or you can open the document on your own.
>
> **What would you like to do?**
> 1. **Start drilling** — interactive Q&A session right here
> 2. **Take it offline** — review the document on your own
> 3. **Both** — drill now, finish the rest offline later

---

## Phase 2: Interactive Drill

Triggered when user chooses to drill (option 1 or 3 above), or says "drill me on [topic]" referencing an existing study material file.

### Drill Pre-Flight (Silent — before first question)

Check for an existing Review Session document and prior `doc_status`:

```bash
# 1. Check doc_status in knowledge graph
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py doc_status "Study Material/<slug>_<date>.md"

# 2. Check for existing Review Session file
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<slug>_review.md" 2>/dev/null
```

- **`status: "new"`** → begin from TU-01. No special greeting needed.
- **`status: "returning"`** → open with a brief, specific recap before Question 1:
  > "Welcome back. Last session ([date]): [coverage_pct]% coverage, [N] concepts confirmed. You were strong on [understood]. Still working on: [missed]. Let's revisit those first."
  Then reorder: missed concepts' questions come first, then continue forward from last covered TU.

If the Review Session file exists, read it for richer session context (prior session notes, correction history).

### Drill Engine — Core Loop

**Tone**: Study coach — encouraging but honest. A peer who's a year ahead and wants you to succeed. Direct feedback, no sugarcoating, never punitive. Celebrates genuine understanding, calls out surface-level pattern matching.

**One question at a time. Wait for the user's answer. Never show the answer preemptively.**

For each question:

1. **Present the question** — include the complexity tag and slide reference so the user can look it up if needed after answering
2. **Wait for response**
3. **Evaluate and respond** based on accuracy:

| Outcome | Response Pattern | Example |
|---|---|---|
| **Correct** | Brief confirmation + one enrichment nugget that extends their knowledge. Move on. | "Exactly right. Worth noting — Rhoton describes a variant where the AComm is duplicated in ~18% of cases, which changes the aneurysm approach. Next question:" |
| **Partially correct** | Acknowledge what's right, isolate what's missing with a targeted follow-up probe. Do NOT reveal the full answer yet. | "You got the artery right — PCA. But which segment gives off the perforators to the thalamus, P1 or P2? And does it matter?" |
| **Incorrect** | No immediate answer reveal. One Socratic redirect targeting the specific misconception. | "Think about where the lenticulostriates actually originate — are they from the PCA, or somewhere else? Trace the vessel." |
| **Incorrect after redirect** | Now reveal the full answer with complete explanation. No shame. Frame as a learning moment. | "The answer is thalamoperforating arteries from P1. Here's the key distinction: [full explanation]. This is a high-yield discrimination — let's make sure it sticks." |
| **"I don't know" / "skip"** | Respected immediately. Full explanation given. No judgment. | "No problem — this is exactly what we're here for. [Full explanation]. I'll circle back to this concept later to make sure it landed." |

4. **Silent confidence tagging**: Tag each response:
   ```json
   {"concept": "concept text", "response_confidence": "high|low", "correct": true|false}
   ```
   - **High confidence**: declarative, no hedging, no qualifiers
   - **Low confidence**: "I think", "maybe", hedging, question marks

### Adaptive Ordering

1. **Start with `recall` questions** — warm-up, build momentum
2. **Progress to `spatial` and `discrimination`** — medium difficulty
3. **End with `mechanism` and `integration`** — requires accumulated knowledge from earlier questions
4. **`visual` questions**: intersperse where relevant to break up text-heavy sequences

**Adaptive reordering rule**: If the user gets 2+ questions wrong within the same teaching unit, **insert 1-2 additional questions from that unit** before moving on. These should target the same concept from a different angle (e.g., if they missed a recall question about Circle of Willis components, follow up with a spatial question about the same vessels).

**"I don't know" circle-back**: Track any questions answered with "I don't know" or skipped. After completing the primary pass, revisit these concepts with a simpler version of the question to check if the explanation landed.

### Mid-Session Checkpoint

Every ~12 questions, pause:

> **Checkpoint**: <N> down, <M> to go. Here's where you stand:
> - **Strong**: [teaching units with ≥80% correct]
> - **Needs work**: [teaching units with <60% correct]
>
> Want to: **keep going** | **focus on weak areas** | **pause here**?

If the user chooses "focus on weak areas," reorder remaining questions to prioritize the weak teaching units, interleaving with occasional strong-area questions to maintain confidence.

**At every checkpoint, silently run `log_doc_progress`** (heartbeat — preserves progress on unexpected exit):

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py log_doc_progress \
  --doc "Study Material/<slug>_<date>.md" \
  --doc-type "study-material" \
  --covered "<all Q IDs attempted so far, comma-sep>" \
  --understood "<Q IDs answered correctly, comma-sep>" \
  --missed '[{"concept":"<Q ID>","error_type":"<type>","misconception":"<brief>"}]' \
  --coverage-pct <attempted/total*100> \
  --total-concepts <total_questions>
```

### Session-End Summary

After all questions (or user stops):

```
## Session Complete: <topic>

| Metric | Value |
|--------|-------|
| Questions attempted | X / Y total |
| Correct | N (%) |
| Partial | N (%) |
| Incorrect | N (%) |
| Skipped / IDK | N |

### Strongest Areas
- [Teaching unit] — X/Y correct
- [Teaching unit] — X/Y correct

### Focus Areas (prioritize before exam)
- [Teaching unit] — X/Y correct. Key gap: [specific concept(s) missed]
- [Teaching unit] — X/Y correct. Key gap: [specific concept(s) missed]

### Calibration Check
- [If applicable: "You were confident but wrong on X — watch for overconfidence in [domain]"]
- [If applicable: "You hedged on X but got it right — trust your reasoning on [domain]"]

### Recommendation
[1-2 sentences: what to review before next session, based on performance]
```

Then offer:
> **What next?**
> 1. **Save to Anki** — Create flashcards from this session (targets weak areas)
> 2. **Review weak areas** — Deep-dive RAG explanation on your gap topics
> 3. **Another file** — Load a new PDF/PPTX for study material
> 4. **End session**

### Knowledge Graph Logging (Silent — after session summary)

Log the session results. Run both commands:

Use `heartbeat.sh` with `--obsidian-write` to atomically log to the knowledge graph AND write the Obsidian review session file:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
./src/heartbeat.sh \
  --doc "Study Material/<slug>_<date>.md" \
  --doc-type "study-material" \
  --covered "<all Q IDs attempted, comma-sep>" \
  --understood "<Q IDs answered correctly, comma-sep>" \
  --missed '[{"concept":"<Q ID>","error_type":"<type>","misconception":"<specific>"}]' \
  --coverage-pct <final_pct> \
  --total <total_questions> \
  --topics "<comma-separated topics from teaching units>" \
  --depth 2 \
  --gaps "<comma-separated concepts answered incorrectly>" \
  --gap-details '[{"concept":"<missed concept>","error_type":"<type>","misconception":"<what they got wrong>","remediation":"<what to review>"}]' \
  --obsidian-write \
  --topic-name "<Topic Name>" \
  --slug "<topic_slug>" \
  --session-num <N> \
  --score "<N>/<N> (<pct>%)" \
  --skill "study-material" \
  --domain "<domain>" \
  --understood-detail "[TU-XX] <concept A>, <concept B>" \
  --gaps-detail "[TU-XX] <concept> (Q<N>) -- <error_type> -- <specific misconception>"
```

For multiple gap entries in `--gaps-detail`, separate them with `|` (pipe):
```
--gaps-detail "[TU-02] retrograde flow (Q9) -- reasoning_gap -- did not trace collateral|[TU-03] AChA origin (Q14) -- cross_contamination -- confused with PComA origin"
```

**Error type classification for gap-details:**
- User confused two similar structures → `cross_contamination`
- User couldn't recall a fact → `numerical_recall` (if quantitative) or `conceptual_confusion` (if qualitative)
- User knew the concept but couldn't apply it to the vignette → `application_failure`
- User skipped a step in a causal chain → `reasoning_gap`

**BAD vs GOOD logging examples:**

BAD (shallow, useless for future sessions):
```bash
--gaps "PComA anatomy" --gap-details '[{"concept":"PComA","error_type":"conceptual_confusion","misconception":"user was unsure"}]'
```

GOOD (specific, actionable, reconstructable):
```bash
--gaps "fetal-variant PComA retrograde flow,AChA origin identification" \
--gap-details '[{"concept":"fetal-variant PComA retrograde flow","error_type":"reasoning_gap","misconception":"did not trace retrograde collateral pathway from vertebral/basilar/P1 through fetal PComA during proximal ICA occlusion","remediation":"review posterior circulation collateral anatomy and sink effect pressure gradients"},{"concept":"AChA origin identification","error_type":"cross_contamination","misconception":"confused AChA origin with PComA origin on supraclinoid ICA","remediation":"drill ICA segment anatomy C4-C7 with branch points"}]'
```

The misconception field must describe WHAT the user specifically believed or failed to trace — not that they "were unsure" or "got it wrong".

If calibration data is notable (≥3 overconfident-wrong or underconfident-right signals), also log:
```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && python3 src/knowledge_graph.py log_bootcamp \
  --topics "<topics>" \
  --weaknesses "<weak concepts>" \
  --module "study-material" \
  --outcome "<pass|partial|fail based on overall %>" \
  --calibration '[<array of confidence tags>]'
```

Outcome thresholds: ≥80% correct → "pass", 50-79% → "partial", <50% → "fail"

Do not narrate the logging. Do not mention the knowledge graph to the user.

### Obsidian Session Log (Handled by heartbeat.sh)

The `--obsidian-write` flag on `heartbeat.sh` (used in the session-end command above) automatically handles:
- Creating or appending to `Review Sessions/<slug>_review.md`
- Updating frontmatter (`last_studied`, `session_count`, `coverage_pct`)
- Updating `Review Sessions/INDEX.md`

**The agent is still responsible for:**
1. Updating the `## Concept Map Status` table in the review file after heartbeat.sh runs — read the file, regenerate the table from current `doc_status`, and write it back
2. Updating `Study Material/INDEX.md` if the Study Material doc was newly created in Phase 1

**Gap detail quality rule for `--gaps-detail`**: Each gap entry must describe the specific incorrect mental model, not just "got it wrong". Example:
- BAD: `[TU-03] PComA anatomy (Q9) -- conceptual_confusion -- user was unsure`
- GOOD: `[TU-03] Fetal-variant PComA retrograde flow (Q9) -- reasoning_gap -- user identified need for distal control but did not trace the retrograde collateral pathway (vertebral -> basilar -> P1 -> fetal PComA) that supplies the aneurysm dome even with proximal ICA occlusion`

Do not narrate this write to the user.

### Concept Extraction (Silent)

After the session log write, extract 2-5 atomic concepts from the Study Material that are:
- Named clinical entities (syndromes, classifications, procedures, structures, danger zones) encountered during the drill
- NOT already in `Concepts/` (check via `ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null`)
- Important enough to be wikilink targets for future content

Write each to `Concepts/<Name>.md` per the Concept Extraction Protocol in shared-system.md. Use `extracted_from: "study-material: <document title>"`. Each concept should wikilink back to the Study Material document.

### Post-Session Hook (Silent)

Run the Universal Post-Session Hook (see shared-system.md) to update Dashboard.md.

### Progress Over Sessions (in `<slug>_review.md`)

When appending a new session block to `Review Sessions/<slug>_review.md`, also regenerate the `## Progress Over Sessions` table immediately after the `## Concept Map Status` table. This table shows the cumulative trajectory across all sessions for this document:

```markdown
## Progress Over Sessions
| Session | Date | Coverage | Score | Key Gaps |
|---------|------|----------|-------|----------|
| 1 | YYYY-MM-DD | TU-01 to TU-02 (25%) | 8/12 (67%) | [TU-02] concept D — conceptual_confusion |
| 2 | YYYY-MM-DD | TU-01 to TU-04 (50%) | 18/24 (75%) | [TU-03] concept F — reasoning_gap |
```

Construct this table from the existing `### Session N` blocks in the file. This provides at-a-glance progress visibility without reading every session block.

---

## Resuming a Previous Study Document

If the user says "drill me on brain anatomy lab 1" or "continue where we left off on [topic]", check for an existing file in `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/` matching the topic. If found, read the document and start Phase 2 directly — no need to regenerate.

If multiple dates exist for the same topic, use the most recent unless the user specifies otherwise.

---

## Anki Handoff

If the user selects "Save to Anki" after a drill session, follow the **Surgical Handoff Protocol**:
1. Compile the session transcript (questions asked, user responses, correct answers, explanations)
2. Prefix with: `### CRITICAL: STUDY MATERIAL DRILL SESSION. GENERATE CARDS ONLY FOR INCORRECTLY ANSWERED AND SKIPPED QUESTIONS — THESE ARE THE HIGHEST-YIELD TARGETS. Also include any enrichment nuggets from correctly answered questions that add new information beyond what the user demonstrated knowing. ###`
3. Trigger the `anki-sync` skill with this scoped transcript
4. Use **claude-sonnet-4-6** for the extraction to ensure medical accuracy

---

## Context Compression

If the drill session exceeds 12 turns, follow the standard compression protocol from CLAUDE.md:
1. Notify: *"We're ~12 turns in — want a session digest before we continue?"*
2. On approval: produce digest with question performance, teaching unit progress, identified gaps
3. Write to `data/Sessions/session_digest_YYYYMMDD.md`
4. Continue drilling from where you left off

---

## Initialization

When this skill is triggered, do NOT present a menu. Immediately begin Phase 1 using the file path provided. The first user-visible output should be the Step 5 notification after the document is generated.

If no file path was provided in the trigger message, ask:
> What file would you like me to create study material from? Give me the path to a PDF or PPTX.
