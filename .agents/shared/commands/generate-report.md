# Generate Report

Produce an encyclopedic, citation-dense reference document on a neurosurgical topic — a personalized textbook chapter that captures the current expert understanding from all available sources. The output is reference truth, not a learner-tailored study aid.

The resident reading this report should not need another source to develop deep, comprehensive understanding of the topic. Density is the primary quality metric.

---

## Role and Output

You are an expert research synthesizer. Your output is a single Markdown file at `Reports/<Title Case Title>.md` in the Obsidian vault. The file is encyclopedic in ambition, operational where the topic warrants, and grounded in citations at the point of every claim.

Do not address the learner. Do not mention PGY level or any individual's prior knowledge. Do not skip foundational material because it might already be known. The report is written for the topic, not for a person.

**Reference exemplar.** The gold-standard output for this skill is `Reports/Sphenoid Wing Meningiomas.md` in the vault — read its first 40 lines if you need a structural and tonal anchor before writing. Match or exceed its density, citation specificity, differentiator coverage, and operative detail. For the opening Clinical Utility & Quick Reference block specifically, follow `Reports/Temporal ICH Management.md` as the structural exemplar.

**Anti-patterns — do NOT do any of these.** They are residue from prior versions of this skill or from generic AI-summary writing:
- No `Generation Mode: [+RAG]` or `[-RAG]` header (legacy tag — banned). When RAG was actually used during generation, emit the sanctioned callout instead: `> [!info] RAG Supplemented` placed immediately above the opening H2, with a one-line description on the next blockquote line. Absence of the callout signals no RAG was used. No `STATUS: COMPLETE` markers. No "citation registry" appendix. No phase numbering in the file.
- No H1 title at the top (filename is the title in Obsidian); no YAML at the top (YAML goes at the bottom).
- No "you," "the learner," "the resident should know," PGY-level qualifiers, or assumed-knowledge skips.
- No repo-workflow leakage: do not discuss source cards, query rewriting, coverage ledgers, gap repair, raw-source audits, validators, or RAG internals in the final report body. Those belong in `data/Sessions/<Title>/` artifacts and final user summaries, not in clinical reference prose.
- No "studies suggest," "is known to," "recent evidence indicates," "research has shown," "in conclusion," "it is important to note." Replace each with a specific cited claim.
- No bare wikilinks invented from intuition — every `[[Note Name]]` must appear in the Step 2 vault scan.
- No PMID or DOI constructed from memory — copy from tool output verbatim.
- No `_v2`, `(updated)`, or date-stamped filenames when regenerating an existing report — overwrite in place.

---

## Modular Workflow Authority

This file is the public command contract and orchestrator. Detailed post-retrieval instructions live in focused modules. Read the relevant module freshly when reaching each checkpoint:

- `.agents/shared/commands/generate-report-research-plan.md` — query best practices, topic-archetype classification, required/optional/not-applicable report domains, and planned retrieval queries.
- `.agents/shared/commands/generate-report-research.md` — `source_cards.jsonl`, non-RAG source-card normalization, and `coverage_ledger.json`.
- `.agents/shared/commands/generate-report-synthesis-map.md` — compact-but-dense `report_knowledge_map.json` built from source cards and the coverage ledger.
- `.agents/shared/commands/generate-report-finalize.md` — write from the synthesis map, run `report_validator.py --coverage-ledger`, update INDEX, concepts, memory, and final user summary.

Do not copy the full `/intraoperative-guide` workflow. Reports need structured coverage control, not mandatory reviewer subagents, operative verdict chains, or attending-question gates. Optional review is appropriate only for unusually large, high-stakes, or controversy-heavy reports.

## Structured Artifact Rule

The final report must be written from structured post-retrieval artifacts, not directly from raw RAG dumps. Raw retrieval output may be consulted for a narrow citation dispute, but ordinary synthesis flows through:

1. `report_research_plan.json`
2. `source_cards.jsonl`
3. `coverage_ledger.json`
4. `report_knowledge_map.json`
5. final report prose

If `coverage_ledger.json` contains any required block with `status: gap`, do not write the final report. Run targeted retrieval or explicitly repair scope until the ledger has no required gap statuses. `report_validator.py --coverage-ledger` enforces this as a final gate.

---

## Pre-Research Setup

### Step 0: Resolve the topic

Derive a Title Case slug from the user's request. If the topic is genuinely ambiguous (e.g., "report on aneurysms" with no localizer or context), ask one clarifying question. Otherwise infer scope and proceed.

If `Reports/<Title>.md` already exists, treat the request as a regeneration: overwrite the file in place, refresh INDEX.md, and replace any concept stubs that are now stale. Do not create date-stamped variants or `_v2` files.

Create the report session directory at the start of the run:

```bash
cd /Users/gabrielreyes/agentic-neuro && \
mkdir -p "data/Sessions/<Title>"
```

### Step 1: Related-report discovery (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2 --include-curated
```

The sole purpose of memory summary here is to surface existing related memory/report anchors on overlapping subject matter so the new report can reference them via wikilink rather than duplicate their coverage. `--include-curated` lets curated cross-session summaries also surface — useful for noticing if a thematic pattern (e.g., "stroke BP thresholds remain a fault line") suggests the new report should foreground that material. Do not use summary to assess what the learner knows or to compress depth — these reports are not learner-tailored.

### Step 2: Vault scan for cross-citation targets (silent)

```bash
ls "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Operative Guides/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Study Material/"*.md \
   "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Concepts/"*.md 2>/dev/null
```

Identify wikilink targets relevant to this topic. Use them as inline references and citations within the prose, and list them in a final `## Related in This Vault` section.

---

## Quality Contract

The report MUST contain the following content elements. The agent decides depth, ordering, prose form, and section names based on what the topic demands. A vascular pathology, a functional indication, a device, an anatomic concept, a controversy, and a technique each shape the structure differently — let the topic dictate, not a template. The opening block below is the single exception: it is fixed in structure and naming.

- **Opening block** — every report opens with a single H2 `## Clinical Utility & Quick Reference` containing, in this exact order:
    1. A blockquoted TL;DR: `> **TL;DR:** …` (3–6 sentences).
    2. `### When to Reference This Report` — bulleted list of triggering clinical scenarios.
    3. `### Key Numbers at a Glance` — table with header `| Parameter | Value | Context | Source |` (≥10 rows per the floor below).
    4. `### Decision Framework` — numbered, named steps with bolded step labels (`1. **Step Name:** …`). Not a code block; not a flowchart.

    `Reports/Temporal ICH Management.md` is the structural exemplar for this block.
- **TL;DR** — three to six sentences capturing the most important current understanding of the topic (renders as the blockquote in the opening block above).
- **Key Numbers Table** — quantitative anchors a reader should be able to recall: incidence, thresholds, outcome rates, named values, with a citation per row.
- **Differentiator** — explicit contrast with related entities, approaches, or concepts the topic could be confused with or conflated against. Broad framing accommodates pathology differentials, technique comparisons, device alternatives, anatomic neighbors, indication overlaps. Organize by the feature that distinguishes (e.g., "DBS for OCD targets the ventral capsule/ventral striatum, whereas ablative anterior capsulotomy lesions the anterior limb — different mechanism of effect, different side-effect profile, different reversibility").
- **Operative walkthrough** when the topic is procedural — among the most important sections when applicable. Step sequence, named maneuvers and their indications, intraoperative tests of success (electrophysiology, ICG, neuromonitoring expectations), bail-outs, what to do when bleeding obscures landmarks or anatomy is anomalous, closure considerations.
- **Common failure modes and pitfalls** — specific known errors, complications-from-error, sources of misinterpretation. Concrete (e.g., "the most common identification error in AChA clipping is mistaking a lenticulostriate perforator for the AChA itself; ICG can be falsely reassuring if perfusion is preserved through collaterals"), not generic ("be careful with retraction").
- **Evidence quality labels** on every major recommendation — Level I/II/III/IV, or Guideline / RCT / Cohort / Case Series / Expert Consensus. The reader must be able to tell at a glance whether a recommendation is trial-grade or opinion-grade.
- **Effect-size magnitudes** on every cited trial — absolute risk reduction, NNT, mRS shift, hazard ratios, odds ratios. Never "significant" alone.
- **Mechanism → consequence chains** for any molecular, genetic, or pathophysiologic content. No orphan facts. If a mutation, pathway, or physiologic principle is named, its functional and clinical consequence is stated in the same passage.
- **Mastery Objectives** — a final `## Mastery Objectives` section defining what a reader should be able to do with the report's knowledge under clinical, operative, or oral-board pressure. Use testable action verbs; do not address Gabriel directly.
- **Cross-references** — wikilinks to existing vault notes woven through the prose at the point of relevance, plus a final `## Related in This Vault` section listing the most relevant prior reports, guides, and concepts with one line on the relationship.

If a Mandatory Element is genuinely not applicable to a specific topic (e.g., operative walkthrough on a pure pharmacology report, mechanism→consequence chains on a pure operative anatomy report), state the omission briefly in your self-audit reasoning and proceed.

**Quality floors are content-driven, not count-driven.** A report is incomplete when it lacks the clinical density naturally required by its topic, even if it passes structural validation. Do not use arbitrary citation counts, row counts, line counts, or fixed numbers of pitfalls as a substitute for expert coverage.

Use these topic-shaped floors during self-audit:

- A clinical emergency or ICU topic is incomplete without management-changing thresholds, bedside monitoring parameters, escalation triggers, lesion-level physiology, predictable complications, and handoff-ready failure modes.
- A procedural or operative topic is incomplete without approach logic, anatomy-risk relationships, key maneuvers, intraoperative tests of success, bailouts, and complication mechanisms.
- A pathology or differential topic is incomplete without discriminators against close mimics, natural history, imaging patterns, management consequences, and common diagnostic traps.
- A physiology, molecular, or anatomy topic is incomplete without mechanism-to-consequence chains that explain how the fact changes exam interpretation, imaging, treatment, prognosis, or complications.
- A controversy or evidence-review topic is incomplete without evidence strength, population boundaries, effect size when available, and practical interpretation of conflicting sources.
- Any report is incomplete if useful granular source detail was compressed into generic claims, if high-stakes numbers lack source verification, or if clinical physiology and operational bedside detail were replaced by workflow commentary.

The Sphenoid Wing Meningiomas reference exemplar remains the calibration point: density comes from source-specific clinical substance, not padding.

---

## Research Principles

### Checkpoint 1: Research Plan

Read `.agents/shared/commands/generate-report-research-plan.md` before any retrieval. This module owns query rewriting: transform the user's request into focused search strings per domain rather than passing a vague topic or mixed keyword bag directly into RAG.

Build `data/Sessions/<Title>/report_research_plan.json` before retrieval. The plan classifies the topic archetype and marks each report domain as required, optional, or not applicable. A tumor, vascular pathology, pharmacology topic, device, anatomy report, and trial/controversy review should not use the same required-domain shape.

### Checkpoint 2: Structured Research

Read `.agents/shared/commands/generate-report-research.md`.

Run source retrieval according to the plan and produce:

```text
data/Sessions/<Title>/source_cards.jsonl
data/Sessions/<Title>/coverage_ledger.json
```

The coverage ledger must track required domains such as epidemiology/natural history, pathophysiology/mechanism, anatomy, diagnosis/imaging, management, operative or procedural considerations when applicable, complications/failure modes, outcomes/evidence, controversies/guidelines, differentiators, key numbers, Mastery Objectives, and vault crosslinks. Domains may be marked `not_applicable`, but required domains may not remain `gap`.

### Checkpoint 3: Synthesis Map

Read `.agents/shared/commands/generate-report-synthesis-map.md`.

Build `data/Sessions/<Title>/report_knowledge_map.json` from source cards and the coverage ledger. This map is the synthesis layer: integrated claims, source-card IDs, provenance tiers, key numbers, differentiators, pitfalls, controversies, and planned citations. If mapping exposes a required domain gap, update the ledger and return to research before drafting.

**Two primary sources, agent picks weighting per section.** The local textbook corpus (`lance_retriever.py compare`) and PubMed/PMC are the two main evidence streams. Decide per section which produced more important or relevant material — anatomy and classical teaching often weigh toward textbook RAG, evidence base and trials toward PubMed. Web search is a supplementary source only for non-published information: society guidelines and consensus statements, FDA approvals and device specifications, ongoing trial registrations, recent position papers not yet indexed in PMC.

**Textbook RAG — prefer `compare --card-json` for workflow runs.** Each planned query should emit compact-but-dense source cards with coverage-block labels:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused concept query>" \
  --card-json \
  --card-output "data/Sessions/<Title>/source_cards_q<N>.jsonl" \
  --coverage-block "<domain_id>" \
  --card-prefix "Q<N>-CARD" \
  [--no-frontier]
```

Use `compare --stdout` only for ad-hoc narrow re-checking or citation disputes. The canonical handoff is `source_cards.jsonl`, not a raw RAG transcript.

**Frontier decision — agent determines.** Use `--no-frontier` for established clinical knowledge (anatomy, classic management, standard surgical approaches). Omit the flag when the topic involves recent developments, novel techniques, or evolving evidence where PMC literature adds value.

**Using retrieved sources.** Extract specific facts, thresholds, citations, and operative details into source cards, then synthesize them into `report_knowledge_map.json` before prose. Cite textbook sources inline at the point of claim (e.g., "Youmans 8th Ed., Ch. 37, p. 777"). Do not restructure report sections around passage order or parrot passage text verbatim. Run multiple focused queries across different research threads rather than one broad query.

Use subtasks freely when the topic has independent research threads (e.g., separate evidence base for clipping vs. coiling, separate molecular vs. operative threads on a tumor). Subtasks are a tool, not a workflow — no temp-directory ceremony, no write-protocol micromanagement, no verify gate. Spawn them when parallel research is genuinely faster, integrate their output, and move on.

**Density over coverage.** A paragraph integrating three sources beats three paragraphs each summarizing one source. Prefer specifics over generalities: thresholds, percentages, named maneuvers, page references, named trials, named series. Compression is for removing raw-passage bulk and redundancy, not for removing clinically useful numbers, physiology, anatomy, complications, or operative decision logic.

**Citations always, at the point of claim.** Every quantitative claim, every recommendation, every mechanism, every "current understanding" assertion is cited inline with PMID, DOI, or textbook + page. Copy PMIDs and URLs from tools verbatim — never construct PubMed URLs from memory. Exclude Wikipedia, blogs, patient-facing sites, social media, and uncited AI summaries.

**Provenance tiering — never launder a citation.** Every claim falls in one of three internal tiers, and the reader must be able to tell which claims are source-grounded versus unverified:
- **Source-grounded** — supported by a retrieved RAG passage, PubMed/PMC article, guideline, device document, or textbook page. Cite it inline as above. The cited source must actually support the specific claim (semantic check, not string match) — confirm the retrieved passage is about *this* entity before borrowing its numbers. Misattributing a related condition's statistics (e.g., a cranial DAVF hemorrhage rate applied to a spinal dAVF, or a meningioma radiosurgery dose applied to a vestibular schwannoma) is a citation-laundering failure even though a real source name is attached.
- **Model knowledge — verified** — initially supplied from clinical/model knowledge, then confirmed in a real source during gap-fill. Once verified, cite the confirming source and treat the final prose as source-grounded. The map may keep the `model_knowledge_verified` tier for audit, but the report body does not need an extra label if the citation is accurate.
- **Model knowledge — verify** — clinically useful but not located in any retrieved or confirming source. Keep it only when it adds real value, label it inline as model knowledge, and never attach a textbook/PMID/DOI citation to it. Flag high-stakes specifics with `⚠`: doses, physiologic thresholds, correction-rate ceilings, resection extents, device specs, and quantitative outcome/percentage figures. In the `### Key Numbers at a Glance` table, a model-knowledge value carries `model est. — verify` in the Source cell, never a fabricated citation.

This replaces the older binary "drop it or label expert consensus, unsourced" rule: keep the knowledge, tier it transparently, and flag the specifics worth verifying.

**Hyperlink every PMID and DOI.** Linkable identifiers must be rendered as clickable markdown links so the reader can open the source in one click. Use these forms:
- `[PMID 26738503](https://pubmed.ncbi.nlm.nih.gov/26738503/)`
- `[DOI 10.1007/s12028-015-0224-8](https://doi.org/10.1007/s12028-015-0224-8)`
- Preferred for table Source columns and inline body citations: wrap the author-year label itself as the link text — `[Anderson et al., 2013](https://doi.org/10.1056/NEJMoa1214609)`. This is the AChA Aneurysms exemplar pattern: one clickable label per citation.

**Key Numbers Source column.** Every row in the `### Key Numbers at a Glance` table must have a clickable Source cell when the underlying source is a journal article or trial publication. The Source column is the most-used reference surface in the report — leaving it as plain text defeats its purpose. Pure textbook citations (`Youmans 8th Ed, p. 777`, `Greenberg Handbook of Neurosurgery, p. 799`) remain plain text because they are not linkable. Guideline document references without an attached PMID/DOI also remain plain. Pre-1980 historical references (e.g., `Cushing 1901`, `Simpson 1957`) predate PubMed indexing and are exempted by the validator.

Raw tokens like `PMID:26738503` or `DOI:10.1007/...` without a link wrapper are a formatting failure. The validator enforces this — `python3 src/report_validator.py` fails on (a) any raw PMID/DOI token outside a markdown link, and (b) any Key Numbers Source cell that has a journal-style `Author YEAR` or `Author et al., YEAR` citation but no hyperlink.

**Do not attach PubMed links to textbook labels.** A RAG textbook citation is not a PubMed article. Cite it as book/chapter/page, e.g. `Youmans and Winn 8th Ed, Vol. 5, p. 588`. If the same fact is supported by a PubMed article, cite the actual article label separately, e.g. `[Author et al., 2024](https://pubmed.ncbi.nlm.nih.gov/...)`. Never write `Youmans 8th Ed [PMID: ...]` or `Greenberg [DOI: ...]`; that falsely implies the book passage is the linked online article.

**Honest uncertainty.** Surface controversy and evolving consensus rather than averaging. If two large series disagree on an outcome rate, report both and identify the methodological difference. If a guideline lags the literature, say so.

**Encyclopedic ambition.** If something material is missing from your draft, find it. The output is meant to be a one-stop reference — gaps in coverage are quality failures, not acceptable trade-offs.

**Validation is invisible to the reader.** Query decomposition, source-card compression, coverage-ledger repair, and raw-source audit are how the agent earns trust; they are not topics in the report. Use them to make the clinical reference denser, better cited, and more precise. Never replace clinical physiology, ICU metrics, operative decision logic, or failure-mode detail with workflow commentary.

**YAML metadata and Provenance tracking.** The bottom YAML block MUST contain standard vault metadata as well as explicit process and provenance keys to maintain absolute transparency. Specifically, you must include:
- `internal_knowledge_used: true|false` (set to `true` if any section or claim relies on unverified model knowledge, i.e., `model knowledge — verify`; otherwise `false`).
- `provenance: "<summary>"` (a 1-2 sentence description explaining the source distribution, e.g., "Textbook RAG supplemented with clinical model knowledge for specific management details").
Do not add other process/workflow fields like source-card counts, query counts, or validator status. The validator expects and permits these keys.


---

## Self-Audit Before Write

This is the intelligence layer of this skill. Before committing the file, read your own draft end-to-end and validate:

- **Opening block** — H2 `## Clinical Utility & Quick Reference` present with all four required children (blockquoted TL;DR, `### When to Reference This Report`, `### Key Numbers at a Glance` with the canonical `| Parameter | Value | Context | Source |` table header, `### Decision Framework` as numbered bolded steps), in that order. After writing, run `python3 src/report_validator.py "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Title Case Title>.md" --coverage-ledger "data/Sessions/<Title>/coverage_ledger.json"` to confirm structural and coverage-ledger compliance for the target report — its exit code is binary.
- **Coverage ledger** — `coverage_ledger.json` contains no required block with `status: gap`. Optional or genuinely not-applicable domains are explicitly marked, not silently omitted.
- **Comprehensiveness** — every Mandatory Element from the Quality Contract is present, or its absence is justified by the topic.
- **Density** — the prose integrates sources rather than serial-summarizing them. No padding sections, no encyclopedic-history filler when operational depth is missing.
- **Citation integrity** — every quantitative claim, every recommendation, every mechanism is cited. The cited source actually supports the claim made (semantic check, not string match), and is about the same entity (no related-condition misattribution). PMIDs and DOIs are verbatim from the source tool, not constructed.
- **Provenance tiering** — every substantive claim is either source-grounded (cited) or labelled **model knowledge — verify**; no claim is untiered. No textbook/PMID/DOI citation is attached to model-knowledge content. High-stakes model-knowledge specifics (doses, thresholds, percentages, device specs) carry a `⚠` verify flag, and model-knowledge Key Numbers rows use `model est. — verify` in the Source cell.
- **Specificity** — the prose names thresholds, percentages, named maneuvers, page references, named series. No "studies suggest," no "is known to," no "recent evidence indicates."
- **Mastery Objectives** — `## Mastery Objectives` contains 5-10 testable objectives, uses strong action verbs, avoids weak verbs, and maps to management-changing discriminators, thresholds, mechanisms, complications, anatomy-risk relationships, or operative decisions from the report body.
- **Wikilinks resolve** to real vault notes from your Step 2 vault scan. No invented filenames — verify each `[[...]]` against the scan output before writing.
- **Voice** — reads like an expert reference chapter, not an AI summary. No "in conclusion," no "it is important to note," no narrator commentary.
- **No learner-tailoring leakage** — the report does not address "you," does not mention PGY level, does not skip content because something might be assumed.

This is not a checklist gate. If the draft fails the contract on any axis, re-research and rewrite the deficient sections. The agent owns this judgment — there is no external verifier downstream.

**Stop-and-research trigger.** If during self-audit you find the draft below any Quality Floor or the coverage ledger contains a required `gap`, do NOT write the file with a note like "more research needed." Run additional `lance_retriever.py compare --card-json` queries on the deficient topic, do additional PubMed searches, update source cards and the synthesis map, and rewrite the section to floor before committing.

---

## Finish

Before executing the finish steps, read `.agents/shared/commands/generate-report-finalize.md`.

1. **Write the file** to `Reports/<Title Case Title>.md`. No H1 header — the filename is the title in Obsidian. Start with the opening `## Clinical Utility & Quick Reference` block. End the body with topic sections, `## Mastery Objectives`, `## Related in This Vault`, and a YAML metadata block at the bottom (per CLAUDE.md §1).

2. **Validate the report and coverage ledger**:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/report_validator.py \
  "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Title Case Title>.md" \
  --coverage-ledger "data/Sessions/<Title>/coverage_ledger.json"
```

If validation fails, repair the report or coverage artifacts and rerun validation before claiming success.

3. **Update `Reports/INDEX.md`** with the new entry per the standard table format.

4. **Concept extraction** per CLAUDE.md §7c — identify 2–5 atomic concepts not already in `Concepts/` and write each as its own concept stub.

5. **Log to memory** so downstream `/study-review` and future `/generate-report` runs can discover this report. Two calls in sequence — `log-answer` creates a topic-indexed artifact anchor entry, then `end-session` records the summary and next-strategy directive. This is discoverability/provenance only: `skill="generate-report"` must not be interpreted as learner mastery, an open gap, or curation evidence.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
SESSION_TS=$(date -u +%Y-%m-%dT%H:%M:%S+00:00) && \
python3 src/study_memory.py log-answer \
  --session "$SESSION_TS" \
  --topic "<canonical topic, lowercase, 3-8 words>" \
  --concept "report coverage anchor" \
  --question "What is covered in the <Title> reference report?" \
  --answer "<2-4 sentence outline of the report's coverage>" \
  --correct 2 \
  --doc "Reports/<Title>.md" \
  --skill "generate-report" && \
python3 src/study_memory.py end-session \
  --session "$SESSION_TS" \
  --summary "<1-3 sentence description of what the report covers>" \
  --next-strategy "<actionable hint for downstream review/study tools>" \
  --json
```

Read the JSON output silently. `generate-report` sessions are excluded from curation counting; if the JSON ever reports otherwise, treat it as a memory-layer warning and investigate before running curation.

The `--next-strategy` should name what is most worth studying from this report next. Examples:
GOOD: "Quiz on AChA cisternal subdivisions and perforator-vs-AChA-origin discrimination; oral-board defense on contemporary clipping vs coiling outcomes."
GOOD: "Drill EVD waveform troubleshooting algorithm; transfer to ICP refractoriness decision points."
BAD: "Review this report."

6. **Surface to user**: TL;DR, file path, source mix (textbook vs PubMed vs web, rough proportions), Quality Contract checklist result (which Mandatory Elements are present, which were intentionally omitted and why), coverage-ledger result, validator result, wikilinks added. Do not dump the full report into chat.
