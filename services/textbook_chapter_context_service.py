"""Isolated, page-aware chapter context for configured NCERT textbooks."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services import textbook_pdf_service, textbook_registry, textbook_text_service


logger = logging.getLogger(__name__)

# Retained as a compatibility alias for the original Class 10 implementation.
# Runtime cache validation always uses the selected textbook configuration.
PARSER_VERSION = "class10-science-page-boundaries-v1"
COMBINED_BOOK_SOURCE = "combined_book"
INDIVIDUAL_CHAPTER_SOURCE = "individual_chapter_pdf"


def _positive_int_from_environment(name: str, default: int) -> int:
    raw_value = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw_value)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning(
            "textbook_chapter_context_configuration_invalid setting=%s value=%r default=%s",
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
            "textbook_chapter_context_configuration_invalid setting=%s value=%r default=%s",
            name,
            raw_value,
            default,
        )
        return default


TEXTBOOK_CHAPTER_CONTEXT_CACHE_DIR = Path(
    os.environ.get(
        "TEXTBOOK_CHAPTER_CONTEXT_CACHE_DIR",
        Path(__file__).resolve().parent.parent
        / "instance"
        / "textbook_chapter_context_cache",
    )
)
TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS = _positive_int_from_environment(
    "TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS",
    24_000,
)
TEXTBOOK_CHAPTER_CONTEXT_MAX_PAGES = _positive_int_from_environment(
    "TEXTBOOK_CHAPTER_CONTEXT_MAX_PAGES",
    300,
)
TEXTBOOK_CHAPTER_CONTEXT_EXTRACTION_TIMEOUT_SECONDS = _positive_float_from_environment(
    "TEXTBOOK_CHAPTER_CONTEXT_EXTRACTION_TIMEOUT_SECONDS",
    30.0,
)


@dataclass(frozen=True)
class _ChapterDefinition:
    number: int
    title: str
    aliases: tuple[str, ...] = ()

    @property
    def identifier(self) -> str:
        return f"chapter-{self.number:02d}"


CLASS_10_SCIENCE_CHAPTERS = (
    _ChapterDefinition(1, "Chemical Reactions and Equations"),
    _ChapterDefinition(2, "Acids, Bases and Salts"),
    _ChapterDefinition(3, "Metals and Non-metals"),
    _ChapterDefinition(4, "Carbon and its Compounds"),
    _ChapterDefinition(5, "Life Processes"),
    _ChapterDefinition(6, "Control and Coordination"),
    _ChapterDefinition(7, "How do Organisms Reproduce?"),
    _ChapterDefinition(8, "Heredity", ("Heredity and Evolution",)),
    _ChapterDefinition(9, "Light – Reflection and Refraction"),
    _ChapterDefinition(10, "The Human Eye and the Colourful World"),
    _ChapterDefinition(11, "Electricity"),
    _ChapterDefinition(12, "Magnetic Effects of Electric Current"),
    _ChapterDefinition(13, "Our Environment"),
)


# The titles below are transcribed from the official Contents page in the
# Class 9 Exploration preliminary PDF (iesc1ps.pdf), First Edition April 2026.
CLASS_9_SCIENCE_CHAPTERS = (
    _ChapterDefinition(
        1,
        "Exploration: Entering the World of Secondary Science",
        ("Entering the World of Secondary Science",),
    ),
    _ChapterDefinition(2, "Cell: The Building Block of Life"),
    _ChapterDefinition(3, "Tissues in Action"),
    _ChapterDefinition(4, "Describing Motion Around Us"),
    _ChapterDefinition(5, "Exploring Mixtures and their Separation"),
    _ChapterDefinition(6, "How Forces Affect Motion"),
    _ChapterDefinition(7, "Work, Energy, and Simple Machines"),
    _ChapterDefinition(8, "Journey Inside the Atom"),
    _ChapterDefinition(9, "Atomic Foundations of Matter"),
    _ChapterDefinition(10, "Sound Waves: Characteristics and Applications"),
    _ChapterDefinition(11, "Reproduction: How Life Continues"),
    _ChapterDefinition(12, "Patterns in Life: Diversity and Classification"),
    _ChapterDefinition(13, "Earth as a System: Energy, Matter, and Life"),
)


@dataclass(frozen=True)
class _TextbookChapterConfiguration:
    """The deliberately small, reviewed set of textbooks this service can parse."""

    student_class: int
    subject: str
    title: str
    pdf_url: str
    parser_version: str
    cache_slug: str
    chapters: tuple[_ChapterDefinition, ...]
    source_strategy: str


CLASS_10_SCIENCE_CONFIGURATION = _TextbookChapterConfiguration(
    student_class=10,
    subject="Science",
    title="Science",
    pdf_url="https://ncert.nic.in/textbook/pdf/jesc1ps.pdf",
    parser_version=PARSER_VERSION,
    cache_slug="class_10_science",
    chapters=CLASS_10_SCIENCE_CHAPTERS,
    source_strategy=COMBINED_BOOK_SOURCE,
)
CLASS_9_SCIENCE_CONFIGURATION = _TextbookChapterConfiguration(
    student_class=9,
    subject="Science",
    title="Exploration",
    pdf_url="https://ncert.nic.in/textbook/pdf/iesc1ps.pdf",
    parser_version="class9-exploration-chapter-pdf-v2",
    cache_slug="class_9_science_exploration",
    chapters=CLASS_9_SCIENCE_CHAPTERS,
    source_strategy=INDIVIDUAL_CHAPTER_SOURCE,
)
TEXTBOOK_CHAPTER_CONFIGURATIONS = (
    CLASS_10_SCIENCE_CONFIGURATION,
    CLASS_9_SCIENCE_CONFIGURATION,
)

_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


def get_chapter_context(
    student_class: Any,
    subject: Any,
    chapter: Any,
    *,
    cache_dir: str | os.PathLike[str] | None = None,
    pdf_cache_dir: str | os.PathLike[str] | None = None,
    page_cache_dir: str | os.PathLike[str] | None = None,
    max_chars: int | None = None,
) -> dict[str, Any] | None:
    """Return a bounded, validated context for one configured textbook chapter.

    This service is intentionally isolated from lesson generation.  It only uses
    the Milestone 2 registry/PDF cache and the shared isolated pypdf extractor.
    """
    textbook = textbook_registry.get_textbook(student_class, subject)
    configuration = _configuration_for_textbook(textbook)
    definition = _resolve_chapter_definition(chapter, configuration)
    requested_chapter = str(chapter or "").strip()
    if configuration is None or definition is None:
        _log_unavailable(
            student_class,
            subject,
            definition.identifier if definition else None,
            reason="unsupported_request",
        )
        return None

    chapter_metadata = None
    source_pdf_url = str(textbook.get("pdf_url") or "").strip()
    if configuration.source_strategy == INDIVIDUAL_CHAPTER_SOURCE:
        chapter_metadata = textbook_registry.get_chapter(
            configuration.student_class,
            configuration.subject,
            definition.number,
        )
        if not _chapter_metadata_matches_definition(
            chapter_metadata,
            definition,
            configuration,
        ):
            _log_unavailable(
                student_class,
                subject,
                definition.identifier,
                reason="chapter_metadata_unavailable",
            )
            return None
        source_pdf_url = str(chapter_metadata["pdf_url"]).strip()

    character_limit = _resolve_character_limit(max_chars)
    cache_path = build_chapter_context_cache_path(
        textbook,
        definition,
        configuration=configuration,
        source_pdf_url=source_pdf_url,
        character_limit=character_limit,
        cache_dir=cache_dir,
    )
    cache_key = cache_path.stem.rsplit("_", 1)[-1]
    cached_context, invalid_cache = _read_context_cache(
        cache_path,
        textbook,
        definition,
        configuration,
        source_pdf_url=source_pdf_url,
        character_limit=character_limit,
    )
    if cached_context is not None:
        logger.info(
            "textbook_chapter_context_cache_hit class=%s subject=%r chapter_id=%s cache_key=%s",
            configuration.student_class,
            configuration.subject,
            definition.identifier,
            cache_key,
        )
        return _with_requested_chapter(cached_context, requested_chapter)

    if invalid_cache:
        _remove_invalid_cache(cache_path, cache_key, definition.identifier)
    logger.info(
        "textbook_chapter_context_cache_miss class=%s subject=%r chapter_id=%s cache_key=%s",
        configuration.student_class,
        configuration.subject,
        definition.identifier,
        cache_key,
    )

    with _lock_for(cache_path):
        cached_context, invalid_cache_after_lock = _read_context_cache(
            cache_path,
            textbook,
            definition,
            configuration,
            source_pdf_url=source_pdf_url,
            character_limit=character_limit,
        )
        if cached_context is not None:
            logger.info(
                "textbook_chapter_context_cache_hit class=%s subject=%r chapter_id=%s cache_key=%s",
                configuration.student_class,
                configuration.subject,
                definition.identifier,
                cache_key,
            )
            return _with_requested_chapter(cached_context, requested_chapter)
        if invalid_cache_after_lock:
            _remove_invalid_cache(cache_path, cache_key, definition.identifier)

        if configuration.source_strategy == INDIVIDUAL_CHAPTER_SOURCE:
            extracted_pages = textbook_text_service.get_chapter_pages(
                configuration.student_class,
                configuration.subject,
                definition.number,
                page_cache_dir=page_cache_dir,
                pdf_cache_dir=pdf_cache_dir,
                max_pages=TEXTBOOK_CHAPTER_CONTEXT_MAX_PAGES,
                timeout_seconds=TEXTBOOK_CHAPTER_CONTEXT_EXTRACTION_TIMEOUT_SECONDS,
            )
            if extracted_pages is None:
                _log_unavailable(
                    student_class,
                    subject,
                    definition.identifier,
                    reason="chapter_pdf_unavailable",
                    cache_key=cache_key,
                )
                return None
            page_texts, total_pages = extracted_pages
        else:
            pdf_path = textbook_pdf_service.get_textbook_pdf(
                configuration.student_class,
                configuration.subject,
                cache_dir=pdf_cache_dir,
            )
            if pdf_path is None:
                _log_unavailable(
                    student_class,
                    subject,
                    definition.identifier,
                    reason="pdf_unavailable",
                    cache_key=cache_key,
                )
                return None

            try:
                page_texts, total_pages = textbook_text_service.extract_pdf_pages_with_timeout(
                    pdf_path,
                    max_pages=TEXTBOOK_CHAPTER_CONTEXT_MAX_PAGES,
                    timeout_seconds=TEXTBOOK_CHAPTER_CONTEXT_EXTRACTION_TIMEOUT_SECONDS,
                )
            except Exception as error:
                _log_unavailable(
                    student_class,
                    subject,
                    definition.identifier,
                    reason=f"page_extraction_{type(error).__name__}",
                    cache_key=cache_key,
                )
                return None

        if total_pages > TEXTBOOK_CHAPTER_CONTEXT_MAX_PAGES:
            _log_unavailable(
                student_class,
                subject,
                definition.identifier,
                reason="page_limit_reached",
                cache_key=cache_key,
            )
            return None

        cleaned_pages = _clean_page_texts(page_texts, configuration.chapters)
        boundary = (
            _locate_individual_chapter_pdf_boundary(
                [textbook_text_service.clean_extracted_text(page) for page in page_texts],
                definition,
            )
            if configuration.source_strategy == INDIVIDUAL_CHAPTER_SOURCE
            else _locate_chapter_boundaries(
                cleaned_pages,
                definition,
                configuration.chapters,
            )
        )
        if boundary is None:
            _log_unavailable(
                student_class,
                subject,
                definition.identifier,
                reason="boundary_unavailable",
                cache_key=cache_key,
            )
            return None

        start_page_index, end_page_index, match = boundary
        selected_pages = [
            {"page_index": page_index, "text": cleaned_pages[page_index]}
            for page_index in range(start_page_index, end_page_index + 1)
            if cleaned_pages[page_index]
        ]
        chapter_text = _join_page_texts(selected_pages)
        if not chapter_text:
            _log_unavailable(
                student_class,
                subject,
                definition.identifier,
                reason="empty_chapter_text",
                cache_key=cache_key,
            )
            return None

        bounded_text, truncated = _truncate_at_safe_boundary(
            chapter_text,
            character_limit,
        )
        if not bounded_text:
            _log_unavailable(
                student_class,
                subject,
                definition.identifier,
                reason="empty_bounded_text",
                cache_key=cache_key,
            )
            return None

        context = {
            "cache_version": configuration.parser_version,
            "textbook_id": _textbook_identity(textbook),
            "pdf_url": source_pdf_url,
            "source_strategy": configuration.source_strategy,
            "chapter_id": definition.identifier,
            "requested_chapter": requested_chapter,
            "matched_chapter_title": definition.title,
            "normalized_matched_chapter_title": _normalize_title(definition.title),
            "start_page_index": start_page_index,
            "end_page_index": end_page_index,
            "page_texts": selected_pages,
            "text": bounded_text,
            "truncated": truncated,
            "max_chars": character_limit,
            "match": match,
        }
        try:
            _write_context_cache_atomic(cache_path, context)
        except OSError as error:
            _log_unavailable(
                student_class,
                subject,
                definition.identifier,
                reason=f"cache_write_{type(error).__name__}",
                cache_key=cache_key,
            )
            return None

        logger.info(
            "textbook_chapter_context_boundary_match class=%s subject=%r chapter_id=%s "
            "start_page=%s end_page=%s confidence=%s",
            configuration.student_class,
            configuration.subject,
            definition.identifier,
            start_page_index,
            end_page_index,
            match["confidence"],
        )
        if truncated:
            logger.info(
                "textbook_chapter_context_truncated class=%s subject=%r chapter_id=%s "
                "cache_key=%s max_chars=%s",
                configuration.student_class,
                configuration.subject,
                definition.identifier,
                cache_key,
                character_limit,
            )
        logger.info(
            "textbook_chapter_context_extraction_complete class=%s subject=%r chapter_id=%s "
            "pages=%s chars=%s cache_key=%s",
            configuration.student_class,
            configuration.subject,
            definition.identifier,
            len(selected_pages),
            len(bounded_text),
            cache_key,
        )
        return context


def build_chapter_context_cache_path(
    textbook: dict[str, Any],
    definition: _ChapterDefinition,
    *,
    configuration: _TextbookChapterConfiguration | None = None,
    source_pdf_url: str | None = None,
    character_limit: int,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Return a deterministic, traversal-safe chapter-context JSON cache path."""
    configuration = configuration or _configuration_for_textbook(textbook)
    if configuration is None:
        raise ValueError("chapter context cache requested for an unconfigured textbook")
    source_pdf_url = str(source_pdf_url or textbook.get("pdf_url") or "").strip()
    if not source_pdf_url:
        raise ValueError("chapter context cache requested without a source PDF URL")
    cache_root = Path(cache_dir or TEXTBOOK_CHAPTER_CONTEXT_CACHE_DIR).resolve(
        strict=False
    )
    cache_identity = {
        "textbook_id": _textbook_identity(textbook),
        "pdf_url": source_pdf_url,
        "chapter_id": definition.identifier,
        "chapter_title": definition.title,
        "parser_version": configuration.parser_version,
        "max_chars": character_limit,
    }
    cache_key = hashlib.sha256(
        json.dumps(
            cache_identity,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return cache_root / f"{configuration.cache_slug}_{definition.identifier}_{cache_key}.json"


def _resolve_chapter_definition(
    chapter: Any,
    configuration: _TextbookChapterConfiguration | None,
) -> _ChapterDefinition | None:
    if configuration is None:
        return None
    chapter_number = _chapter_number(chapter)
    if chapter_number is not None:
        return next(
            (
                definition
                for definition in configuration.chapters
                if definition.number == chapter_number
            ),
            None,
        )

    normalized_request = _normalize_title(_strip_chapter_prefix(str(chapter or "")))
    if not normalized_request:
        return None
    for definition in configuration.chapters:
        candidates = (definition.title, *definition.aliases)
        if normalized_request in {_normalize_title(candidate) for candidate in candidates}:
            return definition
    return None


def _chapter_number(chapter: Any) -> int | None:
    if isinstance(chapter, int) and not isinstance(chapter, bool):
        return chapter if chapter > 0 else None
    match = re.fullmatch(r"\s*(?:chapter\s*)?(\d{1,2})\s*", str(chapter or ""), re.I)
    return int(match.group(1)) if match else None


def _configuration_for_textbook(
    textbook: dict[str, Any] | None,
) -> _TextbookChapterConfiguration | None:
    if not textbook:
        return None
    return next(
        (
            configuration
            for configuration in TEXTBOOK_CHAPTER_CONFIGURATIONS
            if textbook.get("class") == configuration.student_class
            and textbook.get("subject") == configuration.subject
            and textbook.get("title") == configuration.title
            and textbook.get("pdf_url") == configuration.pdf_url
        ),
        None,
    )


def _chapter_metadata_matches_definition(
    chapter_metadata: dict[str, Any] | None,
    definition: _ChapterDefinition,
    configuration: _TextbookChapterConfiguration,
) -> bool:
    """Accept only the registry chapter matching this configured identity."""
    if not isinstance(chapter_metadata, dict):
        return False
    source_url = str(chapter_metadata.get("pdf_url") or "").strip()
    return bool(
        chapter_metadata.get("id") == definition.identifier
        and chapter_metadata.get("number") == definition.number
        and _normalize_title(chapter_metadata.get("title"))
        == _normalize_title(definition.title)
        and source_url
        and source_url != configuration.pdf_url
    )


def _clean_page_texts(
    page_texts: list[str],
    chapters: tuple[_ChapterDefinition, ...],
) -> list[str]:
    pages = [textbook_text_service.clean_extracted_text(page) for page in page_texts]
    repeated_edge_lines: dict[str, int] = {}
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        for line in (lines[:1] + lines[-1:]):
            normalized = _normalize_title(line)
            if normalized:
                repeated_edge_lines[normalized] = repeated_edge_lines.get(normalized, 0) + 1

    cleaned_pages = []
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        if lines and _is_removable_running_line(lines[0], repeated_edge_lines, chapters):
            lines.pop(0)
        if lines and _is_removable_running_line(lines[-1], repeated_edge_lines, chapters):
            lines.pop()
        cleaned_pages.append("\n".join(lines).strip())
    return cleaned_pages


def _is_removable_running_line(
    line: str,
    counts: dict[str, int],
    chapters: tuple[_ChapterDefinition, ...],
) -> bool:
    normalized = _normalize_title(line)
    if counts.get(normalized, 0) < 2:
        return False
    if re.fullmatch(r"\d+", line.strip()):
        return True
    if normalized in {_normalize_title(definition.title) for definition in chapters}:
        return False
    return not re.fullmatch(r"chapter\s*\d+", line.strip(), re.I)


def _locate_chapter_boundaries(
    pages: list[str],
    definition: _ChapterDefinition,
    chapters: tuple[_ChapterDefinition, ...],
) -> tuple[int, int, dict[str, Any]] | None:
    start_match = _find_validated_heading(pages, definition, start_page_index=0)
    if start_match is None:
        return None
    start_page_index, heading_line_index = start_match

    next_definition = next(
        (
            item
            for item in chapters
            if item.number == definition.number + 1
        ),
        None,
    )
    next_match = (
        _find_validated_heading(
            pages,
            next_definition,
            start_page_index=start_page_index + 1,
        )
        if next_definition is not None
        else None
    )
    if next_definition is not None and next_match is None:
        return None

    end_page_index = next_match[0] - 1 if next_match is not None else len(pages) - 1
    if end_page_index < start_page_index:
        return None
    return (
        start_page_index,
        end_page_index,
        {
            "method": "validated_page_heading",
            "confidence": "high",
            "heading_page_index": start_page_index,
            "heading_line_index": heading_line_index,
            "next_heading_page_index": next_match[0] if next_match else None,
        },
    )


def _locate_individual_chapter_pdf_boundary(
    pages: list[str],
    definition: _ChapterDefinition,
) -> tuple[int, int, dict[str, Any]] | None:
    """Validate an individual NCERT chapter PDF without scanning for a successor."""
    heading_match = _find_standalone_chapter_heading(pages, definition)
    if heading_match is None:
        return None
    heading_page_index, heading_line_index = heading_match
    return (
        0,
        len(pages) - 1,
        {
            "method": "validated_standalone_chapter_pdf_heading",
            "confidence": "high",
            "heading_page_index": heading_page_index,
            "heading_line_index": heading_line_index,
            "next_heading_page_index": None,
        },
    )


def _find_standalone_chapter_heading(
    pages: list[str],
    definition: _ChapterDefinition,
) -> tuple[int, int] | None:
    """Find the expected number and title together near an individual PDF's start."""
    expected_title = _normalize_title(definition.title)
    for page_index, page in enumerate(pages[:2]):
        lines = [line.strip() for line in page.splitlines() if line.strip()][:100]
        if not lines or _looks_like_contents_page(lines):
            continue
        for line_index in range(len(lines)):
            for title_line_count in range(1, 5):
                title_lines = lines[line_index : line_index + title_line_count]
                if _normalize_title(" ".join(title_lines)) != expected_title:
                    continue
                if _has_expected_chapter_number_near_title(
                    lines,
                    title_start=line_index,
                    title_end=line_index + title_line_count,
                    chapter_number=definition.number,
                ):
                    return page_index, line_index
    return None


def _has_expected_chapter_number_near_title(
    lines: list[str],
    *,
    title_start: int,
    title_end: int,
    chapter_number: int,
) -> bool:
    start = max(0, title_start - 6)
    end = min(len(lines), title_end + 6)
    for line_index in range(start, end):
        line = lines[line_index]
        if re.fullmatch(rf"chapter\s*{chapter_number}\s*[:.\-â€“â€”]?", line, re.I):
            return True
        if (
            re.fullmatch(r"chapter\s*[:.\-â€“â€”]?", line, re.I)
            and line_index + 1 < len(lines)
            and re.fullmatch(rf"{chapter_number}\s*[:.\-â€“â€”]?", lines[line_index + 1])
        ):
            return True
    return False


def _find_validated_heading(
    pages: list[str],
    definition: _ChapterDefinition,
    *,
    start_page_index: int,
) -> tuple[int, int] | None:
    expected_title = _normalize_title(definition.title)
    for page_index in range(start_page_index, len(pages)):
        lines = [line.strip() for line in pages[page_index].splitlines() if line.strip()]
        if _looks_like_contents_page(lines):
            continue
        for line_index, line in enumerate(lines[:12]):
            if not re.fullmatch(rf"chapter\s*{definition.number}\s*[:.\-–—]?", line, re.I):
                continue
            for title_line_count in range(1, 4):
                title_lines = lines[
                    line_index + 1 : line_index + 1 + title_line_count
                ]
                if _normalize_title(" ".join(title_lines)) != expected_title:
                    continue
                body_lines = lines[line_index + 1 + title_line_count :]
                if body_lines and any(
                    not re.fullmatch(r"\d+", body_line) for body_line in body_lines
                ):
                    return page_index, line_index
    return None


def _looks_like_contents_page(lines: list[str]) -> bool:
    first_lines = lines[:15]
    normalized_first_lines = [_normalize_title(line) for line in first_lines]
    if "contents" in normalized_first_lines:
        return True
    chapter_marker_count = sum(
        bool(re.fullmatch(r"chapter\s*\d+", line, re.I)) for line in first_lines
    )
    return chapter_marker_count >= 3


def _join_page_texts(page_texts: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[PDF page {page['page_index']}]\n{page['text']}" for page in page_texts
    ).strip()


def _truncate_at_safe_boundary(text: str, maximum_characters: int) -> tuple[str, bool]:
    if len(text) <= maximum_characters:
        return text, False
    search_start = max(0, int(maximum_characters * 0.75))
    for delimiter in ("\n\n", "\n", " "):
        boundary = text.rfind(delimiter, search_start, maximum_characters + 1)
        if boundary >= search_start:
            return text[:boundary].rstrip(), True
    return text[:maximum_characters].rstrip(), True


def _resolve_character_limit(max_chars: int | None) -> int:
    if isinstance(max_chars, int) and not isinstance(max_chars, bool) and max_chars > 0:
        return max_chars
    return TEXTBOOK_CHAPTER_CONTEXT_MAX_CHARS


def _normalize_title(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _strip_chapter_prefix(value: str) -> str:
    return re.sub(r"^\s*chapter\s*\d+\s*[:.\-–—]?\s*", "", value, flags=re.I)


def _textbook_identity(textbook: dict[str, Any]) -> str:
    fields = (
        textbook.get("board"),
        textbook.get("class"),
        textbook.get("subject"),
        textbook.get("title"),
        textbook.get("language"),
        textbook.get("version"),
    )
    return "-".join(_safe_identity_part(field) for field in fields)


def _safe_identity_part(value: Any) -> str:
    return _normalize_title(value).replace(" ", "-") or "unknown"


def _read_context_cache(
    cache_path: Path,
    textbook: dict[str, Any],
    definition: _ChapterDefinition,
    configuration: _TextbookChapterConfiguration,
    *,
    source_pdf_url: str,
    character_limit: int,
) -> tuple[dict[str, Any] | None, bool]:
    try:
        if cache_path.is_symlink() or not cache_path.exists():
            return None, cache_path.is_symlink()
        if not cache_path.is_file():
            return None, True
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, True
    if not isinstance(payload, dict):
        return None, True
    text = payload.get("text")
    page_texts = payload.get("page_texts")
    start_page_index = payload.get("start_page_index")
    end_page_index = payload.get("end_page_index")
    if (
        payload.get("cache_version") != configuration.parser_version
        or payload.get("textbook_id") != _textbook_identity(textbook)
        or payload.get("pdf_url") != source_pdf_url
        or payload.get("source_strategy", COMBINED_BOOK_SOURCE)
        != configuration.source_strategy
        or payload.get("chapter_id") != definition.identifier
        or payload.get("matched_chapter_title") != definition.title
        or payload.get("max_chars") != character_limit
        or not isinstance(text, str)
        or not text.strip()
        or len(text) > character_limit
        or not isinstance(start_page_index, int)
        or isinstance(start_page_index, bool)
        or not isinstance(end_page_index, int)
        or isinstance(end_page_index, bool)
        or start_page_index < 0
        or end_page_index < start_page_index
        or not isinstance(page_texts, list)
        or not page_texts
        or not all(
            isinstance(page, dict)
            and isinstance(page.get("page_index"), int)
            and not isinstance(page.get("page_index"), bool)
            and start_page_index <= page["page_index"] <= end_page_index
            and isinstance(page.get("text"), str)
            and bool(page["text"].strip())
            for page in page_texts
        )
        or not isinstance(payload.get("match"), dict)
        or not isinstance(payload.get("truncated"), bool)
    ):
        return None, True
    page_indexes = [page["page_index"] for page in page_texts]
    if page_indexes != sorted(set(page_indexes)):
        return None, True
    return payload, False


def _write_context_cache_atomic(cache_path: Path, context: dict[str, Any]) -> None:
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
            json.dump(context, temporary_file, ensure_ascii=False, sort_keys=True)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, cache_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _remove_invalid_cache(cache_path: Path, cache_key: str, chapter_id: str) -> None:
    try:
        if cache_path.exists() or cache_path.is_symlink():
            cache_path.unlink()
            logger.info(
                "textbook_chapter_context_cache_invalid chapter_id=%s cache_key=%s",
                chapter_id,
                cache_key,
            )
    except OSError as error:
        logger.warning(
            "textbook_chapter_context_unavailable chapter_id=%s cache_key=%s reason=cache_cleanup_%s",
            chapter_id,
            cache_key,
            type(error).__name__,
        )


def _lock_for(cache_path: Path) -> threading.Lock:
    lock_key = os.path.normcase(str(cache_path.resolve(strict=False)))
    with _cache_locks_guard:
        return _cache_locks.setdefault(lock_key, threading.Lock())


def _with_requested_chapter(context: dict[str, Any], requested_chapter: str) -> dict[str, Any]:
    result = dict(context)
    result["requested_chapter"] = requested_chapter
    return result


def _log_unavailable(
    student_class: Any,
    subject: Any,
    chapter_id: str | None,
    *,
    reason: str,
    cache_key: str | None = None,
) -> None:
    logger.info(
        "textbook_chapter_context_unavailable class=%r subject=%r chapter_id=%s reason=%s cache_key=%s",
        student_class,
        subject,
        chapter_id or "none",
        reason,
        cache_key or "none",
    )


def _clear_cache_locks_for_tests() -> None:
    with _cache_locks_guard:
        _cache_locks.clear()
