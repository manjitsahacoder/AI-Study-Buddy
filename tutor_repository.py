from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from database import db
from models import LearningHistory, TutorLesson, TutorMessage


def get_user_lesson(lesson_id, user_id):
    return LearningHistory.query.filter_by(id=lesson_id, user_id=user_id).first()


def get_or_create_tutor_lesson(user_id, learning_history, name, student_class):
    tutor_lesson = TutorLesson.query.filter_by(
        user_id=user_id,
        learning_history_id=learning_history.id,
    ).first()
    if tutor_lesson:
        changed = False
        if name and tutor_lesson.name != name:
            tutor_lesson.name = name
            changed = True
        if student_class and tutor_lesson.student_class != student_class:
            tutor_lesson.student_class = student_class
            changed = True
        if changed:
            db.session.commit()
        return tutor_lesson

    tutor_lesson = TutorLesson(
        user_id=user_id,
        learning_history_id=learning_history.id,
        name=name,
        student_class=student_class,
        subject=learning_history.subject,
        book_name=learning_history.book_name,
        chapter=learning_history.topic,
    )
    db.session.add(tutor_lesson)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        tutor_lesson = TutorLesson.query.filter_by(
            user_id=user_id,
            learning_history_id=learning_history.id,
        ).first()
    return tutor_lesson


def get_tutor_lesson_for_user(tutor_lesson_id, user_id):
    return (
        TutorLesson.query.options(joinedload(TutorLesson.learning_history))
        .filter(TutorLesson.id == tutor_lesson_id, TutorLesson.user_id == user_id)
        .first()
    )


def get_tutor_messages(tutor_lesson_id):
    return (
        TutorMessage.query.filter_by(tutor_lesson_id=tutor_lesson_id)
        .order_by(TutorMessage.created_at.asc(), TutorMessage.id.asc())
        .all()
    )


def get_recent_tutor_messages(tutor_lesson_id, limit=12):
    messages = (
        TutorMessage.query.filter_by(tutor_lesson_id=tutor_lesson_id)
        .order_by(TutorMessage.created_at.desc(), TutorMessage.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(messages))


def save_tutor_exchange(tutor_lesson, student_message, tutor_response):
    db.session.add_all(
        [
            TutorMessage(
                tutor_lesson_id=tutor_lesson.id,
                user_id=tutor_lesson.user_id,
                sender="student",
                content=student_message,
            ),
            TutorMessage(
                tutor_lesson_id=tutor_lesson.id,
                user_id=tutor_lesson.user_id,
                sender="assistant",
                content=tutor_response,
            ),
        ]
    )
    db.session.commit()
