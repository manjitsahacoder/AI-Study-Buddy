from dataclasses import dataclass


SUPPORTED_LICENSE_KEYWORDS = (
    "cc0",
    "public domain",
    "cc by",
    "cc-by",
    "cc by-sa",
    "cc-by-sa",
    "gfdl",
)

REJECTED_LICENSE_KEYWORDS = (
    "fair use",
    "non-free",
    "copyrighted",
    "all rights reserved",
    "no derivatives",
    "noncommercial",
    "non-commercial",
)


@dataclass
class DiagramCandidate:
    provider: str
    title: str
    image_url: str
    source_url: str
    author: str
    license: str
    attribution: str
    mime_type: str
    width: int = 0
    height: int = 0


def reusable_license(license_text):
    normalized = str(license_text or "").strip().lower()
    if not normalized:
        return False
    if any(keyword in normalized for keyword in REJECTED_LICENSE_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in SUPPORTED_LICENSE_KEYWORDS)


def attribution_text(title, author, license_text, source_url):
    parts = [str(title or "Educational diagram").strip()]
    if author:
        parts.append(f"by {author}")
    if license_text:
        parts.append(f"licensed {license_text}")
    if source_url:
        parts.append(f"via {source_url}")
    return ", ".join(parts)
