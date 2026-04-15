"""Novelty filtering and persistence using FastEmbed + Chroma."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from collections.abc import Iterable, Mapping

from .schemas import ClaimModel


@dataclass
class NoveltyDecision:
    claim_id: str
    claim_text: str
    max_similarity: float
    is_novel: bool


class NoveltyStore:
    def __init__(self, db_path: str, collection_name: str, embedding_model: str):
        import chromadb  # type: ignore
        from fastembed import TextEmbedding  # type: ignore

        self._client = chromadb.PersistentClient(path=str(db_path))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine", "schema": "anki_claim_memory_v1"},
        )
        self._embedder = TextEmbedding(model_name=embedding_model)

    def _embed(self, texts: Iterable[str]) -> list[list[float]]:
        vectors = list(self._embedder.embed(list(texts)))
        return [list(map(float, vec.tolist() if hasattr(vec, "tolist") else vec)) for vec in vectors]

    def _query_max_similarity(self, embedding: list[float]) -> float:
        if self._collection.count() == 0:
            return 0.0
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["distances"],
        )
        distances = (result.get("distances") or [[]])[0]
        if not distances:
            return 0.0
        try:
            distance = float(distances[0])
        except Exception:
            return 0.0
        similarity = 1.0 - distance
        return max(0.0, min(1.0, similarity))

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
            sim = self._query_max_similarity(emb)
            is_novel = sim <= threshold
            decisions.append(
                NoveltyDecision(
                    claim_id=claim.claim_id,
                    claim_text=claim.claim_text,
                    max_similarity=sim,
                    is_novel=is_novel,
                )
            )
            if is_novel:
                novel.append(claim)

        return novel, decisions

    def persist_claims(
        self,
        claims: list[ClaimModel],
        metadata: Mapping[str, str | int | float | bool] | None = None,
    ) -> None:
        if not claims:
            return
        embeddings = self._embed([c.claim_text for c in claims])

        ids: list[str] = []
        docs: list[str] = []
        metas: list[dict[str, str | int | float | bool]] = []
        for claim in claims:
            claim_hash = hashlib.sha256(claim.claim_text.encode("utf-8")).hexdigest()[:24]
            ids.append(f"claim-{claim_hash}")
            docs.append(claim.claim_text)
            row_meta: dict[str, str | int | float | bool] = {
                "claim_id": claim.claim_id,
                "subject": claim.subject,
                "verb": claim.verb,
                "object": claim.object,
            }
            if metadata:
                row_meta.update(metadata)
            metas.append(row_meta)

        self._collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
