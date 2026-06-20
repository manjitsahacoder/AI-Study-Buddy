import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import current_app, has_app_context
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool


db = SQLAlchemy()

POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+psycopg2"}


def normalize_database_url(database_url):
    if not database_url:
        return database_url

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    return with_postgres_connection_defaults(database_url)


def with_postgres_connection_defaults(database_url):
    parsed_url = urlsplit(database_url)
    if parsed_url.scheme not in POSTGRES_SCHEMES:
        return database_url

    query_values = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    query_values.setdefault("sslmode", "require")
    query_values.setdefault("connect_timeout", "30")

    return urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            urlencode(query_values),
            parsed_url.fragment,
        )
    )


def redact_database_url(database_url):
    if not database_url:
        return "not configured"

    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<configured database url>"


def database_engine_options(database_url):
    engine_options = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    try:
        url = make_url(database_url)
    except Exception:
        return engine_options

    if url.get_backend_name() != "postgresql":
        return engine_options

    if (url.host or "").endswith(".pooler.supabase.com") and url.port == 6543:
        engine_options["poolclass"] = NullPool

    return engine_options


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
        database_engine_options(app.config["SQLALCHEMY_DATABASE_URI"]),
    )
    db.init_app(app)

    app.logger.info(
        "DATABASE_URL = %s",
        redact_database_url(app.config["SQLALCHEMY_DATABASE_URI"]),
    )


def create_database_tables():
    if not has_app_context():
        raise RuntimeError(
            "create_database_tables() must be called inside app.app_context()."
        )

    import models  # noqa: F401

    try:
        db.create_all()
    except SQLAlchemyError:
        current_app.logger.exception("Failed to create database tables.")
        raise


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
