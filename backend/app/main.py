"""FastAPI app: start scans in the background, store and serve their findings.

Config (env vars):
  INVENTORY_PATH     snapshot file             (default data/inventory.json)
  DATABASE_URL       SQLAlchemy URL            (default sqlite:///./mini_gauntlet.db)
  SCAN_WORKERS       concurrent accounts       (default 4)
  CORS_ORIGINS       comma-separated origins   (default http://localhost:3000)
  SIMULATE_LATENCY   "0" skips the per-account wait (tests only)
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from . import scanner
from .checks import CHECKS
from .checks.registry import CANNOT_SCAN, FAIL, PASS, SEVERITIES
from .db import (
    COMPLETED,
    DEFAULT_DATABASE_URL,
    FAILED,
    RUNNING,
    Base,
    FindingRow,
    ScanRow,
    as_utc,
    make_sessionmaker,
    utcnow,
)
from .schemas import CheckInfo, FindingPage, ScanDetail, ScanRequest, ScanSummary

log = logging.getLogger("api")

STATUS_ORDER = {FAIL: 0, CANNOT_SCAN: 1, PASS: 2}
SEVERITY_ORDER = {sev: i for i, sev in enumerate(SEVERITIES)}


# --------------------------------------------------------------------------- scan job


def run_scan_job(
    Session: sessionmaker,
    scan_id: str,
    inventory_path: str,
    account_ids: list[str] | None,
    simulate_latency: bool,
) -> None:
    """Runs in a worker thread after POST /api/scans has returned 202."""
    try:
        inventory = scanner.load_inventory(inventory_path)
        findings = scanner.run_scan(inventory, selected=account_ids, sleep=simulate_latency)
        with Session.begin() as s:  # findings + COMPLETED land in one transaction
            s.add_all(FindingRow(scan_id=scan_id, **f.to_dict()) for f in findings)
            s.execute(
                update(ScanRow).where(ScanRow.id == scan_id).values(status=COMPLETED, finished_at=utcnow())
            )
        log.info("scan %s completed with %d findings", scan_id, len(findings))
    except Exception as exc:
        log.exception("scan %s failed", scan_id)
        with Session.begin() as s:
            s.execute(
                update(ScanRow)
                .where(ScanRow.id == scan_id)
                .values(status=FAILED, finished_at=utcnow(), error=str(exc)[:500])
            )


# --------------------------------------------------------------------------- summaries


def _counts(counter: Counter) -> dict[str, int]:
    return {PASS: counter[PASS], FAIL: counter[FAIL], CANNOT_SCAN: counter[CANNOT_SCAN]}


def _score(counter: Counter) -> float | None:
    scored = counter[PASS] + counter[FAIL]
    return round(100 * counter[PASS] / scored, 1) if scored else None


def _summary(scan: ScanRow, counter: Counter) -> dict[str, Any]:
    started, finished = as_utc(scan.started_at), as_utc(scan.finished_at)
    return {
        "id": scan.id,
        "status": scan.status,
        "started_at": started,
        "finished_at": finished,
        "duration_seconds": round((finished - started).total_seconds(), 2) if finished else None,
        "account_ids": [a["account_id"] for a in scan.accounts],
        "score": _score(counter),
        "counts": _counts(counter),
        "error": scan.error,
    }


def _get_scan(s: Session, scan_id: str) -> ScanRow:
    scan = s.get(ScanRow, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


# --------------------------------------------------------------------------- app


def create_app(
    database_url: str | None = None,
    inventory_path: str | None = None,
    simulate_latency: bool | None = None,
) -> FastAPI:
    db_url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    inv_path = inventory_path or str(scanner.inventory_path())
    if simulate_latency is None:
        simulate_latency = os.environ.get("SIMULATE_LATENCY", "1") != "0"
    Session = make_sessionmaker(db_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        Base.metadata.create_all(Session.kw["bind"])
        # A scan still RUNNING at startup was cut off by a restart; it will never finish.
        with Session.begin() as s:
            s.execute(
                update(ScanRow)
                .where(ScanRow.status == RUNNING)
                .values(status=FAILED, finished_at=utcnow(), error="Interrupted by API restart")
            )
        yield

    app = FastAPI(title="Mini Gauntlet", version="0.1.0", lifespan=lifespan)
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/checks", response_model=list[CheckInfo])
    def list_checks() -> list[dict[str, str]]:
        return [c.to_dict() for c in CHECKS.values()]

    @app.post("/api/scans", status_code=202, response_model=ScanSummary)
    def start_scan(
        background: BackgroundTasks,
        body: ScanRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        requested = body.account_ids if body else None
        if requested is not None and not requested:
            raise HTTPException(status_code=422, detail="account_ids must not be empty")

        # Read the snapshot now to validate IDs; if it can't be read, the scan still
        # starts and is marked FAILED by the job (that's what FAILED is for).
        try:
            known = {
                a["account_id"]: a
                for a in scanner.load_inventory(inv_path)["accounts"]
                if isinstance(a, dict) and isinstance(a.get("account_id"), str)
            }
        except scanner.InventoryError:
            known = None

        if requested is not None:
            selected = list(dict.fromkeys(requested))  # dedupe, keep order
            if known is not None:
                unknown = [a for a in selected if a not in known]
                if unknown:
                    raise HTTPException(
                        status_code=422, detail={"message": "Unknown account IDs", "account_ids": unknown}
                    )
        else:
            selected = list(known) if known else []

        accounts = [
            {
                "account_id": aid,
                "name": known[aid].get("name") if known and isinstance(known[aid].get("name"), str) else None,
                "provider": known[aid].get("provider") if known else None,
            }
            for aid in selected
        ]
        scan = ScanRow(id=str(uuid.uuid4()), status=RUNNING, started_at=utcnow(), accounts=accounts)
        with Session.begin() as s:
            s.add(scan)
        background.add_task(
            run_scan_job, Session, scan.id, inv_path, selected if requested else None, simulate_latency
        )
        return _summary(scan, Counter())

    @app.get("/api/scans", response_model=list[ScanSummary])
    def list_scans() -> list[dict[str, Any]]:
        with Session() as s:
            scans = s.scalars(select(ScanRow).order_by(ScanRow.started_at.desc(), ScanRow.id)).all()
            per_scan: dict[str, Counter] = defaultdict(Counter)
            rows = s.execute(
                select(FindingRow.scan_id, FindingRow.status, func.count()).group_by(
                    FindingRow.scan_id, FindingRow.status
                )
            )
            for scan_id, status, n in rows:
                per_scan[scan_id][status] = n
            return [_summary(scan, per_scan[scan.id]) for scan in scans]

    @app.get("/api/scans/{scan_id}", response_model=ScanDetail)
    def get_scan(scan_id: str) -> dict[str, Any]:
        with Session() as s:
            scan = _get_scan(s, scan_id)
            rows = s.execute(
                select(FindingRow.account_id, FindingRow.status, FindingRow.severity, func.count())
                .where(FindingRow.scan_id == scan_id)
                .group_by(FindingRow.account_id, FindingRow.status, FindingRow.severity)
            ).all()

        total: Counter = Counter()
        by_account: dict[str, Counter] = defaultdict(Counter)
        fail_by_sev: Counter = Counter()
        for account_id, status, severity, n in rows:
            total[status] += n
            by_account[account_id][status] += n
            if status == FAIL:
                fail_by_sev[severity] += n

        detail = _summary(scan, total)
        detail["fail_by_severity"] = {sev: fail_by_sev[sev] for sev in SEVERITIES}
        detail["accounts"] = [
            {
                "account_id": a["account_id"],
                "name": a.get("name"),
                "provider": a.get("provider"),
                "score": _score(by_account[a["account_id"]]),
                "counts": _counts(by_account[a["account_id"]]),
            }
            for a in scan.accounts
        ]
        return detail

    @app.get("/api/scans/{scan_id}/findings", response_model=FindingPage)
    def list_findings(
        scan_id: str,
        status: str | None = None,
        severity: str | None = None,
        provider: str | None = None,
        account_id: str | None = None,
        check_id: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ) -> dict[str, Any]:
        filters = [FindingRow.scan_id == scan_id]
        for column, value in (
            (FindingRow.status, status),
            (FindingRow.severity, severity),
            (FindingRow.provider, provider),
            (FindingRow.account_id, account_id),
            (FindingRow.check_id, check_id),
        ):
            if value is not None and value.strip():
                filters.append(func.lower(column) == value.strip().lower())

        order = (
            case(STATUS_ORDER, value=FindingRow.status, else_=len(STATUS_ORDER)),
            case(SEVERITY_ORDER, value=FindingRow.severity, else_=len(SEVERITY_ORDER)),
            FindingRow.check_id,
            func.coalesce(FindingRow.resource_id, ""),
            FindingRow.id,
        )
        with Session() as s:
            _get_scan(s, scan_id)
            total = s.scalar(select(func.count()).select_from(FindingRow).where(*filters)) or 0
            items = s.scalars(
                select(FindingRow)
                .where(*filters)
                .order_by(*order)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "items": [{c.name: getattr(f, c.name) for c in FindingRow.__table__.columns} for f in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
