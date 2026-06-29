import hashlib
import re
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image


ALLOWED_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}


def safe_cache_filename(topic, image_url, mime_type):
    extension = ALLOWED_MIME_EXTENSIONS.get(mime_type, ".img")
    digest = hashlib.sha256(f"{topic}|{image_url}".encode("utf-8")).hexdigest()[:24]
    safe_topic = re.sub(r"[^A-Za-z0-9_-]+", "_", topic or "diagram").strip("_")[:48]
    return f"{safe_topic or 'diagram'}_{digest}{extension}"


def download_and_store(candidate, cache_dir, topic, timeout=10):
    mime_type = candidate.mime_type
    if mime_type not in ALLOWED_MIME_EXTENSIONS:
        return None
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    filename = safe_cache_filename(topic, candidate.image_url, mime_type)
    target = cache_path / filename
    if target.exists() and target.stat().st_size > 0:
        return target

    request = Request(candidate.image_url, headers={"User-Agent": "AI-Study-Buddy/1.0"})
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        data = response.read(8 * 1024 * 1024)

    effective_mime = content_type or mime_type
    if effective_mime not in ALLOWED_MIME_EXTENSIONS:
        return None
    if not _valid_image_bytes(data, effective_mime):
        return None

    target.write_bytes(data)
    return target


def _valid_image_bytes(data, mime_type):
    if not data:
        return False
    if mime_type == "image/svg+xml":
        text = data[:200000].decode("utf-8", errors="ignore").lower()
        if "<svg" not in text:
            return False
        blocked = ("<script", "javascript:", " onload=", " onerror=", " onclick=")
        return not any(item in text for item in blocked)
    try:
        from io import BytesIO

        with Image.open(BytesIO(data)) as image:
            image.verify()
        return True
    except Exception:
        return False
