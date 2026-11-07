from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    grade: Mapped[int]
    source_file: Mapped[str] = mapped_column(String(255))
    # sual yaratmaq ucun dersliyin metnini saxlayiriq (.txt olanda)
    source_text: Mapped[str] = mapped_column(Text, default="")
    # draft -> admin tesdiqleyene qeder sagirde gorunmur
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    concepts: Mapped[list["Concept"]] = relationship(back_populates="chapter", cascade="all, delete-orphan", order_by="Concept.id")
    edges: Mapped[list["ConceptEdge"]] = relationship(back_populates="chapter", cascade="all, delete-orphan", order_by="ConceptEdge.id")


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("chapter_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")

    chapter: Mapped[Chapter] = relationship(back_populates="concepts")


class ConceptEdge(Base):
    __tablename__ = "concept_edges"
    __table_args__ = (UniqueConstraint("from_concept_id", "to_concept_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    # from -> evvelceden bilinmeli olan, to -> ona soykenen movzu
    from_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))
    to_concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    chapter: Mapped[Chapter] = relationship(back_populates="edges")
    from_concept: Mapped[Concept] = relationship(foreign_keys=[from_concept_id])
    to_concept: Mapped[Concept] = relationship(foreign_keys=[to_concept_id])


class QuestionTemplate(Base):
    __tablename__ = "question_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"))
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)
    variables: Mapped[list] = mapped_column(JSON)
    constraints: Mapped[list] = mapped_column(JSON)
    answer_expr: Mapped[str] = mapped_column(Text)
    answer_format: Mapped[str] = mapped_column(String(20), default="fraction")
    distractors: Mapped[list] = mapped_column(JSON)
    source_quote: Mapped[str] = mapped_column(Text, default="")
    # auto_ok -> kod yoxlamasindan kecdi, needs_review -> admin baxmalidir
    # approved / rejected -> admin qerari
    status: Mapped[str] = mapped_column(String(20), default="needs_review")
    check_report: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    concept: Mapped[Concept] = relationship()

    def as_dict(self):
        return {
            "variables": self.variables,
            "constraints": self.constraints,
            "answer_expr": self.answer_expr,
            "answer_format": self.answer_format,
            "distractors": self.distractors,
            "text": self.text,
        }


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassSession(Base):
    """Muellimin acdigi sessiya: 4 reqemli kodla sagirdler qosulur."""
    __tablename__ = "class_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), nullable=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    class_name: Mapped[str] = mapped_column(String(40))
    join_code: Mapped[str] = mapped_column(String(8), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attempt(Base):
    """Bir sagirdin bir test kecmesi. LangGraph thread_id = attempt-<id>."""
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # sagird bu token olmadan cavab gondere bilmez
    token: Mapped[str] = mapped_column(String(64), unique=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("class_sessions.id", ondelete="SET NULL"), nullable=True)
    nickname: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    diagnosis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("question_templates.id", ondelete="SET NULL"), nullable=True)
    concept: Mapped[str] = mapped_column(String(200))
    question_text: Mapped[str] = mapped_column(Text)
    chosen: Mapped[str] = mapped_column(String(60))
    correct_value: Mapped[str] = mapped_column(String(60))
    correct: Mapped[bool] = mapped_column(Boolean)
    misconception: Mapped[str | None] = mapped_column(Text, nullable=True)
    points_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
