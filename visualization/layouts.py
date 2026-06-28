import math
import random
from collections import defaultdict, deque


NODE_WIDTH = 184
NODE_HEIGHT = 72
TITLE_HEIGHT = 92
PADDING = 56


def estimate_node_size(label):
    label = label or ""
    width = min(240, max(144, 88 + min(20, len(label)) * 5.2))
    lines = max(1, math.ceil(len(label) / 22))
    height = min(116, max(62, 42 + lines * 18))
    return width, height


def estimate_mind_map_node_size(label):
    label = label or ""
    normalized = " ".join(str(label).split())
    longest_word = max((len(word) for word in normalized.split()), default=0)
    width = min(320, max(160, 96 + min(34, len(normalized)) * 5.7, longest_word * 8.2 + 36))
    line_chars = max(16, int((width - 42) / 7.2))
    lines = max(1, min(5, math.ceil(max(1, len(normalized)) / line_chars)))
    height = max(70, 38 + lines * 18)
    return width, height, lines


def bounds_for(nodes):
    if not nodes:
        return 900, 560
    max_x = max(node["x"] + node["width"] / 2 for node in nodes)
    max_y = max(node["y"] + node["height"] / 2 for node in nodes)
    min_x = min(node["x"] - node["width"] / 2 for node in nodes)
    min_y = min(node["y"] - node["height"] / 2 for node in nodes)
    width = max(760, int(max_x - min_x + PADDING * 2))
    height = max(500, int(max_y - min_y + PADDING * 2))
    shift_x = PADDING - min_x
    shift_y = PADDING + TITLE_HEIGHT - min_y
    for node in nodes:
        node["x"] += shift_x
        node["y"] += shift_y
    return width, height + TITLE_HEIGHT


def decorate(nodes, kind="node"):
    for node in nodes:
        width, height = estimate_node_size(node.get("label", ""))
        node["width"] = node.get("width", width)
        node["height"] = node.get("height", height)
        node["kind"] = node.get("kind", kind)
    return nodes


def decorate_mind_map(nodes):
    for node in nodes:
        width, height, lines = estimate_mind_map_node_size(node.get("label", ""))
        node["width"] = node.get("width", width)
        node["height"] = node.get("height", height)
        node["text_max_lines"] = node.get("text_max_lines", lines)
        node["kind"] = node.get("kind", "node")
    return nodes


def vertical_flow(nodes, connections=None):
    laid_out = []
    gap = 42
    y = 0
    for index, node in enumerate(decorate([dict(item) for item in nodes])):
        node["x"] = 0
        node["y"] = y
        node["rank"] = index
        laid_out.append(node)
        y += node["height"] + gap
    return laid_out


def horizontal_flow(nodes, connections=None):
    laid_out = []
    gap = 74
    x = 0
    for index, node in enumerate(decorate([dict(item) for item in nodes])):
        node["x"] = x
        node["y"] = 0
        node["rank"] = index
        laid_out.append(node)
        x += node["width"] + gap
    return laid_out


def circular_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    count = max(1, len(items))
    radius = max(170, min(430, 48 * count))
    for index, node in enumerate(items):
        angle = -math.pi / 2 + index * 2 * math.pi / count
        node["x"] = math.cos(angle) * radius
        node["y"] = math.sin(angle) * radius
        node["angle"] = angle
    return items


def radial_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    if not items:
        return items
    items[0]["x"] = 0
    items[0]["y"] = 0
    items[0]["kind"] = "root"
    outer = items[1:]
    count = max(1, len(outer))
    radius = max(210, min(520, 54 * count))
    for index, node in enumerate(outer):
        angle = -math.pi / 2 + index * 2 * math.pi / count
        node["x"] = math.cos(angle) * radius
        node["y"] = math.sin(angle) * radius
        node["angle"] = angle
    return items


def timeline_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    gap = 210
    offset = -(len(items) - 1) * gap / 2
    for index, node in enumerate(items):
        node["x"] = offset + index * gap
        node["y"] = -92 if index % 2 == 0 else 92
        node["kind"] = "milestone"
        node["rank"] = index
    return items


def grid_layout(nodes, columns=None):
    items = decorate([dict(item) for item in nodes])
    count = len(items)
    if columns is None:
        columns = max(2, min(4, math.ceil(math.sqrt(count or 1))))
    cell_w = 260
    cell_h = 138
    for index, node in enumerate(items):
        row, column = divmod(index, columns)
        node["x"] = (column - (columns - 1) / 2) * cell_w
        node["y"] = row * cell_h
    return items


def comparison_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    if len(items) <= 2:
        return horizontal_flow(items)
    for index, node in enumerate(items):
        column = index % 2
        row = index // 2
        node["x"] = -160 if column == 0 else 160
        node["y"] = row * 118
        node["kind"] = "comparison"
    return items


def layer_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    for index, node in enumerate(items):
        node["x"] = 0
        node["y"] = index * 78
        node["width"] = max(320, 520 - index * 26)
        node["height"] = 62
        node["kind"] = "layer"
    return items


def pyramid_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    count = max(1, len(items))
    for index, node in enumerate(items):
        level = count - index
        node["x"] = 0
        node["y"] = index * 76
        node["width"] = 190 + level * 58
        node["height"] = 64
        node["kind"] = "pyramid"
    return items


def hierarchy_layout(nodes, connections=None):
    items = [dict(item) for item in nodes]
    decorate(items)
    if not items:
        return items

    by_id = {node["id"]: node for node in items}
    children = defaultdict(list)
    incoming = defaultdict(int)
    for edge in connections or []:
        start = edge.get("from")
        end = edge.get("to")
        if start in by_id and end in by_id:
            children[start].append(end)
            incoming[end] += 1

    roots = [node["id"] for node in items if incoming[node["id"]] == 0] or [items[0]["id"]]
    depths = {}
    queue = deque((root, 0) for root in roots)
    while queue:
        node_id, depth = queue.popleft()
        if node_id in depths and depths[node_id] <= depth:
            continue
        depths[node_id] = depth
        for child_id in children.get(node_id, []):
            queue.append((child_id, depth + 1))

    for node in items:
        depths.setdefault(node["id"], 0)

    levels = defaultdict(list)
    for node in items:
        levels[depths[node["id"]]].append(node)

    for depth, level_nodes in levels.items():
        gap = max(220, 760 / max(1, len(level_nodes)))
        start_x = -(len(level_nodes) - 1) * gap / 2
        for index, node in enumerate(level_nodes):
            node["x"] = start_x + index * gap
            node["y"] = depth * 132
            node["rank"] = depth
            node["kind"] = "root" if depth == 0 else "node"
    return items


def _mind_map_horizontal_gap(left, right, depth):
    size_gap = (left["width"] + right["width"]) * 0.18
    depth_gap = max(48, 76 - depth * 5)
    return max(58, size_gap, depth_gap)


def _mind_map_vertical_gap(parent, children):
    tallest_child = max((child["height"] for child in children), default=NODE_HEIGHT)
    return max(100, (parent["height"] + tallest_child) * 0.72)


def mind_map_layout(nodes, connections=None):
    items = decorate_mind_map([dict(item) for item in nodes])
    if not items:
        return items

    by_id = {node["id"]: node for node in items}
    children = defaultdict(list)
    parent_for = {}
    incoming = defaultdict(int)

    for edge in connections or []:
        start = edge.get("from")
        end = edge.get("to")
        if start not in by_id or end not in by_id or start == end or end in parent_for:
            continue
        children[start].append(end)
        parent_for[end] = start
        incoming[end] += 1

    root_id = next((node["id"] for node in items if incoming[node["id"]] == 0), items[0]["id"])
    for node in items:
        if node["id"] != root_id and node["id"] not in parent_for:
            children[root_id].append(node["id"])
            parent_for[node["id"]] = root_id

    reachable = set()

    def collect_reachable(node_id, ancestors=None):
        ancestors = set(ancestors or ())
        if node_id in ancestors:
            return
        reachable.add(node_id)
        for child_id in children.get(node_id, []):
            collect_reachable(child_id, ancestors | {node_id})

    collect_reachable(root_id)
    for node in items:
        if node["id"] != root_id and node["id"] not in reachable:
            children[root_id].append(node["id"])

    measured = {}

    def measure(node_id, depth=0, ancestors=None):
        ancestors = set(ancestors or ())
        node = by_id[node_id]
        valid_children = [
            child_id
            for child_id in children.get(node_id, [])
            if child_id in by_id and child_id not in ancestors
        ]
        children[node_id] = valid_children

        child_widths = []
        for child_id in valid_children:
            child_widths.append(measure(child_id, depth + 1, ancestors | {node_id}))

        if child_widths:
            gaps = sum(
                _mind_map_horizontal_gap(by_id[valid_children[index]], by_id[valid_children[index + 1]], depth + 1)
                for index in range(len(valid_children) - 1)
            )
            children_width = sum(child_widths) + gaps
        else:
            children_width = 0

        subtree_width = max(node["width"], children_width)
        node["subtree_width"] = subtree_width
        node["rank"] = depth
        node["kind"] = "root" if node_id == root_id else "node"
        measured[node_id] = subtree_width
        return subtree_width

    measure(root_id, 0, set())

    def assign(node_id, left, y):
        node = by_id[node_id]
        subtree_width = measured[node_id]
        center_x = left + subtree_width / 2
        node["x"] = center_x
        node["y"] = y
        node["subtree_left"] = left
        node["subtree_right"] = left + subtree_width

        child_ids = children.get(node_id, [])
        if not child_ids:
            return

        children_width = sum(measured[child_id] for child_id in child_ids)
        children_width += sum(
            _mind_map_horizontal_gap(by_id[child_ids[index]], by_id[child_ids[index + 1]], node["rank"] + 1)
            for index in range(len(child_ids) - 1)
        )
        child_left = center_x - children_width / 2
        child_y = y + node["height"] / 2 + _mind_map_vertical_gap(node, [by_id[child_id] for child_id in child_ids])
        for index, child_id in enumerate(child_ids):
            child = by_id[child_id]
            assign(child_id, child_left, child_y + child["height"] / 2)
            child_left += measured[child_id]
            if index < len(child_ids) - 1:
                child_left += _mind_map_horizontal_gap(child, by_id[child_ids[index + 1]], node["rank"] + 1)

    assign(root_id, -measured[root_id] / 2, 0)
    return items


def anatomy_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    if not items:
        return items
    items[0]["x"] = 0
    items[0]["y"] = 0
    items[0]["width"] = max(items[0]["width"], 220)
    items[0]["height"] = max(items[0]["height"], 112)
    items[0]["kind"] = "anatomy-core"
    labels = items[1:] if len(items) > 1 else []
    count = max(1, len(labels))
    radius_x = 330
    radius_y = 190
    for index, node in enumerate(labels):
        angle = -math.pi / 2 + index * 2 * math.pi / count
        node["x"] = math.cos(angle) * radius_x
        node["y"] = math.sin(angle) * radius_y
        node["kind"] = "label"
    return items


def cause_effect_layout(nodes, connections=None):
    items = decorate([dict(item) for item in nodes])
    if not items:
        return items
    effect = items[-1]
    effect["x"] = 360
    effect["y"] = 0
    effect["kind"] = "effect"
    causes = items[:-1]
    for index, node in enumerate(causes):
        node["x"] = -270 + (index % 3) * 185
        node["y"] = -130 if index % 2 == 0 else 130
        node["kind"] = "cause"
    return items


def force_directed_layout(nodes, connections=None, seed=42):
    items = decorate([dict(item) for item in nodes])
    count = len(items)
    if count <= 1:
        for node in items:
            node["x"] = 0
            node["y"] = 0
        return items
    if count <= 8:
        return radial_layout(items, connections)

    rng = random.Random(seed)
    radius = max(260, min(560, count * 34))
    for index, node in enumerate(items):
        angle = index * 2 * math.pi / count
        node["x"] = math.cos(angle) * radius + rng.uniform(-20, 20)
        node["y"] = math.sin(angle) * radius + rng.uniform(-20, 20)

    by_id = {node["id"]: node for node in items}
    edges = [
        (by_id[edge["from"]], by_id[edge["to"]])
        for edge in connections or []
        if edge.get("from") in by_id and edge.get("to") in by_id
    ]

    area = max(900 * 650, count * 80000)
    k = math.sqrt(area / count)
    for iteration in range(90):
        displacements = {node["id"]: [0.0, 0.0] for node in items}
        for i, left in enumerate(items):
            for right in items[i + 1:]:
                dx = left["x"] - right["x"]
                dy = left["y"] - right["y"]
                distance = max(24, math.hypot(dx, dy))
                force = (k * k) / distance
                fx = dx / distance * force
                fy = dy / distance * force
                displacements[left["id"]][0] += fx
                displacements[left["id"]][1] += fy
                displacements[right["id"]][0] -= fx
                displacements[right["id"]][1] -= fy
        for start, end in edges:
            dx = start["x"] - end["x"]
            dy = start["y"] - end["y"]
            distance = max(24, math.hypot(dx, dy))
            force = (distance * distance) / k
            fx = dx / distance * force
            fy = dy / distance * force
            displacements[start["id"]][0] -= fx
            displacements[start["id"]][1] -= fy
            displacements[end["id"]][0] += fx
            displacements[end["id"]][1] += fy
        temperature = max(10, 90 * (1 - iteration / 90))
        for node in items:
            dx, dy = displacements[node["id"]]
            distance = max(1, math.hypot(dx, dy))
            node["x"] += dx / distance * min(abs(dx), temperature)
            node["y"] += dy / distance * min(abs(dy), temperature)
    return items


def layout_for_type(visualization_type, nodes, connections=None):
    if visualization_type in {"flowchart"}:
        return vertical_flow(nodes, connections)
    if visualization_type in {"process", "scientific_process", "chain", "circuit", "er_diagram"}:
        return horizontal_flow(nodes, connections)
    if visualization_type in {"cycle", "orbit"}:
        return circular_layout(nodes, connections)
    if visualization_type == "timeline":
        return timeline_layout(nodes, connections)
    if visualization_type in {"tree", "hierarchy", "organization_chart"}:
        return hierarchy_layout(nodes, connections)
    if visualization_type == "mind_map":
        return mind_map_layout(nodes, connections)
    if visualization_type in {"concept_map", "network_graph", "ecosystem"}:
        return force_directed_layout(nodes, connections)
    if visualization_type == "comparison":
        return comparison_layout(nodes, connections)
    if visualization_type == "matrix":
        return grid_layout(nodes)
    if visualization_type == "anatomy":
        return anatomy_layout(nodes, connections)
    if visualization_type == "layer":
        return layer_layout(nodes, connections)
    if visualization_type == "pyramid":
        return pyramid_layout(nodes, connections)
    if visualization_type == "cause_and_effect":
        return cause_effect_layout(nodes, connections)
    return vertical_flow(nodes, connections)
