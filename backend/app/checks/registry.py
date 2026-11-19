"""Check registry.

Adding a check = write one function in any module of this package and decorate
it with @register(...). Modules are imported automatically (see __init__.py),
so nothing else needs editing.

A check function receives (resource, ctx) and returns (status, details).
It may raise CannotScan (or any exception) when the record can't be evaluated;
the scanner turns that into a CANNOT_SCAN finding.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
CANNOT_SCAN = "CANNOT_SCAN"

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


class CannotScan(Exception):
    """Raised by a check when a resource's fields can't be evaluated."""


@dataclass(frozen=True)
class ScanContext:
    snapshot_taken_at: datetime


CheckResult = tuple[str, str]
CheckFunc = Callable[[dict[str, Any], ScanContext], CheckResult]


@dataclass(frozen=True)
class Check:
    check_id: str
    title: str
    severity: str
    provider: str
    collection: str
    id_field: str
    func: CheckFunc

    def to_dict(self) -> dict[str, str]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "severity": self.severity,
            "provider": self.provider,
            "collection": self.collection,
            "resource_id_field": self.id_field,
        }


CHECKS: dict[str, Check] = {}


def register(
    check_id: str,
    title: str,
    severity: str,
    provider: str,
    collection: str,
    id_field: str,
) -> Callable[[CheckFunc], CheckFunc]:
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity {severity!r} for {check_id}")

    def decorator(func: CheckFunc) -> CheckFunc:
        if check_id in CHECKS:
            raise ValueError(f"duplicate check id {check_id}")
        CHECKS[check_id] = Check(check_id, title, severity, provider, collection, id_field, func)
        return func

    return decorator
