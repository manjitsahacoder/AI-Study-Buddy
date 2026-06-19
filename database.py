import os
from pathlib import Path

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError


db = SQLAlchemy()


def normalize_database_url(database_url):
    if database_url and database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    return database_url


def local_sqlite_uri(app):
    sqlite_path = (
        app.config.get("LOCAL_SQLITE_PATH")
        or os.environ.get("QUIZ_HISTORY_DB")
        or str(Path(app.root_path) / "quiz_history.db")
    )
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.resolve().as_posix()}"


def configure_database(app):
    database_url = normalize_database_url(os.environ.get("DATABASE_URL"))
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url or local_sqlite_uri(app)
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault(
        "SQLALCHEMY_ENGINE_OPTIONS",
        {
            "pool_pre_ping": True,
        },
    )
    db.init_app(app)


def create_database_tables():
    db.create_all()


def rollback_database_session(error=None):
    try:
        db.session.rollback()
    except SQLAlchemyError:
        pass
    return error


def reset_database_for_tests(app, database_uri):
    app.config["SQLALCHEMY_DATABASE_URI"] = database_uri
    with app.app_context():
        db.session.remove()
        engines = getattr(db, "_app_engines", {}).get(app)
        if engines:
            for engine in engines.values():
                engine.dispose()
            engines.clear()
        db.create_all()
