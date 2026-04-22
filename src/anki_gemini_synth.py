"""Batch cloze-card synthesis via the Gemini CLI (Gemini 3 Flash).

This is the *only* place a language model touches real-time Anki output.
Everything else (queue, dedup, AnkiConnect dispatch, KG backlink) is
deterministic Python. Keep the prompt here — and only here — so card
quality can be tuned without touching pipeline code.

Invocation: `gemini -m gemini-3-flash-preview -p PROMPT -o text --approval-mode yolo`
We pipe the candidate JSON in on stdin so the prompt stays short and
escaping is easy.

Return contract: list[CardDraft]. Invalid cards (schema mismatch, missing
cloze braces, too long) are dropped silently — a failed synthesis must
never break a user-facing session.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    from src.anki_sync.schemas import CardDraft
except ImportError:  # pragma: no cover - fallback when run outside package
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from src.anki_sync.schemas import CardDraft


DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_TIMEOUT_S = 120
GEMINI_BIN = "gemini"


# ---------------------------------------------------------------------------
# Per-error-type cloze templates. The agent is instructed to favor these
# shapes so the card structure mirrors the cognitive task Gabriel got
# wrong — this makes Anki spaced repetition target the actual weakness,
# not a generic restatement of the fact.
# ---------------------------------------------------------------------------

ERROR_TYPE_GUIDANCE = {
    "numerical_recall": (
        "Put the numeric threshold / dosage / cutoff inside {{c1::...}}. "
        "If the miss was a unit or direction confusion, also cloze the unit in {{c2::...}}."
    ),
    "cross_contamination": (
        "Interference-reduction cloze: {{c1::correct entity}} (not {{c2::the entity it was confused with}}). "
        "Always include the negation to force discrimination."
    ),
    "conceptual_confusion": (
        "Interference-reduction cloze: {{c1::correct concept}} is defined by {{c2::discriminating feature}}, "
        "not {{c3::the confused-with feature}}."
    ),
    "application_failure": (
        "Clinical-trigger cloze: In the context of {{c1::specific scenario}}, the next step is "
        "{{c2::correct management}}. The learner knew the fact but misapplied it — card must embed the trigger."
    ),
    "reasoning_gap": (
        "Causal cloze: Because {{c1::upstream mechanism}}, the result is {{c2::downstream consequence}}. "
        "Force the link that was missing."
    ),
    "omission": (
        "Completeness cloze: A full workup for {{c1::diagnosis}} includes {{c2::the omitted element}} "
        "alongside {{c3::anchoring elements the learner did mention}}."
    ),
    "anatomical_ambiguity": (
        "Landmark cloze: {{c1::structure}} runs / originates at {{c2::precise landmark}}, distinguishing it "
        "from {{c3::the adjacent structure}}."
    ),
    "": (
        "Standard discriminator cloze on the most testable atomic fact. Keep it to ONE c1 unless a "
        "confusable pair is naturally present."
    ),
}


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

SYSTEM_RULES = """You are a neurosurgery Anki card author. You will be given a JSON array
of LEARNING EXCHANGES from an active study session between an AI tutor and a neurosurgery resident.
Your job: emit one or more ATOMIC cloze cards per exchange that capture the most testable, high-yield
fact the exchange surfaced — calibrated to the resident's error type.

STRICT RULES — a violation invalidates the card:

1. Output MUST be a single JSON object: {"cards": [ ... ]}. No prose, no markdown, no backticks.
2. Each card MUST have fields: claim_id (short ID, <=16 chars), card_type="cloze",
   cloze_text (<=600 chars, MUST contain at least one {{c1::...}}), answer_text (<=200 chars,
   the plain answer/discriminator), category (optional, <=60 chars).
3. cloze_text is the Anki Cloze card front. It must read as a complete clinical sentence
   with the hidden fragment inside {{c1::...}} (and {{c2::...}} if comparison is warranted).
4. answer_text is the back-of-card supplement: mechanism, discriminator, or clinical consequence
   in ONE tight sentence. Not a definition dump.
5. Atomicity: ONE testable fact per card. If an exchange yields two independent facts, emit two
   cards with different claim_ids.
6. NO first-person pronouns, NO references to "the user", NO references to "the session" or
   "as we discussed". Cards must read like textbook facts for a learner who has never seen the
   session.
7. NO emojis, NO markdown formatting inside cloze_text. Plain text and {{cX::...}} syntax only.
8. If the exchange is too thin to yield a high-yield card (e.g. chit-chat, duplicate of an earlier
   fact in the batch), omit it. Quality over quantity.
9. If the exchange has a misconception or correction, the card MUST embed the DISCRIMINATOR
   (correct vs misconception), using the interference-reduction template for that error_type.
10. Keep cloze_text under 240 characters when possible. Long cards fail spaced repetition.

PER-ERROR-TYPE GUIDANCE (follow the one matching each candidate's error_type):
"""


def _build_prompt(candidates: list[dict]) -> str:
    guidance_lines = [
        f"- error_type={et!r}: {rule}" for et, rule in ERROR_TYPE_GUIDANCE.items()
    ]
    return (
        SYSTEM_RULES
        + "\n".join(guidance_lines)
        + "\n\nINPUT CANDIDATES (one per exchange):\n"
        + json.dumps(candidates, ensure_ascii=False, indent=2)
        + '\n\nEmit the JSON object now. Nothing else.'
    )


# ---------------------------------------------------------------------------
# JSON extraction (Gemini sometimes prefixes "YOLO mode is enabled." to stdout)
# ---------------------------------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json_object(text: str) -> dict | None:
    if not text:
        return None
    match = _JSON_OBJECT_RE.search(text)
    if not match:
        return None
    blob = match.group(0)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # Try to repair trailing-comma / code-fence noise
        cleaned = re.sub(r",\s*([}\]])", r"\1", blob)
        cleaned = cleaned.strip("` \n")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# Gemini invocation
# ---------------------------------------------------------------------------


def _invoke_gemini(prompt: str, model: str, timeout_s: int) -> str:
    """Run the Gemini CLI headlessly and return stdout text."""
    cmd = [
        GEMINI_BIN,
        "-m", model,
        "-p", prompt,
        "-o", "text",
        "--approval-mode", "yolo",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"gemini CLI not found on PATH: {exc}") from exc
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"gemini synthesis timed out after {timeout_s}s")

    if proc.returncode != 0:
        raise RuntimeError(
            f"gemini CLI exit {proc.returncode}: {proc.stderr.strip()[:400]}"
        )
    return proc.stdout


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesize_cards(
    candidates: Iterable[dict],
    *,
    model: str = DEFAULT_MODEL,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> list[CardDraft]:
    """Turn a batch of queue candidates into validated CardDrafts.

    Each candidate dict should minimally contain: exchange_id, topic, concept,
    question, answer, correction, correct, error_type, misconception, depth,
    domain, breakthrough.

    Returns only cards that round-trip through the CardDraft validator.
    Silently drops malformed cards — they'll be retried on the next flush
    (the queue is cleared only for the exchanges whose cards succeed).
    """
    candidates_list = list(candidates)
    if not candidates_list:
        return []

    prompt = _build_prompt(candidates_list)
    stdout = _invoke_gemini(prompt, model=model, timeout_s=timeout_s)
    payload = _extract_json_object(stdout)
    if not payload or not isinstance(payload.get("cards"), list):
        return []

    drafts: list[CardDraft] = []
    seen_ids: set[str] = set()
    for idx, raw in enumerate(payload["cards"]):
        if not isinstance(raw, dict):
            continue
        raw.setdefault("card_type", "cloze")
        # Ensure a unique claim_id even if Gemini repeats ids.
        claim = str(raw.get("claim_id") or f"c{idx+1}")[:16]
        while claim in seen_ids:
            claim = f"{claim[:14]}_{idx}"[:16]
        seen_ids.add(claim)
        raw["claim_id"] = claim
        try:
            drafts.append(CardDraft.model_validate(raw))
        except Exception as exc:  # noqa: BLE001
            print(
                f"[anki_gemini_synth] card validation failed (claim={claim}): {exc}",
                file=sys.stderr,
            )
    return drafts


__all__ = ["synthesize_cards", "DEFAULT_MODEL", "ERROR_TYPE_GUIDANCE"]
