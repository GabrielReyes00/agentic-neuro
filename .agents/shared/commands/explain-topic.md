# Explain Topic

Use for direct precision explanations of a topic. Do not invoke RAG unless the user asks for database lookup.

## Input

Parse arguments as:

- Topic: required free text.
- Depth: `--brief`, `--standard` default, or `--deep`.
- `--save`: persist to vault.

Ask one short question if the topic is missing or domain-ambiguous.

## Learner Context

Optionally calibrate emphasis:

```bash
python3 src/study_memory.py recall --topic "<topic>"
```

Use recall output to adjust depth — skip basics for known concepts, focus on gaps. Continue if unavailable.

## Output

1. **The Core**: exact definition; correct common sloppy definitions.
2. **The Mechanism**: causal chain, variables, and why behavior follows.
3. **The Discriminations**: adjacent concepts and the axis that separates them.
4. **The Application**: decisions or practice changes unlocked by precision.

Depth:

| Depth | Behavior |
|---|---|
| brief | Core plus one practical impact sentence, about 150 words |
| standard | Core, Mechanism, Discriminations, Application, about 400-600 words |
| deep | Standard plus **The Edge**: failure modes, second-order effects, model breakdowns |

Voice: expert-to-expert, precise, no filler, no emojis. If an analogy is used, immediately translate it to mechanism.

## Save

Only save when `--save` is explicit. Write to the relevant vault folder, no H1, with metadata at bottom and related vault links when available.
