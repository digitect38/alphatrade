from datetime import datetime

from pydantic import BaseModel

from app.models.common import CollectionResult


class NewsRecord(BaseModel):
    time: datetime
    source: str
    title: str
    content: str | None = None
    url: str | None = None
    stock_codes: list[str] = []
    category: str | None = None


class NewsCollectionResult(CollectionResult):
    sample: list[NewsRecord] = []
