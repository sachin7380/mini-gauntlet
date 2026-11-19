# Mini Gauntlet

A small cloud posture scanner. It reads a snapshot of cloud configuration (`data/inventory.json`),
runs 10 security checks across AWS, Azure and GCP accounts, stores the findings and shows them
in a dashboard.

[![CI](https://github.com/sachin7380/mini-gauntlet/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sachin7380/mini-gauntlet/actions/workflows/ci.yml?query=branch%3Amain)

**CI:** [GitHub Actions runs on `main`](https://github.com/sachin7380/mini-gauntlet/actions/workflows/ci.yml?query=branch%3Amain).
The newest run is the one for the final commit. Each run lints, type-checks, runs both test
suites, builds both images, and runs a real scan against the composed stack.

---

## Quick start

```bash
docker compose up --build
```

- Dashboard: http://localhost:3000
- API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)

Click **Run scan**. The scan takes about 3 seconds, then shows a posture score of **60.0**
(27 PASS, 18 FAIL, 4 CANNOT_SCAN). Scan data is kept in the `api-data` volume;
`docker compose down -v` resets it.

## Running locally without Docker

```bash
# API (Python 3.10+)
cd backend
python -m venv .venv && .venv/Scripts/activate      # or: source .venv/bin/activate
pip install -e ".[dev]"
INVENTORY_PATH=../data/inventory.json uvicorn app.main:app --port 8000

# Dashboard (Node 20+)
cd frontend
npm ci
npm run dev                                          # http://localhost:3000

# Scanner only, as a CLI
cd backend && INVENTORY_PATH=../data/inventory.json python -m app.scanner
```

| Env var | Default | Meaning |
|---|---|---|
| `INVENTORY_PATH` | `data/inventory.json` | Snapshot to scan |
| `DATABASE_URL` | `sqlite:///./mini_gauntlet.db` | Any SQLAlchemy URL (Postgres works too) |
| `SCAN_WORKERS` | `4` | Accounts scanned concurrently |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `VITE_API_URL` | `http://localhost:8000` | API URL used by the dashboard (set at build time) |

## Running the tests

```bash
cd backend  && ruff check . && ruff format --check . && pytest -q     # 147 tests
cd frontend && npm run lint && npm run typecheck && npm test         # 7 tests
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push and pull request. It then builds
both images with `docker compose build`, starts the stack, runs a real scan against it and checks
that the score is 60.0 and that both containers run as non-root.

---

## Architecture

```
 React dashboard ──JSON──▶ FastAPI ──starts──▶ Scanner engine ◀── inventory.json
  (nginx :3000)            (:8000)      │        (registry, 4 threads)
                              ▲         └── findings ──▶ SQLite (volume)
                              └──────── reads ──────────┘
```

```
backend/app/
  checks/registry.py   @register decorator, Check dataclass, CHECKS dict
  checks/common.py     strict field readers, port/CIDR parsing, text sanitising
  checks/aws.py, azure.py, gcp.py   the 10 checks: one function each
  scanner.py           load snapshot, scan accounts concurrently, CANNOT_SCAN rules, score
  db.py / schemas.py   SQLAlchemy models, Pydantic response models
  main.py              FastAPI routes + background scan job
frontend/src/
  pages/ScansPage.tsx  scan list, Run scan, polling while RUNNING
  pages/ScanPage.tsx   score, counts, per-account scores, filtered/paginated findings
  components/          tables, filters, badges, loading/empty/error states
```

**Adding a check** means writing one function in any module under `app/checks/` and decorating it
with `@register(...)`. The package imports every module in its folder automatically, so nothing
else needs editing.

**How a scan works:** `POST /api/scans` validates the account IDs, saves a `RUNNING` row and
returns `202`. A background task loads the snapshot and scans the accounts in a
`ThreadPoolExecutor` (each account first sleeps `simulated_latency_ms`). It then writes every
finding and the `COMPLETED` status in a single transaction. If anything fails at the scan level
(for example, the snapshot can't be read), the scan is marked `FAILED` with the error.

## Decisions and trade-offs

- **Threads, not asyncio, for scanning.** The checks are plain synchronous functions (easy to
  write and test), and the "latency" stands in for blocking SDK calls such as boto3. A
  `ThreadPoolExecutor(4)` turns 8 s of total latency into about 3 s, the longest single account.
- **Findings are written at the end, in one transaction.** A scan never shows half its findings,
  and the score is never computed from partial data. The cost is that a running scan shows no
  findings until it finishes; with a ~3 s scan that's fine.
- **Summaries are computed with SQL `GROUP BY` when read**, not stored. This keeps a single source
  of truth, and it's cheap at this size.
- **Strict validation, not coercion.** Every field is type-checked (`"true"` is not `true`, a bool
  is not a port). Anything unexpected becomes a `CANNOT_SCAN` finding with a reason, and a warning
  is logged. A check that crashes also becomes `CANNOT_SCAN`, so one bad record can't stop a scan.
- **Untrusted strings:** values copied into `details` have control characters removed and are
  truncated to 200 characters. The API returns JSON only. The dashboard renders everything as
  React text nodes; ESLint bans `dangerouslySetInnerHTML`, a test checks the `<img onerror>`
  payload renders as text, and nginx sends a strict CSP.
- **Restarts:** on startup, any scan still `RUNNING` is marked `FAILED` ("Interrupted by API
  restart"), so it doesn't spin forever in the UI.
- **SQLite with WAL.** It's simple and runs in a single container; `DATABASE_URL` can point at
  Postgres for production (see DEPLOY.md).

## Assumptions

- **SSH/RDP exposure** means TCP port 22 or 3389 is reachable from `0.0.0.0/0` or `::/0` (for
  Azure, also the sources `*`, `Internet` and `Any`). It counts when a port range contains the
  port, or when the protocol is "all" (`-1`, `*`, `all`). UDP and ICMP rules can't expose SSH/RDP,
  so they are ignored.
- **Mixed results in one resource:** if one rule exposes SSH/RDP and another rule is malformed,
  the result is **FAIL**, because a confirmed exposure is more useful than "can't tell". If no
  rule fails and any rule is malformed, the result is CANNOT_SCAN.
- **Azure NSG:** only `Inbound` + `Allow` rules count. `destination_ports` may be `"22"`,
  `"3380-3400"`, `"22,3389"`, `"*"` or a list of these. Rule priority isn't in the snapshot, so a
  Deny can't override an Allow.
- **GCP firewall:** a missing `direction` means INGRESS and a missing `disabled` means false (GCP's
  defaults). An `allowed` entry with no `ports` means all ports.
- **IAM keys:** "older than 90 days" means `snapshot_taken_at - created_at > 90 days`, so a key
  exactly 90 days old passes. Inactive keys are ignored. Timestamps without a time zone are
  treated as UTC.
- **S3:** `public_access_block: null` means no block is configured, which is a FAIL, not a
  CANNOT_SCAN.
- **Collection-level errors:** findings created because a whole collection couldn't be read have
  `resource_id` and `region` set to null.
- **`page_size` over 100** returns 422 rather than being silently capped.
- **`simulated_latency_ms`** is capped at 60 s so a hostile value can't hang a scan.

## Unfinished / next steps

- None of the stretch goals are done (IaC, live AWS mode, CIS mapping, scan diff, Trivy/SBOM,
  CSV/API key).
- No authentication. Anyone who can reach the API can start scans.
- Base images are pinned by tag, not digest. Next step: pin by digest and let Dependabot bump them.
- Findings are inserted in one batch. For very large inventories, stream them in chunks and add
  a progress field.
- The dashboard has no URL state for filters or page, so a filtered view can't be shared as a link.

## Time spent and AI usage

Times are the approximate wall-clock time of the AI-assisted build session.

| Part | Time (approx.) |
|---|---|
| Reading the brief, writing the build plan (`AI_PLAN.md`) | 5 min |
| Scanner engine + 10 checks + engine tests | 10 min |
| REST API + persistence + API tests | 10 min |
| Dashboard + component tests, manual check in a browser | 10 min |
| Per-check edge-case tests | 3 min |
| Docker + CI | 5 min |
| README + DEPLOY.md | 5 min |
| Git, GitHub repo, first green CI run | 10 min |

**AI assistance:** I used Claude Code to help write the code, tests, Docker/CI setup and
documentation, working through it step by step from a plan. I reviewed the output and can
explain and change any part of it.
