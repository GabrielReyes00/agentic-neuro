---
name: generate_report
description: Multi-agent research report generator — decomposes a neurosurgical topic into sequential web-research sub-tasks, supplements with optional textbook RAG, and synthesizes a comprehensive reference report.
---

# /generate-report — Multi-Agent Research Report Generator

Goal: one high-quality report at `/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Reports/<Human Readable Title>.md`

Operating model: web-primary evidence, textbook-supplemental context, single synthesis pass in main agent. All §7 session-end hooks mandatory (preflight, concept extraction, post-session hook).

## Global Rules

1. No research sub-tasks until user approves plan
2. Sequential sub-tasks only (never parallel)
3. Every factual claim requires inline citation
4. Exclude Wikipedia, blogs, patient-facing sites, social media, uncited AI summaries
5. `[citation needed]` for unverifiable claims

## Phase 0: Pre-Flight (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && ./src/preflight.sh "$QUERY"
```

Use learner context for depth calibration only.

## Phase 1: Research Plan

### 1.1 Classify Archetype

One of: procedure, pathology, device, pharmacology, molecular, anatomy, syndrome, emerging research, outcomes, systems/quality.

### 1.2 Select Modules (5-8)

Pool: Epidemiology, Mechanism/Pathophysiology, Molecular/Genetic, Anatomy/Surgical anatomy, Clinical presentation/Diagnosis, Classification, Imaging/Workup, Surgical technique, Device specs/FDA, Pharmacology/Dosing, Comparative analysis, Evidence base/Landmark trials, Complications, Outcomes/Prognosis, Guidelines/Consensus, Emerging directions, Clinical decision framework.

### 1.3 Decompose Agents

Narrow: 2-3 | Medium: 3-4 | Broad: 4-6. Always include Historical Context agent. Non-overlapping scope, assigned modules, source priorities.

### 1.4 Present Plan + Ask Approval

Show archetype, modules, agent scopes, synthesis path. Ask: "Textbook RAG supplement? (yes/no)" → store as `rag_opted_in`. Do not proceed without approval.

## Phase 2: Run Research Sub-Tasks

### 2.1 Create Temp Directory

```bash
TEMP_DIR="/tmp/neuro-report-$(date +%s)" && mkdir -p "$TEMP_DIR" && echo "$TEMP_DIR"
```

### 2.2 Module Agents (Sequential)

Each sub-task prompt must include: `RESEARCH TOPIC`, `YOUR SCOPE`, `YOUR OUTPUT FILE` (in TEMP_DIR), module list with target depth (300-800 words/module), source priority, citation format, write protocol.

#### Source Priority

1. PubMed/PMC  2. Society guidelines (AANS/CNS/AAN/NCCN/AHA-ASA)  3. UpToDate  4. Cochrane  5. ClinicalTrials.gov  6. Manufacturer/FDA  7. NeurosurgeryAtlas  8. Peer-reviewed journals

#### Citation Format

`[Author et al., Year](URL)` for literature, `[Society, Year](URL)` for guidelines, `[UpToDate: "Title", accessed YYYY-MM-DD]` for UpToDate. Mark unverifiable: `*[citation needed]*`. Never fabricate citations or construct PubMed URLs from memory.

#### Citation Integrity

Copy PMIDs VERBATIM from search tool results. NEVER construct pubmed URLs from memory. No real PMID from tool → cite source URL or `*[citation needed]*`.

#### Citation Registry (Required in every output file)

Before `STATUS: COMPLETE`:
```
## CITATION REGISTRY
PMID:12345678 | [Author et al., Year] | Article Title
URL:https://... | [Author et al., Year] | Source title (non-PubMed)
```

#### Write Protocol

Search → write → search → write. Never back-to-back searches without writing. If blocked: write findings, try one alternative, write again, move on. Output ends with `STATUS: COMPLETE`.

### 2.3 Historical Context Agent

500-1000 words: timeline, seminal contributions, paradigm shifts, abandoned approaches, lineage to current practice.

### 2.4 Fallback

If sub-task workflow fails repeatedly, continue direct-research in main context.

## Phase 3: Verify Output

For each file: confirm substance, confirm `STATUS: COMPLETE`, re-run one retry if weak.

## Phase 4: Optional Textbook RAG

Skip if `rag_opted_in = false`.

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/lance_retriever.py compare "$CONCEPT_QUERY" --no-frontier --output "$TEMP_DIR/rag_context.md"
```

Use `--append` for subsequent queries. Keep anatomy/mechanistic/historical depth. Exclude stale treatment guidance.

## Phase 5: Synthesize Report

### 5.1 Read all agent outputs + optional `rag_context.md`

### 5.1.5 Citation Audit (Mandatory)

1. Extract all CITATION REGISTRY entries across agents
2. Verify each PMID via search tool (author+year match → VERIFIED; mismatch → replace with `*[citation needed — PMID mismatch]*`; not found → `*[citation needed — PMID not found]*`)
3. URL-only entries: accept as-is
4. Build verified citation map for report writing
5. Report audit result in one line

No CITATION REGISTRY in agent output → treat all its PubMed citations as `*[citation needed — unverified]*`.

### 5.2 Cross-Reference Discovery

Per §5 pre-write guards. Build wikilinks for `## Related in This Vault`.

### 5.3 Write Report

Title Case filename, no H1, metadata YAML at bottom (`title`, `date`, `domain`, `topic_type`, `key_terms`, `clinical_context`, `related_reports`, `tags`).

**Mandatory Header (First line of file):**
`Generation Mode: [+RAG]` (if `rag_opted_in = true`) OR `Generation Mode: [-RAG]` (if `rag_opted_in = false`)

Required sections: `## TL;DR` (3-5 bullets) → `## Clinical Utility & Quick Reference` → dynamic content sections → `## Contradictions & Evolving Consensus` → `## Synthesis & Integration` → `## Confidence Assessment` → `## Related in This Vault`.

Quality: cohesive prose, preserve quantitative data, resolve contradictions, separate strong vs weak evidence.

## Phase 6: Cleanup, Index, Logging

1. `rm -rf "$TEMP_DIR" && rm -f data/Sessions/learner_context.json`
2. Upsert `Reports/INDEX.md` with wikilinks
3. `log_study` with key topics, depth 3
4. Extract 3-8 concepts per §7
5. Post-session hook per §7 (hard verification)

## Phase 7: Present to User

Return: TL;DR, TOC, source composition, cross-references, verification status, file path. Do not dump full report into chat.
