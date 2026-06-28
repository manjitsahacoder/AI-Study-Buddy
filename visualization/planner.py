import json
from urllib.parse import quote

from .schemas import (
    clamp_number,
    display_type,
    infer_type,
    normalize_connections,
    normalize_label,
    normalize_nodes,
    normalize_text,
    normalize_visualization_type,
    safe_title,
    sequential_connections,
)


TOPIC_TEMPLATES = [
    {
        "terms": ["plant cell vs animal cell", "plant cell and animal cell"],
        "type": "comparison",
        "title": "Plant Cell vs Animal Cell",
        "nodes": ["Plant Cell", "Animal Cell", "Cell Wall", "Chloroplast", "Centrioles", "Shape"],
        "reason": "The lesson compares similarities and differences between two cell types.",
        "confidence": 0.93,
    },
    {
        "key": "flower",
        "terms": ["flower", "parts of flower", "plant", "plants"],
        "type": "anatomy",
        "title": "Flower",
        "nodes": ["Flower", "Petal", "Sepal", "Stamen", "Pistil", "Ovary"],
        "reason": "Plant topics are easier to learn with labeled botanical parts.",
        "confidence": 0.88,
    },
    {
        "terms": ["water cycle", "rain cycle"],
        "type": "cycle",
        "title": "Water Cycle",
        "nodes": ["Evaporation", "Condensation", "Precipitation", "Collection"],
        "reason": "This topic describes a repeating natural process.",
        "confidence": 0.97,
    },
    {
        "terms": ["digestive system", "digestion"],
        "type": "anatomy",
        "title": "Human Digestive System",
        "nodes": ["Digestive System", "Mouth", "Oesophagus", "Stomach", "Small Intestine", "Large Intestine"],
        "reason": "This topic is best understood as a labeled body-system diagram.",
        "confidence": 0.94,
    },
    {
        "terms": ["animal classification", "classification", "taxonomy"],
        "type": "tree",
        "title": "Animal Classification",
        "nodes": ["Animals", "Vertebrates", "Invertebrates", "Mammals", "Birds", "Reptiles", "Insects"],
        "reason": "Classification topics naturally branch from broad groups to specific groups.",
        "confidence": 0.93,
    },
    {
        "terms": ["french revolution", "revolution"],
        "type": "timeline",
        "title": "French Revolution",
        "nodes": ["Estates-General", "Tennis Court Oath", "Bastille", "Republic", "Reign of Terror", "Napoleon"],
        "reason": "Historical events are easier to learn in chronological order.",
        "confidence": 0.95,
    },
    {
        "terms": ["photosynthesis"],
        "type": "scientific_process",
        "title": "Photosynthesis",
        "nodes": ["Sunlight", "Carbon Dioxide", "Water", "Chlorophyll", "Glucose", "Oxygen"],
        "reason": "This topic describes inputs and outputs in a biological process.",
        "confidence": 0.96,
    },
    {
        "terms": ["solar system", "planets"],
        "type": "orbit",
        "title": "Solar System",
        "nodes": ["Sun", "Mercury", "Venus", "Earth", "Mars", "Jupiter"],
        "reason": "Planetary motion is best represented with orbital placement.",
        "confidence": 0.96,
    },
    {
        "terms": ["computer network", "network"],
        "type": "network_graph",
        "title": "Computer Network",
        "nodes": ["Router", "Server", "Switch", "Laptop", "Printer", "Internet"],
        "reason": "Connected devices and relationships are best shown as a network graph.",
        "confidence": 0.94,
    },
    {
        "terms": ["food chain"],
        "type": "chain",
        "title": "Food Chain",
        "nodes": ["Sun", "Producer", "Primary Consumer", "Secondary Consumer", "Decomposer"],
        "reason": "Energy transfer follows a directed chain.",
        "confidence": 0.95,
    },
    {
        "terms": ["democracy structure", "democracy", "government structure"],
        "type": "hierarchy",
        "title": "Democracy Structure",
        "nodes": ["People", "Elected Representatives", "Parliament", "Government", "Local Bodies"],
        "reason": "This topic describes levels of authority and representation.",
        "confidence": 0.9,
    },
    {
        "terms": ["newton's laws", "newtons laws", "newton laws"],
        "type": "concept_map",
        "title": "Newton's Laws",
        "nodes": ["Newton's Laws", "First Law", "Second Law", "Third Law", "Force", "Motion"],
        "reason": "Related principles and terms are best studied as a concept map.",
        "confidence": 0.91,
    },
    {
        "terms": ["database relationships", "database relationship", "er diagram"],
        "type": "er_diagram",
        "title": "Database Relationships",
        "nodes": ["Student", "Course", "Enrollment", "Teacher", "Department"],
        "reason": "Entities and relationships are best represented in an ER-style diagram.",
        "confidence": 0.92,
    },
    {
        "terms": ["electric circuit", "circuit"],
        "type": "circuit",
        "title": "Electric Circuit",
        "nodes": ["Battery", "Switch", "Wire", "Bulb", "Current"],
        "reason": "Circuit components and current direction are best shown as a connected path.",
        "confidence": 0.94,
    },
]


def _template_for(subject, topic):
    haystack = f"{normalize_text(subject)} {normalize_text(topic)}".lower()
    for template in TOPIC_TEMPLATES:
        if any(term in haystack for term in template["terms"]):
            return template
    return None


def normalize_diagram_labels(labels):
    if not isinstance(labels, list):
        return []
    normalized = [normalize_label(label, limit=80) for label in labels]
    return [label for label in normalized if label][:24]


def _legacy_to_nodes(raw_diagram):
    labels = normalize_diagram_labels(raw_diagram.get("labels", []))
    if raw_diagram.get("title") and raw_diagram.get("diagram_type") in {"organ", "cell", "relationship"}:
        labels = [raw_diagram["title"]] + labels
    return labels


def normalize_diagram_payload(raw_diagram):
    if isinstance(raw_diagram, str):
        try:
            raw_diagram = json.loads(raw_diagram)
        except json.JSONDecodeError:
            raw_diagram = {}

    if isinstance(raw_diagram, list):
        raw_diagram = {"nodes": [{"label": label} for label in raw_diagram]}
    if not isinstance(raw_diagram, dict):
        raw_diagram = {}

    raw_type = raw_diagram.get("type") or raw_diagram.get("diagram_type") or raw_diagram.get("visualization_type")
    visualization_required = raw_diagram.get("visualization_required")
    labels = _legacy_to_nodes(raw_diagram) if "labels" in raw_diagram else []
    nodes = normalize_nodes(raw_diagram.get("nodes"), labels=labels)
    node_ids = [node["id"] for node in nodes]
    raw_connections = (
        raw_diagram.get("connections")
        or raw_diagram.get("edges")
        or raw_diagram.get("relationships")
        or []
    )
    connections = normalize_connections(raw_connections, node_ids=node_ids)

    visualization_type = normalize_visualization_type(raw_type)
    if raw_type in {"none", "unavailable", "no_diagram"}:
        visualization_type = "none"

    return {
        "available": visualization_type != "none" and bool(nodes),
        "visualization_required": visualization_required,
        "decision_visualization_type": normalize_text(raw_diagram.get("decision_visualization_type") or ""),
        "type": visualization_type,
        "diagram_type": visualization_type,
        "title": normalize_text(raw_diagram.get("title", "")),
        "nodes": nodes,
        "connections": connections,
        "labels": [node["label"] for node in nodes],
        "reason": normalize_text(raw_diagram.get("reason") or raw_diagram.get("why") or ""),
        "confidence": raw_diagram.get("confidence", raw_diagram.get("confidence_score")),
        "explanation": normalize_text(raw_diagram.get("explanation") or raw_diagram.get("note") or ""),
        "notes": normalize_diagram_labels(raw_diagram.get("notes", [])),
        "template_key": normalize_text(raw_diagram.get("template_key") or ""),
    }


def _nodes_from_labels(labels):
    return [{"id": str(index), "label": label} for index, label in enumerate(labels, start=1)]


def _template_payload(template):
    nodes = normalize_nodes(_nodes_from_labels(template["nodes"]))
    connections = sequential_connections(nodes)
    if template["type"] in {"cycle", "orbit"} and len(nodes) > 2:
        connections.append({"from": nodes[-1]["id"], "to": nodes[0]["id"]})
    if template["type"] in {"tree", "hierarchy"} and len(nodes) > 2:
        root = nodes[0]["id"]
        connections = [{"from": root, "to": node["id"]} for node in nodes[1:]]
    if template["type"] in {"concept_map", "network_graph", "er_diagram"} and len(nodes) > 2:
        root = nodes[0]["id"]
        connections = [{"from": root, "to": node["id"]} for node in nodes[1:]]
    if template["type"] == "anatomy":
        root = nodes[0]["id"]
        connections = [{"from": root, "to": node["id"]} for node in nodes[1:]]
    return {
        "available": True,
        "template_key": template.get("key") or template["terms"][0].replace(" ", "_"),
        "type": template["type"],
        "diagram_type": template["type"],
        "title": template["title"],
        "nodes": nodes,
        "connections": connections,
        "labels": [node["label"] for node in nodes],
        "reason": template["reason"],
        "confidence": template["confidence"],
        "explanation": "",
        "notes": [],
    }


def _complete_payload(payload, subject="", topic=""):
    nodes = payload["nodes"]
    inferred_type = infer_type(subject, topic, payload.get("labels", []))
    visualization_type = payload["type"] if payload["type"] != "flowchart" else inferred_type
    visualization_type = normalize_visualization_type(visualization_type)
    connections = payload["connections"]
    if not connections and visualization_type not in {"matrix", "comparison", "layer", "pyramid"}:
        connections = sequential_connections(nodes)
        if visualization_type in {"cycle", "orbit"} and len(nodes) > 2:
            connections.append({"from": nodes[-1]["id"], "to": nodes[0]["id"]})
        if visualization_type in {"tree", "hierarchy", "organization_chart", "concept_map", "mind_map", "anatomy"} and len(nodes) > 2:
            root = nodes[0]["id"]
            connections = [{"from": root, "to": node["id"]} for node in nodes[1:]]

    reason = payload["reason"] or reason_for_type(visualization_type)
    confidence = payload["confidence"]
    if confidence is None:
        confidence = 0.86 if payload.get("template_key") else 0.82
    confidence = clamp_number(confidence, default=0.82)

    return {
        **payload,
        "available": bool(nodes),
        "visualization_required": True,
        "type": visualization_type,
        "diagram_type": visualization_type,
        "visualization_label": display_type(visualization_type),
        "title": safe_title(topic, payload.get("title")),
        "nodes": nodes,
        "connections": connections,
        "labels": [node["label"] for node in nodes],
        "reason": reason,
        "confidence": confidence,
        "confidence_percent": int(round(confidence * 100)),
        "explanation": payload.get("explanation") or "",
    }


def reason_for_type(visualization_type):
    reasons = {
        "cycle": "This topic repeats through stages, so a cycle makes the pattern easier to remember.",
        "timeline": "This topic depends on chronological order, so a timeline shows progression clearly.",
        "tree": "This topic branches from broad categories into smaller groups.",
        "hierarchy": "This topic describes levels, roles, or authority relationships.",
        "concept_map": "This topic has connected ideas that are easier to learn as a relationship map.",
        "mind_map": "This topic has a central idea with supporting branches.",
        "comparison": "This topic compares two or more ideas side by side.",
        "network_graph": "This topic is made of connected parts with multiple relationships.",
        "organization_chart": "This topic describes roles and reporting relationships.",
        "ecosystem": "This topic shows interacting living and non-living components.",
        "anatomy": "This topic needs labeled parts around a central structure.",
        "scientific_process": "This topic explains inputs, steps, and outcomes in a scientific process.",
        "layer": "This topic is organized in stacked levels.",
        "pyramid": "This topic is best shown as levels that narrow toward the top.",
        "matrix": "This topic needs row-and-column comparison.",
        "cause_and_effect": "This topic is about causes leading to an effect.",
        "orbit": "This topic is best shown with objects arranged around a central body.",
        "chain": "This topic moves in a direct one-way sequence.",
        "circuit": "This topic involves connected components in a closed path.",
        "er_diagram": "This topic describes entities and relationships.",
    }
    return reasons.get(visualization_type, "This layout best matches the structure of the topic.")


def build_diagram_payload(subject, topic, raw_diagram=None):
    payload = normalize_diagram_payload(raw_diagram)
    if payload.get("visualization_required") is False:
        reason = payload["reason"] or "This lesson is primarily text-based and is better learned through reading and examples."
        return {
            "available": False,
            "visualization_required": False,
            "visualization_type": payload.get("decision_visualization_type") or "none",
            "template_key": "none",
            "type": "none",
            "diagram_type": "none",
            "visualization_label": "No visualization",
            "title": safe_title(topic, f"{topic} Visualization" if topic else "Visualization"),
            "nodes": [],
            "connections": [],
            "labels": [],
            "reason": reason,
            "confidence": payload.get("confidence") or 0,
            "confidence_percent": int(round(clamp_number(payload.get("confidence"), default=0) * 100)),
            "explanation": payload.get("explanation") or reason,
            "notes": payload.get("notes") or ["No visualization required for this lesson."],
        }
    template = _template_for(subject, topic)
    if payload["available"]:
        if template and not payload.get("template_key"):
            payload["template_key"] = template.get("key") or template["terms"][0].replace(" ", "_")
        return _complete_payload(payload, subject=subject, topic=topic)

    if template:
        return _complete_payload(_template_payload(template), subject=subject, topic=topic)

    return {
        "available": False,
        "visualization_required": False,
        "visualization_type": "none",
        "template_key": "none",
        "type": "none",
        "diagram_type": "none",
        "visualization_label": "No visualization",
        "title": safe_title(topic, f"{topic} Visualization" if topic else "Visualization"),
        "nodes": [],
        "connections": [],
        "labels": [],
        "reason": "The AI did not return enough structured data to create a useful visualization.",
        "confidence": 0,
        "confidence_percent": 0,
        "explanation": "Try a concrete topic with parts, stages, events, comparisons, or relationships.",
        "notes": ["No visualization available for this topic."],
    }


def diagram_labels(payload, minimum=4):
    labels = normalize_diagram_labels(payload.get("labels", []))
    if len(labels) >= minimum:
        return labels
    return labels + [node.get("label", "") for node in payload.get("nodes", []) if node.get("label")][len(labels):minimum]


def create_diagram_svg_data_uri(diagram_payload):
    from .svg_renderer import render_educational_diagram_svg

    svg = render_educational_diagram_svg(diagram_payload)
    return f"data:image/svg+xml;charset=utf-8,{quote(svg)}"


def create_diagram_image(topic, diagram_payload):
    payload = diagram_payload if isinstance(diagram_payload, dict) else build_diagram_payload("", topic, diagram_payload)
    return create_diagram_svg_data_uri(payload)
