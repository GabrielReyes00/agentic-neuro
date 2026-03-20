"""AnkiConnect client utilities."""

from __future__ import annotations

import json
import re
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


class AnkiClient:
    def __init__(self, url: str):
        self.url = url

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

    def add_card(self, card: CardDraft, deck_name: str, tags: list[str] | None = None) -> AnkiDispatchResult:
        safe_tags = tags or ["Neuro-Agent", "CLI-Export", "anki-sync"]
        note = {
            "deckName": deck_name,
            "options": {"allowDuplicate": False},
            "tags": safe_tags,
            "fields": {},
            "modelName": "",
        }

        if card.card_type == "cloze":
            note["modelName"] = "Cloze"
            note["fields"] = {
                "Text": card.cloze_text.replace("\\n", "<br>"),
                "Extra": "",
            }
        else:
            note["modelName"] = "Basic"
            note["fields"] = {
                "Front": card.front.replace("\\n", "<br>"),
                "Back": card.back.replace("\\n", "<br>"),
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
