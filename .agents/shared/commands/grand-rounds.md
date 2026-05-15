# Grand Rounds Presentation Builder

Build an educational neurosurgery slide deck for departmental grand rounds, case conference, or journal club. This command is explicit-invocation only.

Use for:
- `/grand-rounds --mode case`
- `/grand-rounds --mode article`
- "put together a case presentation"
- "journal club presentation"
- "build my grand rounds"

Do not use this command for ordinary clinical questions, oral-board drilling, or research reports unless the user explicitly wants a presentation deck.

## Core Posture

1. The pipeline is mode-stable: intake, enrichment, rubric, gap probe, outline, deck, vault write, optional rehearsal.
2. Mode only changes the rubric and deck shape:
   - `case`: presentation, workup, decision, intervention, outcome, teaching points, anticipated questions.
   - `article`: background, question, methods, results, limitations, clinical impact, critique, anticipated questions.
3. No hand-curated PowerPoint templates. The agent builds a content-specific deck.
4. Visual-first deck design: one primary visual, table, timeline, imaging placeholder, or structural diagram per slide where possible. Slide text is headline and anchor-phrase density; speaker notes carry full prose.
5. Do not retrieve, generate, or fabricate clinical images. Use placeholders and an image manifest describing what Gabriel should pull from PACS, article figures, or provided files.
6. No memory writes during deck-building unless rehearsal starts. The deck-building phase is artifact creation, not active testing.
7. If rehearsal starts, follow the shared learning-session contract with `--skill "grand-rounds"`.
8. Protect privacy: scrub names, MRNs, DOBs, exact dates, room numbers, contact information, and unnecessary identifiers from case decks and vault notes. Use relative timing such as hospital day, POD, or age decade when possible.
9. The attending angle is first-class. Every deck needs a thesis shaped around the reason the attending picked the case or article.

## Model Compatibility

This command must work for Claude/Sonnet and Gemini/Flash:
- Keep durable workflow logic in this shared command file.
- Use `src/grand_rounds_writer.py` for vault persistence and index upsert.
- For deck creation, use the model's available PowerPoint/PPTX capability:
  - Claude: use the available pptx/PowerPoint skill or toolchain.
  - Gemini: use the Gemini-compatible command environment and local PPTX tooling.
  - Codex: use the PowerPoint skill when available, or the bundled workspace document libraries.
- Output the `.pptx` to `/Users/gabrielreyes/Desktop/<Title>.pptx`.

## Arguments

Supported forms:

```text
/grand-rounds --mode case [--case-log "<filename>"] [--skip-rehearsal]
/grand-rounds --mode article [--pdf "<path>"] [--skip-rehearsal]
```

If `--mode` is missing and cannot be inferred, ask one clarifying question: case presentation or article/journal club?

## Phase 0: Intake

Ask for one generous dump, not a schema. If the user already provided enough information in the command arguments or prior message, proceed.

Case mode prompt:

```text
Dump whatever you have for the case: HPI, exam, imaging descriptions or file paths, differential considered, operative plan, intraop findings, postop course, complications, outcome, why the attending picked this case, and any images you plan to show.
```

Article mode prompt:

```text
Send the PDF path or DOI and whatever you already have: why the attending assigned it, pre-read notes or critiques, the angle to emphasize, and your familiarity with the topic or authors.
```

Parse the dump silently. Do not force the user to fill missing fields.

If `--pdf` is supplied, parse the PDF with available local PDF tooling. If the user names a file path as their case source, read that path directly as intake.

Silently extract:
- `topic`
- `domain`
- `attending_angle`
- `presentation_thesis`
- `possible_phi_markers`

If case intake contains PHI or exact identifiers, do not repeat them. Convert to deidentified presentation language before any outline, deck, manifest, or vault write.

## Phase 1: Landscape Enrichment

Before creating the rubric, build a compact internal landscape note.

Case mode:
- Extract likely pathology, subtype, procedure, anatomy, management controversy, and likely guideline/evidence axis.
- Run focused RAG when useful:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<pathology/subtype management controversy anatomy guideline query>" --stdout --no-frontier
```

Article mode:
- Extract article topic, study design, clinical question, comparator, outcome class, and methodologic risk.
- Retrieve prior evidence, competing studies, guideline context, and common critique points for that design.
- Classify the paper explicitly: RCT, prospective cohort, retrospective cohort, case series, systematic review/meta-analysis, database study, technical note, or translational/basic science.

Use RAG output as context, not as a transcript artifact. Do not show the raw landscape note unless Gabriel asks.

If RAG returns nothing useful, continue from model knowledge and do not fabricate citations.

## Phase 2: Title Gate

After intake and landscape enrichment, propose exactly 3 Title Case titles and ask Gabriel to choose one or ask for alternatives. Do not write files or generate the deck before title confirmation.

Once selected, use the exact confirmed title for:
- Vault file: `Presentations/Cases/<Title>.md` or `Presentations/Articles/<Title>.md`
- Deck path: `/Users/gabrielreyes/Desktop/<Title>.pptx`

## Phase 3: Internal Rubric

Synthesize an internal rubric from:
- Expected norms for the presentation type.
- The landscape note.
- Gabriel's intake and attending angle.

Structure the rubric internally:
- Must-haves: absence will hurt the presentation.
- Strongly enhances: expected by an educated neurosurgical audience.
- Nice-to-have: deepens the presentation but is optional.

For each item, track `covered`, `partial`, or `missing`. Do not show the raw rubric.

Article-mode rubric must include:
- Study design and design-appropriate critique.
- PICO or equivalent research question.
- Endpoint hierarchy and clinical importance.
- Bias, confounding, selection effects, crossover/loss to follow-up, or missing-data threats as applicable.
- Statistical interpretation of the primary endpoint and whether the result is clinically meaningful.
- Internal validity versus external validity.
- Practice impact: should this change Baylor neurosurgery practice, change counseling, or remain hypothesis-generating?
- One defendable journal-club question per major limitation.

Case-mode rubric must include:
- Why this case is educational, not just interesting.
- Decision point and alternatives.
- Operative/anatomic or management consequence.
- Outcome, complication, or follow-up lesson.
- What the presenter should not overclaim.

## Phase 4: Gap Probe

Ask only about gaps, grouped by priority. No teaching and no mini-lectures.

Use this voice:

```text
Before I draft the deck, a few things would strengthen this. Do you have any of the following? No worries if not; I will note the absence so you are ready if asked.

- <gap 1>
- <gap 2>
- <gap 3>
```

Rules:
- User may answer "have it", "do not have it", "partial", or "skip".
- For absent must-haves, record a presentation risk for later.
- Run one probe round by default.
- If the user adds meaningful new material, re-audit silently and do at most one second probe.
- Hard cap: two probe rounds.

## Phase 5: Content Outline

Draft the presentation content before building slides.

Each slide node should include:
- Slide title.
- Slide archetype.
- Intended slide content.
- Speaker notes in full prose.
- Image placeholder or diagram suggestion, if useful.
- Citation anchor, if applicable.

Use slide archetypes instead of fixed templates:
- Case hook
- Illness script
- Imaging sequence
- Decision fork
- Operative anatomy
- Procedure timeline
- Postop course timeline
- Complication learning point
- Evidence ladder
- Methods flow
- Results table
- Forest plot or endpoint interpretation
- Bias map
- Practice impact
- Faculty Q&A

Case deck shape:
1. Opening hook and case reason.
2. Presentation and exam.
3. Imaging/workup sequence.
4. Differential and decision point.
5. Management options and rationale.
6. Intervention or operation.
7. Outcome and complications.
8. Teaching points.
9. Anticipated faculty questions.

Article deck shape:
1. Clinical problem and why this article matters.
2. Prior evidence and unanswered question.
3. Study question/PICO.
4. Methods and cohort/trial flow.
5. Results that matter clinically.
6. Endpoint interpretation and statistical meaning.
7. Validity and limitations.
8. How it changes or does not change practice.
9. Critique and anticipated faculty questions.

Presentation risks from Phase 4 belong in anticipated questions and in the vault file's `## Presentation Risks` section, not as alarming slide warnings.

Add a private `## What Not To Say` section for:
- Unsupported causal claims.
- Overstated practice-changing conclusions.
- Weak or speculative mechanistic bridges.
- Areas where the clean answer is "uncertain" or "hypothesis-generating."
- Case details that are missing and should not be invented.

## Phase 6: Deck Generation

Generate an editable `.pptx` at:

```text
/Users/gabrielreyes/Desktop/<Title>.pptx
```

Deck requirements:
- Visual-first layout.
- Minimal slide text.
- Full prose speaker notes.
- Image placeholders with explicit captions, for example: `INSERT: sagittal T2 MRI showing tonsillar descent`.
- No invented clinical images.
- No fixed slide count, word count, or image quota.
- Keep departmental tone: polished, restrained, educational, not marketing-like.

If the model lacks a native PPTX skill, use available local document libraries to create an editable deck rather than saving only Markdown.

## Phase 6a: Deck Quality Gate

Before saving final artifacts, audit the outline and deck against this gate:

1. Every slide has exactly one job and a declared archetype.
2. No slide is a paragraph dump; dense prose belongs in speaker notes.
3. Every image placeholder appears in the image manifest.
4. Every citation used on slides appears in the citation list.
5. Every citation in the note supports an actual claim.
6. Anticipated questions include absent must-haves and attending-angle risks.
7. The `## What Not To Say` section covers overclaims and uncertainty.
8. Case mode has no PHI or exact identifiers.
9. Article mode has design-specific critique, internal/external validity, endpoint interpretation, and practice impact.

If any gate fails, fix the artifact before writing. Do not ask Gabriel to debug formatting or missing sections.

## Phase 7: Vault Write

Write the presentation note using `src/grand_rounds_writer.py`. The body must include:

```markdown
**Mode**: Case | Article
**Deck**: [<Title>.pptx](/Users/gabrielreyes/Desktop/<Title>.pptx)
**Attending Angle**: <why this was assigned or selected>
**Thesis**: <one-sentence presentation thesis>

## Presentation Arc

## Slide Outline and Speaker Notes

## Study Design and Methods

For article mode only. Omit this section in case mode.

## Methods Critique

For article mode only. Omit this section in case mode.

## Clinical Impact

For article mode only. Omit this section in case mode.

## Citation List

## Image Manifest

## Anticipated Questions

## Presentation Risks

## What Not To Say
```

Rules:
- No H1.
- Bottom YAML only.
- Title Case filename.
- Case files go in `Presentations/Cases/`.
- Article files go in `Presentations/Articles/`.
- Upsert `Presentations/INDEX.md`.
- The writer rejects obvious PHI in case mode and can enforce the quality gate with `--require-quality-gate`.
- The writer creates `data/Sessions/grand_rounds_<slug>_manifest.json`; use it as the recovery/rehearsal state if context gets long.

Writer call:

```bash
python3 src/grand_rounds_writer.py \
  --action create \
  --mode "<case|article>" \
  --title "<confirmed title>" \
  --topic "<specific topic>" \
  --domain "<domain>" \
  --summary "<one-line summary>" \
  --deck-path "/Users/gabrielreyes/Desktop/<Title>.pptx" \
  --attending-angle "<attending angle>" \
  --citations "<citation 1>; <citation 2>" \
  --image-count <N> \
  --slide-titles "<slide 1>; <slide 2>" \
  --image-manifest "<placeholder 1>; <placeholder 2>" \
  --presentation-risks "<risk 1>; <risk 2>" \
  --anticipated-questions "<question 1>; <question 2>" \
  --require-quality-gate \
  --body "<rendered markdown body>" \
  --quiet
```

If the file already exists, ask before overwriting.

## Phase 8: Concept Extraction and Hook

Extract 2-5 atomic concepts from the presentation content when they are useful as future wikilink targets and not already in `Concepts/`. Follow the repository's concept extraction rules.

## Phase 9: Optional Rehearsal

After the deck and note are saved, ask once:

```text
Presentation is saved and ready for offline review. Want to run through it now? I can quiz you on likely faculty questions, probe weak spots, and surface gaps in your own understanding of the material.
```

If no, stop cleanly.

If yes, ask Gabriel to choose one rehearsal mode:
- **Faculty Q&A**: short, adversarial defense of decisions, critique, limitations, and missing must-haves.
- **Talk Run-Through**: slide-by-slide transitions, timing, sequencing, and where the speaker notes are too thin or too long.

Then:
1. Set `SESSION_TS` and run `study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2`.
2. Use anticipated questions as the first question bank.
3. In Faculty Q&A, probe article critique, decision rationale, teaching points, and skipped nice-to-have terrain.
4. In Talk Run-Through, move slide by slide: ask Gabriel for the transition and thesis of the next slide, then tighten delivery.
5. Ask one question at a time and stop after each question.
6. Log every committed answer via `study_memory.py log-answer --skill "grand-rounds"`.
7. At completion, append `## Rehearsal Notes - <date>` to the vault note:

```bash
python3 src/grand_rounds_writer.py \
  --action append-rehearsal \
  --target "Presentations/<Cases|Articles>/<Title>.md" \
  --notes "<rehearsal notes>" \
  --weak-spots "<spot 1>; <spot 2>" \
  --quiet
```

8. Run `study_memory.py end-session` with rehearsal weak spots and next rehearsal strategy.

## Failure Handling

- No PDF for article mode: proceed from DOI, notes, model knowledge, and RAG; add `Unable to verify article specifics without PDF` to presentation risks.
- Sparse case intake: proceed, but the gap probe will be longer and presentation risks may be substantial.
- RAG failure or empty retrieval: continue without citations from RAG and do not invent them.
- PPTX generation failure: still write the vault note and clearly state that the deck file was not created.
