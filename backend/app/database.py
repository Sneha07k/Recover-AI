from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# check_same_thread=False is a SQLite-specific quirk: by default SQLite
# refuses to let a connection be used across threads, but FastAPI can
# handle a single request across different threads. Safe for our use case
# since SQLAlchemy's session handling still keeps operations sequential.
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Every SQLAlchemy model (Phase 2 onward) will inherit from this Base,
# which is what lets SQLAlchemy know to create a table for it.
Base = declarative_base()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """
    Creates all tables that have been defined via classes inheriting from
    Base (see app/models/models.py). Safe to call repeatedly — it only
    creates tables that don't already exist.
    """
    from app.models import models  # noqa: F401 (import registers the tables)

    Base.metadata.create_all(bind=engine)


def get_db():
    """
    FastAPI dependency: gives each request its own DB session and
    guarantees it's closed afterward, even if the request raises an error.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


