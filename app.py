from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from base64 import b64encode
from collections import Counter, defaultdict
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
from datetime import datetime, timedelta, timezone
from functools import lru_cache, wraps
from difflib import SequenceMatcher
from werkzeug.security import check_password_hash, generate_password_hash
from urllib.parse import quote
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import load_only
import json
import markdown
import os
import re
from dotenv import load_dotenv

load_dotenv()
from config import GEMINI_API_KEY, GEMINI_API_KEY_2
from database import configure_database, create_database_tables, db, rollback_database_session
from models import DownloadedFile, LearningHistory, LearningSession, QuizHistory, User


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "ai-study-buddy-dev-secret-key"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_REFRESH_EACH_REQUEST=True,
)
configure_database(app)
latest_report = {}
genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-2.5-flash")

@app.errorhandler(SQLAlchemyError)
def handle_database_error(error):
    rollback_database_session(error)

    app.logger.error(
        "Database error while handling %s %s",
        request.method,
        request.path,
        exc_info=(type(error), error, error.__traceback__),
    )

    return (
        "<h2>Database Error</h2><p>The database is temporarily unavailable.</p>",
        503,
    )


def initialize_database():
    with app.app_context():
        create_database_tables()
        ensure_user_roles()
        app.logger.info("Database tables are ready.")


ROLE_DEFINITIONS = {
    "developer": {
        "label": "Developer",
        "badge": "&#128311; Developer",
        "class": "role-developer",
        "permissions": "Full access",
    },
    "technical_support": {
        "label": "Technical Support",
        "badge": "&#128995; Technical Support",
        "class": "role-technical-support",
        "permissions": "Support access",
    },
    "qa_tester": {
        "label": "Testing & Quality Assurance",
        "badge": "&#128994; Testing &amp; Quality Assurance",
        "class": "role-qa-tester",
        "permissions": "Testing access",
    },
    "student": {
        "label": "Student",
        "badge": "&#9898; Student",
        "class": "role-student",
        "permissions": "Student access",
    },
}

SPECIAL_ROLE_ACCOUNTS = {
    ("manjit", "manjit"): "developer",
    ("manjit saha", "manjit"): "developer",
    ("manjit saha", "manjitsaha"): "developer",
    ("gyanjyoti mahanta", "gyanjyoti"): "technical_support",
    ("lakshya tuwani", "lakshya"): "qa_tester",
}

WEBSITE_VERSION = os.environ.get("WEBSITE_VERSION", "AI Study Buddy 1.0")
DEVELOPER_USERS_PER_PAGE = 25


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


def init_quiz_history_db():
    return None


def init_users_db():
    return None


def normalize_account_name(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def resolve_account_role(full_name, username=""):
    normalized_name = normalize_account_name(full_name)
    normalized_username = normalize_account_name(username)
    return SPECIAL_ROLE_ACCOUNTS.get((normalized_name, normalized_username), "student")


def normalize_role(role):
    return role if role in ROLE_DEFINITIONS else "student"


def role_details(role):
    return ROLE_DEFINITIONS[normalize_role(role)]


def ensure_user_roles():
    User.query.filter(or_(User.role.is_(None), User.role == "")).update(
        {"role": "student"},
        synchronize_session=False,
    )
    for (normalized_name, normalized_username), role in SPECIAL_ROLE_ACCOUNTS.items():
        User.query.filter(
            func.lower(User.full_name) == normalized_name,
            func.lower(User.username) == normalized_username,
            User.role != role,
        ).update({"role": role}, synchronize_session=False)
    db.session.commit()


def apply_predefined_roles():
    ensure_user_roles()


def init_account_activity_db():
    return None


def init_learning_history_db():
    return None


def get_user_by_id(user_id):
    if not user_id:
        return None

    return db.session.get(User, user_id)


def get_user_by_username_or_email(identifier):
    normalized_identifier = identifier.strip().lower()
    return User.query.filter(
        or_(
            func.lower(User.username) == normalized_identifier,
            func.lower(User.email) == normalized_identifier,
        )
    ).first()


def find_registration_conflicts(username, email):
    identifiers = [
        value
        for value in {(username or "").strip().lower(), (email or "").strip().lower()}
        if value
    ]
    if not identifiers:
        return []

    return User.query.filter(
        or_(
            func.lower(User.username).in_(identifiers),
            func.lower(User.email).in_(identifiers),
        )
    ).all()


try:
    initialize_database()
except SQLAlchemyError:
    app.logger.exception("Database initialization failed during application startup.")
    raise


def create_user(full_name, username, email, student_class, password):
    role = resolve_account_role(full_name, username)
    user = User(
        full_name=full_name,
        username=username,
        email=email.lower(),
        student_class=student_class,
        role=role,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()
    return user


def update_user_password(user_id, password):
    user = db.session.get(User, user_id)
    if user:
        user.password_hash = generate_password_hash(password)
        db.session.commit()


def validate_new_password(password, confirm_password):
    errors = []
    if not password:
        errors.append("New password is required.")
    elif len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if password != confirm_password:
        errors.append("Passwords do not match.")
    return errors


def current_user():
    if not hasattr(g, "_current_user"):
        g._current_user = get_user_by_id(session.get("user_id"))
    return g._current_user


def start_authenticated_session(account):
    # Authenticated sessions must be permanent so a normal page refresh keeps
    # Flask's signed session cookie valid until explicit logout or expiry.
    session.permanent = True
    session.pop("password_reset_user_id", None)
    session["user_id"] = account["id"]
    session["user_name"] = account["full_name"]
    session["username"] = account["username"]
    session["role"] = normalize_role(account["role"])


@app.context_processor
def inject_current_user():
    account = current_user() if session.get("user_id") else None
    account_role = account["role"] if account else None
    account_role_details = role_details(account_role) if account else None
    return {
        "current_user": account,
        "role_details": role_details,
        "user": {
            "id": account["id"],
            "name": account["full_name"],
            "full_name": account["full_name"],
            "username": account["username"],
            "role": account_role,
            "role_label": account_role_details["label"],
            "role_badge": account_role_details["badge"],
            "role_class": account_role_details["class"],
        } if account else None,
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


def user_can_access_role(account, allowed_roles):
    if not account:
        return False
    user_role = normalize_role(account["role"])
    normalized_allowed_roles = {normalize_role(role) for role in allowed_roles}
    return user_role == "developer" or user_role in normalized_allowed_roles


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not session.get("user_id"):
                flash(
                    "Login required. Create a free account to save your progress and unlock personalized learning.",
                    "error",
                )
                return redirect(url_for("login", next=request.path))

            account = current_user()
            if not user_can_access_role(account, allowed_roles):
                flash("Access Denied. Your account role does not have permission to open this page.", "error")
                return render_template(
                    "access_denied.html",
                    account=account,
                    allowed_roles=[role_details(role)["label"] for role in allowed_roles],
                ), 403

            return view(*args, **kwargs)

        return wrapped_view

    return decorator


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
    learning_session = LearningSession(
        user_id=user_id,
        name=name,
        student_class=student_class,
        subject=subject,
        book_name=book_name,
        topic=topic,
        notes=notes,
    )
    db.session.add(learning_session)
    db.session.commit()
    return learning_session.id


def save_learning_history(user_id, subject, book_name, topic, notes, diagram_data, quiz_questions):
    duplicate_cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    duplicate = LearningHistory.query.filter(
        LearningHistory.user_id == user_id,
        func.lower(LearningHistory.subject) == subject.lower(),
        func.lower(func.coalesce(LearningHistory.book_name, "")) == (book_name or "").lower(),
        func.lower(LearningHistory.topic) == topic.lower(),
        LearningHistory.created_at >= duplicate_cutoff,
    ).first()
    if duplicate:
        return duplicate.id

    lesson = LearningHistory(
        user_id=user_id,
        subject=subject,
        book_name=book_name,
        topic=topic,
        notes=notes,
        diagram_data=json.dumps(diagram_data),
        quiz_questions=json.dumps(quiz_questions),
    )
    db.session.add(lesson)
    db.session.commit()
    return lesson.id


LEARNING_HISTORY_FILTERS = [
    ("all", "All"),
    ("science", "Science"),
    ("mathematics", "Mathematics"),
    ("english", "English"),
    ("social-science", "Social Science"),
    ("computer", "Computer"),
    ("others", "Others"),
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
    query = LearningHistory.query.options(
        load_only(
            LearningHistory.id,
            LearningHistory.subject,
            LearningHistory.book_name,
            LearningHistory.topic,
            LearningHistory.created_at,
        )
    ).filter(LearningHistory.user_id == user_id)
    search_text = search.strip().lower()

    if search_text:
        like_value = f"%{search_text}%"
        query = query.filter(
            or_(
                func.lower(LearningHistory.subject).like(like_value),
                func.lower(func.coalesce(LearningHistory.book_name, "")).like(like_value),
                func.lower(LearningHistory.topic).like(like_value),
            )
        )

    pattern = subject_filter_pattern(subject_filter)
    if pattern:
        query = query.filter(func.lower(LearningHistory.subject).like(pattern))
    elif subject_filter == "others":
        query = query.filter(
            and_(
                ~func.lower(LearningHistory.subject).like("%science%"),
                ~func.lower(LearningHistory.subject).like("%math%"),
                ~func.lower(LearningHistory.subject).like("%english%"),
                ~func.lower(LearningHistory.subject).like("%social%"),
                ~func.lower(LearningHistory.subject).like("%computer%"),
            )
        )

    if sort_order == "oldest":
        query = query.order_by(LearningHistory.created_at.asc(), LearningHistory.id.asc())
    elif sort_order == "alphabetical":
        query = query.order_by(
            func.lower(LearningHistory.topic).asc(),
            func.lower(LearningHistory.subject).asc(),
            LearningHistory.created_at.desc(),
            LearningHistory.id.desc(),
        )
    else:
        query = query.order_by(LearningHistory.created_at.desc(), LearningHistory.id.desc())
    return query.all()


def get_learning_history_entry(entry_id, user_id):
    return LearningHistory.query.filter_by(id=entry_id, user_id=user_id).first()


def delete_learning_history_entry(entry_id, user_id):
    lesson = LearningHistory.query.filter_by(id=entry_id, user_id=user_id).first()
    if lesson:
        db.session.delete(lesson)
        db.session.commit()


def decode_json_list(value):
    try:
        decoded_value = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []

    return decoded_value if isinstance(decoded_value, list) else []


def decode_diagram_payload(value, subject="", topic=""):
    try:
        decoded_value = json.loads(value or "{}")
    except json.JSONDecodeError:
        decoded_value = {}
    return build_diagram_payload(subject, topic, decoded_value)


def save_downloaded_file(user_id, file_type, subject, topic, score="", grade=""):
    downloaded_file = DownloadedFile(
        user_id=user_id,
        file_type=file_type,
        subject=subject,
        topic=topic,
        score=score,
        grade=grade,
    )
    db.session.add(downloaded_file)
    db.session.commit()
    return downloaded_file.id


def save_quiz_history(name, student_class, subject, topic, score, grade, questions, answers, report_text, user_id=None):
    history = QuizHistory(
        user_id=user_id,
        name=name,
        student_class=student_class,
        subject=subject,
        topic=topic,
        score=score,
        grade=grade,
        questions_json=json.dumps(questions),
        answers_json=json.dumps(answers),
        report_text=report_text,
    )
    db.session.add(history)
    db.session.commit()
    return history.id


def get_quiz_history(limit=50, user_id=None):
    query = QuizHistory.query.options(
        load_only(
            QuizHistory.id,
            QuizHistory.created_at,
            QuizHistory.name,
            QuizHistory.student_class,
            QuizHistory.subject,
            QuizHistory.topic,
            QuizHistory.score,
            QuizHistory.grade,
        )
    )
    if user_id:
        query = query.filter(QuizHistory.user_id == user_id)
    return query.order_by(QuizHistory.created_at.desc(), QuizHistory.id.desc()).limit(limit).all()


def score_to_number(score):
    match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*10", score or "")
    return float(match.group(1)) if match else None


def format_mark(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0"
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def grade_from_percentage(percentage):
    if percentage >= 90:
        return "A+"
    if percentage >= 80:
        return "A"
    if percentage >= 70:
        return "B+"
    if percentage >= 60:
        return "B"
    return "C"


def normalize_evaluation_status(status):
    status = (status or "").strip().lower()
    if "correct" in status and "incorrect" not in status:
        return "correct"
    if "partial" in status or "partly" in status or "half" in status:
        return "partial"
    return "incorrect"


def extract_json_payload(text):
    response_text = (text or "").strip()
    if not response_text:
        return None

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        response_text = fence_match.group(1).strip()

    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    start = response_text.find("{")
    end = response_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(response_text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def list_from_value(value, fallback):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        lines = [
            re.sub(r"^[-*]\s*", "", line).strip()
            for line in value.splitlines()
            if line.strip()
        ]
        return lines or fallback
    return fallback


def build_fallback_evaluation(response_text, questions, answers):
    score_match = re.search(r"Score:\s*(\d+(?:\.\d+)?)/10", response_text or "", re.IGNORECASE)
    grade_match = re.search(r"Grade:\s*([A-Z+]+)", response_text or "", re.IGNORECASE)
    total_score = float(score_match.group(1)) if score_match else 0
    per_question_mark = total_score / max(len(questions), 1)
    if per_question_mark >= 1.6:
        fallback_status = "correct"
    elif per_question_mark > 0:
        fallback_status = "partial"
    else:
        fallback_status = "incorrect"

    return {
        "questions": [
            {
                "question": question,
                "student_answer": answer,
                "correct_answer": "Review the lesson notes for the model answer.",
                "status": fallback_status,
                "marks_awarded": round(per_question_mark, 1),
                "marks_label": format_mark(per_question_mark),
                "max_marks": "2",
                "teacher_feedback": "The AI returned a general report for this attempt.",
                "revision_tip": "Revise the topic notes and compare your answer with key terms.",
            }
            for question, answer in zip(questions, answers)
        ],
        "summary": {
            "total_score": round(total_score, 1),
            "total_score_label": format_mark(total_score),
            "max_score": "10",
            "score_label": f"{format_mark(total_score)}/10",
            "percentage": round(total_score * 10, 1),
            "percentage_label": f"{format_mark(total_score * 10)}%",
            "grade": grade_match.group(1) if grade_match else grade_from_percentage(total_score * 10),
            "correct_answers": len(questions) if fallback_status == "correct" else 0,
            "incorrect_answers": len(questions) if fallback_status == "incorrect" else 0,
            "partial_answers": len(questions) if fallback_status == "partial" else 0,
        },
        "teacher_report": {
            "overall_feedback": "Your quiz has been evaluated. Use the details below to revise steadily.",
            "strengths": ["You completed the quiz and attempted the questions."],
            "weak_areas": ["Review any answers where important points were missing."],
            "revision_suggestions": [
                "Read the generated notes again.",
                "Rewrite weak answers in your own words.",
                "Retake the quiz after revision.",
            ],
        },
    }


def normalize_evaluation_payload(payload, response_text, questions, answers):
    if not isinstance(payload, dict):
        return build_fallback_evaluation(response_text, questions, answers)

    raw_questions = payload.get("questions") or payload.get("question_analysis") or []
    normalized_questions = []
    mark_total = 0.0
    for index, question in enumerate(questions):
        raw_item = raw_questions[index] if index < len(raw_questions) and isinstance(raw_questions[index], dict) else {}
        max_marks = raw_item.get("max_marks", 2)
        try:
            max_marks = float(max_marks)
        except (TypeError, ValueError):
            max_marks = 2.0

        marks_awarded = raw_item.get("marks_awarded", raw_item.get("marks", 0))
        try:
            marks_awarded = max(0.0, min(float(marks_awarded), max_marks))
        except (TypeError, ValueError):
            marks_awarded = 0.0

        status = normalize_evaluation_status(raw_item.get("status"))
        if not raw_item.get("status"):
            if marks_awarded >= max_marks:
                status = "correct"
            elif marks_awarded > 0:
                status = "partial"
            else:
                status = "incorrect"

        mark_total += marks_awarded
        normalized_questions.append(
            {
                "question": str(raw_item.get("question") or question).strip(),
                "student_answer": str(raw_item.get("student_answer") or answers[index]).strip(),
                "correct_answer": str(raw_item.get("correct_answer") or "Review the lesson notes for the model answer.").strip(),
                "status": status,
                "marks_awarded": round(marks_awarded, 1),
                "marks_label": format_mark(marks_awarded),
                "max_marks": format_mark(max_marks),
                "teacher_feedback": str(raw_item.get("teacher_feedback") or raw_item.get("feedback") or "Keep revising this concept.").strip(),
                "revision_tip": str(raw_item.get("revision_tip") or "").strip(),
            }
        )

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    max_score = 10.0
    total_score = summary.get("total_score", mark_total)
    try:
        total_score = max(0.0, min(float(total_score), max_score))
    except (TypeError, ValueError):
        total_score = mark_total
    percentage = round((total_score / max_score) * 100, 1)
    correct_count = sum(1 for item in normalized_questions if item["status"] == "correct")
    incorrect_count = sum(1 for item in normalized_questions if item["status"] == "incorrect")
    partial_count = sum(1 for item in normalized_questions if item["status"] == "partial")

    teacher_report = payload.get("teacher_report") if isinstance(payload.get("teacher_report"), dict) else {}
    evaluation = {
        "questions": normalized_questions,
        "summary": {
            "total_score": round(total_score, 1),
            "total_score_label": format_mark(total_score),
            "max_score": "10",
            "score_label": f"{format_mark(total_score)}/10",
            "percentage": percentage,
            "percentage_label": f"{format_mark(percentage)}%",
            "grade": str(summary.get("grade") or grade_from_percentage(percentage)).strip(),
            "correct_answers": correct_count,
            "incorrect_answers": incorrect_count,
            "partial_answers": partial_count,
        },
        "teacher_report": {
            "overall_feedback": str(teacher_report.get("overall_feedback") or "Good effort. Use this report to revise the weak areas and strengthen your next attempt.").strip(),
            "strengths": list_from_value(
                teacher_report.get("strengths"),
                ["You attempted the quiz and engaged with the topic."],
            ),
            "weak_areas": list_from_value(
                teacher_report.get("weak_areas"),
                ["Review any question marked incorrect or partial."],
            ),
            "revision_suggestions": list_from_value(
                teacher_report.get("revision_suggestions") or teacher_report.get("personalized_revision_suggestions"),
                ["Revise the notes, then retry similar questions without looking at the answers."],
            ),
        },
    }
    return evaluation


def build_structured_evaluation(response_text, questions, answers):
    return normalize_evaluation_payload(
        extract_json_payload(response_text),
        response_text,
        questions,
        answers,
    )


def structured_evaluation_to_markdown(evaluation):
    summary = evaluation["summary"]
    report = evaluation["teacher_report"]
    lines = [
        "# Performance Summary",
        f"Score: {summary['score_label']}",
        f"Percentage: {summary['percentage_label']}",
        f"Grade: {summary['grade']}",
        f"Correct Answers: {summary['correct_answers']}",
        f"Incorrect Answers: {summary['incorrect_answers']}",
        f"Partial Marks: {summary['partial_answers']}",
        "",
        "# Question Analysis",
    ]
    for index, item in enumerate(evaluation["questions"], start=1):
        lines.extend(
            [
                f"## Question {index}",
                f"Question: {item['question']}",
                f"Student Answer: {item['student_answer']}",
                f"Correct Answer: {item['correct_answer']}",
                f"Status: {item['status'].title()}",
                f"Marks Awarded: {item['marks_label']}/{item['max_marks']}",
                f"Teacher Feedback: {item['teacher_feedback']}",
            ]
        )
        if item["revision_tip"]:
            lines.append(f"Revision Tip: {item['revision_tip']}")
        lines.append("")

    lines.extend(["# AI Teacher Report", report["overall_feedback"], "", "# Strengths"])
    lines.extend(f"- {item}" for item in report["strengths"])
    lines.append("")
    lines.append("# Weak Areas")
    lines.extend(f"- {item}" for item in report["weak_areas"])
    lines.append("")
    lines.append("# Personalized Revision Suggestions")
    lines.extend(f"- {item}" for item in report["revision_suggestions"])
    return "\n".join(lines)


def format_model_datetime(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def get_recent_learning_activity(user_id, limit=5):
    lessons = (
        LearningHistory.query.with_entities(
            LearningHistory.subject,
            LearningHistory.topic,
            LearningHistory.created_at,
        )
        .filter_by(user_id=user_id)
        .order_by(LearningHistory.created_at.desc(), LearningHistory.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "subject": lesson.subject,
            "topic": lesson.topic,
            "created_at": format_model_datetime(lesson.created_at),
            "score": "Not attempted",
        }
        for lesson in lessons
    ]


def calculate_study_streak(activity_dates):
    normalized_dates = []
    for date_value in activity_dates:
        if not date_value:
            continue
        if isinstance(date_value, datetime):
            normalized_dates.append(date_value.date())
        else:
            normalized_dates.append(datetime.fromisoformat(str(date_value)[:10]).date())
    normalized_dates = sorted(set(normalized_dates), reverse=True)
    if not normalized_dates:
        return 0

    streak = 1
    current_date = normalized_dates[0]
    for next_date in normalized_dates[1:]:
        day_difference = (current_date - next_date).days
        if day_difference == 1:
            streak += 1
            current_date = next_date
        elif day_difference > 1:
            break

    return streak


def get_dashboard_stats(user_id):
    quiz_rows = (
        QuizHistory.query.with_entities(QuizHistory.score, QuizHistory.created_at)
        .filter_by(user_id=user_id)
        .all()
    )
    lesson_dates = [
        row.created_at
        for row in LearningHistory.query.with_entities(LearningHistory.created_at)
        .filter_by(user_id=user_id)
        .all()
    ]
    topics_studied = len(lesson_dates)
    quizzes_attempted = len(quiz_rows)
    downloaded_count = DownloadedFile.query.filter_by(user_id=user_id).count()

    scores = [
        numeric_score
        for numeric_score in (score_to_number(row.score) for row in quiz_rows)
        if numeric_score is not None
    ]
    average_score = f"{sum(scores) / len(scores):.1f}/10" if scores else "0"
    study_streak = calculate_study_streak(
        lesson_dates + [row.created_at for row in quiz_rows]
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


def score_to_percentage(score):
    numeric_score = score_to_number(score)
    if numeric_score is not None:
        return round(numeric_score * 10, 2)

    match = re.search(r"(\d+(?:\.\d+)?)\s*%", score or "")
    if match:
        return round(float(match.group(1)), 2)

    return None


def format_percentage(value):
    if value is None:
        return "Not enough data yet."
    rounded = round(value, 1)
    return f"{int(rounded)}%" if rounded.is_integer() else f"{rounded}%"


def normalize_subject_label(subject):
    normalized = re.sub(r"\s+", " ", (subject or "Unspecified").strip())
    return normalized or "Unspecified"


def format_activity_date(date_value):
    if not date_value:
        return "Not available"
    if isinstance(date_value, datetime):
        activity_date = date_value.date()
        if activity_date == datetime.now(timezone.utc).date():
            return "Today"
        return date_value.strftime("%d %b %Y")
    return str(date_value)


def datetime_sort_value(date_value):
    if not date_value:
        return 0
    if isinstance(date_value, datetime):
        if date_value.tzinfo is None:
            date_value = date_value.replace(tzinfo=timezone.utc)
        return date_value.timestamp()
    return 0


def performance_recent_activity(lesson_rows, quiz_rows, limit=10):
    activities = []
    for lesson in lesson_rows:
        activities.append(
            {
                "type": "Learning",
                "topic": lesson.topic,
                "subject": normalize_subject_label(lesson.subject),
                "score": "Not attempted",
                "date": format_activity_date(lesson.created_at),
                "created_at": lesson.created_at,
            }
        )

    for quiz in quiz_rows:
        activities.append(
            {
                "type": "Quiz",
                "topic": quiz.topic,
                "subject": normalize_subject_label(quiz.subject),
                "score": quiz.score,
                "date": format_activity_date(quiz.created_at),
                "created_at": quiz.created_at,
            }
        )

    activities.sort(key=lambda item: datetime_sort_value(item["created_at"]), reverse=True)
    return activities[:limit]


def build_performance_insights(overview, subject_analysis, quiz_scores, activity_dates):
    insights = []

    strongest = subject_analysis.get("strongest_subject")
    weakest = subject_analysis.get("weakest_subject")
    if strongest and strongest != "Not enough data yet.":
        insights.append(f"{strongest} is currently your strongest subject.")
    if weakest and weakest != "Not enough data yet." and weakest != strongest:
        insights.append(f"{weakest} needs more practice.")

    recent_scores = [item["percentage"] for item in quiz_scores[-3:]]
    previous_scores = [item["percentage"] for item in quiz_scores[-6:-3]]
    if len(recent_scores) >= 2 and previous_scores:
        recent_average = sum(recent_scores) / len(recent_scores)
        previous_average = sum(previous_scores) / len(previous_scores)
        if recent_average > previous_average:
            insights.append("You have improved over your recent quizzes.")
        elif recent_average < previous_average:
            insights.append("Recent quiz scores dipped a little, so a short revision session may help.")

    studied_dates = {
        value.date() if isinstance(value, datetime) else value
        for value in activity_dates
        if value
    }
    if len(studied_dates) >= 3:
        insights.append("You are studying consistently.")

    if overview["total_quizzes_attempted"] == 0 and overview["total_topics_studied"] == 0:
        return ["Not enough data yet."]

    return insights or ["Not enough data yet."]


def get_performance_analytics(user_id):
    quiz_rows = (
        QuizHistory.query.options(
            load_only(
                QuizHistory.id,
                QuizHistory.subject,
                QuizHistory.topic,
                QuizHistory.score,
                QuizHistory.created_at,
            )
        )
        .filter_by(user_id=user_id)
        .order_by(QuizHistory.created_at.asc(), QuizHistory.id.asc())
        .all()
    )
    lesson_rows = (
        LearningHistory.query.options(
            load_only(
                LearningHistory.id,
                LearningHistory.subject,
                LearningHistory.topic,
                LearningHistory.created_at,
            )
        )
        .filter_by(user_id=user_id)
        .order_by(LearningHistory.created_at.asc(), LearningHistory.id.asc())
        .all()
    )
    learning_session_count = LearningSession.query.filter_by(user_id=user_id).count()

    topic_keys = {
        (normalize_subject_label(row.subject).lower(), (row.topic or "").strip().lower())
        for row in lesson_rows
        if (row.topic or "").strip()
    }
    subject_counts = Counter(normalize_subject_label(row.subject) for row in lesson_rows)
    quiz_subject_scores = defaultdict(list)
    quiz_scores = []

    for quiz in quiz_rows:
        percentage = score_to_percentage(quiz.score)
        if percentage is None:
            continue
        subject = normalize_subject_label(quiz.subject)
        quiz_subject_scores[subject].append(percentage)
        quiz_scores.append(
            {
                "subject": subject,
                "topic": quiz.topic,
                "score": quiz.score,
                "percentage": percentage,
                "date": format_activity_date(quiz.created_at),
                "created_at": quiz.created_at,
            }
        )

    score_values = [item["percentage"] for item in quiz_scores]
    all_subjects = {
        normalize_subject_label(row.subject)
        for row in [*lesson_rows, *quiz_rows]
        if normalize_subject_label(row.subject)
    }
    activity_dates = [row.created_at for row in lesson_rows] + [row.created_at for row in quiz_rows]
    last_activity_date = max(activity_dates, key=datetime_sort_value) if activity_dates else None

    overview = {
        "total_topics_studied": len(topic_keys),
        "total_quizzes_attempted": len(quiz_rows),
        "average_quiz_score": format_percentage(sum(score_values) / len(score_values)) if score_values else "Not enough data yet.",
        "highest_score": format_percentage(max(score_values)) if score_values else "Not enough data yet.",
        "lowest_score": format_percentage(min(score_values)) if score_values else "Not enough data yet.",
        "subjects_studied": len(all_subjects),
        "total_learning_sessions": learning_session_count,
        "last_study_date": format_activity_date(last_activity_date),
    }

    average_score_by_subject = {
        subject: round(sum(scores) / len(scores), 1)
        for subject, scores in sorted(quiz_subject_scores.items())
        if scores
    }
    quizzes_per_subject = {
        subject: len(scores)
        for subject, scores in sorted(quiz_subject_scores.items())
    }

    strongest_subject = "Not enough data yet."
    weakest_subject = "Not enough data yet."
    if len(average_score_by_subject) >= 2:
        strongest_subject = max(average_score_by_subject, key=average_score_by_subject.get)
        weakest_subject = min(average_score_by_subject, key=average_score_by_subject.get)
    elif len(average_score_by_subject) == 1:
        strongest_subject = next(iter(average_score_by_subject))

    most_studied_subject = "Not enough data yet."
    if subject_counts:
        most_studied_subject = subject_counts.most_common(1)[0][0]

    subject_analysis = {
        "average_score_by_subject": average_score_by_subject,
        "quizzes_per_subject": quizzes_per_subject,
        "most_studied_subject": most_studied_subject,
        "weakest_subject": weakest_subject,
        "strongest_subject": strongest_subject,
    }

    chart_data = {
        "average_score_by_subject": {
            "labels": list(average_score_by_subject.keys()),
            "values": list(average_score_by_subject.values()),
        },
        "topics_by_subject": {
            "labels": list(subject_counts.keys()),
            "values": list(subject_counts.values()),
        },
        "quiz_scores_over_time": {
            "labels": [item["date"] for item in quiz_scores],
            "values": [item["percentage"] for item in quiz_scores],
        },
    }

    summary = {
        "average_score": overview["average_quiz_score"],
        "best_subject": strongest_subject,
        "needs_improvement": weakest_subject,
        "topics_studied": overview["total_topics_studied"],
        "last_active": overview["last_study_date"],
    }

    return {
        "overview": overview,
        "summary": summary,
        "subject_analysis": subject_analysis,
        "insights": build_performance_insights(overview, subject_analysis, quiz_scores, activity_dates),
        "recent_activity": performance_recent_activity(lesson_rows, quiz_rows),
        "chart_data": chart_data,
        "has_quiz_data": bool(score_values),
        "has_topic_data": bool(subject_counts),
        "has_any_activity": bool(activity_dates),
    }


def get_developer_panel_stats():
    today_start, tomorrow_start = utc_day_range()
    table_counts = {
        "users": User.query.count(),
        "learning_history": LearningHistory.query.count(),
        "learning_sessions": LearningSession.query.count(),
        "quiz_history": QuizHistory.query.count(),
        "downloaded_files": DownloadedFile.query.count(),
    }
    active_user_ids = set()
    for model in (LearningHistory, LearningSession, QuizHistory, DownloadedFile):
        active_user_ids.update(
            user_id
            for (user_id,) in model.query.with_entities(model.user_id)
            .filter(model.created_at >= today_start, model.created_at < tomorrow_start)
            .distinct()
            .all()
            if user_id
        )

    recent_registrations = (
        User.query.options(
            load_only(User.id, User.full_name, User.student_class, User.role, User.created_at)
        )
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(10)
        .all()
    )

    return {
        "total_users": table_counts["users"],
        "users_registered_today": User.query.filter(
            User.created_at >= today_start,
            User.created_at < tomorrow_start,
        ).count(),
        "total_topics_generated": table_counts["learning_sessions"],
        "total_lessons": table_counts["learning_history"],
        "total_quizzes": table_counts["quiz_history"],
        "total_notes_saved": table_counts["learning_history"],
        "total_downloads": table_counts["downloaded_files"],
        "active_users_today": len(active_user_ids),
        "recent_registrations": recent_registrations,
        "ai_provider_status": {
            "gemini": "Configured" if GEMINI_API_KEY else "Missing API key",
            "ollama": "Placeholder",
        },
        "website_version": WEBSITE_VERSION,
        "database_statistics": table_counts,
        "server_status": "Online placeholder",
    }


def utc_day_range(date_value=None):
    if date_value is None:
        date_value = datetime.now(timezone.utc).date()
    start = datetime(date_value.year, date_value.month, date_value.day)
    return start, start + timedelta(days=1)


def parse_filter_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_admin_datetime(value):
    if not value:
        return "Not available"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")
    return str(value)


def apply_developer_user_filters(query, search="", student_class="", role="", registration_date=""):
    search_text = (search or "").strip().lower()
    if search_text:
        like_value = f"%{search_text}%"
        query = query.filter(
            or_(
                func.lower(User.full_name).like(like_value),
                func.lower(User.username).like(like_value),
                func.lower(User.email).like(like_value),
            )
        )

    if student_class:
        query = query.filter(User.student_class == student_class)

    if role in ROLE_DEFINITIONS:
        query = query.filter(User.role == role)

    parsed_date = parse_filter_date(registration_date)
    if parsed_date:
        start, end = utc_day_range(parsed_date)
        query = query.filter(User.created_at >= start, User.created_at < end)

    return query


def developer_user_filter_options():
    class_rows = (
        User.query.with_entities(User.student_class)
        .filter(User.student_class.isnot(None), User.student_class != "")
        .distinct()
        .order_by(User.student_class.asc())
        .all()
    )
    return {
        "classes": [row.student_class for row in class_rows],
        "roles": [
            {"value": role, "label": details["label"]}
            for role, details in ROLE_DEFINITIONS.items()
        ],
    }


def empty_developer_rollup():
    return {
        "topics_studied": 0,
        "quizzes_attempted": 0,
        "average_quiz_score": "No quizzes",
        "highest_score": "No quizzes",
        "lowest_score": "No quizzes",
        "downloads": 0,
        "saved_notes": 0,
    }


def developer_user_rollups(user_ids):
    rollups = {user_id: empty_developer_rollup() for user_id in user_ids}
    if not user_ids:
        return rollups

    for user_id, total in (
        LearningHistory.query.with_entities(
            LearningHistory.user_id,
            func.count(LearningHistory.id),
        )
        .filter(LearningHistory.user_id.in_(user_ids))
        .group_by(LearningHistory.user_id)
        .all()
    ):
        rollups[user_id]["topics_studied"] = total
        rollups[user_id]["saved_notes"] = total

    for user_id, total in (
        QuizHistory.query.with_entities(
            QuizHistory.user_id,
            func.count(QuizHistory.id),
        )
        .filter(QuizHistory.user_id.in_(user_ids))
        .group_by(QuizHistory.user_id)
        .all()
    ):
        rollups[user_id]["quizzes_attempted"] = total

    quiz_scores_by_user = defaultdict(list)
    for user_id, score in (
        QuizHistory.query.with_entities(QuizHistory.user_id, QuizHistory.score)
        .filter(QuizHistory.user_id.in_(user_ids))
        .all()
    ):
        percentage = score_to_percentage(score)
        if percentage is not None:
            quiz_scores_by_user[user_id].append(percentage)

    for user_id, scores in quiz_scores_by_user.items():
        rollups[user_id]["average_quiz_score"] = format_percentage(sum(scores) / len(scores))
        rollups[user_id]["highest_score"] = format_percentage(max(scores))
        rollups[user_id]["lowest_score"] = format_percentage(min(scores))

    for user_id, total in (
        DownloadedFile.query.with_entities(
            DownloadedFile.user_id,
            func.count(DownloadedFile.id),
        )
        .filter(DownloadedFile.user_id.in_(user_ids))
        .group_by(DownloadedFile.user_id)
        .all()
    ):
        rollups[user_id]["downloads"] = total

    return rollups


def get_developer_users_page(filters, page=1, per_page=DEVELOPER_USERS_PER_PAGE):
    page = max(page, 1)
    base_query = apply_developer_user_filters(
        User.query,
        search=filters.get("search", ""),
        student_class=filters.get("student_class", ""),
        role=filters.get("role", ""),
        registration_date=filters.get("registration_date", ""),
    )
    total = base_query.order_by(None).count()
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)

    users = (
        base_query.options(
            load_only(
                User.id,
                User.full_name,
                User.username,
                User.email,
                User.student_class,
                User.role,
                User.created_at,
            )
        )
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
        .all()
    )
    rollups = developer_user_rollups([user.id for user in users])

    return {
        "users": users,
        "rollups": rollups,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def get_developer_user_detail(user_id):
    user = User.query.options(
        load_only(
            User.id,
            User.full_name,
            User.username,
            User.email,
            User.student_class,
            User.role,
            User.created_at,
        )
    ).filter_by(id=user_id).first()
    if not user:
        return None

    rollup = developer_user_rollups([user.id])[user.id]
    learning_dates = [
        row.created_at
        for row in LearningHistory.query.with_entities(LearningHistory.created_at)
        .filter_by(user_id=user.id)
        .all()
    ]
    quiz_dates = [
        row.created_at
        for row in QuizHistory.query.with_entities(QuizHistory.created_at)
        .filter_by(user_id=user.id)
        .all()
    ]
    rollup["study_streak"] = calculate_study_streak(learning_dates + quiz_dates)

    return {
        "user": user,
        "stats": rollup,
        "recent_activity": get_developer_user_recent_activity(user.id),
    }


def get_developer_user_recent_activity(user_id, limit=10):
    activities = []

    lessons = (
        LearningHistory.query.with_entities(
            LearningHistory.subject,
            LearningHistory.topic,
            LearningHistory.created_at,
        )
        .filter_by(user_id=user_id)
        .order_by(LearningHistory.created_at.desc(), LearningHistory.id.desc())
        .limit(limit)
        .all()
    )
    for lesson in lessons:
        activities.append(
            {
                "type": "Saved Note",
                "subject": lesson.subject,
                "topic": lesson.topic,
                "score": "N/A",
                "created_at": lesson.created_at,
                "date": format_admin_datetime(lesson.created_at),
            }
        )

    quizzes = (
        QuizHistory.query.with_entities(
            QuizHistory.subject,
            QuizHistory.topic,
            QuizHistory.score,
            QuizHistory.created_at,
        )
        .filter_by(user_id=user_id)
        .order_by(QuizHistory.created_at.desc(), QuizHistory.id.desc())
        .limit(limit)
        .all()
    )
    for quiz in quizzes:
        activities.append(
            {
                "type": "Quiz",
                "subject": quiz.subject,
                "topic": quiz.topic,
                "score": quiz.score,
                "created_at": quiz.created_at,
                "date": format_admin_datetime(quiz.created_at),
            }
        )

    downloads = (
        DownloadedFile.query.with_entities(
            DownloadedFile.file_type,
            DownloadedFile.subject,
            DownloadedFile.topic,
            DownloadedFile.score,
            DownloadedFile.created_at,
        )
        .filter_by(user_id=user_id)
        .order_by(DownloadedFile.created_at.desc(), DownloadedFile.id.desc())
        .limit(limit)
        .all()
    )
    for download in downloads:
        activities.append(
            {
                "type": f"Download: {download.file_type.replace('_', ' ').title()}",
                "subject": download.subject or "N/A",
                "topic": download.topic,
                "score": download.score or "N/A",
                "created_at": download.created_at,
                "date": format_admin_datetime(download.created_at),
            }
        )

    activities.sort(key=lambda item: datetime_sort_value(item["created_at"]), reverse=True)
    return activities[:limit]


def developer_user_filters_from_request():
    return {
        "search": request.args.get("search", "").strip(),
        "student_class": request.args.get("student_class", "").strip(),
        "role": request.args.get("role", "").strip(),
        "registration_date": request.args.get("registration_date", "").strip(),
    }


def support_tools():
    return [
        {
            "title": "Student Account Lookup",
            "description": "Placeholder for future support-assisted account checks.",
        },
        {
            "title": "Learning Issue Notes",
            "description": "Placeholder for tracking student-reported study or download issues.",
        },
        {
            "title": "System Health Checklist",
            "description": "Placeholder for quick support diagnostics.",
        },
    ]


def qa_panel_items():
    return {
        "checklist": [
            "Login and logout flow",
            "Guest mode locked features",
            "AI notes generation",
            "Quiz evaluation and PDF download",
            "Learning history save and delete",
            "Responsive dashboard and profile views",
        ],
        "bug_reports": [
            "No open bug reports yet.",
            "Use this space for exhibition testing notes later.",
        ],
        "feature_status": [
            {"name": "Authentication", "status": "Ready"},
            {"name": "Guest Mode", "status": "Ready"},
            {"name": "Learning History", "status": "Ready"},
            {"name": "Performance Analytics", "status": "Coming Soon"},
            {"name": "AI Recommendations", "status": "Coming Soon"},
        ],
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


DIAGRAM_TEMPLATE_DEFINITIONS = [
    {
        "key": "plant_cell",
        "category": "science",
        "diagram_type": "cell",
        "title": "Plant Cell",
        "terms": ["plant cell"],
        "labels": ["Cell wall", "Cell membrane", "Nucleus", "Chloroplast", "Vacuole"],
    },
    {
        "key": "animal_cell",
        "category": "science",
        "diagram_type": "cell",
        "title": "Animal Cell",
        "terms": ["animal cell"],
        "labels": ["Cell membrane", "Nucleus", "Cytoplasm", "Mitochondria", "Vacuole"],
    },
    {
        "key": "human_heart",
        "category": "science",
        "diagram_type": "organ",
        "title": "Human Heart",
        "terms": ["human heart", "heart"],
        "labels": ["Aorta", "Right atrium", "Left atrium", "Right ventricle", "Left ventricle"],
    },
    {
        "key": "digestive_system",
        "category": "science",
        "diagram_type": "organ",
        "title": "Digestive System",
        "terms": ["digestive system", "digestion"],
        "labels": ["Mouth", "Oesophagus", "Stomach", "Small intestine", "Large intestine"],
    },
    {
        "key": "photosynthesis",
        "category": "science",
        "diagram_type": "process",
        "title": "Photosynthesis",
        "terms": ["photosynthesis"],
        "labels": ["Sunlight", "Carbon dioxide", "Water", "Chlorophyll", "Glucose and oxygen"],
    },
    {
        "key": "water_cycle",
        "category": "science",
        "diagram_type": "cycle",
        "title": "Water Cycle",
        "terms": ["water cycle", "rain cycle"],
        "labels": ["Evaporation", "Condensation", "Clouds", "Precipitation", "Collection"],
    },
    {
        "key": "food_chain",
        "category": "science",
        "diagram_type": "chain",
        "title": "Food Chain",
        "terms": ["food chain"],
        "labels": ["Sun", "Producer", "Primary consumer", "Secondary consumer", "Decomposer"],
    },
    {
        "key": "solar_system",
        "category": "science",
        "diagram_type": "orbit",
        "title": "Solar System",
        "terms": ["solar system", "planets"],
        "labels": ["Sun", "Mercury", "Venus", "Earth", "Mars"],
    },
    {
        "key": "electric_circuit",
        "category": "science",
        "diagram_type": "circuit",
        "title": "Electric Circuit",
        "terms": ["electric circuit", "circuit"],
        "labels": ["Cell", "Switch", "Bulb", "Wire", "Current path"],
    },
    {
        "key": "flower",
        "category": "science",
        "diagram_type": "flower",
        "title": "Flower",
        "terms": ["flower", "parts of flower", "plant", "plants"],
        "labels": ["Petal", "Sepal", "Stamen", "Pistil", "Ovary"],
    },
    {
        "key": "eye",
        "category": "science",
        "diagram_type": "organ",
        "title": "Eye",
        "terms": ["eye", "human eye"],
        "labels": ["Cornea", "Lens", "Iris", "Retina", "Optic nerve"],
    },
    {
        "key": "ear",
        "category": "science",
        "diagram_type": "organ",
        "title": "Ear",
        "terms": ["ear", "human ear"],
        "labels": ["Outer ear", "Ear canal", "Eardrum", "Cochlea", "Auditory nerve"],
    },
    {
        "key": "india_map",
        "category": "geography",
        "diagram_type": "map",
        "title": "India Map",
        "terms": ["india map", "map of india", "india"],
        "labels": ["North India", "West India", "East India", "South India", "Indian Ocean"],
    },
    {
        "key": "world_map",
        "category": "geography",
        "diagram_type": "map",
        "title": "World Map",
        "terms": ["world map", "continents", "map of world"],
        "labels": ["North America", "South America", "Europe", "Africa", "Asia"],
    },
    {
        "key": "layers_of_earth",
        "category": "geography",
        "diagram_type": "layers",
        "title": "Layers of Earth",
        "terms": ["layers of earth", "earth layers", "interior of earth"],
        "labels": ["Crust", "Mantle", "Outer core", "Inner core"],
    },
    {
        "key": "timeline",
        "category": "history",
        "diagram_type": "timeline",
        "title": "Historical Timeline",
        "terms": ["timeline", "chronology", "history timeline"],
        "labels": ["Event 1", "Event 2", "Event 3", "Event 4", "Event 5"],
    },
    {
        "key": "kingdom_chart",
        "category": "history",
        "diagram_type": "chart",
        "title": "Kingdom Chart",
        "terms": ["kingdom", "empire", "dynasty", "kingdom chart"],
        "labels": ["Ruler", "Capital", "Administration", "Society", "Legacy"],
    },
    {
        "key": "story_flowchart",
        "category": "english",
        "diagram_type": "flowchart",
        "title": "Story Flowchart",
        "terms": ["story", "plot", "story flowchart"],
        "labels": ["Beginning", "Problem", "Events", "Climax", "Ending"],
    },
    {
        "key": "character_map",
        "category": "english",
        "diagram_type": "relationship",
        "title": "Character Relationship Map",
        "terms": ["character", "characters", "relationship map"],
        "labels": ["Main character", "Friend", "Family", "Conflict", "Resolution"],
    },
    {
        "key": "geometry",
        "category": "mathematics",
        "diagram_type": "geometry",
        "title": "Geometry",
        "terms": ["geometry", "triangle", "circle", "angle", "polygon"],
        "labels": ["Point", "Line", "Angle", "Side", "Shape"],
    },
    {
        "key": "coordinate_plane",
        "category": "mathematics",
        "diagram_type": "coordinate",
        "title": "Coordinate Plane",
        "terms": ["coordinate plane", "coordinates", "cartesian"],
        "labels": ["X-axis", "Y-axis", "Origin", "Quadrant I", "Point"],
    },
    {
        "key": "number_line",
        "category": "mathematics",
        "diagram_type": "number_line",
        "title": "Number Line",
        "terms": ["number line", "integers"],
        "labels": ["Negative numbers", "Zero", "Positive numbers", "Equal spacing"],
    },
    {
        "key": "fractions",
        "category": "mathematics",
        "diagram_type": "fraction",
        "title": "Fractions",
        "terms": ["fraction", "fractions"],
        "labels": ["Whole", "Equal parts", "Numerator", "Denominator"],
    },
]


def normalize_diagram_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def find_diagram_template(subject, topic):
    haystack = normalize_diagram_text(f"{subject} {topic}")
    subject_text = normalize_diagram_text(subject)

    for template in DIAGRAM_TEMPLATE_DEFINITIONS:
        if any(term in haystack for term in template["terms"]):
            return template

    category_defaults = {
        "geography": "world_map",
        "history": "timeline",
        "english": "story_flowchart",
        "mathematics": "geometry",
        "math": "geometry",
    }
    for subject_term, template_key in category_defaults.items():
        if subject_term in subject_text:
            return next(item for item in DIAGRAM_TEMPLATE_DEFINITIONS if item["key"] == template_key)

    return None


def normalize_diagram_labels(labels):
    if not isinstance(labels, list):
        return []

    normalized_labels = []
    for label in labels:
        if isinstance(label, dict):
            text = label.get("text") or label.get("label") or label.get("name") or ""
        else:
            text = label
        text = re.sub(r"\s+", " ", str(text).strip())
        if text:
            normalized_labels.append(text[:80])
    return normalized_labels[:8]


def normalize_diagram_payload(raw_diagram):
    if isinstance(raw_diagram, dict):
        return {
            "diagram_type": str(raw_diagram.get("diagram_type", "")).strip(),
            "title": str(raw_diagram.get("title", "")).strip(),
            "labels": normalize_diagram_labels(raw_diagram.get("labels", [])),
            "arrows": normalize_diagram_labels(raw_diagram.get("arrows", [])),
            "notes": normalize_diagram_labels(raw_diagram.get("notes", [])),
        }
    if isinstance(raw_diagram, list):
        return {
            "diagram_type": "",
            "title": "",
            "labels": normalize_diagram_labels(raw_diagram),
            "arrows": [],
            "notes": [],
        }
    return {
        "diagram_type": "",
        "title": "",
        "labels": [],
        "arrows": [],
        "notes": [],
    }


def build_diagram_payload(subject, topic, raw_diagram=None):
    template = find_diagram_template(subject, topic)
    if not template:
        return {
            "available": False,
            "template_key": "none",
            "diagram_type": "none",
            "title": f"{topic} Diagram" if topic else "Diagram",
            "labels": [],
            "arrows": [],
            "notes": ["No diagram available for this topic."],
        }

    normalized = normalize_diagram_payload(raw_diagram)
    return {
        "available": True,
        "template_key": template["key"],
        "diagram_type": normalized["diagram_type"] or template["diagram_type"],
        "title": normalized["title"] or template["title"],
        "labels": normalized["labels"] or template["labels"],
        "arrows": normalized["arrows"],
        "notes": normalized["notes"],
    }


def extract_json_object(text):
    cleaned_text = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "")
    start = cleaned_text.find("{")
    end = cleaned_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        decoded = json.loads(cleaned_text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


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
        r"(?im)^\s*#{1,6}\s+Diagram(?:\s+(?:JSON|Data|Plan))?\s*$",
        notes_text,
    )
    if not diagram_marker:
        return notes_text.strip(), {}

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

    diagram_json = extract_json_object(diagram_text)
    if diagram_json:
        return notes_without_diagram, diagram_json

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


def svg_text(x, y, text, css_class="label", anchor="middle"):
    return f'<text x="{x}" y="{y}" class="{css_class}" text-anchor="{anchor}">{escape(str(text))}</text>'


def svg_label_box(x, y, label, color="#3157d5"):
    return f"""
    <g>
        <rect x="{x}" y="{y}" width="180" height="40" rx="12" fill="#ffffff" stroke="{color}" stroke-width="2"/>
        {svg_text(x + 90, y + 26, label, "small")}
    </g>
    """


def diagram_labels(payload, minimum=4):
    labels = normalize_diagram_labels(payload.get("labels", []))
    if len(labels) >= minimum:
        return labels
    template = next(
        (item for item in DIAGRAM_TEMPLATE_DEFINITIONS if item["key"] == payload.get("template_key")),
        None,
    )
    return (labels + (template["labels"] if template else []))[:max(minimum, len(labels))]


def wrap_svg_diagram(title, body, width=900, height=560):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">
    <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#3157d5"/>
        </marker>
        <style>
            .title {{ font: 800 30px Arial, sans-serif; fill: #172033; }}
            .label {{ font: 800 18px Arial, sans-serif; fill: #172033; }}
            .small {{ font: 700 14px Arial, sans-serif; fill: #172033; }}
            .muted {{ font: 700 13px Arial, sans-serif; fill: #667085; }}
            .line {{ stroke: #3157d5; stroke-width: 3; fill: none; marker-end: url(#arrow); }}
        </style>
    </defs>
    <rect width="{width}" height="{height}" rx="26" fill="#f8fbff"/>
    <rect x="24" y="24" width="{width - 48}" height="{height - 48}" rx="22" fill="#ffffff" stroke="#d8e2ff"/>
    {svg_text(width / 2, 64, title, "title")}
    {body}
</svg>"""


def render_unavailable_diagram(payload):
    body = f"""
    <g>
        <rect x="210" y="190" width="480" height="150" rx="24" fill="#fff7ed" stroke="#f0b35f" stroke-width="3"/>
        {svg_text(450, 250, "No diagram available", "title")}
        {svg_text(450, 292, "No diagram available for this topic.", "label")}
    </g>
    """
    return wrap_svg_diagram(payload.get("title", "Diagram"), body)


def render_cell_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    plant = payload.get("template_key") == "plant_cell"
    shape = (
        '<rect x="250" y="145" width="400" height="275" rx="42" fill="#e8f7df" stroke="#2f9f67" stroke-width="8"/>'
        if plant
        else '<ellipse cx="450" cy="285" rx="220" ry="145" fill="#eef6ff" stroke="#3157d5" stroke-width="7"/>'
    )
    body = f"""
    {shape}
    <ellipse cx="450" cy="285" rx="58" ry="46" fill="#c7d2fe" stroke="#3157d5" stroke-width="4"/>
    <ellipse cx="350" cy="235" rx="38" ry="22" fill="#bbf7d0" stroke="#2f9f67" stroke-width="3"/>
    <ellipse cx="545" cy="330" rx="42" ry="24" fill="#fed7aa" stroke="#f97316" stroke-width="3"/>
    <ellipse cx="450" cy="285" rx="16" ry="12" fill="#3157d5"/>
    {svg_label_box(75, 140, labels[0], "#2f9f67")}
    {svg_label_box(645, 140, labels[1], "#3157d5")}
    {svg_label_box(360, 440, labels[2], "#3157d5")}
    {svg_label_box(75, 345, labels[3], "#2f9f67")}
    {svg_label_box(645, 345, labels[4], "#f97316")}
    <path class="line" d="M255 175 L205 160"/>
    <path class="line" d="M610 170 L645 160"/>
    <path class="line" d="M450 332 L450 440"/>
    <path class="line" d="M350 255 L205 365"/>
    <path class="line" d="M545 350 L645 365"/>
    """
    return wrap_svg_diagram(payload.get("title", "Cell"), body)


def render_cycle_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    positions = [(450, 130), (650, 245), (575, 425), (325, 425), (250, 245)]
    colors = ["#fde68a", "#bfdbfe", "#bbf7d0", "#fecaca", "#ddd6fe"]
    body = ""
    for index, (x, y) in enumerate(positions):
        body += f'<circle cx="{x}" cy="{y}" r="58" fill="{colors[index]}" stroke="#3157d5" stroke-width="3"/>'
        body += svg_text(x, y + 6, labels[index], "small")
    for start, end in zip(positions, positions[1:] + positions[:1]):
        body += f'<path class="line" d="M{start[0] + 42},{start[1] + 18} C{(start[0] + end[0]) / 2},{(start[1] + end[1]) / 2} {end[0] - 42},{end[1] - 18} {end[0] - 48},{end[1] - 10}"/>'
    body += svg_text(450, 285, payload.get("diagram_type", "cycle").title(), "label")
    return wrap_svg_diagram(payload.get("title", "Cycle"), body)


def render_chain_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = ""
    x_values = [70, 235, 400, 565, 730]
    for index, label in enumerate(labels[:5]):
        body += f'<rect x="{x_values[index]}" y="230" width="120" height="92" rx="18" fill="#f0fdf4" stroke="#2f9f67" stroke-width="3"/>'
        body += svg_text(x_values[index] + 60, 282, label, "small")
        if index < 4:
            body += f'<path class="line" d="M{x_values[index] + 128},276 L{x_values[index + 1] - 12},276"/>'
    return wrap_svg_diagram(payload.get("title", "Chain"), body)


def render_solar_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = '<circle cx="170" cy="285" r="58" fill="#fbbf24" stroke="#f59e0b" stroke-width="4"/>'
    body += svg_text(170, 292, labels[0], "small")
    orbit_radii = [110, 175, 240, 305]
    colors = ["#94a3b8", "#fca5a5", "#60a5fa", "#fb7185"]
    for index, radius in enumerate(orbit_radii):
        body += f'<ellipse cx="170" cy="285" rx="{radius + 115}" ry="{radius * 0.48}" fill="none" stroke="#cbd5e1" stroke-width="2"/>'
        x = 170 + radius + 115
        y = 285
        body += f'<circle cx="{x}" cy="{y}" r="{18 + index * 2}" fill="{colors[index]}" stroke="#334155" stroke-width="2"/>'
        body += svg_text(x, y + 45, labels[index + 1], "small")
    return wrap_svg_diagram(payload.get("title", "Solar System"), body)


def render_circuit_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = """
    <rect x="210" y="170" width="480" height="260" rx="22" fill="none" stroke="#172033" stroke-width="8"/>
    <line x1="285" y1="170" x2="285" y2="110" stroke="#172033" stroke-width="6"/>
    <line x1="325" y1="170" x2="325" y2="125" stroke="#172033" stroke-width="3"/>
    <circle cx="585" cy="300" r="48" fill="#fde68a" stroke="#f59e0b" stroke-width="5"/>
    <line x1="535" y1="210" x2="610" y2="170" stroke="#172033" stroke-width="6"/>
    """
    body += svg_label_box(95, 95, labels[0], "#172033")
    body += svg_label_box(610, 105, labels[1], "#172033")
    body += svg_label_box(610, 355, labels[2], "#f59e0b")
    body += svg_label_box(95, 355, labels[3], "#172033")
    body += svg_text(450, 490, labels[4], "label")
    return wrap_svg_diagram(payload.get("title", "Electric Circuit"), body)


def render_layers_diagram(payload):
    labels = diagram_labels(payload, minimum=4)
    colors = ["#92400e", "#f97316", "#facc15", "#fde68a"]
    radii = [155, 115, 75, 38]
    body = ""
    for radius, color in zip(radii, colors):
        body += f'<circle cx="450" cy="290" r="{radius}" fill="{color}" opacity="0.88" stroke="#ffffff" stroke-width="3"/>'
    for index, label in enumerate(labels[:4]):
        body += svg_label_box(80 if index % 2 == 0 else 640, 155 + index * 75, label, colors[index])
    return wrap_svg_diagram(payload.get("title", "Layers"), body)


def render_map_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    is_india = payload.get("template_key") == "india_map"
    map_shape = (
        '<path d="M430 120 C500 145 560 225 535 310 C515 380 465 410 450 470 C420 415 345 400 350 320 C355 240 390 190 430 120 Z" fill="#dbeafe" stroke="#3157d5" stroke-width="5"/>'
        if is_india
        else '<path d="M120 250 C180 160 290 200 340 245 C425 155 565 180 625 250 C700 230 775 275 790 345 C700 390 560 350 500 400 C400 345 260 390 170 345 C110 330 90 285 120 250 Z" fill="#dbeafe" stroke="#3157d5" stroke-width="5"/>'
    )
    body = f"{map_shape}{svg_text(450, 505, 'Reference map for study use', 'muted')}"
    for index, label in enumerate(labels[:5]):
        body += svg_label_box(55 + (index % 3) * 275, 110 + (index // 3) * 330, label, "#3157d5")
    return wrap_svg_diagram(payload.get("title", "Map"), body)


def render_timeline_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = '<line x1="110" y1="300" x2="790" y2="300" stroke="#3157d5" stroke-width="6"/>'
    for index, label in enumerate(labels[:5]):
        x = 130 + index * 160
        body += f'<circle cx="{x}" cy="300" r="18" fill="#3157d5"/>'
        body += svg_label_box(x - 80, 190 if index % 2 == 0 else 345, label, "#3157d5")
    return wrap_svg_diagram(payload.get("title", "Timeline"), body)


def render_chart_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = f'<rect x="360" y="110" width="180" height="58" rx="14" fill="#eef2ff" stroke="#3157d5" stroke-width="3"/>{svg_text(450, 146, labels[0], "small")}'
    for index, label in enumerate(labels[1:5]):
        x = 105 + index * 175
        body += f'<path class="line" d="M450,168 L{x + 75},250"/>'
        body += f'<rect x="{x}" y="250" width="150" height="80" rx="14" fill="#f8fafc" stroke="#64748b" stroke-width="3"/>'
        body += svg_text(x + 75, 296, label, "small")
    return wrap_svg_diagram(payload.get("title", "Chart"), body)


def render_geometry_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = """
    <polygon points="275,405 450,150 625,405" fill="#ecfeff" stroke="#0891b2" stroke-width="5"/>
    <circle cx="450" cy="150" r="7" fill="#3157d5"/>
    <line x1="275" y1="405" x2="625" y2="405" stroke="#f97316" stroke-width="5"/>
    <path d="M330 405 A55 55 0 0 1 360 355" fill="none" stroke="#22c55e" stroke-width="5"/>
    """
    body += svg_label_box(75, 130, labels[0], "#3157d5")
    body += svg_label_box(640, 130, labels[1], "#0891b2")
    body += svg_label_box(75, 390, labels[2], "#22c55e")
    body += svg_label_box(640, 390, labels[3], "#f97316")
    body += svg_text(450, 470, labels[4], "label")
    return wrap_svg_diagram(payload.get("title", "Geometry"), body)


def render_coordinate_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = """
    <line x1="130" y1="300" x2="770" y2="300" stroke="#172033" stroke-width="4" marker-end="url(#arrow)"/>
    <line x1="450" y1="480" x2="450" y2="120" stroke="#172033" stroke-width="4" marker-end="url(#arrow)"/>
    <g stroke="#d8e2ff" stroke-width="1">
    """
    for x in range(170, 750, 40):
        body += f'<line x1="{x}" y1="140" x2="{x}" y2="460"/>'
    for y in range(140, 470, 40):
        body += f'<line x1="150" y1="{y}" x2="750" y2="{y}"/>'
    body += '</g><circle cx="570" cy="220" r="10" fill="#ef4444"/>'
    body += svg_label_box(100, 95, labels[0], "#172033")
    body += svg_label_box(620, 95, labels[1], "#172033")
    body += svg_label_box(360, 310, labels[2], "#3157d5")
    body += svg_label_box(600, 210, labels[4], "#ef4444")
    return wrap_svg_diagram(payload.get("title", "Coordinate Plane"), body)


def render_number_line_diagram(payload):
    labels = diagram_labels(payload, minimum=4)
    body = '<line x1="120" y1="285" x2="780" y2="285" stroke="#172033" stroke-width="5" marker-end="url(#arrow)"/>'
    for index, value in enumerate(range(-3, 4)):
        x = 210 + index * 80
        body += f'<line x1="{x}" y1="265" x2="{x}" y2="305" stroke="#172033" stroke-width="3"/>'
        body += svg_text(x, 335, value, "small")
    body += svg_label_box(90, 170, labels[0], "#ef4444")
    body += svg_label_box(360, 170, labels[1], "#3157d5")
    body += svg_label_box(625, 170, labels[2], "#22c55e")
    return wrap_svg_diagram(payload.get("title", "Number Line"), body)


def render_fraction_diagram(payload):
    labels = diagram_labels(payload, minimum=4)
    colors = ["#3157d5", "#93c5fd", "#93c5fd", "#93c5fd"]
    body = ""
    for index, color in enumerate(colors):
        body += f'<path d="M450 285 L450 135 A150 150 0 0 1 {450 + (index + 1) * 35} {135 + index * 42} Z" fill="{color}" opacity="0.88" stroke="#ffffff" stroke-width="3" transform="rotate({index * 90} 450 285)"/>'
    body += '<circle cx="450" cy="285" r="150" fill="none" stroke="#172033" stroke-width="4"/>'
    body += svg_label_box(95, 160, labels[0], "#3157d5")
    body += svg_label_box(625, 160, labels[1], "#3157d5")
    body += svg_label_box(95, 375, labels[2], "#3157d5")
    body += svg_label_box(625, 375, labels[3], "#3157d5")
    return wrap_svg_diagram(payload.get("title", "Fractions"), body)


def render_organ_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    key = payload.get("template_key")
    if key == "human_heart":
        center = '<path d="M450 420 C300 310 315 165 405 170 C435 172 450 195 450 195 C450 195 465 172 495 170 C585 165 600 310 450 420 Z" fill="#fecaca" stroke="#dc2626" stroke-width="5"/>'
    elif key == "digestive_system":
        center = '<path d="M450 125 C410 175 440 215 480 240 C555 285 515 390 450 420 C375 390 370 295 430 260 C375 215 390 160 450 125 Z" fill="#fed7aa" stroke="#f97316" stroke-width="5"/>'
    elif key == "eye":
        center = '<path d="M210 285 C330 170 570 170 690 285 C570 400 330 400 210 285 Z" fill="#e0f2fe" stroke="#0891b2" stroke-width="5"/><circle cx="450" cy="285" r="70" fill="#ffffff" stroke="#3157d5" stroke-width="4"/><circle cx="450" cy="285" r="32" fill="#172033"/>'
    elif key == "ear":
        center = '<path d="M410 135 C560 145 595 300 485 345 C430 365 445 430 380 430 C300 430 300 330 345 300 C400 260 350 215 410 135 Z" fill="#fde2e2" stroke="#db2777" stroke-width="5"/>'
    else:
        center = '<path d="M450 420 C300 310 315 165 405 170 C435 172 450 195 450 195 C450 195 465 172 495 170 C585 165 600 310 450 420 Z" fill="#fecaca" stroke="#dc2626" stroke-width="5"/>'
    body = center
    positions = [(70, 120), (650, 120), (70, 370), (650, 370), (360, 455)]
    for index, label in enumerate(labels[:5]):
        body += svg_label_box(positions[index][0], positions[index][1], label, "#3157d5")
    return wrap_svg_diagram(payload.get("title", "Organ"), body)


def render_flower_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = """
    <line x1="450" y1="330" x2="450" y2="475" stroke="#16a34a" stroke-width="10"/>
    <ellipse cx="450" cy="225" rx="52" ry="95" fill="#f9a8d4" stroke="#db2777" stroke-width="3"/>
    <ellipse cx="450" cy="225" rx="52" ry="95" fill="#f9a8d4" stroke="#db2777" stroke-width="3" transform="rotate(72 450 285)"/>
    <ellipse cx="450" cy="225" rx="52" ry="95" fill="#f9a8d4" stroke="#db2777" stroke-width="3" transform="rotate(144 450 285)"/>
    <ellipse cx="450" cy="225" rx="52" ry="95" fill="#f9a8d4" stroke="#db2777" stroke-width="3" transform="rotate(216 450 285)"/>
    <ellipse cx="450" cy="225" rx="52" ry="95" fill="#f9a8d4" stroke="#db2777" stroke-width="3" transform="rotate(288 450 285)"/>
    <circle cx="450" cy="285" r="42" fill="#fde68a" stroke="#f59e0b" stroke-width="4"/>
    """
    for index, label in enumerate(labels[:5]):
        body += svg_label_box(70 if index % 2 == 0 else 650, 110 + index * 72, label, "#db2777")
    return wrap_svg_diagram(payload.get("title", "Flower"), body)


def render_flowchart_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    body = ""
    y = 130
    for index, label in enumerate(labels[:5]):
        body += f'<rect x="330" y="{y}" width="240" height="54" rx="16" fill="#eef2ff" stroke="#3157d5" stroke-width="3"/>'
        body += svg_text(450, y + 34, label, "small")
        if index < 4:
            body += f'<path class="line" d="M450,{y + 58} L450,{y + 90}"/>'
        y += 86
    return wrap_svg_diagram(payload.get("title", "Flowchart"), body)


def render_relationship_diagram(payload):
    labels = diagram_labels(payload, minimum=5)
    positions = [(450, 285), (245, 165), (655, 165), (245, 405), (655, 405)]
    body = ""
    for x, y in positions[1:]:
        body += f'<line x1="450" y1="285" x2="{x}" y2="{y}" stroke="#3157d5" stroke-width="3"/>'
    for index, (x, y) in enumerate(positions):
        body += f'<circle cx="{x}" cy="{y}" r="58" fill="#f8fafc" stroke="#3157d5" stroke-width="3"/>'
        body += svg_text(x, y + 6, labels[index], "small")
    return wrap_svg_diagram(payload.get("title", "Relationship Map"), body)


def render_educational_diagram_svg(payload):
    if not payload.get("available"):
        return render_unavailable_diagram(payload)

    key = payload.get("template_key")
    diagram_type = payload.get("diagram_type")
    if key in {"plant_cell", "animal_cell"}:
        return render_cell_diagram(payload)
    if key in {"photosynthesis", "water_cycle"}:
        return render_cycle_diagram(payload)
    if key == "food_chain":
        return render_chain_diagram(payload)
    if key == "solar_system":
        return render_solar_diagram(payload)
    if key == "electric_circuit":
        return render_circuit_diagram(payload)
    if key in {"india_map", "world_map"}:
        return render_map_diagram(payload)
    if key == "layers_of_earth":
        return render_layers_diagram(payload)
    if key == "timeline":
        return render_timeline_diagram(payload)
    if key == "kingdom_chart":
        return render_chart_diagram(payload)
    if key == "story_flowchart":
        return render_flowchart_diagram(payload)
    if key == "character_map":
        return render_relationship_diagram(payload)
    if key == "coordinate_plane":
        return render_coordinate_diagram(payload)
    if key == "number_line":
        return render_number_line_diagram(payload)
    if key == "fractions":
        return render_fraction_diagram(payload)
    if key == "geometry":
        return render_geometry_diagram(payload)
    if key == "flower":
        return render_flower_diagram(payload)
    if diagram_type == "organ" or key in {"human_heart", "digestive_system", "eye", "ear"}:
        return render_organ_diagram(payload)
    return render_flowchart_diagram(payload)


def create_diagram_svg_data_uri(diagram_payload):
    svg = render_educational_diagram_svg(diagram_payload)
    return f"data:image/svg+xml;charset=utf-8,{quote(svg)}"


def create_diagram_image(topic, diagram_payload):
    if isinstance(diagram_payload, dict):
        payload = diagram_payload
    else:
        payload = build_diagram_payload("", topic, diagram_payload)
    return create_diagram_svg_data_uri(payload)


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


def evaluation_to_pdf_flowables(evaluation, styles):
    status_colors = {
        "correct": ("#e7f7ef", "#2f9f67"),
        "incorrect": ("#fff0f0", "#d94848"),
        "partial": ("#fff7dc", "#c58a18"),
    }
    flowables = [
        Paragraph("Question-by-Question Analysis", styles["SectionHeading"]),
        Spacer(1, 4),
    ]
    for index, item in enumerate(evaluation.get("questions", []), start=1):
        status = item.get("status", "incorrect")
        background, border = status_colors.get(status, status_colors["incorrect"])
        card = Table(
            [
                [
                    Paragraph(
                        f"<b>Question {index}:</b> {escape(item.get('question', ''))}",
                        styles["ReportBody"],
                    )
                ],
                [
                    Paragraph(
                        f"<b>Student Answer:</b> {escape(item.get('student_answer', ''))}",
                        styles["ReportBody"],
                    )
                ],
                [
                    Paragraph(
                        f"<b>Correct Answer:</b> {escape(item.get('correct_answer', ''))}",
                        styles["ReportBody"],
                    )
                ],
                [
                    Paragraph(
                        f"<b>Status:</b> {escape(status.title())} &nbsp;&nbsp; <b>Marks:</b> {escape(str(item.get('marks_label', '0')))}/{escape(str(item.get('max_marks', '2')))}",
                        styles["ReportBody"],
                    )
                ],
                [
                    Paragraph(
                        f"<b>Teacher Feedback:</b> {escape(item.get('teacher_feedback', ''))}",
                        styles["ReportBody"],
                    )
                ],
            ],
            colWidths=[5.7 * inch],
        )
        card_rows = [
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor(border)),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        card.setStyle(TableStyle(card_rows))
        flowables.extend([card, Spacer(1, 8)])
        if item.get("revision_tip"):
            flowables.append(
                Paragraph(
                    f"<b>Revision Tip:</b> {escape(item['revision_tip'])}",
                    styles["Tip"],
                )
            )
            flowables.append(Spacer(1, 6))

    report = evaluation.get("teacher_report", {})
    flowables.extend(
        [
            Spacer(1, 8),
            Paragraph("AI Teacher Report", styles["SectionHeading"]),
            Paragraph(escape(report.get("overall_feedback", "")), styles["ReportBody"]),
            Paragraph("Strengths", styles["SectionHeading"]),
        ]
    )
    flowables.extend(
        Paragraph(f"&bull; {escape(item)}", styles["BulletLine"])
        for item in report.get("strengths", [])
    )
    flowables.append(Paragraph("Weak Areas", styles["SectionHeading"]))
    flowables.extend(
        Paragraph(f"&bull; {escape(item)}", styles["BulletLine"])
        for item in report.get("weak_areas", [])
    )
    flowables.append(Paragraph("Personalized Revision Suggestions", styles["SectionHeading"]))
    flowables.extend(
        Paragraph(f"&bull; {escape(item)}", styles["BulletLine"])
        for item in report.get("revision_suggestions", [])
    )
    return flowables


def create_performance_pdf(name, subject, topic, score, grade, report_text, evaluation=None):
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
    if evaluation:
        summary = evaluation.get("summary", {})
        result_table = Table(
            [
                [
                    Paragraph("Percentage", styles["CardLabel"]),
                    Paragraph("Correct", styles["CardLabel"]),
                    Paragraph("Incorrect", styles["CardLabel"]),
                    Paragraph("Partial", styles["CardLabel"]),
                ],
                [
                    Paragraph(escape(str(summary.get("percentage_label", "0%"))), styles["CardValue"]),
                    Paragraph(escape(str(summary.get("correct_answers", 0))), styles["CardValue"]),
                    Paragraph(escape(str(summary.get("incorrect_answers", 0))), styles["CardValue"]),
                    Paragraph(escape(str(summary.get("partial_answers", 0))), styles["CardValue"]),
                ],
            ],
            colWidths=[1.42 * inch, 1.42 * inch, 1.42 * inch, 1.42 * inch],
        )
        result_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef6ff")),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#c9d8ff")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#c9d8ff")),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.extend([result_table, Spacer(1, 16)])
        story.extend(evaluation_to_pdf_flowables(evaluation, styles))
    else:
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


def create_learning_history_pdf(entry, diagram_payload, questions):
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

    if diagram_payload.get("available"):
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Diagram: {escape(diagram_payload.get('title', 'Diagram'))}", styles["SectionHeading"]))
        story.extend(
            Paragraph(f"&bull; {escape(label)}", styles["BulletLine"])
            for label in diagram_payload.get("labels", [])
        )
    else:
        story.append(Spacer(1, 12))
        story.append(Paragraph("Diagram", styles["SectionHeading"]))
        story.append(Paragraph("No diagram available for this topic.", styles["ReportBody"]))

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
    form_data = {
        "full_name": "",
        "username": "",
        "email": "",
        "student_class": "",
    }

    if request.method == "POST":
        form_data, errors = validate_registration_form(request.form)

        if not errors:
            conflicts = find_registration_conflicts(form_data["username"], form_data["email"])
            normalized_username = form_data["username"].lower()
            normalized_email = form_data["email"].lower()

            if any(
                normalized_username in {user.username.lower(), user.email.lower()}
                for user in conflicts
            ):
                errors.append("That username is already taken.")
            if any(
                normalized_email in {user.username.lower(), user.email.lower()}
                for user in conflicts
            ):
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
        except IntegrityError:
            db.session.rollback()
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

        start_authenticated_session(account)

        next_url = request.args.get("next", "")
        if next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for("dashboard"))

    return render_template("login.html", identifier="")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        session.pop("password_reset_user_id", None)
        return render_template("forgot_password.html", identifier="", reset_step=False)

    action = request.form.get("action", "find_account")
    if action == "find_account":
        identifier = request.form.get("identifier", "").strip()
        if not identifier:
            flash("Please enter your username or email address.", "error")
            return render_template("forgot_password.html", identifier=identifier, reset_step=False), 400

        account = get_user_by_username_or_email(identifier)
        if not account:
            flash("We could not find an account with that username or email.", "error")
            return render_template("forgot_password.html", identifier=identifier, reset_step=False), 404

        # Future email verification or OTP checks can be inserted before enabling this step.
        session["password_reset_user_id"] = account["id"]
        return render_template(
            "forgot_password.html",
            identifier=identifier,
            reset_step=True,
            account=account,
        )

    if action == "reset_password":
        reset_user_id = session.get("password_reset_user_id")
        if not reset_user_id:
            flash("Please confirm your username or email before resetting the password.", "error")
            return render_template("forgot_password.html", identifier="", reset_step=False), 400

        account = get_user_by_id(reset_user_id)
        if not account:
            session.pop("password_reset_user_id", None)
            flash("We could not find that account. Please try again.", "error")
            return render_template("forgot_password.html", identifier="", reset_step=False), 404

        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        errors = validate_new_password(password, confirm_password)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "forgot_password.html",
                identifier=account["username"],
                reset_step=True,
                account=account,
            ), 400

        update_user_password(account["id"], password)
        session.pop("password_reset_user_id", None)
        flash("Your password has been reset successfully. Please log in with your new password.", "success")
        return redirect(url_for("login"))

    abort(400, description="Invalid password reset request.")


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


@app.route("/performance")
@login_required
def performance():
    account = current_user()
    return render_template(
        "performance.html",
        account=account,
        analytics=get_performance_analytics(account["id"]),
    )


@app.route("/developer")
@role_required("developer")
def developer_panel():
    account = current_user()
    return render_template(
        "developer.html",
        account=account,
        stats=get_developer_panel_stats(),
    )


@app.route("/developer/users")
@role_required("developer")
def developer_users():
    account = current_user()
    filters = developer_user_filters_from_request()
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1

    users_page = get_developer_users_page(filters, page=page)
    template_context = {
        "account": account,
        "filters": filters,
        "filter_options": developer_user_filter_options(),
        "users_page": users_page,
    }

    if request.args.get("partial") == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render_template("components/developer_users_table.html", **template_context)

    return render_template("developer_users.html", **template_context)


@app.route("/developer/user/<int:user_id>")
@role_required("developer")
def developer_user_detail(user_id):
    account = current_user()
    detail = get_developer_user_detail(user_id)
    if not detail:
        abort(404)
    return render_template(
        "developer_user_detail.html",
        account=account,
        detail=detail,
    )


@app.route("/support")
@role_required("technical_support")
def support_panel():
    account = current_user()
    return render_template(
        "support.html",
        account=account,
        tools=support_tools(),
    )


@app.route("/qa")
@role_required("qa_tester")
def qa_panel():
    account = current_user()
    return render_template(
        "qa.html",
        account=account,
        qa_items=qa_panel_items(),
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
    if sort_order not in {"newest", "oldest", "alphabetical"}:
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

    diagram_payload = decode_diagram_payload(lesson["diagram_data"], lesson["subject"], lesson["topic"])
    questions = decode_json_list(lesson["quiz_questions"])
    return render_template(
        "learning_history_detail.html",
        lesson=lesson,
        notes_html=markdown.markdown(lesson["notes"]),
        diagram_payload=diagram_payload,
        diagram_steps=diagram_payload.get("labels", []),
        diagram_image=create_diagram_image(lesson["topic"], diagram_payload),
        diagram_available=diagram_payload.get("available", False),
        questions=questions,
    )


@app.route("/learning-history/<int:lesson_id>/download")
@login_required
def download_learning_history_pdf(lesson_id):
    lesson = get_learning_history_entry(lesson_id, session["user_id"])
    if not lesson:
        abort(404)

    diagram_payload = decode_diagram_payload(lesson["diagram_data"], lesson["subject"], lesson["topic"])
    pdf_file = create_learning_history_pdf(
        lesson,
        diagram_payload,
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


@app.route("/learning-history/<int:lesson_id>/diagram/download")
@login_required
def download_learning_history_diagram(lesson_id):
    lesson = get_learning_history_entry(lesson_id, session["user_id"])
    if not lesson:
        abort(404)

    diagram_payload = decode_diagram_payload(lesson["diagram_data"], lesson["subject"], lesson["topic"])
    svg = render_educational_diagram_svg(diagram_payload)
    return send_file(
        BytesIO(svg.encode("utf-8")),
        mimetype="image/svg+xml",
        as_attachment=True,
        download_name=safe_notes_filename(lesson["topic"], extension="svg"),
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

## Diagram JSON

Return only a valid JSON object describing the diagram.
Do NOT create an image.
Do NOT create a text diagram.
Use this structure:
{{
  "diagram_type": "process, cycle, cell, organ, map, timeline, chart, flowchart, geometry, coordinate, number_line, fraction, or none",
  "title": "short diagram title",
  "labels": ["3 to 8 short textbook labels"],
  "arrows": ["short arrow descriptions if useful"],
  "notes": ["1 to 3 short notes"]
}}
If the topic does not support a useful educational diagram, use "diagram_type": "none" and empty labels.

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
        notes, raw_diagram, questions = split_learning_content(response.text)
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

## Diagram JSON
{{"diagram_type":"process","title":"Topic Diagram","labels":["label 1","label 2","label 3"],"arrows":[],"notes":[]}}

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
            notes, raw_diagram, questions = split_learning_content(response.text)
        except Exception as retry_error:
            print("LEARN RETRY ERROR:", retry_error)
            abort(502, description="The AI did not return a valid five-question quiz. Please try again.")

    diagram_payload = build_diagram_payload(subject, topic, raw_diagram)
    diagram_image = create_diagram_image(topic, diagram_payload)

    if session.get("user_id"):
        save_learning_history(
            session["user_id"],
            subject,
            book_name,
            topic,
            notes,
            diagram_payload,
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
        diagram_payload=diagram_payload,
        diagram_image=diagram_image,
        diagram_available=diagram_payload.get("available", False),
        diagram_json=json.dumps(diagram_payload),
        questions=questions,
    )


@app.route("/download_diagram", methods=["POST"])
def download_diagram():
    topic = request.form.get("topic", "").strip()
    raw_json = request.form.get("diagram_json", "").strip()
    if not raw_json:
        abort(400, description="Diagram data is required.")

    try:
        diagram_payload = json.loads(raw_json)
    except json.JSONDecodeError:
        abort(400, description="Diagram data is invalid.")

    svg = render_educational_diagram_svg(diagram_payload)
    return send_file(
        BytesIO(svg.encode("utf-8")),
        mimetype="image/svg+xml",
        as_attachment=True,
        download_name=safe_notes_filename(topic or diagram_payload.get("title", "diagram"), extension="svg"),
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
    if diagram_image.startswith(("data:image/png;base64,", "data:image/svg+xml")):
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
You are an expert school teacher evaluating a five-question quiz.

Topic: {topic}
Class: {student_class}
Subject: {subject}

Student Answers:

{question_and_answer_text}

Evaluate every answer individually. Award up to 2 marks per question, for a total of 10 marks. Use partial marks when an answer includes some correct ideas but misses important details.

Return valid JSON only. Do not include markdown, code fences, or extra text.

Use exactly this schema:
{{
  "questions": [
    {{
      "question": "Question text",
      "student_answer": "Student answer",
      "correct_answer": "Teacher model answer",
      "status": "correct, incorrect, or partial",
      "marks_awarded": 0,
      "max_marks": 2,
      "teacher_feedback": "Short teacher feedback",
      "revision_tip": "Helpful tip if incorrect or partial, otherwise empty"
    }}
  ],
  "summary": {{
    "total_score": 0,
    "max_score": 10,
    "percentage": 0,
    "grade": "A+/A/B+/B/C",
    "correct_answers": 0,
    "incorrect_answers": 0,
    "partial_answers": 0
  }},
  "teacher_report": {{
    "overall_feedback": "Encouraging overall feedback",
    "strengths": ["Point 1", "Point 2", "Point 3"],
    "weak_areas": ["Point 1", "Point 2", "Point 3"],
    "revision_suggestions": ["Suggestion 1", "Suggestion 2", "Suggestion 3"]
  }}
}}
"""

    try:
        print("Gemini call: Evaluation")
        response = generate_content_with_fallback(evaluation_prompt)
    except Exception as error:
        print("EVALUATION ERROR:", error)
        if "429" in str(error):
            abort(503, description="Gemini quota reached. Please try again later.")
        abort(503, description="The evaluation service is unavailable. Please try again later.")

    evaluation = build_structured_evaluation(response.text, questions, answers)
    report_text = structured_evaluation_to_markdown(evaluation)
    report = markdown.markdown(report_text)
    evaluation_json = json.dumps(evaluation)
    score = evaluation["summary"]["score_label"]
    grade = evaluation["summary"]["grade"]

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
            evaluation_json,
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
        "report_text": report_text,
        "evaluation_json": evaluation_json,
    }

    return render_template(
        "result.html",
        name=name,
        student_class=student_class,
        subject=subject,
        topic=topic,
        report=report,
        report_text=report_text,
        evaluation=evaluation,
        evaluation_json=evaluation_json,
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
    evaluation_json = values.get("evaluation_json", "").strip()

    if not report_text and latest_report:
        name = name or latest_report.get("name", "")
        subject = subject or latest_report.get("subject", "")
        topic = topic or latest_report.get("topic", "")
        score = score or latest_report.get("score", "")
        grade = grade or latest_report.get("grade", "")
        report_text = latest_report.get("report_text", "")
        evaluation_json = evaluation_json or latest_report.get("evaluation_json", "")

    if not topic or not report_text:
        abort(400, description="Topic and report content are required.")

    evaluation = None
    if evaluation_json:
        evaluation_payload = extract_json_payload(evaluation_json)
        if isinstance(evaluation_payload, dict):
            evaluation = evaluation_payload

    pdf_file = create_performance_pdf(name, subject, topic, score, grade, report_text, evaluation)

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
