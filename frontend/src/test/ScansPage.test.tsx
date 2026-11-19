import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ScansPage } from "../pages/ScansPage";
import type { ScanSummary } from "../types";

const completed: ScanSummary = {
  id: "scan-1",
  status: "COMPLETED",
  started_at: "2026-11-19T10:00:00Z",
  finished_at: "2026-11-19T10:00:03Z",
  duration_seconds: 3.02,
  account_ids: ["a", "b", "c", "d"],
  score: 60,
  counts: { PASS: 27, FAIL: 18, CANNOT_SCAN: 4 },
  error: null,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ScansPage />
    </MemoryRouter>,
  );
}

describe("ScansPage", () => {
  it("lists scans with score, duration and N/A for unscored scans", async () => {
    const unscored: ScanSummary = { ...completed, id: "scan-2", score: null, counts: { PASS: 0, FAIL: 0, CANNOT_SCAN: 3 } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([completed, unscored])));

    renderPage();

    expect(screen.getByRole("status")).toHaveTextContent("Loading scans");
    expect(await screen.findByText("60.0")).toBeInTheDocument();
    expect(screen.getByText("N/A")).toBeInTheDocument();
    expect(screen.getAllByText("3.0 s")).toHaveLength(2);
    expect(screen.getAllByRole("link", { name: "View" })).toHaveLength(2);
  });

  it("shows an empty state when there are no scans", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([])));
    renderPage();
    expect(await screen.findByText(/No scans yet/)).toBeInTheDocument();
  });

  it("shows an error with retry when the API is down", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse([completed]));
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the API");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("60.0")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("starts a scan and shows it as running", async () => {
    const running: ScanSummary = {
      ...completed,
      id: "scan-new",
      status: "RUNNING",
      finished_at: null,
      duration_seconds: null,
      score: null,
      counts: { PASS: 0, FAIL: 0, CANNOT_SCAN: 0 },
    };
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      Promise.resolve(init?.method === "POST" ? jsonResponse(running, 202) : jsonResponse([])),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderPage();
    await screen.findByText(/No scans yet/);
    await userEvent.click(screen.getByRole("button", { name: "Run scan" }));

    expect(await screen.findByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText("running…")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(expect.stringMatching(/\/api\/scans$/), expect.objectContaining({ method: "POST" })),
    );
  });
});
