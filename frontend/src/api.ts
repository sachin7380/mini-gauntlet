import type { FindingFilters, FindingPage, ScanDetail, ScanSummary } from "./types";

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}

function detailMessage(body: unknown): string | null {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(`Can't reach the API at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      message = detailMessage(await res.json()) ?? message;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(message, res.status);
  }
  return (await res.json()) as T;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong";
}

export const api = {
  listScans: () => request<ScanSummary[]>("/api/scans"),
  getScan: (id: string) => request<ScanDetail>(`/api/scans/${encodeURIComponent(id)}`),
  startScan: () =>
    request<ScanSummary>("/api/scans", { method: "POST", headers: { "Content-Type": "application/json" } }),
  getFindings: (id: string, filters: FindingFilters, page: number, pageSize = 25) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value);
    }
    return request<FindingPage>(`/api/scans/${encodeURIComponent(id)}/findings?${params}`);
  },
};
