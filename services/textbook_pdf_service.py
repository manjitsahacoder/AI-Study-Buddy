"""Download and persistently cache PDFs referenced by the textbook registry."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from services import textbook_registry


logger = logging.getLogger(__name__)

TEXTBOOK_PDF_CACHE_DIR = (
    Path(__file__).resolve().parent.parent / "instance" / "textbook_pdf_cache"
)
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 30
DOWNLOAD_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
DOWNLOAD_CHUNK_SIZE = 64 * 1024
PDF_SIGNATURE = b"%PDF-"

_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


def get_textbook_pdf(
    student_class: Any,
    subject: Any,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Return a cached textbook PDF, downloading it when necessary.

    The existing registry remains the source of truth. Failures at the registry,
    URL, filesystem, or network boundary are logged and returned as ``None``.
    """
    textbook = textbook_registry.get_textbook(student_class, subject)
    if textbook is None:
        logger.info(
            "textbook_pdf_download_failed reason=registry_missing class=%r subject=%r",
            student_class,
            subject,
        )
        return None

    pdf_url = str(textbook.get("pdf_url") or "").strip()
    url_issue = _url_issue(pdf_url)
    if url_issue:
        logger.info(
            "textbook_pdf_download_failed reason=%s class=%r subject=%r",
            url_issue,
            student_class,
            subject,
        )
        return None

    cache_path = build_textbook_cache_path(textbook, cache_dir=cache_dir)
    cache_key = cache_path.stem.rsplit("_", 1)[-1]
    if _is_valid_pdf(cache_path):
        _log_cache_hit(student_class, subject, cache_key)
        return cache_path

    logger.info(
        "textbook_pdf_cache_miss class=%r subject=%r cache_key=%s",
        student_class,
        subject,
        cache_key,
    )

    with _lock_for(cache_path):
        if _is_valid_pdf(cache_path):
            _log_cache_hit(student_class, subject, cache_key)
            return cache_path

        _remove_invalid_cache_file(cache_path, student_class, subject, cache_key)
        return _download_pdf(
            pdf_url,
            cache_path,
            student_class=student_class,
            subject=subject,
            cache_key=cache_key,
        )


def build_textbook_cache_path(
    textbook: dict[str, Any],
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Build a deterministic, traversal-safe cache path for textbook metadata."""
    cache_root = Path(cache_dir or TEXTBOOK_PDF_CACHE_DIR).resolve(strict=False)
    class_slug = _safe_slug(textbook.get("class"), "unknown", maximum_length=16)
    subject_slug = _safe_slug(
        textbook.get("subject"), "unknown-subject", maximum_length=32
    )
    title_slug = _safe_slug(
        textbook.get("title"), "unknown-textbook", maximum_length=48
    )
    cache_key = _metadata_cache_key(textbook)[:16]
    filename = f"class_{class_slug}_{subject_slug}_{title_slug}_{cache_key}.pdf"
    return cache_root / filename


def _download_pdf(
    pdf_url: str,
    cache_path: Path,
    *,
    student_class: Any,
    subject: Any,
    cache_key: str,
) -> Path | None:
    temporary_path: Path | None = None
    safe_url = _safe_url_for_log(pdf_url)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(
            "textbook_pdf_download_started class=%r subject=%r cache_key=%s url=%s",
            student_class,
            subject,
            cache_key,
            safe_url,
        )
        with requests.get(
            pdf_url,
            stream=True,
            timeout=DOWNLOAD_TIMEOUT,
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            temporary_path, bytes_written, signature = _stream_to_temporary_file(
                response,
                cache_path,
            )

        if bytes_written == 0:
            _log_invalid_response(
                student_class,
                subject,
                cache_key,
                reason="empty",
                content_type=content_type,
            )
            return None

        if signature != PDF_SIGNATURE:
            _log_invalid_response(
                student_class,
                subject,
                cache_key,
                reason="non_pdf",
                content_type=content_type,
            )
            return None

        os.replace(temporary_path, cache_path)
        temporary_path = None
        logger.info(
            "textbook_pdf_download_complete class=%r subject=%r cache_key=%s bytes=%s",
            student_class,
            subject,
            cache_key,
            bytes_written,
        )
        return cache_path
    except Exception as error:
        logger.warning(
            "textbook_pdf_download_failed reason=%s class=%r subject=%r "
            "cache_key=%s url=%s",
            type(error).__name__,
            student_class,
            subject,
            cache_key,
            safe_url,
        )
        return None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError as error:
                logger.warning(
                    "textbook_pdf_download_failed reason=temp_cleanup_%s class=%r "
                    "subject=%r cache_key=%s",
                    type(error).__name__,
                    student_class,
                    subject,
                    cache_key,
                )


def _stream_to_temporary_file(response: requests.Response, cache_path: Path):
    signature = bytearray()
    bytes_written = 0
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=f".{cache_path.stem}.",
        suffix=".tmp",
        dir=cache_path.parent,
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
        try:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                if len(signature) < len(PDF_SIGNATURE):
                    signature.extend(chunk[: len(PDF_SIGNATURE) - len(signature)])
                temporary_file.write(chunk)
                bytes_written += len(chunk)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        except Exception:
            temporary_file.close()
            temporary_path.unlink(missing_ok=True)
            raise

    return temporary_path, bytes_written, bytes(signature)


def _metadata_cache_key(textbook: dict[str, Any]) -> str:
    key_fields = {
        field: textbook.get(field)
        for field in (
            "board",
            "class",
            "subject",
            "title",
            "pdf_url",
            "language",
            "version",
        )
    }
    canonical_metadata = json.dumps(
        key_fields,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical_metadata.encode("utf-8")).hexdigest()


def _safe_slug(value: Any, default: str, *, maximum_length: int) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:maximum_length].strip("-") or default)


def _url_issue(pdf_url: str) -> str | None:
    if not pdf_url:
        return "missing_url"

    lowered_url = pdf_url.lower()
    if (
        lowered_url.startswith("placeholder:")
        or lowered_url in {"placeholder", "todo", "tbd", "n/a", "none"}
        or any(character in pdf_url for character in "{}<>")
    ):
        return "placeholder_url"

    try:
        parsed_url = urlsplit(pdf_url)
        port = parsed_url.port
    except ValueError:
        return "invalid_url"

    placeholder_hosts = {
        "example.com",
        "www.example.com",
        "example.org",
        "www.example.org",
        "example.net",
        "www.example.net",
    }
    if parsed_url.hostname and parsed_url.hostname.lower() in placeholder_hosts:
        return "placeholder_url"
    if (
        parsed_url.scheme.lower() not in {"http", "https"}
        or not parsed_url.hostname
        or (port is None and parsed_url.netloc.endswith(":"))
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        return "invalid_url"
    return None


def _safe_url_for_log(pdf_url: str) -> str:
    try:
        parsed_url = urlsplit(pdf_url)
        hostname = parsed_url.hostname or ""
        if parsed_url.port is not None:
            hostname = f"{hostname}:{parsed_url.port}"
        return urlunsplit((parsed_url.scheme, hostname, parsed_url.path, "", ""))
    except ValueError:
        return "<invalid-url>"


def _is_valid_pdf(cache_path: Path) -> bool:
    try:
        if cache_path.is_symlink() or not cache_path.is_file():
            return False
        if cache_path.stat().st_size == 0:
            return False
        with cache_path.open("rb") as cached_pdf:
            return cached_pdf.read(len(PDF_SIGNATURE)) == PDF_SIGNATURE
    except OSError:
        return False


def _remove_invalid_cache_file(
    cache_path: Path,
    student_class: Any,
    subject: Any,
    cache_key: str,
) -> None:
    try:
        if cache_path.exists() or cache_path.is_symlink():
            cache_path.unlink()
            _log_invalid_response(
                student_class,
                subject,
                cache_key,
                reason="invalid_cached_file",
                content_type="",
            )
    except OSError as error:
        logger.warning(
            "textbook_pdf_download_failed reason=cache_cleanup_%s class=%r "
            "subject=%r cache_key=%s",
            type(error).__name__,
            student_class,
            subject,
            cache_key,
        )


def _lock_for(cache_path: Path) -> threading.Lock:
    lock_key = os.path.normcase(str(cache_path.resolve(strict=False)))
    with _cache_locks_guard:
        return _cache_locks.setdefault(lock_key, threading.Lock())


def _log_cache_hit(student_class: Any, subject: Any, cache_key: str) -> None:
    logger.info(
        "textbook_pdf_cache_hit class=%r subject=%r cache_key=%s",
        student_class,
        subject,
        cache_key,
    )


def _log_invalid_response(
    student_class: Any,
    subject: Any,
    cache_key: str,
    *,
    reason: str,
    content_type: str,
) -> None:
    logger.warning(
        "textbook_pdf_invalid_response reason=%s class=%r subject=%r "
        "cache_key=%s content_type=%r",
        reason,
        student_class,
        subject,
        cache_key,
        content_type,
    )


def _clear_cache_locks_for_tests() -> None:
    with _cache_locks_guard:
        _cache_locks.clear()
