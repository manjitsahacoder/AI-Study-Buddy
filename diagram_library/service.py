from pathlib import Path

from sqlalchemy import func

from database import db
from models import DiagramLibrary

from .cache import cache_file_exists, utc_now
from .lookup import acceptable_candidate_title, build_search_queries
from .providers import ProviderRegistry
from .storage import download_and_store, repair_cached_image_extension
from .wikimedia import WikimediaCommonsProvider


def default_registry():
    return ProviderRegistry([WikimediaCommonsProvider()])


def find_cached_diagram(static_folder, subject, topic):
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
        diagram.last_used = utc_now()
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
):
    cached = find_cached_diagram(static_folder, subject, topic)
    if cached:
        return cached

    if testing:
        return None

    registry = provider_registry or default_registry()
    queries = build_search_queries(
        subject=subject,
        topic=topic,
        student_class=student_class,
        book_name=book_name,
        visualization_type=visualization_type,
    )
    cache_dir = Path(static_folder) / "diagram_cache"
    try:
        candidates = registry.search(queries, limit_per_query=8)
        for candidate in candidates:
            if not acceptable_candidate_title(candidate.title):
                continue
            stored_path = download_and_store(candidate, cache_dir, topic)
            if not stored_path:
                continue
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
    except Exception:
        db.session.rollback()
        return None
    return None


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
