"""Google Cloud checks."""

from __future__ import annotations

from typing import Any

from .common import (
    admin_ports_in,
    is_open_cidr,
    parse_port_spec,
    req_bool,
    req_dict,
    req_list,
    req_str,
    text,
)
from .registry import FAIL, PASS, CannotScan, CheckResult, ScanContext, register

PUBLIC_MEMBERS = {"allUsers", "allAuthenticatedUsers"}


@register("GCP-GCS-01", "Bucket isn't public", "HIGH", "gcp", "gcs_buckets", "name")
def gcs_not_public(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    public: list[str] = []
    for i, binding in enumerate(req_list(r, "iam_bindings")):
        binding = req_dict(binding, f"IAM binding #{i + 1}")
        role = text(binding.get("role", "?"))
        for member in req_list(binding, "members"):
            if member in PUBLIC_MEMBERS:
                public.append(f"{member} has {role}")
    if public:
        return FAIL, "Bucket is public: " + "; ".join(public)
    return PASS, "No IAM binding grants access to allUsers or allAuthenticatedUsers"


@register(
    "GCP-GCS-02",
    "Bucket uses uniform bucket-level access",
    "LOW",
    "gcp",
    "gcs_buckets",
    "name",
)
def gcs_uniform_access(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    if not req_bool(r, "uniform_bucket_level_access"):
        return FAIL, "Uniform bucket-level access is disabled (per-object ACLs are allowed)"
    return PASS, "Uniform bucket-level access is enabled"


@register(
    "GCP-VPC-01",
    "Firewall rule doesn't expose SSH or RDP to the internet",
    "CRITICAL",
    "gcp",
    "firewall_rules",
    "name",
)
def firewall_no_open_admin_ports(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    # GCP defaults: direction INGRESS, disabled false.
    direction = req_str(r, "direction").strip().upper() if "direction" in r else "INGRESS"
    disabled = req_bool(r, "disabled") if "disabled" in r else False
    if direction != "INGRESS":
        return PASS, f"Rule direction is {text(direction)}, not INGRESS"
    if disabled:
        return PASS, "Rule is disabled"

    open_sources = [s for s in req_list(r, "source_ranges") if is_open_cidr(s)]
    if not open_sources:
        return PASS, "Rule does not allow traffic from the whole internet"

    exposed: set[str] = set()
    for i, allowed in enumerate(req_list(r, "allowed")):
        allowed = req_dict(allowed, f"allowed entry #{i + 1}")
        protocol = req_str(allowed, "IPProtocol").strip().lower()
        if protocol not in ("tcp", "all", "6"):
            continue
        ports = allowed.get("ports")
        if ports is None:  # no ports listed = every port
            ranges = [(0, 65535)]
        else:
            if not isinstance(ports, list):
                raise CannotScan(f"allowed entry #{i + 1} ports must be a list")
            ranges = [parse_port_spec(p) for p in ports]
        for lo, hi in ranges:
            exposed.update(admin_ports_in(lo, hi))

    if exposed:
        return FAIL, (
            f"Firewall rule {text(r.get('name'))} allows {', '.join(sorted(exposed))} "
            f"from {', '.join(text(s) for s in open_sources)}"
        )
    return PASS, "Rule does not expose SSH or RDP"
