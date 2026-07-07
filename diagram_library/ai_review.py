import hashlib
import json
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import google.generativeai as genai

from config import GEMINI_API_KEY

from .lookup import candidate_language_category


AI_REVIEW_BATCH_SIZE = 8
AI_REVIEW_CONFIDENCE_THRESHOLD = 0.75
AI_REVIEW_CACHE_LIMIT = 256

_LOGGER = logging.getLogger(__name__)
_REVIEW_CACHE = OrderedDict()


@dataclass(frozen=True)
class DiagramReviewDecision:
    selected_index: int | None = None
    confidence: float = 0.0
    reason: str = ""
    unavailable: bool = False
    from_cache: bool = False

    @property
    def accepted(self):
        return (
            self.selected_index is not None
            and self.confidence >= AI_REVIEW_CONFIDENCE_THRESHOLD
            and not self.unavailable
        )


def review_diagram_candidates(
    *,
    topic,
    subject="",
    student_class="",
    visualization_type="",
    candidates,
    model_factory=None,
):
    candidates = list(candidates or [])
    if not candidates:
        return DiagramReviewDecision()
    if not ai_review_enabled():
        return DiagramReviewDecision(unavailable=True, reason="Gemini diagram review is disabled.")
    if not GEMINI_API_KEY and model_factory is None:
        return DiagramReviewDecision(unavailable=True, reason="Gemini API key is not configured.")

    metadata = [_candidate_review_metadata(index, candidate) for index, candidate in enumerate(candidates)]
    cache_key = _review_cache_key(topic, subject, student_class, visualization_type, metadata)
    cached = _cache_get(cache_key)
    if cached:
        return DiagramReviewDecision(
            selected_index=cached.selected_index,
            confidence=cached.confidence,
            reason=cached.reason,
            unavailable=cached.unavailable,
            from_cache=True,
        )

    prompt = build_diagram_review_prompt(
        topic=topic,
        subject=subject,
        student_class=student_class,
        visualization_type=visualization_type,
        candidates_metadata=metadata,
    )
    try:
        if model_factory is None:
            genai.configure(api_key=GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.5-flash")
        else:
            model = model_factory()
        response = _generate_review_response(model, prompt)
        decision = parse_diagram_review_response(getattr(response, "text", "") or "", len(candidates))
    except Exception as error:
        _LOGGER.warning("diagram_ai_review_failed topic=%s error=%s", topic, _sanitize_error(error))
        decision = DiagramReviewDecision(unavailable=True, reason="Gemini diagram review is unavailable.")

    if not decision.unavailable:
        _cache_set(cache_key, decision)
    return decision


def ai_review_enabled():
    return os.environ.get("DIAGRAM_AI_REVIEW_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def build_diagram_review_prompt(
    *,
    topic,
    subject="",
    student_class="",
    visualization_type="",
    candidates_metadata,
):
    payload = {
        "topic": topic or "",
        "subject": subject or "",
        "class_level": student_class or "Classes 6-10",
        "visualization_type": visualization_type or "",
        "candidates": candidates_metadata,
    }
    return f"""You are reviewing educational diagrams for a school AI learning platform.

The final diagram must feel like it came from an NCERT textbook:
- English labels only
- Clean educational illustration
- Relevant to the topic
- Readable
- Suitable for Classes 6-10

For each candidate evaluate:
- relevance (0-10)
- English language quality (0-10)
- readability (0-10)
- educational usefulness (0-10)
- textbook suitability (0-10)

Reject any candidate that:
- is not predominantly English
- has labels mostly in another language
- is mixed-language where English is not dominant
- is unrelated to the requested topic
- is only a photograph, decorative image, meme, or artistic illustration
- is blurry, tiny, crowded, unreadable, or heavily watermarked
- is too advanced for Classes 6-10

Prefer textbook diagrams, labeled scientific diagrams, clean educational illustrations, NCERT-style diagrams, and Wikimedia educational SVGs.

Review only the lightweight metadata and image URLs below. Do not assume a full-resolution image will be downloaded.

Return ONLY JSON with this exact shape:
{{
  "selected_index": 2,
  "confidence": 0.96,
  "reason": "Best English educational diagram with clear labels."
}}

If no candidate is acceptable, use:
{{
  "selected_index": null,
  "confidence": 0.0,
  "reason": "No suitable educational diagram found."
}}

No markdown.
No explanations.
Only JSON.

Candidate data:
{json.dumps(payload, ensure_ascii=True, indent=2)}
"""


def parse_diagram_review_response(response_text, candidate_count):
    payload = _extract_json_object(response_text)
    if not payload:
        return DiagramReviewDecision(unavailable=True, reason="Gemini diagram review returned invalid JSON.")
    selected_index = payload.get("selected_index")
    if selected_index is None:
        normalized_index = None
    else:
        try:
            normalized_index = int(selected_index)
        except (TypeError, ValueError):
            normalized_index = None
    if normalized_index is not None and not 0 <= normalized_index < candidate_count:
        normalized_index = None
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    return DiagramReviewDecision(
        selected_index=normalized_index,
        confidence=confidence,
        reason=str(payload.get("reason", "") or "")[:280],
    )


def clear_review_cache():
    _REVIEW_CACHE.clear()


def _generate_review_response(model, prompt):
    generation_config = {
        "temperature": 0.0,
        "response_mime_type": "application/json",
    }
    try:
        return model.generate_content(
            prompt,
            generation_config=generation_config,
            request_options={"timeout": 12},
        )
    except TypeError:
        return model.generate_content(prompt)


def _candidate_review_metadata(index, candidate):
    provider_metadata = getattr(candidate, "provider_metadata", {}) or {}
    commons_metadata = getattr(candidate, "commons_metadata", {}) or {}
    return {
        "index": index,
        "provider": _clean_text(getattr(candidate, "provider", "")),
        "title": _clean_text(getattr(candidate, "title", "")),
        "filename": _candidate_filename(candidate),
        "image_url": _clean_text(getattr(candidate, "image_url", "")),
        "source_url": _clean_text(getattr(candidate, "source_url", "")),
        "author": _clean_text(getattr(candidate, "author", "")),
        "license": _clean_text(getattr(candidate, "license", "")),
        "mime_type": _clean_text(getattr(candidate, "mime_type", "")),
        "width": _safe_int(getattr(candidate, "width", 0)),
        "height": _safe_int(getattr(candidate, "height", 0)),
        "description": _clean_text(getattr(candidate, "description", ""), limit=600),
        "categories": [_clean_text(category, limit=120) for category in (getattr(candidate, "categories", ()) or ())[:12]],
        "language_hint": candidate_language_category(candidate),
        "metadata": _limited_metadata({**commons_metadata, **provider_metadata}),
    }


def _limited_metadata(metadata):
    if not isinstance(metadata, dict):
        return {}
    useful = {}
    for key, value in metadata.items():
        if len(useful) >= 12:
            break
        if key == "local_path":
            continue
        cleaned = _clean_text(value, limit=180)
        if cleaned:
            useful[_clean_text(key, limit=80)] = cleaned
    return useful


def _candidate_filename(candidate):
    for value in (
        getattr(candidate, "image_url", ""),
        getattr(candidate, "source_url", ""),
        getattr(candidate, "title", ""),
    ):
        parsed_path = urlsplit(str(value or "")).path
        filename = unquote(parsed_path.rsplit("/", 1)[-1] or str(value or ""))
        filename = filename.replace("File:", "")
        if filename:
            return _clean_text(filename, limit=220)
    return ""


def _clean_text(value, limit=320):
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _extract_json_object(response_text):
    text = str(response_text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _review_cache_key(topic, subject, student_class, visualization_type, metadata):
    canonical = json.dumps(
        {
            "topic": topic or "",
            "subject": subject or "",
            "student_class": student_class or "",
            "visualization_type": visualization_type or "",
            "candidates": metadata,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_get(key):
    decision = _REVIEW_CACHE.get(key)
    if decision:
        _REVIEW_CACHE.move_to_end(key)
    return decision


def _cache_set(key, decision):
    _REVIEW_CACHE[key] = decision
    _REVIEW_CACHE.move_to_end(key)
    while len(_REVIEW_CACHE) > AI_REVIEW_CACHE_LIMIT:
        _REVIEW_CACHE.popitem(last=False)


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sanitize_error(error):
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[REDACTED_API_KEY]", str(error))
