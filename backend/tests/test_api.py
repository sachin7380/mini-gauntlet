"""API tests. Latency is switched off so a scan finishes instantly.

Note: Starlette's TestClient runs background tasks before the request returns,
so after POST /api/scans the scan is already COMPLETED in the database while
the response body still shows the RUNNING state the API returned.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

INVENTORY = Path(__file__).resolve().parents[2] / "data" / "inventory.json"
AZURE = "8f14e45f-ceea-4e7a-9d3b-2f6c1a0b7d21"
AWS_PROD = "123456789012"
AWS_DEV = "210987654321"


@pytest.fixture
def client(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        inventory_path=str(INVENTORY),
        simulate_latency=False,
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def scan_id(client):
    r = client.post("/api/scans")
    assert r.status_code == 202
    return r.json()["id"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_checks_catalog(client):
    checks = client.get("/api/checks").json()
    assert len(checks) == 10
    assert {"check_id": "AWS-IAM-02", "severity": "MEDIUM"}.items() <= next(
        c for c in checks if c["check_id"] == "AWS-IAM-02"
    ).items()


def test_start_scan_returns_running(client):
    r = client.post("/api/scans")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "RUNNING"
    assert body["finished_at"] is None
    assert body["score"] is None
    assert len(body["account_ids"]) == 4


def test_scan_completes_with_summary(client, scan_id):
    scan = client.get(f"/api/scans/{scan_id}").json()
    assert scan["status"] == "COMPLETED"
    assert scan["finished_at"] is not None
    assert scan["counts"] == {"PASS": 27, "FAIL": 18, "CANNOT_SCAN": 4}
    assert scan["score"] == 60.0
    assert scan["fail_by_severity"] == {"CRITICAL": 7, "HIGH": 8, "MEDIUM": 2, "LOW": 1}
    per_account = {a["account_id"]: a for a in scan["accounts"]}
    assert per_account[AWS_DEV]["score"] == 66.7  # 2 PASS, 1 FAIL
    assert per_account[AWS_DEV]["counts"]["CANNOT_SCAN"] == 4
    assert per_account[AZURE]["name"] == "example-corp-azure"


def test_scan_subset_of_accounts(client):
    r = client.post("/api/scans", json={"account_ids": [AZURE]})
    assert r.status_code == 202
    scan = client.get(f"/api/scans/{r.json()['id']}").json()
    assert scan["account_ids"] == [AZURE]
    assert [a["account_id"] for a in scan["accounts"]] == [AZURE]
    assert scan["counts"] == {"PASS": 4, "FAIL": 3, "CANNOT_SCAN": 0}


@pytest.mark.parametrize(
    "body",
    [{"account_ids": []}, {"account_ids": ["999999999999"]}, {"account_ids": [AZURE, "nope"]}],
)
def test_start_scan_422(client, body):
    assert client.post("/api/scans", json=body).status_code == 422
    assert client.get("/api/scans").json() == []  # nothing was created


def test_list_scans_newest_first(client):
    first = client.post("/api/scans", json={"account_ids": [AZURE]}).json()["id"]
    second = client.post("/api/scans").json()["id"]
    scans = client.get("/api/scans").json()
    assert [s["id"] for s in scans] == [second, first]
    assert scans[0]["counts"]["FAIL"] == 18
    assert scans[1]["score"] == 57.1  # Azure: 4 / 7


def test_unknown_scan_404(client):
    assert client.get("/api/scans/does-not-exist").status_code == 404
    assert client.get("/api/scans/does-not-exist/findings").status_code == 404


def test_findings_default_page_and_order(client, scan_id):
    page = client.get(f"/api/scans/{scan_id}/findings").json()
    assert page["total"] == 49
    assert page["page"] == 1 and page["page_size"] == 25
    assert len(page["items"]) == 25

    all_items = client.get(f"/api/scans/{scan_id}/findings", params={"page_size": 100}).json()["items"]
    status_rank = {"FAIL": 0, "CANNOT_SCAN": 1, "PASS": 2}
    sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    keys = [
        (status_rank[f["status"]], sev_rank[f["severity"]], f["check_id"], f["resource_id"] or "")
        for f in all_items
    ]
    assert keys == sorted(keys)
    assert all_items[0]["status"] == "FAIL" and all_items[0]["severity"] == "CRITICAL"
    assert set(all_items[0]) == {
        "id",
        "scan_id",
        "check_id",
        "title",
        "provider",
        "account_id",
        "region",
        "resource_id",
        "status",
        "severity",
        "details",
    }


def test_findings_pagination(client, scan_id):
    url = f"/api/scans/{scan_id}/findings"
    p1 = client.get(url, params={"page_size": 20, "page": 1}).json()["items"]
    p3 = client.get(url, params={"page_size": 20, "page": 3}).json()
    assert len(p1) == 20
    assert len(p3["items"]) == 9 and p3["total"] == 49
    beyond = client.get(url, params={"page": 99}).json()
    assert beyond["items"] == [] and beyond["total"] == 49


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}])
def test_findings_bad_paging_422(client, scan_id, params):
    assert client.get(f"/api/scans/{scan_id}/findings", params=params).status_code == 422


def test_findings_filters_case_insensitive(client, scan_id):
    url = f"/api/scans/{scan_id}/findings"
    fails = client.get(url, params={"status": "fail", "page_size": 100}).json()
    assert fails["total"] == 18 and all(f["status"] == "FAIL" for f in fails["items"])

    crit = client.get(url, params={"status": "FAIL", "severity": "critical"}).json()
    assert crit["total"] == 7

    gcp = client.get(url, params={"provider": "GCP", "page_size": 100}).json()
    assert gcp["total"] == 11 and {f["provider"] for f in gcp["items"]} == {"gcp"}

    az = client.get(url, params={"account_id": AZURE.upper()}).json()
    assert az["total"] == 7

    chk = client.get(url, params={"check_id": "aws-iam-02"}).json()
    assert chk["total"] == 7  # 6 users in prod + 1 CANNOT_SCAN for dev

    assert client.get(url, params={"status": "nonsense"}).json()["total"] == 0


def test_untrusted_strings_returned_as_plain_json(client, scan_id):
    items = client.get(
        f"/api/scans/{scan_id}/findings", params={"check_id": "GCP-VPC-01", "status": "FAIL"}
    ).json()["items"]
    assert [f["resource_id"] for f in items] == ["allow-rdp-anywhere"]
    assert "3389" in items[0]["details"] and "0.0.0.0/0" in items[0]["details"]


def test_scan_fails_when_inventory_unreadable(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'f.db'}",
        inventory_path=str(tmp_path / "missing.json"),
        simulate_latency=False,
    )
    with TestClient(app) as c:
        scan_id = c.post("/api/scans").json()["id"]
        scan = c.get(f"/api/scans/{scan_id}").json()
        assert scan["status"] == "FAILED"
        assert "cannot read inventory" in scan["error"]
        assert scan["score"] is None


def test_scans_survive_restart_and_running_marked_failed(tmp_path):
    db = f"sqlite:///{tmp_path / 'persist.db'}"
    with TestClient(create_app(db, str(INVENTORY), simulate_latency=False)) as c:
        scan_id = c.post("/api/scans").json()["id"]

    # Simulate a crash mid-scan: leave a RUNNING row behind.
    from app.db import RUNNING, ScanRow, make_sessionmaker, utcnow

    with make_sessionmaker(db).begin() as s:
        s.add(ScanRow(id="stuck", status=RUNNING, started_at=utcnow(), accounts=[]))

    with TestClient(create_app(db, str(INVENTORY), simulate_latency=False)) as c:
        assert c.get(f"/api/scans/{scan_id}").json()["status"] == "COMPLETED"
        stuck = c.get("/api/scans/stuck").json()
        assert stuck["status"] == "FAILED" and "restart" in stuck["error"]
