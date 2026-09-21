from __future__ import annotations

from pydantic import BaseModel, Field

MAX_TEXT_CHARS = 5000


class NerRequest(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS, examples=["Nama saya Budi Santoso dan tinggal di Jalan Sudirman Jakarta"])
    threshold: float | None = Field(None, ge=0.05, le=0.95,
                                    description="Override the entity threshold (lower = higher recall).")


class NerBatchRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=64)
    threshold: float | None = Field(None, ge=0.05, le=0.95)


class EntityOut(BaseModel):
    text: str
    label: str = Field(..., examples=["PERSON"])
    start: int
    end: int
    score: float


class NerResponse(BaseModel):
    entities: list[EntityOut]
    model_version: str
    inference_ms: float


class NerBatchResponse(BaseModel):
    results: list[list[EntityOut]]
    model_version: str
    inference_ms: float
