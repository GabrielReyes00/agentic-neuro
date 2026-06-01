"""
LanceDB Retrieval Module — Primary retrieval engine for agentic-neuro.

Pipeline: BGE-M3 encode → Dense search + FTS → RRF fusion → MiniLM-L6 rerank
          → Entity-aware filtering → Parent-child expansion
          → Adaptive Context Distillation (axis decomposition + budgeting) → Output

CLI:
    python3 src/lance_retriever.py compare "query" --stdout [--no-frontier]
    python3 src/lance_retriever.py list_textbooks
    python3 src/lance_retriever.py search "query" [--json]
"""

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

# ── Venv & working directory guard ───────────────────────────────────────────
if __name__ == "__main__":
    from _env_guard import check_environment
    check_environment("lance_retriever.py")
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
SESSIONS_DIR = DATA_DIR / "Sessions"

# ── Configuration ────────────────────────────────────────────────────────────

# LanceDB defaults
DEFAULT_LANCE_DIR = os.environ.get(
    "NEURO_LANCE_DIR",
    str(BASE_DIR),
)
DEFAULT_LANCE_TABLE = os.environ.get("NEURO_LANCE_TABLE", "neurosurgery_v4")

# Retrieval parameters
DEFAULT_MIN_SIMILARITY = 0.35
DEFAULT_N_RESULTS = 35
PRE_RERANK_MAX_CANDIDATES = 55
RERANKER_SCORE_FLOOR = float(os.environ.get("NEURO_RERANKER_SCORE_FLOOR", "0.15"))

# Context limits
CONTEXT_MAX_PASSAGES = int(os.environ.get("NEURO_CONTEXT_MAX_PASSAGES", "8"))
CONTEXT_MIN_SOURCES = int(os.environ.get("NEURO_CONTEXT_MIN_SOURCES", "3"))

# Quality-aware augmentation (AUG-CE)
# Non-destructive: appends up to AUG_MAX_EXTRA passages to the post-distill
# context when the candidate pool contains a passage with a meaningful quality
# gain over the current weakest baseline passage AND a cross-encoder score at
# or above the floor. Gated on three axes (Δ-quality, CE floor, token budget)
# to avoid the QA-full failure mode where term-coverage sorting overrides CE.
AUG_MAX_EXTRA = int(os.environ.get("NEURO_AUG_MAX_EXTRA", "2"))
AUG_TOKEN_BUDGET = int(os.environ.get("NEURO_AUG_TOKEN_BUDGET", "8000"))
AUG_MIN_Q_DELTA = float(os.environ.get("NEURO_AUG_MIN_Q_DELTA", "0.05"))
AUG_CE_ABS_FLOOR = float(os.environ.get("NEURO_AUG_CE_ABS_FLOOR", "0.85"))
AUG_CE_REL_FRAC = float(os.environ.get("NEURO_AUG_CE_REL_FRAC", "0.92"))
AUG_TERM_STOP_EXTRA = {
    "surgical", "operative", "management", "treatment", "approach",
    "patient", "patients", "clinical", "disease", "syndrome", "imaging",
}

# Reranker model registry
RERANKER_MODELS = {
    "bge-reranker-base": "BAAI/bge-reranker-base",
    "minilm-l6": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "minilm-l4": "cross-encoder/ms-marco-MiniLM-L-4-v2",
}
DEFAULT_RERANKER = "minilm-l6"

# Medical stopwords for keyword extraction
STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "some", "them",
    "than", "its", "over", "such", "that", "this", "with", "will", "each",
    "from", "they", "were", "which", "their", "what", "there", "when", "make",
    "like", "into", "also", "most", "more", "other", "these", "then", "does",
    "may", "should", "could", "would", "about", "after", "before", "during",
    "between", "through", "being", "those", "where", "very", "well", "much",
    "many", "only", "both", "same", "often", "usually", "typically",
}


# ── Lazy-loaded singletons ──────────────────────────────────────────────────

_LANCE_DB = None
_LANCE_TABLE = None
_EMBEDDING_MODEL = None
_RERANKER_CACHE: Dict[str, Any] = {}


class _ClonedCrossEncoder:
    """Cross-encoder wrapper that avoids mmap-backed safetensors at inference.

    On this local macOS/Python/Torch stack, the normal SentenceTransformers
    CrossEncoder path can bus-error inside BLAS when running from cached
    safetensors. Cloning the weights into regular contiguous CPU tensors avoids
    that uncatchable process crash while preserving the same model.
    """

    def __init__(self, model_id: str):
        from huggingface_hub import snapshot_download
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer
        import torch

        local_path = Path(snapshot_download(model_id, local_files_only=True))
        model_file = local_path / "model.safetensors"
        if not model_file.exists():
            raise FileNotFoundError(f"No local safetensors file for {model_id}")

        self.tokenizer = AutoTokenizer.from_pretrained(local_path, local_files_only=True)
        config = AutoConfig.from_pretrained(local_path, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_config(config)
        state = load_file(str(model_file), device="cpu")
        state = {k: v.clone().contiguous() for k, v in state.items()}
        self.model.load_state_dict(state, strict=False)
        self.model.eval()
        self._torch = torch

    def predict(self, pairs: list, batch_size: int = 32):
        scores = []
        with self._torch.no_grad():
            for i in range(0, len(pairs), batch_size):
                batch = pairs[i:i + batch_size]
                queries = [p[0] for p in batch]
                docs = [p[1] for p in batch]
                inputs = self.tokenizer(
                    queries,
                    docs,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=512,
                )
                logits = self.model(**inputs).logits.reshape(-1)
                scores.extend(float(x) for x in logits)
        return scores


def _list_lancedb_tables(db) -> list[str]:
    """Return table names across older/newer LanceDB client APIs."""
    raw = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    if hasattr(raw, "tables"):
        return list(raw.tables)
    return list(raw)


def _get_lance_table(lance_dir: str = "", table_name: str = ""):
    """Open LanceDB connection and table (lazy, cached)."""
    global _LANCE_DB, _LANCE_TABLE
    lance_dir = lance_dir or DEFAULT_LANCE_DIR
    table_name = table_name or DEFAULT_LANCE_TABLE

    if _LANCE_TABLE is not None:
        return _LANCE_TABLE

    import lancedb
    _LANCE_DB = lancedb.connect(lance_dir)
    _LANCE_TABLE = _LANCE_DB.open_table(table_name)
    return _LANCE_TABLE


def _get_embedding_model():
    """Load BGE-M3 for query encoding (dense + sparse)."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        from FlagEmbedding import BGEM3FlagModel
        _EMBEDDING_MODEL = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    return _EMBEDDING_MODEL


def _get_reranker(model_key: str = DEFAULT_RERANKER):
    """Load a cross-encoder reranker by key. Cached per model_key."""
    if model_key in _RERANKER_CACHE:
        return _RERANKER_CACHE[model_key], model_key

    model_id = RERANKER_MODELS.get(model_key, model_key)
    try:
        ce = _ClonedCrossEncoder(model_id)
        ce.predict([["warmup", "warmup"]], batch_size=1)
        _RERANKER_CACHE[model_key] = ce
        return ce, model_key
    except Exception as cloned_exc:
        cloned_error = cloned_exc

    try:
        from sentence_transformers import CrossEncoder
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        ce = CrossEncoder(model_id, device=device)
        ce.predict([["warmup", "warmup"]])
        _RERANKER_CACHE[model_key] = ce
        return ce, model_key
    except Exception as e:
        print(f"[WARN] Failed to load reranker '{model_id}': {e}; cloned loader also failed: {cloned_error}")
        _RERANKER_CACHE[model_key] = None
        return None, model_key


# ── Utility functions ────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> set:
    tokens = re.findall(r"[a-zA-Z]{3,}", (text or "").lower())
    return {t for t in tokens if t not in STOPWORDS}


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _content_hash(text: str) -> str:
    return (text or "").strip().lower()[:220]


def _reference_signal_counts(text: str) -> dict:
    text_lower = (text or "").lower()
    total_chars = max(1, len(text or ""))
    et_al_count = text_lower.count("et al")
    return {
        "et_al_count": et_al_count,
        "et_al_density": et_al_count / (total_chars / 1000.0),
        "numbered_refs": len(re.findall(r'(?:^|\n)\s*\d{1,3}\.\s+[A-Z][a-z]', text or "")),
        "journal_patterns": (
            len(re.findall(r'\d{4};\s*\d+', text or ""))
            + len(re.findall(r'\d+:\d+-\d+', text or ""))
        ),
        "semicolons": (text or "").count(';'),
    }


def _is_reference_chunk(text: str) -> bool:
    """Detect bibliography/citation-list chunks."""
    if not text or len(text) < 100:
        return False
    counts = _reference_signal_counts(text)

    score = 0
    if counts["et_al_density"] > 3.0:
        score += 3
    elif counts["et_al_density"] > 1.5:
        score += 2
    elif counts["et_al_density"] > 0.5:
        score += 1
    if counts["numbered_refs"] >= 5:
        score += 3
    elif counts["numbered_refs"] >= 3:
        score += 2
    if counts["journal_patterns"] >= 6:
        score += 2
    elif counts["journal_patterns"] >= 3:
        score += 1
    if counts["semicolons"] > 10 and counts["et_al_count"] > 2:
        score += 1
    return score >= 4


def _is_low_value_retrieval_hit(hit: dict) -> bool:
    """Detect reference/index/navigation hits before they consume passage slots."""
    text = hit.get("distilled_text") or hit.get("text") or hit.get("parent_text") or ""
    if _is_reference_chunk(text):
        return True

    citation = (hit.get("citation") or "").lower()
    heading = (hit.get("metadata", {}).get("heading") or "").lower()
    section_path = (hit.get("metadata", {}).get("section_path") or "").lower()
    joined_meta = f" {citation} {heading} {section_path} "
    counts = _reference_signal_counts(text)

    if " ch: index " in joined_meta or " index " == f" {heading.strip()} ":
        return True

    is_reference_section = (
        " ch: references " in joined_meta
        or heading.strip() in {"references", "bibliography"}
        or section_path.strip().endswith("references")
    )
    if is_reference_section and counts["et_al_count"] >= 1 and counts["journal_patterns"] >= 1:
        return True

    nav_markers = len(re.findall(
        r"\.{3,}\s*\d+|(?:\.\s*){6,}\d+|,\s*[123]\s*=",
        text or "",
    ))
    if nav_markers >= 4 and ("imaging and diagnostics" in joined_meta or "contents" in joined_meta):
        return True
    if nav_markers >= 8 and counts["et_al_count"] == 0:
        return True

    return False


# ── Medical NER (SciSpacy) — lazy loaded ─────────────────────────────────────

_NER_NLP = None  # lazy singleton
_ENTITY_CACHE: Dict[str, List[str]] = {}  # query → entities (avoids repeated NER calls)
_NER_DOC_CACHE: Dict[str, Any] = {}  # query → spacy Doc (avoids re-running NER for drug/disease)

def _get_ner_nlp():
    """Lazily load SciSpacy NER model (en_ner_bc5cdr_md).

    Returns spacy Language or None if unavailable. ~200ms first call, cached after.
    Recognizes CHEMICAL (drugs) and DISEASE entities in biomedical text.
    """
    global _NER_NLP
    if _NER_NLP is not None:
        return _NER_NLP if _NER_NLP != "UNAVAILABLE" else None
    try:
        import spacy
        _NER_NLP = spacy.load("en_ner_bc5cdr_md")
        return _NER_NLP
    except Exception:
        _NER_NLP = "UNAVAILABLE"
        return None


def _extract_entities_via_ner(query: str) -> Optional[List[str]]:
    """Extract medical entities using SciSpacy NER model.

    Returns list of (lowercased) entity strings, or None if NER unavailable.
    Labels: CHEMICAL → drugs, DISEASE → conditions/pathologies.
    Caches the spacy Doc in _NER_DOC_CACHE for reuse by drug-disease classification.
    """
    nlp = _get_ner_nlp()
    if nlp is None:
        return None
    # Cache the Doc object so _classify_drug_disease_context doesn't re-run NER
    if query in _NER_DOC_CACHE:
        doc = _NER_DOC_CACHE[query]
    else:
        doc = nlp(query)
        _NER_DOC_CACHE[query] = doc
    entities = []
    for ent in doc.ents:
        text = ent.text.strip().lower()
        if len(text) > 2:
            entities.append(text)
    return entities if entities else None


# ── Entity extraction & heading-aware filtering ──────────────────────────────

# Patterns that indicate a medical entity name (noun phrases after "of/for/in")
# Limited to medical nouns — excludes generic continuation words like "how", "do",
# "current", "treatments" that caused the old regex to capture entire queries.
_ENTITY_TRAIL_RE = re.compile(
    r"(?:of|for|in|after|following|during|with)\s+"
    r"((?:[A-Z][a-z]+|[A-Z]{2,}|type\s+[IVX]+|grade\s+[IVX]+)"
    r"(?:\s+(?:and|vs\.?|versus|or)\s+(?:[A-Z][a-z]+|[A-Z]{2,}|type\s+[IVX]+|grade\s+[IVX]+))?"
    r"(?:\s+(?:malformation[s]?|glioma[s]?|hemorrhage|haemorrhage"
    r"|aneurysm[s]?|tumor[s]?|tumour[s]?|syndrome|disease|disorder"
    r"|resection|surgery|decompression"
    r"|receptor\s+antagonist[s]?|receptor[s]?))*)",
    re.IGNORECASE,
)

# Common medical entity patterns that appear as the primary subject
_ENTITY_SUBJECT_RE = re.compile(
    r"(?:^|\s)((?:(?:Chiari|Arnold-Chiari|Dandy-Walker|moyamoya|glioblastoma|meningioma|"
    r"astrocytoma|oligodendroglioma|ependymoma|craniopharyngioma|schwannoma|"
    r"vestibular\s+schwannoma|acoustic\s+neuroma|pituitary\s+adenoma|"
    r"arteriovenous\s+malformation|AVM|cavernous\s+malformation|"
    r"subarachnoid\s+hemorrhage|SAH|aneurysm|vasospasm|"
    r"hydrocephalus|syringomyelia|diastematomyelia|"
    r"insular\s+glioma|thalamic\s+glioma|brainstem\s+glioma|"
    r"split\s+cord\s+malformation|focal\s+cortical\s+dysplasia|"
    r"trigeminal\s+neuralgia|hemifacial\s+spasm|"
    r"epidural\s+hematoma|subdural\s+hematoma|"
    r"cerebral\s+vasospasm|delayed\s+cerebral\s+ischemia|"
    r"nimodipine|endothelin|"
    r"Type\s+[IVX]+\s+\w+)"
    r"(?:\s+(?:malformation[s]?|type\s+[IVX]+|grade\s+[IVX]+))?))",
    re.IGNORECASE,
)


# Known drug names for drug-disease context filtering
_DRUG_NAMES = {
    "nimodipine", "endothelin", "mannitol", "dexamethasone",
    "levetiracetam", "phenytoin", "heparin", "aspirin",
    "clopidogrel", "temozolomide", "bevacizumab", "clazosentan",
    "nifedipine", "nicardipine", "dantrolene", "labetalol",
    "propofol", "midazolam", "fentanyl", "thiopental",
    "carbamazepine", "valproate", "topiramate", "gabapentin",
    "methylprednisolone", "hydrocortisone", "vancomycin",
    "ceftriaxone", "methotrexate", "carmustine", "lomustine",
}


# Well-known medical abbreviations for entities that NER extracts as full phrases.
# Maps lowercase full-form → abbreviation. Used to expand entity matching so
# passages containing "NPH" match the entity "normal pressure hydrocephalus".
_MEDICAL_ABBREVIATIONS = {
    "normal pressure hydrocephalus": "nph",
    "subarachnoid hemorrhage": "sah",
    "arteriovenous malformation": "avm",
    "traumatic brain injury": "tbi",
    "intracranial pressure": "icp",
    "cerebrospinal fluid": "csf",
    "cerebral perfusion pressure": "cpp",
    "deep brain stimulation": "dbs",
    "ventriculoperitoneal shunt": "vps",
    "Glasgow coma scale": "gcs",
    "Glasgow outcome scale": "gos",
    "central nervous system": "cns",
    "magnetic resonance imaging": "mri",
    "computed tomography": "ct",
    "middle cerebral artery": "mca",
    "anterior cerebral artery": "aca",
    "posterior cerebral artery": "pca",
    "anterior communicating artery": "acomm",
    "posterior communicating artery": "pcomm",
    "internal carotid artery": "ica",
    "external ventricular drain": "evd",
    "idiopathic intracranial hypertension": "iih",
    "focal cortical dysplasia": "fcd",
    "diffuse axonal injury": "dai",
    "spinal cord injury": "sci",
    "white matter": "wm",
    "blood brain barrier": "bbb",
    "cerebral blood flow": "cbf",
    "mean arterial pressure": "map",
    "vasospasm": "vsm",
    "glioblastoma multiforme": "gbm",
    "world health organization": "who",
}


def _get_entity_abbreviation(entity: str) -> Optional[str]:
    """Get the medical abbreviation for a multi-word entity, if known.

    First checks the curated map, then falls back to generating the
    first-letter acronym for entities with 3+ words (e.g., "normal pressure
    hydrocephalus" → "nph"). Only returns acronyms of 2+ characters.
    """
    lower = entity.lower()
    # Check curated map first
    if lower in _MEDICAL_ABBREVIATIONS:
        return _MEDICAL_ABBREVIATIONS[lower]
    # Generate first-letter acronym for 3+ word entities
    words = [w for w in lower.split() if len(w) > 2 and w not in STOPWORDS]
    if len(words) >= 3:
        acronym = "".join(w[0] for w in words)
        if len(acronym) >= 2:
            return acronym
    return None


def _extract_primary_entities(query: str) -> List[str]:
    """Extract primary medical entities from query for disambiguation.

    Returns a list of entity strings (lowercased) that represent the core
    medical concepts the query is about. Used to filter false positives
    where 'Type I/II' or other ambiguous terms match wrong pathologies.

    Strategy: SciSpacy NER (CHEMICAL + DISEASE labels) → regex fallback.
    NER produces far cleaner entities (e.g., "Chiari I malformation" as one
    unit instead of regex fragments). Regex fallback keeps us functional
    if scispacy is not installed. Results cached per query string.
    """
    if query in _ENTITY_CACHE:
        return _ENTITY_CACHE[query]

    # ── Primary: SciSpacy NER ──
    ner_entities = _extract_entities_via_ner(query)
    if ner_entities is not None:
        # NER models sometimes extract bare nouns (e.g., "hydrocephalus") when
        # the query says "normal pressure hydrocephalus". Augment short NER
        # entities by scanning for qualifying modifiers in the original query.
        # Functional/framing words that should never be treated as medical modifiers.
        # These appear in query phrasing ("role of X", "management of Y") but don't
        # add specificity to the entity.
        _QUERY_FRAMING_WORDS = {
            "role", "management", "treatment", "approach", "use", "effect",
            "effects", "impact", "outcomes", "outcome", "results", "response",
            "mechanism", "mechanisms", "pathophysiology", "indications",
            "considerations", "techniques", "technique", "options", "option",
            "diagnosis", "evaluation", "assessment", "prognosis", "prevention",
            "risk", "risks", "factors", "current", "recent", "novel", "new",
            "newly", "diagnosed", "advanced", "initial", "primary", "secondary",
            "early", "late", "acute", "chronic", "first", "predict", "compare",
            "versus", "patients", "cases", "setting", "context",
        }

        augmented = []
        query_lower = query.lower()
        for ent in ner_entities:
            # Try to expand single-word entities with preceding modifiers
            if " " not in ent:
                # Look for multi-word phrase containing this entity in the query
                # Pattern: 1-3 preceding words + entity word
                pattern = re.compile(
                    r'((?:\w+\s+){1,3})' + re.escape(ent),
                    re.IGNORECASE,
                )
                m = pattern.search(query_lower)
                if m:
                    prefix = m.group(1).strip()
                    # Keep only medical modifiers — anatomical, pathological,
                    # or clinical adjectives that add entity specificity
                    prefix_words = [
                        w for w in prefix.split()
                        if len(w) > 2 and w not in STOPWORDS
                        and w not in _QUERY_FRAMING_WORDS
                    ]
                    if prefix_words:
                        expanded = " ".join(prefix_words) + " " + ent
                        augmented.append(expanded)
                        continue
            augmented.append(ent)

        # Deduplicate: prefer longer matches, remove substrings
        seen = set()
        unique = []
        for e in sorted(augmented, key=len, reverse=True):
            if e not in seen and not any(e in s for s in seen):
                unique.append(e)
                seen.add(e)
        _ENTITY_CACHE[query] = unique
        return unique

    # ── Fallback: regex-based extraction ──
    entities = []

    # Strategy 1: Named medical entities via curated pattern
    for m in _ENTITY_SUBJECT_RE.finditer(query):
        ent = m.group(1).strip().lower()
        if len(ent) > 3 and ent not in STOPWORDS:
            entities.append(ent)

    # Strategy 2: Trailing noun phrases after "of/for/in/after"
    for m in _ENTITY_TRAIL_RE.finditer(query):
        ent = m.group(1).strip().lower()
        if len(ent) > 3 and ent not in STOPWORDS:
            entities.append(ent)

    # Deduplicate while preserving order, prefer longer matches
    _KNOWN_SINGLE_ENTITIES = _DRUG_NAMES | {
        "vasospasm", "hydrocephalus", "syringomyelia", "meningioma",
        "glioblastoma", "astrocytoma", "ependymoma", "schwannoma",
        "craniopharyngioma", "diastematomyelia", "moyamoya",
    }
    _GENERIC_ENTITY_WORDS = {
        "type", "types", "grade", "grades", "class", "stage", "level",
        "malformation", "malformations", "syndrome", "disease",
    }
    seen = set()
    unique = []
    for e in sorted(entities, key=len, reverse=True):
        if e not in seen and not any(e in s for s in seen):
            if " " not in e and e not in _KNOWN_SINGLE_ENTITIES:
                continue
            e_words = [w for w in e.split()
                       if len(w) > 3 and w.lower() not in STOPWORDS
                       and w.lower() not in _GENERIC_ENTITY_WORDS]
            if not e_words and " " in e:
                continue
            unique.append(e)
            seen.add(e)

    _ENTITY_CACHE[query] = unique
    return unique


def _classify_drug_disease_context(entities: List[str], query: str = "") -> Optional[Dict[str, List[str]]]:
    """Detect drug+disease pairs among extracted entities.

    When a query mentions both a drug (e.g., "nimodipine") and a disease
    (e.g., "vasospasm", "SAH"), passages matching only the drug without
    the disease context are likely false positives (e.g., nimodipine for
    vestibular schwannoma surgery).

    Uses NER CHEMICAL/DISEASE labels when available, falls back to _DRUG_NAMES set.

    Returns None if no drug-disease pair detected, otherwise:
    {"drugs": [...], "diseases": [...]}
    """
    if not entities:
        return None

    drugs = []
    diseases = []

    # Try NER-based classification first (CHEMICAL vs DISEASE labels)
    # Reuse cached Doc from _extract_entities_via_ner if available
    doc = _NER_DOC_CACHE.get(query) if query else None
    if doc is None and query:
        nlp = _get_ner_nlp()
        if nlp is not None:
            doc = nlp(query)
            _NER_DOC_CACHE[query] = doc
    if doc is not None:
        ner_chemicals = {ent.text.strip().lower() for ent in doc.ents if ent.label_ == "CHEMICAL"}
        ner_diseases = {ent.text.strip().lower() for ent in doc.ents if ent.label_ == "DISEASE"}
        for ent in entities:
            if ent in ner_chemicals:
                drugs.append(ent)
            elif ent in ner_diseases:
                diseases.append(ent)
            else:
                # Fallback: check against hardcoded drug list
                if set(ent.split()) & _DRUG_NAMES:
                    drugs.append(ent)
                else:
                    diseases.append(ent)
    else:
        # Regex fallback: use hardcoded drug names
        for ent in entities:
            if set(ent.split()) & _DRUG_NAMES:
                drugs.append(ent)
            else:
                diseases.append(ent)

    if drugs and diseases:
        return {"drugs": drugs, "diseases": diseases}
    return None


def _entity_match_ratio(text: str, entities: List[str]) -> float:
    """Compute co-occurrence ratio: what fraction of the best-matching entity's
    distinctive words appear in the text.

    Returns a float in [0.0, 1.0]:
    - 1.0 = all distinctive words (or full phrase / abbreviation) found
    - 0.5 = half the distinctive words found
    - 0.0 = no entity words found at all

    This replaces the old binary _entity_present_in_text. The continuous ratio
    lets the penalty system apply proportional demotions — a passage matching
    1/3 entity words ("hydrocephalus" only for "normal pressure hydrocephalus")
    gets a harsher penalty than one matching 2/3 ("pressure" + "hydrocephalus").
    """
    if not entities:
        return 1.0  # No entities extracted → no filtering

    # Common classifier words that appear across many pathologies
    _GENERIC = {
        "type", "types", "grade", "grades", "class", "stage", "level",
        "malformation", "malformations", "syndrome", "disease",
        "disorder", "lesion", "lesions", "tumor", "tumors",
        "management", "treatment", "surgical", "presentation",
        "clinical", "pathophysiology",
    }

    text_lower = text.lower()
    best_ratio = 0.0

    for entity in entities:
        # Fast path: full entity phrase present → 1.0
        if entity.lower() in text_lower:
            return 1.0

        # Fast path: known abbreviation present → 1.0
        abbrev = _get_entity_abbreviation(entity)
        if abbrev and re.search(r'\b' + re.escape(abbrev) + r'\b', text_lower):
            return 1.0

        # Decompose into distinctive vs generic words
        seen = set()
        distinctive_words = []
        generic_words = []
        for w in entity.split():
            wl = w.lower()
            if len(wl) <= 3 or wl in STOPWORDS or wl in seen:
                continue
            seen.add(wl)
            if wl in _GENERIC:
                generic_words.append(wl)
            else:
                distinctive_words.append(wl)

        # Compute co-occurrence ratio on distinctive words
        if distinctive_words:
            matches = sum(1 for w in distinctive_words if w in text_lower)
            ratio = matches / len(distinctive_words)
            best_ratio = max(best_ratio, ratio)
        elif generic_words:
            # No distinctive words — use generic words (e.g., "type I malformation")
            matches = sum(1 for w in generic_words if w in text_lower)
            ratio = matches / len(generic_words)
            best_ratio = max(best_ratio, ratio)
        else:
            # Very short entity — exact substring check
            if entity.lower() in text_lower:
                return 1.0

    return round(best_ratio, 3)


def _entity_present_in_text(text: str, entities: List[str]) -> bool:
    """Binary wrapper for backward compatibility (drug-disease check).

    Returns True if co-occurrence ratio ≥ 0.5 (at least half the entity's
    distinctive words are present).
    """
    return _entity_match_ratio(text, entities) >= 0.5


def _heading_matches_entity(hit: dict, entities: List[str]) -> bool:
    """Check if the passage heading/chapter relates to the query entities.

    Returns True if heading/chapter contains entity keywords, or if no
    entities were extracted (pass-through). This catches cross-entity
    contamination where a chunk from a different chapter section gets
    retrieved due to superficial keyword overlap.
    """
    if not entities:
        return True
    meta = hit.get("metadata", {})
    heading = (meta.get("heading") or "").lower()
    chapter = (meta.get("chapter_title") or "").lower()
    section_path = (meta.get("section_path") or "").lower()
    combined = f"{heading} {chapter} {section_path}"

    for entity in entities:
        entity_words = [w for w in entity.split() if len(w) > 3 and w not in STOPWORDS]
        if not entity_words:
            if entity in combined:
                return True
            continue
        matches = sum(1 for w in entity_words if w in combined)
        if matches >= max(1, len(entity_words) * 0.4):
            return True
    return False


def _compute_heading_entity_similarity(hits: list, entity_phrase: str) -> list:
    """Option 1: Semantic entity disambiguation via embedding distance.

    Encodes the entity phrase and each passage's heading/chapter with BGE-M3,
    then computes cosine similarity. Adds 'heading_entity_sim' to each hit.
    Headings semantically close to the entity get high scores; unrelated
    headings (e.g., "Focal Cortical Dysplasias" vs "Chiari malformations")
    score low despite sharing keywords like "type I/II."

    Batched inference: one encode call for all headings + entity (~50ms).
    """
    if not hits or not entity_phrase:
        return hits

    # Collect unique heading strings to encode
    heading_strings = []
    hit_heading_map = []  # (hit_index, heading_str)
    for i, hit in enumerate(hits):
        meta = hit.get("metadata", {})
        heading = meta.get("heading") or ""
        chapter = meta.get("chapter_title") or ""
        combined = f"{heading} — {chapter}".strip(" —")
        if not combined:
            combined = "unknown section"
        heading_strings.append(combined)
        hit_heading_map.append((i, combined))

    # Encode entity + all headings in one batch
    try:
        model = _get_embedding_model()
        all_texts = [entity_phrase] + heading_strings
        out = model.encode(
            all_texts, batch_size=len(all_texts), max_length=128,
            return_dense=True, return_sparse=False,
        )
        vecs = out["dense_vecs"]  # shape: (1+N, 1024)
        entity_vec = vecs[0]
        heading_vecs = vecs[1:]

        # Cosine similarity: entity_vec vs each heading_vec
        entity_norm = np.linalg.norm(entity_vec)
        if entity_norm == 0:
            return hits

        for idx, (hit_i, _) in enumerate(hit_heading_map):
            h_norm = np.linalg.norm(heading_vecs[idx])
            if h_norm == 0:
                sim = 0.0
            else:
                sim = float(np.dot(entity_vec, heading_vecs[idx]) / (entity_norm * h_norm))
            hits[hit_i] = dict(hits[hit_i])
            hits[hit_i]["heading_entity_sim"] = round(sim, 4)

    except Exception:
        # Graceful fallback: skip semantic heading check
        pass

    return hits


def _apply_entity_aware_filtering(
    reranked: list,
    query: str,
    entities: Optional[List[str]] = None,
) -> list:
    """Apply two-layer entity-aware filtering post-rerank.

    Layer 1: Keyword-based heading/text match (fast, catches obvious mismatches)
    Layer 2: Embedding distance — heading vs entity phrase (semantic, ~50ms)

    Note: Cross-encoder disambiguation was tested and removed — the MiniLM CE
    is a relevance model that scores false positives (FCD/SCM) at 0.82 due to
    shared classifiers like "type I/II". Heading embedding is the reliable signal.

    Penalty tiers by heading_entity_sim:
    - < 0.40: Very distant heading → 0.0 (drop) or 0.15 multiplier
    - < 0.55: Distant heading → 0.1–0.25 multiplier
    - < 0.70: Moderate → 0.3–0.65 multiplier
    - ≥ 0.70: Close heading → pass through (0.8–1.0)
    """
    if entities is None:
        entities = _extract_primary_entities(query)
    if not entities:
        return reranked

    # Build the entity phrase for semantic comparison
    entity_phrase = max(entities, key=len)

    # Detect drug-disease pairs for context-aware filtering
    drug_disease = _classify_drug_disease_context(entities, query)

    # Layer 1: Keyword-based heading/text match + co-occurrence ratio
    for i, hit in enumerate(reranked):
        reranked[i] = dict(hit)
        reranked[i]["_kw_heading_match"] = _heading_matches_entity(hit, entities)
        entity_ratio = _entity_match_ratio(hit.get("text", ""), entities)
        reranked[i]["_entity_ratio"] = entity_ratio
        reranked[i]["_kw_text_match"] = entity_ratio >= 0.5
        # Drug-disease context: passages mentioning the drug must also mention the disease
        if drug_disease and reranked[i]["_kw_text_match"]:
            text_lower = hit.get("text", "").lower()
            has_drug = any(d in text_lower for d in drug_disease["drugs"])
            has_disease = _entity_present_in_text(hit.get("text", ""), drug_disease["diseases"])
            if has_drug and not has_disease:
                reranked[i]["_kw_text_match"] = False
                reranked[i]["_drug_no_disease"] = True

    # Layer 2: Semantic heading-entity similarity via BGE-M3 embedding
    reranked = _compute_heading_entity_similarity(reranked, entity_phrase)

    # Combine signals and apply penalties
    # The entity co-occurrence ratio modulates penalties: low ratio (e.g., 0.33 = 1/3
    # entity words matched) gets harsher treatment than high ratio (0.67 = 2/3 words).
    # This prevents "hydrocephalus"-only passages from passing the filter for
    # "normal pressure hydrocephalus" queries, while still allowing partial matches
    # with proportional penalties.
    adjusted = []
    for hit in reranked:
        enriched = dict(hit)
        heading_sim = hit.get("heading_entity_sim", 1.0)
        kw_heading = hit.get("_kw_heading_match", True)
        kw_text = hit.get("_kw_text_match", True)
        entity_ratio = hit.get("_entity_ratio", 1.0)

        penalty = None
        multiplier = 1.0
        is_drug_no_disease = hit.get("_drug_no_disease", False)

        # Drug-disease override: passage mentions drug but not the disease context
        # Heavy penalty regardless of heading similarity (e.g., nimodipine for VS surgery)
        if is_drug_no_disease:
            penalty = "drug_without_disease"
            multiplier = 0.1
        elif heading_sim < 0.40:
            # Very distant heading — high confidence mismatch
            if not kw_text:
                penalty = "heading_very_distant+text_miss"
                multiplier = 0.0
            else:
                penalty = "heading_very_distant"
                multiplier = 0.15 * entity_ratio
        elif heading_sim < 0.55:
            # Distant heading — strong penalty
            if not kw_text:
                penalty = "heading_distant+text_miss"
                multiplier = 0.1
            else:
                penalty = "heading_distant"
                multiplier = 0.25 * entity_ratio
        elif heading_sim < 0.70:
            # Moderately related heading
            if not kw_heading and not kw_text:
                penalty = "moderate_heading+kw_miss"
                multiplier = 0.3
            elif not kw_heading:
                penalty = "moderate_heading_miss"
                multiplier = 0.65 * entity_ratio
            elif entity_ratio < 0.5:
                # Heading matches but text has low entity word overlap
                penalty = "low_entity_ratio"
                multiplier = 0.4 * (0.5 + entity_ratio)
        else:
            # Close heading — normally pass through, but penalize low entity ratio
            if not kw_text:
                penalty = "text_miss_only"
                multiplier = 0.8
            elif entity_ratio < 0.5:
                # High heading similarity but low word overlap — partial penalty
                penalty = "low_entity_ratio_close_heading"
                multiplier = 0.5 + (entity_ratio * 0.5)

        if penalty:
            enriched["entity_penalty"] = penalty
            enriched["entity_multiplier"] = round(multiplier, 2)
            enriched["rank_score"] = round(
                hit.get("rank_score", 0.0) * multiplier, 4
            )

        adjusted.append(enriched)

    # Remove hits marked for dropping
    filtered = [h for h in adjusted if h.get("entity_multiplier", 1.0) > 0.0]

    # Re-sort by adjusted rank_score
    filtered.sort(
        key=lambda x: (x.get("rank_score", 0.0), x.get("similarity", 0.0)),
        reverse=True,
    )

    # Clean up internal keys
    for hit in filtered:
        hit.pop("_kw_heading_match", None)
        hit.pop("_kw_text_match", None)
        hit.pop("_entity_ratio", None)
        hit.pop("_drug_no_disease", None)

    return filtered


def _format_citation(row: dict) -> str:
    """Build a human-readable citation from LanceDB row metadata."""
    book = row.get("source_book", "Unknown")
    chapter = row.get("chapter_title", "")
    heading = row.get("heading", "")
    page = row.get("page_start")
    parts = [book]
    if chapter:
        parts.append(f"Ch: {chapter}")
    if heading and heading != chapter:
        parts.append(f"§ {heading}")
    if page:
        parts.append(f"p.{page}")
    return " — ".join(parts)


# ── Core retrieval ───────────────────────────────────────────────────────────

def _encode_query(query: str) -> List[float]:
    """Encode query with BGE-M3 → dense_vec. Sparse channel uses LanceDB FTS."""
    model = _get_embedding_model()
    out = model.encode(
        [query], batch_size=1, max_length=512,
        return_dense=True, return_sparse=False,
    )
    return out["dense_vecs"][0].astype(np.float32).tolist()


def _dense_search(table, query_vec: List[float], n_results: int = DEFAULT_N_RESULTS):
    """Vector similarity search on LanceDB dense_vec column."""
    t0 = time.perf_counter()
    results = (
        table.search(query_vec, vector_column_name="dense_vec")
        .metric("cosine")
        .limit(n_results)
        .to_list()
    )
    ms = round((time.perf_counter() - t0) * 1000, 2)

    hits = []
    for row in results:
        dist = row.get("_distance", 1.0)
        similarity = 1.0 - (dist / 2.0)
        hits.append(_row_to_hit(row, similarity))
    return hits, ms


def _sparse_search_fts(table, query_text: str, n_results: int = DEFAULT_N_RESULTS):
    """Full-text search on child_text column as the sparse retrieval channel."""
    t0 = time.perf_counter()
    try:
        results = table.search(query_text, query_type="fts").limit(n_results).to_list()
    except Exception:
        return [], round((time.perf_counter() - t0) * 1000, 2)

    ms = round((time.perf_counter() - t0) * 1000, 2)
    hits = []
    for row in results:
        fts_score = float(row.get("_score", 0.0))
        # Normalize BM25 scores to [0,1] using sigmoid-like mapping
        # fts_score=2 → 0.67, fts_score=5 → 0.83, fts_score=10 → 0.91
        similarity = fts_score / (fts_score + 1.0) if fts_score > 0 else 0.0
        hits.append(_row_to_hit(row, similarity))
    return hits, ms


def _row_to_hit(row: dict, similarity: float) -> dict:
    """Convert a LanceDB row to a standardized hit dict."""
    return {
        "text": row.get("child_text", ""),
        "parent_text": row.get("parent_text", ""),
        "similarity": round(similarity, 4),
        "metadata": {
            "source_book": row.get("source_book", ""),
            "source_path": row.get("source_book", ""),
            "chapter_title": row.get("chapter_title", ""),
            "heading": row.get("heading", ""),
            "section_path": row.get("section_path", ""),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "chunk_index": row.get("child_index_in_parent", 0),
            "has_image": row.get("has_image", False),
            "has_table": row.get("has_table", False),
            "has_caption": row.get("has_caption", False),
            "item_types": row.get("item_types", ""),
            "subspecialty": row.get("subspecialty", ""),
            "noise_type": row.get("noise_type", "content"),
        },
        "citation": _format_citation(row),
        "source_key": row.get("source_book", "unknown"),
        "child_id": row.get("child_id", ""),
        "parent_id": row.get("parent_id", ""),
        "table_markdown": row.get("table_markdown", ""),
        "caption_text": row.get("caption_text", ""),
    }


# ── Fusion & Reranking ───────────────────────────────────────────────────────

def _apply_rrf(vector_hits: list, fts_hits: list, k: int = 60) -> list:
    """Reciprocal Rank Fusion."""
    scores = defaultdict(float)
    hit_map = {}

    for rank, hit in enumerate(vector_hits, start=1):
        key = _content_hash(hit["text"])
        scores[key] += 1.0 / (k + rank)
        hit_map[key] = hit

    for rank, hit in enumerate(fts_hits, start=1):
        key = _content_hash(hit["text"])
        scores[key] += 1.0 / (k + rank)
        if key not in hit_map:
            hit_map[key] = hit

    sorted_keys = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    fused = []
    for key in sorted_keys:
        hit = dict(hit_map[key])
        hit["rrf_score"] = round(scores[key], 6)
        fused.append(hit)
    return fused


def _rerank_hits(query: str, hits: list, reranker_key: str = DEFAULT_RERANKER):
    """Cross-encoder reranking. Returns (reranked_hits, latency_ms)."""
    if not hits:
        return hits, 0.0

    ce, model_key = _get_reranker(reranker_key)
    if ce is None:
        return _rerank_hits_lexical(query, hits), 0.0

    t0 = time.perf_counter()
    try:
        doc_texts = [hit.get("text", "")[:2200] for hit in hits]
        pairs = [[query, doc] for doc in doc_texts]
        raw_scores = ce.predict(pairs, batch_size=32)
        scores = [float(s) for s in raw_scores]
    except Exception:
        return _rerank_hits_lexical(query, hits), 0.0

    ms = round((time.perf_counter() - t0) * 1000, 2)

    max_score = max(scores) if scores else 0
    min_score = min(scores) if scores else 0
    scores_are_sigmoid = (0 <= min_score and max_score <= 1.0)

    reranked = []
    for i, hit in enumerate(hits):
        enriched = dict(hit)
        sim = float(hit.get("similarity") or 0.0)
        ce_score = scores[i]
        sigmoid_ce = ce_score if scores_are_sigmoid else 1.0 / (1.0 + math.exp(-ce_score))
        rank_score = (0.2 * sim) + (0.8 * sigmoid_ce)

        enriched["ce_score"] = round(ce_score, 4)
        enriched["sigmoid_ce"] = round(sigmoid_ce, 4)
        enriched["rank_score"] = round(rank_score, 4)

        if _is_reference_chunk(hit.get("text", "")):
            enriched["rank_score"] = round(rank_score * 0.3, 4)
            enriched["is_reference_chunk"] = True

        reranked.append(enriched)

    reranked.sort(key=lambda x: (x.get("rank_score", 0.0), x.get("similarity", 0.0)), reverse=True)
    reranked = [h for h in reranked if h.get("sigmoid_ce", 1.0) >= RERANKER_SCORE_FLOOR]
    return reranked, ms


def _rerank_hits_lexical(query: str, hits: list) -> list:
    """Fallback lexical-overlap reranking."""
    q_terms = _extract_keywords(query)
    reranked = []
    for hit in hits:
        sim = float(hit.get("similarity") or 0.0)
        h_terms = _extract_keywords(hit.get("text", ""))
        overlap = len(q_terms & h_terms) / max(1, len(q_terms)) if q_terms else 0.0
        enriched = dict(hit)
        enriched["rank_score"] = round((0.7 * sim) + (0.3 * overlap), 4)
        reranked.append(enriched)
    reranked.sort(key=lambda x: x.get("rank_score", 0.0), reverse=True)
    return reranked


# ── Maximal Marginal Relevance (MMR) ─────────────────────────────────────────
# Carbonell & Goldstein 1998 — selects passages that maximize relevance to
# the query while minimizing redundancy with already-selected passages.
# This trades a small amount of top-relevance for substantially better
# diversity, which is critical when an LLM agent is the consumer: 3 passages
# saying the same thing wastes context budget, while 3 diverse perspectives
# give the agent richer synthesis material.

def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Fast word-level Jaccard similarity for MMR redundancy measurement.

    Uses significant words (>3 chars, not stopwords) as the token set.
    O(n) where n = number of tokens. No model calls needed.
    """
    words_a = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text_a) if w.lower() not in STOPWORDS}
    words_b = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", text_b) if w.lower() not in STOPWORDS}
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union > 0 else 0.0


def _mmr_select(
    candidates: list,
    max_select: int,
    lambda_param: float = 0.7,
    score_key: str = "rank_score",
) -> list:
    """Select passages via Maximal Marginal Relevance.

    MMR(d) = λ * Relevance(d) - (1 - λ) * max_sim(d, selected)

    Args:
        candidates: list of hit dicts, pre-sorted by score
        max_select: number of passages to select
        lambda_param: trade-off between relevance (1.0) and diversity (0.0).
            0.7 = strongly prefer relevance, gently penalize redundancy.
            Lower values → more diverse but potentially less relevant.
        score_key: which score field to use for relevance

    Returns:
        Selected passages in order of selection (first = highest MMR).
    """
    if not candidates or max_select <= 0:
        return []
    if len(candidates) <= max_select:
        return list(candidates)

    # Normalize relevance scores to [0, 1] for fair comparison with Jaccard
    scores = [h.get(score_key, 0.0) for h in candidates]
    max_score = max(scores) if scores else 1.0
    if max_score == 0:
        max_score = 1.0

    selected = []
    remaining = list(range(len(candidates)))

    # First pick: always the highest-scoring passage
    best_idx = max(remaining, key=lambda i: scores[i])
    selected.append(best_idx)
    remaining.remove(best_idx)

    # Iterative selection via MMR
    while len(selected) < max_select and remaining:
        best_mmr = -float("inf")
        best_r = -1

        for r_idx in remaining:
            # Relevance term: normalized score
            relevance = scores[r_idx] / max_score

            # Redundancy term: max Jaccard similarity with any selected passage
            r_text = candidates[r_idx].get("text", "")
            max_redundancy = 0.0
            for s_idx in selected:
                s_text = candidates[s_idx].get("text", "")
                sim = _jaccard_similarity(r_text, s_text)
                if sim > max_redundancy:
                    max_redundancy = sim

            mmr = lambda_param * relevance - (1 - lambda_param) * max_redundancy

            if mmr > best_mmr:
                best_mmr = mmr
                best_r = r_idx

        if best_r >= 0:
            selected.append(best_r)
            remaining.remove(best_r)
        else:
            break

    return [candidates[i] for i in selected]


# ── Parent-child context expansion ───────────────────────────────────────────

def _expand_with_parent_text(hits: list, query: str = "") -> list:
    """Use stored parent_text instead of re-fetching adjacent chunks."""
    parent_groups: Dict[str, list] = defaultdict(list)
    orphans = []

    for hit in hits:
        pid = hit.get("parent_id", "")
        if pid:
            parent_groups[pid].append(hit)
        else:
            orphans.append(hit)

    expanded = []
    for parent_id, children in parent_groups.items():
        children.sort(key=lambda h: h.get("metadata", {}).get("chunk_index", 0))
        anchor = max(children, key=lambda h: h.get("rank_score", h.get("similarity", 0.0)))
        parent_text = anchor.get("parent_text", "") or anchor.get("text", "")

        enriched = dict(anchor)
        enriched["text_original"] = anchor["text"]
        enriched["text"] = parent_text
        enriched["passage_tokens"] = _approx_tokens(parent_text)
        enriched["context_expanded"] = True
        enriched["passage_chunks"] = len(children)
        enriched["cluster_hits"] = len(children)
        enriched["cluster_score"] = round(
            max(h.get("rank_score", h.get("similarity", 0.0)) for h in children), 4
        )
        expanded.append(enriched)

    expanded.extend(orphans)
    expanded.sort(
        key=lambda x: x.get("cluster_score", x.get("rank_score", x.get("similarity", 0.0))),
        reverse=True,
    )

    # Enforce passage limits and source diversity
    selected = []
    source_set = set()
    for hit in expanded:
        if len(selected) >= CONTEXT_MAX_PASSAGES:
            break
        selected.append(hit)
        source_set.add(hit.get("source_key", ""))

    if len(source_set) < CONTEXT_MIN_SOURCES and len(expanded) > len(selected):
        unselected_new = [
            h for h in expanded
            if h not in selected and h.get("source_key", "") not in source_set
        ]
        if unselected_new:
            src_counts = defaultdict(int)
            for s in selected:
                src_counts[s.get("source_key", "")] += 1
            for i in range(len(selected) - 1, -1, -1):
                if src_counts[selected[i].get("source_key", "")] > 1:
                    evicted = selected.pop(i)
                    src_counts[evicted.get("source_key", "")] -= 1
                    selected.append(unselected_new[0])
                    source_set.add(unselected_new[0].get("source_key", ""))
                    break

    finalized = []
    selected_keys = set()
    for hit in selected:
        selected_keys.add(hit.get("child_id") or _content_hash(hit.get("text", "")))
        if not _is_low_value_retrieval_hit(hit):
            finalized.append(hit)

    if len(finalized) < CONTEXT_MAX_PASSAGES:
        for hit in expanded:
            key = hit.get("child_id") or _content_hash(hit.get("text", ""))
            if key in selected_keys:
                continue
            candidate = dict(hit)
            selected_keys.add(key)
            if _is_low_value_retrieval_hit(candidate):
                continue
            finalized.append(candidate)
            if len(finalized) >= CONTEXT_MAX_PASSAGES:
                break

    return finalized


# ── Adaptive Context Distillation ────────────────────────────────────────────

_QUESTION_PREFIXES = re.compile(
    r"^(?:what\s+(?:is|are|does|do|was|were)\s+(?:the\s+)?|"
    r"how\s+(?:does|do|is|are|can|should)\s+(?:the\s+)?|"
    r"why\s+(?:does|do|is|are)\s+(?:the\s+)?|"
    r"describe\s+(?:the\s+)?|"
    r"explain\s+(?:the\s+)?|"
    r"compare\s+(?:the\s+)?|"
    r"differentiate\s+(?:between\s+)?(?:the\s+)?|"
    r"contrast\s+(?:the\s+)?)",
    re.IGNORECASE,
)

_MAX_AXES = 4


def _decompose_axes(query: str) -> List[str]:
    """Parse query into semantic axes via heuristic splitting.

    Splits on ', and ', ' and ', commas, question marks. Strips common
    question prefixes and stopwords. Falls back to full query as single axis.
    Capped at 4 axes.

    Clinical vignettes (age + presentation + question) are handled specially:
    the narrative portion is kept as a single context axis, and actual
    questions at the end are split normally. This prevents fragmenting
    "55-year-old man with hand weakness and fasciculations" into meaningless
    sub-axes.

    Entity propagation: When splitting produces short axes that lose the
    medical entity context (e.g., "pathophysiology" from a query about
    "Chiari malformations"), the entity suffix from the longest axis is
    appended to shorter axes so the cross-encoder can score them properly.
    """
    # ── Detect clinical vignettes ──
    # Pattern: starts with age/demographic, contains clinical presentation,
    # ends with one or more questions. Split at the question boundary, not
    # within the narrative.
    _VIGNETTE_RE = re.compile(
        r'^(.*?\b(?:\d{1,2}[-\s]?(?:year|yr|y/?o|month|mo)[-\s]?old|'
        r'(?:infant|neonate|child|adolescent|man|woman|patient|boy|girl)\b).*?)'
        r'[.]\s*'
        r'((?:How|What|When|Where|Which|Should|Is|Are|Do|Does|Can|Would)\s.+)$',
        re.IGNORECASE | re.DOTALL,
    )
    stripped = query.strip()
    vignette_match = _VIGNETTE_RE.match(stripped)
    if vignette_match:
        narrative = vignette_match.group(1).strip().rstrip(".")
        questions = vignette_match.group(2).strip()
        # The narrative becomes one context axis (the clinical scenario)
        # The question portion gets decomposed normally
        cleaned = _QUESTION_PREFIXES.sub("", questions).strip("? ").strip()
        if not cleaned:
            cleaned = questions.strip("? ").strip()
        # Split only the question part on " and " and "?"
        q_parts = re.split(r"\s+and\s+(?=what|how|when|where|which|should|is|are)\s*", cleaned, flags=re.IGNORECASE)
        question_axes = []
        for qp in q_parts:
            for sub in re.split(r"\?\s*", qp):
                sub = sub.strip("? .,").strip()
                sub = _QUESTION_PREFIXES.sub("", sub).strip("? ").strip()
                if sub:
                    tokens = set(re.findall(r"[a-zA-Z]{3,}", sub.lower()))
                    if tokens and not tokens.issubset(STOPWORDS):
                        question_axes.append(sub)
        # Combine: narrative context + question axes
        axes = [narrative] + question_axes if question_axes else [stripped]
        axes = axes[:_MAX_AXES]
        if len(axes) > 1:
            axes = _propagate_entity_to_axes(axes, query)
        return axes

    # ── Standard decomposition for non-vignette queries ──
    # Strip leading question prefix
    cleaned = _QUESTION_PREFIXES.sub("", stripped)
    cleaned = cleaned.strip("? ").strip()

    if not cleaned:
        cleaned = stripped.strip("? ").strip()

    # Split on explicit delimiters: ", and " first, then " and ", then commas,
    # then question marks (multi-question queries)
    # Order matters: try compound delimiter first
    parts = [cleaned]
    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r",\s*and\s+", p))
    parts = new_parts

    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r"\s+and\s+", p))
    parts = new_parts

    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r",\s*", p))
    parts = new_parts

    new_parts = []
    for p in parts:
        new_parts.extend(re.split(r"\?\s*", p))
    parts = new_parts

    # Clean each axis: strip stopwords from edges, drop empty
    axes = []
    for part in parts:
        part = part.strip("? .,").strip()
        # Re-apply prefix stripping on each part
        part = _QUESTION_PREFIXES.sub("", part).strip("? ").strip()
        if not part:
            continue
        # Drop axes that are purely stopwords
        tokens = set(re.findall(r"[a-zA-Z]{3,}", part.lower()))
        if tokens and not tokens.issubset(STOPWORDS):
            axes.append(part)

    if not axes:
        return [query.strip()]

    axes = axes[:_MAX_AXES]

    # ── Entity propagation ──────────────────────────────────────────────
    # If we split into multiple axes, short axes may lose the entity context.
    # Find the entity phrase from the longest axis and append it to shorter ones.
    if len(axes) > 1:
        axes = _propagate_entity_to_axes(axes, query)

    return axes


def _propagate_entity_to_axes(axes: List[str], original_query: str) -> List[str]:
    """Append entity context to short axes that lost it during splitting.

    Heuristic: the longest axis usually retains the entity phrase (e.g.,
    "surgical management of Type I vs Type II Chiari malformations").
    Extract the trailing entity phrase via preposition anchors and append
    to axes that are missing entity keywords.
    """
    # Extract entities from the full query
    entities = _extract_primary_entities(original_query)
    if not entities:
        return axes

    # Find the entity phrase from the original query to use as suffix.
    # Look for "of/for/in/after <entity phrase>" pattern in the longest axis
    longest = max(axes, key=len)
    entity_suffix = ""

    # Try to extract the trailing entity phrase from the longest axis
    trail_match = re.search(
        r"\b((?:of|for|in|after|following|during|with)\s+.+)$",
        longest, re.IGNORECASE,
    )
    if trail_match:
        entity_suffix = trail_match.group(1).strip()

    # If no preposition-anchored suffix, try extracting from the original query
    if not entity_suffix:
        trail_match = re.search(
            r"\b((?:of|for|in|after|following|during|with)\s+.+?)(?:\s*\??\s*$)",
            original_query, re.IGNORECASE,
        )
        if trail_match:
            entity_suffix = trail_match.group(1).strip()

    if not entity_suffix:
        return axes

    # Determine which axes need the suffix — those missing entity keywords
    entity_kw = set()
    for ent in entities:
        entity_kw.update(w.lower() for w in ent.split() if len(w) > 3)

    propagated = []
    for ax in axes:
        ax_lower = ax.lower()
        ax_words = set(re.findall(r"[a-zA-Z]{4,}", ax_lower))
        has_entity = bool(ax_words & entity_kw)

        if has_entity or len(ax.split()) >= 6:
            # Already has entity context or is long enough
            propagated.append(ax)
        else:
            # Short axis missing entity — append the suffix
            propagated.append(f"{ax} {entity_suffix}")

    return propagated


def _score_passages_by_axis(
    query_axes: List[str],
    hits: list,
    reranker,
) -> list:
    """Score each hit against every axis using the loaded cross-encoder.

    Adds `axis_scores` dict and `primary_axis` to each hit.
    Returns the enriched hits list (same order).
    """
    if not hits or not query_axes:
        return hits

    # Build all (axis, passage) pairs at once for batched inference
    pairs = []
    for hit in hits:
        child_text = (hit.get("text_original") or hit.get("text", ""))[:2200]
        for axis in query_axes:
            pairs.append([axis, child_text])

    try:
        raw_scores = reranker.predict(pairs, batch_size=64)
        scores = [float(s) for s in raw_scores]
    except Exception:
        # Fallback: no axis scoring, assign equal scores
        for hit in hits:
            hit["axis_scores"] = {ax: 0.5 for ax in query_axes}
            hit["primary_axis"] = query_axes[0]
        return hits

    # Map raw CE scores to sigmoid probabilities
    n_axes = len(query_axes)
    for i, hit in enumerate(hits):
        axis_scores = {}
        for j, axis in enumerate(query_axes):
            raw = scores[i * n_axes + j]
            sig = raw if (0 <= raw <= 1.0) else 1.0 / (1.0 + math.exp(-raw))
            axis_scores[axis] = round(sig, 4)
        hit["axis_scores"] = axis_scores
        hit["primary_axis"] = max(axis_scores, key=axis_scores.get)

    return hits


def _budget_passages(
    hits_with_axes: list,
    axes: List[str],
    max_total: int = CONTEXT_MAX_PASSAGES,
    min_sources: int = CONTEXT_MIN_SOURCES,
) -> list:
    """Allocate passages across axes with source diversity enforcement.

    Budget: ceil(max_total / len(axes)) per axis. Within each axis bucket,
    prefer source diversity (different source_book), sorted by axis score.
    Surplus budget from underfilled axes redistributes to others.
    """
    if not hits_with_axes or not axes:
        return hits_with_axes[:max_total]

    per_axis_budget = math.ceil(max_total / len(axes))

    # Group by primary axis
    axis_candidates: Dict[str, list] = {ax: [] for ax in axes}
    for hit in hits_with_axes:
        primary = hit.get("primary_axis", axes[0])
        if primary in axis_candidates:
            axis_candidates[primary].append(hit)
        else:
            # Axis not in our list (shouldn't happen), assign to best match
            axis_candidates[axes[0]].append(hit)

    # Sort each bucket by axis score descending
    for ax in axes:
        axis_candidates[ax].sort(
            key=lambda h: h.get("axis_scores", {}).get(ax, 0.0),
            reverse=True,
        )

    # Select within each axis bucket using MMR (Maximal Marginal Relevance)
    # MMR maximizes relevance while minimizing redundancy with already-selected
    # passages — critical for giving the LLM agent diverse synthesis material.
    selected_per_axis: Dict[str, list] = {ax: [] for ax in axes}
    global_seen = set()  # content hashes to avoid cross-axis duplicates

    for ax in axes:
        bucket = axis_candidates[ax]
        # Deduplicate against cross-axis selections
        unique_bucket = []
        for h in bucket:
            ch = _content_hash(h.get("text", ""))
            if ch not in global_seen:
                unique_bucket.append(h)

        # Use axis-specific scores for MMR relevance
        for h in unique_bucket:
            h["_mmr_relevance"] = h.get("axis_scores", {}).get(ax, 0.0)

        # MMR selection: λ=0.7 balances relevance (70%) vs diversity (30%)
        mmr_picked = _mmr_select(
            unique_bucket, per_axis_budget,
            lambda_param=0.7, score_key="_mmr_relevance",
        )

        for h in mmr_picked:
            ch = _content_hash(h.get("text", ""))
            global_seen.add(ch)
            h.pop("_mmr_relevance", None)
        selected_per_axis[ax] = mmr_picked

    # Redistribute surplus from underfilled axes via MMR on remaining
    total_selected = sum(len(v) for v in selected_per_axis.values())
    if total_selected < max_total:
        remaining_budget = max_total - total_selected
        for ax in sorted(axes, key=lambda a: len(axis_candidates[a]), reverse=True):
            if remaining_budget <= 0:
                break
            current = selected_per_axis[ax]
            remaining_in_axis = [
                h for h in axis_candidates[ax]
                if _content_hash(h.get("text", "")) not in global_seen
            ]
            if remaining_in_axis:
                for h in remaining_in_axis:
                    h["_mmr_relevance"] = h.get("axis_scores", {}).get(ax, 0.0)
                # Run MMR on remaining, seeded with already-selected for redundancy check
                extra_picks = _mmr_select(
                    remaining_in_axis, remaining_budget,
                    lambda_param=0.7, score_key="_mmr_relevance",
                )
                for h in extra_picks:
                    ch = _content_hash(h.get("text", ""))
                    global_seen.add(ch)
                    h.pop("_mmr_relevance", None)
                    current.append(h)
                    remaining_budget -= 1
                    if remaining_budget <= 0:
                        break

    # Flatten, preserving axis grouping order
    result = []
    for ax in axes:
        result.extend(selected_per_axis[ax])

    # Final source diversity check
    source_set = {h.get("source_key", "") for h in result if h.get("source_key")}
    if len(source_set) < min_sources and len(hits_with_axes) > len(result):
        for hit in hits_with_axes:
            if len(result) >= max_total:
                break
            ch = _content_hash(hit.get("text", ""))
            if ch in global_seen:
                continue
            src = hit.get("source_key", "")
            if src not in source_set:
                result.append(hit)
                source_set.add(src)
                global_seen.add(ch)
                if len(source_set) >= min_sources:
                    break

    return result[:max_total]


def _select_text_level(hit: dict) -> str:
    """Choose child_text vs parent_text based on axis score and sibling context.

    - High-scoring primary (axis_score > 0.7) with parent_text → parent_text
    - Supplementary (0.4-0.7) → child_text only
    - Always include table_markdown and caption_text alongside
    Returns the selected text content.
    """
    axis_scores = hit.get("axis_scores", {})
    primary_axis = hit.get("primary_axis")
    primary_score = axis_scores.get(primary_axis, 0.0) if primary_axis else 0.0

    parent_text = hit.get("parent_text", "")
    child_text = hit.get("text_original") or hit.get("text", "")

    # High-scoring primary with meaningful parent context → use parent
    if primary_score > 0.7 and parent_text and len(parent_text) > len(child_text) * 1.3:
        text = parent_text
    else:
        text = child_text

    # Append table and caption data if present
    extras = []
    if hit.get("table_markdown"):
        extras.append(hit["table_markdown"])
    if hit.get("caption_text"):
        extras.append(hit["caption_text"])

    if extras:
        text = text + "\n\n" + "\n\n".join(extras)

    return text


# ── Quality-aware augmentation (AUG-CE) ──────────────────────────────────────

def _aug_query_terms(query: str) -> List[str]:
    """Auto-derive a term list for AUG-CE quality scoring.

    Uses _extract_keywords (already excludes generic English stopwords) plus
    AUG_TERM_STOP_EXTRA to drop generic clinical noise that would otherwise
    inflate term-coverage scores across nearly every passage.
    """
    kws = _extract_keywords(query)
    return sorted(k for k in kws if k not in AUG_TERM_STOP_EXTRA and len(k) >= 3)


def _aug_hit_text(hit: dict) -> str:
    """Best available text for a hit when scoring augmentation quality.

    Prefers distilled_text (set by _distill_by_axes / _select_text_level) so
    augmentation candidates that have already passed distill are scored on the
    same text the consumer will read. Falls back to text and text_original.
    """
    return hit.get("distilled_text") or hit.get("text") or hit.get("text_original") or ""


def _aug_hit_ce(hit: dict) -> float:
    """Cross-encoder relevance for a hit, falling back through rerank variants."""
    for key in ("sigmoid_ce", "rank_score", "rerank_score", "similarity"):
        v = hit.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _aug_term_coverage(text: str, terms: List[str]) -> float:
    if not terms:
        return 0.0
    low = (text or "").lower()
    return sum(1 for t in terms if t.lower() in low) / len(terms)


def _aug_quality(hit: dict, terms: List[str]) -> float:
    """Weighted blend of term coverage, keyword presence, and CE relevance.

    Mirrors the dry-run scoring (0.45 term + 0.25 keyword + 0.25 CE − junk)
    that AUG-CE was validated against. AUG-CE only USES this to RANK
    candidates and gate them, not to grade them — the production
    relevance signal (CE) is the floor enforced separately.
    """
    text = _aug_hit_text(hit)
    term_cov = _aug_term_coverage(text, terms)
    # kw_cov uses the same terms list so it's not double-counted; this matches
    # how the dry-run code used the auto-derived keyword set as both.
    kw_cov = term_cov
    ce = _aug_hit_ce(hit)
    junk = 0.2 if _is_low_value_retrieval_hit(hit) else 0.0
    return round((0.45 * term_cov) + (0.25 * kw_cov) + (0.25 * ce) - junk, 4)


def _quality_augment(query: str,
                     current_hits: List[dict],
                     candidate_pool: List[dict],
                     max_extra: int = AUG_MAX_EXTRA,
                     token_budget: int = AUG_TOKEN_BUDGET,
                     min_q_delta: float = AUG_MIN_Q_DELTA,
                     ce_abs_floor: float = AUG_CE_ABS_FLOOR,
                     ce_rel_frac: float = AUG_CE_REL_FRAC) -> tuple:
    """Append up to ``max_extra`` quality-aware passages to ``current_hits``.

    Non-destructive: current_hits are preserved in order. Candidates must
    clear three gates: (a) quality score exceeds the weakest current passage
    by at least ``min_q_delta``; (b) cross-encoder score at or above
    ``max(ce_abs_floor, ce_rel_frac * mean_current_CE)``; (c) appending does
    not push combined token estimate past ``token_budget``.

    No second cross-encoder pass — candidate CE is reused from the rerank step
    already attached to each hit. ``_select_text_level`` shapes each appended
    candidate so downstream formatters see the same distilled_text shape as
    the baseline hits.

    Returns ``(augmented_hits, meta)`` where meta is a dict with appended ids,
    gate reasons, and elapsed_ms — useful for the retrieve() metadata block.
    """
    t0 = time.perf_counter()
    meta = {
        "added_ids": [],
        "rejected": {"in_baseline": 0, "low_quality": 0, "low_ce": 0, "over_budget": 0, "junk": 0},
        "considered": 0,
        "terms_count": 0,
        "ce_floor": 0.0,
    }

    if not current_hits or not candidate_pool:
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return current_hits, meta

    terms = _aug_query_terms(query)
    meta["terms_count"] = len(terms)
    if not terms:
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return current_hits, meta

    base_qualities = [_aug_quality(h, terms) for h in current_hits]
    base_ces = [_aug_hit_ce(h) for h in current_hits]
    if not base_qualities or not base_ces:
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return current_hits, meta

    base_tokens = sum(_approx_tokens(_aug_hit_text(h)) for h in current_hits)
    if base_tokens >= token_budget:
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return current_hits, meta

    lowest_base_q = min(base_qualities)
    mean_base_ce = sum(base_ces) / len(base_ces)
    ce_floor = max(ce_abs_floor, mean_base_ce * ce_rel_frac)
    meta["ce_floor"] = round(ce_floor, 4)

    current_ids = {str(h.get("child_id")) for h in current_hits if h.get("child_id") is not None}
    current_hashes = {_content_hash(_aug_hit_text(h)) for h in current_hits}

    scored_candidates = []
    for cand in candidate_pool:
        meta["considered"] += 1
        cid = str(cand.get("child_id"))
        if cid in current_ids or _content_hash(_aug_hit_text(cand)) in current_hashes:
            meta["rejected"]["in_baseline"] += 1
            continue
        if _is_low_value_retrieval_hit(cand):
            meta["rejected"]["junk"] += 1
            continue
        cq = _aug_quality(cand, terms)
        if cq < lowest_base_q + min_q_delta:
            meta["rejected"]["low_quality"] += 1
            continue
        if _aug_hit_ce(cand) < ce_floor:
            meta["rejected"]["low_ce"] += 1
            continue
        scored_candidates.append((cand, cq))

    scored_candidates.sort(key=lambda kv: kv[1], reverse=True)

    augmented = list(current_hits)
    running_tokens = base_tokens
    for cand, cq in scored_candidates:
        if len(meta["added_ids"]) >= max_extra:
            break
        cand_copy = dict(cand)
        if not cand_copy.get("distilled_text"):
            cand_copy["distilled_text"] = _select_text_level(cand_copy)
        cand_copy["augmented_by_quality"] = True
        cand_copy["augment_quality"] = cq
        cand_tokens = _approx_tokens(_aug_hit_text(cand_copy))
        if running_tokens + cand_tokens > token_budget:
            meta["rejected"]["over_budget"] += 1
            continue
        augmented.append(cand_copy)
        running_tokens += cand_tokens
        meta["added_ids"].append(str(cand_copy.get("child_id")))

    meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return augmented, meta


def _keyword_axis_coverage(hits: list, axes: List[str]) -> Dict[str, int]:
    """Quick keyword-based axis coverage check (no model inference).

    For each axis, count how many passages contain ≥2 distinctive keywords
    from that axis. Returns {axis: passage_count}.
    """
    coverage = {ax: 0 for ax in axes}
    for ax in axes:
        ax_kw = _extract_keywords(ax)
        for hit in hits:
            text = (hit.get("text_original") or hit.get("text", "")).lower()
            matched = sum(1 for kw in ax_kw if kw in text)
            if matched >= min(2, len(ax_kw)):
                coverage[ax] += 1
    return coverage


def _assign_axes_by_keyword(hits: list, axes: List[str]) -> list:
    """Assign axis scores using keyword overlap instead of CE inference.

    Cheap alternative to _score_passages_by_axis when CE re-scoring
    would not change the passage set (all axes covered, pool ≤ cap).
    """
    for hit in hits:
        text = (hit.get("text_original") or hit.get("text", "")).lower()
        axis_scores = {}
        for ax in axes:
            ax_kw = _extract_keywords(ax)
            if not ax_kw:
                axis_scores[ax] = 0.5
                continue
            matched = sum(1 for kw in ax_kw if kw in text)
            # Normalize to 0-1 range, with baseline from reranker score
            kw_ratio = matched / len(ax_kw)
            base_score = hit.get("rank_score", 0.5)
            axis_scores[ax] = round(base_score * (0.5 + 0.5 * kw_ratio), 4)
        hit["axis_scores"] = axis_scores
        hit["primary_axis"] = max(axis_scores, key=axis_scores.get)
    return hits


def _distill_by_axes(
    query: str,
    hits: list,
    reranker_key: str = DEFAULT_RERANKER,
) -> dict:
    """Full distillation pipeline: decompose → score → budget → text-level select.

    Returns dict with:
        axes: list of detected axes
        hits: budgeted hits with axis metadata and text_level selected
        distilled: True

    Conditional optimization: when passage count ≤ CONTEXT_MAX_PASSAGES and
    all axes already have keyword coverage (≥2 passages each), skip the
    expensive CE re-scoring and use keyword-based axis assignment instead.
    This preserves text-level selection and budget allocation while
    eliminating ~500-2000ms of cross-encoder inference per query.
    """
    axes = _decompose_axes(query)

    if len(axes) <= 1:
        # Single axis: no distillation needed, just select text levels
        for hit in hits:
            hit["axis_scores"] = {axes[0]: hit.get("rank_score", 0.5)}
            hit["primary_axis"] = axes[0]
            hit["distilled_text"] = _select_text_level(hit)
        return {"axes": axes, "hits": hits, "distilled": False}

    # ── Conditional distillation gate ──
    # If the passage pool is already at/below the cap and all axes have
    # keyword coverage, CE re-scoring won't change which passages survive.
    # Use cheap keyword-based axis assignment instead.
    if len(hits) <= CONTEXT_MAX_PASSAGES:
        kw_coverage = _keyword_axis_coverage(hits, axes)
        all_covered = all(count >= 2 for count in kw_coverage.values())
        if all_covered:
            scored = _assign_axes_by_keyword(hits, axes)
            budgeted = _budget_passages(scored, axes)
            for hit in budgeted:
                hit["distilled_text"] = _select_text_level(hit)
            return {"axes": axes, "hits": budgeted, "distilled": True,
                    "distill_mode": "keyword"}

    ce, _ = _get_reranker(reranker_key)
    if ce is None:
        for hit in hits:
            hit["axis_scores"] = {ax: 0.5 for ax in axes}
            hit["primary_axis"] = axes[0]
            hit["distilled_text"] = _select_text_level(hit)
        return {"axes": axes, "hits": hits, "distilled": False}

    scored = _score_passages_by_axis(axes, hits, ce)

    # Entity co-occurrence filter using ratio scoring: passages must match a
    # sufficient fraction of the entity's distinctive words. A passage matching
    # 1/3 entity words (e.g., "hydrocephalus" only for "normal pressure
    # hydrocephalus") gets axis scores scaled by the ratio, while full matches
    # pass through. This prevents generic-category passages from outscoring
    # entity-specific ones during budget allocation.
    entities = _extract_primary_entities(query)
    if entities:
        drug_disease = _classify_drug_disease_context(entities, query)

        for hit in scored:
            text = hit.get("text_original") or hit.get("text", "")
            ratio = _entity_match_ratio(text, entities)

            if ratio < 0.5:
                # Low co-occurrence — scale axis scores by ratio (harsh for 0.33, mild for 0.49)
                penalty_mult = max(0.15, ratio)
                axis_scores = hit.get("axis_scores", {})
                for ax in axis_scores:
                    axis_scores[ax] = round(axis_scores[ax] * penalty_mult, 4)
                hit["entity_cooccurrence_penalty"] = True
                hit["_entity_ratio_distill"] = ratio
            elif drug_disease:
                # Drug-disease check: passage has entity but is it about the right disease?
                text_lower = text.lower()
                has_drug = any(d in text_lower for d in drug_disease["drugs"])
                has_disease = _entity_present_in_text(text, drug_disease["diseases"])
                if has_drug and not has_disease:
                    axis_scores = hit.get("axis_scores", {})
                    for ax in axis_scores:
                        axis_scores[ax] = round(axis_scores[ax] * 0.2, 4)
                    hit["entity_cooccurrence_penalty"] = True
                    hit["drug_no_disease_context"] = True

    budgeted = _budget_passages(scored, axes)

    for hit in budgeted:
        hit["distilled_text"] = _select_text_level(hit)

    return {"axes": axes, "hits": budgeted, "distilled": True}


# ── Main retrieval pipeline ──────────────────────────────────────────────────

def retrieve(
    query: str,
    lance_dir: str = "",
    table_name: str = "",
    n_results: int = DEFAULT_N_RESULTS,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    reranker_key: str = DEFAULT_RERANKER,
    use_parent_expansion: bool = True,
    visual: bool = False,
) -> dict:
    """Full retrieval pipeline: encode → dense+FTS → RRF → rerank → expand."""
    t_total_start = time.perf_counter()

    table = _get_lance_table(lance_dir, table_name)

    t0 = time.perf_counter()
    query_dense = _encode_query(query)
    encode_ms = round((time.perf_counter() - t0) * 1000, 2)

    dense_hits, dense_ms = _dense_search(table, query_dense, n_results)
    fts_hits, fts_ms = _sparse_search_fts(table, query, n_results)

    t0 = time.perf_counter()
    fused = _apply_rrf(dense_hits, fts_hits)
    rrf_ms = round((time.perf_counter() - t0) * 1000, 2)

    candidates = [h for h in fused if h.get("similarity", 0.0) >= min_similarity]
    below_threshold = len(fused) - len(candidates)
    if not candidates and fused:
        candidates = fused[:10]

    pre_ref_count = len(candidates)
    candidates = [h for h in candidates if not _is_low_value_retrieval_hit(h)]
    refs_dropped = pre_ref_count - len(candidates)
    candidates_before_cap = len(candidates)
    if PRE_RERANK_MAX_CANDIDATES > 0:
        candidates = candidates[:PRE_RERANK_MAX_CANDIDATES]

    reranked, rerank_ms = _rerank_hits(query, candidates, reranker_key)
    reranked = [
        h for h in reranked
        if not h.get("is_reference_chunk") and not _is_low_value_retrieval_hit(h)
    ]

    # Entity-aware filtering: penalize/remove cross-entity false positives
    pre_entity_count = len(reranked)
    entities = _extract_primary_entities(query)
    if entities and reranked:
        reranked = _apply_entity_aware_filtering(reranked, query, entities)
    post_entity_count = len(reranked)

    # Snapshot the post-entity-filter reranked pool. The expansion step caps
    # final_hits to CONTEXT_MAX_PASSAGES; AUG-CE augmentation downstream needs
    # the wider pool to consider candidates that didn't make the initial cut.
    reranked_pool_snapshot = list(reranked)

    t0 = time.perf_counter()
    if use_parent_expansion and reranked:
        final_hits = _expand_with_parent_text(reranked, query)
    else:
        final_hits = reranked[:CONTEXT_MAX_PASSAGES]
    expand_ms = round((time.perf_counter() - t0) * 1000, 2)

    # Visual mode: enrich final hits with image_bytes from LanceDB
    if visual:
        image_ids = [h.get("child_id") for h in final_hits
                     if h.get("metadata", {}).get("has_image") and h.get("child_id")]
        if image_ids:
            try:
                import pyarrow.compute as pc
                arrow = table.to_arrow()
                for cid in image_ids:
                    mask = pc.equal(arrow["child_id"], cid)
                    filtered = arrow.filter(mask)
                    if len(filtered) > 0:
                        img = filtered["image_bytes"][0].as_py()
                        for h in final_hits:
                            if h.get("child_id") == cid and img:
                                h["_image_bytes"] = img
            except Exception:
                pass

    total_ms = round((time.perf_counter() - t_total_start) * 1000, 2)
    unique_sources = {h.get("source_key", "") for h in final_hits if h.get("source_key")}

    return {
        "query": query,
        "reranker": reranker_key,
        "hits": final_hits,
        "_reranked_pool": reranked_pool_snapshot,
        "latency": {
            "encode_ms": encode_ms, "dense_ms": dense_ms, "fts_ms": fts_ms,
            "rrf_ms": rrf_ms, "rerank_ms": rerank_ms, "expand_ms": expand_ms,
            "total_ms": total_ms,
        },
        "metadata": {
            "dense_candidates": len(dense_hits),
            "fts_candidates": len(fts_hits),
            "fused_candidates": len(fused),
            "below_threshold": below_threshold,
            "refs_dropped": refs_dropped,
            "pre_rerank_candidates": candidates_before_cap,
            "pre_rerank_cap": PRE_RERANK_MAX_CANDIDATES,
            "pre_rerank_capped": max(0, candidates_before_cap - len(candidates)),
            "after_rerank": len(reranked),
            "final_passages": len(final_hits),
            "unique_sources": len(unique_sources),
            "source_books": sorted(unique_sources),
        },
    }


# ── Context building ─────────────────────────────────────────────────────────

def _load_frontier_notes(min_mtime: float | None = None) -> str:
    """Read frontier_cache.md if it exists and is fresh (<5 min).

    If ``min_mtime`` is provided, only accept cache files modified at or after
    that epoch timestamp. This prevents stale cross-query frontier reuse.
    """
    cache_path = SESSIONS_DIR / "frontier_cache.md"
    try:
        if cache_path.exists():
            cache_mtime = cache_path.stat().st_mtime
            if min_mtime is not None and cache_mtime < min_mtime:
                return ""
            age_sec = time.time() - cache_mtime
            if age_sec < 300:
                cached = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
                if cached and "No frontier evidence found" not in cached:
                    return cached
    except Exception:
        pass
    return ""


def _extract_images(hits: list) -> list:
    """Extract image_bytes from hits with has_image=True, save to temp files.
    Returns list of dicts with {path, citation, page, source_book}.
    """
    import base64
    figures_dir = SESSIONS_DIR / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    for i, hit in enumerate(hits):
        meta = hit.get("metadata", {})
        img_bytes = hit.get("_image_bytes")
        if not img_bytes or not meta.get("has_image"):
            continue
        fname = f"fig_{i:02d}.png"
        fpath = figures_dir / fname
        try:
            fpath.write_bytes(img_bytes)
            extracted.append({
                "path": str(fpath),
                "citation": hit.get("citation", ""),
                "page": meta.get("page_start", "?"),
                "source_book": meta.get("source_book", ""),
            })
        except Exception:
            pass
    return extracted


def _collapse_repeated_prefixes(text: str, min_len: int = 60, min_reps: int = 3) -> str:
    """Collapse long substrings that repeat excessively in LanceDB passage text.

    Table ingestion produces text like 'Table 76.2 Very Long Name.Col = Val'
    with the table name (100+ chars) repeated per cell.  This finds any long
    substring that appears 3+ times and keeps the first occurrence, replacing
    subsequent ones with a short '[...]' marker.

    Also collapses pipe-table header rows where every column cell is identical
    (e.g. '| Long Name | Long Name | Long Name |') into a single mention.
    """
    # Find "Table X.Y <title>" strings that repeat
    candidates = re.findall(r"(Table\s+[\d.]+\s+\S[^|]{" + str(min_len - 10) + r",}?)(?=[.|])", text)
    if not candidates:
        return text

    from collections import Counter
    counts = Counter(candidates)
    result = text

    for substr, count in counts.items():
        if count < min_reps or len(substr) < min_len:
            continue
        # Keep first occurrence, replace the rest
        first = result.find(substr)
        if first == -1:
            continue
        before = result[:first + len(substr)]
        after = result[first + len(substr):]
        after = after.replace(substr, "[tbl]")
        result = before + after

    return result


def _format_hit_block(hit: dict, passage_id: str = "") -> Optional[str]:
    """Format a single hit into a passage block. Returns None for reference chunks.

    When passage_id is provided (e.g. "P1"), it is prepended to the block header
    to enable citation tracing between scratch_context.md and transform_output.md.
    """
    # Use distilled text if available (axis-aware text-level selection),
    # otherwise fall back to raw text
    text = hit.get("distilled_text") or hit.get("text", "")
    text = _collapse_repeated_prefixes(text)
    if _is_low_value_retrieval_hit({**hit, "text": text}):
        return None

    citation = hit.get("citation", "uncited")
    meta_flags = []
    meta = hit.get("metadata", {})
    if meta.get("has_image"):
        meta_flags.append("[HAS_FIGURE]")
    if meta.get("has_table"):
        meta_flags.append("[HAS_TABLE]")
    if meta.get("page_start"):
        meta_flags.append(f"[Page {meta['page_start']}]")
    chunks = hit.get("passage_chunks")
    cluster_hits = hit.get("cluster_hits")
    if chunks and chunks > 1:
        meta_flags.append(f"[{cluster_hits} hits clustered across {chunks} chunks]")

    flag_str = " ".join(meta_flags)
    id_prefix = f"[{passage_id}] " if passage_id else ""
    block = f"{id_prefix}[TEXTBOOK THEORY] {citation} {flag_str}\n{text}"

    # Store passage_id on the hit for downstream audit
    if passage_id:
        hit["_passage_id"] = passage_id

    # Only append table_markdown separately if not already included via distilled_text
    if hit.get("table_markdown") and not hit.get("distilled_text"):
        table_md = _collapse_repeated_prefixes(hit["table_markdown"])
        block += f"\n\n[TEXTBOOK THEORY TABLE DATA]\n{table_md}"

    return block


def build_scratch_context(result: dict, frontier_text: str = "",
                          visual: bool = False) -> str:
    """Format retrieval results into scratch_context.md for the Transform subagent.

    Each passage is assigned a unique ID (P1, P2, ...) for citation tracing.
    """
    query = result["query"]
    hits = result["hits"]
    axes = result.get("axes", [])
    distilled = result.get("distilled", False)

    passage_counter = [0]  # mutable counter for closure

    def _next_id() -> str:
        passage_counter[0] += 1
        return f"P{passage_counter[0]}"

    if distilled and len(axes) > 1:
        # Group passages by axis
        axis_groups: Dict[str, list] = {ax: [] for ax in axes}
        for hit in hits:
            primary = hit.get("primary_axis", axes[0])
            if primary in axis_groups:
                axis_groups[primary].append(hit)
            else:
                axis_groups[axes[0]].append(hit)

        sections = []
        for ax in axes:
            group_hits = axis_groups[ax]
            if not group_hits:
                continue
            blocks = []
            for hit in group_hits:
                block = _format_hit_block(hit, passage_id=_next_id())
                if block:
                    blocks.append(block)
            if blocks:
                sections.append(f"## Axis: {ax.strip().title()}\n\n" + "\n\n".join(blocks))

        source_knowledge = "\n\n".join(sections).strip() or "No local source knowledge provided."
    else:
        # Flat format (single axis or no distillation)
        blocks = []
        for hit in hits:
            block = _format_hit_block(hit, passage_id=_next_id())
            if block:
                blocks.append(block)
        source_knowledge = "\n\n".join(blocks).strip() or "No local source knowledge provided."

    if frontier_text:
        frontier_section = frontier_text
    else:
        frontier_section = (
            "No external frontier notes provided. "
            "IMPORTANT: Do NOT use [Frontier] tags or fabricate external citations."
        )

    context = (
        f"Query:\n{query.strip()}\n\n"
        f"Source Knowledge:\n{source_knowledge}\n\n"
        f"Frontier Evidence:\n{frontier_section}\n"
    )

    # Visual mode: extract and embed figure references
    if visual:
        figures = _extract_images(hits)
        if figures:
            fig_lines = ["\n# 🖼️ Extracted Figures\n"]
            for fig in figures:
                fig_lines.append(
                    f"**Figure** — {fig['citation']} (p.{fig['page']})\n"
                    f"```python\nfrom IPython.display import Image, display\n"
                    f"display(Image(filename='{fig['path']}'))\n```\n"
                )
            context += "\n".join(fig_lines)

    return context


def _split_sentences(text: str) -> list[str]:
    """Lightweight sentence splitter for source-card extraction."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text) if s.strip()]


_OPERATIVE_SIGNAL_RE = re.compile(
    r"\b("
    r"indicat|contraindicat|approach|exposure|plane|retractor|longus|"
    r"decompress|foramin|osteophyte|PLL|OPLL|graft|cage|plate|screw|"
    r"monitor|SSEP|MEP|MAP|cuff|hemost|bleed|injur|complication|"
    r"avoid|repair|rescue|tamponade|angiograph|dysphagia|laryngeal|"
    r"esophag|vertebral artery|outcome|arthroplasty|pseudarthrosis|"
    r"adjacent|hematoma|CSF|dural|fusion|alignment|kyphosis"
    r")\b",
    re.IGNORECASE,
)


_NUMBER_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|degrees?|mm|cm|years?|months?|weeks?|days?|hours?|lbs?)\b|"
    r"\b(?:less than|more than|greater than|fewer than|up to|approximately|around|about)\s+\d+)",
    re.IGNORECASE,
)


def _compact_sentences(text: str, max_items: int = 5) -> list[str]:
    """Select conduct-changing sentences without calling an LLM."""
    scored: list[tuple[int, int, str]] = []
    for idx, sent in enumerate(_split_sentences(text)):
        if len(sent) < 45:
            continue
        score = 0
        score += 3 if _OPERATIVE_SIGNAL_RE.search(sent) else 0
        score += 2 if _NUMBER_RE.search(sent) else 0
        score += 1 if len(sent) < 260 else 0
        if score:
            scored.append((score, -idx, sent[:420]))
    scored.sort(reverse=True)
    selected = [s for _, _, s in scored[:max_items]]
    if selected:
        return selected
    return [s[:420] for s in _split_sentences(text)[:max_items]]


def _numbers_from_text(text: str, max_items: int = 8) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for match in _NUMBER_RE.finditer(text or ""):
        val = match.group(0).strip()
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(val)
        if len(values) >= max_items:
            break
    return values


def _is_low_value_source_card(hit: dict, text: str) -> bool:
    """Skip cards that are mostly index/reference navigation rather than content."""
    citation = (hit.get("citation") or "").lower()
    if " ch: index " in f" {citation} ":
        return True
    if " ch: r " in f" {citation} ":
        return True
    low_value_markers = len(re.findall(r"\b\d{2,4}-\d{2,4}\b|,\s*[123]\s*=", text or ""))
    signal_sentences = sum(1 for s in _split_sentences(text) if _OPERATIVE_SIGNAL_RE.search(s))
    return low_value_markers >= 8 and signal_sentences <= 2


def build_source_cards_jsonl(
    result: dict,
    frontier_text: str = "",
    coverage_blocks: Optional[list[str]] = None,
    max_takeaways: int = 8,
    card_prefix: str = "QCARD",
    compact_schema: bool = True,
) -> str:
    """Build compact machine-readable source cards from retrieval hits.

    This is deliberately extractive and conservative. The agent still reasons
    from the cards, but it no longer needs to ingest raw RAG dumps just to make
    the first compression pass.
    """
    query = result["query"]
    rows: list[dict[str, Any]] = []
    for idx, hit in enumerate(result.get("hits", []), 1):
        text = hit.get("distilled_text") or hit.get("text", "")
        text = _collapse_repeated_prefixes(text)
        if not text or _is_low_value_retrieval_hit({**hit, "text": text}):
            continue
        if _is_low_value_source_card(hit, text):
            continue
        meta = hit.get("metadata", {}) or {}
        row = {
            "card_id": f"{card_prefix}-{idx:02d}",
            "citation": hit.get("citation", "uncited"),
            "page_start": meta.get("page_start"),
            "takeaways": [s[:260] for s in _compact_sentences(text, max_items=max_takeaways)],
            "numbers_thresholds_effects": _numbers_from_text(text, max_items=5),
            "raw_ref": {
                "child_id": hit.get("child_id"),
                "source_key": hit.get("source_key", ""),
                "chunk_index": meta.get("chunk_index"),
            },
        }
        if not compact_schema:
            row.update({
                "query": query,
                "coverage_blocks": coverage_blocks or [],
                "source_key": hit.get("source_key", ""),
                "has_figure": bool(meta.get("has_image")),
                "has_table": bool(meta.get("has_table")),
                "operative_consequence": "Use for operative decision-making, risk anticipation, or rescue planning if relevant to the coverage block.",
                "uncertainty": "Extractive card; inspect raw passage if a passage-level dispute or exact quotation matters.",
            })
        rows.append(row)

    if frontier_text and "No external frontier notes provided" not in frontier_text:
        row = {
            "card_id": f"{card_prefix}-{len(rows)+1:02d}",
            "citation": "Frontier Evidence",
            "page_start": None,
            "takeaways": _compact_sentences(frontier_text, max_items=max_takeaways),
            "numbers_thresholds_effects": _numbers_from_text(frontier_text),
            "raw_ref": {"cache": str(SESSIONS_DIR / "frontier_cache.md")},
        }
        if not compact_schema:
            row.update({
                "query": query,
                "coverage_blocks": coverage_blocks or [],
                "source_key": "frontier",
                "has_figure": False,
                "has_table": False,
                "operative_consequence": "Use only when contemporary evidence changes selection, consent, or outcomes defense.",
                "uncertainty": "Frontier note is extractive; verify primary article if exact practice-changing claim is disputed.",
            })
        rows.append(row)

    header = {
        "type": "source_card_manifest",
        "query": query,
        "coverage_blocks": coverage_blocks or [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "card_count": len(rows),
        "format": "jsonl",
        "schema": "compact" if compact_schema else "verbose",
    }
    return "\n".join([json.dumps(header, ensure_ascii=False)] + [
        json.dumps(row, ensure_ascii=False) for row in rows
    ]) + "\n"


# ── High-level CLI commands ──────────────────────────────────────────────────

def _run_frontier_search(query: str) -> bool:
    """Run frontier_search.py as a subprocess to fetch PMC evidence.

    Always invoked by compare() to ensure up-to-date literature is available.
    Respects the frontier cache (10-min TTL + query overlap) inside
    frontier_search.py itself, so redundant fetches are avoided.
    Returns True on success, False on failure.
    """
    frontier_script = BASE_DIR / "src" / "frontier_search.py"
    if not frontier_script.exists():
        return False

    venv_python = str(BASE_DIR / ".venv" / "bin" / "python3")
    python_bin = venv_python if os.path.isfile(venv_python) else sys.executable
    cmd = [python_bin, str(frontier_script), query]
    # Ensure arm64 on macOS to match venv numpy architecture
    if sys.platform == "darwin" and os.path.isfile("/usr/bin/arch"):
        cmd = ["/usr/bin/arch", "-arm64"] + cmd
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=45,
            cwd=str(BASE_DIR),
        )
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "")[-400:].strip()
            print(f"[WARN] Frontier search failed with exit code {proc.returncode}: {stderr_tail}", file=sys.stderr)
            return False
        # frontier_search.py writes to frontier_cache.md via file handshake
        # and also prints the result to stdout — we rely on the file handshake
        return True  # _load_frontier_notes() will read the cache file
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"[WARN] Frontier search failed: {e}", file=sys.stderr)
        return False


def _start_frontier_search(
    query: str,
    disabled: bool = False,
) -> tuple[threading.Thread | None, float | None, dict[str, bool]]:
    """Start frontier search in the background and return its state handle."""
    status = {"ok": False}
    if disabled:
        return None, None, status

    started_at = time.time()

    def _worker() -> None:
        status["ok"] = _run_frontier_search(query)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread, started_at, status


def _finish_frontier_search(
    thread: threading.Thread | None,
    started_at: float | None,
    status: dict[str, bool],
) -> str:
    """Wait for frontier search and return cache text if it completed."""
    if thread is None:
        return ""

    thread.join(timeout=45)
    if thread.is_alive():
        status["ok"] = False
        print("[WARN] Frontier search timed out; skipping frontier evidence for this run.", file=sys.stderr)
        return ""
    if status["ok"] and started_at is not None:
        return _load_frontier_notes(min_mtime=started_at)
    return ""


def _detect_coverage_gaps(hits: list, axes: List[str]) -> List[str]:
    """Detect axes with insufficient primary passage coverage.

    Uses axis scores from CE distillation (when available) rather than keyword
    overlap. An axis is a "gap" if no passage has it as its primary_axis with
    a score ≥ 0.3. Falls back to keyword overlap if axis_scores aren't present.

    This catches cases where DTI passages incidentally mention "craniotomy" or
    "stimulation" but aren't primarily about awake craniotomy technique.
    """
    if not axes or len(axes) <= 1:
        return []

    # Prefer axis-score-based gap detection (post-distillation)
    has_axis_scores = any(h.get("axis_scores") for h in hits)

    gap_axes = []
    for axis in axes:
        if has_axis_scores:
            # Count passages whose primary axis matches AND score is meaningful
            count = sum(
                1 for h in hits
                if h.get("primary_axis") == axis
                and h.get("axis_scores", {}).get(axis, 0.0) >= 0.3
            )
        else:
            # Fallback: keyword overlap (pre-distillation calls)
            axis_kw = _extract_keywords(axis)
            count = sum(
                1 for h in hits
                if len(_extract_keywords(h.get("text", "")) & axis_kw) >= 2
            )
        if count == 0:
            gap_axes.append(axis)
    return gap_axes


def compare(query: str, output_file: str = "",
            visual: bool = False, no_distill: bool = False,
            no_frontier: bool = False, stdout: bool = False,
            card_json: bool = False,
            card_output: str = "",
            coverage_blocks: Optional[list[str]] = None,
            max_passages: int = 0,
            frontier_max_chars: int = 0,
            card_prefix: str = "QCARD",
            max_takeaways: int = 4,
            verbose_cards: bool = False):
    """Retrieve, build context, and deliver to the agent.

    This is the primary entrypoint called by the agent workflow.

    Delivery modes:
      --stdout   Print formatted context to stdout (agent gets it inline
                 from the bash tool result — no file, no extra read step).
      --output   Write to a custom file path.
      (default)  Write to data/Sessions/scratch_context.md.

    Frontier search is always triggered (unless --no-frontier) to ensure
    up-to-date PMC literature is included alongside textbook retrieval.
    Frontier runs concurrently with retrieval (I/O-bound vs CPU-bound).
    """
    frontier_thread, frontier_started_at, frontier_status = _start_frontier_search(
        query,
        disabled=no_frontier,
    )

    result = retrieve(query, visual=visual)

    # Adaptive Context Distillation (between retrieval and context building)
    pre_distill_count = len(result["hits"])
    if not no_distill and result["hits"]:
        distill_result = _distill_by_axes(query, result["hits"])
        result["hits"] = distill_result["hits"]
        result["axes"] = distill_result["axes"]
        result["distilled"] = distill_result["distilled"]
    post_distill_count = len(result["hits"])

    # Auto-append: detect axes with zero coverage and run targeted retrieval
    gap_fill_added = 0
    if not no_distill and result.get("axes") and len(result["axes"]) > 1:
        gap_axes = _detect_coverage_gaps(result["hits"], result["axes"])
        if gap_axes:
            # Extract original query's entities for:
            # 1. Entity propagation into gap-fill search queries
            # 2. Drug-disease filtering of gap results
            _gap_entities = _extract_primary_entities(query)
            _gap_drug_disease = _classify_drug_disease_context(_gap_entities, query) if _gap_entities else None

            for gap_axis in gap_axes[:2]:
                # ── Entity-enriched gap-fill query ──
                # Axis decomposition often strips entity context, leaving generic
                # axes like "surgical considerations for each in the posterior
                # fossa" when the query was about dermoid/epidermoid cysts.
                # Enrich the gap search by appending entity names that aren't
                # already present in the axis text.
                gap_query = gap_axis
                if _gap_entities:
                    axis_lower = gap_axis.lower()
                    missing_entities = [
                        e for e in _gap_entities
                        if e.lower() not in axis_lower
                    ]
                    if missing_entities:
                        entity_suffix = " ".join(missing_entities)
                        gap_query = f"{gap_axis} {entity_suffix}"

                gap_result = retrieve(gap_query, visual=False)
                if gap_result["hits"]:
                    # Filter gap results: require minimum entity co-occurrence
                    # with original query entities (ratio ≥ 0.5)
                    if _gap_entities:
                        filtered_gap_hits = []
                        for gh in gap_result["hits"]:
                            text = gh.get("text_original") or gh.get("text", "")
                            ratio = _entity_match_ratio(text, _gap_entities)
                            if ratio >= 0.4:  # Slightly relaxed for gap-fill
                                filtered_gap_hits.append(gh)
                        # Drug-disease additional filter
                        if _gap_drug_disease and filtered_gap_hits:
                            final_gap_hits = []
                            for gh in filtered_gap_hits:
                                t = (gh.get("text_original") or gh.get("text", "")).lower()
                                has_drug = any(d in t for d in _gap_drug_disease["drugs"])
                                has_disease = _entity_present_in_text(
                                    gh.get("text", ""), _gap_drug_disease["diseases"]
                                )
                                if has_drug and not has_disease:
                                    continue
                                final_gap_hits.append(gh)
                            gap_result["hits"] = final_gap_hits
                        else:
                            gap_result["hits"] = filtered_gap_hits

                    # Run distillation on gap results with single axis
                    gap_distill = _distill_by_axes(gap_axis, gap_result["hits"])
                    new_hits = gap_distill["hits"]
                    # Merge into existing hits, deduplicate by content hash
                    existing_hashes = {_content_hash(h.get("text", "")) for h in result["hits"]}
                    added = 0
                    for h in new_hits:
                        ch = _content_hash(h.get("text", ""))
                        if ch not in existing_hashes and len(result["hits"]) < CONTEXT_MAX_PASSAGES + 4:
                            h["primary_axis"] = gap_axis
                            h["gap_fill"] = True
                            result["hits"].append(h)
                            existing_hashes.add(ch)
                            added += 1
                    if added:
                        gap_fill_added += added
                        print(f"  gap-fill: +{added} passages for axis '{gap_axis[:50]}'",
                              file=sys.stderr)

    # Quality-aware augmentation (AUG-CE): append up to AUG_MAX_EXTRA passages
    # from the reranked pool when the candidate clears the Δ-quality + CE-floor
    # + token-budget gates. Non-destructive — preserves all existing hits.
    aug_candidates = result.get("_reranked_pool") or []
    if aug_candidates and result.get("hits"):
        augmented_hits, aug_meta = _quality_augment(query, result["hits"], aug_candidates)
        result["hits"] = augmented_hits
        result["augment_ce"] = aug_meta

    frontier_text = _finish_frontier_search(
        frontier_thread,
        frontier_started_at,
        frontier_status,
    )
    if max_passages and max_passages > 0:
        result["hits"] = result["hits"][:max_passages]

    if frontier_max_chars and frontier_max_chars > 0 and len(frontier_text) > frontier_max_chars:
        frontier_text = (
            frontier_text[:frontier_max_chars].rstrip()
            + "\n\n[Frontier evidence truncated by --frontier-max-chars; inspect frontier_cache.md for full audit.]"
        )

    prompt_content = build_scratch_context(result, frontier_text, visual=visual)
    card_content = ""
    if card_json:
        card_content = build_source_cards_jsonl(
            result,
            frontier_text=frontier_text,
            coverage_blocks=coverage_blocks or [],
            card_prefix=card_prefix,
            max_takeaways=max_takeaways,
            compact_schema=not verbose_cards,
        )

    n_passages = len(result["hits"])
    source_set = {h.get("source_key", "") for h in result["hits"] if h.get("source_key")}
    n_sources = len(source_set)
    ms = result["latency"]["total_ms"]

    if card_output:
        card_path = Path(card_output)
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text(card_content or build_source_cards_jsonl(
            result,
            frontier_text=frontier_text,
            coverage_blocks=coverage_blocks or [],
            card_prefix=card_prefix,
            max_takeaways=max_takeaways,
            compact_schema=not verbose_cards,
        ), encoding="utf-8")

    if stdout:
        # Deliver context directly to agent via stdout — no file intermediary.
        # Summary line goes to stderr so it doesn't pollute the context.
        print(card_content if card_json else prompt_content)
        print(f"OK {n_passages} passages | {n_sources} sources | {ms:.0f}ms",
              file=sys.stderr)
    else:
        context_file = Path(output_file) if output_file else SESSIONS_DIR / "scratch_context.md"
        context_file.parent.mkdir(parents=True, exist_ok=True)
        context_file.write_text(prompt_content, encoding="utf-8")
        print(f"OK {n_passages} passages | {n_sources} sources | {ms:.0f}ms")


# ── Warm-up ──────────────────────────────────────────────────────────────────
#
# Each fresh `compare` invocation pays ~10-15s in model load + HuggingFace
# network checks before retrieval can begin. The `warmup` subcommand is a
# one-shot in-process preload that confirms the HuggingFace cache is healthy
# and prints per-stage timings — useful as a sanity check before a batch of
# RAG queries from the same process. It does NOT spawn a daemon.

def _warm_models(verbose: bool = True) -> Dict[str, float]:
    """Preload BGE-M3, the default cross-encoder reranker, and SciSpacy NER.

    Returns a per-stage timing dict. Network calls happen only if the HuggingFace
    cache is missing or stale; set HF_HUB_OFFLINE=1 to force fully offline.
    """
    timings: Dict[str, float] = {}

    if verbose:
        print("[warmup] loading LanceDB table…", flush=True)
    t0 = time.time()
    _get_lance_table()
    timings["lancedb_table"] = time.time() - t0

    if verbose:
        print("[warmup] loading BGE-M3 embedding model…", flush=True)
    t0 = time.time()
    _get_embedding_model()
    timings["embedding_bge_m3"] = time.time() - t0

    if verbose:
        print(f"[warmup] loading cross-encoder reranker '{DEFAULT_RERANKER}'…", flush=True)
    t0 = time.time()
    _get_reranker(DEFAULT_RERANKER)
    timings["reranker_cross_encoder"] = time.time() - t0

    if verbose:
        print("[warmup] loading SciSpacy NER (en_ner_bc5cdr_md)…", flush=True)
    t0 = time.time()
    _get_ner_nlp()
    timings["ner_scispacy"] = time.time() - t0

    if verbose:
        print("[warmup] done. timings (s):", {k: round(v, 2) for k, v in timings.items()}, flush=True)
    return timings


def list_textbooks():
    """List all unique textbooks and chunk counts in the LanceDB table."""
    import pyarrow.compute as pc
    table = _get_lance_table()
    arrow = table.to_arrow()
    vc = pc.value_counts(arrow["source_book"])

    entries = []
    total = 0
    for i in range(len(vc)):
        s = vc[i]
        name = s["values"].as_py()
        count = s["counts"].as_py()
        entries.append((count, name))
        total += count
    entries.sort(key=lambda x: -x[0])

    print(f"Database Inventory ({DEFAULT_LANCE_TABLE})")
    print(f"{'─' * 50}")
    for count, name in entries:
        print(f"  {count:>5d}  {name}")
    print(f"{'─' * 50}")
    print(f"  {total:>5d}  TOTAL ({len(entries)} books)")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LanceDB retrieval engine")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # compare
    p_compare = subparsers.add_parser("compare",
                                      help="Retrieve, rerank, distill, and deliver textbook context")
    p_compare.add_argument("query", help="Search query")
    p_compare.add_argument("--stdout", action="store_true",
                           help="Print context to stdout (agent gets it inline, no file)")
    p_compare.add_argument("--output", default="", help="Custom output file path")
    p_compare.add_argument("--visual", action="store_true", help="Extract images from hits")
    p_compare.add_argument("--no-distill", action="store_true",
                           help="Bypass adaptive context distillation")
    p_compare.add_argument("--no-frontier", action="store_true",
                           help="Skip automatic frontier (PMC) search")
    p_compare.add_argument("--card-json", action="store_true",
                           help="Print/write compact JSONL source cards instead of full formatted context")
    p_compare.add_argument("--card-output", default="",
                           help="Optional path for JSONL source-card output")
    p_compare.add_argument("--coverage-block", action="append", default=[],
                           help="Coverage block label to attach to emitted source cards; repeatable")
    p_compare.add_argument("--max-passages", type=int, default=0,
                           help="Limit final passage/card count after retrieval and distillation")
    p_compare.add_argument("--frontier-max-chars", type=int, default=0,
                           help="Truncate frontier evidence in output/cards to this many characters")
    p_compare.add_argument("--card-prefix", default="QCARD",
                           help="Prefix for emitted source card IDs, e.g. Q1-CARD")
    p_compare.add_argument("--max-takeaways", type=int, default=4,
                           help="Maximum extractive takeaways per emitted source card")
    p_compare.add_argument("--verbose-cards", action="store_true",
                           help="Include repeated query/coverage metadata on every card row")

    # search (raw retrieval for debugging)
    p_search = subparsers.add_parser("search", help="Raw retrieval (debug)")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--json", action="store_true", help="JSON output")
    p_search.add_argument("--reranker", default=DEFAULT_RERANKER,
                          choices=list(RERANKER_MODELS.keys()))
    p_search.add_argument("--n-results", type=int, default=DEFAULT_N_RESULTS)

    # list_textbooks
    subparsers.add_parser("list_textbooks", help="Show database inventory")

    # warmup: preload embedding/reranker/NER models in-process (one-shot, no daemon)
    p_warmup = subparsers.add_parser("warmup",
                                     help="Preload models so HuggingFace cache is verified and ready (one-shot, no daemon)")
    p_warmup.add_argument("--quiet", action="store_true",
                          help="Suppress per-stage logging (print final timings only)")

    args = parser.parse_args()

    if args.command == "compare":
        compare(args.query, output_file=args.output,
                visual=args.visual, no_distill=args.no_distill,
                no_frontier=args.no_frontier,
                stdout=args.stdout,
                card_json=args.card_json,
                card_output=args.card_output,
                coverage_blocks=args.coverage_block,
                max_passages=args.max_passages,
                frontier_max_chars=args.frontier_max_chars,
                card_prefix=args.card_prefix,
                max_takeaways=args.max_takeaways,
                verbose_cards=args.verbose_cards)

    elif args.command == "warmup":
        _warm_models(verbose=not args.quiet)

    elif args.command == "search":
        result = retrieve(args.query, reranker_key=args.reranker,
                          n_results=args.n_results)
        if args.json:
            output = {
                "query": result["query"], "reranker": result["reranker"],
                "latency": result["latency"], "metadata": result["metadata"],
                "hits": [
                    {"citation": h.get("citation"), "similarity": h.get("similarity"),
                     "rank_score": h.get("rank_score"), "sigmoid_ce": h.get("sigmoid_ce"),
                     "passage_tokens": h.get("passage_tokens"),
                     "source_key": h.get("source_key"),
                     "text_preview": h.get("text", "")[:200]}
                    for h in result["hits"]
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            lat = result["latency"]
            meta = result["metadata"]
            print(f"OK {meta['final_passages']} passages | {meta['unique_sources']} sources | {lat['total_ms']:.0f}ms")
            for i, hit in enumerate(result["hits"], 1):
                print(f"  [{i}] {hit.get('citation', 'uncited')}")
                print(f"      rank={hit.get('rank_score')}, ce={hit.get('sigmoid_ce')}, "
                      f"tokens={hit.get('passage_tokens', '?')}")

    elif args.command == "list_textbooks":
        list_textbooks()

    else:
        parser.print_help()
