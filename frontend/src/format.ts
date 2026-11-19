/** Start time in the viewer's own time zone. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  return `${m} min ${Math.round(seconds - m * 60)} s`;
}

export function formatScore(score: number | null): string {
  return score === null ? "N/A" : score.toFixed(1);
}

export function scoreClass(score: number | null): string {
  if (score === null) return "score-na";
  if (score >= 80) return "score-good";
  if (score >= 50) return "score-mid";
  return "score-bad";
}
