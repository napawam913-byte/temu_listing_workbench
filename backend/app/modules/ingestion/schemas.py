from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    source: str = Field(..., min_length=1)
    entity_type: str = "product"
    mode: str = "upsert"
    idempotency_key: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    records: list[dict[str, Any]] = Field(..., min_length=1)


@dataclass
class CategoryResolution:
    source_category_raw: str = ""
    source_category_path: str = ""
    source_category_level1: str = ""
    source_category_level2: str = ""
    canonical_category_id: str | None = None
    canonical_category_path: str = ""
    status: str = "missing"
    score: float = 0.0
    method: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class NormalizedIngestItem:
    item_id: str
    source_row_index: int
    raw_record: dict[str, Any]
    normalized_record: dict[str, Any]
    source_entity_id: str
    target_table: str = ""
    target_id: str = ""
    category: CategoryResolution = field(default_factory=CategoryResolution)
