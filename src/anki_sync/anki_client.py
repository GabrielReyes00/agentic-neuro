"""AnkiConnect client utilities."""

from __future__ import annotations

import json
import re
from html import escape
import urllib.error
import urllib.request
from dataclasses import dataclass

from .schemas import CardDraft, CardImage


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

    def list_decks(self) -> list[str]:
        return list(self._invoke("deckNames") or [])

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

    def find_cards(self, query: str) -> list[int]:
        """Return Anki card IDs matching a search query (e.g. 'deck:Neuro*')."""
        result = self._invoke("findCards", query=query)
        if isinstance(result, list):
            return [int(c) for c in result if c is not None]
        return []

    def cards_info(self, card_ids: list[int], batch_size: int = 50) -> list[dict]:
        """Fetch detail objects for the given card IDs in batches."""
        out: list[dict] = []
        for i in range(0, len(card_ids), batch_size):
            batch = card_ids[i : i + batch_size]
            chunk = self._invoke("cardsInfo", cards=batch)
            if isinstance(chunk, list):
                out.extend(item for item in chunk if isinstance(item, dict))
        return out

    def notes_info(self, note_ids: list[int], batch_size: int = 50) -> list[dict]:
        """Fetch detail objects for the given note IDs in batches."""
        out: list[dict] = []
        for i in range(0, len(note_ids), batch_size):
            batch = note_ids[i : i + batch_size]
            chunk = self._invoke("notesInfo", notes=batch)
            if isinstance(chunk, list):
                out.extend(item for item in chunk if isinstance(item, dict))
        return out

    def store_media_file(self, filename: str, data_b64: str) -> None:
        """Store an image file in Anki's collection.media folder via AnkiConnect."""
        self._invoke(
            "storeMediaFile",
            filename=filename,
            data=data_b64,
            deleteExisting=True,
        )

    def _build_image_html(self, image: CardImage | None) -> str:
        """Build the <img> HTML block for a card's image, if present."""
        if not image:
            return ""
        image_html = (
            f'<div class="card-image">'
            f'<img src="{escape(image.filename, quote=True)}" alt="{escape(image.alt_text, quote=True)}">'
            f'</div>'
        )
        if image.attribution:
            image_html += f'<div class="image-attribution">{escape(image.attribution)}</div>'
        return image_html

    def add_card(self, card: CardDraft, deck_name: str, tags: list[str] | None = None) -> AnkiDispatchResult:
        safe_tags = tags or ["Neuro-Agent", "CLI-Export", "anki-sync"]
        image = card.image

        # Store the image file first if present
        if image and image.data_b64:
            try:
                self.store_media_file(image.filename, image.data_b64)
            except Exception as e:  # noqa: BLE001
                # Image storage failure is non-fatal — card still gets created without image
                import sys
                print(f"Warning: failed to store image {image.filename}: {e}", file=sys.stderr)
                image = None

        note = {
            "deckName": deck_name,
            "options": {"allowDuplicate": False},
            "tags": safe_tags,
            "fields": {},
            "modelName": "",
        }

        img_html = self._build_image_html(image)

        if card.card_type == "cloze":
            note["modelName"] = "Cloze"
            cloze_fields = self._model_fields("Cloze")
            extra_field = "Extra" if "Extra" in cloze_fields else "Back Extra" if "Back Extra" in cloze_fields else None
            fields = {"Text": _format_text(card.cloze_text)}
            if extra_field:
                extra_parts = []
                answer_text = _format_text(getattr(card, "answer_text", "") or "")
                if answer_text:
                    extra_parts.append(answer_text)
                if img_html:
                    extra_parts.append(img_html)
                fields[extra_field] = "<br>".join(extra_parts)
            note["fields"] = fields
        else:
            note["modelName"] = "Basic"
            front_text = _format_text(card.front)
            back_text = _format_text(card.back)

            if image:
                placement = image.placement
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
