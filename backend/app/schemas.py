"""Request / response models (they also drive the OpenAPI docs at /docs)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ids: list[str] | None = None


class StatusCounts(BaseModel):
    PASS: int = 0
    FAIL: int = 0
    CANNOT_SCAN: int = 0


class SeverityCounts(BaseModel):
    CRITICAL: int = 0
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0


class AccountSummary(BaseModel):
    account_id: str
    name: str | None
    provider: str | None
    score: float | None
    counts: StatusCounts


class ScanSummary(BaseModel):
    id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    account_ids: list[str]
    score: float | None
    counts: StatusCounts
    error: str | None = None


class ScanDetail(ScanSummary):
    fail_by_severity: SeverityCounts
    accounts: list[AccountSummary]


class Finding(BaseModel):
    id: int
    scan_id: str
    check_id: str
    title: str
    provider: str
    account_id: str
    region: str | None
    resource_id: str | None
    status: str
    severity: str
    details: str


class FindingPage(BaseModel):
    items: list[Finding]
    total: int
    page: int
    page_size: int


class CheckInfo(BaseModel):
    check_id: str
    title: str
    severity: str
    provider: str
    collection: str
    resource_id_field: str
