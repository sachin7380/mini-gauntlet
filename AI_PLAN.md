# Mini Gauntlet: AI Build Plan

Short guide for an AI coding assistant building the Mini Posture Scanner assignment.
Work through the steps in order. After each step, run the tests before you move on.

---

## 1. Goal

Build a cloud posture scanner that:
- reads `data/inventory.json` (do **not** edit this file)
- runs 10 security checks on 4 accounts (AWS, Azure, GCP)
- stores scans and findings in SQLite and serves them through a FastAPI API
- shows the results in a React + TypeScript dashboard
- starts with `docker compose up --build` and is tested in GitHub Actions CI

---

## 2. Tech stack

| Part      | Choice |
|-----------|--------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy, SQLite |
| Frontend  | React 18, TypeScript, Vite |
| Tests     | pytest + httpx (API), Vitest + React Testing Library (UI) |
| Lint      | Ruff, ESLint, `tsc --noEmit` |
| Infra     | Docker, docker compose, GitHub Actions |

---

## 3. Folder layout

```
assignment/
├── data/inventory.json
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app + routes
│   │   ├── db.py            # SQLite models (Scan, Finding)
│   │   ├── scanner.py       # runs checks on accounts concurrently
│   │   └── checks/
│   │       ├── registry.py  # @register decorator + CHECKS list
│   │       ├── aws.py  azure.py  gcp.py
│   ├── tests/
│   ├── Dockerfile  .dockerignore  pyproject.toml
├── frontend/
│   ├── src/ (pages/ScansPage.tsx, pages/ScanPage.tsx, api.ts)
│   ├── Dockerfile  .dockerignore  nginx.conf
├── docker-compose.yml
├── .github/workflows/ci.yml
├── README.md
└── DEPLOY.md
```

---

## 4. Build steps

### Step 1: Scanner engine
- **Registry:** each check is a function that has a `@register(check_id, title, severity, provider, collection, id_field)` decorator. A new check needs only one new function.
- **Check signature:** `check(resource, ctx) -> (status, details)`. `ctx` holds `snapshot_taken_at`.
- **Per account:** first `sleep(simulated_latency_ms)`, then for every check of that provider:
  - collection is in `errors` → one CANNOT_SCAN finding with the error code in details and no resource_id
  - collection is missing from both → no findings
  - otherwise → one finding per resource. Wrap each call in `try/except`: on a bad field, log a warning and return CANNOT_SCAN.
- **Concurrency:** `ThreadPoolExecutor(max_workers=SCAN_WORKERS or 4)`. The whole scan should take about 3 s, not 8 s.
- Read the file path from `INVENTORY_PATH`.
- **Score:** `round(100 * PASS / (PASS + FAIL), 1)`. If PASS + FAIL = 0, the score is `None`.

### Step 2: The 10 checks (rules + edge cases)

| Check | FAIL when |
|-------|-----------|
| AWS-S3-01 | `public_access_block` is null, or any of its 4 flags is false |
| AWS-EC2-01 | ingress from `0.0.0.0/0` or `::/0`, protocol `tcp` or `-1`, and the port range covers 22 or 3389 (`-1` means all ports). A non-numeric port → CANNOT_SCAN |
| AWS-IAM-01 | `console_access` is true and `mfa_enabled` is false |
| AWS-IAM-02 | any **Active** key is **more than** 90 days older than the snapshot (exactly 90 days → PASS) |
| AWS-RDS-01 | `publicly_accessible` is true |
| AZ-STG-01 | `allow_blob_public_access` is true |
| AZ-NSG-01 | an Inbound + Allow rule, source `*` / `Internet` / `Any` / `0.0.0.0/0` / `::/0`, protocol Tcp or `*`, and ports (`*`, a range or a list) cover 22 or 3389 |
| GCP-GCS-01 | any binding member is `allUsers` or `allAuthenticatedUsers` |
| GCP-GCS-02 | `uniform_bucket_level_access` is false |
| GCP-VPC-01 | INGRESS, not disabled, source `0.0.0.0/0` or `::/0`, protocol tcp or all, and ports (none listed = all) cover 22 or 3389 |

FAIL `details` must name the rule, port and source, for example `rule allow-rdp-anywhere opens tcp/3389 to 0.0.0.0/0`.

### Step 3: REST API
- Tables: `scans(id, status, started_at, finished_at, account_ids)` and `findings(id, scan_id, check_id, title, provider, account_id, region, resource_id, status, severity, details)`.
- `POST /api/scans` → validate `account_ids` (an empty list or an unknown ID returns 422) → save the scan as RUNNING → run it with `BackgroundTasks` → set COMPLETED, or FAILED if the scan crashes.
- Endpoints: `/api/health`, `/api/checks`, `/api/scans` (GET/POST), `/api/scans/{id}` (404 if unknown), `/api/scans/{id}/findings`.
- Findings: filters are case-insensitive, `page_size` is at most 100, and results are sorted FAIL → CANNOT_SCAN → PASS, then by severity, then by check_id, then by resource_id.
- Enable CORS for `http://localhost:3000`.

### Step 4: Dashboard
- **Scans page:** a table of scans (status, local start time, duration, score or "N/A") and a **Run scan** button. While any scan is RUNNING, poll every 1.5 s.
- **Scan page:** the score, counts by status, FAIL counts by severity, the score per account, and the findings table with filters and pagination.
- Add loading, empty and error states (including "API is down").
- **Security:** render text only as `{value}`, and never use `dangerouslySetInnerHTML`. The inventory contains an `<img onerror>` payload on purpose.

### Step 5: Tests
- pytest: PASS, FAIL and CANNOT_SCAN for every check, plus these edge cases: port ranges, `::/0`, Deny rules, Outbound rules, disabled rules, and a key exactly 90 days old.
- API tests: start a scan, read it, filter, paginate, and get 404 and 422.
- Vitest: at least 2 component tests (for example, the scans table renders, and the error state shows when fetch fails).

### Step 6: Docker
- Backend: `python:3.12-slim` (pinned), a non-root user, `HEALTHCHECK` on `/api/health`, port 8000.
- Frontend: a multi-stage build (`node:20-alpine` build → `nginx:alpine` serve), non-root, port 3000.
- Compose: both services, plus a named volume for the SQLite file, with `data/` mounted read-only.

### Step 7: CI (`.github/workflows/ci.yml`)
Run on every push and pull request: Ruff → pytest → ESLint → `tsc --noEmit` → Vitest → `docker build` for both images.

### Step 8: Docs
- **README.md:** setup, how to run the tests, an architecture overview, decisions and assumptions, what's unfinished and next steps, time spent on each part, where AI was used, and a link to the green CI run.
- **DEPLOY.md** (about 1 page, AWS):
  - Compute: ECS Fargate. Database: RDS Postgres. Networking: an ALB in a private VPC.
  - Secrets: Secrets Manager. Logs: CloudWatch.
  - CI deploys through GitHub OIDC, so there are no long-lived keys.
  - Scanner permissions are read-only: `s3:GetBucketPublicAccessBlock`, `s3:ListAllMyBuckets`, `ec2:DescribeSecurityGroups`, `iam:ListUsers`, `iam:GetLoginProfile`, `iam:ListMFADevices`, `iam:ListAccessKeys`, `rds:DescribeDBInstances`.

---

## 5. Expected results (sanity check)

| Account | FAIL | Notes |
|---------|------|-------|
| aws prod | public-downloads, logs (S3); bastion, legacy-admin, ipv6-ssh, debug-all-traffic (EC2); bob (MFA); reporting-bot, legacy-etl (keys); analytics-replica (RDS) | ci-deployer's key is exactly 90 days old → PASS |
| aws dev | dev-scratch (S3) | iam_users and rds_instances → CANNOT_SCAN; corrupt-record → CANNOT_SCAN |
| azure | examplecorppublic; nsg-jumpbox, nsg-mgmt | nsg-locked → PASS (Deny + Outbound) |
| gcp | public-site, partner-share (GCS-01); ml-data (GCS-02); allow-rdp-anywhere | the disabled, egress and 8000-9000 rules → PASS |

---

## 6. Final checklist
- [ ] `docker compose up --build` works on a clean machine
- [ ] CI is green on the final commit
- [ ] No secrets, `.env`, `node_modules` or build output in git
- [ ] README and DEPLOY.md are complete
