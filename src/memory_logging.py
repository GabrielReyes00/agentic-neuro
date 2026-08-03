"""Memory-logging discipline: the four-layer field taxonomy, the atomic-concept
guard, and loud inventory-binding resolution.

The classic failure of this codebase was overloading the `concept` field as
identity, label, and mini-summary at once, so labels drifted into verbose,
conflated prose that cannot be matched or used for calibration. The redesign
separates four layers, each with one job and one rule:

  IDENTITY    inventory_concept_id, topic_id, claim_state_id
              -> the ONLY layer matching / sequencing / calibration may key on.
                 Resolved at log time; never re-derived from prose.
  CATEGORICAL cognitive_op, gap_type, answer_mode, confidence_observed,
              teaching_move, coverage_role, priority, score
              -> controlled vocabularies; calibration-grade signal.
  NUMERICAL   attempts, successes, stability, difficulty, retrievability
              -> pure numbers; never reconstructed from a rounded value.
  SUBJECTIVE  tested_claim, learner_claim, demonstrated_edge, misconception,
              corrected_rule, clinical_consequence, retest_prompt_shape,
              teaching_intervention
              -> retrieval-only; the agent READS them to design the next probe.
                 Never matched, counted, or used as identity.

The rule the redesign enforces: math runs on IDENTITY + CATEGORICAL + NUMERICAL;
the agent reads SUBJECTIVE. This module owns the guards that keep that true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

IDENTITY_FIELDS = ("inventory_concept_id", "topic_id", "claim_state_id", "concept_id")
CATEGORICAL_FIELDS = (
    "cognitive_op", "gap_type", "answer_mode", "confidence_observed",
    "teaching_move", "coverage_role", "priority", "score", "teaching_intent",
)
NUMERICAL_FIELDS = ("attempts", "successes", "stability", "difficulty", "retrievability")
SUBJECTIVE_FIELDS = (
    "tested_claim", "learner_claim", "demonstrated_edge", "misconception",
    "corrected_rule", "correction", "clinical_consequence",
    "retest_prompt_shape", "missing_edge", "teaching_intervention",
)

# A concept label should name ONE inventory concept. These markers mean the label
# is carrying more than identity — the extra detail belongs in tested_claim.
_CONJUNCTION_MARKERS = (" and ", " & ", " plus ", " including ", " incl ", ", and ", " w/ ")
_COMPARISON_MARKERS = (" vs ", " vs. ", " versus ")
# Trial names embedded in a concept label are evidence detail, not identity.
_EVIDENCE_MARKERS = (
    "trial", "nascis", "patchell", "stich", "stash", "isat", "issue", "rescue",
    "decra", "destiny", "chimps", "mistie", "carmustine", "stich-ii",
)
MAX_ATOMIC_WORDS = 6

_WORD_RE = re.compile(r"[a-z0-9]+")


def atomicity_warnings(concept: str) -> list[str]:
    """Advisory checks that a concept label names one atomic inventory concept.

    Returns human-readable advisories (empty when the label is clean). Advisory by
    design: it never blocks a log, it nudges the agent toward a canonical label and
    moving conflated detail into tested_claim, so future binding actually works.
    """
    low = f" {str(concept or '').lower().strip()} "
    issues: list[str] = []
    if any(marker in low for marker in _CONJUNCTION_MARKERS):
        issues.append(
            "conflated_concept: label joins multiple concepts with a conjunction; "
            "log one concept and move the rest into tested_claim or a second exchange"
        )
    if any(marker in low for marker in _COMPARISON_MARKERS):
        issues.append(
            "comparison_as_concept: bind the concept to one inventory node and log "
            "the discrimination in tested_claim rather than naming both sides"
        )
    if any(marker in low for marker in _EVIDENCE_MARKERS):
        issues.append(
            "evidence_in_label: move trial/evidence detail into tested_claim; the "
            "concept label should be the durable clinical concept"
        )
    word_count = len(_WORD_RE.findall(low))
    if word_count > MAX_ATOMIC_WORDS:
        issues.append(
            f"verbose_label: {word_count} words (> {MAX_ATOMIC_WORDS}); use a short "
            "canonical concept name and put specifics in tested_claim"
        )
    return issues


@dataclass
class BindingResolution:
    """Outcome of resolving a logged concept to a canonical inventory node.

    `status` is the loud signal the agent and user act on:
      explicit   - the agent passed a verified inventory_concept_id (best).
      inferred   - lexically matched to a scoped node (provisional; pass --inventory-concept-id next time).
      unresolved - no node matched; candidates feed the node-proposal queue (Pillar C).
    """

    status: str
    inventory_concept_id: str = ""
    score: float = 0.0
    candidates: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status}
        if self.inventory_concept_id:
            payload["inventory_concept_id"] = self.inventory_concept_id
        if self.status != "explicit":
            payload["score"] = round(float(self.score), 3)
        if self.candidates:
            payload["candidates"] = self.candidates
        return payload


def top_candidate_nodes(concept: str, knowledge_map: list[dict], k: int = 3) -> list[dict]:
    """Best near-miss inventory nodes for an unresolved concept (node-proposal input)."""
    from session_map import _lexical_score, _tokens  # noqa: PLC0415

    query = _tokens(concept)
    if not query:
        return []
    scored: list[tuple[float, str, str]] = []
    for entry in knowledge_map:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("concept_id", ""))
        if not cid:
            continue
        score = _lexical_score(query, _tokens(str(entry.get("concept", ""))))
        if score > 0:
            scored.append((score, cid, str(entry.get("concept", ""))))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"inventory_concept_id": cid, "concept": name, "score": round(score, 3)}
        for score, cid, name in scored[:k]
    ]


def resolve_inventory_binding(
    *,
    explicit_id: str,
    concept: str,
    knowledge_map: list[dict] | None,
) -> BindingResolution:
    """Classify how a logged concept binds to the inventory, loudly.

    The agent passing an id wins. Otherwise we lexically match against the live
    session knowledge map; a hit is `inferred` (provisional), a miss is
    `unresolved` and carries the near-miss candidates so the gap is visible
    instead of silently swallowed.
    """
    if explicit_id:
        return BindingResolution(status="explicit", inventory_concept_id=explicit_id, score=1.0)
    if not knowledge_map:
        return BindingResolution(status="unresolved", score=0.0)
    from session_map import lexical_match_inventory_id  # noqa: PLC0415

    matched, score = lexical_match_inventory_id(concept, {"knowledge_map": knowledge_map})
    if matched:
        return BindingResolution(status="inferred", inventory_concept_id=matched, score=score)
    return BindingResolution(
        status="unresolved",
        score=score,
        candidates=top_candidate_nodes(concept, knowledge_map),
    )
