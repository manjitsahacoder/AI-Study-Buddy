from pathlib import Path

from sqlalchemy import func

from database import db
from models import DiagramLibrary
from performance_monitor import performance_span

from .ai_review import AI_REVIEW_BATCH_SIZE, review_diagram_candidates
from .cache import cache_file_exists, utc_now
from .lookup import (
    acceptable_candidate_title,
    build_search_queries,
    candidate_language_category,
    rank_diagram_candidates,
    relevant_diagram_candidates,
)
from .providers import NcertProvider, ProviderRegistry, WikimediaCommonsProvider
from .storage import download_and_store, repair_cached_image_extension


def default_registry(static_folder="static"):
    return ProviderRegistry([NcertProvider(static_folder=static_folder), WikimediaCommonsProvider()])


def find_cached_diagram(static_folder, subject, topic):
    with performance_span("Cache lookups", detail=f"diagram {subject}/{topic}"):
        diagram = (
            DiagramLibrary.query.filter(
                DiagramLibrary.verified.is_(True),
                DiagramLibrary.subject == (subject or ""),
                DiagramLibrary.topic == (topic or ""),
            )
            .order_by(DiagramLibrary.last_used.desc(), DiagramLibrary.cached_at.desc())
            .first()
        )
        if diagram is None:
            diagram = (
                DiagramLibrary.query.filter(
                    DiagramLibrary.verified.is_(True),
                    func.lower(DiagramLibrary.subject) == (subject or "").lower(),
                    func.lower(DiagramLibrary.topic) == (topic or "").lower(),
                )
                .order_by(DiagramLibrary.last_used.desc(), DiagramLibrary.cached_at.desc())
                .first()
            )
    if diagram and cache_file_exists(static_folder, diagram.image_path):
        now = utc_now()
        try:
            should_touch = not diagram.last_used or (now - diagram.last_used).total_seconds() >= 3600
        except TypeError:
            should_touch = True
        if should_touch:
            diagram.last_used = now
            db.session.commit()
        return diagram
    if diagram:
        repaired_path = repair_cached_image_extension(static_folder, diagram.image_path)
        if repaired_path and cache_file_exists(static_folder, repaired_path):
            diagram.image_path = repaired_path
            diagram.last_used = utc_now()
            db.session.commit()
            return diagram
        diagram.verified = False
        db.session.commit()
    return None


def get_or_create_diagram(
    *,
    lesson_id,
    subject,
    topic,
    student_class="",
    book_name="",
    visualization_type="",
    static_folder="static",
    testing=False,
    provider_registry=None,
    reviewer=None,
):
    cached = find_cached_diagram(static_folder, subject, topic)
    if cached:
        return cached

    if testing:
        return None

    registry = provider_registry or default_registry(static_folder=static_folder)
    queries = build_search_queries(
        subject=subject,
        topic=topic,
        student_class=student_class,
        book_name=book_name,
        visualization_type=visualization_type,
    )
    cache_dir = Path(static_folder) / "diagram_cache"
    try:
        for provider, provider_candidates in _provider_candidate_groups(
            registry,
            queries,
            topic=topic,
            subject=subject,
            limit_per_query=8,
        ):
            with performance_span("Diagram ranking", detail=getattr(provider, "name", "") if provider else ""):
                candidates = rank_diagram_candidates(
                    provider_candidates,
                    topic=topic,
                    subject=subject,
                    visualization_type=visualization_type,
                )
            candidates = [
                candidate for candidate in candidates if acceptable_candidate_title(candidate.title)
            ]
            candidates = relevant_diagram_candidates(
                candidates,
                topic=topic,
                subject=subject,
                student_class=student_class,
                visualization_type=visualization_type,
            )
            for candidate in _reviewed_candidate_order(
                candidates,
                topic=topic,
                subject=subject,
                student_class=student_class,
                visualization_type=visualization_type,
                reviewer=reviewer,
            ):
                diagram = _store_reviewed_candidate(
                    provider,
                    candidate,
                    cache_dir,
                    static_folder,
                    lesson_id=lesson_id,
                    topic=topic,
                    subject=subject,
                )
                if diagram:
                    return diagram
    except Exception:
        db.session.rollback()
        return None
    return None


def _reviewed_candidate_order(
    candidates,
    *,
    topic="",
    subject="",
    student_class="",
    visualization_type="",
    reviewer=None,
):
    candidates = list(candidates or [])
    trusted = [candidate for candidate in candidates if "ncert" in str(getattr(candidate, "provider", "")).lower()]
    if trusted:
        yield from trusted
        return
    for start in range(0, len(candidates), AI_REVIEW_BATCH_SIZE):
        batch = candidates[start : start + AI_REVIEW_BATCH_SIZE]
        if not batch:
            continue
        decision = _review_batch(
            batch,
            topic=topic,
            subject=subject,
            student_class=student_class,
            visualization_type=visualization_type,
            reviewer=reviewer,
        )
        if decision.accepted:
            yield batch[decision.selected_index]
            continue
        if decision.unavailable:
            yield from _fallback_candidate_order(batch)


def _review_batch(batch, *, topic="", subject="", student_class="", visualization_type="", reviewer=None):
    if reviewer is not None:
        return reviewer(
            topic=topic,
            subject=subject,
            student_class=student_class,
            visualization_type=visualization_type,
            candidates=batch,
        )
    return review_diagram_candidates(
        topic=topic,
        subject=subject,
        student_class=student_class,
        visualization_type=visualization_type,
        candidates=batch,
    )


def _fallback_candidate_order(candidates):
    for language_category in ("english_or_neutral", "unknown"):
        for candidate in candidates:
            if candidate_language_category(candidate) == language_category:
                yield candidate


def _store_reviewed_candidate(
    provider,
    candidate,
    cache_dir,
    static_folder,
    *,
    lesson_id,
    topic,
    subject,
):
    with performance_span("Diagram storage", detail=getattr(candidate, "title", "")):
        stored_path = _fetch_candidate(provider, candidate, cache_dir, topic)
    if not stored_path:
        return None
    image_path = stored_path.relative_to(static_folder).as_posix()
    diagram = DiagramLibrary(
        lesson_id=lesson_id,
        topic=topic,
        subject=subject,
        image_path=image_path,
        provider=candidate.provider,
        source_url=candidate.source_url,
        author=candidate.author,
        license=candidate.license,
        attribution=candidate.attribution,
        verified=True,
        cached_at=utc_now(),
        last_used=utc_now(),
    )
    db.session.add(diagram)
    db.session.commit()
    return diagram


def _provider_candidate_groups(registry, queries, *, topic="", subject="", limit_per_query=8):
    finder = getattr(registry, "find_by_provider", None)
    if finder:
        yield from finder(
            queries,
            topic=topic,
            subject=subject,
            limit_per_query=limit_per_query,
        )
        return
    yield None, registry.search(queries, limit_per_query=limit_per_query)


def _fetch_candidate(provider, candidate, cache_dir, topic):
    fetcher = getattr(provider, "fetch", None) if provider else None
    if fetcher:
        return fetcher(candidate, cache_dir, topic)
    return download_and_store(candidate, cache_dir, topic)


def diagram_record_to_view(diagram, url_builder=None):
    if not diagram:
        return None
    image_url = url_builder(diagram.image_path) if url_builder else diagram.image_path
    return {
        "id": diagram.id,
        "image_url": image_url,
        "image_path": diagram.image_path,
        "provider": diagram.provider,
        "source_url": diagram.source_url,
        "author": diagram.author,
        "license": diagram.license,
        "attribution": diagram.attribution,
        "verified": diagram.verified,
    }
