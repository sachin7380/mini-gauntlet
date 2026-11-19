import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FindingFiltersBar } from "../components/FindingFiltersBar";
import { FindingsTable } from "../components/FindingsTable";
import type { Finding } from "../types";

const xss = "<img src=x onerror=alert('untrusted-input')> temporary rule";

const finding: Finding = {
  id: 1,
  scan_id: "s",
  check_id: "GCP-VPC-01",
  title: "Firewall rule doesn't expose SSH or RDP to the internet",
  provider: "gcp",
  account_id: "example-corp-gcp",
  region: "global",
  resource_id: "<b>allow-rdp-anywhere</b>",
  status: "FAIL",
  severity: "CRITICAL",
  details: xss,
};

describe("FindingsTable", () => {
  it("renders untrusted strings as plain text, never as HTML", () => {
    const { container } = render(<FindingsTable items={[finding]} />);

    expect(screen.getByText(xss)).toBeInTheDocument();
    expect(screen.getByText("<b>allow-rdp-anywhere</b>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });

  it("shows a dash when a finding has no resource ID or region", () => {
    render(<FindingsTable items={[{ ...finding, resource_id: null, region: null, status: "CANNOT_SCAN" }]} />);
    expect(screen.getAllByText("—")).toHaveLength(2);
    expect(screen.getByText("CANNOT SCAN")).toBeInTheDocument();
  });
});

describe("FindingFiltersBar", () => {
  it("reports filter changes", async () => {
    const onChange = vi.fn();
    render(
      <FindingFiltersBar
        value={{ status: "", severity: "", provider: "", account_id: "" }}
        accounts={[
          { account_id: "123", name: "prod", provider: "aws", score: 50, counts: { PASS: 1, FAIL: 1, CANNOT_SCAN: 0 } },
        ]}
        onChange={onChange}
      />,
    );

    await userEvent.selectOptions(screen.getByLabelText("Severity"), "HIGH");
    expect(onChange).toHaveBeenLastCalledWith({ status: "", severity: "HIGH", provider: "", account_id: "" });

    await userEvent.selectOptions(screen.getByLabelText("Account"), "123");
    expect(onChange).toHaveBeenLastCalledWith({ status: "", severity: "", provider: "", account_id: "123" });
  });
});
