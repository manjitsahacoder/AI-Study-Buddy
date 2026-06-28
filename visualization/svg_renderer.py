import math
from html import escape

from .layouts import bounds_for, layout_for_type
from .planner import build_diagram_payload
from .schemas import display_type, normalize_visualization_type


PALETTE = [
    ("#e0f2fe", "#0284c7"),
    ("#dcfce7", "#16a34a"),
    ("#fef3c7", "#d97706"),
    ("#fce7f3", "#db2777"),
    ("#ede9fe", "#7c3aed"),
    ("#ccfbf1", "#0f766e"),
    ("#fee2e2", "#dc2626"),
    ("#e2e8f0", "#475569"),
]


def wrap_words(text, max_chars=22, max_lines=3):
    words = str(text or "").split()
    if not words:
        return [""]
    lines = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            while len(word) > max_chars:
                lines.append(word[:max_chars])
                word = word[max_chars:]
            current = word
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words and " ".join(lines) != " ".join(words):
        lines[-1] = f"{lines[-1][: max(0, max_chars - 1)]}..."
    return lines or [str(text or "")[:max_chars]]


def svg_text_lines(x, y, lines, css_class="viz-label", anchor="middle", line_height=17):
    total = (len(lines) - 1) * line_height
    tspans = []
    for index, line in enumerate(lines):
        dy = -total / 2 + index * line_height
        tspans.append(
            f'<tspan x="{x:.1f}" dy="{dy if index == 0 else line_height:.1f}">{escape(line)}</tspan>'
        )
    return f'<text class="{css_class}" text-anchor="{anchor}" dominant-baseline="middle">{"".join(tspans)}</text>'


def center_of(node):
    return node["x"], node["y"]


def edge_path(start, end, curve=0.18):
    sx, sy = center_of(start)
    ex, ey = center_of(end)
    dx = ex - sx
    dy = ey - sy
    distance = max(1, math.hypot(dx, dy))
    sx += dx / distance * (start["width"] / 2)
    sy += dy / distance * (start["height"] / 2)
    ex -= dx / distance * (end["width"] / 2 + 8)
    ey -= dy / distance * (end["height"] / 2 + 8)
    if abs(dx) > abs(dy):
        c1x = sx + dx * curve
        c1y = sy
        c2x = ex - dx * curve
        c2y = ey
    else:
        c1x = sx
        c1y = sy + dy * curve
        c2x = ex
        c2y = ey - dy * curve
    return f"M {sx:.1f} {sy:.1f} C {c1x:.1f} {c1y:.1f}, {c2x:.1f} {c2y:.1f}, {ex:.1f} {ey:.1f}"


def render_node(node, index, visualization_type):
    fill, stroke = PALETTE[index % len(PALETTE)]
    x = node["x"] - node["width"] / 2
    y = node["y"] - node["height"] / 2
    max_lines = int(node.get("text_max_lines") or 3)
    label_lines = wrap_words(node.get("label", ""), max_chars=max(13, int(node["width"] / 8)), max_lines=max_lines)
    node_id = escape(str(node.get("id", index)))
    node_class = f"viz-node viz-node-{escape(node.get('kind', 'node'))}"

    if visualization_type == "cycle":
        radius = max(42, min(72, node["width"] / 2))
        shape = (
            f'<circle class="viz-node-shape" cx="{node["x"]:.1f}" cy="{node["y"]:.1f}" r="{radius:.1f}" '
            f'fill="url(#nodeGradient{index % len(PALETTE)})" stroke="{stroke}"/>'
        )
    elif visualization_type == "pyramid":
        shape = (
            f'<rect class="viz-node-shape" x="{x:.1f}" y="{y:.1f}" width="{node["width"]:.1f}" '
            f'height="{node["height"]:.1f}" rx="10" fill="url(#nodeGradient{index % len(PALETTE)})" stroke="{stroke}"/>'
        )
    else:
        shape = (
            f'<rect class="viz-node-shape" x="{x:.1f}" y="{y:.1f}" width="{node["width"]:.1f}" '
            f'height="{node["height"]:.1f}" rx="16" fill="url(#nodeGradient{index % len(PALETTE)})" stroke="{stroke}"/>'
        )

    description = escape(node.get("description", "") or node.get("label", ""))
    return f"""
    <g class="{node_class}" tabindex="0" role="button" data-node-id="{node_id}" aria-label="{escape(node.get("label", ""))}">
        <title>{description}</title>
        {shape}
        {svg_text_lines(node["x"], node["y"], label_lines)}
    </g>
    """


def render_timeline_axis(nodes):
    if not nodes:
        return ""
    left = min(node["x"] for node in nodes) - 90
    right = max(node["x"] for node in nodes) + 90
    y = sum(node["y"] for node in nodes) / len(nodes)
    markers = "".join(
        f'<circle class="viz-milestone-dot" cx="{node["x"]:.1f}" cy="{y:.1f}" r="8"/>'
        f'<path class="viz-soft-line" d="M {node["x"]:.1f} {y:.1f} L {node["x"]:.1f} {node["y"]:.1f}"/>'
        for node in nodes
    )
    return f'<path class="viz-axis" d="M {left:.1f} {y:.1f} L {right:.1f} {y:.1f}"/>{markers}'


def render_cause_spine(nodes):
    if not nodes:
        return ""
    y = nodes[-1]["y"]
    left = min(node["x"] for node in nodes) - 120
    right = nodes[-1]["x"] - nodes[-1]["width"] / 2
    return f'<path class="viz-axis" marker-end="url(#vizArrow)" d="M {left:.1f} {y:.1f} L {right:.1f} {y:.1f}"/>'


def render_orbit_guides(nodes):
    if len(nodes) < 2:
        return ""
    center = nodes[0]
    guides = []
    for node in nodes[1:]:
        rx = abs(node["x"] - center["x"])
        ry = max(60, abs(node["y"] - center["y"]) * 0.72 + 80)
        guides.append(
            f'<ellipse class="viz-orbit" cx="{center["x"]:.1f}" cy="{center["y"]:.1f}" rx="{rx:.1f}" ry="{ry:.1f}"/>'
        )
    return "".join(guides)


def render_edges(nodes, connections):
    by_id = {node["id"]: node for node in nodes}
    rendered = []
    for edge in connections:
        start = by_id.get(edge.get("from"))
        end = by_id.get(edge.get("to"))
        if not start or not end:
            continue
        path_id = f"edge-{escape(str(edge.get('from')))}-{escape(str(edge.get('to')))}"
        rendered.append(
            f'<path id="{path_id}" class="viz-edge" data-from="{escape(str(edge.get("from")))}" '
            f'data-to="{escape(str(edge.get("to")))}" marker-end="url(#vizArrow)" d="{edge_path(start, end)}"/>'
        )
        if edge.get("label"):
            sx, sy = center_of(start)
            ex, ey = center_of(end)
            rendered.append(
                f'<text class="viz-edge-label" x="{(sx + ex) / 2:.1f}" y="{(sy + ey) / 2 - 8:.1f}" text-anchor="middle">'
                f'{escape(edge["label"])}</text>'
            )
    return "".join(rendered)


def svg_defs():
    gradients = []
    for index, (fill, stroke) in enumerate(PALETTE):
        gradients.append(
            f"""
            <linearGradient id="nodeGradient{index}" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="{fill}"/>
                <stop offset="100%" stop-color="#ffffff"/>
            </linearGradient>
            """
        )
    return f"""
    <defs>
        {"".join(gradients)}
        <linearGradient id="vizSurface" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#f8fbff"/>
            <stop offset="100%" stop-color="#eef6ff"/>
        </linearGradient>
        <filter id="vizShadow" x="-20%" y="-20%" width="140%" height="150%">
            <feDropShadow dx="0" dy="10" stdDeviation="9" flood-color="#0f172a" flood-opacity="0.14"/>
        </filter>
        <marker id="vizArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--viz-edge)"/>
        </marker>
        <style>
            .ai-visualization-svg {{
                --viz-ink: #172033;
                --viz-muted: #64748b;
                --viz-edge: #3157d5;
                --viz-soft-edge: rgba(49, 87, 213, 0.28);
                --viz-panel: #ffffff;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                max-width: 100%;
                height: auto;
            }}
            .viz-bg {{ fill: url(#vizSurface); }}
            .viz-panel {{ fill: var(--viz-panel); stroke: rgba(49, 87, 213, 0.16); }}
            .viz-title {{ font-size: 30px; font-weight: 850; fill: var(--viz-ink); }}
            .viz-subtitle {{ font-size: 13px; font-weight: 750; letter-spacing: 0; fill: var(--viz-muted); }}
            .viz-label {{ font-size: 14px; font-weight: 800; fill: var(--viz-ink); pointer-events: none; }}
            .viz-edge {{
                fill: none;
                stroke: var(--viz-edge);
                stroke-width: 3;
                stroke-linecap: round;
                opacity: 0.86;
                stroke-dasharray: 900;
                stroke-dashoffset: 900;
                animation: viz-draw 900ms ease forwards;
            }}
            .viz-edge.is-active {{ stroke-width: 5; opacity: 1; }}
            .viz-soft-line {{ fill: none; stroke: var(--viz-soft-edge); stroke-width: 2.5; stroke-linecap: round; }}
            .viz-edge-label {{ font-size: 11px; font-weight: 800; fill: var(--viz-muted); paint-order: stroke; stroke: var(--viz-panel); stroke-width: 4; }}
            .viz-axis {{ fill: none; stroke: var(--viz-edge); stroke-width: 5; stroke-linecap: round; }}
            .viz-orbit {{ fill: none; stroke: rgba(100, 116, 139, 0.24); stroke-width: 2; stroke-dasharray: 8 8; }}
            .viz-milestone-dot {{ fill: var(--viz-edge); stroke: #ffffff; stroke-width: 3; }}
            .viz-node {{ cursor: pointer; transition: transform 180ms ease, opacity 180ms ease; transform-origin: center; }}
            .viz-node-shape {{ stroke-width: 2.5; filter: url(#vizShadow); transition: stroke-width 180ms ease, filter 180ms ease; }}
            .viz-node:hover .viz-node-shape,
            .viz-node:focus-visible .viz-node-shape,
            .viz-node.is-active .viz-node-shape {{ stroke-width: 4; filter: url(#vizShadow); }}
            .viz-node.is-dimmed {{ opacity: 0.32; }}
            .viz-node-root .viz-node-shape,
            .viz-node-anatomy-core .viz-node-shape,
            .viz-node-effect .viz-node-shape {{ stroke-width: 4; }}
            @keyframes viz-draw {{ to {{ stroke-dashoffset: 0; }} }}
            @media (prefers-color-scheme: dark) {{
                .ai-visualization-svg {{
                    --viz-ink: #e5e7eb;
                    --viz-muted: #a8b3c7;
                    --viz-edge: #86a1ff;
                    --viz-soft-edge: rgba(134, 161, 255, 0.32);
                    --viz-panel: #111827;
                }}
                .viz-bg {{ fill: #0f172a; }}
                .viz-panel {{ fill: #111827; stroke: rgba(134, 161, 255, 0.22); }}
                .viz-node-shape {{ fill-opacity: 0.9; }}
            }}
        </style>
    </defs>
    """


def render_unavailable(payload):
    title = escape(payload.get("title") or "Visualization")
    message = escape(payload.get("notes", ["No visualization available for this topic."])[0])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" class="ai-visualization-svg" viewBox="0 0 900 520" role="img" aria-label="{title}">
    {svg_defs()}
    <rect class="viz-bg" width="900" height="520" rx="28"/>
    <rect class="viz-panel" x="36" y="36" width="828" height="448" rx="24"/>
    <text class="viz-title" x="450" y="208" text-anchor="middle">No visualization available</text>
    <text class="viz-subtitle" x="450" y="252" text-anchor="middle">{message}</text>
    <text class="viz-subtitle" x="450" y="284" text-anchor="middle">Try a topic with parts, stages, events, comparisons, or relationships.</text>
</svg>"""


def render_educational_diagram_svg(payload):
    if not isinstance(payload, dict):
        payload = build_diagram_payload("", "", payload)
    if not payload.get("available"):
        return render_unavailable(payload)

    visualization_type = normalize_visualization_type(payload.get("type") or payload.get("diagram_type"))
    nodes = layout_for_type(visualization_type, payload.get("nodes", []), payload.get("connections", []))
    width, height = bounds_for(nodes)
    by_id = {node["id"]: node for node in nodes}
    connections = [
        edge for edge in payload.get("connections", [])
        if edge.get("from") in by_id and edge.get("to") in by_id
    ]
    content = []
    if visualization_type == "timeline":
        content.append(render_timeline_axis(nodes))
    if visualization_type == "cause_and_effect":
        content.append(render_cause_spine(nodes))
    if visualization_type == "orbit":
        content.append(render_orbit_guides(nodes))
    content.append(render_edges(nodes, connections))
    content.extend(render_node(node, index, visualization_type) for index, node in enumerate(nodes))

    title = escape(payload.get("title") or "AI Visualization")
    type_label = escape(payload.get("visualization_label") or display_type(visualization_type))
    node_count = len(nodes)
    edge_count = len(connections)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" class="ai-visualization-svg" viewBox="0 0 {width} {height}" role="img" aria-label="{title}">
    {svg_defs()}
    <rect class="viz-bg" width="{width}" height="{height}" rx="28"/>
    <rect class="viz-panel" x="28" y="28" width="{width - 56}" height="{height - 56}" rx="24"/>
    <text class="viz-title" x="{width / 2:.1f}" y="58" text-anchor="middle">{title}</text>
    <text class="viz-subtitle" x="{width / 2:.1f}" y="84" text-anchor="middle">{type_label} | {node_count} nodes | {edge_count} connections</text>
    <g class="viz-viewport" data-viz-viewport>
        {"".join(content)}
    </g>
</svg>"""
