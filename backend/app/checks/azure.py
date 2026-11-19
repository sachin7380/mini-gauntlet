"""Azure checks."""

from __future__ import annotations

from typing import Any

from .common import admin_ports_in, parse_port_spec, req_bool, req_dict, req_list, req_str, text
from .registry import FAIL, PASS, CannotScan, CheckResult, ScanContext, register

# Azure service tags / wildcards that mean "anyone on the internet".
OPEN_SOURCES = {"*", "internet", "any", "0.0.0.0/0", "::/0"}


@register(
    "AZ-STG-01",
    "Storage account blocks public blob access",
    "HIGH",
    "azure",
    "storage_accounts",
    "name",
)
def storage_blocks_public_blob(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    if req_bool(r, "allow_blob_public_access"):
        return FAIL, "Storage account has allow_blob_public_access set to true"
    return PASS, "Public blob access is disabled"


def _port_ranges(rule: dict[str, Any], label: str) -> list[tuple[int, int]]:
    """destination_ports may be '22', '22,3389', '3380-3400', '*' or a list of those."""
    raw = rule.get("destination_ports")
    if isinstance(raw, str):
        parts: list[Any] = raw.split(",")
    elif isinstance(raw, list):
        parts = raw
    else:
        raise CannotScan(f"{label} destination_ports is missing or invalid: {text(repr(raw))}")
    return [parse_port_spec(p) for p in parts]


@register(
    "AZ-NSG-01",
    "NSG doesn't expose SSH or RDP to the internet",
    "CRITICAL",
    "azure",
    "network_security_groups",
    "name",
)
def nsg_no_open_admin_ports(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    problems: list[str] = []
    for i, rule in enumerate(req_list(r, "rules")):
        rule = req_dict(rule, f"rule #{i + 1}")
        name = text(rule.get("name", f"#{i + 1}"))
        label = f"rule {name}"
        direction = req_str(rule, "direction").strip().lower()
        access = req_str(rule, "access").strip().lower()
        protocol = req_str(rule, "protocol").strip().lower()
        source = req_str(rule, "source").strip().lower()
        if direction != "inbound" or access != "allow":
            continue
        if protocol not in ("tcp", "*"):
            continue
        if source not in OPEN_SOURCES:
            continue
        ports = sorted({p for lo, hi in _port_ranges(rule, label) for p in admin_ports_in(lo, hi)})
        if ports:
            problems.append(
                f"{label} allows {', '.join(ports)} ({text(rule.get('protocol'))}, "
                f"ports {text(rule.get('destination_ports'))}) from source {text(rule.get('source'))}"
            )
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, "No inbound allow rule exposes SSH or RDP to the internet"
