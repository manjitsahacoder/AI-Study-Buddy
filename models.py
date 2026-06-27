from datetime import datetime, timezone

from database import db


class ModelMappingMixin:
    def __getitem__(self, key):
        value = getattr(self, key)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value

    def get(self, key, default=None):
        value = getattr(self, key, default)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value


def utc_now():
    return datetime.now(timezone.utc)


class User(ModelMappingMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.Text, nullable=False)
    username = db.Column(db.Text, nullable=False, unique=True, index=True)
    email = db.Column(db.Text, nullable=False, unique=True, index=True)
    student_class = db.Column(db.Text, nullable=False)
    role = db.Column(db.Text, nullable=False, default="student")
    password_hash = db.Column(db.Text, nullable=False)
    theme_preference = db.Column(db.Text, nullable=False, default="system")
    ai_explanation_style = db.Column(db.Text, nullable=False, default="standard")
    default_subject = db.Column(db.Text)
    default_class = db.Column(db.Text)
    notifications_enabled = db.Column(db.Boolean, nullable=False, default=True)
    notify_study_reminders = db.Column(db.Boolean, nullable=False, default=True)
    notify_achievement_notifications = db.Column(db.Boolean, nullable=False, default=True)
    notify_daily_challenge_reminders = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    quiz_history = db.relationship("QuizHistory", back_populates="user", lazy=True)
    learning_history = db.relationship("LearningHistory", back_populates="user", lazy=True)
    learning_sessions = db.relationship("LearningSession", back_populates="user", lazy=True)
    downloaded_files = db.relationship("DownloadedFile", back_populates="user", lazy=True)
    tutor_lessons = db.relationship("TutorLesson", back_populates="user", lazy=True)
    flashcard_sets = db.relationship("FlashcardSet", back_populates="user", lazy=True)
    revision_sheets = db.relationship("RevisionSheet", back_populates="user", lazy=True)
    mind_maps = db.relationship("MindMap", back_populates="user", lazy=True)
    important_question_sets = db.relationship("ImportantQuestionSet", back_populates="user", lazy=True)


class QuizHistory(ModelMappingMixin, db.Model):
    __tablename__ = "quiz_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    name = db.Column(db.Text, nullable=False)
    student_class = db.Column(db.Text, nullable=False)
    subject = db.Column(db.Text, nullable=False)
    topic = db.Column(db.Text, nullable=False)
    score = db.Column(db.Text, nullable=False)
    grade = db.Column(db.Text, nullable=False)
    questions_json = db.Column(db.Text, nullable=False)
    answers_json = db.Column(db.Text, nullable=False)
    report_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    user = db.relationship("User", back_populates="quiz_history")


class LearningSession(ModelMappingMixin, db.Model):
    __tablename__ = "learning_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.Text, nullable=False)
    student_class = db.Column(db.Text, nullable=False)
    subject = db.Column(db.Text, nullable=False)
    book_name = db.Column(db.Text)
    topic = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    user = db.relationship("User", back_populates="learning_sessions")


class DownloadedFile(ModelMappingMixin, db.Model):
    __tablename__ = "downloaded_files"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    file_type = db.Column(db.Text, nullable=False)
    subject = db.Column(db.Text)
    topic = db.Column(db.Text, nullable=False)
    score = db.Column(db.Text)
    grade = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    user = db.relationship("User", back_populates="downloaded_files")


class LearningHistory(ModelMappingMixin, db.Model):
    __tablename__ = "learning_history"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject = db.Column(db.Text, nullable=False)
    book_name = db.Column(db.Text)
    topic = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=False)
    diagram_data = db.Column(db.Text, nullable=False)
    quiz_questions = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    user = db.relationship("User", back_populates="learning_history")
    tutor_lessons = db.relationship(
        "TutorLesson",
        back_populates="learning_history",
        cascade="all, delete-orphan",
        lazy=True,
    )
    flashcard_sets = db.relationship(
        "FlashcardSet",
        back_populates="learning_history",
        cascade="all, delete-orphan",
        lazy=True,
    )
    revision_sheets = db.relationship(
        "RevisionSheet",
        back_populates="learning_history",
        cascade="all, delete-orphan",
        lazy=True,
    )
    mind_maps = db.relationship(
        "MindMap",
        back_populates="learning_history",
        cascade="all, delete-orphan",
        lazy=True,
    )
    important_question_sets = db.relationship(
        "ImportantQuestionSet",
        back_populates="learning_history",
        cascade="all, delete-orphan",
        lazy=True,
    )


class MindMap(ModelMappingMixin, db.Model):
    __tablename__ = "mind_maps"
    __table_args__ = (
        db.UniqueConstraint("user_id", "learning_history_id", name="uq_mind_map_user_history"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_history_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_history.id"),
        nullable=False,
        index=True,
    )
    map_json = db.Column(db.Text, nullable=False)
    source_model = db.Column(db.Text, nullable=False, default="gemini-2.5-flash")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    user = db.relationship("User", back_populates="mind_maps")
    learning_history = db.relationship("LearningHistory", back_populates="mind_maps")


class RevisionSheet(ModelMappingMixin, db.Model):
    __tablename__ = "revision_sheets"
    __table_args__ = (
        db.UniqueConstraint("user_id", "learning_history_id", name="uq_revision_sheet_user_history"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_history_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_history.id"),
        nullable=False,
        index=True,
    )
    content_markdown = db.Column(db.Text, nullable=False)
    source_model = db.Column(db.Text, nullable=False, default="gemini-2.5-flash")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    user = db.relationship("User", back_populates="revision_sheets")
    learning_history = db.relationship("LearningHistory", back_populates="revision_sheets")


class ImportantQuestionSet(ModelMappingMixin, db.Model):
    __tablename__ = "important_question_sets"
    __table_args__ = (
        db.UniqueConstraint("user_id", "learning_history_id", name="uq_important_question_set_user_history"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_history_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_history.id"),
        nullable=False,
        index=True,
    )
    markdown = db.Column(db.Text, nullable=False)
    source_model = db.Column(db.Text, nullable=False, default="gemini-2.5-flash")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    user = db.relationship("User", back_populates="important_question_sets")
    learning_history = db.relationship("LearningHistory", back_populates="important_question_sets")


class FlashcardSet(ModelMappingMixin, db.Model):
    __tablename__ = "flashcard_sets"
    __table_args__ = (
        db.UniqueConstraint("user_id", "learning_history_id", name="uq_flashcard_set_user_history"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_history_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_history.id"),
        nullable=False,
        index=True,
    )
    source_model = db.Column(db.Text, nullable=False, default="gemini-2.5-flash")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    user = db.relationship("User", back_populates="flashcard_sets")
    learning_history = db.relationship("LearningHistory", back_populates="flashcard_sets")
    flashcards = db.relationship(
        "Flashcard",
        back_populates="flashcard_set",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="Flashcard.position",
    )


class Flashcard(ModelMappingMixin, db.Model):
    __tablename__ = "flashcards"

    id = db.Column(db.Integer, primary_key=True)
    flashcard_set_id = db.Column(
        db.Integer,
        db.ForeignKey("flashcard_sets.id"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_history_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_history.id"),
        nullable=False,
        index=True,
    )
    position = db.Column(db.Integer, nullable=False, default=0)
    front = db.Column(db.Text, nullable=False)
    back = db.Column(db.Text, nullable=False)
    mastered = db.Column(db.Boolean, nullable=False, default=False)
    needs_revision = db.Column(db.Boolean, nullable=False, default=False)
    review_count = db.Column(db.Integer, nullable=False, default=0)
    interval_days = db.Column(db.Integer, nullable=False, default=0)
    ease_factor = db.Column(db.Float, nullable=False, default=2.5)
    memory_tip = db.Column(db.Text)
    weak_topic_tag = db.Column(db.Text)
    last_reviewed_at = db.Column(db.DateTime)
    next_review_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    flashcard_set = db.relationship("FlashcardSet", back_populates="flashcards")


class TutorLesson(ModelMappingMixin, db.Model):
    __tablename__ = "tutor_lessons"
    __table_args__ = (
        db.UniqueConstraint("user_id", "learning_history_id", name="uq_tutor_lesson_user_history"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    learning_history_id = db.Column(
        db.Integer,
        db.ForeignKey("learning_history.id"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.Text, nullable=False)
    student_class = db.Column(db.Text, nullable=False)
    subject = db.Column(db.Text, nullable=False)
    book_name = db.Column(db.Text)
    chapter = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now, index=True)

    user = db.relationship("User", back_populates="tutor_lessons")
    learning_history = db.relationship("LearningHistory", back_populates="tutor_lessons")
    messages = db.relationship(
        "TutorMessage",
        back_populates="tutor_lesson",
        cascade="all, delete-orphan",
        lazy=True,
        order_by="TutorMessage.created_at",
    )


class TutorMessage(ModelMappingMixin, db.Model):
    __tablename__ = "tutor_messages"

    id = db.Column(db.Integer, primary_key=True)
    tutor_lesson_id = db.Column(
        db.Integer,
        db.ForeignKey("tutor_lessons.id"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    sender = db.Column(db.Text, nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)

    tutor_lesson = db.relationship("TutorLesson", back_populates="messages")
