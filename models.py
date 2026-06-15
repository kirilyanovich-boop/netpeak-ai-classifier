from typing import Literal
from pydantic import BaseModel, Field


class RequestClassification(BaseModel):
    id: str
    category: Literal[
        "автоматизація",
        "інтеграція",
        "звіт/аналітика",
        "баг/підтримка",
        "питання/консультація",
        "поза скоупом",
    ]
    target_department: str | None
    priority: Literal["low", "medium", "high"]
    short_summary: str
    requested_actions: list[str]
    needs_clarification: bool
    confidence: int = Field(ge=1, le=10)
    is_likely_duplicate: bool


class ProcessingError(BaseModel):
    id: str
    error: str
    raw_response: str
