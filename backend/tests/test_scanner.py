"""Engine-level tests: registry, CANNOT_SCAN rules, concurrency, scoring.

Per-check PASS/FAIL edge cases live in test_checks.py (step 5).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.checks import CHECKS, ScanContext
from app.checks.registry import CANNOT_SCAN, FAIL, register
from app.scanner import Finding, InventoryError, load_inventory, run_scan, scan_account, score

INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory.json"


@pytest.fixture(scope="module")
def findings():
    return run_scan(load_inventory(INVENTORY), sleep=False)


def statuses(findings, status):
    return {(f.check_id, f.resource_id) for f in findings if f.status == status}


def test_all_ten_checks_registered():
    assert set(CHECKS) == {
        "AWS-S3-01",
        "AWS-EC2-01",
        "AWS-IAM-01",
        "AWS-IAM-02",
        "AWS-RDS-01",
        "AZ-STG-01",
        "AZ-NSG-01",
        "GCP-GCS-01",
        "GCP-GCS-02",
        "GCP-VPC-01",
    }


def test_expected_fails_on_real_inventory(findings):
    assert statuses(findings, FAIL) == {
        ("AWS-S3-01", "example-corp-public-downloads"),
        ("AWS-S3-01", "example-corp-logs"),
        ("AWS-S3-01", "example-corp-dev-scratch"),
        ("AWS-EC2-01", "sg-0a1b2c3d4e5f60002"),
        ("AWS-EC2-01", "sg-0a1b2c3d4e5f60003"),
        ("AWS-EC2-01", "sg-0a1b2c3d4e5f60004"),
        ("AWS-EC2-01", "sg-0a1b2c3d4e5f60006"),
        ("AWS-IAM-01", "bob"),
        ("AWS-IAM-02", "reporting-bot"),
        ("AWS-IAM-02", "legacy-etl"),
        ("AWS-RDS-01", "analytics-replica"),
        ("AZ-STG-01", "examplecorppublic"),
        ("AZ-NSG-01", "nsg-jumpbox"),
        ("AZ-NSG-01", "nsg-mgmt"),
        ("GCP-GCS-01", "example-corp-public-site"),
        ("GCP-GCS-01", "example-corp-partner-share"),
        ("GCP-GCS-02", "example-corp-ml-data"),
        ("GCP-VPC-01", "allow-rdp-anywhere"),
    }


def test_cannot_scan_on_real_inventory(findings):
    assert statuses(findings, CANNOT_SCAN) == {
        ("AWS-EC2-01", "sg-0b1c2d3e4f5a60002"),  # corrupt port
        ("AWS-IAM-01", None),  # iam_users: AccessDenied
        ("AWS-IAM-02", None),
        ("AWS-RDS-01", None),  # rds_instances: UnauthorizedOperation
    }
    errs = [f for f in findings if f.resource_id is None]
    assert all(f.account_id == "210987654321" for f in errs)
    assert any("AccessDenied" in f.details for f in errs)


def test_counts_and_score(findings):
    assert len(findings) == 49
    assert score(findings) == 60.0  # 27 / (27 + 18)


def test_score_none_when_nothing_scored():
    f = Finding("X", "t", "aws", "a", None, None, CANNOT_SCAN, "LOW", "d")
    assert score([f]) is None
    assert score([]) is None


def test_missing_collection_produces_no_findings():
    ctx_inv = {
        "snapshot_taken_at": "2026-10-01T00:00:00Z",
        "accounts": [{"provider": "aws", "account_id": "1", "errors": {}, "resources": {}}],
    }
    assert run_scan(ctx_inv, sleep=False) == []


def test_bad_record_and_crashing_check_do_not_stop_scan():
    @register("TEST-CRASH-01", "always crashes", "LOW", "testcloud", "things", "id")
    def crash(r, ctx):
        raise RuntimeError("boom")

    try:
        inv = {
            "snapshot_taken_at": "2026-10-01T00:00:00Z",
            "accounts": [
                {
                    "provider": "testcloud",
                    "account_id": "t1",
                    "resources": {"things": [{"id": "a"}, "not-a-dict", {"id": "c"}]},
                }
            ],
        }
        out = run_scan(inv, sleep=False)
        assert [f.status for f in out] == [CANNOT_SCAN] * 3
        assert [f.resource_id for f in out] == ["a", None, "c"]
    finally:
        del CHECKS["TEST-CRASH-01"]


def test_selected_accounts_only():
    out = run_scan(load_inventory(INVENTORY), selected=["8f14e45f-ceea-4e7a-9d3b-2f6c1a0b7d21"], sleep=False)
    assert {f.provider for f in out} == {"azure"}


def test_accounts_scanned_concurrently():
    inv = load_inventory(INVENTORY)
    start = time.perf_counter()
    run_scan(inv, workers=4)
    elapsed = time.perf_counter() - start
    assert 2.9 <= elapsed < 4.5  # longest latency is 3s; serial would be 8s


def test_scan_is_deterministic():
    inv = load_inventory(INVENTORY)
    a = [f.to_dict() for f in run_scan(inv, sleep=False)]
    b = [f.to_dict() for f in run_scan(inv, sleep=False)]
    assert a == b


def test_load_inventory_errors(tmp_path):
    with pytest.raises(InventoryError):
        load_inventory(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(InventoryError):
        load_inventory(bad)
    bad.write_text(json.dumps({"accounts": []}))  # no snapshot time
    with pytest.raises(InventoryError):
        load_inventory(bad)


def test_details_strip_control_chars_and_truncate():
    ctx = ScanContext(datetime(2026, 10, 1, tzinfo=timezone.utc))
    acct = {
        "provider": "azure",
        "account_id": "a",
        "resources": {
            "storage_accounts": [{"name": "evil\nname" + "x" * 500, "allow_blob_public_access": "yes"}]
        },
    }
    [f] = scan_account(acct, ctx, sleep=False)
    assert f.status == CANNOT_SCAN
    assert "\n" not in f.resource_id and len(f.resource_id) <= 200
