# Knowledge Map

Use for progress, dashboard, gaps, studied topics, milestones, ACGME, and learning-state questions. Route "what should I study today" to `study-session`.

## Core Commands

```bash
python3 src/knowledge_graph.py dashboard
python3 src/knowledge_graph.py topics --only-studied --sort confidence
python3 src/knowledge_graph.py topics --domain "<Domain>" --sort confidence
python3 src/knowledge_graph.py topics --only-studied --sort confidence_asc
python3 src/knowledge_graph.py topics --only-studied --sort recent --limit 20
python3 src/knowledge_graph.py activity --n 30
python3 src/knowledge_graph.py status
python3 src/knowledge_graph.py topic_detail "<topic>"
python3 src/knowledge_graph.py add_topic --name "<topic>" --category "<category>" --source "attending-directive" --priority 1
python3 src/knowledge_graph.py gaps --top 15 [--rotation "<Rotation>"]
python3 src/knowledge_graph.py review_queue --n 10
python3 src/memory_orchestrator.py next-item --mode zpd --limit 10
python3 src/memory_orchestrator.py proactive-probe --pop
python3 src/memory_orchestrator.py tutor-strategy "<topic>"
python3 src/knowledge_graph.py milestone_report
```

Valid rotations: Vascular, Spine, Tumor, Functional and Stereotactic, Trauma, Pediatric Neurosurgery, Critical Care and General Neurosurgery.

## Rendering

Dashboard: coverage summary, domain progress table, Mastery Landscape, weakest/strongest areas, recent activity, patterns/calibration.

Topics: table with topic, domain, confidence, depth, encounters, last seen.

Gaps: group by urgency, decay, shallow coverage, error clusters, adaptive ZPD candidates, queued proactive probes, mastery-ladder next rungs, bottlenecks, transfer gaps, and error recurrence fingerprints. Include due concepts. Offer to start `study-session`.

Milestones: weakest-first competency table and top 3 priority targets.

## Anki Sync Freshness

If recommendations may be stale because Anki has not synced recently, ask whether Anki is open. If yes:

```bash
python3 src/knowledge_graph.py sync_anki
```

## Dashboard Write

After dashboard, gap, or milestone rendering, silently update:

`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Dashboard.md`

Rules: use real KG values, no stale carryover, no H1, no emojis, tables for data, Obsidian callouts for prose. Include overview, curriculum progress, study queue, Mastery Landscape, bottlenecks, transfer gaps, recurring error fingerprints, concept gaps, recent activity, patterns/calibration, vault assets, and what changed last session.

Run the universal post-session hook for `knowledge-map` and surface failures.
