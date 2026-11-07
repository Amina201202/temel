from datetime import datetime

from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: int
    name: str
    description: str


class EdgeOut(BaseModel):
    id: int
    from_concept: str
    to_concept: str
    approved: bool


class ChapterOut(BaseModel):
    id: int
    title: str
    grade: int
    source_file: str
    status: str
    created_at: datetime
    concept_count: int
    edge_count: int


class GraphOut(BaseModel):
    chapter: ChapterOut
    concepts: list[ConceptOut]
    edges: list[EdgeOut]


class OptionOut(BaseModel):
    value: str
    correct: bool
    misconception: str | None = None
    points_to: str | None = None


class QuestionOut(BaseModel):
    id: int
    concept: str
    difficulty: int
    status: str
    template_text: str
    source_quote: str
    problems: list[str]
    notes: list[str] = []
    # admin ucun numune: sablondan yaranmis bir konkret sual
    sample_text: str | None = None
    sample_options: list[OptionOut] = []


class StatusIn(BaseModel):
    status: str


class QuestionStats(BaseModel):
    total: int
    auto_ok: int
    needs_review: int
    approved: int
    rejected: int


class AttemptIn(BaseModel):
    nickname: str
    chapter_id: int | None = None
    join_code: str | None = None


class AnswerIn(BaseModel):
    token: str
    value: str


class PublicQuestion(BaseModel):
    number: int
    max: int
    concept: str
    text: str
    options: list[str]


class Feedback(BaseModel):
    # evvelki suala qisa geri bildirim (duz/sehv, sehvin menasi)
    correct: bool
    correct_value: str
    misconception: str | None = None


class AttemptStep(BaseModel):
    attempt_id: int
    token: str
    done: bool
    question: PublicQuestion | None = None
    feedback: Feedback | None = None
    diagnosis: dict | None = None
