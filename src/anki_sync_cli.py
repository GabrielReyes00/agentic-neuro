#!/usr/bin/env python3
"""
Lightweight Anki Sync CLI tools.
Handles ChromaDB semantic novelty filtering and AnkiConnect dispatch.
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import sys
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping

from kg_constants import BASE_DIR, DATA_DIR, SESSIONS_DIR
from src.anki_sync.payloads import (
    ImageAuditRow,
    ImageCandidatePayload,
    ImageSearchRequest,
    ImageSearchResultPayload,
    ImageSelectionPayload,
    ThumbnailManifestEntry,
    ThumbnailRecord,
    ValidationReportPayload,
)

# Suppress ChromaDB telemetry warnings before any chromadb import
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


class _TelemetryFilter:
    """Filters out ChromaDB 0.6.x broken telemetry stderr messages."""
    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        if "Failed to send telemetry event" in text:
            return len(text)
        return self._stream.write(text)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stderr = _TelemetryFilter(sys.stderr)

sys.path.append(str(BASE_DIR))

try:
    from src.anki_sync.schemas import ClaimModel, CardDraft
    from src.anki_sync.novelty import NoveltyStore
    from src.anki_sync.anki_client import AnkiClient, make_deck_name
    HAS_SCHEMAS = True
except ImportError as e:
    print(f"Warning: Essential sync dependencies (pydantic) missing: {e}", file=sys.stderr)
    print("Falling back to simplified sync logic (validation disabled).", file=sys.stderr)
    HAS_SCHEMAS = False
    class CardDraft: pass 
    class ClaimModel: pass
    NoveltyStore = None
    from src.anki_sync.anki_client import AnkiClient, make_deck_name

RUNS_DIR = SESSIONS_DIR / "anki_sync_runs"
REQUIRED_BLIND_VALIDATION_FIELDS = ("prompt_visible", "self_guess", "exact_match", "revision_count")


def _read_json(filename: str) -> dict[str, object]:
    path = RUNS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Expected to find {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_list(filename: str, key: str) -> list[object]:
    """Reads JSON from file. If it's a dict with the key, returns that list. If it's a list, returns it."""
    path = RUNS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Expected to find {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get(key, [])
    if isinstance(data, list):
        return data
    return []


def _write_json(filename: str, data: object) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / filename
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _validate_blind_validation_meta(raw_card: Mapping[str, object], idx: int) -> None:
    """Enforce evidence that blind validation occurred for each drafted card."""
    meta = raw_card.get("blind_validation")
    if not isinstance(meta, dict):
        raise ValueError(
            f"Card {idx} ({raw_card.get('claim_id', 'unknown')}): missing blind_validation object"
        )

    missing = [k for k in REQUIRED_BLIND_VALIDATION_FIELDS if k not in meta]
    if missing:
        raise ValueError(
            f"Card {idx} ({raw_card.get('claim_id', 'unknown')}): blind_validation missing fields: {', '.join(missing)}"
        )

    if not str(meta.get("prompt_visible", "")).strip():
        raise ValueError(f"Card {idx}: blind_validation.prompt_visible must be non-empty")
    if not str(meta.get("self_guess", "")).strip():
        raise ValueError(f"Card {idx}: blind_validation.self_guess must be non-empty")
    if meta.get("exact_match") is not True:
        raise ValueError(
            f"Card {idx}: blind_validation.exact_match must be true before card inclusion"
        )

    rev = meta.get("revision_count")
    if not isinstance(rev, int) or rev < 0:
        raise ValueError(f"Card {idx}: blind_validation.revision_count must be an integer >= 0")


def _validate_final_cards_payload() -> tuple[list[CardDraft | dict[str, object]], ValidationReportPayload]:
    """Validate final_cards.json and return (cards, report)."""
    path = RUNS_DIR / "final_cards.json"
    if not path.exists():
        raise FileNotFoundError(f"Expected to find {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("final_cards.json must be an object with 'cards' and 'validation_report'")

    cards = payload.get("cards")
    if not isinstance(cards, list) or not cards:
        raise ValueError("final_cards.json cards must be a non-empty list")

    report = payload.get("validation_report")
    if not isinstance(report, dict):
        raise ValueError("final_cards.json missing validation_report object")

    drafted = report.get("cards_drafted")
    refined = report.get("cards_refined")
    if not isinstance(drafted, int) or drafted < len(cards):
        raise ValueError("validation_report.cards_drafted must be an integer >= number of cards")
    if not isinstance(refined, int) or refined < 0:
        raise ValueError("validation_report.cards_refined must be an integer >= 0")
    if len(cards) > 3 and refined == 0:
        raise ValueError(
            "validation_report.cards_refined is 0 with >3 cards; likely blind validation was skipped"
        )

    validated_cards: list[CardDraft | dict[str, object]] = []
    for idx, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise ValueError(f"Card {idx} is not a JSON object")
        _validate_blind_validation_meta(card, idx)
        if HAS_SCHEMAS:
            validated_cards.append(CardDraft.model_validate(card))
        else:
            validated_cards.append(card)

    validated_report: ValidationReportPayload = {
        "cards_drafted": drafted,
        "cards_refined": refined,
    }
    return validated_cards, validated_report


def filter_novelty():
    """Reads current_claims.json, filters against the Anki novelty store, writes novel_claims.json."""
    try:
        if not HAS_SCHEMAS or NoveltyStore is None:
            print(
                "Error in filter_novelty: required dependencies unavailable "
                "(pydantic + chromadb + fastembed).",
                file=sys.stderr,
            )
            sys.exit(1)

        claims_list = _read_json_list("current_claims.json", "claims")
        if not claims_list:
            _write_json("novel_claims.json", [])
            print("No claims found to filter.")
            return

        # STRICT validation: Every claim must have subject, verb, and object
        if HAS_SCHEMAS:
            claims = [ClaimModel.model_validate(c) for c in claims_list]
        else:
            claims = claims_list
        
        db_path = str(DATA_DIR / "chromadb_store_anki_memory")
        collection = "neurosurgery_memory_v1"
        fastembed_model = "BAAI/bge-small-en-v1.5"
        
        # This ChromaDB store is only for Anki claim novelty, not learner memory.
        store = NoveltyStore(db_path=db_path, collection_name=collection, embedding_model=fastembed_model)
        
        novelty_threshold = 0.88
        novel_claims, decisions = store.filter_novel_claims(claims=claims, threshold=novelty_threshold)
        
        if HAS_SCHEMAS:
            _write_json("novel_claims.json", [c.model_dump() for c in novel_claims])
        else:
            _write_json("novel_claims.json", novel_claims)
        print(f"Novelty filter complete. {len(novel_claims)} novel facts kept out of {len(claims)} total.")

    except Exception as e:
        print(f"Error in filter_novelty: {e}", file=sys.stderr)
        sys.exit(1)


def validate_final_cards():
    """Validate final_cards.json blind-validation metadata + CardDraft schema."""
    try:
        cards, report = _validate_final_cards_payload()
        _write_json(
            "validation_audit.json",
            {
                "ok": True,
                "cards": len(cards),
                "cards_drafted": report.get("cards_drafted"),
                "cards_refined": report.get("cards_refined"),
            },
        )
        print(
            "Validation complete. "
            f"Cards: {len(cards)} | Drafted: {report.get('cards_drafted')} | "
            f"Refined: {report.get('cards_refined')}"
        )
    except Exception as e:
        _write_json("validation_audit.json", {"ok": False, "error": str(e)})
        print(f"Error in validate_final_cards: {e}", file=sys.stderr)
        sys.exit(1)


def dispatch():
    """Reads final_cards.json/current_topic.json, sends to AnkiConnect, updates Anki novelty store."""
    try:
        cards, _report = _validate_final_cards_payload()
        if not cards:
            print("No final cards to dispatch.")
            return

        topic_data = _read_json("current_topic.json")
        topic = topic_data.get("topic", "Neuro RAG Session")
        deck_name = topic_data.get("deck") or make_deck_name("Neuro RAG", topic)
        
        client = AnkiClient("http://localhost:8765")
        ok, err = client.check_connection()
        if not ok:
            print(f"Failed to connect to Anki: {err}", file=sys.stderr)
            sys.exit(1)
            
        client.ensure_models()
        client.ensure_deck(deck_name)
        
        dispatch_results = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(client.add_card, c, deck_name) for c in cards]
            for fut in futures:
                try:
                    dispatch_results.append(fut.result())
                except Exception as e:
                    print(f"Failed to dispatch card: {e}", file=sys.stderr)
                    
        created = len([r for r in dispatch_results if r.status == "created"])
        duplicate = len([r for r in dispatch_results if r.status == "duplicate"])
        failed = len([r for r in dispatch_results if r.status == "failed"])
        
        # Persist successful claims into the Anki novelty store.
        success_claim_ids = {r.claim_id for r in dispatch_results if r.status in ("created", "duplicate")}
        
        claims_data = _read_json_list("novel_claims.json", "claims")
        persisted_claims = []
        persisted_claim_texts: list[str] = []
        for c in claims_data:
            if HAS_SCHEMAS:
                claim = ClaimModel.model_validate(c)
                claim_id = claim.claim_id
                claim_text = claim.claim_text
            else:
                if not isinstance(c, dict):
                    continue
                claim_id = str(c.get("claim_id", "")).strip()
                claim_text = str(c.get("claim_text", "")).strip()
                if not claim_id:
                    continue
                claim = c
            if claim_id in success_claim_ids:
                persisted_claims.append(claim)
                if claim_text:
                    persisted_claim_texts.append(claim_text)
                
        if persisted_claims and HAS_SCHEMAS and NoveltyStore is not None:
            db_path = str(DATA_DIR / "chromadb_store_anki_memory")
            collection = "neurosurgery_memory_v1"
            store = NoveltyStore(db_path=db_path, collection_name=collection, embedding_model="BAAI/bge-small-en-v1.5")
            store.persist_claims(persisted_claims, metadata={"topic": topic, "deck": deck_name})

        print(f"Dispatch complete! Created: {created} | Duplicates: {duplicate} | Failed: {failed}")
        if persisted_claims:
            print(f"Stored {len(persisted_claims)} conceptual rules in the Anki novelty store.")

        # ── Knowledge Graph signal (silent, never blocks) ──
        try:
            from src.knowledge_graph import KnowledgeGraph
            _kg = KnowledgeGraph()
            _kg.log_anki_creation(
                topic=topic,
                card_count=created,
                claim_texts=persisted_claim_texts if persisted_claim_texts else None,
            )
        except Exception:
            pass  # Knowledge graph must never block Anki sync

    except Exception as e:
        print(f"Error in dispatch: {e}", file=sys.stderr)
        sys.exit(1)


def search_images():
    """Search for candidate images for cards in final_cards.json.

    Reads image_search_requests.json (written by the subagent) with structure:
      [{"claim_id": "C001", "image_type": "anatomy_diagram",
        "search_queries": ["circle of willis labeled diagram", ...]}]

    Writes image_candidates.json with search results for the subagent to validate.
    """
    try:
        from src.anki_sync.image_search import search_images as _search, fallback_search

        requests_path = RUNS_DIR / "image_search_requests.json"
        if not requests_path.exists():
            print("No image_search_requests.json found.", file=sys.stderr)
            sys.exit(1)

        requests_data: list[ImageSearchRequest] = json.loads(requests_path.read_text(encoding="utf-8"))
        if not requests_data:
            print("No search requests to process.")
            return

        all_candidates: list[ImageSearchResultPayload] = []
        total_cards = len(requests_data)
        for i, req in enumerate(requests_data):
            claim_id = req["claim_id"]
            image_type = req.get("image_type", "anatomy_diagram")
            queries = req.get("search_queries", [])

            print(f"  [{i+1}/{total_cards}] Searching for {claim_id} ({image_type})...", flush=True)

            if not queries:
                all_candidates.append(
                    ImageSearchResultPayload(
                        claim_id=claim_id,
                        source_used="none",
                        candidates=[],
                    )
                )
                continue

            candidates, source = _search(image_type, queries, max_results=3)

            # If primary source returned < 2 results, try fallback
            if len(candidates) < 2:
                fallback = fallback_search(queries, source, image_type=image_type, max_results=3)
                seen_urls = {c.url for c in candidates}
                for c in fallback:
                    if c.url not in seen_urls:
                        seen_urls.add(c.url)
                        candidates.append(c)

            if not candidates:
                source_used = source if source == "openi_unavailable" else "none"
            else:
                sources = {c.source for c in candidates}
                source_used = source if len(sources) == 1 else "mixed"

            all_candidates.append(
                ImageSearchResultPayload(
                    claim_id=claim_id,
                    source_used=source_used,
                    candidates=[
                        ImageCandidatePayload(
                            url=c.url,
                            thumbnail_url=c.thumbnail_url,
                            title=c.title,
                            source=c.source,
                            license=c.license,
                            width=c.width,
                            height=c.height,
                            description=c.description,
                            attribution=c.attribution,
                        )
                        for c in candidates
                    ],
                )
            )

            # Rate-limit pacing: 1.5s between cards to avoid Wikimedia throttling
            if i < total_cards - 1:
                time.sleep(1.5)

        _write_json("image_candidates.json", all_candidates)
        total = sum(len(r["candidates"]) for r in all_candidates)
        print(f"Image search complete. {total} candidates across {len(all_candidates)} cards.")

    except Exception as e:
        print(f"Error in search_images: {e}", file=sys.stderr)
        sys.exit(1)


def download_thumbnails():
    """Batch-download top-N candidate thumbnails to /tmp/anki_thumbs/.

    Reads image_candidates.json, downloads up to 3 thumbnails per card,
    saves them as /tmp/anki_thumbs/{claim_id}_1.jpg, _2.jpg, _3.jpg.
    Writes a manifest to /tmp/anki_thumbs/manifest.json for the agent.

    This replaces 100+ individual Python shell calls with one batch command.
    """
    import shutil
    try:
        from src.anki_sync.image_processing import download_image, make_thumbnail_b64
        import base64

        candidates_path = RUNS_DIR / "image_candidates.json"
        if not candidates_path.exists():
            print("No image_candidates.json found.", file=sys.stderr)
            sys.exit(1)

        candidates_data: list[ImageSearchResultPayload] = json.loads(candidates_path.read_text(encoding="utf-8"))
        if not isinstance(candidates_data, list):
            print("image_candidates.json must be a list.", file=sys.stderr)
            sys.exit(1)

        thumb_dir = RUNS_DIR / "anki_thumbs"
        if thumb_dir.exists():
            shutil.rmtree(thumb_dir)
        thumb_dir.mkdir(parents=True)

        manifest: list[ThumbnailManifestEntry] = []
        max_per_card = 3
        total_cards = len(candidates_data)

        for i, entry in enumerate(candidates_data):
            cid = entry.get("claim_id", f"unknown_{i}")
            cands = entry.get("candidates", [])[:max_per_card]

            print(f"  [{i+1}/{total_cards}] Downloading thumbnails for {cid}...", flush=True)

            card_thumbs: list[ThumbnailRecord] = []
            for j, cand in enumerate(cands):
                thumb_url = cand.get("thumbnail_url") or cand.get("url", "")
                if not thumb_url:
                    continue
                filename = f"{cid}_{j+1}.jpg"
                filepath = thumb_dir / filename
                try:
                    raw = download_image(thumb_url, timeout=10, max_retries=1)
                    thumb_bytes = base64.b64decode(make_thumbnail_b64(raw))
                    filepath.write_bytes(thumb_bytes)
                    card_thumbs.append(
                        ThumbnailRecord(
                            index=j,
                            file=str(filepath),
                            source_url=cand.get("url", ""),
                            title=cand.get("title", ""),
                            attribution=cand.get("attribution", ""),
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"    Skipped {cid} candidate {j+1}: {e}", file=sys.stderr)

                # Pacing between downloads
                time.sleep(0.8)

            manifest.append(ThumbnailManifestEntry(claim_id=cid, thumbnails=card_thumbs))

        manifest_path = thumb_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        total_thumbs = sum(len(m["thumbnails"]) for m in manifest)
        print(f"Thumbnail download complete. {total_thumbs} thumbnails for {total_cards} cards.")
        print(f"Manifest: {manifest_path}")
        print(f"Use the Read tool on data/Sessions/anki_sync_runs/anki_thumbs/<claim_id>_<N>.jpg to visually inspect.")

    except Exception as e:
        print(f"Error in download_thumbnails: {e}", file=sys.stderr)
        sys.exit(1)


def process_selected_images():
    """Batch-process selected images and merge into final_cards.json.

    Preferred input: image_selections.json (written by image validation step), shape:
      [{
        "claim_id":"C001",
        "image_url":"https://...",
        "placement":"back",
        "alt_text":"...",
        "validated_by_vision": true,
        "validation_scores": {"relevance":4,"accuracy":4,"clarity":4,"quality":4}
      }]

    Strict mode by default: images are only processed when a claim has an
    explicit, vision-validated selection. No auto-picking from candidates.
    Writes final_cards.json and image_audit.json.
    """
    try:
        from src.anki_sync.image_processing import download_image, process_for_anki

        payload = _read_json("final_cards.json")
        cards = payload.get("cards", []) if isinstance(payload, dict) else []
        validation_report = payload.get("validation_report", {}) if isinstance(payload, dict) else {}
        if not cards:
            print("No cards found in final_cards.json.")
            return

        raw_candidates: list[ImageSearchResultPayload] = []
        candidates_path = RUNS_DIR / "image_candidates.json"
        if candidates_path.exists():
            raw_candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
            if not isinstance(raw_candidates, list):
                raise ValueError("image_candidates.json must be a list")
        candidates_by_claim = {
            row.get("claim_id"): row for row in raw_candidates if isinstance(row, dict) and row.get("claim_id")
        }

        selections_path = RUNS_DIR / "image_selections.json"
        selections_raw: list[ImageSelectionPayload] = []
        if selections_path.exists():
            maybe = json.loads(selections_path.read_text(encoding="utf-8"))
            if isinstance(maybe, list):
                selections_raw = maybe

        # Build selection map. Explicit vision-validated selections are required.
        selections_by_claim: dict[str, ImageSelectionPayload] = {}
        for item in selections_raw:
            if not isinstance(item, dict):
                continue
            cid = item.get("claim_id")
            if cid:
                selections_by_claim[cid] = item

        cards_by_claim = {}
        for card in cards:
            cid = card.get("claim_id")
            if cid:
                cards_by_claim[cid] = card
                # Reset image to prevent stale carry-over.
                card["image"] = None

        def _has_vision_validation(sel: dict) -> bool:
            scores = sel.get("validation_scores")
            return (
                sel.get("validated_by_vision") is True
                and isinstance(scores, dict)
                and all(k in scores for k in ("relevance", "accuracy", "clarity", "quality"))
            )

        def _alt_text(sel: dict, cand: dict) -> str:
            for field in (sel.get("alt_text"), (cand or {}).get("description"), (cand or {}).get("title")):
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", field or "")).strip()
                if text:
                    return text[:300]
            return "clinical image"

        audit_rows: list[ImageAuditRow] = []
        enriched = 0
        failed = 0

        for cid, card in cards_by_claim.items():
            selection = selections_by_claim.get(cid, {})
            row = candidates_by_claim.get(cid, {})
            candidate_list = row.get("candidates", []) if isinstance(row, dict) else []
            source_used = row.get("source_used", "none") if isinstance(row, dict) else "none"

            preferred_url = (selection.get("image_url") or "").strip()

            # Gate: must have a URL and full vision validation metadata
            if not preferred_url or not _has_vision_validation(selection):
                failed += 1
                status = "no_validated_selection" if not preferred_url else "missing_vision_metadata"
                audit_rows.append(
                    ImageAuditRow(
                        claim_id=cid,
                        source_used=source_used,
                        candidates_found=len(candidate_list),
                        selected_url=preferred_url or None,
                        status=status,
                        error=f"{status} for this claim",
                    )
                )
                continue

            # Build URL list: preferred + any fallbacks
            urls_to_try = [preferred_url]
            for fb in selection.get("fallback_urls") or []:
                url = (fb or "").strip()
                if url and url not in urls_to_try:
                    urls_to_try.append(url)

            chosen_candidate = None
            processed = None
            last_error = ""

            for url in urls_to_try:
                candidate = next((c for c in candidate_list if c.get("url") == url), {"url": url})
                try:
                    processed = process_for_anki(download_image(url), cid)
                    chosen_candidate = candidate
                    break
                except Exception as e:  # noqa: BLE001
                    last_error = str(e)

            if processed and chosen_candidate:
                placement = (selection.get("placement") or "back").strip().lower()
                if placement not in {"front", "back", "both"}:
                    placement = "back"
                card["image"] = {
                    "filename": processed.filename,
                    "data_b64": processed.data_b64,
                    "source_url": (selection.get("source_url") or chosen_candidate.get("url") or "")[:500],
                    "attribution": (selection.get("attribution") or chosen_candidate.get("attribution") or "")[:300],
                    "placement": placement,
                    "alt_text": _alt_text(selection, chosen_candidate),
                }
                enriched += 1
                audit_rows.append(
                    ImageAuditRow(
                        claim_id=cid,
                        source_used=source_used,
                        candidates_found=len(candidate_list),
                        selected_url=chosen_candidate.get("url"),
                        status="enriched",
                        error="",
                    )
                )
            else:
                failed += 1
                audit_rows.append(
                    ImageAuditRow(
                        claim_id=cid,
                        source_used=source_used,
                        candidates_found=len(candidate_list),
                        selected_url=None,
                        status="download_failed",
                        error=last_error,
                    )
                )

            time.sleep(1.0)  # rate-limit pacing

        _write_json("final_cards.json", {"cards": cards, "validation_report": validation_report})
        _write_json("image_audit.json", audit_rows)
        print(
            "Batch image processing complete. "
            f"Enriched: {enriched} | Text-only: {failed} | Total: {len(cards)}"
        )

    except Exception as e:
        print(f"Error in process_selected_images: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python3 src/anki_sync_cli.py "
            "[filter_novelty|validate_final_cards|dispatch|search_images|download_thumbnails|process_selected_images]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = sys.argv[1].strip().lower()
    commands = {
        "filter_novelty": filter_novelty,
        "validate_final_cards": validate_final_cards,
        "dispatch": dispatch,
        "search_images": search_images,
        "download_thumbnails": download_thumbnails,
        "process_selected_images": process_selected_images,
    }
    if cmd in commands:
        commands[cmd]()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
