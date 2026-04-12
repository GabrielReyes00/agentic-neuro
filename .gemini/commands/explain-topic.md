# Explain Topic Command

Deliver a precision explanation for `{{args}}` that upgrades the learner's mental model.

## Input Parsing

Interpret args as:
- Topic (required)
- Depth: `--brief`, `--standard` (default), `--deep`
- `--save` (optional)

If topic missing, ask one short question.  
If topic is domain-ambiguous, ask one clarifying question.

## Learner Context Prepass (Silent)

```bash
cd /Users/gabrielreyes/agentic-neuro && source .venv/bin/activate && \
python3 src/knowledge_graph.py context "<topic>" --output data/Sessions/learner_context.json
```

Use this only for emphasis calibration (prior gaps vs prior mastery). Continue if unavailable.

## Output Structure

1. **The Core**: exact definition with corrected precision if common definitions are sloppy.
2. **The Mechanism**: causal chain, variables, and why behavior follows.
3. **The Discriminations**: where this concept diverges from confusables and along which axis.
4. **The Application**: decisions/practice changes unlocked by correct understanding.

## Depth Rules

- **brief**: Core + one sentence on practical impact (~150 words).
- **standard**: Core/Mechanism/Discriminations/Application (400-600 words). Optional Socratic prompt allowed.
- **deep**: standard + **The Edge** (failure modes, second-order effects, model breakdowns), 700+ words, optional Socratic transfer question.

## Voice Constraints

- Expert-to-expert tone.
- Precision over breadth.
- No filler, no hedging language.
- If analogy used, immediately translate to mechanistic language.
- Bold only first use of key terms.
- No emojis.

## Saving Rules

Save only when `--save` is explicitly provided.

Path:
`/Users/gabrielreyes/Documents/Obsidian/agentic-neuro/Review Sessions/<topic-slug>.md`

Frontmatter:

```yaml
---
title: "<Topic Name>"
topic: "<topic>"
depth: "<brief|standard|deep>"
skill: "explain-topic"
tags:
  - type/session
  - source/agent
---
```
