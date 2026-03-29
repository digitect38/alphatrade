from datetime import datetime

from pydantic import BaseModel

from app.models.common import CollectionResult


class DisclosureRecord(BaseModel):
    time: datetime
    stock_code: str
    report_name: str
    report_type: str | None = None
    rcept_no: str
    dcm_no: str | None = None
    url: str | None = None
    is_major: bool = False


class DisclosureCollectionRequest(BaseModel):
    corp_codes: list[str] | None = None
    bgn_de: str | None = None  # YYYYMMDD
    end_de: str | None = None


class DisclosureCollectionResult(CollectionResult):
    major_disclosures: list[DisclosureRecord] = []
