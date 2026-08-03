# Generate Report Research Plan

Use this module after topic resolution, related-memory discovery, and vault crosslink discovery.

## Purpose

Build the coverage plan before retrieval so the report is written from intentional domain coverage rather than whatever the first RAG queries happen to return.

This module also owns query rewriting. Before any RAG, PubMed, guideline, or web search, transform the user's request into focused search strings. Do not pass a vague user topic or a long mixed keyword bag directly into retrieval.

Load `.agents/shared/commands/rag-routing.md` before assigning textbook query
tiers.

Write the canonical plan to:

```text
data/Sessions/<Title>/report_research_plan.json
```

## Query Best Practices

Retrieval quality depends on query shape. Full RAG uses the complete quoted
query for hybrid search, reranking, entity filtering, and distillation; long
keyword bags dilute signal by mixing entities or questions.

### Core Rule

Write one focused query per coverage domain or sub-question. Prefer several precise queries over one mega-query.

Use this pattern:

```text
<core entity> <specific domain/question> <1-3 exact anchor terms>
```

Examples:

```text
acute traumatic spinal cord injury early decompression within 24 hours neurological outcomes
central cord syndrome timing of surgical decompression cervical trauma outcomes
cervical fracture dislocation traumatic spinal cord injury urgent reduction decompression timing
acute spinal cord injury decompression timing guideline 24 hours evidence
```

### Good Query Traits

- Names the **core entity** explicitly: `traumatic spinal cord injury`, `central cord syndrome`, `cervical fracture dislocation`.
- Names the **coverage domain**: timing, imaging, pathophysiology, anatomy, operative management, complications, outcomes, guideline.
- Includes **1-3 anchor terms** that should appear in relevant sources: `within 24 hours`, `decompression`, `neurological outcomes`.
- Uses natural phrase order when possible; dense retrieval and reranking benefit from coherent meaning.
- Uses comparison wording only when comparison is intended: `central cord syndrome versus fracture dislocation decompression timing`.

### Avoid

- Long mixed keyword bags that combine multiple subtypes, interventions, and outcomes in one string.
- Abbreviations alone when the expanded term matters (`SCI` alone is weaker than `traumatic spinal cord injury`; using both is acceptable when common).
- Adding every synonym to every query. Put synonyms in separate targeted queries when needed.
- Query strings that name a broad topic with no domain (`spinal cord injury`) unless doing an initial inventory pass.

### Query Splitting Heuristic

Split the user's request when it contains:

- Multiple entities: `central cord syndrome`, `fracture dislocation`, `acute SCI`.
- Multiple decisions: timing, approach, reduction, ICU management.
- Multiple evidence domains: guideline, trial outcomes, textbook anatomy, complications.
- A subtype and a parent entity where each deserves its own evidence base.

### Source Targeting

- Use `textbook_mini` for a named scale, score, classification, staging system,
  defining table, or compact reference.
- Use `textbook_full` for anatomy, classic disease mechanisms, standard
  management, operative anatomy, and durable synthesis.
- Use PubMed/frontier searches for current guidelines, trials, outcomes, controversies, devices, and evolving timing/indication questions.
- Use web only for primary non-literature sources such as society statements, device specifications, FDA pages, or trial registries.

### Plan Requirement

Every `retrieval_queries` entry in `report_research_plan.json` should be a rewritten, retrieval-ready query. Preserve the user's original request in the plan topic fields, but do not use it unmodified as the default search string unless it is already focused.

## Topic Archetype

Classify the report into one or more archetypes:

- `pathology`
- `procedure_or_technique`
- `anatomy`
- `device_or_implant`
- `pharmacology_or_critical_care`
- `trial_or_guideline`
- `controversy`
- `general_reference`

The archetype controls which domains are required, optional, or not applicable. Do not use a fixed template blindly.

## Default Domains

Start from these domains, then customize:

- `clinical_utility`
- `epidemiology_natural_history`
- `pathophysiology_mechanism`
- `anatomy`
- `diagnosis_imaging`
- `classification_staging`
- `management_decision_framework`
- `operative_or_procedural_considerations`
- `complications_failure_modes`
- `outcomes_evidence`
- `controversies_guidelines`
- `differentiators`
- `key_numbers`
- `mastery_objectives`
- `vault_crosslinks`

## Plan Shape

```json
{
  "report_title": "<Title>",
  "topic": "<canonical topic>",
  "archetypes": ["pathology"],
  "domains": {
    "epidemiology_natural_history": {
      "required": true,
      "rationale": "Natural history changes treatment threshold.",
      "retrieval_queries": [
        {
          "query": "<focused textbook or literature query>",
          "source_targets": ["textbook_full", "pubmed"],
          "frontier": true
        }
      ]
    },
    "operative_or_procedural_considerations": {
      "required": false,
      "rationale": "Only needed if management includes procedure selection.",
      "retrieval_queries": []
    }
  },
  "known_crosslinks": ["Reports/Related.md"],
  "planned_key_questions": [
    "What decision changes if this fact is true?"
  ]
}
```

Each required domain must have at least one retrieval query or a stated reason why internal knowledge is the only feasible source. The report may add queries later, but it may not silently drop a required domain.

## Output Discipline

The plan is a scratch artifact, not report prose. Keep it compact enough to drive retrieval and coverage checking.
