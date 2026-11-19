import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { Empty, ErrorState, Loading } from "../components/common";
import { ScansTable } from "../components/ScansTable";
import type { ScanSummary } from "../types";

export const POLL_MS = 1500;

export function ScansPage() {
  const [scans, setScans] = useState<ScanSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    try {
      setScans(await api.listScans());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something is still running.
  const anyRunning = scans?.some((s) => s.status === "RUNNING") ?? false;
  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [anyRunning, load]);

  async function runScan() {
    setStarting(true);
    try {
      const scan = await api.startScan();
      setScans((prev) => [scan, ...(prev ?? []).filter((s) => s.id !== scan.id)]);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  return (
    <section>
      <div className="page-header">
        <h1>Scans</h1>
        <button type="button" className="btn" onClick={runScan} disabled={starting}>
          {starting ? "Starting…" : "Run scan"}
        </button>
      </div>

      {error && <ErrorState message={error} onRetry={load} />}
      {scans === null && !error && <Loading label="Loading scans…" />}
      {scans !== null && scans.length === 0 && <Empty>No scans yet. Click “Run scan” to start one.</Empty>}
      {scans !== null && scans.length > 0 && <ScansTable scans={scans} />}
    </section>
  );
}
