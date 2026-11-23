"""Database tables (SQLAlchemy Core). SQLite locally, Postgres in production."""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, MetaData, String, Table, UniqueConstraint,
    create_engine,
)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("lang", String(5), nullable=False, default="en"),
    Column("source", String(200)),  # utm_source/utm_campaign at sign-up
    Column("created_at", DateTime(timezone=True), nullable=False),
)

purchases = Table(
    "purchases", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("exam_slug", String(100), nullable=False),
    Column("stripe_session_id", String(255), nullable=False, unique=True),
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(10), nullable=False),
    Column("status", String(20), nullable=False),  # paid | refunded
    Column("created_at", DateTime(timezone=True), nullable=False),
)

login_tokens = Table(
    "login_tokens", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)

# One row per (user, exam, question): how often they got it right/wrong.
progress = Table(
    "progress", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("exam_slug", String(100), nullable=False),
    Column("question_id", String(50), nullable=False),
    Column("correct", Integer, nullable=False, default=0),
    Column("wrong", Integer, nullable=False, default=0),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("user_id", "exam_slug", "question_id"),
)

mock_results = Table(
    "mock_results", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("exam_slug", String(100), nullable=False),
    Column("score", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    Column("passed", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def now():
    return datetime.now(timezone.utc)


def make_engine(url):
    # Railway and Heroku hand out postgres:// URLs; SQLAlchemy wants a driver name.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    engine = create_engine(url, pool_pre_ping=True, future=True)
    metadata.create_all(engine)
    return engine
