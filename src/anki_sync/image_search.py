"""Image search clients for Anki card enrichment.

Primary source: Wikimedia Commons (reliable, well-indexed, broad medical coverage).
Secondary source: Open-i / NIH NLM (best-effort — may fail on systems with older SSL).

Smart routing augments search queries based on image_type to get the best
results from Wikimedia Commons for all categories (anatomy, radiology,
histology, surgical). Open-i is attempted as fallback for clinical image
types when Wikimedia returns insufficient results.
"""

from __future__ import annotations

import json
import re
import time
from html import unescape
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class ImageCandidate:
    """A candidate image returned from search."""

    url: str  # direct image URL
    thumbnail_url: str  # smaller preview URL
    title: str  # descriptive title / filename
    source: Literal["wikimedia", "openi"]
    license: str  # e.g. "CC-BY-SA 4.0", "Open Access"
    width: int = 0
    height: int = 0
    description: str = ""
    attribution: str = ""


# ── Query augmentation by image type ──────────────────────────────

_TYPE_QUERY_HINTS: dict[str, list[str]] = {
    "anatomy_diagram": ["anatomy", "diagram", "labeled"],
    "schematic": ["diagram", "schematic", "illustration"],
    "radiology": ["medical imaging", "radiograph"],
    "histology": ["histology", "microscopy", "pathology"],
    "surgical_photo": ["surgery", "intraoperative", "medical"],
}

# Image types where Open-i is worth trying as fallback
_OPENI_TYPES = {"radiology", "histology", "surgical_photo"}

_QUERY_STOPWORDS = {
    "and", "the", "for", "with", "from", "into", "without", "after", "before",
    "this", "that", "image", "images", "view", "labeled", "diagram", "illustration",
}

_MEDICAL_STRONG_TERMS = {
    "brain", "cerebral", "intracranial", "neuro", "neur", "angiogram", "angiography",
    "arteriovenous", "aneurysm", "hemorrhage", "haemorrhage", "vascular", "dural",
    "cortical", "venous", "arterial", "mri", "ct", "histology", "pathology", "surgical",
    "fistula", "malformation", "cavernous", "willis", "avm", "avf", "davf",
}

_NEGATIVE_CONTEXT_TERMS = {
    "postcard", "highway", "freeway", "road", "street", "station", "rail", "trolley",
    "boston", "city", "bridge", "traffic", "map of",
}

_TYPE_RELEVANCE_HINTS = {
    "anatomy_diagram": {"brain", "cerebral", "artery", "arteries", "anatomy"},
    "schematic": {"diagram", "schematic", "illustration", "classification", "pathway"},
    "radiology": {"mri", "ct", "angiography", "angiogram", "scan", "avm", "avf", "davf"},
    "histology": {"histology", "microscopy", "stain", "pathology"},
    "surgical_photo": {"surgery", "operative", "intraoperative"},
}


def _augment_query(query: str, image_type: str) -> str:
    """Add category-specific hint terms to improve Wikimedia search relevance."""
    hints = _TYPE_QUERY_HINTS.get(image_type, [])
    if not hints:
        return query
    # Only add hints not already present in the query
    lower_q = query.lower()
    extras = [h for h in hints if h.lower() not in lower_q]
    if extras:
        return f"{query} {' '.join(extras[:2])}"
    return query


def _clean_text(text: str) -> str:
    """Strip HTML tags and normalize whitespace for relevance filtering."""
    if not text:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(no_tags)).strip().lower()


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _is_relevant_candidate(query: str, image_type: str, title: str, description: str) -> bool:
    """Heuristic filter to suppress common non-medical Wikimedia false positives."""
    text = _clean_text(f"{title} {description}")
    if not text:
        return False
    if any(term in text for term in _NEGATIVE_CONTEXT_TERMS):
        return False

    query_tokens = [
        t for t in re.findall(r"[a-z0-9]+", query.lower())
        if len(t) >= 4 and t not in _QUERY_STOPWORDS
    ]
    text_tokens = _tokenize(text)
    overlap = sum(1 for t in query_tokens if t in text_tokens)

    strong_hits = sum(1 for term in _MEDICAL_STRONG_TERMS if term in text)
    type_hits = sum(1 for term in _TYPE_RELEVANCE_HINTS.get(image_type, set()) if term in text)

    if overlap >= 2:
        return True
    if overlap >= 1 and (strong_hits >= 2 or type_hits >= 1):
        return True

    query_has_medical_anchor = any(t in _MEDICAL_STRONG_TERMS for t in query_tokens)
    if query_has_medical_anchor and (strong_hits >= 2 or type_hits >= 1):
        return True

    return False


# ── Wikimedia Commons search ──────────────────────────────────────

_WIKI_API = "https://commons.wikimedia.org/w/api.php"


def _wiki_request(params: dict, timeout: int = 10) -> dict:
    """Make a GET request to the MediaWiki API."""
    params.setdefault("format", "json")
    params.setdefault("origin", "*")
    url = f"{_WIKI_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "NeuroAgent/1.0 (AnkiImageSearch)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_wikimedia(query: str, max_results: int = 5, image_type: Optional[str] = None) -> list[ImageCandidate]:
    """Search Wikimedia Commons for images matching a query.

    Uses the MediaWiki search API with image-info props to get
    direct file URLs and metadata.
    """
    search_params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",  # File namespace
        "gsrlimit": str(max_results + 3),  # fetch extra to account for non-image filtering
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata|mime",
        "iiurlwidth": "1200",  # request a larger rendered thumbnail (useful for SVG)
    }

    try:
        data = _wiki_request(search_params)
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return []

    candidates: list[ImageCandidate] = []
    for page in pages.values():
        info_list = page.get("imageinfo", [])
        if not info_list:
            continue
        info = info_list[0]

        # Skip non-image MIME types (e.g., SVG without rasterization, PDF)
        mime = info.get("mime", "")
        if not mime.startswith("image/"):
            continue
        # Skip tiny images (icons, badges)
        width = info.get("width", 0)
        height = info.get("height", 0)
        if width < 200 or height < 150:
            continue

        # Prefer rendered thumbnail URLs whenever available.
        # This reduces bandwidth/rate-limit pressure and is sufficient for Anki's <=1000px pipeline.
        original_url = info.get("url", "")
        thumb_url = info.get("thumburl", original_url)
        image_url = thumb_url or original_url

        # Extract metadata
        extmeta = info.get("extmetadata", {})
        license_short = extmeta.get("LicenseShortName", {}).get("value", "Unknown")
        description = extmeta.get("ImageDescription", {}).get("value", "")
        artist = extmeta.get("Artist", {}).get("value", "")

        # Build attribution
        title = page.get("title", "").replace("File:", "")
        if not _is_relevant_candidate(query, image_type or "", title, description):
            continue
        attribution = title
        if artist:
            artist_clean = re.sub(r"<[^>]+>", "", artist).strip()
            if artist_clean:
                attribution = artist_clean
        attribution += f" | Wikimedia Commons, {license_short}"

        candidates.append(ImageCandidate(
            url=image_url,
            thumbnail_url=thumb_url,
            title=title,
            source="wikimedia",
            license=license_short,
            width=width,
            height=height,
            description=description[:300] if description else "",
            attribution=attribution,
        ))

        if len(candidates) >= max_results:
            break

    return candidates


# ── Open-i (NIH/NLM) search ──────────────────────────────────────

_OPENI_API = "https://openi.nlm.nih.gov/api/search"
_OPENI_LAST_ERROR: Optional[str] = None


def search_openi(query: str, max_results: int = 5) -> list[ImageCandidate]:
    """Search the Open-i biomedical image database (best-effort).

    Open-i provides clinical images, radiology, histology, and
    figures from PubMed Central open-access articles.

    Note: May fail on systems with older SSL/TLS libraries (LibreSSL < 3.x).
    Returns empty list on any connection failure — caller should fall back.
    """
    global _OPENI_LAST_ERROR
    params = {
        "query": query,
        "it": "xg,pg",  # x-ray/radiograph, photograph
        "m": "1",  # start at result 1
        "n": str(max_results),
    }
    url = f"{_OPENI_API}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NeuroAgent/1.0 (AnkiImageSearch)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _OPENI_LAST_ERROR = None
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
        # SSL handshake failures, timeouts, etc. — graceful degradation
        _OPENI_LAST_ERROR = str(e)
        return []

    results = data.get("list", [])
    if not results:
        return []

    candidates: list[ImageCandidate] = []
    for item in results:
        img_large = item.get("imgLarge", "")
        img_thumb = item.get("imgThumb", "")

        if not img_large:
            continue

        # Open-i URLs are relative — prepend the base
        base = "https://openi.nlm.nih.gov"
        if img_large.startswith("/"):
            img_large = base + img_large
        if img_thumb and img_thumb.startswith("/"):
            img_thumb = base + img_thumb

        title = item.get("title", "")[:200]
        caption = item.get("caption", "")[:300]
        journal = item.get("journal", {})
        journal_name = journal if isinstance(journal, str) else journal.get("value", "")

        attribution = "Open-i / NLM"
        if journal_name:
            attribution += f" | {journal_name}"
        attribution += " | Open Access"

        candidates.append(ImageCandidate(
            url=img_large,
            thumbnail_url=img_thumb or img_large,
            title=title,
            source="openi",
            license="Open Access (NLM)",
            description=caption,
            attribution=attribution,
        ))

    return candidates


# ── Unified search entry point ────────────────────────────────────


def search_images(
    image_type: str,
    search_queries: list[str],
    max_results: int = 5,
) -> tuple[list[ImageCandidate], str]:
    """Smart-routed image search.

    Tries each search query individually on Wikimedia Commons (most specific
    first), stopping as soon as we get enough results. Wikimedia's search
    engine works best with shorter, more natural queries rather than long
    concatenated keyword strings.

    For clinical image types (radiology, histology, surgical), attempts
    Open-i as fallback if Wikimedia returns insufficient results.

    Returns (candidates, source_used).
    """
    all_candidates: list[ImageCandidate] = []
    seen_urls: set[str] = set()

    api_calls = 0
    for query in search_queries:
        for q in (_augment_query(query, image_type), query):
            if api_calls > 0:
                time.sleep(0.5)  # pacing between Wikimedia API calls
            results = search_wikimedia(q, max_results=max_results, image_type=image_type)
            api_calls += 1
            for c in results:
                if c.url not in seen_urls:
                    seen_urls.add(c.url)
                    all_candidates.append(c)
            if len(all_candidates) >= max_results:
                return all_candidates[:max_results], "wikimedia"

    if all_candidates:
        return all_candidates[:max_results], "wikimedia"

    # For clinical types, try Open-i as last resort
    if image_type in _OPENI_TYPES:
        combined = " ".join(search_queries[:2])
        candidates = search_openi(combined, max_results=max_results)
        if candidates:
            return candidates, "openi"
        if _OPENI_LAST_ERROR:
            return [], "openi_unavailable"

    return [], "none"


def fallback_search(
    search_queries: list[str],
    primary_source: str,
    image_type: Optional[str] = None,
    max_results: int = 5,
) -> list[ImageCandidate]:
    """Search the OTHER source if the primary returned insufficient candidates."""
    combined_query = " ".join(search_queries[:2])

    if primary_source != "openi":
        # Try Open-i (best-effort — may return empty due to SSL)
        results = search_openi(combined_query, max_results=max_results)
        if results:
            return results

    if primary_source != "wikimedia":
        return search_wikimedia(combined_query, max_results=max_results, image_type=image_type)

    return []
