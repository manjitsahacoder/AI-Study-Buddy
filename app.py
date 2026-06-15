from flask import Flask, abort, render_template, request, send_file
from base64 import b64encode
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import google.generativeai as genai
from html import escape
from io import BytesIO
from pathlib import Path
from contextlib import closing
import json
import markdown
import os
import re
import sqlite3

from config import GEMINI_API_KEY, GEMINI_API_KEY_2


app = Flask(__name__)


def default_quiz_history_db():
    render_disk_path = os.environ.get("RENDER_DISK_PATH")
    if render_disk_path:
        return str(Path(render_disk_path) / "quiz_history.db")
    return str(Path(app.root_path) / "quiz_history.db")


app.config["QUIZ_HISTORY_DB"] = os.environ.get(
    "QUIZ_HISTORY_DB",
    default_quiz_history_db(),
)
latest_report = {}
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-2.5-flash")


def is_quota_error(error):
    error_text = str(error).lower()
    return (
        "429" in error_text
        or "quota" in error_text
        or "rate limit" in error_text
        or "resource_exhausted" in error_text
    )


def backup_gemini_api_keys():
    return [key for key in [GEMINI_API_KEY_2] if key]


def generate_content_with_fallback(prompt):
    try:
        return model.generate_content(prompt)
    except Exception as primary_error:
        if not is_quota_error(primary_error):
            raise

        last_error = primary_error
        for api_key in backup_gemini_api_keys():
            try:
                genai.configure(api_key=api_key)
                backup_model = genai.GenerativeModel("gemini-2.5-flash")
                return backup_model.generate_content(prompt)
            except Exception as backup_error:
                last_error = backup_error
                if not is_quota_error(backup_error):
                    raise

        raise last_error


def get_db_connection():
    db_path = Path(app.config["QUIZ_HISTORY_DB"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_quiz_history_db():
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                student_class TEXT NOT NULL,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                score TEXT NOT NULL,
                grade TEXT NOT NULL,
                questions_json TEXT NOT NULL,
                answers_json TEXT NOT NULL,
                report_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def save_quiz_history(name, student_class, subject, topic, score, grade, questions, answers, report_text):
    init_quiz_history_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            INSERT INTO quiz_history (
                name,
                student_class,
                subject,
                topic,
                score,
                grade,
                questions_json,
                answers_json,
                report_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                student_class,
                subject,
                topic,
                score,
                grade,
                json.dumps(questions),
                json.dumps(answers),
                report_text,
            ),
        )
        connection.commit()


def get_quiz_history(limit=50):
    init_quiz_history_db()
    with closing(get_db_connection()) as connection:
        return connection.execute(
            """
            SELECT
                id,
                name,
                student_class,
                subject,
                topic,
                score,
                grade,
                created_at
            FROM quiz_history
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def split_learning_content(response_text):
    marker = re.search(r"(?im)^\s*#{1,6}\s+Questions\s*$", response_text)
    if not marker:
        raise ValueError("The AI response did not include a Questions section.")

    notes, diagram_steps = split_notes_and_diagram(response_text[:marker.start()])
    questions = []

    for line in response_text[marker.end():].strip().splitlines():
        cleaned_line = re.sub(r"^\s*[-*]\s*", "", line).strip()
        cleaned_line = cleaned_line.replace("**", "").replace("__", "")
        match = re.match(
            r"^Q([1-5])\s*[.):\-]\s*(.+)$",
            cleaned_line,
            re.IGNORECASE,
        )
        if match:
            questions.append((int(match.group(1)), match.group(2).strip()))

    if [number for number, _ in questions] != list(range(1, 6)):
        raise ValueError("The AI response did not include exactly five numbered questions.")

    return notes, diagram_steps, [question for _, question in questions]


def split_notes_and_diagram(notes_text):
    diagram_marker = re.search(
        r"(?im)^\s*#{1,6}\s+Diagram(?:\s+(?:Data|Plan))?\s*$",
        notes_text,
    )
    if not diagram_marker:
        return notes_text.strip(), []

    next_heading = re.search(r"(?m)^\s*#{1,6}\s+", notes_text[diagram_marker.end():])
    diagram_end = (
        diagram_marker.end() + next_heading.start()
        if next_heading
        else len(notes_text)
    )
    diagram_text = notes_text[diagram_marker.end():diagram_end]
    notes_without_diagram = (
        notes_text[:diagram_marker.start()] + notes_text[diagram_end:]
    ).strip()

    diagram_steps = []
    for line in diagram_text.splitlines():
        cleaned_line = re.sub(r"^\s*[-*]\s*", "", line).strip()
        cleaned_line = re.sub(r"^D\d+\s*[.):\-]\s*", "", cleaned_line, flags=re.IGNORECASE)
        cleaned_line = cleaned_line.replace("**", "").replace("__", "").strip()
        if cleaned_line and cleaned_line != "->":
            diagram_steps.append(cleaned_line[:60])

    return notes_without_diagram, diagram_steps[:5]


def load_diagram_font(size, bold=False):
    font_names = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    font_names.extend(["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"])

    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue

    return ImageFont.load_default()


def wrap_diagram_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        candidate = f"{current_line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current_line = candidate
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines[:3]


def create_diagram_image(topic, diagram_steps):
    steps = diagram_steps or [topic, "Important idea", "Simple example"]
    width = 1000
    height = 240 + (len(steps) * 110)
    image = Image.new("RGB", (width, height), "#f6f7fb")
    draw = ImageDraw.Draw(image)
    title_font = load_diagram_font(34, bold=True)
    label_font = load_diagram_font(23, bold=True)
    body_font = load_diagram_font(22)

    draw.rounded_rectangle((40, 35, width - 40, height - 35), radius=28, fill="white")
    title = f"{topic} Diagram"
    title_width = draw.textlength(title, font=title_font)
    draw.text(((width - title_width) / 2, 70), title, fill="#4f46e5", font=title_font)

    colors = ["#eef2ff", "#ecfeff", "#f0fdf4", "#fff7ed", "#fdf2f8"]
    border_colors = ["#6366f1", "#0891b2", "#16a34a", "#f97316", "#db2777"]
    x1, x2 = 180, width - 180
    box_height = 76
    start_y = 145
    gap = 34

    for index, step in enumerate(steps):
        y1 = start_y + index * (box_height + gap)
        y2 = y1 + box_height
        color_index = index % len(colors)

        draw.ellipse(
            (82, y1 + 9, 140, y1 + 67),
            fill=border_colors[color_index],
        )
        number = str(index + 1)
        number_width = draw.textlength(number, font=label_font)
        draw.text(
            (111 - number_width / 2, y1 + 23),
            number,
            fill="white",
            font=label_font,
        )

        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=18,
            fill=colors[color_index],
            outline=border_colors[color_index],
            width=3,
        )

        lines = wrap_diagram_text(draw, step, body_font, x2 - x1 - 70)
        line_height = 26
        text_y = y1 + (box_height - (len(lines) * line_height)) / 2 - 2
        for line in lines:
            line_width = draw.textlength(line, font=body_font)
            draw.text(
                (x1 + ((x2 - x1) - line_width) / 2, text_y),
                line,
                fill="#1f2937",
                font=body_font,
            )
            text_y += line_height

        if index < len(steps) - 1:
            arrow_x = width / 2
            arrow_top = y2 + 5
            arrow_bottom = y2 + gap - 7
            draw.line(
                (arrow_x, arrow_top, arrow_x, arrow_bottom),
                fill="#6b7280",
                width=4,
            )
            draw.polygon(
                [
                    (arrow_x - 11, arrow_bottom - 2),
                    (arrow_x + 11, arrow_bottom - 2),
                    (arrow_x, arrow_bottom + 14),
                ],
                fill="#6b7280",
            )

    output = BytesIO()
    image.save(output, format="PNG")
    encoded_image = b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded_image}"


def required_form_values(prefix, count=5):
    values = [
        request.form.get(f"{prefix}{index}", "").strip()
        for index in range(1, count + 1)
    ]
    if any(not value for value in values):
        abort(400, description=f"All {prefix}s are required.")
    return values


def safe_notes_filename(topic, extension="html"):
    filename_topic = re.sub(r"[^A-Za-z0-9_-]+", "_", topic).strip("_")
    return f"{filename_topic or 'study'}_notes.{extension}"


def safe_report_filename(topic):
    filename_topic = re.sub(r"[^A-Za-z0-9_-]+", "_", topic or "").strip("_")
    return f"{filename_topic or 'study'}_performance_report.pdf"


def add_pdf_background(canvas, doc):
    canvas.saveState()
    width, height = letter
    canvas.setFillColor(colors.HexColor("#f7f4ee"))
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#3157d5"))
    canvas.rect(0, height - 0.34 * inch, width, 0.34 * inch, stroke=0, fill=1)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawCentredString(width / 2, 0.34 * inch, f"AI Study Buddy Report - Page {doc.page}")
    canvas.restoreState()


def report_text_to_flowables(report_text, styles):
    flowables = []

    for raw_line in report_text.splitlines():
        line = raw_line.strip()
        if not line:
            flowables.append(Spacer(1, 5))
            continue

        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            flowables.append(Spacer(1, 8))
            flowables.append(Paragraph(escape(heading), styles["SectionHeading"]))
            continue

        bullet_match = re.match(r"^[-*]\s+(.+)$", line)
        if bullet_match:
            flowables.append(
                Paragraph(f"&bull; {escape(bullet_match.group(1))}", styles["BulletLine"])
            )
            continue

        label_match = re.match(r"^(Score|Grade):\s*(.+)$", line, re.IGNORECASE)
        if label_match:
            label, value = label_match.groups()
            flowables.append(
                Paragraph(
                    f"<b>{escape(label)}:</b> {escape(value)}",
                    styles["ReportBody"],
                )
            )
            continue

        flowables.append(Paragraph(escape(line), styles["ReportBody"]))

    return flowables


def create_performance_pdf(name, subject, topic, score, grade, report_text):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.58 * inch,
        leftMargin=0.58 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.62 * inch,
        pageCompression=0,
    )
    base_styles = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "Title",
            parent=base_styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            textColor=colors.HexColor("#172033"),
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#667085"),
            alignment=TA_CENTER,
            spaceAfter=18,
        ),
        "CardLabel": ParagraphStyle(
            "CardLabel",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#667085"),
            alignment=TA_CENTER,
        ),
        "CardValue": ParagraphStyle(
            "CardValue",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#3157d5"),
            alignment=TA_CENTER,
        ),
        "SectionHeading": ParagraphStyle(
            "SectionHeading",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#3157d5"),
            spaceBefore=8,
            spaceAfter=6,
        ),
        "ReportBody": ParagraphStyle(
            "ReportBody",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#2d3748"),
            spaceAfter=4,
        ),
        "BulletLine": ParagraphStyle(
            "BulletLine",
            parent=base_styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            leftIndent=12,
            textColor=colors.HexColor("#2d3748"),
            spaceAfter=4,
        ),
        "Tip": ParagraphStyle(
            "Tip",
            parent=base_styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#5a3d10"),
        ),
    }

    story = [
        Paragraph("Performance Report", styles["Title"]),
        Paragraph(
            f"Student: {escape(name or 'Student')} &nbsp;&nbsp; | &nbsp;&nbsp; Subject: {escape(subject or 'N/A')} &nbsp;&nbsp; | &nbsp;&nbsp; Topic: {escape(topic or 'N/A')}",
            styles["Subtitle"],
        ),
    ]

    score_cards = Table(
        [
            [
                Paragraph("Score", styles["CardLabel"]),
                Paragraph("Grade", styles["CardLabel"]),
                Paragraph("Topic", styles["CardLabel"]),
            ],
            [
                Paragraph(escape(score or "N/A"), styles["CardValue"]),
                Paragraph(escape(grade or "N/A"), styles["CardValue"]),
                Paragraph(escape(topic or "N/A"), styles["CardValue"]),
            ],
        ],
        colWidths=[1.9 * inch, 1.9 * inch, 1.9 * inch],
    )
    score_cards.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf8")),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#e7dfd2")),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#e7dfd2")),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story.extend([score_cards, Spacer(1, 16)])

    badges = Table(
        [["Topic Explorer", "Active Learner", "Quiz Attempted"]],
        colWidths=[1.9 * inch, 1.9 * inch, 1.9 * inch],
    )
    badges.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#172033")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([badges, Spacer(1, 16)])
    story.extend(report_text_to_flowables(report_text, styles))
    story.extend(
        [
            Spacer(1, 12),
            Table(
                [[Paragraph("Study Tip: Revise the notes once more and try answering all questions without looking at the notes.", styles["Tip"])]],
                colWidths=[5.7 * inch],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7e6")),
                        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#f0b35f")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 12),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                ),
            ),
        ]
    )

    doc.build(story, onFirstPage=add_pdf_background, onLaterPages=add_pdf_background)
    buffer.seek(0)
    return buffer


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/history")
def history():
    return render_template("history.html", attempts=get_quiz_history())


@app.route("/learn", methods=["POST"])
def learn():
    name = request.form.get("name", "").strip()
    student_class = request.form.get("student_class", "").strip()
    subject = request.form.get("subject", "").strip()
    topic = request.form.get("topic", "").strip()

    if not name or not student_class or not subject or not topic:
        abort(400, description="Name, class, subject, and topic are required.")

    prompt = f"""
You are a school teacher.

Subject: {subject}
Topic: {topic}

Explain the topic for a Class {student_class} student using the subject context.

Rules:
- Use very simple language
- Use short sentences
- Use headings
- Use bullet points
- Give examples

After the explanation create:

## Quick Revision
Give 5 important revision points.

## Diagram Data

Create 3 to 5 short labels for a visual educational diagram.
Use exactly this format:
D1: label
D2: label
D3: label
Do NOT create a text diagram.
Do NOT use arrows.
Keep each label short.
## Questions

Create exactly 5 short-answer questions.

Rules:
- Number questions as Q1, Q2, Q3, Q4 and Q5.
- Put each question on a new line.
- Leave one blank line between questions.
- Do NOT provide answers.
- Do NOT put all questions in one paragraph.
"""

    try:
        print("Gemini call: Learn")
        response = generate_content_with_fallback(prompt)
    except Exception as error:
        print("LEARN ERROR:", error)
        abort(503, description="The learning service is unavailable. Please try again later.")

    try:
        notes, diagram_steps, questions = split_learning_content(response.text)
    except ValueError as error:
        print("LEARN RESPONSE ERROR:", error)
        abort(502, description="The AI did not return a valid five-question quiz. Please try again.")

    diagram_image = create_diagram_image(topic, diagram_steps)

    return render_template(
        "learn.html",
        name=name,
        student_class=student_class,
        subject=subject,
        topic=topic,
        explanation=markdown.markdown(notes),
        notes=notes,
        diagram_image=diagram_image,
        questions=questions,
    )


@app.route("/download_notes", methods=["POST"])
def download_notes():
    name = request.form.get("name", "").strip()
    student_class = request.form.get("student_class", "").strip()
    subject = request.form.get("subject", "").strip()
    topic = request.form.get("topic", "").strip()
    notes = request.form.get("notes", "").strip()
    diagram_image = request.form.get("diagram_image", "").strip()

    if not topic or not notes:
        abort(400, description="Topic and notes are required.")

    notes_html = markdown.markdown(notes)
    diagram_html = ""
    if diagram_image.startswith("data:image/png;base64,"):
        diagram_html = f"""
        <section class="diagram">
            <h2>Diagram</h2>
            <img src="{diagram_image}" alt="{escape(topic)} diagram">
        </section>
"""
    notes_document = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{escape(topic)} - AI Study Buddy Notes</title>
    <style>
        body {{
            margin: 0;
            padding: 32px;
            font-family: 'Segoe UI', Arial, sans-serif;
            color: #333;
            background: #f6f7fb;
        }}
        .notes-page {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            padding: 36px;
            border-radius: 16px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
        }}
        h1, h2, h3 {{
            color: #4f46e5;
        }}
        .student {{
            color: #555;
            font-size: 18px;
            margin-bottom: 24px;
        }}
        .content {{
            font-size: 20px;
            line-height: 1.8;
        }}
        li {{
            margin: 10px 0;
        }}
        .diagram {{
            margin: 30px 0;
        }}
        .diagram img {{
            display: block;
            width: 100%;
            max-width: 900px;
            height: auto;
            border-radius: 16px;
            border: 1px solid #e5e7eb;
        }}
    </style>
</head>
<body>
    <main class="notes-page">
        <h1>{escape(topic)}</h1>
        <div class="student">Student: {escape(name or 'Student')} | Class: {escape(student_class or 'N/A')} | Subject: {escape(subject or 'N/A')}</div>
        <div class="content">
            {notes_html}
        </div>
        {diagram_html}
    </main>
</body>
</html>
"""
    notes_file = BytesIO(notes_document.encode("utf-8"))

    return send_file(
        notes_file,
        mimetype="text/html",
        as_attachment=True,
        download_name=safe_notes_filename(topic),
    )


@app.route("/quiz", methods=["POST"])
def quiz():
    name = request.form.get("name", "").strip()
    student_class = request.form.get("student_class", "").strip()
    subject = request.form.get("subject", "").strip()
    topic = request.form.get("topic", "").strip()
    questions = required_form_values("question")

    if not name or not student_class or not subject or not topic:
        abort(400, description="Name, class, subject, and topic are required.")

    return render_template(
        "quiz.html",
        name=name,
        student_class=student_class,
        subject=subject,
        topic=topic,
        questions=questions,
    )


@app.route("/submit_answers", methods=["POST"])
def submit_answers():
    name = request.form.get("name", "").strip()
    student_class = request.form.get("student_class", "").strip()
    subject = request.form.get("subject", "").strip()
    topic = request.form.get("topic", "").strip()
    questions = required_form_values("question")
    answers = required_form_values("answer")

    if not name or not student_class or not subject or not topic:
        abort(400, description="Name, class, subject, and topic are required.")

    question_and_answer_text = "\n".join(
        f"Q{index}: {question}\nStudent answer: {answer}"
        for index, (question, answer) in enumerate(
            zip(questions, answers),
            start=1,
        )
    )

    evaluation_prompt = f"""
You are a teacher.

Topic: {topic}
Class: {student_class}
Subject: {subject}

Student Answers:

{question_and_answer_text}

Evaluate the answers.

Give the result in exactly this format:

# Performance Summary

Score: X/10

Grade: A+/A/B+/B/C

# Strengths
- Point 1
- Point 2
- Point 3

# Weak Areas
- Point 1
- Point 2
- Point 3

# Study Tips
- Tip 1
- Tip 2
- Tip 3

# Suggestions for Improvement
- Suggestion 1
- Suggestion 2
- Suggestion 3

Be encouraging and student-friendly.
"""

    try:
        print("Gemini call: Evaluation")
        response = generate_content_with_fallback(evaluation_prompt)
    except Exception as error:
        print("EVALUATION ERROR:", error)
        if "429" in str(error):
            abort(503, description="Gemini quota reached. Please try again later.")
        abort(503, description="The evaluation service is unavailable. Please try again later.")

    report = markdown.markdown(response.text)
    score_match = re.search(r"Score:\s*(\d+/10)", response.text)
    grade_match = re.search(r"Grade:\s*([A-Z+]+)", response.text)

    score = score_match.group(1) if score_match else "N/A"
    grade = grade_match.group(1) if grade_match else "N/A"

    save_quiz_history(
        name,
        student_class,
        subject,
        topic,
        score,
        grade,
        questions,
        answers,
        response.text,
    )

    global latest_report
    latest_report = {
        "name": name,
        "student_class": student_class,
        "subject": subject,
        "topic": topic,
        "score": score,
        "grade": grade,
        "report_text": response.text,
    }

    return render_template(
        "result.html",
        name=name,
        student_class=student_class,
        subject=subject,
        topic=topic,
        report=report,
        report_text=response.text,
        score=score,
        grade=grade,
    )


@app.route("/download_pdf", methods=["GET", "POST"])
def download_pdf():
    values = request.form if request.method == "POST" else request.args
    name = values.get("name", "").strip()
    subject = values.get("subject", "").strip()
    topic = values.get("topic", "").strip()
    score = values.get("score", "").strip()
    grade = values.get("grade", "").strip()
    report_text = values.get("report_text", "").strip()

    if not report_text and latest_report:
        name = name or latest_report.get("name", "")
        subject = subject or latest_report.get("subject", "")
        topic = topic or latest_report.get("topic", "")
        score = score or latest_report.get("score", "")
        grade = grade or latest_report.get("grade", "")
        report_text = latest_report.get("report_text", "")

    if not topic or not report_text:
        abort(400, description="Topic and report content are required.")

    pdf_file = create_performance_pdf(name, subject, topic, score, grade, report_text)

    return send_file(
        pdf_file,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=safe_report_filename(topic),
    )


@app.route("/test")
def test():
    return "PDF Route Test"


if __name__ == "__main__":
    app.run(debug=True)
