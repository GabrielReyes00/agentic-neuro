"""Novelty filtering and persistence using FastEmbed + SQLite/Chroma."""

from __future__ import annotations

import hashlib
import sqlite3
import json
from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
import numpy as np

from .schemas import ClaimModel


@dataclass
class NoveltyDecision:
    claim_id: str
    claim_text: str
    max_similarity: float
    is_novel: bool
    matched_text: str = ""


class NoveltyStore:
    def __init__(self, db_path: str, collection_name: str, embedding_model: str):
        from fastembed import TextEmbedding  # type: ignore

        self._db_path = str(db_path)
        self._collection_name = collection_name
        self._embedder = TextEmbedding(model_name=embedding_model, cache_dir="data/Sessions/fastembed_cache")
        
        # If the path is a directory (like in Chroma tests/legacy setup), use ChromaDB
        if not self._db_path.endswith(".db"):
            import chromadb
            self._client = chromadb.PersistentClient(path=self._db_path)
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine", "schema": "anki_claim_memory"},
            )
        else:
            self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS card_vectors (
                id TEXT PRIMARY KEY,
                card_id INTEGER,
                document TEXT NOT NULL,
                metadata TEXT NOT NULL,
                vector BLOB NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_card_id ON card_vectors(card_id);")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS query_embeddings (
                query TEXT PRIMARY KEY,
                vector BLOB NOT NULL,
                timestamp REAL NOT NULL
            );
        """)
        conn.commit()
        conn.close()

    def _embed(self, texts: Iterable[str]) -> list[list[float]]:
        vectors = list(self._embedder.embed(list(texts)))
        return [list(map(float, vec.tolist() if hasattr(vec, "tolist") else vec)) for vec in vectors]

    def _query_max_similarity(self, embedding: list[float]) -> tuple[float, str]:
        """Return (max_similarity, matched_document_text)."""
        # Fallback to Chroma if initialized as a collection (e.g. in tests)
        if hasattr(self, "_collection"):
            if self._collection.count() == 0:
                return 0.0, ""
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=1,
                include=["distances", "documents"],
            )
            distances = (result.get("distances") or [[]])[0]
            documents = (result.get("documents") or [[]])[0]
            if not distances:
                return 0.0, ""
            try:
                distance = float(distances[0])
            except Exception:
                return 0.0, ""
            similarity = max(0.0, min(1.0, 1.0 - distance))
            matched_text = documents[0] if documents else ""
            return similarity, matched_text

        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT document, vector FROM card_vectors;")
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return 0.0, ""

        documents = []
        vectors = []
        for doc, vec_bytes in rows:
            documents.append(doc)
            vectors.append(np.frombuffer(vec_bytes, dtype=np.float32))

        vectors_matrix = np.array(vectors)
        q_vec = np.array(embedding, dtype=np.float32)

        # Cosine similarity (BGE embeddings are already normalized)
        similarities = np.dot(vectors_matrix, q_vec)
        max_idx = np.argmax(similarities)
        max_similarity = float(similarities[max_idx])
        matched_text = documents[max_idx]

        # Clamp similarity to [0.0, 1.0]
        similarity = max(0.0, min(1.0, max_similarity))
        return similarity, matched_text

    def filter_novel_claims(
        self,
        claims: list[ClaimModel],
        threshold: float,
    ) -> tuple[list[ClaimModel], list[NoveltyDecision]]:
        if not claims:
            return [], []

        embeddings = self._embed([c.claim_text for c in claims])
        novel: list[ClaimModel] = []
        decisions: list[NoveltyDecision] = []

        for claim, emb in zip(claims, embeddings):
            sim, matched = self._query_max_similarity(emb)
            is_novel = sim <= threshold
            decisions.append(
                NoveltyDecision(
                    claim_id=claim.claim_id,
                    claim_text=claim.claim_text,
                    max_similarity=sim,
                    is_novel=is_novel,
                    matched_text=matched,
                )
            )
            if is_novel:
                novel.append(claim)

        return novel, decisions

    def persist_claims(
        self,
        claims: list[ClaimModel],
        metadata: Mapping[str, str | int | float | bool] | Sequence[Mapping[str, str | int | float | bool]] | None = None,
    ) -> None:
        if not claims:
            return
        embeddings = self._embed([c.claim_text for c in claims])

        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict[str, str | int | float | bool]] = []
        per_claim_metadata: Sequence[Mapping[str, str | int | float | bool]] | None = None
        shared_metadata: Mapping[str, str | int | float | bool] | None = None
        if isinstance(metadata, Mapping):
            shared_metadata = metadata
        elif isinstance(metadata, Sequence) and not isinstance(metadata, (str, bytes)):
            per_claim_metadata = metadata

        for idx, claim in enumerate(claims):
            claim_hash = hashlib.sha256(claim.claim_text.encode("utf-8")).hexdigest()[:24]
            ids.append(f"claim-{claim_hash}")
            docs.append(claim.claim_text)
            row_meta: dict[str, str | int | float | bool] = {
                "claim_id": claim.claim_id,
                "topic": claim.topic,
                "concept": claim.concept,
                "card_type": claim.card_type,
            }
            if shared_metadata:
                row_meta.update(shared_metadata)
            if per_claim_metadata and idx < len(per_claim_metadata):
                row_meta.update(per_claim_metadata[idx])
            metas.append(row_meta)

        # Fallback to Chroma if initialized as a collection (e.g. in tests)
        if hasattr(self, "_collection"):
            self._collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
            return

        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        for cid, doc, meta, emb in zip(ids, docs, metas, embeddings):
            vec_bytes = np.array(emb, dtype=np.float32).tobytes()
            meta_str = json.dumps(meta)
            # Find card_id in metadata if it exists
            card_id = meta.get("card_id")
            cursor.execute("""
                INSERT INTO card_vectors (id, card_id, document, metadata, vector)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    card_id=excluded.card_id,
                    document=excluded.document,
                    metadata=excluded.metadata,
                    vector=excluded.vector;
            """, (cid, card_id, doc, meta_str, vec_bytes))
        conn.commit()
        conn.close()

    def replace_claims(
        self,
        claims: list[ClaimModel],
        metadata: Mapping[str, str | int | float | bool] | Sequence[Mapping[str, str | int | float | bool]] | None = None,
    ) -> None:
        """Replace the SQLite cache or Chroma collection with the supplied claims.

        Use this only when rebuilding from live Anki, which is the source of
        truth. The novelty store is an advisory cache, not an independent
        record that can veto new cards.
        """
        # Fallback to Chroma if initialized as a collection (e.g. in tests)
        if hasattr(self, "_collection"):
            try:
                self._client.delete_collection(self._collection_name)
            except Exception:
                pass
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine", "schema": "anki_claim_memory"},
            )
            self.persist_claims(claims, metadata)
            return

        conn = sqlite3.connect(self._db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM card_vectors;")
        conn.commit()
        conn.close()
        self.persist_claims(claims, metadata)
