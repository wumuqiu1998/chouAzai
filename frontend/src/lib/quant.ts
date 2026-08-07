// 量化研究框架 API 客户端：/api/quant/* -> Vibe 后端（FastAPI :8900）
import { authHeaders } from "@/lib/api";

export class QuantApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, method: "GET" | "POST" | "PUT" = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() };
  const opts: RequestInit = { method };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (Object.keys(headers).length > 0) opts.headers = headers;
  let resp: Response;
  try {
    resp = await fetch(`/api/quant${path}`, opts);
  } catch {
    throw new QuantApiError("连接不到后端，请先启动 backend（uvicorn app:app --port 8900）", 0);
  }
  let payload: unknown = null;
  try {
    payload = await resp.json();
  } catch {
    /* 非 JSON 响应 */
  }
  if (!resp.ok) {
    const detail = (payload as { detail?: unknown })?.detail;
    throw new QuantApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail ?? payload ?? `HTTP ${resp.status}`),
      resp.status,
    );
  }
  return payload as T;
}

export interface ConfigResponse {
  name: string;
  config: Record<string, unknown>;
  diff?: string[];
  log_id?: string;
}

export interface BacktestResponse {
  metrics: {
    annual_return: number | null;
    max_drawdown: number | null;
    sharpe: number | null;
    turnover: number | null;
    total_cost: number | null;
    yearly: Record<string, number | null>;
    selection_count: number;
    return_concentration: Record<string, number | null>;
  };
  equity_curve: [string, number][];
  ablation: Array<{
    name: string;
    annual_return: number | null;
    max_drawdown: number | null;
    sharpe: number | null;
  }>;
  diagnostics: {
    monotonicity: { monotonic: boolean; spearman: number | null; top_minus_bottom: number | null };
    decay: Record<string, number | null>;
    rank_ic_mean: number | null;
  };
}

export interface ExperimentRow {
  experiment_id: string;
  hypothesis: string;
  unique_change: string;
  expected: string;
  dev_result: string;
  val_result: string;
  cost_result: string;
  passed: boolean;
  failure_reason: string;
  code_version: string;
  created_at: string;
}

export const quantApi = {
  getConfig: (name: string) => request<ConfigResponse>(`/config/${name}`),
  saveConfig: (name: string, data: Record<string, unknown>) =>
    request<ConfigResponse>(`/config/${name}`, "PUT", { data }),
  runBacktest: (params: {
    n_symbols: number;
    n_days: number;
    seed: number;
    window: number;
    top_n: number;
  }) => request<BacktestResponse>("/backtest/run", "POST", params),
  experiments: () => request<{ total: number; success_rate: number; rows: ExperimentRow[] }>("/experiments"),
  auditChecklist: () => request<{ items: string[] }>("/audit/checklist"),
};
