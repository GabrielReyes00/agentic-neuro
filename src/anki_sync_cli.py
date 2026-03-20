#!/usr/bin/env python3
"""
Lightweight Anki Sync CLI tools.
Handles ChromaDB semantic novelty filtering and AnkiConnect dispatch.
All LLM reasoning is handled natively by the Gemini CLI or Claude Code Agent workflow.
"""

import warnings
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import sys
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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

# Make sure we can import from the rest of the source
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

try:
    from src.anki_sync.schemas import ClaimModel, CardDraft
    from src.anki_sync.novelty import NoveltyStore
    from src.anki_sync.anki_client import AnkiClient, make_deck_name
except ImportError as e:
    print(f"Error importing modules: {e}", file=sys.stderr)
    sys.exit(1)

RUNS_DIR = BASE_DIR / "data" / "Sessions" / "anki_sync_runs"


def _read_json(filename: str) -> dict:
    path = RUNS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Expected to find {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(filename: str, data):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / filename
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def filter_novelty():
    """Reads current_claims.json, filters against ChromaDB, writes novel_claims.json"""
    try:
        claims_data = _read_json("current_claims.json")
        claims_list = claims_data.get("claims", [])
        if not claims_list:
            _write_json("novel_claims.json", [])
            print("No claims found to filter.")
            return

        claims = [ClaimModel.model_validate(c) for c in claims_list]
        
        db_path = str(BASE_DIR / "data" / "chromadb_store_anki_memory")
        collection = "neurosurgery_memory_v1"
        fastembed_model = "BAAI/bge-small-en-v1.5"
        
        # Initialize the ChromaDB store for memory if it doesn't already exist
        store = NoveltyStore(db_path=db_path, collection_name=collection, embedding_model=fastembed_model)
        
        novelty_threshold = 0.88
        novel_claims, decisions = store.filter_novel_claims(claims=claims, threshold=novelty_threshold)
        
        _write_json("novel_claims.json", [c.model_dump() for c in novel_claims])
        print(f"Novelty filter complete. {len(novel_claims)} novel facts kept out of {len(claims)} total.")

    except Exception as e:
        print(f"Error in filter_novelty: {e}", file=sys.stderr)
        sys.exit(1)


def dispatch():
    """Reads final_cards.json and current_topic.json, sends to AnkiConnect, saves to ChromaDB"""
    try:
        cards_data = _read_json("final_cards.json")
        cards_list = cards_data.get("cards", [])
        if not cards_list:
            print("No final cards to dispatch.")
            return

        cards = [CardDraft.model_validate(c) for c in cards_list]
        
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
        
        # Persist the successful claims into ChromaDB memory store
        success_claim_ids = {r.claim_id for r in dispatch_results if r.status in ("created", "duplicate")}
        
        claims_data = _read_json("novel_claims.json")
        persisted_claims = []
        for c in claims_data:
            claim = ClaimModel.model_validate(c)
            if claim.claim_id in success_claim_ids:
                persisted_claims.append(claim)
                
        if persisted_claims:
            db_path = str(BASE_DIR / "data" / "chromadb_store_anki_memory")
            collection = "neurosurgery_memory_v1"
            store = NoveltyStore(db_path=db_path, collection_name=collection, embedding_model="BAAI/bge-small-en-v1.5")
            store.persist_claims(persisted_claims, metadata={"topic": topic, "deck": deck_name})

        print(f"Dispatch complete! Created: {created} | Duplicates: {duplicate} | Failed: {failed}")
        if persisted_claims:
            print(f"Stored {len(persisted_claims)} conceptual rules into long-term Memory ChromaDB.")

        # ── Knowledge Graph signal (silent, never blocks) ──
        try:
            from src.knowledge_graph import KnowledgeGraph
            _kg = KnowledgeGraph()
            _kg.log_anki_creation(
                topic=topic,
                card_count=created,
                claim_texts=[c.claim_text for c in persisted_claims] if persisted_claims else None,
            )
        except Exception:
            pass  # Knowledge graph must never block Anki sync

    except Exception as e:
        print(f"Error in dispatch: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 src/anki_sync_cli.py [filter_novelty|dispatch]", file=sys.stderr)
        sys.exit(1)
        
    cmd = sys.argv[1].strip().lower()
    if cmd == "filter_novelty":
        filter_novelty()
    elif cmd == "dispatch":
        dispatch()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
