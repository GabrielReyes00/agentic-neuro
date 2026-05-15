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
- No "studies suggest," "is known to," "recent evidence indicates," "research has shown," "in conclusion," "it is important to note." Replace each with a specific cited claim.
- No bare wikilinks invented from intuition — every `[[Note Name]]` must appear in the Step 2 vault scan.
- No PMID or DOI constructed from memory — copy from tool output verbatim.
- No `_v2`, `(updated)`, or date-stamped filenames when regenerating an existing report — overwrite in place.

---

## Pre-Research Setup

### Step 0: Resolve the topic

Derive a Title Case slug from the user's request. If the topic is genuinely ambiguous (e.g., "report on aneurysms" with no localizer or context), ask one clarifying question. Otherwise infer scope and proceed.

If `Reports/<Title>.md` already exists, treat the request as a regeneration: overwrite the file in place, refresh INDEX.md, and replace any concept stubs that are now stale. Do not create date-stamped variants or `_v2` files.

### Step 1: Related-report discovery (silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/study_memory.py summary --topic "<topic>" --limit 8 --scaffold-limit 2
```

The sole purpose of memory summary here is to surface existing related memory/report anchors on overlapping subject matter so the new report can reference them via wikilink rather than duplicate their coverage. Do not use summary to assess what the learner knows or to compress depth — these reports are not learner-tailored.

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

**Quality floors (hard minimums).** A report below any of these floors is incomplete — go research more before writing:
- Key Numbers Table: **≥10 rows**, each with a citation.
- Differentiator: **≥5 contrasted entities** (or ≥5 distinguishing axes for a non-pathology topic).
- Operative walkthrough (when procedural): **≥3 phases** (e.g., setup → bone work → intradural → closure) with named maneuvers.
- Failure modes: **≥6 specific named pitfalls**, each describing the error and its mechanism — not generic cautions.
- Unique citations: **≥8 distinct sources**, mixing PubMed primary literature and textbook RAG.
- Wikilinks: **≥3 inline cross-references** plus the final `## Related in This Vault` section, all verified to resolve.
- Mastery Objectives: `## Mastery Objectives` present with **5-10** testable objectives using action verbs; weak verbs such as "know," "understand," "appreciate," "be familiar with," "review," and "learn" fail the contract.
- Total length: **≥200 lines** of body content for a typical topic; encyclopedic ambition usually pushes 250–350. A short report is a red flag, not a feature.

These are floors, not ceilings. The Sphenoid Wing Meningiomas reference exemplar exceeds every floor — use it as the calibration point.

---

## Research Principles

**Two primary sources, agent picks weighting per section.** The local textbook corpus (`lance_retriever.py compare`) and PubMed/PMC are the two main evidence streams. Decide per section which produced more important or relevant material — anatomy and classical teaching often weigh toward textbook RAG, evidence base and trials toward PubMed. Web search is a supplementary source only for non-published information: society guidelines and consensus statements, FDA approvals and device specifications, ongoing trial registrations, recent position papers not yet indexed in PMC.

**Textbook RAG — use `compare --stdout`.** Each query retrieves, reranks, and distills relevant textbook passages, printing them directly to stdout (no intermediate file). Run one focused query per research thread:

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "<focused concept query>" --stdout --no-frontier
```

**Frontier decision — agent determines.** Use `--no-frontier` for established clinical knowledge (anatomy, classic management, standard surgical approaches). Omit the flag when the topic involves recent developments, novel techniques, or evolving evidence where PMC literature adds value.

**Using retrieved passages.** Passages land directly in your context from the bash output. Extract specific facts, thresholds, citations, and operative details — then synthesize them into your own prose. Cite textbook sources inline at the point of claim (e.g., "Youmans 8th Ed., Ch. 37, p. 777"). Do not restructure report sections around passage order or parrot passage text verbatim. Run multiple focused queries across different research threads rather than one broad query.

Use subtasks freely when the topic has independent research threads (e.g., separate evidence base for clipping vs. coiling, separate molecular vs. operative threads on a tumor). Subtasks are a tool, not a workflow — no temp-directory ceremony, no write-protocol micromanagement, no verify gate. Spawn them when parallel research is genuinely faster, integrate their output, and move on.

**Density over coverage.** A paragraph integrating three sources beats three paragraphs each summarizing one source. Prefer specifics over generalities: thresholds, percentages, named maneuvers, page references, named trials, named series.

**Citations always, at the point of claim.** Every quantitative claim, every recommendation, every mechanism, every "current understanding" assertion is cited inline with PMID, DOI, or textbook + page. Copy PMIDs and URLs from tools verbatim — never construct PubMed URLs from memory. Exclude Wikipedia, blogs, patient-facing sites, social media, and uncited AI summaries. If a claim cannot be sourced, either drop it or label it explicitly as "expert consensus, unsourced."

**Hyperlink every PMID and DOI.** Linkable identifiers must be rendered as clickable markdown links so the reader can open the source in one click. Use these forms:
- `[PMID 26738503](https://pubmed.ncbi.nlm.nih.gov/26738503/)`
- `[DOI 10.1007/s12028-015-0224-8](https://doi.org/10.1007/s12028-015-0224-8)`
- Preferred for table Source columns and inline body citations: wrap the author-year label itself as the link text — `[Anderson et al., 2013](https://doi.org/10.1056/NEJMoa1214609)`. This is the AChA Aneurysms exemplar pattern: one clickable label per citation.

**Key Numbers Source column.** Every row in the `### Key Numbers at a Glance` table must have a clickable Source cell when the underlying source is a journal article or trial publication. The Source column is the most-used reference surface in the report — leaving it as plain text defeats its purpose. Pure textbook citations (`Youmans 8th Ed, p. 777`, `Greenberg Handbook of Neurosurgery, p. 799`) remain plain text because they are not linkable. Guideline document references without an attached PMID/DOI also remain plain. Pre-1980 historical references (e.g., `Cushing 1901`, `Simpson 1957`) predate PubMed indexing and are exempted by the validator.

Raw tokens like `PMID:26738503` or `DOI:10.1007/...` without a link wrapper are a formatting failure. The validator enforces this — `python3 src/report_validator.py` fails on (a) any raw PMID/DOI token outside a markdown link, and (b) any Key Numbers Source cell that has a journal-style `Author YEAR` or `Author et al., YEAR` citation but no hyperlink.

**Honest uncertainty.** Surface controversy and evolving consensus rather than averaging. If two large series disagree on an outcome rate, report both and identify the methodological difference. If a guideline lags the literature, say so.

**Encyclopedic ambition.** If something material is missing from your draft, find it. The output is meant to be a one-stop reference — gaps in coverage are quality failures, not acceptable trade-offs.

---

## Self-Audit Before Write

This is the intelligence layer of this skill. Before committing the file, read your own draft end-to-end and validate:

- **Opening block** — H2 `## Clinical Utility & Quick Reference` present with all four required children (blockquoted TL;DR, `### When to Reference This Report`, `### Key Numbers at a Glance` with the canonical `| Parameter | Value | Context | Source |` table header, `### Decision Framework` as numbered bolded steps), in that order. After writing, run `python3 src/report_validator.py "/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Title Case Title>.md"` to confirm structural compliance for the target report — its exit code is binary.
- **Comprehensiveness** — every Mandatory Element from the Quality Contract is present, or its absence is justified by the topic.
- **Density** — the prose integrates sources rather than serial-summarizing them. No padding sections, no encyclopedic-history filler when operational depth is missing.
- **Citation integrity** — every quantitative claim, every recommendation, every mechanism is cited. The cited source actually supports the claim made (semantic check, not string match). PMIDs and DOIs are verbatim from the source tool, not constructed.
- **Specificity** — the prose names thresholds, percentages, named maneuvers, page references, named series. No "studies suggest," no "is known to," no "recent evidence indicates."
- **Mastery Objectives** — `## Mastery Objectives` contains 5-10 testable objectives, uses strong action verbs, avoids weak verbs, and maps to management-changing discriminators, thresholds, mechanisms, complications, anatomy-risk relationships, or operative decisions from the report body.
- **Wikilinks resolve** to real vault notes from your Step 2 vault scan. No invented filenames — verify each `[[...]]` against the scan output before writing.
- **Voice** — reads like an expert reference chapter, not an AI summary. No "in conclusion," no "it is important to note," no narrator commentary.
- **No learner-tailoring leakage** — the report does not address "you," does not mention PGY level, does not skip content because something might be assumed.

This is not a checklist gate. If the draft fails the contract on any axis, re-research and rewrite the deficient sections. The agent owns this judgment — there is no external verifier downstream.

**Stop-and-research trigger.** If during self-audit you find the draft below any Quality Floor, do NOT write the file with a note like "more research needed." Run additional `lance_retriever.py compare --stdout` queries on the deficient topic, do additional PubMed searches, and rewrite the section to floor before committing.

---

## Finish

1. **Write the file** to `Reports/<Title Case Title>.md`. No H1 header — the filename is the title in Obsidian. Start with the opening `## Clinical Utility & Quick Reference` block. End the body with topic sections, `## Mastery Objectives`, `## Related in This Vault`, and a YAML metadata block at the bottom (per CLAUDE.md §1).

2. **Update `Reports/INDEX.md`** with the new entry per the standard table format.

3. **Concept extraction** per CLAUDE.md §7c — identify 2–5 atomic concepts not already in `Concepts/` and write each as its own concept stub.

4. **Log to memory** so downstream `/study-review` and future `/generate-report` runs can discover this report. Two calls in sequence — `log-answer` creates a topic-indexed memory anchor entry, then `end-session` records the summary and next-strategy directive:

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
  --next-strategy "<actionable hint for downstream review/study tools>"
```

The `--next-strategy` should name what is most worth studying from this report next. Examples:
GOOD: "Quiz on AChA cisternal subdivisions and perforator-vs-AChA-origin discrimination; oral-board defense on contemporary clipping vs coiling outcomes."
GOOD: "Drill EVD waveform troubleshooting algorithm; transfer to ICP refractoriness decision points."
BAD: "Review this report."

5. **Surface to user**: TL;DR, file path, source mix (textbook vs PubMed vs web, rough proportions), Quality Contract checklist result (which Mandatory Elements are present, which were intentionally omitted and why), wikilinks added. Do not dump the full report into chat.
