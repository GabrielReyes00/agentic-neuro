"""Pydantic schemas for strict Anki stage outputs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ClaimModel(BaseModel):
    claim_id: str = Field(min_length=2, max_length=16)
    subject: str = Field(min_length=1, max_length=200)
    verb: str = Field(min_length=1, max_length=120)
    object: str = Field(min_length=1, max_length=260)
    claim_text: str = Field(min_length=8, max_length=420)


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
    cloze_text: str = Field(default="", max_length=600)
    answer_text: str = Field(default="", max_length=200)
    front: str = Field(default="", max_length=500)
    back: str = Field(default="", max_length=500)
    image: Optional[CardImage] = None

    @model_validator(mode="after")
    def _enforce_card_shape(self):
        if self.card_type == "cloze":
            if not self.cloze_text.strip() or "{{c1::" not in self.cloze_text:
                raise ValueError("cloze card requires cloze_text containing {{c1::...}}")
            if not self.answer_text.strip():
                raise ValueError("cloze card requires answer_text")
            return self

        if not self.front.strip() or not self.back.strip():
            raise ValueError("qa card requires front/back")
        return self
