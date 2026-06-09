from __future__ import annotations

import json
from unittest import mock

from src.anki_feedback import (
    build_feedback_summary,
    build_session_anki_profile,
    classify_card_lifecycle,
    _resolve_card_concept_and_topic,
)

DAY_MS = 86_400_000
NOW_MS = 1_800_000_000_000


def _card(card_id_days_ago: int, **overrides):
    card = {
        "cardId": NOW_MS - (card_id_days_ago * DAY_MS),
        "note": NOW_MS - (card_id_days_ago * DAY_MS),
        "deckName": "Neurosurgery::Spine::Spine Emergencies",
        "tags": ["topic/spine-emergencies"],
        "type": 2,
        "queue": 2,
        "reps": 4,
        "lapses": 0,
        "interval": 30,
        "question": "Spine emergency card",
    }
    card.update(overrides)
    return card


def _review(days_ago: int, ease: int, **overrides):
    review = {
        "id": NOW_MS - (days_ago * DAY_MS),
        "ease": ease,
        "time": 5_000,
        "type": 1,
        "ivl": 30,
        "lastIvl": 14,
    }
    review.update(overrides)
    return review


def test_classifies_new_card_temporal_zones():
    fresh = classify_card_lifecycle(
        _card(1, type=0, queue=0, reps=0, interval=0),
        [],
        now_ms=NOW_MS,
    )
    transition = classify_card_lifecycle(
        _card(5, type=0, queue=0, reps=0, interval=0),
        [],
        now_ms=NOW_MS,
    )
    stale = classify_card_lifecycle(
        _card(10, type=0, queue=0, reps=0, interval=0),
        [],
        now_ms=NOW_MS,
    )

    assert fresh["category"] == "fresh_new"
    assert transition["category"] == "transition_new"
    assert stale["category"] == "stale_new"


def test_classifies_lapse_and_leech_with_precedence():
    lapse = classify_card_lifecycle(
        _card(40, lapses=1, interval=1),
        [_review(1, 1, lastIvl=90, time=24_000)],
        now_ms=NOW_MS,
    )
    leech = classify_card_lifecycle(
        _card(40, lapses=4, interval=1),
        [_review(1, 1, lastIvl=10)],
        now_ms=NOW_MS,
    )

    assert lapse["category"] == "active_lapse"
    assert lapse["subtype"] == "mature_lapse"
    assert leech["category"] == "leech"
    assert leech["subtype"] == "chronic_leech"


def test_classifies_shaky_success_recent_success_and_mature_stale():
    shaky = classify_card_lifecycle(
        _card(20, reps=8, lapses=1, interval=10),
        [_review(1, 2, time=20_000)],
        now_ms=NOW_MS,
    )
    recent = classify_card_lifecycle(
        _card(20, reps=8, lapses=0, interval=30),
        [_review(2, 3, time=4_000)],
        now_ms=NOW_MS,
    )
    mature = classify_card_lifecycle(
        _card(200, reps=12, lapses=0, interval=120),
        [_review(100, 3, ivl=120, time=4_000)],
        now_ms=NOW_MS,
    )

    assert shaky["category"] == "shaky_success"
    assert recent["category"] == "recent_success"
    assert mature["category"] == "mature_stale"


def test_resolve_card_concept_and_topic_from_deck_and_tags():
    deck_card = {
        "deckName": "Neurosurgery::Trauma::Acute SDH",
        "note": 12345,
        "tags": [],
    }
    tagged_card = {
        "deckName": "Neurosurgery",
        "note": 12345,
        "tags": ["domain/spine", "concept/spinal-shock"],
    }

    assert _resolve_card_concept_and_topic(deck_card, None) == ("Trauma", "Acute SDH")
    assert _resolve_card_concept_and_topic(tagged_card, None) == ("Spine", "Spinal Shock")


def test_resolve_card_concept_and_topic_from_chroma_note_metadata():
    mock_collection = mock.Mock()
    mock_collection.get.return_value = {
        "metadatas": [{"topic": "Vascular", "concept": "SAH Vasospasm"}]
    }

    card_detail = {
        "deckName": "Neurosurgery::Trauma::Acute SDH",
        "note": 123456789012,
        "tags": [],
    }

    topic, concept = _resolve_card_concept_and_topic(card_detail, mock_collection)

    mock_collection.get.assert_called_once_with(where={"note_id": 123456789012})
    assert topic == "Vascular"
    assert concept == "SAH Vasospasm"


def test_build_session_anki_profile_is_topic_scoped_and_bounded():
    cards = [
        _card(
            30,
            cardId=NOW_MS - (30 * DAY_MS),
            note=201,
            tags=["topic/spine-emergencies", "concept/bulbocavernosus-reflex"],
            reps=8,
            lapses=2,
            interval=1,
            question="Return of the bulbocavernosus reflex marks {{c1::end of spinal shock}}.",
        ),
        _card(
            40,
            cardId=NOW_MS - (40 * DAY_MS),
            note=202,
            tags=["topic/spine-emergencies", "concept/neurogenic-shock"],
            reps=14,
            lapses=0,
            interval=90,
            question="Neurogenic shock causes {{c1::hypotension with bradycardia}}.",
        ),
        _card(
            1,
            cardId=NOW_MS - DAY_MS,
            note=203,
            type=0,
            queue=0,
            reps=0,
            interval=0,
            tags=["topic/spine-emergencies", "concept/spinal-clearance-algorithm"],
            question="A reliable exam after spine trauma requires {{c1::no intoxication or distracting injury}}.",
        ),
        _card(
            10,
            cardId=NOW_MS - (10 * DAY_MS),
            note=204,
            type=0,
            queue=0,
            reps=0,
            interval=0,
            tags=["topic/spine-emergencies", "concept/thoracic-burst-fractures"],
            question="A burst fracture implies failure of the {{c1::anterior and middle columns}}.",
        ),
        _card(
            5,
            cardId=NOW_MS - (5 * DAY_MS),
            note=205,
            deckName="Neurosurgery::Neurocritical Care::EVD Management",
            tags=["topic/evd-management", "concept/kochers-point"],
            reps=3,
            lapses=0,
            interval=6,
            question="Kocher's point is {{c1::1 cm anterior to coronal suture}}.",
        ),
    ]
    for idx in range(105, 225):
        cards.append(
            _card(
                80,
                cardId=idx,
                note=idx + 1000,
                tags=["topic/spine-emergencies", f"concept/stable-{idx}"],
                reps=10,
                lapses=0,
                interval=180,
            )
        )

    reviews = {
        str(NOW_MS - (30 * DAY_MS)): [_review(1, 1, lastIvl=28, ivl=1, time=24_500)],
        str(NOW_MS - (40 * DAY_MS)): [_review(2, 3, ivl=90, time=4_000)],
        **{str(idx): [_review(20, 3, ivl=180, time=4_000)] for idx in range(105, 225)},
    }

    def fake_invoke(action, **params):
        if action == "multi":
            return [fake_invoke(act["action"], **act.get("params", {})) for act in params["actions"]]
        if action == "version":
            return 6
        if action == "findCards":
            return [card["cardId"] for card in cards]
        if action == "cardsInfo":
            wanted = set(params["cards"])
            return [card for card in cards if card["cardId"] in wanted]
        if action == "getReviewsOfCards":
            return {str(card_id): reviews.get(str(card_id), []) for card_id in params["cards"]}
        raise AssertionError(action)

    with mock.patch("src.anki_feedback.invoke", side_effect=fake_invoke), mock.patch(
        "src.anki_feedback._load_chroma_collection",
        return_value=None,
    ):
        profile = build_session_anki_profile(
            "Spine Emergencies",
            resolved_topic="spine-emergencies",
            now_ms=NOW_MS,
        )

    assert profile["status"] == "success"
    assert profile["scope"] == "topic"
    assert profile["cards_examined"] == len(cards) - 1
    assert profile["macro_counts"]["active_lapse"] == 1
    assert profile["macro_counts"]["fresh_new"] == 1
    assert profile["macro_counts"]["stale_new"] == 1
    assert profile["atomic_focus"][0]["concept"] == "Bulbocavernosus Reflex"
    assert profile["atomic_focus"][0]["fact"] == "Return of the bulbocavernosus reflex marks [end of spinal shock]."
    assert profile["atomic_focus"][0]["metrics"]["lapses"] == 2
    assert profile["atomic_primes"][0]["concept"] == "Thoracic Burst Fractures"
    assert "Kocher" not in json.dumps(profile)
    assert profile["avoid_direct_quiz"]["count"] == 1
    assert "].." not in json.dumps(profile["teaching_directives"])
    assert "].;" not in json.dumps(profile["teaching_directives"])
    assert len(json.dumps(profile, separators=(",", ":"))) <= 1500


def test_evd_topic_surfaces_kocher_atomic_fact_when_in_scope():
    cards = [
        _card(
            5,
            cardId=NOW_MS - (5 * DAY_MS),
            note=205,
            deckName="Neurosurgery::Neurocritical Care::EVD Management",
            tags=["topic/evd-management", "concept/kochers-point"],
            reps=3,
            lapses=0,
            interval=6,
            question="Kocher's point is {{c1::1 cm anterior to coronal suture}}.",
        )
    ]
    reviews = {str(NOW_MS - (5 * DAY_MS)): [_review(1, 2, ivl=6, lastIvl=5, time=40_000)]}

    def fake_invoke(action, **params):
        if action == "version":
            return 6
        if action == "findCards":
            return [card["cardId"] for card in cards]
        if action == "cardsInfo":
            return cards
        if action == "getReviewsOfCards":
            return {str(card_id): reviews.get(str(card_id), []) for card_id in params["cards"]}
        raise AssertionError(action)

    with mock.patch("src.anki_feedback.invoke", side_effect=fake_invoke), mock.patch(
        "src.anki_feedback._load_chroma_collection",
        return_value=None,
    ):
        profile = build_session_anki_profile(
            "EVD Management",
            resolved_topic="evd-management",
            now_ms=NOW_MS,
        )

    assert profile["atomic_focus"][0]["fact"] == "Kocher's point is [1 cm anterior to coronal suture]."
    assert profile["atomic_focus"][0]["metrics"]["rt_s"] == 40.0


class _FakeChroma:
    def __init__(self, metadata: dict, distance: float):
        self.metadata = metadata
        self.distance = distance

    def query(self, **_params):
        return {
            "metadatas": [[self.metadata]],
            "distances": [[self.distance]],
        }

    def get(self, where):
        if where.get("note_id") == self.metadata.get("note_id") or where.get("card_id") == self.metadata.get("card_id"):
            return {"metadatas": [self.metadata]}
        return {"metadatas": []}


def test_semantic_chroma_hit_can_enter_without_lexical_scope_match():
    card = _card(
        30,
        cardId=606,
        note=6606,
        deckName="Neurosurgery::Trauma::Central Cord Syndrome",
        tags=["concept/central-cord-syndrome"],
        reps=8,
        lapses=1,
        interval=3,
        question="Central cord syndrome preferentially weakens {{c1::hands more than legs}}.",
    )
    reviews = {"606": [_review(1, 1, ivl=1, lastIvl=21, time=13_000)]}
    chroma = _FakeChroma(
        {
            "card_id": 606,
            "note_id": 6606,
            "topic": "Trauma",
            "concept": "Central Cord Syndrome",
        },
        distance=0.24,
    )

    def fake_invoke(action, **params):
        if action == "version":
            return 6
        if action == "findCards":
            return []
        if action == "cardsInfo":
            return [card]
        if action == "getReviewsOfCards":
            return {str(card_id): reviews.get(str(card_id), []) for card_id in params["cards"]}
        raise AssertionError(action)

    with mock.patch("src.anki_feedback.invoke", side_effect=fake_invoke), mock.patch(
        "src.anki_feedback._load_chroma_collection",
        return_value=chroma,
    ):
        profile = build_session_anki_profile(
            "Spine Emergencies",
            resolved_topic="spine-emergencies",
            now_ms=NOW_MS,
        )

    assert profile["status"] == "success"
    assert profile["cards_examined"] == 1
    assert profile["atomic_focus"][0]["concept"] == "Central Cord Syndrome"
    assert profile["atomic_focus"][0]["fact"] == "Central cord syndrome preferentially weakens [hands more than legs]."


def test_weak_generic_semantic_hit_does_not_leak_into_scoped_overlay():
    card = _card(
        30,
        cardId=707,
        note=7707,
        deckName="Neurosurgery::Neurocritical Care::Seizure Emergencies",
        tags=["concept/status-epilepticus"],
        reps=8,
        lapses=1,
        interval=3,
        question="Emergency seizure treatment starts with {{c1::benzodiazepines}}.",
    )
    chroma = _FakeChroma(
        {
            "card_id": 707,
            "note_id": 7707,
            "topic": "Neurocritical Care",
            "concept": "Status Epilepticus",
        },
        distance=1.2,
    )

    def fake_invoke(action, **params):
        if action == "version":
            return 6
        if action == "findCards":
            return []
        if action == "cardsInfo":
            return [card]
        if action == "getReviewsOfCards":
            return {str(card_id): [] for card_id in params["cards"]}
        raise AssertionError(action)

    with mock.patch("src.anki_feedback.invoke", side_effect=fake_invoke), mock.patch(
        "src.anki_feedback._load_chroma_collection",
        return_value=chroma,
    ):
        profile = build_session_anki_profile(
            "Spine Emergencies",
            resolved_topic="spine-emergencies",
            now_ms=NOW_MS,
        )

    assert profile["status"] == "no_matches"
    assert "Status Epilepticus" not in json.dumps(profile)


def test_global_session_anki_profile_returns_headlines_not_concepts():
    cards = [
        _card(
            30,
            cardId=301,
            note=401,
            deckName="Neurosurgery::Vascular::SAH",
            tags=["topic/sah"],
        )
    ]
    reviews = {"301": [_review(1, 1, time=8_000)]}

    def fake_invoke(action, **params):
        if action == "version":
            return 6
        if action == "findCards":
            assert "rated:7" in params["query"]
            return [301]
        if action == "cardsInfo":
            return cards
        if action == "getReviewsOfCards":
            return reviews
        raise AssertionError(action)

    with mock.patch("src.anki_feedback.invoke", side_effect=fake_invoke), mock.patch(
        "src.anki_feedback._load_chroma_collection",
        return_value=None,
    ):
        profile = build_session_anki_profile("", global_mode=True, now_ms=NOW_MS)

    assert profile["status"] == "success"
    assert profile["scope"] == "global_recent"
    assert profile["concept_level_overlay"] is False
    assert "intervention_targets" not in profile
    assert profile["topic_headlines"][0]["topic"] == "Sah"


@mock.patch("src.anki_feedback.invoke")
def test_build_session_anki_profile_offline(mock_invoke):
    mock_invoke.side_effect = ConnectionError("Connection refused")
    result = build_session_anki_profile("Spine Emergencies")
    assert result["status"] == "offline"
    assert "offline" in result["message"]


@mock.patch("src.anki_feedback.invoke")
@mock.patch("src.anki_feedback.get_recent_reviews")
@mock.patch("src.anki_feedback._load_chroma_collection")
def test_build_feedback_summary_success(mock_chroma, mock_get_reviews, mock_invoke):
    mock_invoke.return_value = "version_info"
    mock_chroma.return_value = None
    mock_get_reviews.return_value = [
        {
            "card": {
                "cardId": 111,
                "note": 222,
                "deckName": "Neurosurgery::Spine::Spine Emergencies",
                "question": "What is bulbocavernosus reflex?",
                "tags": [],
            },
            "reviews": [
                {"id": 1000, "ease": 3, "time": 5000, "type": 1},
                {"id": 2000, "ease": 1, "time": 8000, "type": 1},
            ],
        }
    ]

    result = build_feedback_summary(7)

    assert result["status"] == "success"
    assert result["total_reviews_evaluated"] == 2
    assert "Spine" in result["topics"]
    assert result["topics"]["Spine"]["total_reviews"] == 2
    assert result["topics"]["Spine"]["fails"] == 1
    assert len(result["lapses"]) == 1
    assert result["lapses"][0]["concept"] == "Spine Emergencies"


def test_enforce_cap_compaction_stages():
    cards = [
        _card(
            30,
            cardId=101,
            note=201,
            tags=["topic/spine-emergencies", "concept/bulbocavernosus-reflex"],
            reps=8,
            lapses=2,
            interval=1,
            question="Return of the bulbocavernosus reflex marks {{c1::end of spinal shock}}.",
        ),
        _card(
            40,
            cardId=102,
            note=202,
            tags=["topic/spine-emergencies", "concept/neurogenic-shock"],
            reps=14,
            lapses=0,
            interval=90,
            question="Neurogenic shock causes {{c1::hypotension with bradycardia}}.",
        ),
    ]
    reviews = {
        "101": [_review(1, 1, lastIvl=28, ivl=1, time=24_500)],
        "102": [_review(2, 3, ivl=90, time=4_000)],
    }

    def fake_invoke(action, **params):
        if action == "version":
            return 6
        if action == "findCards":
            return [101, 102]
        if action == "cardsInfo":
            return cards
        if action == "getReviewsOfCards":
            return reviews
        raise AssertionError(action)

    with mock.patch("src.anki_feedback.invoke", side_effect=fake_invoke), mock.patch(
        "src.anki_feedback._load_chroma_collection",
        return_value=None,
    ):
        # 1. Large cap: rollup is structured list of dicts
        profile_large = build_session_anki_profile(
            "Spine Emergencies",
            resolved_topic="spine-emergencies",
            max_chars=5000,
            now_ms=NOW_MS,
        )
        assert isinstance(profile_large["concept_rollup"], list)
        assert isinstance(profile_large["concept_rollup"][0], dict)
        assert profile_large["concept_rollup"][0]["concept"] == "Bulbocavernosus Reflex"

        # 2. Medium cap: rollup is compacted to list of strings
        profile_med = build_session_anki_profile(
            "Spine Emergencies",
            resolved_topic="spine-emergencies",
            max_chars=1000,
            now_ms=NOW_MS,
        )
        assert isinstance(profile_med["concept_rollup"], list)
        assert len(profile_med["concept_rollup"]) > 0
        assert isinstance(profile_med["concept_rollup"][0], str)
        assert "Bulbocavernosus Reflex:active_lapse(1)" in profile_med["concept_rollup"]

        # 3. Tight cap: rollup is empty
        profile_tight = build_session_anki_profile(
            "Spine Emergencies",
            resolved_topic="spine-emergencies",
            max_chars=800,
            now_ms=NOW_MS,
        )
        assert profile_tight["concept_rollup"] == []
