#!/usr/bin/env python3
"""
Frontier Search — Fetches recent, high-quality clinical literature from PubMed/PMC.

Used by the Neuro-RAG pipeline to provide "Frontier Evidence" alongside local
textbook retrieval.  Best practices implemented:

  1. NCBI API key support (env: NCBI_API_KEY) — avoids rate-limit bans.
  2. Exponential backoff retry on transient failures.
  3. Date-range filtering — defaults to last 5 years of literature.
  4. Study-type weighting — prefers RCTs, meta-analyses, reviews over case reports.
  5. MeSH-aware phrase preservation for precise PubMed queries.
  6. Abstract-level relevance filtering to remove off-topic hits.
  7. File handshake: auto-writes to frontier_cache.md for lance_retriever.py compare.
"""

import sys
import os
from typing import Optional, List, Tuple
import urllib.request
import urllib.parse
import json
import xml.etree.ElementTree as ET
import argparse
import textwrap
import time
import re
from datetime import datetime, timedelta

from pathlib import Path
SESSIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "Sessions"

# ── Venv & working directory guard ───────────────────────────────────────────
if __name__ == "__main__":
    from _env_guard import check_environment
    check_environment("frontier_search.py")

# ── Configuration ──────────────────────────────────────────────────────────────
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
DEFAULT_MAX_RESULTS = 3
DEFAULT_YEARS_BACK = 5
MAX_PARAGRAPHS_PER_ARTICLE = 20
MIN_PARAGRAPH_LENGTH = 40
REQUEST_TIMEOUT_SEC = 15
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # seconds; doubles each retry
RELEVANCE_THRESHOLD = 0.25  # min keyword overlap to keep an article

DEFAULT_FRONTIER_CACHE = SESSIONS_DIR / "frontier_cache.md"

# Study types to prefer (PubMed publication type filters)
# These are appended as OR-joined filters when available.
PREFERRED_STUDY_TYPES = [
    "Meta-Analysis",
    "Systematic Review",
    "Randomized Controlled Trial",
    "Review",
    "Clinical Trial",
    "Guideline",
    "Practice Guideline",
]

# Stop words for keyword extraction
_STOP_WORDS = frozenset({
    "how", "do", "you", "best", "avoid", "a", "when", "performing", "what",
    "are", "the", "most", "common", "of", "in", "is", "to", "for", "and",
    "or", "with", "on", "at", "by", "from", "an", "this", "that", "it",
    "as", "be", "was", "can", "which", "does", "should", "would", "could",
    "may", "will", "has", "have", "had", "been", "being", "its", "my",
    "your", "their", "our", "about", "between", "through", "during", "before",
    "after", "above", "below", "up", "down", "out", "into", "over", "under",
    "again", "further", "then", "once", "here", "there", "why", "all",
    "each", "every", "both", "few", "more", "other", "some", "such", "than",
    "too", "very", "just", "also", "not", "no", "nor", "only", "same",
    "so", "tell", "me", "describe", "explain", "teach", "walk", "addresses",
    "using", "role", "effect", "effects", "use", "used", "approach",
})

# ── Medical phrase dictionary ─────────────────────────────────────────────────
# Multi-word terms that should be kept as quoted phrases in PubMed queries.
# Order matters — longer phrases should come first to match greedily.
_MEDICAL_PHRASES = [
    # Neuromodulation / Pain
    "dorsal root ganglion", "spinal cord stimulation", "spinal cord stimulator",
    "deep brain stimulation", "responsive neurostimulation", "vagus nerve stimulation",
    "peripheral nerve stimulation", "motor cortex stimulation",
    "transcranial magnetic stimulation", "transcranial direct current stimulation",
    "endovascular stimulation", "endovascular neuromodulation",
    "chronic pain", "neuropathic pain", "complex regional pain syndrome",
    "failed back surgery syndrome", "phantom limb pain",
    "gate control theory", "neurostimulation",
    # Vascular
    "subarachnoid hemorrhage", "arteriovenous malformation",
    "middle cerebral artery", "anterior communicating artery",
    "posterior communicating artery", "basilar artery",
    "internal carotid artery", "vertebral artery",
    "cerebral vasospasm", "delayed cerebral ischemia",
    "flow diverter", "pipeline embolization",
    # Tumor
    "glioblastoma multiforme", "vestibular schwannoma",
    "pituitary adenoma", "meningioma",
    "gross total resection", "subtotal resection",
    "5-aminolevulinic acid", "awake craniotomy",
    # Spine
    "anterior cervical discectomy", "posterior cervical fusion",
    "lumbar interbody fusion", "spinal stenosis",
    "degenerative disc disease", "cervical myelopathy",
    # Functional
    "temporal lobe epilepsy", "mesial temporal sclerosis",
    "essential tremor", "Parkinson disease", "parkinsonian tremor",
    # Anatomy
    "dorsal column", "dorsal horn", "neural foramen",
    "cauda equina", "conus medullaris", "filum terminale",
    "circle of Willis",
    # Trauma
    "traumatic brain injury", "diffuse axonal injury",
    "intracranial pressure", "cerebral perfusion pressure",
    # Hydrocephalus
    "normal pressure hydrocephalus", "endoscopic third ventriculostomy",
    # CSF
    "cerebrospinal fluid",
]

# Abbreviation → MeSH-friendly expansion for PubMed queries
_ABBREVIATION_TO_MESH = {
    "drg": ("dorsal root ganglion", "Ganglia, Spinal[MeSH Terms]"),
    "scs": ("spinal cord stimulation", "Spinal Cord Stimulation[MeSH Terms]"),
    "dbs": ("deep brain stimulation", "Deep Brain Stimulation[MeSH Terms]"),
    "tbi": ("traumatic brain injury", "Brain Injuries, Traumatic[MeSH Terms]"),
    "icp": ("intracranial pressure", "Intracranial Pressure[MeSH Terms]"),
    "avm": ("arteriovenous malformation", "Intracranial Arteriovenous Malformations[MeSH Terms]"),
    "sah": ("subarachnoid hemorrhage", "Subarachnoid Hemorrhage[MeSH Terms]"),
    "gbm": ("glioblastoma multiforme", "Glioblastoma[MeSH Terms]"),
    "crps": ("complex regional pain syndrome", "Complex Regional Pain Syndromes[MeSH Terms]"),
    "vns": ("vagus nerve stimulation", "Vagus Nerve Stimulation[MeSH Terms]"),
    "rns": ("responsive neurostimulation", ""),
    "nph": ("normal pressure hydrocephalus", "Hydrocephalus, Normal Pressure[MeSH Terms]"),
    "acdf": ("anterior cervical discectomy and fusion", ""),
    "mca": ("middle cerebral artery", "Middle Cerebral Artery[MeSH Terms]"),
    "ica": ("internal carotid artery", "Carotid Artery, Internal[MeSH Terms]"),
}


def extract_keywords(text: str) -> Tuple[List[str], List[str]]:
    """Extract meaningful keywords from a natural-language query.

    Uses phrase-aware extraction: detects multi-word medical terms and
    preserves them as quoted phrases. Single remaining words are kept as
    individual keywords.

    Returns:
        Tuple of (phrases_and_keywords, mesh_terms) where:
        - phrases_and_keywords: list of quoted phrases and single keywords
        - mesh_terms: list of MeSH term filters to OR-join
    """
    cleaned = re.sub(r'[?.!,;:]', ' ', text)
    lower = cleaned.lower()

    phrases_found = []
    mesh_terms = []

    # 1. Detect and extract multi-word medical phrases
    remaining = lower
    for phrase in _MEDICAL_PHRASES:
        if phrase in remaining:
            phrases_found.append(f'"{phrase}"')
            # Remove the phrase from remaining text so its words aren't double-counted
            remaining = remaining.replace(phrase, " ")

    # 2. Expand abbreviations and collect MeSH terms
    words = remaining.split()
    expanded_words = []
    for w in words:
        w_clean = w.strip()
        if w_clean in _ABBREVIATION_TO_MESH:
            expansion, mesh = _ABBREVIATION_TO_MESH[w_clean]
            phrases_found.append(f'"{expansion}"')
            if mesh:
                mesh_terms.append(mesh)
        elif w_clean not in _STOP_WORDS and len(w_clean) > 1:
            expanded_words.append(w_clean)

    # 3. Combine: quoted phrases + remaining single keywords
    all_terms = phrases_found + expanded_words

    if not all_terms:
        # Fallback: just use the original text
        return ([text.strip()], [])

    return (all_terms, mesh_terms)


def _build_pubmed_query(
    terms: List[str],
    mesh_terms: List[str],
    years_back: int,
    prefer_study_types: bool,
) -> str:
    """Build a well-formed PubMed/PMC query string.

    Strategy:
    - Quoted multi-word phrases get [Title/Abstract] field targeting
    - Single keywords get [Title/Abstract] field targeting
    - MeSH terms are OR-joined as a supplementary filter
    - Study type and date filters are appended
    """
    # Target title/abstract for all terms
    targeted_terms = []
    for term in terms:
        if term.startswith('"') and term.endswith('"'):
            # Quoted phrase → target title/abstract
            targeted_terms.append(f"{term}[Title/Abstract]")
        else:
            targeted_terms.append(f"{term}[Title/Abstract]")

    # AND-join the core terms
    core_query = " AND ".join(targeted_terms)

    # OR-join MeSH terms as supplementary broadening
    if mesh_terms:
        mesh_clause = " OR ".join(mesh_terms)
        core_query = f"({core_query}) OR ({mesh_clause})"

    search_parts = [f"({core_query})", "open access[filter]"]

    # Date filter
    if years_back > 0:
        search_parts.append(_build_date_filter(years_back))

    query = " AND ".join(search_parts)

    # Study type filter
    if prefer_study_types:
        study_filter = _build_study_type_filter()
        query += f" AND {study_filter}"

    return query


def _score_relevance(article: dict, query_terms: List[str]) -> float:
    """Score an article's relevance to the query using keyword overlap.

    Checks title + abstract text against the extracted query terms.
    Returns a 0.0-1.0 relevance score.
    """
    # Build the article text to check against
    check_text = article.get("title", "").lower()
    # Use first 3 paragraphs as proxy for abstract/intro
    for p in article.get("paragraphs", [])[:3]:
        check_text += " " + p.lower()

    # Strip quotes from terms for matching
    clean_terms = []
    for term in query_terms:
        t = term.strip('"').lower()
        if t:
            clean_terms.append(t)

    if not clean_terms:
        return 1.0  # No terms to check against; keep everything

    # Count how many query terms appear in the article text
    matches = sum(1 for t in clean_terms if t in check_text)
    return matches / len(clean_terms)


def _build_date_filter(years_back: int) -> str:
    """Build a PubMed date range filter string for the past N years."""
    end = datetime.now()
    start = end - timedelta(days=years_back * 365)
    return f'{start.strftime("%Y/%m/%d")}:{end.strftime("%Y/%m/%d")}[dp]'


def _build_study_type_filter() -> str:
    """Build an OR-joined filter for preferred study types."""
    parts = [f'"{st}"[pt]' for st in PREFERRED_STUDY_TYPES]
    return "(" + " OR ".join(parts) + ")"


def _request_with_retry(url: str) -> bytes:
    """Make an HTTP GET request with exponential backoff retry."""
    headers = {"User-Agent": "Neuro-RAG/2.0 (neurosurgery education tool)"}
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
                return resp.read()
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF_BASE * (2 ** attempt)
                time.sleep(wait)

    if last_error is None:
        raise RuntimeError("request retries exhausted")
    raise last_error


def _extract_article_text(xml_data: bytes) -> Optional[dict]:
    """Parse a single PMC XML document into structured fields."""
    try:
        root = ET.fromstring(xml_data.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return None

    # Title
    title = "Unknown Title"
    title_el = root.find(".//article-title")
    if title_el is not None:
        title = "".join(title_el.itertext()).strip() or title

    # Year
    year = ""
    year_el = root.find(".//pub-date/year")
    if year_el is not None and year_el.text:
        year = year_el.text.strip()

    # Journal
    journal = ""
    journal_el = root.find(".//journal-title")
    if journal_el is not None and journal_el.text:
        journal = journal_el.text.strip()

    # PMC ID
    pmc_id = ""
    pmc_el = root.find(".//article-id[@pub-id-type='pmc']")
    if pmc_el is not None and pmc_el.text:
        pmc_id = pmc_el.text.strip()

    # Abstract — try to get structured abstract first
    abstract_parts = []
    for abstract_p in root.findall(".//abstract//p"):
        text = "".join(abstract_p.itertext()).strip()
        if len(text) > MIN_PARAGRAPH_LENGTH:
            abstract_parts.append(text)

    # Body paragraphs
    body_parts = []
    for p in root.findall(".//body//p"):
        text = "".join(p.itertext()).strip()
        if len(text) > MIN_PARAGRAPH_LENGTH:
            body_parts.append(text)

    # Prefer body text; fall back to abstract only if body is empty
    paragraphs = body_parts[:MAX_PARAGRAPHS_PER_ARTICLE]
    if not paragraphs:
        paragraphs = abstract_parts[:MAX_PARAGRAPHS_PER_ARTICLE]

    if not paragraphs:
        return None

    return {
        "title": title,
        "year": year,
        "journal": journal,
        "pmc_id": pmc_id,
        "paragraphs": paragraphs,
    }


def fetch_pmc_full_text(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    years_back: int = DEFAULT_YEARS_BACK,
    prefer_study_types: bool = True,
    output_file: Optional[str] = None,
) -> str:
    """Search PubMed Central for recent, high-quality full-text articles.

    Args:
        query: Natural-language search query.
        max_results: Maximum number of articles to retrieve.
        years_back: Only include literature from the past N years.
        prefer_study_types: If True, prioritize RCTs, reviews, meta-analyses.
        output_file: If set, write output to this file path (file handshake).

    Returns:
        Formatted text block suitable for LLM synthesis context.
    """
    # ── Frontier cache freshness check ──
    # If frontier_cache.md was written recently (<10 min) for a similar query,
    # skip the PubMed fetch and reuse the cached result.
    _cache_ttl = int(os.environ.get("NEURO_FRONTIER_CACHE_TTL", "600"))
    try:
        if DEFAULT_FRONTIER_CACHE.exists():
            _cache_age = time.time() - DEFAULT_FRONTIER_CACHE.stat().st_mtime
            if _cache_age < _cache_ttl:
                _cached_text = DEFAULT_FRONTIER_CACHE.read_text(encoding="utf-8", errors="ignore").strip()
                if _cached_text and "No frontier evidence found" not in _cached_text:
                    # Check if first line contains a similar query
                    _first_line = _cached_text.split("\n")[0] if _cached_text else ""
                    _q_lower = query.lower().strip()
                    _fl_lower = _first_line.lower().strip()
                    # Simple overlap check: if >60% of query words appear in the cached header
                    _q_words = set(_q_lower.split())
                    _fl_words = set(_fl_lower.split())
                    _overlap = len(_q_words & _fl_words) / max(1, len(_q_words))
                    if _overlap >= 0.6:
                        print(f"Frontier cache fresh ({int(_cache_age)}s old) — reusing cached results")
                        # Refresh cache timestamp so downstream readers can confirm
                        # this invocation produced/confirmed frontier content.
                        _write_cache(_cached_text, output_file)
                        return _cached_text
    except Exception:
        pass  # Silently fall through to live fetch

    terms, mesh_terms = extract_keywords(query)

    # Build the full PubMed query with phrase targeting
    primary_query = _build_pubmed_query(terms, mesh_terms, years_back, prefer_study_types)

    # Request more than needed so we can filter for relevance
    fetch_count = max_results * 3
    pmc_ids = _search_pmc(primary_query, fetch_count)

    # Fallback: without study type filter if primary returned nothing
    if not pmc_ids and prefer_study_types:
        fallback_query = _build_pubmed_query(terms, mesh_terms, years_back, prefer_study_types=False)
        pmc_ids = _search_pmc(fallback_query, fetch_count)

    # Second fallback: broaden to just the core terms without Title/Abstract targeting
    if not pmc_ids:
        simple_query = " AND ".join(t.strip('"') for t in terms)
        simple_query += " AND open access[filter]"
        if years_back > 0:
            simple_query += f" AND {_build_date_filter(years_back)}"
        pmc_ids = _search_pmc(simple_query, fetch_count)

    if not pmc_ids:
        result = "No frontier evidence found in PMC for this query."
        _write_cache(result, output_file)
        return result

    # Fetch and parse each article
    raw_results = []
    for pmc_id in pmc_ids:
        article = _fetch_article(pmc_id)
        if article:
            raw_results.append(article)

        # Rate limiting: NCBI allows 10 req/sec with API key, 3/sec without
        if not NCBI_API_KEY:
            time.sleep(0.35)  # Stay under 3 req/sec

    if not raw_results:
        result = "Found articles but failed to extract readable text."
        _write_cache(result, output_file)
        return result

    # Relevance filtering: score each article against query terms
    scored = []
    for art in raw_results:
        score = _score_relevance(art, terms)
        scored.append((score, art))

    # Sort by relevance descending, filter below threshold
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [art for score, art in scored if score >= RELEVANCE_THRESHOLD][:max_results]

    # If all filtered out, keep the top result anyway
    if not results and scored:
        results = [scored[0][1]]

    # Format output
    formatted = []
    for art in results:
        header = f"--- {art['title']}"
        if art["journal"]:
            header += f" | {art['journal']}"
        if art["year"]:
            header += f" ({art['year']})"
        if art["pmc_id"]:
            header += f" [PMC{art['pmc_id']}]"
        header += " ---"

        wrapped_paragraphs = [
            textwrap.fill(p, width=150) for p in art["paragraphs"]
        ]
        formatted.append(header + "\n" + "\n\n".join(wrapped_paragraphs))

    output = "\n\n\n".join(formatted)

    # File handshake: write to cache for lance_retriever.py compare
    _write_cache(output, output_file)

    return output


def _write_cache(content: str, output_file: Optional[str] = None):
    """Write frontier output to the cache file for lance_retriever.py handshake."""
    target = Path(output_file) if output_file else DEFAULT_FRONTIER_CACHE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[WARN] Failed to write frontier cache to {target}: {e}", file=sys.stderr)


def _search_pmc(query: str, max_results: int) -> list:
    """Execute a PubMed Central search and return PMC IDs."""
    encoded = urllib.parse.quote(query)
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pmc&term={encoded}&retmode=json&retmax={max_results}"
        f"&sort=relevance"
    )
    if NCBI_API_KEY:
        url += f"&api_key={NCBI_API_KEY}"

    try:
        data = json.loads(_request_with_retry(url).decode())
        return data.get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        print(f"[WARN] PMC search failed: {e}", file=sys.stderr)
        return []


def _fetch_article(pmc_id: str) -> Optional[dict]:
    """Fetch and parse a single PMC article by ID."""
    url = (
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=pmc&id={pmc_id}&retmode=xml"
    )
    if NCBI_API_KEY:
        url += f"&api_key={NCBI_API_KEY}"

    try:
        xml_data = _request_with_retry(url)
        return _extract_article_text(xml_data)
    except Exception as e:
        print(f"[WARN] Failed to fetch PMC{pmc_id}: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch full-text clinical articles from PubMed Central."
    )
    parser.add_argument("query", type=str, help="The search query.")
    parser.add_argument(
        "--max", type=int, default=DEFAULT_MAX_RESULTS,
        help=f"Maximum articles to retrieve (default: {DEFAULT_MAX_RESULTS})."
    )
    parser.add_argument(
        "--years", type=int, default=DEFAULT_YEARS_BACK,
        help=f"Look back N years (default: {DEFAULT_YEARS_BACK}). 0 = no filter."
    )
    parser.add_argument(
        "--no-study-filter", action="store_true",
        help="Disable study-type preference filtering."
    )
    parser.add_argument(
        "--output-file", type=str, default=None,
        help=f"Write output to this file (default: {DEFAULT_FRONTIER_CACHE})."
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Do not write to the default frontier cache file."
    )
    args = parser.parse_args()

    # Determine output file: explicit > default > None (if --no-cache)
    out_file = args.output_file
    if out_file is None and not args.no_cache:
        out_file = str(DEFAULT_FRONTIER_CACHE)

    result = fetch_pmc_full_text(
        args.query,
        max_results=args.max,
        years_back=args.years,
        prefer_study_types=not args.no_study_filter,
        output_file=out_file,
    )
    print(result)
