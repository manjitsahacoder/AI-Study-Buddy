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
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    quiz_history = db.relationship("QuizHistory", back_populates="user", lazy=True)
    learning_history = db.relationship("LearningHistory", back_populates="user", lazy=True)
    learning_sessions = db.relationship("LearningSession", back_populates="user", lazy=True)
    downloaded_files = db.relationship("DownloadedFile", back_populates="user", lazy=True)
    tutor_lessons = db.relationship("TutorLesson", back_populates="user", lazy=True)


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
