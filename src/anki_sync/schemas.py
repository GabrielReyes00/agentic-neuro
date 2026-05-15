"""Pydantic schemas for strict Anki stage outputs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ClaimModel(BaseModel):
    claim_id: str = Field(min_length=2, max_length=16)
    topic: str = Field(default="", max_length=200, description="Session topic for metadata")
    concept: str = Field(default="", max_length=260, description="Tested concept for metadata")
    card_type: str = Field(default="", max_length=10, description="cloze or qa")
    claim_text: str = Field(min_length=8, max_length=420, description="Card text for embedding")


class CardImage(BaseModel):
    """Image attachment for an Anki card."""

    filename: str = Field(max_length=120)
    data_b64: str = Field(default="")
    source_url: str = Field(default="", max_length=500)
    attribution: str = Field(default="", max_length=300)
    placement: Literal["front", "back", "both"] = "back"
    alt_text: str = Field(default="", max_length=300)


class CardDraft(BaseModel):
    claim_id: str = Field(min_length=2, max_length=16)
    card_type: Literal["cloze", "qa"]
    category: str = Field(default="", max_length=60)
    cloze_text: str = Field(default="", max_length=240)
    answer_text: str = Field(default="", max_length=200)
    front: str = Field(default="", max_length=500)
    back: str = Field(default="", max_length=500)
    image: Optional[CardImage] = None

    @model_validator(mode="after")
    def _enforce_card_shape(self):
        if self.card_type == "cloze":
            if not self.cloze_text.strip() or "{{c1::" not in self.cloze_text:
                raise ValueError("cloze card requires cloze_text containing {{c1::...}}")
            return self

        if not self.front.strip() or not self.back.strip():
            raise ValueError("qa card requires front/back")
        return self
