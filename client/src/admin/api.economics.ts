import { adminRead } from "../api.admin";

export type CostDay = {
  day: string;
  video_count: number;
  output_seconds: number;
  video_768p_fen: number;
  video_2k_fen: number;
  analysis_fen: number;
  image_fen: number;
  context_ir_fen: number;
  total_cost_fen: number;
  unknown_count: number;
};

export type CostRecord = {
  id: string;
  occurred_at: string;
  source_type: string;
  source_id: string;
  subject: string;
  resolution: string | null;
  unit: string;
  usage_amount: number | null;
  unit_price_fen: number;
  cost_fen: number | null;
  status: "PENDING" | "ACTUAL" | "UNKNOWN";
};

export type CostOverview = {
  days: CostDay[];
  records: CostRecord[];
  record_total: number;
  records_truncated: boolean;
  total_cost_fen: number;
  total_output_seconds: number;
  average_video_cost_per_second_fen: number | null;
  unknown_count: number;
};

export type CostFilters = {
  lookbackDays: number;
  subject?: string;
  resolution?: string;
};

function query(filters: CostFilters): string {
  const params = new URLSearchParams({
    lookback_days: String(filters.lookbackDays),
  });
  if (filters.subject) params.set("subject", filters.subject);
  if (filters.resolution) params.set("resolution", filters.resolution);
  return params.toString();
}

export function listOperationCosts(
  filters: CostFilters,
): Promise<CostOverview> {
  return adminRead<CostOverview>(
    `/api/control/profit/costs?${query(filters)}`,
    "读取成本明细失败",
  );
}

export function operationCostsCsvUrl(filters: CostFilters): string {
  return `/api/control/profit/costs.csv?${query(filters)}`;
}
