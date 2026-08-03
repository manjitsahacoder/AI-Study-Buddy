"""Read-only NCERT textbook metadata registry."""

from __future__ import annotations

import json
import logging
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "ncert_textbooks.json"
REQUIRED_TEXTBOOK_FIELDS = {
    "board",
    "class",
    "subject",
    "title",
    "pdf_url",
    "language",
    "version",
}

_registry_cache: dict[str, dict[str, dict[str, Any]]] | None = None
_registry_lock = threading.Lock()


class TextbookRegistryError(ValueError):
    """Raised internally when the registry file cannot be used."""


def get_textbook(student_class: Any, subject: Any) -> dict[str, Any] | None:
    """Return textbook metadata for a class and subject, or None if unsupported."""
    registry = _get_registry()
    class_key = _normalize_class(student_class)
    subject_key = _normalize_subject(subject)
    if not class_key or not subject_key:
        _log_unsupported_request(student_class, subject)
        return None

    class_books = registry.get(class_key)
    if not class_books:
        _log_unsupported_request(student_class, subject)
        return None

    canonical_subject = _subject_lookup(class_books).get(subject_key)
    if not canonical_subject:
        _log_unsupported_request(student_class, subject)
        return None

    return deepcopy(class_books[canonical_subject])


def has_textbook(student_class: Any, subject: Any) -> bool:
    """Return True when the registry supports the requested class and subject."""
    return get_textbook(student_class, subject) is not None


def supported_classes() -> list[int]:
    """Return the class levels currently listed in the registry."""
    classes = []
    for class_key in _get_registry():
        try:
            classes.append(int(class_key))
        except (TypeError, ValueError):
            continue
    return sorted(classes)


def supported_subjects(student_class: Any) -> list[str]:
    """Return supported subject names for a class, or an empty list if unsupported."""
    registry = _get_registry()
    class_key = _normalize_class(student_class)
    if not class_key or class_key not in registry:
        _log_unsupported_request(student_class, None)
        return []
    return sorted(registry[class_key])


def _get_registry() -> dict[str, dict[str, dict[str, Any]]]:
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache

    with _registry_lock:
        if _registry_cache is None:
            _registry_cache = _load_registry(REGISTRY_PATH)
    return _registry_cache


def _load_registry(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    try:
        registry = _read_registry_json(path)
        validated_registry = _validate_registry(registry)
    except TextbookRegistryError as error:
        logger.error("invalid NCERT textbook registry: %s", error)
        return {}

    textbook_count = sum(len(subjects) for subjects in validated_registry.values())
    logger.info(
        "NCERT textbook registry loaded from %s with %s entries",
        path,
        textbook_count,
    )
    return validated_registry


def _read_registry_json(path: Path) -> Any:
    duplicate_keys: list[str] = []

    def object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen = set()
        result = {}
        for key, value in pairs:
            if key in seen:
                duplicate_keys.append(str(key))
            seen.add(key)
            result[key] = value
        return result

    try:
        with path.open("r", encoding="utf-8") as registry_file:
            registry = json.load(registry_file, object_pairs_hook=object_pairs_hook)
    except (OSError, json.JSONDecodeError) as error:
        raise TextbookRegistryError(str(error)) from error

    if duplicate_keys:
        duplicates = ", ".join(sorted(set(duplicate_keys)))
        raise TextbookRegistryError(f"duplicate registry key(s): {duplicates}")

    return registry


def _validate_registry(registry: Any) -> dict[str, dict[str, dict[str, Any]]]:
    if not isinstance(registry, dict) or not registry:
        raise TextbookRegistryError("registry must be a non-empty object")

    validated: dict[str, dict[str, dict[str, Any]]] = {}
    for class_key, subjects in registry.items():
        normalized_class = _normalize_class(class_key)
        if not normalized_class:
            raise TextbookRegistryError(f"invalid class key: {class_key!r}")
        if normalized_class in validated:
            raise TextbookRegistryError(f"duplicate class entry: {normalized_class}")
        if not isinstance(subjects, dict) or not subjects:
            raise TextbookRegistryError(f"class {class_key!r} must contain subjects")

        validated_subjects: dict[str, dict[str, Any]] = {}
        normalized_subjects = set()
        for subject_key, metadata in subjects.items():
            normalized_subject = _normalize_subject(subject_key)
            if not normalized_subject:
                raise TextbookRegistryError(
                    f"class {class_key!r} has an invalid subject key"
                )
            if normalized_subject in normalized_subjects:
                raise TextbookRegistryError(
                    f"class {class_key!r} has duplicate subject {subject_key!r}"
                )
            normalized_subjects.add(normalized_subject)
            _validate_textbook_metadata(
                normalized_class,
                normalized_subject,
                subject_key,
                metadata,
            )
            validated_subjects[str(subject_key).strip()] = dict(metadata)

        validated[normalized_class] = validated_subjects

    return validated


def _validate_textbook_metadata(
    class_key: str,
    normalized_subject: str,
    subject_key: Any,
    metadata: Any,
) -> None:
    if not isinstance(metadata, dict):
        raise TextbookRegistryError(
            f"class {class_key!r} subject {subject_key!r} metadata must be an object"
        )

    missing_fields = REQUIRED_TEXTBOOK_FIELDS - set(metadata)
    if missing_fields:
        missing = ", ".join(sorted(missing_fields))
        raise TextbookRegistryError(
            f"class {class_key!r} subject {subject_key!r} is missing {missing}"
        )

    if metadata.get("class") != int(class_key):
        raise TextbookRegistryError(
            f"class {class_key!r} subject {subject_key!r} has mismatched class"
        )

    metadata_subject = _normalize_subject(metadata.get("subject"))
    if metadata_subject != normalized_subject:
        raise TextbookRegistryError(
            f"class {class_key!r} subject {subject_key!r} has mismatched subject"
        )

    for field in REQUIRED_TEXTBOOK_FIELDS - {"class"}:
        if not isinstance(metadata.get(field), str) or not metadata.get(field).strip():
            raise TextbookRegistryError(
                f"class {class_key!r} subject {subject_key!r} has invalid {field}"
            )


def _subject_lookup(class_books: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {_normalize_subject(subject): subject for subject in class_books}


def _normalize_class(value: Any) -> str:
    class_text = str(value or "").strip()
    if not class_text.isdigit():
        return ""
    return str(int(class_text))


def _normalize_subject(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _log_unsupported_request(student_class: Any, subject: Any) -> None:
    logger.info(
        "unsupported NCERT textbook request: class=%r subject=%r",
        student_class,
        subject,
    )


def _clear_registry_cache_for_tests() -> None:
    global _registry_cache
    with _registry_lock:
        _registry_cache = None
