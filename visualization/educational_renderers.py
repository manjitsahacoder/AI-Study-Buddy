from html import escape
import re


WIDTH = 980
HEIGHT = 640


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _labels(payload, fallback=None, limit=12):
    fallback = fallback or []
    raw_labels = payload.get("labels") or []
    labels = [str(label).strip() for label in raw_labels if str(label).strip()]
    if not labels:
        nodes = payload.get("nodes") or []
        labels = [str(node.get("label", "")).strip() for node in nodes if str(node.get("label", "")).strip()]
    combined = labels[:]
    for item in fallback:
        if len(combined) >= min(limit, len(fallback)):
            break
        if item not in combined:
            combined.append(item)
    return (combined or fallback)[:limit]


def _text(x, y, text, css_class="edu-label", anchor="middle"):
    return f'<text class="{css_class}" x="{x}" y="{y}" text-anchor="{anchor}">{escape(str(text))}</text>'


def _wrapped_lines(text, width=18, max_lines=3):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines or [""]


def _wrapped_text(x, y, text, width=18, css_class="edu-label", anchor="middle", line_height=17, max_lines=3):
    lines = _wrapped_lines(text, width=width, max_lines=max_lines)
    tspans = []
    offset = -((len(lines) - 1) * line_height) / 2
    for index, line in enumerate(lines):
        dy = offset if index == 0 else line_height
        tspans.append(f'<tspan x="{x}" dy="{dy}">{escape(line)}</tspan>')
    return f'<text class="{css_class}" text-anchor="{anchor}" dominant-baseline="middle">{"".join(tspans)}</text>'


def _label_box(x, y, text, width=148, height=42, theme="white", anchor="middle"):
    lines = _wrapped_lines(text, width=max(12, int(width / 8.5)), max_lines=2)
    if len(lines) > 1:
        height = max(height, 56)
    if anchor == "start":
        rect_x = x
        text_x = x + width / 2
    elif anchor == "end":
        rect_x = x - width
        text_x = x - width / 2
    else:
        rect_x = x - width / 2
        text_x = x
    rect_y = y - height / 2
    return f"""
    <g class="edu-label-box edu-label-{escape(theme)}">
        <rect x="{rect_x:.1f}" y="{rect_y:.1f}" width="{width}" height="{height}" rx="13"/>
        {_wrapped_text(text_x, y, text, width=max(12, int(width / 8.5)), css_class="edu-box-text", max_lines=2)}
    </g>
    """


def _callout(x1, y1, x2, y2, label, width=150, anchor="start", theme="white"):
    text_x = x2 + (10 if anchor == "start" else -10 if anchor == "end" else 0)
    return f"""
    <path class="edu-callout-line" d="M{x1} {y1} C{(x1 + x2) / 2:.1f} {y1}, {(x1 + x2) / 2:.1f} {y2}, {x2} {y2}"/>
    <circle class="edu-callout-dot" cx="{x1}" cy="{y1}" r="4.5"/>
    {_label_box(text_x, y2, label, width=width, anchor=anchor, theme=theme)}
    """


def _arrow_path(path, css_class="edu-arrow", marker="eduArrow"):
    return f'<path class="{css_class}" marker-end="url(#{marker})" d="{path}"/>'


def _legend(items, x=704, y=500, width=206):
    rows = []
    for index, (color, label) in enumerate(items[:5]):
        row_y = y + 36 + index * 24
        rows.append(
            f'<circle cx="{x + 18}" cy="{row_y}" r="6" fill="{color}"/>'
            f'<text class="edu-legend-text" x="{x + 34}" y="{row_y + 4}">{escape(label)}</text>'
        )
    height = 52 + len(rows) * 24
    return f"""
    <g class="edu-legend">
        <rect x="{x}" y="{y}" width="{width}" height="{height}" rx="16"/>
        <text class="edu-legend-title" x="{x + 18}" y="{y + 24}">Legend</text>
        {"".join(rows)}
    </g>
    """


def _cloud(x, y, scale=1):
    return f"""
    <g class="edu-cloud" transform="translate({x} {y}) scale({scale})">
        <path d="M-72 20 C-72 -8 -44 -22 -20 -10 C-8 -38 42 -38 56 -8 C82 -10 104 8 104 34 C104 62 78 76 44 76 L-42 76 C-76 76 -104 60 -104 34 C-104 10 -90 0 -72 20 Z"/>
    </g>
    """


def _defs():
    return """
    <defs>
        <linearGradient id="eduPaper" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#f8fbff"/>
            <stop offset="100%" stop-color="#eef7f1"/>
        </linearGradient>
        <linearGradient id="eduSun" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#fde68a"/>
            <stop offset="100%" stop-color="#f59e0b"/>
        </linearGradient>
        <radialGradient id="eduSunGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#fef3c7" stop-opacity="0.9"/>
            <stop offset="100%" stop-color="#fde68a" stop-opacity="0"/>
        </radialGradient>
        <linearGradient id="eduLeaf" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#bbf7d0"/>
            <stop offset="100%" stop-color="#16a34a"/>
        </linearGradient>
        <linearGradient id="eduWater" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#bae6fd"/>
            <stop offset="100%" stop-color="#0284c7"/>
        </linearGradient>
        <linearGradient id="eduCell" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#dcfce7"/>
            <stop offset="100%" stop-color="#f0fdf4"/>
        </linearGradient>
        <linearGradient id="eduAnimalCell" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#ede9fe"/>
            <stop offset="100%" stop-color="#fdf2f8"/>
        </linearGradient>
        <linearGradient id="eduOcean" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#38bdf8"/>
            <stop offset="100%" stop-color="#0ea5e9"/>
        </linearGradient>
        <filter id="eduShadow" x="-20%" y="-20%" width="140%" height="160%">
            <feDropShadow dx="0" dy="9" stdDeviation="8" flood-color="#0f172a" flood-opacity="0.16"/>
        </filter>
        <filter id="eduGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="12" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <marker id="eduArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto">
            <path d="M0 0 L10 5 L0 10 z" fill="var(--edu-arrow)"/>
        </marker>
        <marker id="eduInputArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto">
            <path d="M0 0 L10 5 L0 10 z" fill="#0284c7"/>
        </marker>
        <marker id="eduOutputArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto">
            <path d="M0 0 L10 5 L0 10 z" fill="#16a34a"/>
        </marker>
        <style>
            .ai-visualization-svg {
                --edu-ink: #172033;
                --edu-muted: #64748b;
                --edu-panel: #ffffff;
                --edu-line: rgba(49, 87, 213, 0.28);
                --edu-arrow: #3157d5;
                font-family: "Inter", "Segoe UI", Arial, sans-serif;
                max-width: 100%;
                height: auto;
            }
            .edu-bg { fill: url(#eduPaper); }
            .edu-panel { fill: var(--edu-panel); stroke: var(--edu-line); }
            .edu-title { fill: var(--edu-ink); font-size: 34px; font-weight: 880; }
            .edu-subtitle { fill: var(--edu-muted); font-size: 15px; font-weight: 780; letter-spacing: 0; }
            .edu-label { fill: var(--edu-ink); font-size: 16px; font-weight: 840; }
            .edu-small { fill: var(--edu-muted); font-size: 13px; font-weight: 780; }
            .edu-box-text { fill: var(--edu-ink); font-size: 14px; font-weight: 850; }
            .edu-label-box rect { fill: rgba(255,255,255,0.96); stroke: rgba(49,87,213,0.24); stroke-width: 1.5; filter: url(#eduShadow); }
            .edu-label-green rect { fill: #ecfdf5; stroke: rgba(22,163,74,0.32); }
            .edu-label-blue rect { fill: #eff6ff; stroke: rgba(2,132,199,0.32); }
            .edu-label-yellow rect { fill: #fffbeb; stroke: rgba(217,119,6,0.32); }
            .edu-label-purple rect { fill: #faf5ff; stroke: rgba(124,58,237,0.32); }
            .edu-callout-line { fill: none; stroke: var(--edu-arrow); stroke-width: 2.4; stroke-linecap: round; opacity: 0.8; }
            .edu-callout-dot { fill: var(--edu-arrow); stroke: #ffffff; stroke-width: 2; }
            .edu-arrow { fill: none; stroke: var(--edu-arrow); stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; }
            .edu-arrow-input { fill: none; stroke: #0284c7; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; marker-end: url(#eduInputArrow); }
            .edu-arrow-output { fill: none; stroke: #16a34a; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; marker-end: url(#eduOutputArrow); }
            .edu-arrow-energy { fill: none; stroke: #f59e0b; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; marker-end: url(#eduArrow); }
            .edu-soft-line { fill: none; stroke: var(--edu-line); stroke-width: 2.2; stroke-linecap: round; }
            .edu-shadow { filter: url(#eduShadow); }
            .edu-cloud path { fill: #ffffff; stroke: #cbd5e1; stroke-width: 2; filter: url(#eduShadow); }
            .edu-legend rect { fill: rgba(255,255,255,0.94); stroke: rgba(100,116,139,0.22); filter: url(#eduShadow); }
            .edu-legend-title { fill: var(--edu-ink); font-size: 14px; font-weight: 880; }
            .edu-legend-text { fill: var(--edu-muted); font-size: 12px; font-weight: 780; }
            .edu-illustration { transform-origin: center; }
            @media (max-width: 640px) {
                .edu-title { font-size: 28px; }
                .edu-subtitle { font-size: 13px; }
                .edu-label { font-size: 14px; }
                .edu-box-text { font-size: 12px; }
                .edu-legend-text { font-size: 11px; }
            }
            @media (prefers-color-scheme: dark) {
                .ai-visualization-svg {
                    --edu-ink: #e5e7eb;
                    --edu-muted: #a8b3c7;
                    --edu-panel: #111827;
                    --edu-line: rgba(134, 161, 255, 0.24);
                    --edu-arrow: #86a1ff;
                }
                .edu-bg { fill: #0f172a; }
                .edu-panel { fill: #111827; stroke: rgba(134, 161, 255, 0.24); }
                .edu-label-box rect, .edu-legend rect { fill: rgba(15,23,42,0.96); stroke: rgba(134,161,255,0.24); }
                .edu-callout-dot { stroke: #111827; }
                .edu-cloud path { fill: #1f2937; stroke: rgba(148,163,184,0.42); }
            }
        </style>
    </defs>
    """


def _wrap_svg(title, subtitle, body, width=WIDTH, height=HEIGHT, template="illustration"):
    title = escape(title or "AI Visualization")
    subtitle = escape(subtitle or "Educational illustration")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" class="ai-visualization-svg edu-template-{escape(template)}" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{title}">
    {_defs()}
    <rect class="edu-bg" width="{width}" height="{height}" rx="28"/>
    <rect class="edu-panel" x="26" y="26" width="{width - 52}" height="{height - 52}" rx="24"/>
    <text class="edu-title" x="{width / 2}" y="60" text-anchor="middle">{title}</text>
    <text class="edu-subtitle" x="{width / 2}" y="86" text-anchor="middle">{subtitle}</text>
    <g class="edu-illustration" data-edu-template="{escape(template)}">
        {body}
    </g>
</svg>"""


def render_photosynthesis(payload):
    labels = _labels(payload, ["Sunlight", "Water", "Carbon dioxide", "Oxygen", "Glucose", "Leaf"])
    body = f"""
    <circle cx="158" cy="166" r="92" fill="url(#eduSunGlow)" filter="url(#eduGlow)"/>
    <g class="edu-shadow">
        <circle cx="158" cy="166" r="54" fill="url(#eduSun)"/>
        <g stroke="#f59e0b" stroke-width="7" stroke-linecap="round">
            <path d="M158 76 L158 44"/><path d="M158 288 L158 254"/>
            <path d="M68 166 L34 166"/><path d="M282 166 L246 166"/>
            <path d="M94 102 L70 78"/><path d="M222 230 L248 256"/>
            <path d="M222 102 L248 78"/><path d="M94 230 L70 256"/>
        </g>
    </g>
    {_label_box(158, 248, labels[0], width=126, theme="yellow")}
    <path class="edu-shadow" fill="url(#eduLeaf)" stroke="#15803d" stroke-width="3" d="M358 380 C425 190 662 158 790 302 C660 452 468 482 358 380 Z"/>
    <path d="M382 368 C504 326 620 286 766 302" class="edu-soft-line"/>
    <path d="M445 346 C484 360 548 350 612 314" class="edu-soft-line"/>
    <path d="M548 312 C590 330 642 324 708 304" class="edu-soft-line"/>
    <path d="M356 382 C328 420 308 452 286 492" stroke="#15803d" stroke-width="14" stroke-linecap="round"/>
    <path fill="url(#eduWater)" d="M224 462 C224 426 260 392 260 392 C260 392 296 426 296 462 C296 486 280 502 260 502 C240 502 224 486 224 462 Z"/>
    {_label_box(260, 540, labels[1], width=118, theme="blue")}
    <g fill="#e0f2fe" stroke="#0284c7" stroke-width="2.5" class="edu-shadow">
        <circle cx="312" cy="262" r="22"/><circle cx="350" cy="278" r="22"/><circle cx="388" cy="262" r="22"/>
    </g>
    {_label_box(350, 218, labels[2], width=158, theme="blue")}
    <rect x="714" y="472" width="146" height="50" rx="24" fill="#fef3c7" stroke="#d97706" stroke-width="2.5" class="edu-shadow"/>
    {_wrapped_text(787, 497, labels[4], width=16)}
    <g fill="#dcfce7" stroke="#16a34a" stroke-width="2.5" class="edu-shadow">
        <circle cx="824" cy="190" r="19"/><circle cx="852" cy="174" r="19"/>
    </g>
    {_label_box(820, 128, labels[3], width=132, theme="green")}
    <path class="edu-arrow-energy" d="M220 202 C282 236 342 264 430 306"/>
    <path class="edu-arrow-input" d="M396 270 C446 282 480 296 520 324"/>
    <path class="edu-arrow-input" d="M298 464 C388 430 444 394 500 358"/>
    <path class="edu-arrow-output" d="M732 282 C780 246 812 230 834 200"/>
    <path class="edu-arrow-output" d="M692 398 C748 420 780 446 792 472"/>
    {_label_box(582, 432, labels[5], width=104, theme="green")}
    {_legend([("#f59e0b", "Energy"), ("#0284c7", "Inputs"), ("#16a34a", "Outputs"), ("#22c55e", "Plant structure")], x=56, y=498, width=190)}
    """
    return _wrap_svg(payload.get("title") or "Photosynthesis", "Inputs and outputs in a green leaf", body, template="photosynthesis")


def render_plant_cell(payload):
    labels = _labels(payload, ["Cell wall", "Cell membrane", "Nucleus", "Chloroplast", "Vacuole", "Cytoplasm"])
    body = f"""
    <rect class="edu-shadow" x="278" y="172" width="424" height="302" rx="66" fill="#bbf7d0" stroke="#15803d" stroke-width="12"/>
    <rect x="296" y="190" width="388" height="266" rx="54" fill="url(#eduCell)" stroke="#22c55e" stroke-width="4"/>
    <ellipse cx="482" cy="320" rx="92" ry="62" fill="#dbeafe" stroke="#0284c7" stroke-width="3"/>
    <circle cx="586" cy="274" r="42" fill="#f5d0fe" stroke="#a21caf" stroke-width="3"/>
    <circle cx="586" cy="274" r="15" fill="#c084fc"/>
    <g fill="#22c55e" stroke="#15803d" stroke-width="2.5">
        <ellipse cx="374" cy="256" rx="35" ry="19" transform="rotate(-24 374 256)"/>
        <ellipse cx="402" cy="378" rx="35" ry="19" transform="rotate(20 402 378)"/>
        <ellipse cx="622" cy="374" rx="35" ry="19" transform="rotate(-18 622 374)"/>
        <ellipse cx="628" cy="228" rx="30" ry="16" transform="rotate(22 628 228)"/>
    </g>
    <path d="M340 236 C428 210 560 210 650 250" fill="none" stroke="#86efac" stroke-width="12" opacity="0.58"/>
    {_callout(280, 276, 108, 190, labels[0], width=132, theme="green")}
    {_callout(300, 350, 110, 330, labels[1], width=150, theme="green")}
    {_callout(586, 274, 760, 198, labels[2], width=126, theme="purple")}
    {_callout(374, 256, 118, 470, labels[3], width=144, theme="green")}
    {_callout(482, 320, 760, 332, labels[4], width=128, theme="blue")}
    {_callout(446, 430, 760, 452, labels[5], width=130, theme="green")}
    {_legend([("#15803d", "Cell boundary"), ("#0284c7", "Vacuole"), ("#a21caf", "Nucleus"), ("#22c55e", "Chloroplasts")], x=390, y=500, width=212)}
    """
    return _wrap_svg(payload.get("title") or "Plant Cell", "Labeled organelles in a plant cell", body, template="plant_cell")


def render_animal_cell(payload):
    labels = _labels(payload, ["Cell membrane", "Cytoplasm", "Nucleus", "Mitochondria", "Ribosomes"])
    body = f"""
    <path class="edu-shadow" d="M286 352 C258 224 360 158 496 164 C640 170 732 260 688 386 C650 496 512 510 398 472 C330 450 296 416 286 352 Z" fill="url(#eduAnimalCell)" stroke="#7c3aed" stroke-width="5"/>
    <circle cx="520" cy="322" r="62" fill="#f5d0fe" stroke="#a21caf" stroke-width="3"/>
    <circle cx="520" cy="322" r="20" fill="#c084fc"/>
    <g fill="#fecaca" stroke="#dc2626" stroke-width="2.8">
        <ellipse cx="404" cy="278" rx="38" ry="19" transform="rotate(25 404 278)"/>
        <ellipse cx="612" cy="394" rx="38" ry="19" transform="rotate(-22 612 394)"/>
        <ellipse cx="604" cy="246" rx="30" ry="16" transform="rotate(18 604 246)"/>
    </g>
    <g fill="#7c3aed">
        <circle cx="430" cy="414" r="5"/><circle cx="468" cy="236" r="5"/><circle cx="590" cy="264" r="5"/><circle cx="360" cy="350" r="5"/><circle cx="546" cy="454" r="5"/>
    </g>
    {_callout(306, 336, 112, 246, labels[0], width=154, theme="purple")}
    {_callout(432, 360, 118, 454, labels[1], width=134, theme="purple")}
    {_callout(520, 322, 754, 248, labels[2], width=118, theme="purple")}
    {_callout(612, 394, 760, 408, labels[3], width=148, theme="yellow")}
    {_callout(468, 236, 754, 162, labels[4], width=126, theme="blue")}
    {_legend([("#7c3aed", "Cell structures"), ("#a21caf", "Nucleus"), ("#dc2626", "Mitochondria"), ("#64748b", "Ribosomes")], x=384, y=508, width=214)}
    """
    return _wrap_svg(payload.get("title") or "Animal Cell", "Labeled organelles in an animal cell", body, template="animal_cell")


def render_water_cycle(payload):
    labels = _labels(payload, ["Evaporation", "Condensation", "Precipitation", "Collection"])
    body = f"""
    <circle cx="150" cy="158" r="46" fill="url(#eduSun)" class="edu-shadow"/>
    <path d="M86 456 C176 346 238 278 330 456 Z" fill="#cbd5e1" stroke="#94a3b8" stroke-width="2"/>
    <path d="M236 456 C364 300 450 228 596 456 Z" fill="#e2e8f0" stroke="#94a3b8" stroke-width="2"/>
    <path d="M26 468 C190 438 328 456 488 434 C650 412 798 432 954 468 L954 612 L26 612 Z" fill="url(#eduOcean)"/>
    <path d="M390 484 C466 494 540 512 642 486 C694 474 740 474 790 488" fill="none" stroke="#e0f2fe" stroke-width="8" stroke-linecap="round"/>
    {_cloud(594, 156, 1.02)}
    <g stroke="#0284c7" stroke-width="3.2" stroke-linecap="round">
        <path d="M536 246 L518 316"/><path d="M592 248 L574 330"/><path d="M650 246 L628 318"/>
    </g>
    <path class="edu-arrow-input" d="M730 462 C816 342 766 248 666 184"/>
    <path class="edu-arrow" d="M430 172 C514 120 610 122 700 160"/>
    <path class="edu-arrow-input" d="M624 238 C584 304 546 374 512 452"/>
    <path class="edu-arrow-output" d="M386 502 C516 536 650 538 804 498"/>
    {_label_box(782, 318, labels[0], width=148, theme="blue")}
    {_label_box(514, 118, labels[1], width=158, theme="white")}
    {_label_box(688, 296, labels[2], width=160, theme="blue")}
    {_label_box(666, 560, labels[3], width=134, theme="blue")}
    {_legend([("#0284c7", "Water movement"), ("#ffffff", "Clouds"), ("#94a3b8", "Landforms"), ("#0ea5e9", "Collection")], x=58, y=500, width=204)}
    """
    return _wrap_svg(payload.get("title") or "Water Cycle", "Evaporation, condensation, precipitation, and collection", body, template="water_cycle")


def render_food_chain(payload):
    labels = _labels(payload, ["Sun", "Grass", "Grasshopper", "Frog", "Snake", "Hawk"])
    x_positions = [118, 270, 424, 578, 728, 864]
    body_parts = []
    for index in range(len(labels) - 1):
        body_parts.append(_arrow_path(f"M{x_positions[index] + 46} 334 L{x_positions[index + 1] - 56} 334", css_class="edu-arrow-output"))
    body = "".join(body_parts) + f"""
    <circle cx="118" cy="286" r="40" fill="url(#eduSun)" class="edu-shadow"/>{_label_box(118, 404, labels[0], width=96, theme="yellow")}
    <g fill="#22c55e"><path d="M244 356 C246 304 260 280 270 356"/><path d="M270 356 C274 296 292 270 302 356"/><path d="M294 356 C298 316 312 292 324 356"/></g>{_label_box(270, 404, labels[1], width=106, theme="green")}
    <ellipse cx="424" cy="330" rx="42" ry="25" fill="#bef264" stroke="#65a30d" stroke-width="3"/><path d="M392 346 L364 372 M418 350 L404 382 M446 346 L476 372" stroke="#65a30d" stroke-width="4" stroke-linecap="round"/><circle cx="458" cy="318" r="8" fill="#172033"/>{_label_box(424, 404, labels[2], width=134, theme="green")}
    <ellipse cx="578" cy="330" rx="43" ry="28" fill="#86efac" stroke="#16a34a" stroke-width="3"/><path d="M542 346 C520 370 502 370 488 352 M614 346 C638 372 658 372 674 352" stroke="#16a34a" stroke-width="5" fill="none"/><circle cx="604" cy="318" r="7" fill="#172033"/>{_label_box(578, 404, labels[3], width=106, theme="green")}
    <path d="M690 332 C724 300 766 362 802 326" fill="none" stroke="#a16207" stroke-width="14" stroke-linecap="round"/><circle cx="803" cy="325" r="5" fill="#172033"/>{_label_box(728, 404, labels[4], width=104, theme="yellow")}
    <path d="M830 312 L902 276 L880 330 L920 352 L854 346 Z" fill="#cbd5e1" stroke="#475569" stroke-width="3"/>{_label_box(864, 404, labels[5], width=102, theme="white")}
    {_legend([("#f59e0b", "Energy source"), ("#22c55e", "Producer"), ("#86efac", "Consumers"), ("#16a34a", "Energy flow")], x=364, y=506, width=220)}
    """
    return _wrap_svg(payload.get("title") or "Food Chain", "Energy transfer between organisms", body, template="food_chain")


def render_solar_system(payload):
    labels = _labels(payload, ["Sun", "Mercury", "Venus", "Earth", "Mars", "Jupiter"])
    planets = [(332, 320, 8, "#94a3b8"), (396, 274, 12, "#f59e0b"), (500, 382, 14, "#2563eb"), (612, 272, 11, "#dc2626"), (746, 388, 24, "#d97706")]
    orbits = "".join(f'<ellipse class="edu-soft-line" cx="214" cy="330" rx="{92 + index * 84}" ry="{50 + index * 34}"/>' for index in range(5))
    bodies = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" class="edu-shadow"/>{_label_box(x, y + r + 34, labels[index + 1], width=96, theme="white")}' for index, (x, y, r, color) in enumerate(planets))
    body = f"""
    <rect x="54" y="126" width="872" height="380" rx="28" fill="#0f172a" opacity="0.96"/>
    <g fill="#ffffff" opacity="0.72"><circle cx="338" cy="166" r="2"/><circle cx="718" cy="172" r="2"/><circle cx="842" cy="270" r="1.8"/><circle cx="582" cy="188" r="1.6"/><circle cx="422" cy="470" r="2"/></g>
    {orbits}
    <circle cx="214" cy="330" r="58" fill="url(#eduSun)" class="edu-shadow"/>
    {_label_box(214, 426, labels[0], width=94, theme="yellow")}
    {bodies}
    {_legend([("#f59e0b", "Sun and rocky planets"), ("#2563eb", "Earth"), ("#d97706", "Gas giant"), ("#94a3b8", "Orbit paths")], x=686, y=510, width=226)}
    """
    return _wrap_svg(payload.get("title") or "Solar System", "Planet positions along orbital paths", body, template="solar_system")


def render_timeline(payload):
    labels = _labels(payload, ["Start", "Event 1", "Event 2", "Event 3", "Finish"], limit=8)
    count = len(labels)
    start_x = 122
    gap = 736 / max(1, count - 1)
    dots = []
    for index, label in enumerate(labels):
        x = start_x + index * gap
        y = 332
        label_y = 236 if index % 2 == 0 else 430
        dots.append(f'<circle class="edu-shadow" cx="{x:.1f}" cy="{y}" r="14" fill="#3157d5"/><path class="edu-soft-line" d="M{x:.1f} {y} L{x:.1f} {label_y + (-34 if index % 2 else 34)}"/>{_label_box(x, label_y, label, width=132, theme="white")}')
    body = f"""
    <rect x="60" y="148" width="860" height="350" rx="22" fill="#f8fafc" stroke="rgba(100,116,139,0.18)"/>
    <path class="edu-arrow" marker-end="url(#eduArrow)" d="M86 332 C266 300 420 364 560 332 S766 300 900 332"/>
    {"".join(dots)}
    {_legend([("#3157d5", "Milestone"), ("#64748b", "Chronological order"), ("#ffffff", "Event label")], x=382, y=520, width=218)}
    """
    return _wrap_svg(payload.get("title") or "Timeline", "Chronological sequence of key events", body, template="timeline")


def render_electric_circuit(payload):
    labels = _labels(payload, ["Battery", "Switch", "Bulb", "Wires", "Current"])
    body = f"""
    <rect x="128" y="166" width="724" height="326" rx="22" fill="#fffbeb" stroke="#f59e0b" stroke-width="2"/>
    <path class="edu-arrow" d="M210 342 L210 224 L760 224 L760 452 L210 452 Z"/>
    <line x1="178" y1="312" x2="242" y2="312" stroke="#172033" stroke-width="6"/>
    <line x1="194" y1="354" x2="226" y2="354" stroke="#172033" stroke-width="6"/>
    <circle cx="760" cy="342" r="54" fill="#fef3c7" stroke="#d97706" stroke-width="4" class="edu-shadow"/>
    <path d="M730 342 C748 306 772 306 790 342 C772 378 748 378 730 342 Z" fill="none" stroke="#d97706" stroke-width="3"/>
    <g stroke="#f59e0b" stroke-width="3" stroke-linecap="round"><path d="M760 264 L760 246"/><path d="M820 342 L840 342"/><path d="M760 420 L760 438"/></g>
    <path d="M446 224 L514 176" stroke="#172033" stroke-width="6" stroke-linecap="round"/>
    <circle cx="446" cy="224" r="7" fill="#172033"/><circle cx="522" cy="224" r="7" fill="#172033"/>
    {_arrow_path("M306 224 L390 224")} {_arrow_path("M760 288 L760 248")} {_arrow_path("M660 452 L560 452")}
    {_callout(210, 334, 80, 360, labels[0], width=116, theme="yellow")}
    {_callout(484, 198, 408, 132, labels[1], width=116, theme="yellow")}
    {_callout(760, 342, 836, 250, labels[2], width=108, theme="yellow")}
    {_callout(404, 452, 378, 536, labels[3], width=100, theme="white")}
    {_callout(344, 224, 246, 146, labels[4], width=108, theme="blue")}
    {_legend([("#f59e0b", "Electrical energy"), ("#3157d5", "Current direction"), ("#172033", "Conducting wire")], x=626, y=510, width=230)}
    """
    return _wrap_svg(payload.get("title") or "Electric Circuit", "Closed circuit with current direction", body, template="electric_circuit")


def render_human_heart(payload):
    labels = _labels(payload, ["Aorta", "Pulmonary artery", "Right atrium", "Left atrium", "Right ventricle", "Left ventricle"])
    body = f"""
    <path class="edu-shadow" d="M490 214 C428 146 326 188 340 304 C354 414 490 482 490 482 C490 482 626 414 640 304 C654 188 552 146 490 214 Z" fill="#fecaca" stroke="#dc2626" stroke-width="4"/>
    <path d="M490 214 L490 472" stroke="#dc2626" stroke-width="3" opacity="0.42"/>
    <path d="M430 294 C454 274 474 274 490 300 C508 274 536 272 562 292" fill="none" stroke="#dc2626" stroke-width="3"/>
    <path d="M452 182 C456 116 492 102 514 168" fill="none" stroke="#dc2626" stroke-width="26" stroke-linecap="round"/>
    <path d="M526 190 C594 126 640 162 596 236" fill="none" stroke="#2563eb" stroke-width="22" stroke-linecap="round"/>
    <path d="M426 352 C456 370 470 406 480 448" fill="none" stroke="#991b1b" stroke-width="3"/>
    <path d="M554 352 C526 374 512 408 502 448" fill="none" stroke="#991b1b" stroke-width="3"/>
    {_callout(486, 156, 168, 156, labels[0], width=132, theme="yellow")}
    {_callout(570, 198, 718, 156, labels[1], width=160, theme="blue")}
    {_callout(424, 286, 146, 272, labels[2], width=144, theme="blue")}
    {_callout(556, 286, 746, 274, labels[3], width=126, theme="blue")}
    {_callout(430, 382, 150, 438, labels[4], width=156, theme="purple")}
    {_callout(552, 382, 746, 438, labels[5], width=148, theme="purple")}
    {_legend([("#dc2626", "Oxygen-rich blood"), ("#2563eb", "Oxygen-poor blood"), ("#991b1b", "Heart chambers")], x=382, y=516, width=238)}
    """
    return _wrap_svg(payload.get("title") or "Human Heart", "Simplified four-chamber heart anatomy", body, template="human_heart")


def render_digestive_system(payload):
    labels = _labels(payload, ["Mouth", "Oesophagus", "Stomach", "Small intestine", "Large intestine"])
    body = f"""
    <circle cx="474" cy="146" r="42" fill="#fde68a" stroke="#d97706" stroke-width="3"/>
    <path d="M452 140 C462 154 486 154 496 140" fill="none" stroke="#92400e" stroke-width="4" stroke-linecap="round"/>
    <path d="M474 188 C474 240 474 268 474 304" stroke="#f97316" stroke-width="17" stroke-linecap="round"/>
    <path d="M474 304 C552 286 600 330 552 376 C516 410 448 392 450 352 C452 326 478 314 474 304 Z" fill="#fecaca" stroke="#dc2626" stroke-width="4" class="edu-shadow"/>
    <path d="M462 392 C340 424 386 532 506 490 C606 454 588 572 448 544" fill="none" stroke="#f59e0b" stroke-width="19" stroke-linecap="round"/>
    <path d="M362 400 C294 496 354 590 502 584 C652 578 684 456 584 392" fill="none" stroke="#a16207" stroke-width="21" stroke-linecap="round"/>
    {_callout(474, 146, 174, 150, labels[0], width=112, theme="yellow")}
    {_callout(474, 238, 174, 248, labels[1], width=136, theme="yellow")}
    {_callout(536, 346, 716, 294, labels[2], width=128, theme="purple")}
    {_callout(506, 490, 718, 480, labels[3], width=150, theme="yellow")}
    {_callout(362, 440, 174, 466, labels[4], width=150, theme="yellow")}
    {_legend([("#f97316", "Food passage"), ("#dc2626", "Stomach"), ("#f59e0b", "Small intestine"), ("#a16207", "Large intestine")], x=370, y=506, width=246)}
    """
    return _wrap_svg(payload.get("title") or "Digestive System", "Main organs in the digestive tract", body, template="digestive_system")


def render_atom(payload):
    labels = _labels(payload, ["Nucleus", "Electron", "Orbit", "Proton", "Neutron"])
    body = f"""
    <ellipse class="edu-soft-line" cx="490" cy="330" rx="238" ry="90" transform="rotate(0 490 330)"/>
    <ellipse class="edu-soft-line" cx="490" cy="330" rx="238" ry="90" transform="rotate(60 490 330)"/>
    <ellipse class="edu-soft-line" cx="490" cy="330" rx="238" ry="90" transform="rotate(-60 490 330)"/>
    <circle cx="490" cy="330" r="58" fill="#fef3c7" stroke="#d97706" stroke-width="4" class="edu-shadow"/>
    <g fill="#dc2626"><circle cx="474" cy="318" r="13"/><circle cx="508" cy="344" r="13"/></g>
    <g fill="#64748b"><circle cx="506" cy="314" r="12"/><circle cx="472" cy="348" r="12"/></g>
    <circle cx="704" cy="330" r="14" fill="#3157d5"/><circle cx="388" cy="238" r="14" fill="#3157d5"/><circle cx="388" cy="422" r="14" fill="#3157d5"/>
    {_label_box(490, 330, labels[0], width=112, theme="yellow")}
    {_callout(704, 330, 778, 246, labels[1], width=118, theme="blue")}
    {_callout(590, 250, 750, 414, labels[2], width=104, theme="white")}
    {_callout(474, 318, 178, 294, labels[3], width=110, theme="yellow")}
    {_callout(506, 314, 178, 374, labels[4], width=110, theme="white")}
    {_legend([("#d97706", "Nucleus"), ("#3157d5", "Electrons"), ("#dc2626", "Protons"), ("#64748b", "Neutrons")], x=386, y=506, width=212)}
    """
    return _wrap_svg(payload.get("title") or "Atom", "Nucleus, electrons, and orbital paths", body, template="atom")


def render_tree(payload):
    labels = _labels(payload, ["Main idea", "Branch A", "Branch B", "Branch C", "Detail"], limit=7)
    root = labels[0]
    children = labels[1:]
    count = max(1, len(children))
    body = f"""
    <path d="M490 230 C490 318 490 390 490 496" stroke="#92400e" stroke-width="24" stroke-linecap="round"/>
    <path d="M490 498 C448 530 414 544 376 560 M490 500 C522 536 558 550 608 562" stroke="#92400e" stroke-width="8" stroke-linecap="round"/>
    <circle cx="490" cy="198" r="62" fill="#dcfce7" stroke="#16a34a" stroke-width="3" class="edu-shadow"/>
    {_label_box(490, 198, root, width=128, theme="green")}
    """
    for index, label in enumerate(children):
        angle_x = 168 + index * (642 / max(1, count - 1))
        y = 342 if index % 2 == 0 else 420
        body += f'<path class="edu-soft-line" d="M490 258 C490 {y - 76} {angle_x:.1f} {y - 72} {angle_x:.1f} {y - 36}"/><circle cx="{angle_x:.1f}" cy="{y}" r="48" fill="#e0f2fe" stroke="#0284c7" stroke-width="3" class="edu-shadow"/>{_label_box(angle_x, y, label, width=124, theme="blue")}'
    body += _legend([("#16a34a", "Main category"), ("#0284c7", "Branches"), ("#92400e", "Connection")], x=704, y=502, width=198)
    return _wrap_svg(payload.get("title") or "Tree Diagram", "Branching educational structure", body, template="tree")


def render_database(payload):
    labels = _labels(payload, ["Students", "Courses", "Enrollment", "Teachers"], limit=6)
    body = ""
    positions = [(206, 236), (492, 214), (774, 236), (342, 420), (638, 420), (492, 520)]
    for index, label in enumerate(labels):
        x, y = positions[index % len(positions)]
        body += f'<path class="edu-shadow" d="M{x-78} {y-30} C{x-78} {y-58} {x+78} {y-58} {x+78} {y-30} L{x+78} {y+42} C{x+78} {y+70} {x-78} {y+70} {x-78} {y+42} Z" fill="#ecfeff" stroke="#0f766e" stroke-width="3"/><ellipse cx="{x}" cy="{y-30}" rx="78" ry="28" fill="#dbeafe" stroke="#3157d5" stroke-width="3"/>{_label_box(x, y+18, label, width=130, theme="blue")}'
    for left, right in [(positions[0], positions[1]), (positions[1], positions[2]), (positions[0], positions[3]), (positions[2], positions[4])]:
        body += _arrow_path(f"M{left[0]+82} {left[1]+8} C{(left[0]+right[0])/2:.1f} {left[1]+28}, {(left[0]+right[0])/2:.1f} {right[1]-28}, {right[0]-82} {right[1]+8}")
    body += _legend([("#3157d5", "Entity header"), ("#0f766e", "Table body"), ("#3157d5", "Relationship")], x=382, y=528, width=230)
    return _wrap_svg(payload.get("title") or "Database Relationships", "ER-style database relationship layout", body, template="database")


def render_network(payload):
    labels = _labels(payload, ["Router", "Server", "Laptop", "Printer", "Internet"], limit=7)
    coords = [(490, 326), (218, 218), (762, 218), (250, 470), (730, 470), (490, 512), (490, 160)]
    body = ""
    for index in range(1, min(len(labels), len(coords))):
        body += f'<path class="edu-soft-line" d="M{coords[0][0]} {coords[0][1]} L{coords[index][0]} {coords[index][1]}"/>'
    for index, label in enumerate(labels):
        x, y = coords[index % len(coords)]
        fill = "#dbeafe" if index else "#dcfce7"
        stroke = "#3157d5" if index else "#16a34a"
        body += f'<circle cx="{x}" cy="{y}" r="52" fill="{fill}" stroke="{stroke}" stroke-width="3" class="edu-shadow"/>{_label_box(x, y, label, width=116, theme="blue" if index else "green")}'
    body += _legend([("#16a34a", "Hub device"), ("#3157d5", "Connected nodes"), ("#94a3b8", "Network links")], x=386, y=540, width=218)
    return _wrap_svg(payload.get("title") or "Network", "Hub-and-spoke computer network", body, template="network")


def render_map(payload):
    labels = _labels(payload, ["Region", "Route", "River", "Mountain"], limit=5)
    body = f"""
    <path class="edu-shadow" d="M224 230 C324 152 442 194 528 152 C638 98 746 188 712 318 C676 454 558 414 468 486 C362 562 210 474 240 356 C256 296 170 288 224 230 Z" fill="#bbf7d0" stroke="#16a34a" stroke-width="4"/>
    <path d="M258 396 C374 350 420 414 524 346 C610 290 652 328 704 260" fill="none" stroke="#0284c7" stroke-width="9" stroke-linecap="round"/>
    <path class="edu-arrow" d="M292 266 C370 220 458 252 526 214 C590 178 662 202 704 256"/>
    <path d="M382 460 L418 390 L460 460 Z" fill="#cbd5e1" stroke="#64748b" stroke-width="3"/>
    <path d="M826 204 L850 260 L826 246 L802 260 Z" fill="#fef3c7" stroke="#d97706" stroke-width="2"/>
    {_label_box(850, 288, "N", width=54, theme="yellow")}
    {_label_box(478, 530, labels[0], width=126, theme="green")}
    {_callout(526, 214, 748, 164, labels[1], width=112, theme="yellow")}
    {_callout(524, 346, 748, 350, labels[2], width=104, theme="blue")}
    {_callout(418, 420, 166, 464, labels[3], width=128, theme="white")}
    {_legend([("#16a34a", "Land"), ("#0284c7", "Water"), ("#d97706", "Route and compass"), ("#64748b", "Mountains")], x=672, y=486, width=220)}
    """
    return _wrap_svg(payload.get("title") or "Map", "Educational map with route, river, and legend", body, template="map")


SPECIALIZED_RENDERERS = {
    "photosynthesis": render_photosynthesis,
    "plant_cell": render_plant_cell,
    "animal_cell": render_animal_cell,
    "water_cycle": render_water_cycle,
    "food_chain": render_food_chain,
    "solar_system": render_solar_system,
    "timeline": render_timeline,
    "tree": render_tree,
    "database": render_database,
    "network": render_network,
    "electric_circuit": render_electric_circuit,
    "human_heart": render_human_heart,
    "digestive_system": render_digestive_system,
    "atom": render_atom,
    "map": render_map,
}


def resolve_template(payload):
    explicit = _slug(payload.get("template") or payload.get("template_key"))
    if explicit in SPECIALIZED_RENDERERS:
        return explicit

    haystack = " ".join(
        [
            str(payload.get("title") or ""),
            str(payload.get("type") or ""),
            str(payload.get("diagram_type") or ""),
            str(payload.get("visualization_type") or ""),
            " ".join(_labels(payload, limit=16)),
        ]
    ).lower()
    padded_haystack = f" {haystack} "
    rules = [
        ("photosynthesis", ["photosynthesis"]),
        ("plant_cell", ["plant cell"]),
        ("animal_cell", ["animal cell"]),
        ("water_cycle", ["water cycle"]),
        ("food_chain", ["food chain"]),
        ("solar_system", ["solar system", "planet", "orbit"]),
        ("electric_circuit", ["electric circuit", "circuit"]),
        ("human_heart", ["human heart", "heart"]),
        ("digestive_system", ["digestive system", "digestion"]),
        ("atom", [" atom ", " atomic structure "]),
        ("database", ["database", "er_diagram", "entity"]),
        ("network", ["network_graph", "network"]),
        ("map", [" map", "geography"]),
        ("timeline", ["timeline"]),
        ("tree", ["tree", "hierarchy", "classification"]),
    ]
    for template, terms in rules:
        if any(term in padded_haystack for term in terms):
            return template
    return ""


def render_specialized(payload):
    template = resolve_template(payload)
    renderer = SPECIALIZED_RENDERERS.get(template)
    if not renderer:
        return None
    return renderer(payload)
