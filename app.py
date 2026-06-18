from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from base64 import b64encode
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import google.generativeai as genai
from html import escape
from io import BytesIO
from pathlib import Path
from contextlib import closing
from functools import lru_cache, wraps
from difflib import SequenceMatcher
from werkzeug.security import check_password_hash, generate_password_hash
import json
import markdown
import os
import re
import sqlite3
from dotenv import load_dotenv

load_dotenv()
from config import GEMINI_API_KEY, GEMINI_API_KEY_2


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ai-study-buddy-dev-secret-key")


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
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(quiz_history)").fetchall()
        }
        if "user_id" not in existing_columns:
            connection.execute("ALTER TABLE quiz_history ADD COLUMN user_id INTEGER")
        connection.commit()


def init_users_db():
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                student_class TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def init_account_activity_db():
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                student_class TEXT NOT NULL,
                subject TEXT NOT NULL,
                book_name TEXT,
                topic TEXT NOT NULL,
                notes TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS downloaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                subject TEXT,
                topic TEXT NOT NULL,
                score TEXT,
                grade TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def init_learning_history_db():
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                book_name TEXT,
                topic TEXT NOT NULL,
                notes TEXT NOT NULL,
                diagram_data TEXT NOT NULL,
                quiz_questions TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def get_user_by_id(user_id):
    if not user_id:
        return None

    init_users_db()
    with closing(get_db_connection()) as connection:
        return connection.execute(
            """
            SELECT id, full_name, username, email, student_class, created_at
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()


def get_user_by_username_or_email(identifier):
    init_users_db()
    normalized_identifier = identifier.strip().lower()
    with closing(get_db_connection()) as connection:
        return connection.execute(
            """
            SELECT *
            FROM users
            WHERE lower(username) = ? OR lower(email) = ?
            """,
            (normalized_identifier, normalized_identifier),
        ).fetchone()


def create_user(full_name, username, email, student_class, password):
    init_users_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            INSERT INTO users (
                full_name,
                username,
                email,
                student_class,
                password_hash
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                full_name,
                username,
                email.lower(),
                student_class,
                generate_password_hash(password),
            ),
        )
        connection.commit()


def current_user():
    return get_user_by_id(session.get("user_id"))


@app.context_processor
def inject_current_user():
    return {
        "current_user": current_user(),
        "user": {
            "id": session.get("user_id"),
            "name": session.get("user_name"),
            "full_name": session.get("user_name"),
            "username": session.get("username"),
        } if session.get("user_id") else None,
    }


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash(
                "Login required. Create a free account to save your progress and unlock personalized learning.",
                "error",
            )
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def validate_registration_form(form):
    full_name = form.get("full_name", "").strip()
    username = form.get("username", "").strip()
    email = form.get("email", "").strip()
    student_class = form.get("student_class", "").strip()
    password = form.get("password", "")
    confirm_password = form.get("confirm_password", "")
    errors = []

    if not full_name:
        errors.append("Full name is required.")
    if not username:
        errors.append("Username is required.")
    elif not re.fullmatch(r"[A-Za-z0-9_]{3,30}", username):
        errors.append("Username must be 3 to 30 characters and use only letters, numbers, or underscores.")
    if not email:
        errors.append("Email is required.")
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("Please enter a valid email address.")
    if not student_class:
        errors.append("Class is required.")
    if not password:
        errors.append("Password is required.")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if password != confirm_password:
        errors.append("Passwords do not match.")

    return (
        {
            "full_name": full_name,
            "username": username,
            "email": email,
            "student_class": student_class,
            "password": password,
        },
        errors,
    )


def save_learning_session(user_id, name, student_class, subject, book_name, topic, notes):
    init_account_activity_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            INSERT INTO learning_sessions (
                user_id,
                name,
                student_class,
                subject,
                book_name,
                topic,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, student_class, subject, book_name, topic, notes),
        )
        connection.commit()


def save_learning_history(user_id, subject, book_name, topic, notes, diagram_data, quiz_questions):
    init_learning_history_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            INSERT INTO learning_history (
                user_id,
                subject,
                book_name,
                topic,
                notes,
                diagram_data,
                quiz_questions
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                subject,
                book_name,
                topic,
                notes,
                json.dumps(diagram_data),
                json.dumps(quiz_questions),
            ),
        )
        connection.commit()


LEARNING_HISTORY_FILTERS = [
    ("all", "All"),
    ("science", "Science"),
    ("mathematics", "Mathematics"),
    ("english", "English"),
    ("social-science", "Social Science"),
    ("computer", "Computer"),
]


def subject_filter_pattern(filter_value):
    return {
        "science": "%science%",
        "mathematics": "%math%",
        "english": "%english%",
        "social-science": "%social%",
        "computer": "%computer%",
    }.get(filter_value)


def get_learning_history_entries(user_id, search="", subject_filter="all", sort_order="newest"):
    init_learning_history_db()
    clauses = ["user_id = ?"]
    parameters = [user_id]
    search_text = search.strip().lower()

    if search_text:
        clauses.append(
            """
            (
                lower(subject) LIKE ?
                OR lower(COALESCE(book_name, '')) LIKE ?
                OR lower(topic) LIKE ?
            )
            """
        )
        like_value = f"%{search_text}%"
        parameters.extend([like_value, like_value, like_value])

    pattern = subject_filter_pattern(subject_filter)
    if pattern:
        clauses.append("lower(subject) LIKE ?")
        parameters.append(pattern)

    direction = "ASC" if sort_order == "oldest" else "DESC"
    with closing(get_db_connection()) as connection:
        return connection.execute(
            f"""
            SELECT
                id,
                user_id,
                subject,
                book_name,
                topic,
                notes,
                diagram_data,
                quiz_questions,
                created_at
            FROM learning_history
            WHERE {" AND ".join(clauses)}
            ORDER BY datetime(created_at) {direction}, id {direction}
            """,
            parameters,
        ).fetchall()


def get_learning_history_entry(entry_id, user_id):
    init_learning_history_db()
    with closing(get_db_connection()) as connection:
        return connection.execute(
            """
            SELECT
                id,
                user_id,
                subject,
                book_name,
                topic,
                notes,
                diagram_data,
                quiz_questions,
                created_at
            FROM learning_history
            WHERE id = ? AND user_id = ?
            """,
            (entry_id, user_id),
        ).fetchone()


def delete_learning_history_entry(entry_id, user_id):
    init_learning_history_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            DELETE FROM learning_history
            WHERE id = ? AND user_id = ?
            """,
            (entry_id, user_id),
        )
        connection.commit()


def decode_json_list(value):
    try:
        decoded_value = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []

    return decoded_value if isinstance(decoded_value, list) else []


def save_downloaded_file(user_id, file_type, subject, topic, score="", grade=""):
    init_account_activity_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            INSERT INTO downloaded_files (
                user_id,
                file_type,
                subject,
                topic,
                score,
                grade
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, file_type, subject, topic, score, grade),
        )
        connection.commit()


def save_quiz_history(name, student_class, subject, topic, score, grade, questions, answers, report_text, user_id=None):
    init_quiz_history_db()
    with closing(get_db_connection()) as connection:
        connection.execute(
            """
            INSERT INTO quiz_history (
                user_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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


def get_quiz_history(limit=50, user_id=None):
    init_quiz_history_db()
    where_clause = "WHERE user_id = ?" if user_id else ""
    parameters = (user_id, limit) if user_id else (limit,)
    with closing(get_db_connection()) as connection:
        return connection.execute(
            f"""
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
            {where_clause}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()


def score_to_number(score):
    match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", score or "")
    return float(match.group(1)) if match else None


def get_recent_learning_activity(user_id, limit=5):
    init_quiz_history_db()
    init_account_activity_db()
    init_learning_history_db()
    with closing(get_db_connection()) as connection:
        return connection.execute(
            """
            SELECT
                subject,
                topic,
                'Not attempted' AS score,
                created_at
            FROM learning_history
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()


def calculate_study_streak(activity_dates):
    normalized_dates = sorted(
        {
            date_text[:10]
            for date_text in activity_dates
            if date_text
        },
        reverse=True,
    )
    if not normalized_dates:
        return 0

    streak = 1
    current_date = normalized_dates[0]
    for next_date in normalized_dates[1:]:
        with closing(get_db_connection()) as connection:
            day_difference = connection.execute(
                "SELECT julianday(?) - julianday(?)",
                (current_date, next_date),
            ).fetchone()[0]
        if day_difference == 1:
            streak += 1
            current_date = next_date
        elif day_difference > 1:
            break

    return streak


def get_dashboard_stats(user_id):
    init_quiz_history_db()
    init_account_activity_db()
    init_learning_history_db()
    with closing(get_db_connection()) as connection:
        quiz_rows = connection.execute(
            """
            SELECT topic, score, created_at
            FROM quiz_history
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
        lesson_rows = connection.execute(
            """
            SELECT topic, created_at
            FROM learning_history
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
        downloaded_count = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM downloaded_files
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()["total"]

    scores = [
        numeric_score
        for numeric_score in (score_to_number(row["score"]) for row in quiz_rows)
        if numeric_score is not None
    ]
    topics_studied = len(lesson_rows)
    quizzes_attempted = len(quiz_rows)
    average_score = f"{sum(scores) / len(scores):.1f}/10" if scores else "0"
    study_streak = calculate_study_streak(
        [row["created_at"] for row in lesson_rows] + [row["created_at"] for row in quiz_rows]
    )
    achievements_count = (
        1
        + (1 if topics_studied else 0)
        + (1 if quizzes_attempted else 0)
        + (1 if downloaded_count else 0)
        + (1 if study_streak >= 7 else 0)
    )

    return {
        "topics_studied": topics_studied,
        "quizzes_attempted": quizzes_attempted,
        "average_score": average_score,
        "achievements": achievements_count,
        "study_streak": study_streak,
    }


def dashboard_achievements(stats):
    return [
        {
            "icon": "&#129351;",
            "title": "First Login",
            "description": "Account created and ready.",
            "unlocked": True,
        },
        {
            "icon": "&#128214;",
            "title": "First Lesson",
            "description": "Start a lesson to unlock.",
            "unlocked": stats["topics_studied"] > 0,
        },
        {
            "icon": "&#128221;",
            "title": "First Quiz",
            "description": "Complete a quiz to unlock.",
            "unlocked": stats["quizzes_attempted"] > 0,
        },
        {
            "icon": "&#128293;",
            "title": "7-Day Streak",
            "description": "Study for seven days.",
            "unlocked": stats["study_streak"] >= 7,
        },
    ]


def recommended_topics():
    return [
        {"subject": "Science", "topic": "Photosynthesis"},
        {"subject": "Mathematics", "topic": "Linear Equations"},
        {"subject": "English", "topic": "Grammar Revision"},
    ]


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


def create_learning_history_pdf(entry, diagram_steps, questions):
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
    }
    story = [
        Paragraph(escape(entry["topic"]), styles["Title"]),
        Paragraph(
            (
                f"Subject: {escape(entry['subject'])} &nbsp;&nbsp; | &nbsp;&nbsp; "
                f"Book: {escape(entry['book_name'] or 'N/A')} &nbsp;&nbsp; | &nbsp;&nbsp; "
                f"Saved: {escape(entry['created_at'])}"
            ),
            styles["Subtitle"],
        ),
    ]
    story.extend(report_text_to_flowables(entry["notes"], styles))

    if diagram_steps:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Diagram", styles["SectionHeading"]))
        diagram_image = create_diagram_image(entry["topic"], diagram_steps)
        if diagram_image.startswith("data:image/png;base64,"):
            import base64

            image_data = BytesIO(base64.b64decode(diagram_image.split(",", 1)[1]))
            story.append(RLImage(image_data, width=5.7 * inch, height=2.2 * inch))

    if questions:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Quiz Questions", styles["SectionHeading"]))
        for index, question in enumerate(questions, start=1):
            story.append(Paragraph(f"Q{index}. {escape(question)}", styles["ReportBody"]))

    doc.build(story, onFirstPage=add_pdf_background, onLaterPages=add_pdf_background)
    buffer.seek(0)
    return buffer


TEXTBOOK_SUBJECTS = (
    "english",
    "hindi",
    "bengali",
    "history",
    "geography",
    "civics",
    "sst",
    "social science",
)

SCIENCE_MATH_SUBJECTS = (
    "science",
    "math",
    "maths",
    "mathematics",
)

TEXTBOOK_REGISTRY = {
    ("9", "english", "kaveri"): Path("textbooks") / "class_9" / "english" / "kaveri",
}


def subject_matches(subject, subject_keywords):
    subject_key = subject.lower()
    return any(subject_keyword in subject_key for subject_keyword in subject_keywords)


def normalize_lookup_value(value):
    return re.sub(r"\s+", " ", value.strip().lower())


def topic_search_terms(topic):
    normalized_topic = normalize_lookup_value(topic)
    terms = [normalized_topic]
    without_article = re.sub(r"^(?:the|a|an)\s+", "", normalized_topic)
    if without_article and without_article not in terms:
        terms.append(without_article)
    return terms


def textbook_lookup_key(student_class, subject, book_name):
    normalized_class = normalize_lookup_value(student_class).replace("class ", "")
    return (
        normalized_class,
        normalize_lookup_value(subject),
        normalize_lookup_value(book_name),
    )


def find_registered_textbook(student_class, subject, book_name):
    if not book_name:
        return None

    relative_path = TEXTBOOK_REGISTRY.get(
        textbook_lookup_key(student_class, subject, book_name)
    )
    if not relative_path:
        return None

    return Path(app.root_path) / relative_path


@lru_cache(maxsize=16)
def extract_pdf_text(pdf_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        print("PDF extraction unavailable: install pypdf.")
        return ""

    try:
        reader = PdfReader(pdf_path)
        page_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as error:
        print("PDF EXTRACTION ERROR:", error)
        return ""

    return "\n".join(page_text)


def find_topic_start(compact_text, topic):
    for search_term in topic_search_terms(topic):
        match = re.search(re.escape(search_term), compact_text, re.IGNORECASE)
        if match:
            return match.start()

    best_score = 0
    best_start = None
    topic_term = topic_search_terms(topic)[-1]
    topic_words = topic_term.split()
    if len(topic_words) < 2:
        return None

    words = list(re.finditer(r"\b[\w'-]+\b", compact_text))
    window_sizes = {
        size
        for size in (len(topic_words) - 1, len(topic_words), len(topic_words) + 1)
        if size > 0
    }

    for window_size in window_sizes:
        for index in range(0, len(words) - window_size + 1):
            candidate = " ".join(
                word.group(0).lower()
                for word in words[index:index + window_size]
            )
            score = SequenceMatcher(None, topic_term, candidate).ratio()
            if score > best_score:
                best_score = score
                best_start = words[index].start()

    if best_score >= 0.86:
        return best_start
    return None


def extract_chapter_context(pdf_path, topic, max_chars=14000):
    raw_text = extract_pdf_text(str(pdf_path))
    compact_text = re.sub(r"\s+", " ", raw_text).strip()
    if not compact_text:
        return ""

    topic_start = find_topic_start(compact_text, topic)
    if topic_start is None:
        return ""

    start = max(0, topic_start - 800)
    end = min(len(compact_text), topic_start + max_chars)
    return compact_text[start:end].strip()


def textbook_pdf_paths(textbook_path):
    if textbook_path.is_file() and textbook_path.suffix.lower() == ".pdf":
        return [textbook_path]
    if textbook_path.is_dir():
        return sorted(textbook_path.glob("*.pdf"))
    return []


def find_chapter_context(textbook_path, topic):
    for pdf_path in textbook_pdf_paths(textbook_path):
        chapter_context = extract_chapter_context(pdf_path, topic)
        if chapter_context:
            return pdf_path, chapter_context
    return None, ""


def local_textbook_context_section(student_class, subject, book_name, topic):
    textbook_path = find_registered_textbook(student_class, subject, book_name)
    if not textbook_path:
        return ""

    if not textbook_path.exists():
        return f"""
Local Textbook PDF Context:
- A textbook is registered for this class, subject, and book name.
- Expected PDF path: {textbook_path}
- The PDF file is not available locally.
- Do not guess chapter content.
"""

    chapter_pdf_path, chapter_context = find_chapter_context(textbook_path, topic)
    if not chapter_context:
        return f"""
Local Textbook PDF Context:
- Registered textbook files were found at: {textbook_path}
- The requested chapter title was not found in the extracted PDF text.
- Do not guess chapter content.
- Clearly state: "I do not have enough information about this chapter."
"""

    return f"""
Local Textbook PDF Context:
Matched PDF: {chapter_pdf_path}
Use only this extracted textbook context for the chapter:

{chapter_context}
"""


def textbook_prompt_section():
    return """
Textbook Subject Instructions:
- The topic is a chapter title from a school textbook.
- The book name identifies the textbook.
- Use the actual chapter content whenever known.
- Do NOT invent stories.
- Do NOT invent characters.
- Do NOT create fictional summaries.
- Do NOT use these words in the answer: likely, probably, might, perhaps.
- Never guess chapter content.
- If the chapter is unknown, clearly state: "I do not have enough information about this chapter."
- Stay focused on the chapter title and textbook.
- Generate chapter notes, revision points, diagram labels, and questions only from the chapter.
- If the chapter is unknown, still return the required sections and create questions that ask the student to find details in the textbook, without adding any chapter facts.
"""


def science_math_prompt_section():
    return """
Science and Mathematics Instructions:
- Explain the concept normally.
- Use examples and simple language.
- Explain important ideas step by step.
"""


def general_prompt_section():
    return """
General Subject Instructions:
- Explain the topic clearly.
- Use simple examples where helpful.
- Stay focused on the topic.
"""


def learning_subject_prompt_section(subject):
    if subject_matches(subject, TEXTBOOK_SUBJECTS):
        return textbook_prompt_section()
    if subject_matches(subject, SCIENCE_MATH_SUBJECTS):
        return science_math_prompt_section()
    return general_prompt_section()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    init_users_db()
    form_data = {
        "full_name": "",
        "username": "",
        "email": "",
        "student_class": "",
    }

    if request.method == "POST":
        form_data, errors = validate_registration_form(request.form)

        if not errors:
            existing_user = get_user_by_username_or_email(form_data["username"])
            existing_email = get_user_by_username_or_email(form_data["email"])

            if existing_user:
                errors.append("That username is already taken.")
            if existing_email:
                errors.append("That email is already registered.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("register.html", form_data=form_data), 400

        try:
            create_user(
                form_data["full_name"],
                form_data["username"],
                form_data["email"],
                form_data["student_class"],
                form_data["password"],
            )
        except sqlite3.IntegrityError:
            flash("Username or email is already registered.", "error")
            return render_template("register.html", form_data=form_data), 400

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form_data=form_data)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")

        if not identifier or not password:
            flash("Username/email and password are required.", "error")
            return render_template("login.html", identifier=identifier), 400

        account = get_user_by_username_or_email(identifier)
        if not account or not check_password_hash(account["password_hash"], password):
            flash("Invalid username/email or password.", "error")
            return render_template("login.html", identifier=identifier), 401

        session.clear()
        session["user_id"] = account["id"]
        session["user_name"] = account["full_name"]
        session["username"] = account["username"]

        next_url = request.args.get("next", "")
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("dashboard"))

    return render_template("login.html", identifier="")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    account = current_user()
    stats = get_dashboard_stats(account["id"])
    return render_template(
        "dashboard.html",
        account=account,
        stats=stats,
        recent_activity=get_recent_learning_activity(account["id"]),
        achievements=dashboard_achievements(stats),
        recommendations=recommended_topics(),
    )


@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", account=current_user())


@app.route("/learning-history")
def learning_history():
    if not session.get("user_id"):
        return render_template("learning_history.html", guest_locked=True)

    search = request.args.get("search", "").strip()
    subject_filter = request.args.get("subject", "all").strip().lower()
    sort_order = request.args.get("sort", "newest").strip().lower()
    if subject_filter not in {value for value, _ in LEARNING_HISTORY_FILTERS}:
        subject_filter = "all"
    if sort_order not in {"newest", "oldest"}:
        sort_order = "newest"

    return render_template(
        "learning_history.html",
        guest_locked=False,
        lessons=get_learning_history_entries(
            session["user_id"],
            search=search,
            subject_filter=subject_filter,
            sort_order=sort_order,
        ),
        filters=LEARNING_HISTORY_FILTERS,
        search=search,
        subject_filter=subject_filter,
        sort_order=sort_order,
    )


@app.route("/learning-history/<int:lesson_id>")
@login_required
def view_learning_history(lesson_id):
    lesson = get_learning_history_entry(lesson_id, session["user_id"])
    if not lesson:
        abort(404)

    diagram_steps = decode_json_list(lesson["diagram_data"])
    questions = decode_json_list(lesson["quiz_questions"])
    return render_template(
        "learning_history_detail.html",
        lesson=lesson,
        notes_html=markdown.markdown(lesson["notes"]),
        diagram_image=create_diagram_image(lesson["topic"], diagram_steps),
        questions=questions,
    )


@app.route("/learning-history/<int:lesson_id>/download")
@login_required
def download_learning_history_pdf(lesson_id):
    lesson = get_learning_history_entry(lesson_id, session["user_id"])
    if not lesson:
        abort(404)

    pdf_file = create_learning_history_pdf(
        lesson,
        decode_json_list(lesson["diagram_data"]),
        decode_json_list(lesson["quiz_questions"]),
    )
    save_downloaded_file(
        session["user_id"],
        "saved_lesson",
        lesson["subject"],
        lesson["topic"],
    )
    return send_file(
        pdf_file,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=safe_notes_filename(lesson["topic"], extension="pdf"),
    )


@app.route("/learning-history/<int:lesson_id>/delete", methods=["POST"])
@login_required
def delete_learning_history(lesson_id):
    delete_learning_history_entry(lesson_id, session["user_id"])
    flash("Saved lesson deleted.", "success")
    return redirect(url_for("learning_history"))


@app.route("/downloaded-reports")
@login_required
def downloaded_reports():
    return render_template(
        "placeholder.html",
        page_title="Downloaded Reports",
        heading="Downloaded reports coming soon",
        message="Future downloaded performance reports will appear here.",
    )


@app.route("/favourite-notes")
@login_required
def favourite_notes():
    return render_template(
        "placeholder.html",
        page_title="Favourite Notes",
        heading="Favourite notes coming soon",
        message="Saved and favourite notes will appear here.",
    )


@app.route("/settings")
@login_required
def settings():
    return render_template(
        "placeholder.html",
        page_title="Settings",
        heading="Settings coming soon",
        message="Future account and learning preferences will appear here.",
    )


@app.route("/history")
@app.route("/quiz-history")
@login_required
def history():
    return render_template("history.html", attempts=get_quiz_history(user_id=session["user_id"]))


@app.route("/learn", methods=["POST"])
def learn():
    name = request.form.get("name", "").strip()
    student_class = request.form.get("student_class", "").strip()
    subject = request.form.get("subject", "").strip()
    book_name = request.form.get("book_name", "").strip()
    topic = request.form.get("topic", "").strip()

    if not name or not student_class or not subject or not topic:
        abort(400, description="Name, class, subject, and topic are required.")

    subject_prompt_section = learning_subject_prompt_section(subject)
    textbook_context_section = local_textbook_context_section(
        student_class,
        subject,
        book_name,
        topic,
    )

    prompt = f"""
You are a school teacher.

Class: {student_class}
Subject: {subject}
Book Name: {book_name}
Topic: {topic}

{subject_prompt_section}
{textbook_context_section}

Rules:
- Use very simple language
- Use short sentences
- Use headings
- Use bullet points
- Give examples
- Make the notes easy to read for a school student.
- Highlight each main point in bold.
- After each main point, give a brief explanation in 1 to 2 short sentences.
- Do not put many facts in one long paragraph.
- Put each important point on a separate line or bullet.
- Do not use inline asterisks as separators.
- For chapter notes, prefer this format:
  - **Main point:** Brief explanation.

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
- Always include the exact heading "## Questions".
- Always include exactly 5 questions, even if the chapter is unknown.
- If the chapter is unknown, questions must not include invented facts.
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
        retry_prompt = f"""
{prompt}

Your previous response did not follow the required format.
Rewrite the answer using this exact structure:

# Notes

## Quick Revision
- point 1
- point 2
- point 3
- point 4
- point 5

## Diagram Data
D1: label
D2: label
D3: label

## Questions
Q1. question

Q2. question

Q3. question

Q4. question

Q5. question

Do not provide answers to the questions.
Do not invent textbook chapter content.
"""
        try:
            print("Gemini call: Learn retry")
            response = generate_content_with_fallback(retry_prompt)
            notes, diagram_steps, questions = split_learning_content(response.text)
        except Exception as retry_error:
            print("LEARN RETRY ERROR:", retry_error)
            abort(502, description="The AI did not return a valid five-question quiz. Please try again.")

    diagram_image = create_diagram_image(topic, diagram_steps)

    if session.get("user_id"):
        save_learning_history(
            session["user_id"],
            subject,
            book_name,
            topic,
            notes,
            diagram_steps,
            questions,
        )
        save_learning_session(
            session["user_id"],
            name,
            student_class,
            subject,
            book_name,
            topic,
            notes,
        )

    return render_template(
        "learn.html",
        name=name,
        student_class=student_class,
        subject=subject,
        book_name=book_name,
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

    if session.get("user_id"):
        save_downloaded_file(
            session["user_id"],
            "notes",
            subject,
            topic,
        )

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

    if session.get("user_id"):
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
            user_id=session["user_id"],
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

    if session.get("user_id"):
        save_downloaded_file(
            session["user_id"],
            "performance_report",
            subject,
            topic,
            score,
            grade,
        )

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
