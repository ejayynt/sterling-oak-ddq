from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    auth_token = Column(String, index=True)  # secure random token


class GeneratedAnswer(Base):
    __tablename__ = "generated_answers"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    question_text = Column(Text, nullable=False)
    answer_text = Column(Text)
    citation = Column(String)
    evidence_snippet = Column(Text)
    confidence = Column(Float, default=0.0)
    source_filename = Column(String)  # tracks which DDQ this answer belongs to
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
