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
