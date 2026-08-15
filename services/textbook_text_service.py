"""Extract and persistently cache text from registered textbook PDFs."""

from __future__ import annotations

import logging
import multiprocessing
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from services import textbook_pdf_service, textbook_registry


logger = logging.getLogger(__name__)


def _positive_int_from_environment(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning(
            "textbook_text_configuration_invalid setting=%s value=%r default=%s",
            name,
            raw_value,
            default,
        )
        return default


def _positive_float_from_environment(name: str, default: float) -> float:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw_value)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning(
            "textbook_text_configuration_invalid setting=%s value=%r default=%s",
            name,
            raw_value,
            default,
        )
        return default


TEXTBOOK_TEXT_CACHE_DIR = Path(
    os.environ.get(
        "TEXTBOOK_TEXT_CACHE_DIR",
        Path(__file__).resolve().parent.parent / "instance" / "textbook_text_cache",
    )
)
TEXTBOOK_PDF_MAX_PAGES = _positive_int_from_environment(
    "TEXTBOOK_PDF_MAX_PAGES",
    50,
)
TEXTBOOK_PDF_EXTRACTION_TIMEOUT_SECONDS = _positive_float_from_environment(
    "TEXTBOOK_PDF_EXTRACTION_TIMEOUT_SECONDS",
    10.0,
)

_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


class TextbookPdfExtractionTimeout(TimeoutError):
    """Raised when isolated PDF extraction exceeds its finite deadline."""


def get_textbook_text(
    student_class: Any,
    subject: Any,
    *,
    text_cache_dir: str | os.PathLike[str] | None = None,
    pdf_cache_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return cached or freshly extracted text for a registered textbook."""
    textbook = textbook_registry.get_textbook(student_class, subject)
    if textbook is None:
        _log_extraction_failed(student_class, subject, reason="registry_missing")
        return None

    if not str(textbook.get("pdf_url") or "").strip():
        _log_extraction_failed(student_class, subject, reason="missing_pdf_url")
        return None

    cache_path = build_textbook_text_cache_path(textbook, cache_dir=text_cache_dir)
    return _get_text_from_source(
        cache_path,
        student_class=student_class,
        subject=subject,
        pdf_loader=lambda: textbook_pdf_service.get_textbook_pdf(
            student_class,
            subject,
            cache_dir=pdf_cache_dir,
        ),
    )


def get_chapter_text(
    student_class: Any,
    subject: Any,
    chapter: Any,
    *,
    text_cache_dir: str | os.PathLike[str] | None = None,
    pdf_cache_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return cached or freshly extracted text for one registered chapter."""
    textbook = textbook_registry.get_textbook(student_class, subject)
    chapter_metadata = textbook_registry.get_chapter(student_class, subject, chapter)
    if textbook is None or chapter_metadata is None:
        _log_extraction_failed(
            student_class,
            subject,
            reason="registry_missing",
            event_prefix="textbook_chapter_text",
        )
        return None
    if not str(chapter_metadata.get("pdf_url") or "").strip():
        _log_extraction_failed(
            student_class,
            subject,
            reason="missing_pdf_url",
            event_prefix="textbook_chapter_text",
            chapter_id=chapter_metadata["id"],
        )
        return None

    cache_path = build_chapter_text_cache_path(
        textbook,
        chapter_metadata,
        cache_dir=text_cache_dir,
    )
    return _get_text_from_source(
        cache_path,
        student_class=student_class,
        subject=subject,
        chapter_id=chapter_metadata["id"],
        event_prefix="textbook_chapter_text",
        pdf_loader=lambda: textbook_pdf_service.get_chapter_pdf(
            student_class,
            subject,
            chapter_metadata["number"],
            cache_dir=pdf_cache_dir,
        ),
    )


def _get_text_from_source(
    cache_path: Path,
    *,
    student_class: Any,
    subject: Any,
    pdf_loader,
    event_prefix: str = "textbook_text",
    chapter_id: str | None = None,
) -> str | None:
    """Reuse the isolated extraction pipeline for textbook and chapter sources."""
    cache_key = cache_path.stem.rsplit("_", 1)[-1]
    cached_text, invalid_cache = _read_text_cache(cache_path)
    if cached_text is not None:
        _log_cache_hit(
            student_class,
            subject,
            cache_key,
            event_prefix=event_prefix,
            chapter_id=chapter_id,
        )
        return cached_text
    if invalid_cache:
        _log_cache_invalid(
            student_class,
            subject,
            cache_key,
            event_prefix=event_prefix,
            chapter_id=chapter_id,
        )

    logger.info(
        "%s_cache_miss class=%r subject=%r cache_key=%s%s",
        event_prefix,
        student_class,
        subject,
        cache_key,
        _chapter_log_suffix(chapter_id),
    )

    with _lock_for(cache_path):
        cached_text, invalid_cache_after_lock = _read_text_cache(cache_path)
        if cached_text is not None:
            _log_cache_hit(
                student_class,
                subject,
                cache_key,
                event_prefix=event_prefix,
                chapter_id=chapter_id,
            )
            return cached_text
        if invalid_cache_after_lock:
            if not invalid_cache:
                _log_cache_invalid(
                    student_class,
                    subject,
                    cache_key,
                    event_prefix=event_prefix,
                    chapter_id=chapter_id,
                )
            _remove_invalid_cache(
                cache_path,
                student_class,
                subject,
                cache_key,
                event_prefix=event_prefix,
                chapter_id=chapter_id,
            )

        pdf_path = pdf_loader()
        if pdf_path is None:
            _log_extraction_failed(
                student_class,
                subject,
                reason="pdf_unavailable",
                event_prefix=event_prefix,
                chapter_id=chapter_id,
            )
            return None

        started_at = time.perf_counter()
        logger.info(
            "%s_extraction_started class=%r subject=%r cache_key=%s%s "
            "max_pages=%s timeout_seconds=%s",
            event_prefix,
            student_class,
            subject,
            cache_key,
            _chapter_log_suffix(chapter_id),
            TEXTBOOK_PDF_MAX_PAGES,
            TEXTBOOK_PDF_EXTRACTION_TIMEOUT_SECONDS,
        )
        try:
            extracted_text, extracted_pages, total_pages = (
                _extract_pdf_text_with_timeout(
                    pdf_path,
                    max_pages=TEXTBOOK_PDF_MAX_PAGES,
                    timeout_seconds=TEXTBOOK_PDF_EXTRACTION_TIMEOUT_SECONDS,
                )
            )
        except TextbookPdfExtractionTimeout:
            if event_prefix == "textbook_text":
                logger.warning(
                    "textbook_pdf_extraction_timeout class=%r subject=%r "
                    "cache_key=%s timeout_seconds=%s",
                    student_class,
                    subject,
                    cache_key,
                    TEXTBOOK_PDF_EXTRACTION_TIMEOUT_SECONDS,
                )
            else:
                _log_extraction_failed(
                    student_class,
                    subject,
                    reason="timeout",
                    cache_key=cache_key,
                    event_prefix=event_prefix,
                    chapter_id=chapter_id,
                )
            return None
        except Exception as error:
            _log_extraction_failed(
                student_class,
                subject,
                reason=type(error).__name__,
                cache_key=cache_key,
                event_prefix=event_prefix,
                chapter_id=chapter_id,
            )
            return None

        if total_pages > TEXTBOOK_PDF_MAX_PAGES:
            logger.info(
                "%s_page_limit_reached class=%r subject=%r "
                "cache_key=%s%s total_pages=%s extracted_pages=%s",
                event_prefix,
                student_class,
                subject,
                cache_key,
                _chapter_log_suffix(chapter_id),
                total_pages,
                extracted_pages,
            )

        cleaned_text = clean_extracted_text(extracted_text)
        if not cleaned_text:
            _log_extraction_failed(
                student_class,
                subject,
                reason="empty_text",
                cache_key=cache_key,
                event_prefix=event_prefix,
                chapter_id=chapter_id,
            )
            return None

        try:
            _write_text_cache_atomic(cache_path, cleaned_text)
        except Exception as error:
            _log_extraction_failed(
                student_class,
                subject,
                reason=f"cache_write_{type(error).__name__}",
                cache_key=cache_key,
                event_prefix=event_prefix,
                chapter_id=chapter_id,
            )
            return None

        logger.info(
            "%s_extraction_complete class=%r subject=%r cache_key=%s%s "
            "pages=%s chars=%s duration_ms=%.2f",
            event_prefix,
            student_class,
            subject,
            cache_key,
            _chapter_log_suffix(chapter_id),
            extracted_pages,
            len(cleaned_text),
            (time.perf_counter() - started_at) * 1000,
        )
        return cleaned_text


def build_textbook_text_cache_path(
    textbook: dict[str, Any],
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Build a safe text path using the PDF service's textbook identity."""
    cache_root = Path(cache_dir or TEXTBOOK_TEXT_CACHE_DIR).resolve(strict=False)
    pdf_filename = textbook_pdf_service.build_textbook_cache_path(textbook).stem
    return cache_root / f"{pdf_filename}.txt"


def build_chapter_text_cache_path(
    textbook: dict[str, Any],
    chapter: dict[str, Any],
    *,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Build a safe text path using the chapter PDF identity."""
    cache_root = (
        Path(cache_dir or TEXTBOOK_TEXT_CACHE_DIR).resolve(strict=False) / "chapters"
    )
    pdf_filename = textbook_pdf_service.build_chapter_cache_path(
        textbook,
        chapter,
    ).stem
    return cache_root / f"{pdf_filename}.txt"


def clean_extracted_text(text: Any) -> str:
    """Conservatively normalize extracted text without changing its meaning."""
    normalized = str(text or "").replace("\x00", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[^\S\n]+", " ", normalized)
    normalized = "\n".join(line.strip() for line in normalized.split("\n"))
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _extract_pdf_text_with_pypdf(
    pdf_path: str | os.PathLike[str],
    max_pages: int,
) -> tuple[str, int, int]:
    reader = PdfReader(str(pdf_path), strict=False)
    total_pages = len(reader.pages)
    extracted_pages = min(total_pages, max_pages)
    page_text = []
    for page_index in range(extracted_pages):
        page_text.append(reader.pages[page_index].extract_text() or "")
    return clean_extracted_text("\n\n".join(page_text)), extracted_pages, total_pages


def _extract_pdf_process_worker(
    pdf_path: str,
    max_pages: int,
    result_connection,
) -> None:
    try:
        text, extracted_pages, total_pages = _extract_pdf_text_with_pypdf(
            pdf_path,
            max_pages,
        )
        result_connection.send(("ok", text, extracted_pages, total_pages))
    except Exception as error:
        result_connection.send(
            ("error", type(error).__name__, str(error)[:300])
        )
    finally:
        result_connection.close()


def _extract_pdf_text_with_timeout(
    pdf_path: str | os.PathLike[str],
    *,
    max_pages: int,
    timeout_seconds: float,
) -> tuple[str, int, int]:
    context = multiprocessing.get_context("spawn")
    result_connection, worker_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_extract_pdf_process_worker,
        args=(str(pdf_path), max_pages, worker_connection),
    )
    process.daemon = True
    process_started = False

    try:
        process.start()
        process_started = True
        worker_connection.close()

        if not result_connection.poll(timeout_seconds):
            raise TextbookPdfExtractionTimeout(
                f"pypdf extraction exceeded {timeout_seconds} seconds"
            )

        try:
            result = result_connection.recv()
        except EOFError as error:
            raise RuntimeError("pypdf extraction process returned no result") from error

        if not isinstance(result, tuple) or not result:
            raise RuntimeError("pypdf extraction process returned an invalid result")
        if result[0] == "error":
            error_type = result[1] if len(result) > 1 else "unknown"
            error_message = result[2] if len(result) > 2 else ""
            raise RuntimeError(f"{error_type}: {error_message}")
        if len(result) != 4 or result[0] != "ok":
            raise RuntimeError("pypdf extraction process returned an invalid result")
        return result[1], int(result[2]), int(result[3])
    finally:
        try:
            worker_connection.close()
        except OSError:
            pass
        result_connection.close()
        if process_started:
            process.join(1)
            if process.is_alive():
                process.terminate()
                process.join(1)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(1)
            process.close()


def _read_text_cache(cache_path: Path) -> tuple[str | None, bool]:
    try:
        if cache_path.is_symlink():
            return None, True
        if not cache_path.exists():
            return None, False
        if not cache_path.is_file():
            return None, True
        cache_bytes = cache_path.read_bytes()
        cached_text = cache_bytes.decode("utf-8")
        if not cached_text.strip() or "\x00" in cached_text:
            return None, True
        return cached_text.strip(), False
    except (OSError, UnicodeDecodeError):
        return None, True


def _write_text_cache_atomic(cache_path: Path, text: str) -> None:
    temporary_path: Path | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{cache_path.stem}.",
            suffix=".tmp",
            dir=cache_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, cache_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _remove_invalid_cache(
    cache_path: Path,
    student_class: Any,
    subject: Any,
    cache_key: str,
    *,
    event_prefix: str = "textbook_text",
    chapter_id: str | None = None,
) -> None:
    try:
        if cache_path.exists() or cache_path.is_symlink():
            cache_path.unlink()
    except OSError as error:
        _log_extraction_failed(
            student_class,
            subject,
            reason=f"cache_cleanup_{type(error).__name__}",
            cache_key=cache_key,
            event_prefix=event_prefix,
            chapter_id=chapter_id,
        )


def _lock_for(cache_path: Path) -> threading.Lock:
    lock_key = os.path.normcase(str(cache_path.resolve(strict=False)))
    with _cache_locks_guard:
        return _cache_locks.setdefault(lock_key, threading.Lock())


def _log_cache_hit(
    student_class: Any,
    subject: Any,
    cache_key: str,
    *,
    event_prefix: str = "textbook_text",
    chapter_id: str | None = None,
) -> None:
    logger.info(
        "%s_cache_hit class=%r subject=%r cache_key=%s%s",
        event_prefix,
        student_class,
        subject,
        cache_key,
        _chapter_log_suffix(chapter_id),
    )


def _log_cache_invalid(
    student_class: Any,
    subject: Any,
    cache_key: str,
    *,
    event_prefix: str = "textbook_text",
    chapter_id: str | None = None,
) -> None:
    logger.warning(
        "%s_cache_invalid class=%r subject=%r cache_key=%s%s",
        event_prefix,
        student_class,
        subject,
        cache_key,
        _chapter_log_suffix(chapter_id),
    )


def _log_extraction_failed(
    student_class: Any,
    subject: Any,
    *,
    reason: str,
    cache_key: str = "none",
    event_prefix: str = "textbook_text",
    chapter_id: str | None = None,
) -> None:
    logger.warning(
        "%s_extraction_failed reason=%s class=%r subject=%r cache_key=%s%s",
        event_prefix,
        reason,
        student_class,
        subject,
        cache_key,
        _chapter_log_suffix(chapter_id),
    )


def _chapter_log_suffix(chapter_id: str | None) -> str:
    return f" chapter_id={chapter_id}" if chapter_id else ""


def _clear_cache_locks_for_tests() -> None:
    with _cache_locks_guard:
        _cache_locks.clear()
