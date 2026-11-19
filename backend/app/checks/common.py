"""Strict field readers and port/CIDR helpers shared by the checks.

Every value comes from a customer's cloud, so nothing is trusted: a field with
the wrong type raises CannotScan instead of being guessed at.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from typing import Any

from .registry import CannotScan

ADMIN_PORTS = {22: "SSH", 3389: "RDP"}
MAX_TEXT = 200


def text(value: Any) -> str:
    """Make an untrusted value safe to put in a details string."""
    s = "".join(ch if ch.isprintable() else "?" for ch in str(value))
    return s if len(s) <= MAX_TEXT else s[: MAX_TEXT - 3] + "..."


def req_bool(obj: dict[str, Any], key: str) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        raise CannotScan(f"field '{key}' must be true/false, got {text(repr(value))}")
    return value


def req_str(obj: dict[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise CannotScan(f"field '{key}' must be a string, got {text(repr(value))}")
    return value


def req_list(obj: dict[str, Any], key: str) -> list[Any]:
    value = obj.get(key)
    if not isinstance(value, list):
        raise CannotScan(f"field '{key}' must be a list, got {text(repr(value))}")
    return value


def req_dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CannotScan(f"{what} must be an object, got {text(repr(value))}")
    return value


def port_int(value: Any, what: str) -> int:
    """A port must be a real int (not bool, not a string) in 0..65535."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CannotScan(f"{what} is not a number: {text(repr(value))}")
    if not 0 <= value <= 65535:
        raise CannotScan(f"{what} is out of range: {value}")
    return value


def parse_port_spec(spec: Any) -> tuple[int, int]:
    """Parse '22', '8000-9000' or '*' into an inclusive (low, high) range."""
    if isinstance(spec, bool) or not isinstance(spec, (str, int)):
        raise CannotScan(f"port {text(repr(spec))} is not a number or range")
    s = str(spec).strip()
    if s == "*":
        return 0, 65535
    lo_s, sep, hi_s = s.partition("-")
    try:
        lo = int(lo_s)
        hi = int(hi_s) if sep else lo
    except ValueError:
        raise CannotScan(f"port {text(repr(spec))} is not a number or range") from None
    if not (0 <= lo <= hi <= 65535):
        raise CannotScan(f"port range {text(s)} is invalid")
    return lo, hi


def admin_ports_in(lo: int, hi: int) -> list[str]:
    """Return labels like 'SSH/22' for admin ports inside lo..hi."""
    return [f"{name}/{port}" for port, name in ADMIN_PORTS.items() if lo <= port <= hi]


def is_open_cidr(value: Any) -> bool:
    """True for 0.0.0.0/0 and ::/0 (any spelling); CannotScan if unparseable."""
    if not isinstance(value, str):
        raise CannotScan(f"CIDR {text(repr(value))} is not a string")
    try:
        return ipaddress.ip_network(value.strip(), strict=False).prefixlen == 0
    except ValueError:
        raise CannotScan(f"CIDR {text(repr(value))} is not valid") from None


def parse_time(value: Any, what: str) -> datetime:
    """Parse an ISO 8601 timestamp; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise CannotScan(f"{what} is not a timestamp: {text(repr(value))}")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise CannotScan(f"{what} is not a valid timestamp: {text(repr(value))}") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
