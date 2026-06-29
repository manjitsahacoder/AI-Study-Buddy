import hashlib
import re
from pathlib import Path
from urllib.request import Request, urlopen

from PIL import Image


MAX_IMAGE_BYTES = 8 * 1024 * 1024

ALLOWED_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
}

PIL_FORMAT_MIME = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}


def safe_cache_filename(topic, image_url, mime_type):
    extension = ALLOWED_MIME_EXTENSIONS.get(mime_type, ".img")
    digest = hashlib.sha256(f"{topic}|{image_url}".encode("utf-8")).hexdigest()[:24]
    safe_topic = re.sub(r"[^A-Za-z0-9_-]+", "_", topic or "diagram").strip("_")[:48]
    return f"{safe_topic or 'diagram'}_{digest}{extension}"


def download_and_store(candidate, cache_dir, topic, timeout=10):
    candidate_mime = _normalize_mime(candidate.mime_type)
    if candidate_mime not in ALLOWED_MIME_EXTENSIONS:
        return None
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    cached = existing_cached_target(cache_path, topic, candidate.image_url)
    if cached:
        return cached

    request = Request(candidate.image_url, headers={"User-Agent": "AI-Study-Buddy/1.0"})
    with urlopen(request, timeout=timeout) as response:
        content_type = _normalize_mime(response.headers.get("Content-Type", ""))
        data = response.read(MAX_IMAGE_BYTES + 1)

    if len(data) > MAX_IMAGE_BYTES:
        return None

    effective_mime = detect_image_mime(data) or content_type or candidate_mime
    if effective_mime not in ALLOWED_MIME_EXTENSIONS:
        return None
    if not _valid_image_bytes(data, effective_mime):
        return None

    filename = safe_cache_filename(topic, candidate.image_url, effective_mime)
    target = cache_path / filename
    target.write_bytes(data)
    return target


def existing_cached_target(cache_path, topic, image_url):
    for mime_type in ALLOWED_MIME_EXTENSIONS:
        target = Path(cache_path) / safe_cache_filename(topic, image_url, mime_type)
        if valid_cached_image(target):
            return target
    return None


def valid_cached_image(path):
    path = Path(path)
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    actual_mime = detect_image_mime(data)
    if not actual_mime:
        return False
    return path.suffix.lower() in _extensions_for_mime(actual_mime)


def repair_cached_image_extension(static_folder, image_path):
    static_root = Path(static_folder)
    path = static_root / image_path
    if valid_cached_image(path):
        return image_path
    if not path.exists() or path.stat().st_size <= 0:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    actual_mime = detect_image_mime(data)
    if not actual_mime:
        return None
    extension = ALLOWED_MIME_EXTENSIONS[actual_mime]
    repaired_path = path.with_suffix(extension)
    if repaired_path != path:
        if repaired_path.exists() and valid_cached_image(repaired_path):
            return repaired_path.relative_to(static_root).as_posix()
        try:
            path.replace(repaired_path)
        except OSError:
            return None
    return repaired_path.relative_to(static_root).as_posix()


def detect_image_mime(data):
    if not data:
        return None
    text = data[:512].decode("utf-8", errors="ignore").lower()
    if "<svg" in text:
        return "image/svg+xml"
    try:
        from io import BytesIO

        with Image.open(BytesIO(data)) as image:
            return PIL_FORMAT_MIME.get((image.format or "").upper())
    except Exception:
        return None


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


def _normalize_mime(value):
    return str(value or "").split(";")[0].strip().lower()


def _extensions_for_mime(mime_type):
    extension = ALLOWED_MIME_EXTENSIONS.get(mime_type)
    if mime_type in {"image/jpeg", "image/jpg"}:
        return {".jpg", ".jpeg"}
    return {extension} if extension else set()
