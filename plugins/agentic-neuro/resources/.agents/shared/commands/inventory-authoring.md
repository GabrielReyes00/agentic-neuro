# Inventory Authoring

How to add a concept to the canonical inventory deliberately. The inventory JSON
(`data/concept_inventory/`) is the committed, curated source of truth that the
teaching policy and knowledge map are built from. Adding a node changes the map's
structure, so additions are **reviewed, user-approved commits — never runtime
writes.** The cardinal failure to avoid is an inventory that bloats with
redundant, over-granular nodes; the dedup guard exists to prevent exactly that.

## When To Propose A Node

Propose only when all of these hold:
- A learner error or `binding=unresolved` (from `log-answer`) or a migration
  `unbindable`/`provisional` entry exposes a concept the inventory genuinely lacks.
- The concept is recurring and high-yield, not a one-off phrasing.
- It is a missing **node**, not a missing **edge**. If the concept exists but is
  not reachable from the topic, the fix is a `related`/`prereq` edge or an alias on
  the existing node, or a `model_proposed` learner-graph edge during curation —
  not a new node.

Do not propose a node for a verbose or conflated learner label. Fix the label
(atomic concept + tested_claim) and re-check binding first.

## Propose → Review → Apply

1. **Propose** (side-effect free):

```bash
python3 src/inventory_authoring.py \
  --name "<canonical concept name>" --domain <slug> --type <type> --tier <tier> \
  --blurb "<one sentence: what mastery means>" \
  --topic-id <existing topic id>   # OR --topic-name "<new topic>" \
  --alias "<phrasing a learner used>" [--alias ...] \
  --prereq <id> [--prereq ...] --discriminator <id> [...] --related <id> [...]
```

2. **Read the report and present it to the user** (they cannot see the map JSON):
   - `placement`: domain, topic (existing/new), type, tier, generated `concept_id`.
   - `gap_assessment`: `genuine_gap`, `adjacent_nodes_exist_likely_genuine`, or
     `possible_duplicate`. **If `possible_duplicate`, do not add — bind the learner
     concept to the existing node in `near_duplicates` instead.**
   - `near_duplicates`: existing nodes with similar names (the anti-bloat signal).
   - `connections`: the validated `prereqs`/`discriminators`/`related` edges. Aim
     for high-value edges so the node lands in the map correctly; keep ≤ 6 total.
   - `errors`: invalid type/tier, unknown edge ids, or an id collision — fix before approval.

3. **Apply only after the user approves** (this writes the domain JSON and rebuilds):

```bash
python3 src/inventory_authoring.py --name ... --domain ... [all the same flags] --apply
```

`--apply` appends the node (and any new topic) to the domain file in the **canonical
one-per-line layout** (see `data/concept_inventory/SCHEMA.md`), runs `validate`, and
rebuilds the inventory DB. It refuses if validation fails or the id collides. Never
hand-edit a domain file with a pretty-printer; if a file is ever mis-formatted, run
`python3 src/inventory_authoring.py --normalize` to restore the canonical layout.

## Placement Discipline

Follow `data/concept_inventory/SCHEMA.md`:
- `type` ∈ anatomy, physiology, pathology, presentation, diagnostics, imaging,
  classification, management, operative, complication, pharmacology, evidence.
- `tier` ∈ foundation, core, advanced, expert (progression toward mastery).
- `name` ≤ 10 words, precise; `blurb` ≤ 25 words.
- `aliases`: generous — include the abbreviations and phrasings a learner label
  would actually use. This is what makes future projection bind.
- Edges point to the most specific node, not the topic root; use the Core
  Reference IDs in SCHEMA.md for cross-domain prereqs.

The report is the approval surface. Never run `--apply` without showing the user
the placement, gap assessment, and connections first.
