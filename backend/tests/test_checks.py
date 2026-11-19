"""Per-check tests: PASS, FAIL, CANNOT_SCAN and the catalog's edge cases.

Each test runs one check on one hand-built resource through the real engine
(_run_check), so malformed input is converted to CANNOT_SCAN exactly as in a scan.
"""

from datetime import datetime, timezone

import pytest

from app.checks import CHECKS, ScanContext
from app.scanner import _run_check

CTX = ScanContext(datetime(2026, 10, 1, tzinfo=timezone.utc))


def run(check_id, resource):
    f = _run_check(CHECKS[check_id], resource, CTX, "acct")
    return f.status, f.details


# --------------------------------------------------------------------------- AWS-S3-01

ALL_ON = dict.fromkeys(
    ["block_public_acls", "ignore_public_acls", "block_public_policy", "restrict_public_buckets"], True
)


def s3(pab):
    return {"name": "b", "region": "us-east-1", "public_access_block": pab}


def test_s3_pass():
    assert run("AWS-S3-01", s3(ALL_ON))[0] == "PASS"


@pytest.mark.parametrize("flag", list(ALL_ON))
def test_s3_fail_names_disabled_flag(flag):
    status, details = run("AWS-S3-01", s3({**ALL_ON, flag: False}))
    assert status == "FAIL" and flag in details


def test_s3_fail_when_no_block():
    status, details = run("AWS-S3-01", s3(None))
    assert status == "FAIL" and "No public access block" in details


@pytest.mark.parametrize("pab", [{**ALL_ON, "block_public_acls": "true"}, "yes", {}])
def test_s3_cannot_scan_malformed(pab):
    assert run("AWS-S3-01", s3(pab))[0] == "CANNOT_SCAN"


# --------------------------------------------------------------------------- AWS-EC2-01


def sg(*rules):
    return {"group_id": "sg-1", "region": "us-east-1", "ingress": list(rules)}


def rule(protocol="tcp", lo=22, hi=22, cidrs=("0.0.0.0/0",)):
    return {"protocol": protocol, "from_port": lo, "to_port": hi, "cidrs": list(cidrs)}


@pytest.mark.parametrize(
    "r",
    [
        rule(lo=443, hi=443),  # web port
        rule(cidrs=["203.0.113.0/24"]),  # SSH but not from the internet
        rule(protocol="udp", lo=0, hi=65535),  # udp can't carry SSH/RDP
        rule(lo=23, hi=3388),  # range stops just short of 3389
        rule(lo=3390, hi=4000),
    ],
)
def test_ec2_pass(r):
    assert run("AWS-EC2-01", sg(r))[0] == "PASS"


def test_ec2_pass_no_rules():
    assert run("AWS-EC2-01", sg())[0] == "PASS"


@pytest.mark.parametrize(
    "r, expect",
    [
        (rule(), "SSH/22"),
        (rule(lo=3389, hi=3389), "RDP/3389"),
        (rule(lo=3000, hi=3500), "RDP/3389"),  # port range containing 3389
        (rule(lo=0, hi=65535), "SSH/22, RDP/3389"),
        (rule(cidrs=["::/0"]), "::/0"),  # IPv6 any
        (rule(protocol="-1", lo=None, hi=None), "all traffic"),  # all protocols, null ports
        (rule(protocol="6"), "SSH/22"),  # protocol number for tcp
    ],
)
def test_ec2_fail(r, expect):
    status, details = run("AWS-EC2-01", sg(r))
    assert status == "FAIL" and expect in details


def test_ec2_fail_details_name_port_and_source():
    status, details = run("AWS-EC2-01", sg(rule(lo=443, hi=443), rule(cidrs=["10.0.0.0/8", "0.0.0.0/0"])))
    assert status == "FAIL"
    assert "rule #2" in details and "SSH/22" in details and "0.0.0.0/0" in details
    assert "10.0.0.0/8" not in details


@pytest.mark.parametrize(
    "r",
    [
        rule(lo="twenty-two"),  # the corrupt record from the inventory
        rule(lo=True, hi=True),  # bools are not ports
        rule(lo=30, hi=20),  # inverted range
        rule(lo=-1, hi=22),
        rule(cidrs=["not-a-cidr"]),
    ],
)
def test_ec2_cannot_scan(r):
    status, details = run("AWS-EC2-01", sg(r))
    assert status == "CANNOT_SCAN" and details.startswith("Cannot evaluate")


def test_ec2_cannot_scan_ingress_not_list():
    assert run("AWS-EC2-01", {"group_id": "sg-1", "ingress": "open"})[0] == "CANNOT_SCAN"


# --------------------------------------------------------------------------- AWS-IAM-01


def user(console, mfa, keys=()):
    return {"user_name": "u", "console_access": console, "mfa_enabled": mfa, "access_keys": list(keys)}


@pytest.mark.parametrize("console, mfa", [(True, True), (False, False), (False, True)])
def test_iam_mfa_pass(console, mfa):
    assert run("AWS-IAM-01", user(console, mfa))[0] == "PASS"


def test_iam_mfa_fail():
    status, details = run("AWS-IAM-01", user(True, False))
    assert status == "FAIL" and "MFA" in details


@pytest.mark.parametrize("console, mfa", [("true", False), (True, None), (None, None)])
def test_iam_mfa_cannot_scan(console, mfa):
    assert run("AWS-IAM-01", user(console, mfa))[0] == "CANNOT_SCAN"


# --------------------------------------------------------------------------- AWS-IAM-02


def key(created, status="Active", kid="k1"):
    return {"key_id": kid, "status": status, "created_at": created}


@pytest.mark.parametrize(
    "keys",
    [
        [],
        [key("2026-09-01T00:00:00Z")],
        [key("2026-07-03T00:00:00Z")],  # exactly 90 days old: not "older than"
        [key("2020-01-01T00:00:00Z", status="Inactive")],  # old but inactive
        [key("2026-07-03T00:00:00")],  # naive timestamp treated as UTC
    ],
)
def test_iam_key_pass(keys):
    assert run("AWS-IAM-02", user(False, False, keys))[0] == "PASS"


@pytest.mark.parametrize(
    "created, days",
    [("2026-07-02T00:00:00Z", 91), ("2026-07-02T23:59:59Z", 90), ("2025-11-15T00:00:00Z", 320)],
)
def test_iam_key_fail(created, days):
    # 90 days and 1 second is still older than 90 days.
    status, details = run("AWS-IAM-02", user(False, False, [key(created, kid="old-key")]))
    assert status == "FAIL" and "old-key" in details and f"{days} days" in details


def test_iam_key_fail_only_lists_active_old_keys():
    keys = [key("2025-01-01T00:00:00Z", kid="a"), key("2024-01-01T00:00:00Z", "Inactive", "b")]
    status, details = run("AWS-IAM-02", user(False, False, keys))
    assert status == "FAIL" and "a is" in details and "b is" not in details


def test_iam_key_uses_snapshot_time_not_clock():
    # Relative to "now" (late 2026+) this key is old; relative to the snapshot it's 1 day old.
    assert run("AWS-IAM-02", user(False, False, [key("2026-09-30T00:00:00Z")]))[0] == "PASS"


@pytest.mark.parametrize(
    "keys", [[key("yesterday")], [key(None)], [{"key_id": "k", "created_at": "2026-01-01T00:00:00Z"}], "none"]
)
def test_iam_key_cannot_scan(keys):
    r = user(False, False)
    r["access_keys"] = keys
    assert run("AWS-IAM-02", r)[0] == "CANNOT_SCAN"


# --------------------------------------------------------------------------- AWS-RDS-01


@pytest.mark.parametrize(
    "value, expected", [(False, "PASS"), (True, "FAIL"), ("false", "CANNOT_SCAN"), (None, "CANNOT_SCAN")]
)
def test_rds(value, expected):
    assert run("AWS-RDS-01", {"db_instance_id": "db", "publicly_accessible": value})[0] == expected


# --------------------------------------------------------------------------- AZ-STG-01


@pytest.mark.parametrize("value, expected", [(False, "PASS"), (True, "FAIL"), (1, "CANNOT_SCAN")])
def test_storage(value, expected):
    assert run("AZ-STG-01", {"name": "s", "allow_blob_public_access": value})[0] == expected


# --------------------------------------------------------------------------- AZ-NSG-01


def nsg(*rules):
    return {"name": "nsg", "region": "centralindia", "rules": list(rules)}


def az_rule(direction="Inbound", access="Allow", protocol="Tcp", source="Internet", ports="22", name="r1"):
    return {
        "name": name,
        "direction": direction,
        "access": access,
        "protocol": protocol,
        "source": source,
        "destination_ports": ports,
    }


@pytest.mark.parametrize(
    "r",
    [
        az_rule(ports="443"),
        az_rule(access="Deny"),  # Deny rules never expose
        az_rule(direction="Outbound", source="*"),  # Outbound rules don't count
        az_rule(source="10.0.0.0/8"),
        az_rule(source="VirtualNetwork"),
        az_rule(protocol="Udp", ports="*"),
        az_rule(ports="3380-3388"),
    ],
)
def test_nsg_pass(r):
    assert run("AZ-NSG-01", nsg(r))[0] == "PASS"


def test_nsg_pass_deny_and_outbound_together():
    rules = [
        az_rule(access="Deny", name="deny-ssh-internet"),
        az_rule(direction="Outbound", source="*", name="allow-ssh-out"),
    ]
    assert run("AZ-NSG-01", nsg(*rules))[0] == "PASS"


@pytest.mark.parametrize(
    "r, expect",
    [
        (az_rule(source="*"), "SSH/22"),
        (az_rule(source="Internet"), "SSH/22"),
        (az_rule(source="0.0.0.0/0", protocol="*", ports="3380-3400"), "RDP/3389"),  # range
        (az_rule(source="Any", ports="*"), "RDP/3389"),
        (az_rule(ports="80,443,3389"), "RDP/3389"),  # comma list
        (az_rule(ports=["443", "20-25"]), "SSH/22"),  # list form
        (az_rule(source="::/0"), "SSH/22"),
        (az_rule(direction="inbound", access="allow", protocol="tcp", source="internet"), "SSH/22"),
    ],
)
def test_nsg_fail(r, expect):
    status, details = run("AZ-NSG-01", nsg(r))
    assert status == "FAIL" and expect in details and "rule r1" in details


@pytest.mark.parametrize("r", [az_rule(ports="twenty-two"), az_rule(ports=None), az_rule(direction=None)])
def test_nsg_cannot_scan(r):
    assert run("AZ-NSG-01", nsg(r))[0] == "CANNOT_SCAN"


# --------------------------------------------------------------------------- GCP-GCS-01 / 02


def bucket(members=("group:eng@example.com",), uniform=True):
    return {
        "name": "b",
        "uniform_bucket_level_access": uniform,
        "iam_bindings": [{"role": "roles/storage.objectViewer", "members": list(members)}],
    }


def test_gcs_public_pass():
    assert run("GCP-GCS-01", bucket())[0] == "PASS"
    assert run("GCP-GCS-01", {"name": "b", "iam_bindings": []})[0] == "PASS"


@pytest.mark.parametrize("member", ["allUsers", "allAuthenticatedUsers"])
def test_gcs_public_fail(member):
    status, details = run("GCP-GCS-01", bucket([member, "user:x@example.com"]))
    assert status == "FAIL" and member in details and "objectViewer" in details


@pytest.mark.parametrize("bindings", [None, "public", [{"role": "r", "members": "allUsers"}]])
def test_gcs_public_cannot_scan(bindings):
    assert run("GCP-GCS-01", {"name": "b", "iam_bindings": bindings})[0] == "CANNOT_SCAN"


@pytest.mark.parametrize("value, expected", [(True, "PASS"), (False, "FAIL"), (None, "CANNOT_SCAN")])
def test_gcs_uniform(value, expected):
    assert run("GCP-GCS-02", bucket(uniform=value))[0] == expected


# --------------------------------------------------------------------------- GCP-VPC-01


def fw(direction="INGRESS", disabled=False, sources=("0.0.0.0/0",), allowed=None):
    r = {"name": "fw", "region": "global", "direction": direction, "disabled": disabled}
    r["source_ranges" if direction == "INGRESS" else "destination_ranges"] = list(sources)
    r["allowed"] = allowed if allowed is not None else [{"IPProtocol": "tcp", "ports": ["22"]}]
    return r


@pytest.mark.parametrize(
    "r",
    [
        fw(sources=["35.235.240.0/20"]),  # IAP range only
        fw(disabled=True, allowed=[{"IPProtocol": "all"}]),  # disabled rule
        fw(direction="EGRESS"),  # egress rule
        fw(allowed=[{"IPProtocol": "tcp", "ports": ["8000-9000"]}]),
        fw(allowed=[{"IPProtocol": "udp"}]),
        fw(allowed=[{"IPProtocol": "icmp"}]),
    ],
)
def test_vpc_pass(r):
    assert run("GCP-VPC-01", r)[0] == "PASS"


@pytest.mark.parametrize(
    "r, expect",
    [
        (fw(), "SSH/22"),
        (fw(allowed=[{"IPProtocol": "tcp", "ports": ["3389"]}]), "RDP/3389"),
        (fw(allowed=[{"IPProtocol": "tcp", "ports": ["3000-4000"]}]), "RDP/3389"),  # range
        (fw(allowed=[{"IPProtocol": "all"}]), "RDP/3389, SSH/22"),  # no ports = every port
        (fw(allowed=[{"IPProtocol": "tcp"}]), "SSH/22"),
        (fw(sources=["::/0"]), "::/0"),
        (fw(sources=["10.0.0.0/8", "0.0.0.0/0"]), "0.0.0.0/0"),
    ],
)
def test_vpc_fail(r, expect):
    status, details = run("GCP-VPC-01", r)
    assert status == "FAIL" and expect in details and "fw" in details


def test_vpc_defaults_to_ingress_enabled():
    r = fw()
    del r["direction"], r["disabled"]
    assert run("GCP-VPC-01", r)[0] == "FAIL"


@pytest.mark.parametrize(
    "r",
    [
        fw(allowed=[{"IPProtocol": "tcp", "ports": ["ssh"]}]),
        fw(allowed=[{"IPProtocol": "tcp", "ports": "22"}]),
        fw(disabled="no"),
        fw(sources=["nowhere"]),
        {"name": "fw", "direction": "INGRESS", "disabled": False},  # missing source_ranges
    ],
)
def test_vpc_cannot_scan(r):
    assert run("GCP-VPC-01", r)[0] == "CANNOT_SCAN"


def test_vpc_html_description_is_ignored_not_executed():
    r = fw(allowed=[{"IPProtocol": "tcp", "ports": ["3389"]}])
    r["description"] = "<img src=x onerror=alert('x')>"
    status, details = run("GCP-VPC-01", r)
    assert status == "FAIL" and "<img" not in details


# --------------------------------------------------------------------------- generic


@pytest.mark.parametrize("check_id", sorted(CHECKS))
def test_every_check_handles_non_object_and_missing_id(check_id):
    assert run(check_id, "garbage")[0] == "CANNOT_SCAN"
    assert run(check_id, {})[0] == "CANNOT_SCAN"
