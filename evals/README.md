# Agent Behavior Evaluations

`agent_behavior_cases.json` separates two questions that should not be conflated:

- **Graph conformance:** can every declared outcome sequence traverse the typed
  workflow graph to its expected terminal while touching the required safety,
  validation, and approval nodes?
- **Model behavior:** given the repository policy and a realistic user prompt,
  does a model choose the expected route, response shape, evidence tier, mutation
  boundary, and memory boundary?

CI runs the deterministic graph and suite validation:

```bash
python3 src/behavioral_eval.py validate
```

To evaluate a model without coupling the repository to a provider, emit JSONL
prompt packets, run them through the candidate model, and grade its JSONL
decisions:

```bash
python3 src/behavioral_eval.py emit --output /tmp/agent-behavior-prompts.jsonl
python3 src/behavioral_eval.py grade \
  --predictions /tmp/model-predictions.jsonl \
  --minimum-field-accuracy 0.95
```

The grader is deliberately exact and machine-readable. It does not pretend that
keyword matching of a prose answer is a valid model judge. A model run is not a
CI claim until predictions from that model are actually supplied and graded.

## Study-review transcript evaluation

`study_review_cases.json` targets the teaching boundary itself: silent opening,
partial and wrong-answer repair, correct-but-shallow escalation, source
adjudication, independent multi-claim grading, PGY calibration, and bounded
nearby-node expansion.

```bash
python3 src/study_review_eval.py validate
python3 src/study_review_eval.py emit --output /tmp/study-review-prompts.jsonl
python3 src/study_review_eval.py grade --judgments /tmp/blinded-judgments.jsonl
```

The generated response must be judged by a human or independent model using the
structured fields. The deterministic grader then checks the rubric exactly. It
does not infer teaching quality from keywords and the repository does not claim
an effectiveness gain until real candidate transcripts have been judged.
