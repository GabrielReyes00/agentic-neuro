"""Typed JSON payloads shared across the Anki sync CLI stages."""

from __future__ import annotations

from typing import Literal, TypedDict


class ImageSearchRequest(TypedDict):
    claim_id: str
    image_type: str
    search_queries: list[str]


class ImageCandidatePayload(TypedDict):
    url: str
    thumbnail_url: str
    title: str
    source: Literal["wikimedia", "openi"]
    license: str
    width: int
    height: int
    description: str
    attribution: str


class ImageSearchResultPayload(TypedDict):
    claim_id: str
    source_used: str
    candidates: list[ImageCandidatePayload]


class ThumbnailRecord(TypedDict):
    index: int
    file: str
    source_url: str
    title: str
    attribution: str


class ThumbnailManifestEntry(TypedDict):
    claim_id: str
    thumbnails: list[ThumbnailRecord]


class ImageSelectionPayload(TypedDict, total=False):
    claim_id: str
    image_url: str
    placement: Literal["front", "back", "both"]
    alt_text: str
    validated_by_vision: bool
    validation_scores: dict[str, int]
    fallback_urls: list[str]
    source_url: str
    attribution: str


class ImageAuditRow(TypedDict):
    claim_id: str
    source_used: str
    candidates_found: int
    selected_url: str | None
    status: str
    error: str


class ValidationReportPayload(TypedDict):
    cards_drafted: int
    cards_refined: int
