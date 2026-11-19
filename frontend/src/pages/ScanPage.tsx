import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, errorMessage } from "../api";
import { Badge, Empty, ErrorState, Loading, Score } from "../components/common";
import { FindingFiltersBar } from "../components/FindingFiltersBar";
import { FindingsTable } from "../components/FindingsTable";
import { formatDateTime, formatDuration } from "../format";
import { SEVERITIES, type FindingFilters, type FindingPage, type ScanDetail } from "../types";
import { POLL_MS } from "./ScansPage";

const NO_FILTERS: FindingFilters = { status: "", severity: "", provider: "", account_id: "" };

export function ScanPage() {
  const { id = "" } = useParams();
  const [scan, setScan] = useState<ScanDetail | null>(null);
  const [scanError, setScanError] = useState<{ message: string; notFound: boolean } | null>(null);

  const loadScan = useCallback(async () => {
    try {
      setScan(await api.getScan(id));
      setScanError(null);
    } catch (err) {
      setScanError({ message: errorMessage(err), notFound: err instanceof ApiError && err.status === 404 });
    }
  }, [id]);

  useEffect(() => {
    setScan(null);
    void loadScan();
  }, [loadScan]);

  const running = scan?.status === "RUNNING";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => void loadScan(), POLL_MS);
    return () => clearInterval(timer);
  }, [running, loadScan]);

  if (scanError?.notFound) {
    return (
      <section>
        <Link to="/">← All scans</Link>
        <Empty>Scan not found.</Empty>
      </section>
    );
  }

  return (
    <section>
      <Link to="/">← All scans</Link>
      {scanError && <ErrorState message={scanError.message} onRetry={loadScan} />}
      {!scan && !scanError && <Loading label="Loading scan…" />}
      {scan && (
        <>
          <div className="page-header">
            <h1>
              Scan <span className="mono small">{scan.id}</span>
            </h1>
            <Badge value={scan.status} />
          </div>
          <p className="muted">
            Started {formatDateTime(scan.started_at)} · Duration{" "}
            {running ? "running…" : formatDuration(scan.duration_seconds)}
          </p>
          {scan.status === "FAILED" && <ErrorState message={`Scan failed: ${scan.error ?? "unknown error"}`} />}

          <div className="cards">
            <div className="card">
              <div className="card-label">Posture score</div>
              <Score value={scan.score} large />
            </div>
            <div className="card">
              <div className="card-label">Findings by status</div>
              <dl className="kv">
                <dt>Fail</dt>
                <dd>{scan.counts.FAIL}</dd>
                <dt>Cannot scan</dt>
                <dd>{scan.counts.CANNOT_SCAN}</dd>
                <dt>Pass</dt>
                <dd>{scan.counts.PASS}</dd>
              </dl>
            </div>
            <div className="card">
              <div className="card-label">Failures by severity</div>
              <dl className="kv">
                {SEVERITIES.map((sev) => (
                  <div key={sev} className="kv-row">
                    <dt>
                      <Badge value={sev} />
                    </dt>
                    <dd>{scan.fail_by_severity[sev]}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>

          <h2>Accounts</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Provider</th>
                <th className="num">Pass</th>
                <th className="num">Fail</th>
                <th className="num">Cannot scan</th>
                <th className="num">Score</th>
              </tr>
            </thead>
            <tbody>
              {scan.accounts.map((a) => (
                <tr key={a.account_id}>
                  <td>
                    <div>{a.name ?? "—"}</div>
                    <div className="mono small muted">{a.account_id}</div>
                  </td>
                  <td>{a.provider ?? "—"}</td>
                  <td className="num">{a.counts.PASS}</td>
                  <td className="num">{a.counts.FAIL}</td>
                  <td className="num">{a.counts.CANNOT_SCAN}</td>
                  <td className="num">
                    <Score value={a.score} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>Findings</h2>
          <Findings scan={scan} />
        </>
      )}
    </section>
  );
}

function Findings({ scan }: { scan: ScanDetail }) {
  const [filters, setFilters] = useState<FindingFilters>(NO_FILTERS);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<FindingPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let stale = false; // ignore responses that arrive after filters changed
    setError(null);
    api
      .getFindings(scan.id, filters, page)
      .then((res) => !stale && setData(res))
      .catch((err) => !stale && setError(errorMessage(err)));
    return () => {
      stale = true;
    };
    // scan.status: refetch when a running scan finishes
  }, [scan.id, scan.status, filters, page, reloadKey]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <FindingFiltersBar
        value={filters}
        accounts={scan.accounts}
        onChange={(next) => {
          setFilters(next);
          setPage(1);
        }}
      />
      {error && <ErrorState message={error} onRetry={() => setReloadKey((k) => k + 1)} />}
      {!data && !error && <Loading label="Loading findings…" />}
      {data && data.items.length === 0 && (
        <Empty>
          {scan.status === "RUNNING" ? "Scan is running; findings appear when it finishes." : "No findings match these filters."}
        </Empty>
      )}
      {data && data.items.length > 0 && (
        <>
          <FindingsTable items={data.items} />
          <div className="pager">
            <button type="button" className="btn btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </button>
            <span>
              Page {data.page} of {totalPages} · {data.total} findings
            </span>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </>
  );
}
