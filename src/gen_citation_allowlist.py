"""Generate the citation source allowlist from the live RAG table.

Writes data/rag_textbook_sources.json with, per book, the full source_book
name and a distinctive citation key (the short form a writer actually cites by,
e.g. 'Greenberg', 'Youmans', 'Fundamentals', 'Peripheral Nerve'). The validator
loads this file so its citation-density check recognizes any real RAG source.
Run this whenever the RAG corpus changes.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lance_retriever as lr  # noqa: E402
import pyarrow.compute as pc  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

DROP = {"of", "and", "the", "in", "a", "an", "to", "edition", "ed", "8th",
        "1st", "2nd", "3rd", "4th", "through", "for"}
# Non-clinical books that would never be a legitimate operative-guide citation.
EXCLUDE = ("Grant Writing", "How to Write", "A History of Neurosurgery")
# Books whose first significant word is too generic to stand alone as a citation
# key (would false-match ordinary prose) — use the first two significant words.
GENERIC_FIRST = {"atlas", "operative", "comprehensive", "brain", "cranial",
                 "neuro", "imaging", "intensive", "neurosurgery", "peripheral",
                 "neuroanatomy", "essential"}


def short_key(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in DROP]
    if not words:
        return name
    if words[0].lower() in GENERIC_FIRST and len(words) >= 2:
        return f"{words[0]} {words[1]}"
    return words[0]


def main():
    table = lr._get_lance_table()
    arrow = table.to_arrow()
    vc = pc.value_counts(arrow["source_book"])
    books = []
    for i in range(len(vc)):
        name = vc[i]["values"].as_py()
        if name and not any(x.lower() in name.lower() for x in EXCLUDE):
            books.append(name)
    books = sorted(set(books))

    keys = {}
    for b in books:
        keys.setdefault(short_key(b), []).append(b)

    payload = {
        "generated_from": lr.DEFAULT_LANCE_TABLE,
        "book_count": len(books),
        "books": books,
        # citation keys the validator matches against (case-insensitive substring)
        "citation_keys": sorted(keys.keys()) + ["Rhoton", "PMID", "DOI"],
    }
    out = REPO / "data" / "rag_textbook_sources.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"wrote {out}")
    print(json.dumps(payload["citation_keys"], indent=2))


if __name__ == "__main__":
    main()
