"""AnkiConnect client utilities."""

from __future__ import annotations

import json
import re
from html import escape
import urllib.error
import urllib.request
from dataclasses import dataclass

from .schemas import CardDraft


@dataclass
class AnkiDispatchResult:
    claim_id: str
    card_type: str
    status: str
    note_id: int | None
    error: str


def _format_text(text: str) -> str:
    """Convert markdown-lite text to Anki HTML."""
    t = text.replace("\\n", "<br>")
    t = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\*(.*?)\*", r"<i>\1</i>", t)
    return t


class AnkiClient:
    def __init__(self, url: str):
        self.url = url
        self._model_fields_cache: dict[str, set[str]] = {}

    def _invoke(self, action: str, timeout: int = 8, **params):
        payload = {"action": action, "version": 6, "params": params}
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                res = json.loads(response.read().decode("utf-8"))
                if res.get("error"):
                    raise RuntimeError(str(res["error"]))
                return res.get("result")
        except urllib.error.URLError as e:
            raise ConnectionError(f"Cannot connect to AnkiConnect at {self.url}: {e}") from e

    def check_connection(self) -> tuple[bool, str]:
        try:
            self._invoke("version", timeout=3)
            return True, ""
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def ensure_deck(self, deck_name: str) -> None:
        existing = set(self._invoke("deckNames") or [])
        if deck_name not in existing:
            self._invoke("createDeck", deck=deck_name)

    def ensure_models(self) -> None:
        names = set(self._invoke("modelNames") or [])
        missing = []
        for model_name in ("Basic", "Cloze"):
            if model_name not in names:
                missing.append(model_name)
        if missing:
            raise RuntimeError(f"Required built-in Anki models missing: {', '.join(missing)}")

    def _model_fields(self, model_name: str) -> set[str]:
        if model_name not in self._model_fields_cache:
            names = self._invoke("modelFieldNames", modelName=model_name) or []
            self._model_fields_cache[model_name] = set(names)
        return self._model_fields_cache[model_name]

    def store_media_file(self, filename: str, data_b64: str) -> None:
        """Store an image file in Anki's collection.media folder via AnkiConnect."""
        self._invoke(
            "storeMediaFile",
            filename=filename,
            data=data_b64,
            deleteExisting=True,
        )

    def _build_image_html(self, card: CardDraft) -> str:
        """Build the <img> HTML block for a card's image, if present."""
        if not card.image:
            return ""
        img = card.image
        image_html = (
            f'<div class="card-image">'
            f'<img src="{escape(img.filename, quote=True)}" alt="{escape(img.alt_text, quote=True)}">'
            f'</div>'
        )
        if img.attribution:
            image_html += f'<div class="image-attribution">{escape(img.attribution)}</div>'
        return image_html

    def add_card(self, card: CardDraft, deck_name: str, tags: list[str] | None = None) -> AnkiDispatchResult:
        safe_tags = tags or ["Neuro-Agent", "CLI-Export", "anki-sync"]

        # Store the image file first if present
        if card.image and card.image.data_b64:
            try:
                self.store_media_file(card.image.filename, card.image.data_b64)
            except Exception as e:  # noqa: BLE001
                # Image storage failure is non-fatal — card still gets created without image
                import sys
                print(f"Warning: failed to store image {card.image.filename}: {e}", file=sys.stderr)
                card.image = None  # clear so we don't reference a missing file

        note = {
            "deckName": deck_name,
            "options": {"allowDuplicate": False},
            "tags": safe_tags,
            "fields": {},
            "modelName": "",
        }

        img_html = self._build_image_html(card)

        if card.card_type == "cloze":
            note["modelName"] = "Cloze"
            cloze_fields = self._model_fields("Cloze")
            extra_field = "Extra" if "Extra" in cloze_fields else "Back Extra" if "Back Extra" in cloze_fields else None
            fields = {"Text": _format_text(card.cloze_text)}
            if extra_field:
                fields[extra_field] = img_html
            note["fields"] = fields
        else:
            note["modelName"] = "Basic"
            front_text = _format_text(card.front)
            back_text = _format_text(card.back)

            if card.image:
                placement = card.image.placement
                if placement in ("back", "both"):
                    back_text += f"<br>{img_html}"
                if placement in ("front", "both"):
                    front_text = f"{img_html}<br>{front_text}"

            note["fields"] = {
                "Front": front_text,
                "Back": back_text,
            }

        try:
            note_id = self._invoke("addNote", note=note)
            if note_id:
                return AnkiDispatchResult(
                    claim_id=card.claim_id,
                    card_type=card.card_type,
                    status="created",
                    note_id=int(note_id),
                    error="",
                )
            return AnkiDispatchResult(
                claim_id=card.claim_id,
                card_type=card.card_type,
                status="duplicate",
                note_id=None,
                error="Duplicate card",
            )
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "duplicate" in msg.lower():
                return AnkiDispatchResult(
                    claim_id=card.claim_id,
                    card_type=card.card_type,
                    status="duplicate",
                    note_id=None,
                    error="Duplicate card",
                )
            return AnkiDispatchResult(
                claim_id=card.claim_id,
                card_type=card.card_type,
                status="failed",
                note_id=None,
                error=msg,
            )



def make_deck_name(root_deck: str, topic: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9\s\-/&]", " ", (topic or "").replace("::", " "))
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        clean = "Session"
    clean = clean[:60]
    return f"{root_deck}::{clean}"
