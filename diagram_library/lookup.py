import re


BAD_RESULT_TERMS = (
    "logo",
    "icon",
    "flag",
    "portrait",
    "photo",
    "coat of arms",
    "seal",
)

NON_ENGLISH_LANGUAGE_CODES = (
    "ar",
    "ru",
    "zh",
    "zh-hans",
    "zh-hant",
    "ja",
    "ko",
    "fa",
    "he",
    "hi",
    "bn",
    "ur",
    "de",
    "fr",
    "es",
    "pt",
    "it",
    "pl",
    "uk",
    "tr",
    "nl",
    "sv",
    "fi",
    "cs",
    "ro",
    "id",
    "vi",
    "th",
    "as",
    "az",
    "bg",
    "ca",
    "da",
    "el",
    "et",
    "eu",
    "gl",
    "hr",
    "hu",
    "hy",
    "ka",
    "kk",
    "lt",
    "lv",
    "mk",
    "sk",
    "sl",
    "sr",
    "sw",
    "uz",
)

NON_ENGLISH_LANGUAGE_NAMES = (
    "arabic",
    "russian",
    "chinese",
    "japanese",
    "korean",
    "persian",
    "hebrew",
    "hindi",
    "bengali",
    "urdu",
    "german",
    "french",
    "spanish",
    "portuguese",
    "italian",
    "polish",
    "ukrainian",
    "turkish",
    "dutch",
    "swedish",
    "finnish",
    "czech",
    "romanian",
    "indonesian",
    "vietnamese",
    "thai",
    "assamese",
    "azerbaijani",
    "bulgarian",
    "catalan",
    "danish",
    "greek",
    "estonian",
    "basque",
    "galician",
    "croatian",
    "hungarian",
    "armenian",
    "georgian",
    "kazakh",
    "latvian",
    "lithuanian",
    "macedonian",
    "slovak",
    "slovenian",
    "serbian",
    "swahili",
    "uzbek",
)

EDUCATIONAL_TERMS = (
    "diagram",
    "structure",
    "anatomy",
    "cycle",
    "process",
    "overview",
    "schema",
    "schematic",
    "label",
    "labeled",
    "labelled",
    "educational",
    "illustration",
)


def build_search_queries(subject="", topic="", student_class="", book_name="", visualization_type=""):
    subject = str(subject or "").strip()
    topic = str(topic or "").strip()
    student_class = str(student_class or "").strip()
    book_name = str(book_name or "").strip()
    visualization_type = str(visualization_type or "").strip().replace("_", " ")
    context = " ".join(part for part in [subject, f"class {student_class}" if student_class else "", book_name] if part)
    topic_lower = topic.lower()
    if any(term in topic_lower for term in ("photosynthesis", "plant cell", "animal cell", "human heart", "digestive system")):
        domain = "biology educational diagram"
    elif any(term in topic_lower for term in ("solar system", "planet", "orbit")):
        domain = "astronomy educational diagram"
    elif any(term in topic_lower for term in ("water cycle", "river", "map")):
        domain = "geography educational diagram"
    elif any(term in topic_lower for term in ("database", "er diagram", "network")):
        domain = "computer science diagram"
    elif "timeline" in visualization_type or "history" in subject.lower():
        domain = "timeline educational diagram"
    else:
        domain = "educational diagram"

    queries = [
        f"{topic} {subject} {domain}".strip(),
        f"{topic} {domain}".strip(),
        f"{topic} {visualization_type} diagram".strip(),
        f"{topic} diagram".strip(),
        f"{topic} overview diagram".strip(),
    ]
    if context:
        queries.append(f"{topic} {context} educational diagram")
    return _unique_queries(queries)


def acceptable_candidate_title(title):
    normalized = str(title or "").lower()
    for term in BAD_RESULT_TERMS:
        if re.search(rf"\b{re.escape(term)}s?\b", normalized):
            return False
    return bool(re.search(r"\.(png|jpg|jpeg|svg|webp|gif)$", normalized) or normalized)


def rank_diagram_candidates(candidates, topic="", subject="", visualization_type=""):
    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = (getattr(candidate, "image_url", ""), getattr(candidate, "source_url", ""))
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)

    return sorted(
        unique_candidates,
        key=lambda candidate: candidate_rank_score(candidate, topic, subject, visualization_type),
        reverse=True,
    )


def candidate_rank_score(candidate, topic="", subject="", visualization_type=""):
    title = str(getattr(candidate, "title", "") or "")
    image_url = str(getattr(candidate, "image_url", "") or "")
    source_url = str(getattr(candidate, "source_url", "") or "")
    mime_type = str(getattr(candidate, "mime_type", "") or "").lower()
    haystack = " ".join([title, image_url, source_url]).lower()
    score = 0

    if _has_non_latin_script(haystack) or _has_non_english_language_marker(haystack):
        score -= 140
    elif _has_english_language_marker(haystack):
        score += 90
    elif _looks_english_or_language_neutral(title):
        score += 45

    score += _topic_relevance_score(title, topic)
    score += _educational_style_score(haystack)
    score += _format_score(mime_type)
    score += _resolution_score(getattr(candidate, "width", 0), getattr(candidate, "height", 0))

    if str(subject or "").lower() in haystack:
        score += 8
    visualization_words = str(visualization_type or "").lower().replace("_", " ").split()
    score += sum(3 for word in visualization_words if len(word) > 3 and word in haystack)
    return score


def candidate_language_category(candidate):
    haystack = " ".join(
        [
            str(getattr(candidate, "title", "") or ""),
            str(getattr(candidate, "image_url", "") or ""),
            str(getattr(candidate, "source_url", "") or ""),
        ]
    ).lower()
    if _has_non_latin_script(haystack) or _has_non_english_language_marker(haystack):
        return "non_english"
    if _has_english_language_marker(haystack) or _looks_english_or_language_neutral(getattr(candidate, "title", "")):
        return "english_or_neutral"
    return "unknown"


def _has_english_language_marker(value):
    return bool(re.search(r"(^|[ _().-])(en|eng|english)([ _().-]|$)", value))


def _has_non_english_language_marker(value):
    if any(language_name in value for language_name in NON_ENGLISH_LANGUAGE_NAMES):
        return True
    escaped_codes = [re.escape(code) for code in NON_ENGLISH_LANGUAGE_CODES]
    return bool(re.search(rf"(^|[ _().-])({'|'.join(escaped_codes)})([ _().-]|$)", value))


def _has_non_latin_script(value):
    return bool(
        re.search(
            r"[\u0400-\u04ff\u0600-\u06ff\u0750-\u077f\u0590-\u05ff\u0900-\u097f\u0980-\u09ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]",
            value,
        )
    )


def _looks_english_or_language_neutral(title):
    title = str(title or "")
    if _has_non_latin_script(title.lower()):
        return False
    letters = re.findall(r"[A-Za-z]", title)
    return len(letters) >= 3


def _topic_relevance_score(title, topic):
    title_words = set(re.findall(r"[a-z0-9]+", str(title or "").lower()))
    topic_words = [word for word in re.findall(r"[a-z0-9]+", str(topic or "").lower()) if len(word) > 2]
    if not topic_words:
        return 0
    matches = sum(1 for word in topic_words if word in title_words)
    return min(35, matches * 12)


def _educational_style_score(value):
    score = 0
    for term in EDUCATIONAL_TERMS:
        if term in value:
            score += 8
    if "photo" in value or "micrograph" in value:
        score -= 15
    return min(score, 40)


def _format_score(mime_type):
    if mime_type == "image/svg+xml":
        return 35
    if mime_type == "image/png":
        return 18
    if mime_type in {"image/jpeg", "image/jpg", "image/webp"}:
        return 8
    return 0


def _resolution_score(width, height):
    try:
        pixels = int(width or 0) * int(height or 0)
    except (TypeError, ValueError):
        return 0
    if pixels >= 1_200_000:
        return 24
    if pixels >= 700_000:
        return 18
    if pixels >= 300_000:
        return 10
    if pixels > 0:
        return 4
    return 0


def _unique_queries(queries):
    seen = set()
    unique = []
    for query in queries:
        normalized = re.sub(r"\s+", " ", query).strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            unique.append(normalized)
    return unique
