import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from diagram_library.metadata import DiagramCandidate, attribution_text
from diagram_library.storage import copy_local_candidate_to_cache

from .provider_base import DiagramProvider


NCERT_SOURCE_URL = "https://ncert.nic.in/textbook.php"
NCERT_PROVIDER_NAME = "NCERT Textbook Diagrams"


@dataclass(frozen=True)
class NcertDiagramEntry:
    subject_area: str
    filename: str
    title: str
    aliases: tuple
    author: str = "NCERT"
    license: str = "NCERT textbook diagram"
    source_url: str = NCERT_SOURCE_URL
    description: str = ""


NCERT_DIAGRAM_INDEX = (
    NcertDiagramEntry(
        subject_area="biology",
        filename="mitochondria.png",
        title="Mitochondria",
        aliases=("mitochondria", "mitochondrion"),
        description="Textbook diagram of mitochondria.",
    ),
    NcertDiagramEntry(
        subject_area="biology",
        filename="cell_division.png",
        title="Cell Division",
        aliases=("cell division", "mitosis", "mitotic division"),
        description="Textbook diagram of cell division stages.",
    ),
    NcertDiagramEntry(
        subject_area="biology",
        filename="photosynthesis.png",
        title="Photosynthesis",
        aliases=("photosynthesis", "photosynthesis process"),
        description="Textbook diagram of photosynthesis.",
    ),
)


class NcertProvider(DiagramProvider):
    name = "ncert"
    display_name = NCERT_PROVIDER_NAME

    def __init__(self, static_folder="static", entries=None):
        self.static_folder = Path(static_folder)
        self.root_dir = self.static_folder / "textbook_diagrams"
        self.entries = tuple(entries or NCERT_DIAGRAM_INDEX)
        self._alias_index = self._build_alias_index(self.entries)

    def find(self, queries, *, topic="", subject="", limit_per_query=8):
        entry = self._alias_index.get(_normalize_alias(topic))
        if not entry:
            return
        candidate = self._candidate_for_entry(entry)
        if candidate:
            yield candidate

    def search(self, query, *, limit=8):
        entry = self._alias_index.get(_normalize_alias(query))
        if not entry:
            return
        candidate = self._candidate_for_entry(entry)
        if candidate:
            yield candidate

    def fetch(self, candidate, cache_dir, topic):
        source_path = (candidate.provider_metadata or {}).get("local_path")
        if not source_path:
            return None
        return copy_local_candidate_to_cache(candidate, cache_dir, topic, source_path)

    def metadata(self, candidate):
        return dict(candidate.provider_metadata or {})

    def _build_alias_index(self, entries):
        alias_index = {}
        for entry in entries:
            aliases = set(entry.aliases or ())
            aliases.add(entry.title)
            aliases.add(Path(entry.filename).stem.replace("_", " "))
            for alias in aliases:
                normalized = _normalize_alias(alias)
                if normalized:
                    alias_index[normalized] = entry
        return alias_index

    def _candidate_for_entry(self, entry):
        local_path = self._safe_entry_path(entry)
        if not local_path or not local_path.exists() or not local_path.is_file():
            return None

        mime_type = mimetypes.guess_type(local_path.name)[0] or "image/png"
        source_url = entry.source_url or NCERT_SOURCE_URL
        return DiagramCandidate(
            provider=self.display_name,
            title=entry.title,
            image_url=local_path.resolve().as_uri(),
            source_url=source_url,
            author=entry.author,
            license=entry.license,
            attribution=attribution_text(entry.title, entry.author, entry.license, source_url),
            mime_type=mime_type,
            description=entry.description,
            categories=(entry.subject_area, "NCERT", "textbook diagrams"),
            provider_metadata={
                "local_path": str(local_path),
                "subject_area": entry.subject_area,
                "aliases": tuple(entry.aliases or ()),
            },
        )

    def _safe_entry_path(self, entry):
        root = self.root_dir.resolve()
        path = (self.root_dir / entry.subject_area / entry.filename).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path


def _normalize_alias(value):
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()
