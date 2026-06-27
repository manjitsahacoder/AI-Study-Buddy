import re


SUPPORTED_VISUALIZATION_TYPES = {
    "flowchart": "Flowchart",
    "process": "Process Diagram",
    "cycle": "Cycle Diagram",
    "timeline": "Timeline",
    "tree": "Tree Diagram",
    "hierarchy": "Hierarchy Diagram",
    "concept_map": "Concept Map",
    "mind_map": "Mind Map",
    "comparison": "Comparison Diagram",
    "network_graph": "Network Graph",
    "organization_chart": "Organization Chart",
    "ecosystem": "Ecosystem Diagram",
    "anatomy": "Anatomy Diagram",
    "scientific_process": "Scientific Process",
    "layer": "Layer Diagram",
    "pyramid": "Pyramid",
    "matrix": "Matrix",
    "cause_and_effect": "Cause and Effect Diagram",
    "orbit": "Orbit Diagram",
    "chain": "Chain Diagram",
    "circuit": "Circuit Diagram",
    "er_diagram": "ER-style Diagram",
}


TYPE_ALIASES = {
    "chart": "hierarchy",
    "org_chart": "organization_chart",
    "organization": "organization_chart",
    "organ": "anatomy",
    "cell": "anatomy",
    "map": "concept_map",
    "relationship": "concept_map",
    "relationship_map": "concept_map",
    "layers": "layer",
    "flow": "flowchart",
    "network": "network_graph",
    "graph": "network_graph",
    "cause_effect": "cause_and_effect",
    "cause-effect": "cause_and_effect",
    "fishbone": "cause_and_effect",
    "er": "er_diagram",
    "erd": "er_diagram",
    "database": "er_diagram",
}


TYPE_KEYWORDS = [
    ("cycle", ["cycle", "repeating", "circulation", "water cycle", "carbon cycle"]),
    ("anatomy", ["digestive", "heart", "cell", "organ", "body", "anatomy", "flower", "eye", "ear"]),
    ("tree", ["classification", "taxonomy", "family tree", "kingdoms"]),
    ("timeline", ["timeline", "revolution", "history", "war", "movement", "chronology", "events"]),
    ("orbit", ["solar system", "planet", "orbit", "satellite"]),
    ("network_graph", ["network", "internet", "computer network", "web", "relationships"]),
    ("chain", ["food chain", "chain", "sequence"]),
    ("comparison", [" vs ", "versus", "compare", "difference", "plant cell and animal cell"]),
    ("hierarchy", ["democracy", "government", "structure", "levels", "administration"]),
    ("circuit", ["electric circuit", "circuit", "current", "resistor", "battery"]),
    ("er_diagram", ["database", "sql", "relationship", "entity", "foreign key"]),
    ("pyramid", ["pyramid", "levels of", "food pyramid", "energy pyramid"]),
    ("layer", ["layers", "strata", "atmosphere", "earth interior"]),
    ("cause_and_effect", ["cause", "effect", "impact", "reason", "consequence"]),
    ("scientific_process", ["experiment", "method", "scientific method"]),
    ("process", ["photosynthesis", "digestion", "process", "steps", "how"]),
]


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def slugify_type(value):
    value = normalize_text(value).lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value


def normalize_visualization_type(value):
    normalized = slugify_type(value)
    normalized = TYPE_ALIASES.get(normalized, normalized)
    if normalized in SUPPORTED_VISUALIZATION_TYPES:
        return normalized
    return "flowchart"


def display_type(value):
    return SUPPORTED_VISUALIZATION_TYPES.get(
        normalize_visualization_type(value),
        SUPPORTED_VISUALIZATION_TYPES["flowchart"],
    )


def infer_type(subject="", topic="", labels=None):
    haystack = f"{normalize_text(subject)} {normalize_text(topic)} {' '.join(labels or [])}".lower()
    padded = f" {haystack} "
    for visualization_type, keywords in TYPE_KEYWORDS:
        if any(keyword in padded or keyword in haystack for keyword in keywords):
            return visualization_type
    return "concept_map" if len(labels or []) > 5 else "process"


def clamp_number(value, default=0.9, minimum=0.0, maximum=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1 and number <= 100:
        number = number / 100
    return max(minimum, min(maximum, number))


def normalize_label(value, limit=90):
    if isinstance(value, dict):
        value = value.get("label") or value.get("text") or value.get("name") or value.get("title") or ""
    text = normalize_text(value)
    return text[:limit]


def normalize_nodes(raw_nodes, labels=None, max_nodes=80):
    nodes = []
    seen = set()
    source = raw_nodes if isinstance(raw_nodes, list) else []
    if not source and labels:
        source = [{"label": label} for label in labels]

    for index, node in enumerate(source[:max_nodes], start=1):
        if isinstance(node, dict):
            node_id = normalize_text(node.get("id") or node.get("key") or index)
            label = normalize_label(node.get("label") or node.get("text") or node.get("name") or node_id)
            description = normalize_label(node.get("description") or node.get("note") or "", limit=140)
            group = normalize_label(node.get("group") or node.get("category") or "", limit=50)
        else:
            node_id = str(index)
            label = normalize_label(node)
            description = ""
            group = ""

        if not label:
            continue
        if not node_id or node_id in seen:
            node_id = str(index)
        while node_id in seen:
            node_id = f"{node_id}_{index}"
        seen.add(node_id)
        nodes.append({"id": node_id, "label": label, "description": description, "group": group})
    return nodes


def normalize_connections(raw_connections, node_ids=None, max_edges=140):
    node_ids = set(node_ids or [])
    connections = []
    source = raw_connections if isinstance(raw_connections, list) else []

    for edge in source[:max_edges]:
        label = ""
        if isinstance(edge, dict):
            start = edge.get("from") or edge.get("source") or edge.get("start")
            end = edge.get("to") or edge.get("target") or edge.get("end")
            label = normalize_label(edge.get("label") or edge.get("text") or "", limit=70)
        elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
            start, end = edge[0], edge[1]
            label = normalize_label(edge[2], limit=70) if len(edge) > 2 else ""
        else:
            continue

        start = normalize_text(start)
        end = normalize_text(end)
        if not start or not end or start == end:
            continue
        if node_ids and (start not in node_ids or end not in node_ids):
            continue
        item = {"from": start, "to": end}
        if label:
            item["label"] = label
        connections.append(item)
    return connections


def sequential_connections(nodes):
    return [
        {"from": nodes[index]["id"], "to": nodes[index + 1]["id"]}
        for index in range(max(0, len(nodes) - 1))
    ]


def safe_title(topic="", payload_title=""):
    title = normalize_text(payload_title) or normalize_text(topic) or "AI Visualization"
    return title[:90]
