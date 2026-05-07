# Generate Report

Use for explicit requests for a comprehensive neurosurgical research report. Do not use for ordinary clinical questions.

Goal: one cited report at `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Human Readable Title>.md`.

## Hard Rules

1. No research agents or subtasks before user approves the plan.
2. Web evidence is primary; local textbook RAG is supplemental.
3. Exclude Wikipedia, blogs, patient-facing sites, social media, and uncited AI summaries.
4. Every factual claim needs an inline citation or `*[citation needed]*`.
5. Copy PMIDs and URLs from tools verbatim. Never construct PubMed URLs from memory.
6. Agent outputs must include a citation registry and end with `STATUS: COMPLETE`.
7. Final report has no H1 and starts with `Generation Mode: [+RAG]` or `Generation Mode: [-RAG]`.

## Phase 0: Preflight

```bash
python3 src/study_memory.py recall --topic "<query topic>"
```

Use recall output only for depth calibration — skip basics for known concepts.

## Phase 1: Plan

Classify the topic: procedure, pathology, device, pharmacology, molecular/genetic, anatomy, syndrome, emerging research, outcomes, or systems/quality.

Select 5-8 modules from: Epidemiology, Mechanism/Pathophysiology, Molecular/Genetic, Anatomy/Surgical Anatomy, Clinical Presentation/Diagnosis, Classification, Imaging/Workup, Surgical Technique, Device Specs/FDA, Pharmacology/Dosing, Comparative Analysis, Evidence Base/Landmark Trials, Complications, Outcomes/Prognosis, Guidelines/Consensus, Emerging Directions, Clinical Decision Framework.

Present archetype, modules, subtask scopes, synthesis path, and ask whether to include textbook RAG. Wait for approval.

## Phase 2: Research Subtasks

Create a temp directory:

```bash
TEMP_DIR="/tmp/neuro-report-$(date +%s)" && mkdir -p "$TEMP_DIR" && echo "$TEMP_DIR"
```

Use native independent subtasks in parallel when the runtime supports safe isolated workers; otherwise run them sequentially. Each subtask owns an output file in `TEMP_DIR`.

Each subtask prompt includes topic, scope, output path, module list, source priority, citation format, write protocol, and quality bar.

Source priority: PubMed/PMC, society guidelines, UpToDate, Cochrane, ClinicalTrials.gov, manufacturer/FDA, NeurosurgeryAtlas, peer-reviewed journals.

Write protocol: search, write, search, write. Never perform back-to-back searches without writing interim findings. If blocked, write what is available, try one alternative, write again, then move on.

Always include a historical context task covering origin, paradigm shifts, abandoned approaches, and lineage to current practice.

## Phase 3: Verify Outputs

For each output file, confirm substance, citation registry, and `STATUS: COMPLETE`. Retry once if weak. If subtask workflow fails repeatedly, continue direct research in the main context.

## Phase 4: Optional Textbook RAG

Skip if the user declined RAG. Otherwise identify 2-4 anatomy, mechanism, or classical teaching concepts:

```bash
python3 src/lance_retriever.py compare "$CONCEPT_QUERY" --no-frontier --output "$TEMP_DIR/rag_context.md"
```

Use `--append` for later queries. Exclude stale treatment guidance.

## Phase 5: Synthesize

Read all subtask files and optional RAG context. Audit citations:

1. Extract every registry entry.
2. Verify PMIDs with a search or metadata tool.
3. Mismatches become `*[citation needed - PMID mismatch]*`.
4. Missing PMIDs become `*[citation needed - PMID not found]*`.
5. URL-only entries are accepted as-is.

Write the report with: generation mode line, TL;DR, clinical utility/quick reference, dynamic content sections, contradictions/evolving consensus, synthesis/integration, confidence assessment, related vault links, and metadata YAML at bottom.

Quality: cohesive prose, preserved quantitative data, explicit comparisons, honest uncertainty, textbook content woven into relevant sections.

## Phase 6: Finish

Delete only the temp report directory, update `Reports/INDEX.md`, and extract 3-8 concepts per the concept extraction protocol.

Present only TL;DR, table of contents, source composition, cross-references, verification status, and file path. Do not dump the full report into chat.
