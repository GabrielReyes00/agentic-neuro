# Study Review Vault Repair

Load only at point of need during `study-review`. Do not use vault recall during startup for the requested document.

## When To Use

Use targeted vault recall when one of these is true:

- Gabriel misses or gives a partial answer and a personalized note may improve the repair.
- A recurring false rule needs a different discriminator, mental model, execution check, or evidence anchor.
- Gabriel asks for local/service context or comparison with another note.
- The current document is thin on a clinically important adjacent concept.

Do not use vault recall for every turn, for generic explanation, or to replace native clinical reasoning.

## Tool

```bash
python3 src/vault_retriever.py recall "<missed concept or corrected rule>" --task concept-repair --limit 5
```

Use task-specific variants only when the phase requires them, such as `service-local` for local practice or `trial-evidence` for evidence comparison.

## Teaching Use

Read `retrieval_status` first.

- `ready`: use one targeted discriminator, mental model, execution check, evidence anchor, or local clarification.
- `partial`: use only clearly relevant fields; rely on native knowledge for the rest.
- `failed`: do not pretend vault context exists; teach from native knowledge and formal sources when needed.

After using vault context, ask a near-transfer retest. Do not turn a miss into a broad vault-note lecture unless Gabriel asks for a full reveal.

Preserve provenance. Local or experiential notes never silently override formal evidence.

