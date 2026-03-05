import os
import sqlite3
import sqlite_vec
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models import Base, User, GeneratedAnswer  # noqa: F401 — re-export

# Centralised DB path so every module references the same file
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sterling_oak.db")
DB_PATH = os.path.normpath(DB_PATH)

DATABASE_URL = f"sqlite:///{DB_PATH}"

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_vec_connection():
    """Return a raw sqlite3 connection with sqlite-vec loaded."""
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def init_db():
    """Creates relational tables and initialises the vec0 virtual table."""
    # 1. Relational tables via SQLAlchemy
    Base.metadata.create_all(bind=engine)

    # 2. Vector virtual table via raw sqlite3 + sqlite-vec
    conn = get_vec_connection()
    cursor = conn.cursor()
    # 1024 = Mistral mistral-embed dimension
    # Auxiliary columns (+) store metadata alongside vectors without extra JOINs
    # +user_id ensures tenant isolation — each user only retrieves their own context
    cursor.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS document_embeddings USING vec0(
            embedding float[1024],
            +user_id   integer,
            +doc_name  text,
            +chunk_text text
        );
    """
    )
    conn.commit()
    conn.close()


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
