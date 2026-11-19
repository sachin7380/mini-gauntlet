import { FINDING_STATUSES, PROVIDERS, SEVERITIES, type AccountSummary, type FindingFilters } from "../types";

interface Props {
  value: FindingFilters;
  accounts: AccountSummary[];
  onChange: (next: FindingFilters) => void;
}

export function FindingFiltersBar({ value, accounts, onChange }: Props) {
  const set = (key: keyof FindingFilters) => (e: React.ChangeEvent<HTMLSelectElement>) =>
    onChange({ ...value, [key]: e.target.value });

  return (
    <div className="filters">
      <label>
        Status
        <select value={value.status} onChange={set("status")}>
          <option value="">All</option>
          {FINDING_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace("_", " ")}
            </option>
          ))}
        </select>
      </label>
      <label>
        Severity
        <select value={value.severity} onChange={set("severity")}>
          <option value="">All</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <label>
        Provider
        <select value={value.provider} onChange={set("provider")}>
          <option value="">All</option>
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <label>
        Account
        <select value={value.account_id} onChange={set("account_id")}>
          <option value="">All</option>
          {accounts.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.name ? `${a.name} (${a.account_id})` : a.account_id}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
