export type ScanStatus = "RUNNING" | "COMPLETED" | "FAILED";
export type FindingStatus = "PASS" | "FAIL" | "CANNOT_SCAN";
export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export const FINDING_STATUSES: FindingStatus[] = ["FAIL", "CANNOT_SCAN", "PASS"];
export const SEVERITIES: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
export const PROVIDERS = ["aws", "azure", "gcp"] as const;

export type StatusCounts = Record<FindingStatus, number>;

export interface ScanSummary {
  id: string;
  status: ScanStatus;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  account_ids: string[];
  score: number | null;
  counts: StatusCounts;
  error: string | null;
}

export interface AccountSummary {
  account_id: string;
  name: string | null;
  provider: string | null;
  score: number | null;
  counts: StatusCounts;
}

export interface ScanDetail extends ScanSummary {
  fail_by_severity: Record<Severity, number>;
  accounts: AccountSummary[];
}

export interface Finding {
  id: number;
  scan_id: string;
  check_id: string;
  title: string;
  provider: string;
  account_id: string;
  region: string | null;
  resource_id: string | null;
  status: FindingStatus;
  severity: Severity;
  details: string;
}

export interface FindingPage {
  items: Finding[];
  total: number;
  page: number;
  page_size: number;
}

export interface FindingFilters {
  status: string;
  severity: string;
  provider: string;
  account_id: string;
}
