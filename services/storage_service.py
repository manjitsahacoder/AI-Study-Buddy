"""Supabase Storage helpers for generated diagram images."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen


DIAGRAM_BUCKET = "diagrams"
DEFAULT_SEGMENTS = {
    "class": "unknown",
    "subject": "unknown-subject",
    "textbook": "unknown-textbook",
    "chapter": "unknown-chapter",
    "topic": "diagram",
}


class SupabaseStorageConfigurationError(RuntimeError):
    """Raised when Supabase Storage environment configuration is incomplete."""


def upload_diagram_image(image_bytes, filename):
    """Upload a diagram image to Supabase Storage and return its path and public URL."""
    storage_path = build_diagram_storage_path(filename)
    client = _storage_client()
    client.upload(
        DIAGRAM_BUCKET,
        storage_path,
        image_bytes,
        content_type="image/webp",
        upsert=True,
    )
    return {
        "storage_path": storage_path,
        "public_url": get_public_diagram_url(storage_path),
    }


def delete_diagram_image(storage_path):
    """Delete a diagram image from Supabase Storage."""
    normalized_path = normalize_storage_path(storage_path)
    _storage_client().delete(DIAGRAM_BUCKET, normalized_path)
    return None


def get_public_diagram_url(storage_path):
    """Return the public URL for a diagram stored in the configured Supabase project."""
    supabase_url = _supabase_url()
    normalized_path = normalize_storage_path(storage_path)
    return (
        f"{supabase_url}/storage/v1/object/public/"
        f"{DIAGRAM_BUCKET}/{quote(normalized_path, safe='/')}"
    )


def build_diagram_storage_path(filename):
    """Build class/subject/textbook/chapter/topic.webp storage paths from filename."""
    parts = _filename_parts(filename)
    if len(parts) >= 5:
        class_part, subject, textbook, chapter, topic = parts[-5:]
    else:
        padded = [DEFAULT_SEGMENTS["class"], DEFAULT_SEGMENTS["subject"], DEFAULT_SEGMENTS["textbook"], DEFAULT_SEGMENTS["chapter"]]
        class_part, subject, textbook, chapter, topic = (padded + parts)[-5:]

    return "/".join(
        (
            sanitize_class_segment(class_part),
            sanitize_path_segment(subject, DEFAULT_SEGMENTS["subject"]),
            sanitize_path_segment(textbook, DEFAULT_SEGMENTS["textbook"]),
            sanitize_path_segment(chapter, DEFAULT_SEGMENTS["chapter"]),
            f"{sanitize_path_segment(PurePosixPath(topic).stem, DEFAULT_SEGMENTS['topic'])}.webp",
        )
    )


def normalize_storage_path(storage_path):
    """Normalize a storage path and reject empty or unsafe traversal paths."""
    parts = _filename_parts(storage_path)
    if not parts:
        raise ValueError("storage_path is required")

    normalized_parts = []
    for index, part in enumerate(parts):
        if index == 0:
            normalized_parts.append(sanitize_class_segment(part))
        elif index == len(parts) - 1:
            path_part = PurePosixPath(part)
            suffix = path_part.suffix.lower()
            if suffix and re.fullmatch(r"\.[a-z0-9]+", suffix):
                normalized_parts.append(
                    f"{sanitize_path_segment(path_part.stem, 'diagram')}{suffix}"
                )
            else:
                normalized_parts.append(sanitize_path_segment(part, "diagram"))
        else:
            normalized_parts.append(sanitize_path_segment(part, "diagram"))

    return "/".join(normalized_parts)


def sanitize_class_segment(value):
    cleaned = sanitize_path_segment(value, DEFAULT_SEGMENTS["class"])
    class_value = re.sub(r"^class[-_]*", "", cleaned).strip("-_")
    if not class_value:
        class_value = DEFAULT_SEGMENTS["class"]
    return f"class_{class_value}"


def sanitize_path_segment(value, default):
    """Return a URL/path safe ASCII segment."""
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or default


def _filename_parts(filename):
    text = str(filename or "").replace("\\", "/")
    parts = []
    for part in PurePosixPath(text).parts:
        if part in {"", ".", "/", ".."}:
            continue
        parts.append(part)
    return parts


def _storage_client():
    return SupabaseStorageClient.from_environment()


def _supabase_url():
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if not supabase_url:
        raise SupabaseStorageConfigurationError("SUPABASE_URL is required.")
    return supabase_url


def _supabase_key():
    for variable in (
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_KEY",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
    ):
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    raise SupabaseStorageConfigurationError("A Supabase API key is required.")


def _storage_object_url(supabase_url, bucket, storage_path):
    return f"{supabase_url}/storage/v1/object/{bucket}/{quote(storage_path, safe='/')}"


@dataclass
class SupabaseStorageClient:
    supabase_url: str
    api_key: str

    @classmethod
    def from_environment(cls):
        return cls(supabase_url=_supabase_url(), api_key=_supabase_key())

    def upload(self, bucket, storage_path, image_bytes, *, content_type, upsert=True):
        if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("image_bytes must be bytes-like")

        request = Request(
            _storage_object_url(self.supabase_url, bucket, storage_path),
            data=bytes(image_bytes),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "apikey": self.api_key,
                "Content-Type": content_type,
                "x-upsert": "true" if upsert else "false",
            },
        )
        with urlopen(request, timeout=30) as response:
            response.read()

    def delete(self, bucket, storage_path):
        request = Request(
            f"{self.supabase_url}/storage/v1/object/{bucket}",
            data=json.dumps({"prefixes": [storage_path]}).encode("utf-8"),
            method="DELETE",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "apikey": self.api_key,
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:
            response.read()
