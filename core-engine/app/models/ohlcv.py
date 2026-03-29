from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.common import CollectionResult


class OHLCVRecord(BaseModel):
    time: datetime
    stock_code: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    value: int | None = None
    interval: str = "1d"


class OHLCVCollectionRequest(BaseModel):
    stock_codes: list[str] | None = None
    interval: str = "1m"


class OHLCVCollectionResult(CollectionResult):
    redis_published: int = 0
