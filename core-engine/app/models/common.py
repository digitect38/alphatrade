from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CollectionResult(BaseModel):
    status: Literal["success", "partial", "error"]
    inserted: int = 0
    duplicates: int = 0
    errors: list[str] = []
    collected_at: datetime


class CollectionTrigger(BaseModel):
    stock_codes: list[str] | None = None  # None = use active universe
    force: bool = False
