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


def _unique_queries(queries):
    seen = set()
    unique = []
    for query in queries:
        normalized = re.sub(r"\s+", " ", query).strip()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            unique.append(normalized)
    return unique
