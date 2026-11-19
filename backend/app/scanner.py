"""Scanner engine: load the snapshot, run every registered check, score results.

Run directly for a quick summary:  python -m app.scanner
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .checks import CHECKS, Check, ScanContext
from .checks.common import parse_time, text
from .checks.registry import CANNOT_SCAN, FAIL, PASS, CannotScan

log = logging.getLogger("scanner")

DEFAULT_INVENTORY = "data/inventory.json"
DEFAULT_WORKERS = 4


class InventoryError(Exception):
    """The snapshot as a whole can't be used (missing, unreadable, malformed)."""


@dataclass
class Finding:
    check_id: str
    title: str
    provider: str
    account_id: str
    region: str | None
    resource_id: str | None
    status: str
    severity: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- config


def inventory_path() -> Path:
    return Path(os.environ.get("INVENTORY_PATH", DEFAULT_INVENTORY))


def worker_count() -> int:
    raw = os.environ.get("SCAN_WORKERS", str(DEFAULT_WORKERS))
    try:
        return max(1, int(raw))
    except ValueError:
        log.warning("SCAN_WORKERS=%r is not a number; using %d", raw, DEFAULT_WORKERS)
        return DEFAULT_WORKERS


# --------------------------------------------------------------------------- loading


def load_inventory(path: Path | str | None = None) -> dict[str, Any]:
    """Read and minimally validate the snapshot. Raises InventoryError."""
    p = Path(path) if path is not None else inventory_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InventoryError(f"cannot read inventory {p}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise InventoryError("inventory must be an object with an 'accounts' list")
    try:
        parse_time(data.get("snapshot_taken_at"), "snapshot_taken_at")
    except CannotScan as exc:
        raise InventoryError(str(exc)) from exc
    return data


def account_ids(inventory: dict[str, Any]) -> list[str]:
    return [
        str(a["account_id"])
        for a in inventory["accounts"]
        if isinstance(a, dict) and isinstance(a.get("account_id"), str)
    ]


# --------------------------------------------------------------------------- scanning


def _latency_seconds(account: dict[str, Any]) -> float:
    ms = account.get("simulated_latency_ms", 0)
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms < 0:
        log.warning("account %s: bad simulated_latency_ms %r; using 0", text(account.get("account_id")), ms)
        return 0.0
    return min(float(ms), 60_000.0) / 1000.0  # cap so a hostile value can't hang a scan


def _run_check(check: Check, resource: Any, ctx: ScanContext, account_id: str) -> Finding:
    rid: str | None = None
    region: str | None = None
    try:
        if not isinstance(resource, dict):
            raise CannotScan(f"record is not an object: {text(repr(resource))}")
        raw_id = resource.get(check.id_field)
        rid = text(raw_id) if raw_id is not None else None
        raw_region = resource.get("region")
        region = text(raw_region) if isinstance(raw_region, str) else None
        if rid is None:
            raise CannotScan(f"record has no '{check.id_field}' field")
        status, details = check.func(resource, ctx)
        if status not in (PASS, FAIL, CANNOT_SCAN):
            raise CannotScan(f"check returned unknown status {text(status)!r}")
    except CannotScan as exc:
        status, details = CANNOT_SCAN, f"Cannot evaluate: {exc}"
        log.warning("%s on %s/%s: %s", check.check_id, account_id, rid, exc)
    except Exception as exc:  # a buggy check must never stop the scan
        status, details = CANNOT_SCAN, f"Cannot evaluate: internal error ({type(exc).__name__})"
        log.exception("%s crashed on %s/%s", check.check_id, account_id, rid)
    return Finding(
        check_id=check.check_id,
        title=check.title,
        provider=check.provider,
        account_id=account_id,
        region=region,
        resource_id=rid,
        status=status,
        severity=check.severity,
        details=details,
    )


def scan_account(
    account: dict[str, Any],
    ctx: ScanContext,
    checks: Iterable[Check] | None = None,
    sleep: bool = True,
) -> list[Finding]:
    """Scan one account: wait its latency, then run every check for its provider."""
    account_id = text(account.get("account_id"))
    provider = account.get("provider")
    if sleep:
        time.sleep(_latency_seconds(account))

    errors = account.get("errors") if isinstance(account.get("errors"), dict) else {}
    resources = account.get("resources") if isinstance(account.get("resources"), dict) else {}

    findings: list[Finding] = []
    for check in checks if checks is not None else CHECKS.values():
        if check.provider != provider:
            continue
        if check.collection in errors:
            findings.append(
                Finding(
                    check_id=check.check_id,
                    title=check.title,
                    provider=check.provider,
                    account_id=account_id,
                    region=None,
                    resource_id=None,
                    status=CANNOT_SCAN,
                    severity=check.severity,
                    details=f"Collection {check.collection} could not be read: "
                    f"{text(errors[check.collection])}",
                )
            )
            continue
        items = resources.get(check.collection)
        if items is None:
            continue  # missing from both resources and errors: nothing to scan
        if not isinstance(items, list):
            log.warning("account %s: %s is not a list", account_id, check.collection)
            findings.append(
                Finding(
                    check.check_id,
                    check.title,
                    check.provider,
                    account_id,
                    None,
                    None,
                    CANNOT_SCAN,
                    check.severity,
                    f"Collection {check.collection} is malformed (not a list)",
                )
            )
            continue
        findings.extend(_run_check(check, r, ctx, account_id) for r in items)
    return findings


def run_scan(
    inventory: dict[str, Any],
    selected: list[str] | None = None,
    workers: int | None = None,
    sleep: bool = True,
) -> list[Finding]:
    """Scan the selected accounts (all if None) concurrently and return all findings."""
    ctx = ScanContext(parse_time(inventory.get("snapshot_taken_at"), "snapshot_taken_at"))
    accounts = [
        a
        for a in inventory["accounts"]
        if isinstance(a, dict) and (selected is None or a.get("account_id") in selected)
    ]
    with ThreadPoolExecutor(max_workers=workers or worker_count()) as pool:
        results = pool.map(lambda a: scan_account(a, ctx, sleep=sleep), accounts)
        return [f for account_findings in results for f in account_findings]


# --------------------------------------------------------------------------- scoring


def score(findings: Iterable[Finding | dict[str, Any]]) -> float | None:
    """100 * PASS / (PASS + FAIL), one decimal; None when there's nothing to score."""
    counts = Counter(f["status"] if isinstance(f, dict) else f.status for f in findings)
    scored = counts[PASS] + counts[FAIL]
    return round(100 * counts[PASS] / scored, 1) if scored else None


# --------------------------------------------------------------------------- CLI


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    inventory = load_inventory()
    start = time.perf_counter()
    findings = run_scan(inventory)
    elapsed = time.perf_counter() - start
    for f in findings:
        if f.status != PASS:
            print(
                f"{f.status:<12} {f.severity:<8} {f.check_id:<11} {f.account_id:<38} "
                f"{f.resource_id or '-':<32} {f.details}"
            )
    counts = Counter(f.status for f in findings)
    print(
        f"\n{len(findings)} findings {dict(counts)}  score={score(findings)}  "
        f"took {elapsed:.2f}s with {worker_count()} workers"
    )


if __name__ == "__main__":
    main()
