"""Diagram cache workflow for generated educational diagrams."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import db
from models import DiagramCache, utc_now
from services import gemini_image_service, storage_service


logger = logging.getLogger(__name__)
_generation_locks = {}
_generation_locks_guard = threading.Lock()
_diagram_failures = {}
_diagram_failures_guard = threading.Lock()

# Bump this when diagram prompt instructions change so outdated generated
# diagrams miss the cache and are regenerated with the improved prompt.
PROMPT_VERSION = "v1"
MAX_GEMINI_IMAGE_GENERATION_RETRIES = 1
DEFAULT_DIAGRAM_FAILURE_MESSAGE = (
    "The diagram could not be prepared right now. Your lesson is ready, "
    "so please try the diagram again in a moment."
)
DIAGRAM_GENERATION_FAILURE_MESSAGE = (
    "The diagram maker is busy right now. Your lesson is ready, "
    "so please retry the diagram in a moment."
)
UNSUPPORTED_IMAGE_FORMAT_MESSAGE = (
    "The diagram maker returned an image format we cannot display yet. "
    "Please retry the diagram in a moment."
)
STORAGE_UPLOAD_FAILURE_MESSAGE = (
    "The diagram was created, but we could not save it for display. "
    "Please retry the diagram in a moment."
)


class DiagramWorkflowError(RuntimeError):
    """Internal workflow error with a sanitized student-facing message."""

    def __init__(self, failure_code, public_message, original_error):
        super().__init__(public_message)
        self.failure_code = failure_code
        self.public_message = public_message
        self.original_error = original_error


def build_diagram_cache_key(
    *,
    board=None,
    student_class=None,
    subject=None,
    textbook=None,
    chapter=None,
    topic=None,
    language=None,
    diagram_type=None,
):
    """Build a deterministic cache key for diagram lookup."""
    payload = {
        "prompt_version": PROMPT_VERSION,
        # Include the resolved model so diagrams from different image models
        # are never reused accidentally across cache entries.
        "image_model": _normalize_cache_value(gemini_image_service._gemini_image_model()),
        "board": _normalize_cache_value(board, "CBSE"),
        "student_class": _normalize_cache_value(student_class),
        "subject": _normalize_cache_value(subject),
        "textbook": _normalize_cache_value(textbook),
        "chapter": _normalize_cache_value(chapter),
        "topic": _normalize_cache_value(topic),
        "language": _normalize_cache_value(language),
        "diagram_type": _normalize_cache_value(diagram_type),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def find_cached_diagram(
    *,
    board=None,
    student_class=None,
    subject=None,
    textbook=None,
    chapter=None,
    topic=None,
    language=None,
    diagram_type=None,
    prompt=None,
    session=None,
):
    """Return a cached diagram record for the deterministic diagram key."""
    del prompt
    database_session = session or db.session
    cache_key = build_diagram_cache_key(
        board=board,
        student_class=student_class,
        subject=subject,
        textbook=textbook,
        chapter=chapter,
        topic=topic,
        language=language,
        diagram_type=diagram_type,
    )
    return database_session.query(DiagramCache).filter_by(
        cache_key=cache_key
    ).first()


def record_cached_diagram_access(diagram, *, session=None):
    """Increment access metadata for a cached diagram record."""
    if not diagram:
        return None
    database_session = session or db.session
    diagram.access_count = (diagram.access_count or 0) + 1
    diagram.last_accessed = utc_now()
    database_session.commit()
    return diagram


def save_diagram_metadata(
    *,
    cache_key,
    board=None,
    student_class=None,
    subject=None,
    textbook=None,
    chapter=None,
    topic=None,
    prompt,
    public_url,
    storage_path,
    model=None,
    session=None,
):
    """Persist generated diagram metadata and return the new cache record."""
    database_session = session or db.session
    diagram = DiagramCache(
        cache_key=cache_key,
        board=_display_value(board, "CBSE"),
        student_class=_display_value(student_class, "unspecified"),
        subject=_display_value(subject, "unspecified"),
        textbook=_display_value(textbook),
        chapter=_display_value(chapter),
        topic=_display_value(topic, "unspecified"),
        prompt=prompt,
        image_url=public_url,
        storage_path=storage_path,
        model=model or gemini_image_service.DEFAULT_GEMINI_IMAGE_MODEL,
        access_count=0,
    )
    database_session.add(diagram)
    database_session.commit()
    return diagram


def get_or_generate_diagram(
    *,
    board=None,
    student_class=None,
    subject=None,
    textbook=None,
    chapter=None,
    topic=None,
    language=None,
    diagram_type=None,
    session=None,
):
    """Return a cached public diagram URL or generate, upload, and cache one."""
    database_session = session or db.session
    workflow_started_at = time.perf_counter()
    image_model = gemini_image_service._gemini_image_model()
    cache_key = build_diagram_cache_key(
        board=board,
        student_class=student_class,
        subject=subject,
        textbook=textbook,
        chapter=chapter,
        topic=topic,
        language=language,
        diagram_type=diagram_type,
    )
    clear_diagram_failure(cache_key)

    try:
        cache_lookup_started_at = time.perf_counter()
        cached = _find_by_cache_key(database_session, cache_key)
        cache_lookup_duration_ms = _elapsed_ms(cache_lookup_started_at)
        if cached:
            record_cached_diagram_access(cached, session=database_session)
            _log_diagram_event(
                "cache_hit",
                cache_key=cache_key,
                topic=topic,
                duration_ms=cache_lookup_duration_ms,
                image_model=image_model,
            )
            _log_diagram_returned(
                cache_key=cache_key,
                topic=topic,
                source="cache",
                cache_used=True,
                image_model=image_model,
                started_at=workflow_started_at,
            )
            return cached.image_url

        _log_diagram_event(
            "cache_miss",
            cache_key=cache_key,
            topic=topic,
            duration_ms=cache_lookup_duration_ms,
            image_model=image_model,
        )
        with _generation_lock(cache_key):
            cache_lookup_started_at = time.perf_counter()
            cached = _find_by_cache_key(database_session, cache_key)
            cache_lookup_duration_ms = _elapsed_ms(cache_lookup_started_at)
            if cached:
                record_cached_diagram_access(cached, session=database_session)
                _log_diagram_event(
                    "cache_hit",
                    cache_key=cache_key,
                    topic=topic,
                    source="post_lock",
                    duration_ms=cache_lookup_duration_ms,
                    image_model=image_model,
                )
                _log_diagram_returned(
                    cache_key=cache_key,
                    topic=topic,
                    source="cache",
                    cache_used=True,
                    image_model=image_model,
                    started_at=workflow_started_at,
                )
                return cached.image_url

            prompt = gemini_image_service.build_diagram_prompt(
                board,
                student_class,
                subject,
                textbook,
                chapter,
                topic,
            )
            if language:
                prompt = f"{prompt}\n- Label language: {language}."
            if diagram_type:
                prompt = f"{prompt}\n- Diagram type: {diagram_type}."

            generation_started_at = time.perf_counter()
            image_bytes = _generate_diagram_image_with_retry(
                prompt,
                cache_key=cache_key,
                topic=topic,
                image_model=image_model,
            )
            _log_diagram_event(
                "image_generated",
                cache_key=cache_key,
                topic=topic,
                generation_duration_ms=_elapsed_ms(generation_started_at),
                image_bytes=len(image_bytes or b""),
                image_model=image_model,
            )
            upload_result = _upload_diagram_image_with_retry(
                image_bytes,
                _diagram_filename(
                    student_class=student_class,
                    subject=subject,
                    textbook=textbook,
                    chapter=chapter,
                    topic=topic,
                ),
                content_type=getattr(image_bytes, "mime_type", "image/webp"),
                cache_key=cache_key,
                topic=topic,
            )
            diagram = save_diagram_metadata(
                cache_key=cache_key,
                board=board,
                student_class=student_class,
                subject=subject,
                textbook=textbook,
                chapter=chapter,
                topic=topic,
                prompt=prompt,
                public_url=upload_result["public_url"],
                storage_path=upload_result["storage_path"],
                model=image_model,
                session=database_session,
            )
            _log_diagram_returned(
                cache_key=cache_key,
                topic=topic,
                source="generated",
                cache_used=False,
                image_model=image_model,
                started_at=workflow_started_at,
            )
            return diagram.image_url
    except IntegrityError as error:
        database_session.rollback()
        cache_lookup_started_at = time.perf_counter()
        cached = _find_by_cache_key(database_session, cache_key)
        cache_lookup_duration_ms = _elapsed_ms(cache_lookup_started_at)
        if cached:
            record_cached_diagram_access(cached, session=database_session)
            _log_diagram_event(
                "cache_hit",
                cache_key=cache_key,
                topic=topic,
                source="integrity_retry",
                duration_ms=cache_lookup_duration_ms,
                image_model=image_model,
            )
            _log_diagram_returned(
                cache_key=cache_key,
                topic=topic,
                source="cache",
                cache_used=True,
                image_model=image_model,
                started_at=workflow_started_at,
            )
            return cached.image_url
        _log_diagram_failed(
            cache_key=cache_key,
            topic=topic,
            error=error,
            image_model=image_model,
            started_at=workflow_started_at,
        )
        logger.exception("Diagram cache insert conflicted but no cached record was found.")
        return None
    except Exception as error:
        try:
            database_session.rollback()
        except SQLAlchemyError:
            logger.exception("Failed to roll back diagram cache session.")
        _log_diagram_failed(
            cache_key=cache_key,
            topic=topic,
            error=error,
            image_model=image_model,
            started_at=workflow_started_at,
        )
        logger.exception("Diagram generation workflow failed.")
        return None


def _find_by_cache_key(database_session, cache_key):
    return database_session.query(DiagramCache).filter_by(cache_key=cache_key).first()


def _generation_lock(cache_key):
    with _generation_locks_guard:
        lock = _generation_locks.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _generation_locks[cache_key] = lock
        return lock


def _upload_diagram_image_with_retry(image_bytes, filename, *, content_type="image/webp", cache_key, topic=None):
    max_attempts = _upload_retry_attempts()
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = storage_service.upload_diagram_image(
                image_bytes,
                filename,
                content_type=content_type,
            )
            _log_diagram_event(
                "upload_complete",
                cache_key=cache_key,
                topic=topic,
                attempt=attempt,
                storage_path=result.get("storage_path", ""),
            )
            return result
        except Exception as error:
            last_error = error
            logger.warning(
                "diagram_workflow event=upload_failed cache_key=%s topic=%s attempt=%s max_attempts=%s error=%s",
                cache_key,
                topic or "",
                attempt,
                max_attempts,
                error,
                exc_info=True,
            )
    raise DiagramWorkflowError(
        "storage_upload_failed",
        STORAGE_UPLOAD_FAILURE_MESSAGE,
        last_error,
    ) from last_error


def _generate_diagram_image_with_retry(prompt, *, cache_key, topic=None, image_model=""):
    attempts = MAX_GEMINI_IMAGE_GENERATION_RETRIES + 1
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return gemini_image_service.generate_diagram_image(prompt)
        except Exception as error:
            last_error = error
            retry_reason = _temporary_generation_failure_reason(error)
            if not retry_reason or attempt >= attempts:
                if attempt > 1:
                    _log_diagram_event(
                        "image_generation_retry_failed",
                        cache_key=cache_key,
                        topic=topic,
                        attempt=attempt,
                        retry_reason=retry_reason or "non_retryable",
                        image_model=image_model,
                    )
                raise _diagram_generation_workflow_error(error) from error
            _log_diagram_event(
                "image_generation_retry_attempted",
                cache_key=cache_key,
                topic=topic,
                attempt=attempt + 1,
                retry_reason=retry_reason,
                image_model=image_model,
            )
    raise last_error


def _temporary_generation_failure_reason(error):
    if isinstance(error, gemini_image_service.GeminiImageTimeoutError):
        return "timeout"
    if isinstance(error, (ValueError, gemini_image_service.GeminiImageConfigurationError)):
        return ""

    combined = f"{type(error).__name__} {error}".lower()
    if "unsupported image mime" in combined or "supported image mime" in combined:
        return ""
    if any(term in combined for term in ("invalid request", "invalid argument", "bad request", "400")):
        return ""
    if any(term in combined for term in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(term in combined for term in ("429", "rate limit", "ratelimit", "resource_exhausted")):
        return "rate_limit"
    if any(
        term in combined
        for term in (
            "500",
            "502",
            "503",
            "504",
            "server error",
            "internal error",
            "temporarily unavailable",
            "service unavailable",
        )
    ):
        return "temporary_server_error"
    return ""


def _diagram_generation_workflow_error(error):
    if _unsupported_image_format_error(error):
        return DiagramWorkflowError(
            "unsupported_image_format",
            UNSUPPORTED_IMAGE_FORMAT_MESSAGE,
            error,
        )
    return DiagramWorkflowError(
        "generation_failed",
        DIAGRAM_GENERATION_FAILURE_MESSAGE,
        error,
    )


def _unsupported_image_format_error(error):
    combined = f"{type(error).__name__} {error}".lower()
    return "unsupported image mime" in combined or "supported image mime" in combined


def diagram_failure_for_cache_key(cache_key):
    with _diagram_failures_guard:
        failure = _diagram_failures.get(cache_key)
        return dict(failure) if failure else {}


def clear_diagram_failure(cache_key):
    with _diagram_failures_guard:
        _diagram_failures.pop(cache_key, None)


def default_diagram_failure_message():
    return DEFAULT_DIAGRAM_FAILURE_MESSAGE


def _upload_retry_attempts():
    raw_attempts = os.environ.get("DIAGRAM_UPLOAD_RETRY_ATTEMPTS", "2")
    try:
        attempts = int(raw_attempts)
    except (TypeError, ValueError):
        attempts = 2
    return max(1, attempts)


def _log_diagram_event(event, **fields):
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("diagram_workflow event=%s %s", event, details)


def _log_diagram_returned(*, cache_key, topic=None, source, cache_used, image_model, started_at):
    _log_diagram_event(
        "diagram_returned",
        cache_key=cache_key,
        topic=topic,
        source=source,
        cache_used=str(bool(cache_used)).lower(),
        duration_ms=_elapsed_ms(started_at),
        image_model=image_model,
    )


def _log_diagram_failed(*, cache_key, topic=None, error=None, image_model, started_at):
    failure = _diagram_failure_payload(error)
    with _diagram_failures_guard:
        _diagram_failures[cache_key] = failure
    _log_diagram_event(
        "diagram_failed",
        cache_key=cache_key,
        topic=topic,
        cache_used="false",
        failure_code=failure["code"],
        duration_ms=_elapsed_ms(started_at),
        image_model=image_model,
    )


def _diagram_failure_payload(error):
    if isinstance(error, DiagramWorkflowError):
        return {
            "code": error.failure_code,
            "message": error.public_message,
        }
    return {
        "code": "diagram_generation_unavailable",
        "message": DEFAULT_DIAGRAM_FAILURE_MESSAGE,
    }


def _elapsed_ms(started_at):
    return round((time.perf_counter() - started_at) * 1000, 2)


def _diagram_filename(*, student_class=None, subject=None, textbook=None, chapter=None, topic=None):
    return "/".join(
        (
            _display_value(student_class, "unknown"),
            _display_value(subject, "unknown-subject"),
            _display_value(textbook, "unknown-textbook"),
            _display_value(chapter, "unknown-chapter"),
            f"{_display_value(topic, 'diagram')}.webp",
        )
    )


def _normalize_cache_value(value, default=""):
    text = str(value or default or "").strip().casefold()
    return " ".join(text.split())


def _display_value(value, default=""):
    return str(value or default or "").strip()
