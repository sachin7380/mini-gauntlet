import type { Finding } from "../types";
import { Badge } from "./common";

/** Every value is rendered as a React text node, so snapshot strings can't inject HTML. */
export function FindingsTable({ items }: { items: Finding[] }) {
  return (
    <table className="table findings">
      <thead>
        <tr>
          <th>Status</th>
          <th>Severity</th>
          <th>Check</th>
          <th>Account</th>
          <th>Region</th>
          <th>Resource</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {items.map((f) => (
          <tr key={f.id}>
            <td>
              <Badge value={f.status} />
            </td>
            <td>
              <Badge value={f.severity} />
            </td>
            <td>
              <div className="mono">{f.check_id}</div>
              <div className="muted">{f.title}</div>
            </td>
            <td>
              <div className="muted">{f.provider}</div>
              <div className="mono small">{f.account_id}</div>
            </td>
            <td>{f.region ?? "—"}</td>
            <td className="mono">{f.resource_id ?? "—"}</td>
            <td className="details">{f.details}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
