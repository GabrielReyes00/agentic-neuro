"""Image processing pipeline for Anki card images.

Handles download, resize, format optimization, and base64 encoding.
All processing uses Pillow — deterministic, no LLM involvement.
"""

from __future__ import annotations

import base64
import hashlib
import io
import math
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageStat

# ── Constants ─────────────────────────────────────────────────────

MAX_WIDTH = 1000  # px — displays at ~500px via CSS, sharp on retina
MAX_HEIGHT = 800  # px — prevent excessively tall images
MAX_FILE_SIZE = 500_000  # 500KB — keeps Anki sync fast
JPEG_QUALITY = 80  # Anki's own default
THUMBNAIL_WIDTH = 300  # for validation previews
MIN_LUMA_STDDEV = 3.0  # reject near-uniform renders (e.g., black rectangles)
MIN_LUMA_ENTROPY = 0.2  # reject pathological low-information images


@dataclass
class ProcessedImage:
    """A fully processed image ready for Anki dispatch."""

    data_b64: str  # base64-encoded image bytes
    filename: str  # e.g. "anki_C003_a1b2c3d4.png"
    format: str  # "png" or "jpeg"
    width: int
    height: int
    file_size: int  # bytes


_TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}


def _retry_delay_seconds(attempt: int, retry_after: Optional[str] = None) -> float:
    """Compute backoff delay, preferring Retry-After when available."""
    if retry_after:
        try:
            return max(0.5, min(float(retry_after), 20.0))
        except (TypeError, ValueError):
            pass
    # Exponential backoff with jitter, bounded for responsiveness
    return min((2.5**attempt) + random.uniform(0.5, 1.5), 45.0)


def download_image(url: str, timeout: int = 15, max_retries: int = 3) -> bytes:
    """Download an image from a URL and return raw bytes.

    Raises:
        ConnectionError: If the download fails.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NeuroAgent/1.0 (AnkiImageSearch)",
            "Accept": "image/*",
        },
    )
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                # If header exists and is clearly not image, fail fast.
                if content_type and not content_type.lower().startswith("image/"):
                    raise ConnectionError(f"URL did not return image content (Content-Type={content_type})")
                return resp.read()
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in _TRANSIENT_HTTP_CODES and attempt < max_retries:
                delay = _retry_delay_seconds(attempt, e.headers.get("Retry-After"))
                if e.code == 429:
                    delay = max(delay, 5.0)
                time.sleep(delay)
                continue
            raise ConnectionError(f"Failed to download image from {url}: HTTP {e.code} ({e.reason})") from e
        except (urllib.error.URLError, OSError, TimeoutError, ConnectionError) as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(_retry_delay_seconds(attempt))
                continue
            break

    raise ConnectionError(f"Failed to download image from {url}: {last_error}") from last_error


def _detect_format(img: Image.Image) -> str:
    """Decide optimal format: PNG for diagrams/transparency, JPEG for photos."""
    # If the image has an alpha channel, must use PNG
    if img.mode in ("RGBA", "LA", "PA"):
        return "png"

    # If the image has very few unique colors, it's likely a diagram → PNG
    # Sample a region to avoid slow full-image analysis on large images
    sample = img.copy()
    sample.thumbnail((200, 200))
    colors = sample.convert("RGB").getcolors(maxcolors=512)
    if colors is not None and len(colors) < 256:
        return "png"

    return "jpeg"


def _resize_to_bounds(img: Image.Image) -> Image.Image:
    """Resize image to fit within MAX_WIDTH x MAX_HEIGHT, preserving aspect ratio."""
    w, h = img.size
    if w <= MAX_WIDTH and h <= MAX_HEIGHT:
        return img

    ratio = min(MAX_WIDTH / w, MAX_HEIGHT / h)
    new_w = int(w * ratio)
    new_h = int(h * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def _compress_to_budget(img: Image.Image, fmt: str) -> tuple[bytes, int, str]:
    """Compress image to fit within MAX_FILE_SIZE.

    For JPEG, progressively reduces quality. For PNG, uses optimize flag.
    Returns (image_bytes, quality_used, final_format).
    """
    buf = io.BytesIO()

    if fmt == "jpeg":
        # Convert to RGB if necessary (JPEG can't handle RGBA)
        if img.mode in ("RGBA", "LA", "PA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        quality = JPEG_QUALITY
        while quality >= 50:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            if buf.tell() <= MAX_FILE_SIZE:
                return buf.getvalue(), quality, "jpeg"
            quality -= 10

        # If still too large at quality 50, resize further
        img = img.resize((int(img.width * 0.75), int(img.height * 0.75)), Image.LANCZOS)
        buf.seek(0)
        buf.truncate()
        img.save(buf, format="JPEG", quality=60, optimize=True)
        return buf.getvalue(), 60, "jpeg"

    else:  # png
        img.save(buf, format="PNG", optimize=True)
        if buf.tell() <= MAX_FILE_SIZE:
            return buf.getvalue(), 0, "png"

        # PNG too large — convert to JPEG as fallback
        return _compress_to_budget(img, "jpeg")


def _validate_visual_quality(img: Image.Image) -> None:
    """Reject blank or near-uniform placeholder images.

    This catches cases where an image URL resolves but returns an all-black
    rectangle or similarly non-informative render.
    """
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    mean_luma = float(stat.mean[0])
    std_luma = float(stat.stddev[0])

    hist = gray.histogram()
    total = float(sum(hist)) or 1.0
    entropy = 0.0
    for count in hist:
        if count:
            p = count / total
            entropy -= p * math.log2(p)

    if std_luma < MIN_LUMA_STDDEV:
        raise ValueError(
            f"Image quality gate failed: low variance (mean={mean_luma:.2f}, std={std_luma:.2f})"
        )

    if entropy < MIN_LUMA_ENTROPY:
        raise ValueError(
            f"Image quality gate failed: low entropy (entropy={entropy:.3f})"
        )


def process_for_anki(
    image_bytes: bytes,
    claim_id: str,
) -> ProcessedImage:
    """Full processing pipeline: open → resize → optimize → encode.

    Args:
        image_bytes: Raw downloaded image bytes.
        claim_id: The claim ID for filename generation.

    Returns:
        ProcessedImage ready for dispatch.
    """
    img = Image.open(io.BytesIO(image_bytes))

    # Resize to fit bounds
    img = _resize_to_bounds(img)

    # Detect optimal format (Pillow's save() drops EXIF by default)
    fmt = _detect_format(img)

    # Compress to budget
    final_bytes, _, final_fmt = _compress_to_budget(img, fmt)

    # Generate collision-free filename
    content_hash = hashlib.md5(final_bytes).hexdigest()[:8]
    ext = "jpg" if final_fmt == "jpeg" else "png"
    filename = f"anki_{claim_id}_{content_hash}.{ext}"

    # Base64 encode
    data_b64 = base64.b64encode(final_bytes).decode("ascii")

    # Report final post-compression dimensions (may differ after fallback resize)
    with Image.open(io.BytesIO(final_bytes)) as final_img:
        _validate_visual_quality(final_img)
        final_width, final_height = final_img.size

    return ProcessedImage(
        data_b64=data_b64,
        filename=filename,
        format=final_fmt,
        width=final_width,
        height=final_height,
        file_size=len(final_bytes),
    )


def make_thumbnail_b64(image_bytes: bytes) -> str:
    """Create a small base64 thumbnail for validation previews.

    Used by the image subagent to show candidates to Claude vision
    without sending full-resolution images.
    """
    img = Image.open(io.BytesIO(image_bytes))
    img.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_WIDTH), Image.LANCZOS)

    buf = io.BytesIO()
    if img.mode in ("RGBA", "LA", "PA"):
        img.save(buf, format="PNG", optimize=True)
    else:
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=70)

    return base64.b64encode(buf.getvalue()).decode("ascii")
