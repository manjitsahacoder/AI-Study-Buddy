import re
from urllib.parse import unquote, urlsplit


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

BROAD_TOPIC_PROFILES = {
    "cell division": {
        "preferred": (
            "cell division",
            "mitosis",
            "meiosis",
            "chromosome",
            "chromosomes",
            "cytokinesis",
            "stages of mitosis",
            "mitotic phase",
            "metaphase",
            "anaphase",
            "telophase",
            "prophase",
            "interphase",
        ),
        "specialized": (
            "fungal",
            "fungus",
            "fungi",
            "yeast",
            "basidiomycete",
            "basidiomycetes",
            "dikaryotic",
            "dikaryon",
            "bacterial",
            "bacteria",
            "archaeal",
            "archaea",
            "species specific",
            "life cycle",
            "saccharomyces",
            "schizosaccharomyces",
            "aspergillus",
            "neurospora",
        ),
    }
}

BIOLOGY_SPECIALIZED_CASE_TERMS = (
    "fungal",
    "fungus",
    "fungi",
    "yeast",
    "basidiomycete",
    "dikaryotic",
    "bacterial",
    "archaeal",
    "species specific",
)

FIELD_WEIGHTS = {
    "title": 8,
    "filename": 7,
    "description": 5,
    "categories": 4,
    "metadata": 2,
}


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
    text_fields = _candidate_text_fields(candidate)
    haystack = " ".join(text_fields.values()).lower()
    score = 0

    if _has_non_latin_script(haystack) or _has_non_english_language_marker(haystack):
        score -= 140
    elif _has_english_language_marker(haystack):
        score += 90
    elif _looks_english_or_language_neutral(title):
        score += 45

    score += _semantic_relevance_score(candidate, topic, subject)
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
    haystack = " ".join(_candidate_text_fields(candidate).values()).lower()
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


def _semantic_relevance_score(candidate, topic, subject=""):
    topic_text = _normalize_text(topic)
    if not topic_text:
        return 0

    fields = _candidate_text_fields(candidate)
    normalized_fields = {name: _normalize_text(value) for name, value in fields.items()}
    score = 0

    score += _weighted_phrase_score(topic_text, normalized_fields, base=12, cap=110)
    score += _topic_word_coverage_score(topic_text, normalized_fields)

    profile = _topic_profile(topic_text)
    preferred_hits = 0
    if profile:
        for term in profile["preferred"]:
            term_score = _weighted_phrase_score(term, normalized_fields, base=7, cap=70)
            if term_score:
                preferred_hits += 1
                score += term_score

        for term in profile["specialized"]:
            score -= _weighted_phrase_score(term, normalized_fields, base=7, cap=90)

        if preferred_hits and _has_educational_match(normalized_fields):
            score += 35
        if preferred_hits >= 2:
            score += 20
        if _has_general_school_diagram_match(normalized_fields):
            score += 16

    if _is_broad_school_biology_topic(topic_text, subject):
        for term in BIOLOGY_SPECIALIZED_CASE_TERMS:
            score -= _weighted_phrase_score(term, normalized_fields, base=4, cap=44)

    return score


def _candidate_text_fields(candidate):
    title = str(getattr(candidate, "title", "") or "")
    image_url = str(getattr(candidate, "image_url", "") or "")
    source_url = str(getattr(candidate, "source_url", "") or "")
    description = str(getattr(candidate, "description", "") or "")
    categories = " ".join(str(category or "") for category in getattr(candidate, "categories", ()) or ())
    metadata = getattr(candidate, "commons_metadata", {}) or {}
    if isinstance(metadata, dict):
        metadata_text = " ".join(str(value or "") for value in metadata.values())
    else:
        metadata_text = str(metadata or "")
    return {
        "title": title,
        "filename": _candidate_filename(title, image_url, source_url),
        "description": description,
        "categories": categories,
        "metadata": metadata_text,
    }


def _candidate_filename(title, image_url, source_url):
    for value in (image_url, source_url, title):
        parsed_path = urlsplit(str(value or "")).path
        filename = unquote(parsed_path.rsplit("/", 1)[-1] or str(value or ""))
        filename = filename.replace("File:", "")
        if filename:
            return filename
    return ""


def _normalize_text(value):
    normalized = unquote(str(value or "").lower())
    normalized = re.sub(r"<[^>]+>", " ", normalized)
    normalized = re.sub(r"[_+/|:;.,()[\]{}-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _weighted_phrase_score(phrase, normalized_fields, *, base, cap):
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return 0
    score = 0
    pattern = rf"\b{re.escape(normalized_phrase)}s?\b"
    for field_name, field_value in normalized_fields.items():
        if re.search(pattern, field_value):
            score += base * FIELD_WEIGHTS.get(field_name, 1)
    return min(cap, score)


def _topic_word_coverage_score(topic_text, normalized_fields):
    words = [word for word in re.findall(r"[a-z0-9]+", topic_text) if len(word) > 2]
    if not words:
        return 0
    all_text = " ".join(normalized_fields.values())
    matches = sum(1 for word in words if re.search(rf"\b{re.escape(word)}s?\b", all_text))
    score = matches * 14
    if matches == len(words):
        score += 28
    return min(score, 70)


def _topic_profile(topic_text):
    for topic_key, profile in BROAD_TOPIC_PROFILES.items():
        if topic_key in topic_text or topic_text in topic_key:
            return profile
    return None


def _has_educational_match(normalized_fields):
    all_text = " ".join(normalized_fields.values())
    return any(term in all_text for term in EDUCATIONAL_TERMS)


def _has_general_school_diagram_match(normalized_fields):
    all_text = " ".join([normalized_fields["title"], normalized_fields["filename"], normalized_fields["description"]])
    return any(
        term in all_text
        for term in ("diagram", "labelled", "labeled", "overview", "stages", "process", "educational")
    )


def _is_broad_school_biology_topic(topic_text, subject):
    subject_text = _normalize_text(subject)
    if "biology" not in subject_text and not any(term in topic_text for term in ("cell", "mitosis", "meiosis")):
        return False
    return _topic_profile(topic_text) is not None


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
