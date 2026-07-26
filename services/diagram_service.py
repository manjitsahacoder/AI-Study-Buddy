"""Diagram cache workflow for generated educational diagrams."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import db
from models import DiagramCache, utc_now
from services import gemini_image_service, storage_service


logger = logging.getLogger(__name__)
_generation_locks = {}
_generation_locks_guard = threading.Lock()


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

    try:
        cached = _find_by_cache_key(database_session, cache_key)
        if cached:
            record_cached_diagram_access(cached, session=database_session)
            _log_diagram_event("cache_hit", cache_key=cache_key, topic=topic)
            _log_diagram_event("diagram_returned", cache_key=cache_key, topic=topic, source="cache")
            return cached.image_url

        _log_diagram_event("cache_miss", cache_key=cache_key, topic=topic)
        with _generation_lock(cache_key):
            cached = _find_by_cache_key(database_session, cache_key)
            if cached:
                record_cached_diagram_access(cached, session=database_session)
                _log_diagram_event("cache_hit", cache_key=cache_key, topic=topic, source="post_lock")
                _log_diagram_event("diagram_returned", cache_key=cache_key, topic=topic, source="cache")
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

            image_bytes = gemini_image_service.generate_diagram_image(prompt)
            _log_diagram_event(
                "image_generated",
                cache_key=cache_key,
                topic=topic,
                image_bytes=len(image_bytes or b""),
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
                model=gemini_image_service._gemini_image_model(),
                session=database_session,
            )
            _log_diagram_event("diagram_returned", cache_key=cache_key, topic=topic, source="generated")
            return diagram.image_url
    except IntegrityError:
        database_session.rollback()
        cached = _find_by_cache_key(database_session, cache_key)
        if cached:
            record_cached_diagram_access(cached, session=database_session)
            _log_diagram_event("cache_hit", cache_key=cache_key, topic=topic, source="integrity_retry")
            _log_diagram_event("diagram_returned", cache_key=cache_key, topic=topic, source="cache")
            return cached.image_url
        logger.exception("Diagram cache insert conflicted but no cached record was found.")
        return None
    except Exception:
        try:
            database_session.rollback()
        except SQLAlchemyError:
            logger.exception("Failed to roll back diagram cache session.")
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


def _upload_diagram_image_with_retry(image_bytes, filename, *, cache_key, topic=None):
    max_attempts = _upload_retry_attempts()
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = storage_service.upload_diagram_image(image_bytes, filename)
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
    raise last_error


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
