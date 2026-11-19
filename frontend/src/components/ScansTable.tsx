import { Link } from "react-router-dom";
import { formatDateTime, formatDuration } from "../format";
import type { ScanSummary } from "../types";
import { Badge, Score } from "./common";

export function ScansTable({ scans }: { scans: ScanSummary[] }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Status</th>
          <th>Started</th>
          <th>Duration</th>
          <th>Accounts</th>
          <th className="num">Pass</th>
          <th className="num">Fail</th>
          <th className="num">Cannot scan</th>
          <th className="num">Score</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {scans.map((s) => (
          <tr key={s.id}>
            <td>
              <Badge value={s.status} />
            </td>
            <td>{formatDateTime(s.started_at)}</td>
            <td>{s.status === "RUNNING" ? "running…" : formatDuration(s.duration_seconds)}</td>
            <td>{s.account_ids.length}</td>
            <td className="num">{s.counts.PASS}</td>
            <td className="num">{s.counts.FAIL}</td>
            <td className="num">{s.counts.CANNOT_SCAN}</td>
            <td className="num">
              <Score value={s.score} />
            </td>
            <td>
              <Link to={`/scans/${encodeURIComponent(s.id)}`}>View</Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
