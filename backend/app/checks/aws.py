"""AWS checks."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .common import (
    admin_ports_in,
    is_open_cidr,
    parse_time,
    port_int,
    req_bool,
    req_dict,
    req_list,
    req_str,
    text,
)
from .registry import FAIL, PASS, CannotScan, CheckResult, ScanContext, register

PAB_FLAGS = (
    "block_public_acls",
    "ignore_public_acls",
    "block_public_policy",
    "restrict_public_buckets",
)
MAX_KEY_AGE = timedelta(days=90)


@register("AWS-S3-01", "S3 bucket blocks public access", "HIGH", "aws", "s3_buckets", "name")
def s3_blocks_public_access(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    pab = r.get("public_access_block")
    if pab is None:
        return FAIL, "No public access block is configured on the bucket"
    pab = req_dict(pab, "public_access_block")
    off = [flag for flag in PAB_FLAGS if not req_bool(pab, flag)]
    if off:
        return FAIL, f"Public access block settings disabled: {', '.join(off)}"
    return PASS, "All four public access block settings are enabled"


@register(
    "AWS-EC2-01",
    "Security group doesn't expose SSH or RDP to the internet",
    "CRITICAL",
    "aws",
    "security_groups",
    "group_id",
)
def sg_no_open_admin_ports(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    problems: list[str] = []
    for i, rule in enumerate(req_list(r, "ingress")):
        rule = req_dict(rule, f"ingress rule #{i + 1}")
        protocol = req_str(rule, "protocol").strip().lower()
        if protocol in ("-1", "all"):
            lo, hi, proto_label = 0, 65535, "all traffic"
        elif protocol in ("tcp", "6"):
            lo = port_int(rule.get("from_port"), f"ingress rule #{i + 1} from_port")
            hi = port_int(rule.get("to_port"), f"ingress rule #{i + 1} to_port")
            if lo > hi:
                raise CannotScan(f"ingress rule #{i + 1} has from_port {lo} > to_port {hi}")
            proto_label = f"tcp {lo}-{hi}" if lo != hi else f"tcp/{lo}"
        else:
            continue  # SSH and RDP are TCP; udp/icmp rules can't expose them
        ports = admin_ports_in(lo, hi)
        if not ports:
            continue
        open_cidrs = [c for c in req_list(rule, "cidrs") if is_open_cidr(c)]
        if open_cidrs:
            problems.append(
                f"ingress rule #{i + 1} ({proto_label}) allows {', '.join(ports)} "
                f"from {', '.join(text(c) for c in open_cidrs)}"
            )
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, "No ingress rule exposes SSH or RDP to the internet"


@register("AWS-IAM-01", "Console users have MFA", "HIGH", "aws", "iam_users", "user_name")
def iam_console_mfa(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    console = req_bool(r, "console_access")
    mfa = req_bool(r, "mfa_enabled")
    if not console:
        return PASS, "User has no console access"
    if not mfa:
        return FAIL, "User has console access but MFA is not enabled"
    return PASS, "Console user has MFA enabled"


@register(
    "AWS-IAM-02",
    "No active access key is older than 90 days",
    "MEDIUM",
    "aws",
    "iam_users",
    "user_name",
)
def iam_key_age(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    old: list[str] = []
    for i, key in enumerate(req_list(r, "access_keys")):
        key = req_dict(key, f"access key #{i + 1}")
        key_id = text(key.get("key_id", f"#{i + 1}"))
        status = req_str(key, "status").strip().lower()
        created = parse_time(key.get("created_at"), f"access key {key_id} created_at")
        if status != "active":
            continue
        age = ctx.snapshot_taken_at - created
        if age > MAX_KEY_AGE:
            old.append(f"{key_id} is {age.days} days old")
    if old:
        return FAIL, "Active access key older than 90 days: " + "; ".join(old)
    return PASS, "No active access key is older than 90 days"


@register(
    "AWS-RDS-01",
    "RDS instance isn't publicly accessible",
    "HIGH",
    "aws",
    "rds_instances",
    "db_instance_id",
)
def rds_not_public(r: dict[str, Any], ctx: ScanContext) -> CheckResult:
    if req_bool(r, "publicly_accessible"):
        return FAIL, "RDS instance has publicly_accessible set to true"
    return PASS, "RDS instance is not publicly accessible"
