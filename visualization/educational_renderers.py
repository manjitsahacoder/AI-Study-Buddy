from html import escape
import re


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _labels(payload, fallback=None, limit=10):
    fallback = fallback or []
    raw_labels = payload.get("labels") or []
    labels = [str(label).strip() for label in raw_labels if str(label).strip()]
    if not labels:
        nodes = payload.get("nodes") or []
        labels = [str(node.get("label", "")).strip() for node in nodes if str(node.get("label", "")).strip()]
    combined = labels[:]
    for item in fallback:
        if len(combined) >= max(limit, len(fallback)):
            break
        if item not in combined:
            combined.append(item)
    return (combined or fallback)[:limit]


def _text(x, y, text, css_class="edu-label", anchor="middle"):
    return f'<text class="{css_class}" x="{x}" y="{y}" text-anchor="{anchor}">{escape(str(text))}</text>'


def _wrapped_text(x, y, text, width=18, css_class="edu-label", anchor="middle", line_height=16):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:width]
        if len(lines) == 3:
            break
    if current and len(lines) < 3:
        lines.append(current)
    tspans = []
    offset = -((len(lines) - 1) * line_height) / 2
    for index, line in enumerate(lines or [""]):
        dy = offset if index == 0 else line_height
        tspans.append(f'<tspan x="{x}" dy="{dy}">{escape(line)}</tspan>')
    return f'<text class="{css_class}" text-anchor="{anchor}" dominant-baseline="middle">{"".join(tspans)}</text>'


def _callout(x1, y1, x2, y2, label, anchor="start"):
    text_x = x2 + (8 if anchor == "start" else -8)
    return f"""
    <path class="edu-callout-line" d="M{x1} {y1} C{(x1 + x2) / 2} {y1}, {(x1 + x2) / 2} {y2}, {x2} {y2}"/>
    <circle class="edu-callout-dot" cx="{x1}" cy="{y1}" r="4"/>
    {_wrapped_text(text_x, y2, label, width=20, css_class="edu-callout-text", anchor=anchor)}
    """


def _arrow_path(path, css_class="edu-arrow", marker="eduArrow"):
    return f'<path class="{css_class}" marker-end="url(#{marker})" d="{path}"/>'


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
            <stop offset="0%" stop-color="#fae8ff"/>
            <stop offset="100%" stop-color="#fdf2f8"/>
        </linearGradient>
        <linearGradient id="eduOcean" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#38bdf8"/>
            <stop offset="100%" stop-color="#0ea5e9"/>
        </linearGradient>
        <filter id="eduShadow" x="-20%" y="-20%" width="140%" height="160%">
            <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#0f172a" flood-opacity="0.14"/>
        </filter>
        <marker id="eduArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
            <path d="M0 0 L10 5 L0 10 z" fill="var(--edu-arrow)"/>
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
            .edu-title { fill: var(--edu-ink); font-size: 30px; font-weight: 850; }
            .edu-subtitle { fill: var(--edu-muted); font-size: 13px; font-weight: 750; }
            .edu-label { fill: var(--edu-ink); font-size: 14px; font-weight: 820; }
            .edu-small { fill: var(--edu-muted); font-size: 12px; font-weight: 780; }
            .edu-callout-line { fill: none; stroke: var(--edu-arrow); stroke-width: 2.2; stroke-linecap: round; opacity: 0.72; }
            .edu-callout-dot { fill: var(--edu-arrow); stroke: #ffffff; stroke-width: 2; }
            .edu-callout-text { fill: var(--edu-ink); font-size: 12px; font-weight: 820; }
            .edu-arrow { fill: none; stroke: var(--edu-arrow); stroke-width: 3.2; stroke-linecap: round; stroke-linejoin: round; }
            .edu-soft-line { fill: none; stroke: var(--edu-line); stroke-width: 2; stroke-linecap: round; }
            .edu-shadow { filter: url(#eduShadow); }
            .edu-illustration { transform-origin: center; }
            @media (max-width: 640px) {
                .edu-title { font-size: 26px; }
                .edu-label { font-size: 13px; }
                .edu-callout-text { font-size: 11px; }
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
                .edu-callout-dot { stroke: #111827; }
            }
        </style>
    </defs>
    """


def _wrap_svg(title, subtitle, body, width=900, height=560, template="illustration"):
    title = escape(title or "AI Visualization")
    subtitle = escape(subtitle or "Educational illustration")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" class="ai-visualization-svg edu-template-{escape(template)}" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="{title}">
    {_defs()}
    <rect class="edu-bg" width="{width}" height="{height}" rx="28"/>
    <rect class="edu-panel" x="28" y="28" width="{width - 56}" height="{height - 56}" rx="24"/>
    <text class="edu-title" x="{width / 2}" y="60" text-anchor="middle">{title}</text>
    <text class="edu-subtitle" x="{width / 2}" y="84" text-anchor="middle">{subtitle}</text>
    <g class="edu-illustration" data-edu-template="{escape(template)}">
        {body}
    </g>
</svg>"""


def render_photosynthesis(payload):
    labels = _labels(payload, ["Sunlight", "Water", "Carbon dioxide", "Oxygen", "Glucose", "Leaf"])
    body = f"""
    <g class="edu-shadow">
        <circle cx="155" cy="145" r="52" fill="url(#eduSun)"/>
        <g stroke="#f59e0b" stroke-width="6" stroke-linecap="round">
            <path d="M155 62 L155 36"/><path d="M155 254 L155 226"/>
            <path d="M72 145 L44 145"/><path d="M266 145 L236 145"/>
            <path d="M96 86 L76 66"/><path d="M214 204 L235 225"/>
            <path d="M214 86 L235 66"/><path d="M96 204 L76 225"/>
        </g>
    </g>
    {_text(155, 148, labels[0])}
    <path fill="#7dd3fc" opacity="0.95" d="M212 402 C212 378 238 352 238 352 C238 352 264 378 264 402 C264 420 253 432 238 432 C223 432 212 420 212 402 Z"/>
    {_wrapped_text(238, 455, labels[1], width=16)}
    <g>
        <ellipse class="edu-shadow" cx="510" cy="310" rx="178" ry="82" fill="url(#eduLeaf)" transform="rotate(-14 510 310)"/>
        <path d="M353 352 C470 302 555 276 675 242" class="edu-soft-line"/>
        <path d="M382 341 C438 346 505 331 562 292" class="edu-soft-line"/>
        <path d="M449 319 C497 330 543 320 603 274" class="edu-soft-line"/>
    </g>
    {_arrow_path("M216 178 C300 214 354 240 422 274")}
    {_arrow_path("M270 395 C345 368 394 348 444 328")}
    {_arrow_path("M710 278 C766 246 804 206 828 164")}
    {_arrow_path("M655 357 C724 378 766 407 805 450")}
    <g fill="#e0f2fe" stroke="#0284c7" stroke-width="2">
        <circle cx="292" cy="246" r="21"/><circle cx="328" cy="260" r="21"/><circle cx="364" cy="246" r="21"/>
    </g>
    {_wrapped_text(328, 250, labels[2], width=14)}
    <g fill="#dcfce7" stroke="#16a34a" stroke-width="2">
        <circle cx="804" cy="128" r="18"/><circle cx="831" cy="112" r="18"/>
    </g>
    {_wrapped_text(782, 108, labels[3], width=14, anchor="end")}
    <rect x="710" y="432" width="130" height="42" rx="21" fill="#fef3c7" stroke="#d97706" stroke-width="2.4"/>
    {_wrapped_text(775, 453, labels[4], width=16)}
    {_wrapped_text(510, 420, labels[5], width=18)}
    """
    return _wrap_svg(payload.get("title") or "Photosynthesis", "Textbook-style biological process", body, template="photosynthesis")


def render_plant_cell(payload):
    labels = _labels(payload, ["Cell wall", "Cell membrane", "Nucleus", "Chloroplast", "Vacuole", "Cytoplasm"])
    body = f"""
    <rect class="edu-shadow" x="250" y="150" width="410" height="290" rx="58" fill="#bbf7d0" stroke="#15803d" stroke-width="12"/>
    <rect x="268" y="168" width="374" height="254" rx="48" fill="url(#eduCell)" stroke="#22c55e" stroke-width="4"/>
    <ellipse cx="455" cy="292" rx="86" ry="58" fill="#dbeafe" stroke="#0284c7" stroke-width="3"/>
    <circle cx="548" cy="256" r="39" fill="#f5d0fe" stroke="#a21caf" stroke-width="3"/>
    <circle cx="548" cy="256" r="15" fill="#c084fc"/>
    <g fill="#22c55e" stroke="#15803d" stroke-width="2">
        <ellipse cx="350" cy="244" rx="32" ry="18" transform="rotate(-24 350 244)"/>
        <ellipse cx="374" cy="346" rx="32" ry="18" transform="rotate(20 374 346)"/>
        <ellipse cx="586" cy="344" rx="32" ry="18" transform="rotate(-18 586 344)"/>
    </g>
    <path d="M315 210 C410 188 525 184 604 226" fill="none" stroke="#86efac" stroke-width="10" opacity="0.6"/>
    {_callout(250, 248, 128, 210, labels[0])}
    {_callout(278, 315, 132, 316, labels[1])}
    {_callout(548, 256, 704, 210, labels[2])}
    {_callout(350, 244, 170, 395, labels[3])}
    {_callout(455, 292, 704, 326, labels[4])}
    {_callout(425, 390, 708, 418, labels[5])}
    """
    return _wrap_svg(payload.get("title") or "Plant Cell", "Labeled plant cell structure", body, template="plant_cell")


def render_animal_cell(payload):
    labels = _labels(payload, ["Cell membrane", "Cytoplasm", "Nucleus", "Mitochondria", "Ribosomes"])
    body = f"""
    <path class="edu-shadow" d="M282 316 C262 206 348 150 468 154 C596 158 677 238 638 350 C604 452 484 464 382 432 C322 414 292 372 282 316 Z" fill="url(#eduAnimalCell)" stroke="#db2777" stroke-width="5"/>
    <circle cx="487" cy="292" r="58" fill="#f5d0fe" stroke="#a21caf" stroke-width="3"/>
    <circle cx="487" cy="292" r="19" fill="#c084fc"/>
    <g fill="#fecaca" stroke="#dc2626" stroke-width="2.4">
        <ellipse cx="390" cy="248" rx="36" ry="18" transform="rotate(25 390 248)"/>
        <ellipse cx="570" cy="355" rx="36" ry="18" transform="rotate(-22 570 355)"/>
    </g>
    <g fill="#7c3aed">
        <circle cx="415" cy="372" r="5"/><circle cx="446" cy="215" r="5"/><circle cx="550" cy="226" r="5"/><circle cx="348" cy="318" r="5"/>
    </g>
    {_callout(305, 300, 142, 246, labels[0])}
    {_callout(405, 322, 144, 390, labels[1])}
    {_callout(487, 292, 704, 232, labels[2])}
    {_callout(570, 355, 714, 364, labels[3])}
    {_callout(446, 215, 706, 154, labels[4])}
    """
    return _wrap_svg(payload.get("title") or "Animal Cell", "Labeled animal cell structure", body, template="animal_cell")


def render_water_cycle(payload):
    labels = _labels(payload, ["Evaporation", "Condensation", "Precipitation", "Collection"])
    body = f"""
    <circle cx="142" cy="144" r="44" fill="url(#eduSun)" class="edu-shadow"/>
    <path d="M98 420 C178 332 226 258 306 420 Z" fill="#cbd5e1" stroke="#94a3b8" stroke-width="2"/>
    <path d="M238 420 C348 282 424 214 548 420 Z" fill="#e2e8f0" stroke="#94a3b8" stroke-width="2"/>
    <path d="M28 430 C180 404 315 422 454 404 C604 384 744 398 872 430 L872 532 L28 532 Z" fill="url(#eduOcean)"/>
    <path d="M365 438 C442 446 511 462 604 438 C646 428 683 426 726 438" fill="none" stroke="#e0f2fe" stroke-width="8" stroke-linecap="round"/>
    <g fill="#ffffff" stroke="#cbd5e1" stroke-width="2" class="edu-shadow">
        <ellipse cx="568" cy="162" rx="66" ry="34"/><ellipse cx="622" cy="168" rx="54" ry="30"/><ellipse cx="520" cy="174" rx="50" ry="28"/>
    </g>
    <g stroke="#0284c7" stroke-width="3" stroke-linecap="round">
        <path d="M542 220 L526 280"/><path d="M590 224 L574 290"/><path d="M638 220 L620 282"/>
    </g>
    {_arrow_path("M672 430 C740 330 700 250 620 188")}
    {_arrow_path("M422 174 C492 128 566 124 640 158")}
    {_arrow_path("M592 218 C552 278 520 338 492 414")}
    {_arrow_path("M360 455 C470 486 586 488 720 456")}
    {_wrapped_text(744, 316, labels[0], width=18)}
    {_wrapped_text(530, 116, labels[1], width=18)}
    {_wrapped_text(658, 286, labels[2], width=18)}
    {_wrapped_text(610, 498, labels[3], width=18)}
    """
    return _wrap_svg(payload.get("title") or "Water Cycle", "Natural cycle illustration", body, template="water_cycle")


def render_food_chain(payload):
    labels = _labels(payload, ["Sun", "Grass", "Grasshopper", "Frog", "Snake", "Hawk"])
    x_positions = [110, 250, 390, 530, 670, 800]
    body_parts = []
    for index in range(len(labels) - 1):
        body_parts.append(_arrow_path(f"M{x_positions[index] + 42} 318 L{x_positions[index + 1] - 48} 318"))
    body = "".join(body_parts) + f"""
    <circle cx="110" cy="270" r="38" fill="url(#eduSun)" class="edu-shadow"/>{_wrapped_text(110, 365, labels[0], width=14)}
    <g fill="#22c55e"><path d="M230 336 C232 298 242 282 250 336"/><path d="M250 336 C252 292 266 274 272 336"/><path d="M270 336 C272 304 284 286 292 336"/></g>{_wrapped_text(250, 365, labels[1], width=14)}
    <ellipse cx="390" cy="314" rx="40" ry="24" fill="#bef264" stroke="#65a30d" stroke-width="3"/><circle cx="424" cy="304" r="8" fill="#172033"/>{_wrapped_text(390, 365, labels[2], width=14)}
    <ellipse cx="530" cy="314" rx="40" ry="26" fill="#86efac" stroke="#16a34a" stroke-width="3"/><circle cx="555" cy="302" r="7" fill="#172033"/>{_wrapped_text(530, 365, labels[3], width=14)}
    <path d="M632 316 C664 288 704 344 736 310" fill="none" stroke="#a16207" stroke-width="13" stroke-linecap="round"/>{_wrapped_text(670, 365, labels[4], width=14)}
    <path d="M768 298 L832 270 L812 318 L848 338 L790 334 Z" fill="#cbd5e1" stroke="#475569" stroke-width="3"/>{_wrapped_text(800, 365, labels[5], width=14)}
    """
    return _wrap_svg(payload.get("title") or "Food Chain", "Energy transfer between organisms", body, template="food_chain")


def render_solar_system(payload):
    labels = _labels(payload, ["Sun", "Mercury", "Venus", "Earth", "Mars", "Jupiter"])
    planets = [(285, 292, 8, "#94a3b8"), (345, 250, 12, "#f59e0b"), (438, 338, 13, "#2563eb"), (538, 248, 10, "#dc2626"), (660, 330, 22, "#d97706")]
    orbits = "".join(f'<ellipse class="edu-soft-line" cx="190" cy="294" rx="{85 + index * 78}" ry="{46 + index * 30}"/>' for index in range(5))
    bodies = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" class="edu-shadow"/>{_wrapped_text(x, y + r + 24, labels[index + 1], width=12)}' for index, (x, y, r, color) in enumerate(planets))
    body = f"""
    {orbits}
    <circle cx="190" cy="294" r="52" fill="url(#eduSun)" class="edu-shadow"/>
    {_wrapped_text(190, 372, labels[0], width=12)}
    {bodies}
    """
    return _wrap_svg(payload.get("title") or "Solar System", "Orbit-based planetary illustration", body, template="solar_system")


def render_timeline(payload):
    labels = _labels(payload, ["Start", "Event 1", "Event 2", "Event 3", "Finish"], limit=8)
    count = len(labels)
    start_x = 110
    gap = 680 / max(1, count - 1)
    dots = []
    for index, label in enumerate(labels):
        x = start_x + index * gap
        y = 306
        label_y = 228 if index % 2 == 0 else 388
        dots.append(f'<circle class="edu-shadow" cx="{x:.1f}" cy="{y}" r="13" fill="#3157d5"/><path class="edu-soft-line" d="M{x:.1f} {y} L{x:.1f} {label_y + (-22 if index % 2 else 22)}"/>{_wrapped_text(x, label_y, label, width=18)}')
    body = f"""
    <path class="edu-arrow" marker-end="url(#eduArrow)" d="M86 306 C252 282 382 330 510 306 S714 282 820 306"/>
    {"".join(dots)}
    """
    return _wrap_svg(payload.get("title") or "Timeline", "Chronological event illustration", body, template="timeline")


def render_electric_circuit(payload):
    labels = _labels(payload, ["Battery", "Switch", "Bulb", "Wires", "Current"])
    body = f"""
    <path class="edu-arrow" d="M190 310 L190 210 L710 210 L710 410 L190 410 Z"/>
    <line x1="160" y1="286" x2="220" y2="286" stroke="#172033" stroke-width="5"/>
    <line x1="174" y1="322" x2="206" y2="322" stroke="#172033" stroke-width="5"/>
    <path d="M420 210 L482 170" stroke="#172033" stroke-width="5" stroke-linecap="round"/>
    <circle cx="710" cy="310" r="48" fill="#fef3c7" stroke="#d97706" stroke-width="4" class="edu-shadow"/>
    <path d="M686 310 C702 282 718 282 734 310 C718 338 702 338 686 310 Z" fill="none" stroke="#d97706" stroke-width="3"/>
    {_arrow_path("M280 210 L360 210")} {_arrow_path("M710 260 L710 220")} {_arrow_path("M610 410 L520 410")}
    {_wrapped_text(190, 360, labels[0], width=14)}
    {_wrapped_text(452, 154, labels[1], width=14)}
    {_wrapped_text(710, 382, labels[2], width=14)}
    {_wrapped_text(450, 442, labels[3], width=14)}
    {_wrapped_text(336, 186, labels[4], width=14)}
    """
    return _wrap_svg(payload.get("title") or "Electric Circuit", "Closed circuit with current flow", body, template="electric_circuit")


def render_human_heart(payload):
    labels = _labels(payload, ["Aorta", "Pulmonary artery", "Right atrium", "Left atrium", "Right ventricle", "Left ventricle"])
    body = f"""
    <path class="edu-shadow" d="M448 210 C386 142 292 184 306 288 C320 394 448 454 448 454 C448 454 576 394 590 288 C604 184 510 142 448 210 Z" fill="#fecaca" stroke="#dc2626" stroke-width="4"/>
    <path d="M448 210 L448 448" stroke="#dc2626" stroke-width="3" opacity="0.45"/>
    <path d="M408 178 C410 118 444 106 462 166" fill="none" stroke="#dc2626" stroke-width="24" stroke-linecap="round"/>
    <path d="M488 190 C548 128 590 160 552 226" fill="none" stroke="#2563eb" stroke-width="20" stroke-linecap="round"/>
    {_callout(426, 158, 166, 160, labels[0])}
    {_callout(528, 194, 700, 164, labels[1])}
    {_callout(384, 266, 154, 260, labels[2])}
    {_callout(512, 266, 716, 260, labels[3])}
    {_callout(386, 360, 162, 404, labels[4])}
    {_callout(510, 360, 718, 404, labels[5])}
    """
    return _wrap_svg(payload.get("title") or "Human Heart", "Simplified anatomical heart diagram", body, template="human_heart")


def render_digestive_system(payload):
    labels = _labels(payload, ["Mouth", "Oesophagus", "Stomach", "Small intestine", "Large intestine"])
    body = f"""
    <circle cx="450" cy="138" r="32" fill="#fde68a" stroke="#d97706" stroke-width="3"/>
    <path d="M450 170 C450 218 450 240 450 274" stroke="#f97316" stroke-width="16" stroke-linecap="round"/>
    <path d="M450 274 C520 260 560 300 520 340 C490 368 430 352 432 318 C434 294 454 282 450 274 Z" fill="#fecaca" stroke="#dc2626" stroke-width="4"/>
    <path d="M438 358 C336 384 374 478 480 442 C566 414 550 514 430 492" fill="none" stroke="#f59e0b" stroke-width="18" stroke-linecap="round"/>
    <path d="M350 366 C292 456 342 520 472 520 C610 520 642 420 556 358" fill="none" stroke="#a16207" stroke-width="20" stroke-linecap="round"/>
    {_callout(450, 138, 174, 142, labels[0])}
    {_callout(450, 220, 174, 222, labels[1])}
    {_callout(506, 312, 708, 278, labels[2])}
    {_callout(466, 442, 710, 430, labels[3])}
    {_callout(350, 408, 170, 430, labels[4])}
    """
    return _wrap_svg(payload.get("title") or "Digestive System", "Simplified human digestive tract", body, template="digestive_system")


def render_atom(payload):
    labels = _labels(payload, ["Nucleus", "Electron", "Orbit", "Proton", "Neutron"])
    body = f"""
    <ellipse class="edu-soft-line" cx="450" cy="302" rx="220" ry="82" transform="rotate(0 450 302)"/>
    <ellipse class="edu-soft-line" cx="450" cy="302" rx="220" ry="82" transform="rotate(60 450 302)"/>
    <ellipse class="edu-soft-line" cx="450" cy="302" rx="220" ry="82" transform="rotate(-60 450 302)"/>
    <circle cx="450" cy="302" r="54" fill="#fef3c7" stroke="#d97706" stroke-width="4" class="edu-shadow"/>
    <circle cx="646" cy="302" r="13" fill="#3157d5"/><circle cx="354" cy="218" r="13" fill="#3157d5"/><circle cx="354" cy="386" r="13" fill="#3157d5"/>
    {_wrapped_text(450, 302, labels[0], width=12)}
    {_callout(646, 302, 726, 230, labels[1])}
    {_callout(546, 230, 710, 370, labels[2])}
    """
    return _wrap_svg(payload.get("title") or "Atom", "Atomic structure illustration", body, template="atom")


def render_tree(payload):
    labels = _labels(payload, ["Main idea", "Branch A", "Branch B", "Branch C", "Detail"], limit=7)
    root = labels[0]
    children = labels[1:]
    count = max(1, len(children))
    body = f'<circle cx="450" cy="178" r="52" fill="#dcfce7" stroke="#16a34a" stroke-width="3" class="edu-shadow"/>{_wrapped_text(450, 178, root, width=14)}'
    for index, label in enumerate(children):
        x = 160 + index * (580 / max(1, count - 1))
        body += f'<path class="edu-soft-line" d="M450 230 C450 292 {x:.1f} 292 {x:.1f} 350"/><circle cx="{x:.1f}" cy="370" r="42" fill="#e0f2fe" stroke="#0284c7" stroke-width="3" class="edu-shadow"/>{_wrapped_text(x, 370, label, width=14)}'
    return _wrap_svg(payload.get("title") or "Tree Diagram", "Branching educational structure", body, template="tree")


def render_database(payload):
    labels = _labels(payload, ["Students", "Courses", "Enrollment", "Teachers"], limit=6)
    body = ""
    x_positions = [210, 450, 690, 330, 570, 450]
    y_positions = [230, 230, 230, 380, 380, 470]
    for index, label in enumerate(labels):
        x = x_positions[index % len(x_positions)]
        y = y_positions[index % len(y_positions)]
        body += f'<path class="edu-shadow" d="M{x-70} {y-28} C{x-70} {y-52} {x+70} {y-52} {x+70} {y-28} L{x+70} {y+38} C{x+70} {y+62} {x-70} {y+62} {x-70} {y+38} Z" fill="#eef2ff" stroke="#3157d5" stroke-width="3"/><ellipse cx="{x}" cy="{y-28}" rx="70" ry="24" fill="#dbeafe" stroke="#3157d5" stroke-width="3"/>{_wrapped_text(x, y+18, label, width=16)}'
    body += _arrow_path("M280 230 L380 230") + _arrow_path("M520 230 L620 230")
    return _wrap_svg(payload.get("title") or "Database Relationships", "Entity relationship illustration", body, template="database")


def render_network(payload):
    labels = _labels(payload, ["Router", "Server", "Laptop", "Printer", "Internet"], limit=7)
    coords = [(450, 288), (220, 204), (682, 204), (250, 414), (650, 414), (450, 448), (450, 150)]
    body = ""
    for index in range(1, min(len(labels), len(coords))):
        body += f'<path class="edu-soft-line" d="M{coords[0][0]} {coords[0][1]} L{coords[index][0]} {coords[index][1]}"/>'
    for index, label in enumerate(labels):
        x, y = coords[index % len(coords)]
        fill = "#dcfce7" if index == 0 else "#e0f2fe"
        body += f'<circle cx="{x}" cy="{y}" r="44" fill="{fill}" stroke="#3157d5" stroke-width="3" class="edu-shadow"/>{_wrapped_text(x, y, label, width=12)}'
    return _wrap_svg(payload.get("title") or "Network", "Connected systems illustration", body, template="network")


def render_map(payload):
    labels = _labels(payload, ["Region", "Route", "River", "Mountain"], limit=5)
    body = f"""
    <path class="edu-shadow" d="M222 214 C314 144 426 184 500 150 C608 100 704 182 674 300 C642 424 530 388 444 454 C350 526 212 448 238 340 C252 286 172 270 222 214 Z" fill="#bbf7d0" stroke="#16a34a" stroke-width="4"/>
    <path d="M250 370 C354 330 396 390 492 328 C570 278 612 314 660 250" fill="none" stroke="#0284c7" stroke-width="8" stroke-linecap="round"/>
    <path class="edu-arrow" d="M280 250 C350 210 430 238 490 206 C548 176 612 196 650 242"/>
    <path d="M354 420 L386 360 L424 420 Z" fill="#cbd5e1" stroke="#64748b" stroke-width="3"/>
    {_wrapped_text(450, 472, labels[0], width=18)}
    {_callout(492, 206, 706, 166, labels[1])}
    {_callout(492, 328, 706, 330, labels[2])}
    {_callout(386, 382, 154, 420, labels[3])}
    """
    return _wrap_svg(payload.get("title") or "Map", "Simplified educational map", body, template="map")


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
