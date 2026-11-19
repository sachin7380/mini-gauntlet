import { formatScore, scoreClass } from "../format";

export function Badge({ value }: { value: string }) {
  return <span className={`badge badge-${value.toLowerCase()}`}>{value.replace("_", " ")}</span>;
}

export function Score({ value, large = false }: { value: number | null; large?: boolean }) {
  return <span className={`score ${scoreClass(value)} ${large ? "score-large" : ""}`}>{formatScore(value)}</span>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state" role="status">
      {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state-error" role="alert">
      <strong>Error:</strong> {message}
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="state state-empty">{children}</div>;
}
