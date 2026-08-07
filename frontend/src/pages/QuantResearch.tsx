import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { FlaskConical, Play, RefreshCw, Save, ScrollText, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { quantApi, type BacktestResponse, type ExperimentRow } from "@/lib/quant";

const CONFIG_NAMES = ["backtest", "risk", "protocol", "hypothesis"] as const;
const CONFIG_LABELS: Record<string, string> = {
  backtest: "固定回测底座",
  risk: "硬性风控",
  protocol: "实验协议",
  hypothesis: "研究假设卡",
};

type Tab = "config" | "backtest" | "experiments";

function ValueEditor({
  label,
  value,
  onChange,
}: {
  label: string;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (typeof value === "boolean") {
    return (
      <label className="flex items-center gap-2 py-1.5">
        <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} className="accent-[hsl(var(--primary))]" />
        <span className="text-sm">{label}</span>
      </label>
    );
  }
  if (typeof value === "number") {
    return (
      <div className="py-1.5">
        <div className="mb-1 text-xs text-muted-foreground">{label}</div>
        <input
          type="number"
          step="any"
          value={value}
          onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
          className="w-full rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
    );
  }
  if (typeof value === "string") {
    return (
      <div className="py-1.5">
        <div className="mb-1 text-xs text-muted-foreground">{label}</div>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
    );
  }
  const json = JSON.stringify(value, null, 2);
  return (
    <div className="py-1.5">
      <div className="mb-1 text-xs text-muted-foreground">{label}</div>
      <textarea
        defaultValue={json}
        onBlur={(e) => {
          try {
            onChange(JSON.parse(e.target.value));
          } catch {
            /* 保留原值 */
          }
        }}
        rows={Math.min(10, Math.max(3, json.split("\n").length))}
        className="w-full rounded-md bg-muted/50 px-2 py-1.5 font-mono text-xs outline-none focus:ring-1 focus:ring-primary"
      />
    </div>
  );
}

function ConfigPanel() {
  const [name, setName] = useState<(typeof CONFIG_NAMES)[number]>("backtest");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [diff, setDiff] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  const load = useCallback(async (n: string) => {
    setError("");
    setSaved("");
    try {
      const res = await quantApi.getConfig(n);
      setDraft(JSON.parse(JSON.stringify(res.config)));
      setDiff([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load(name);
  }, [name, load]);

  const save = async () => {
    if (!draft) return;
    setError("");
    setSaved("");
    try {
      const res = await quantApi.saveConfig(name, draft);
      setDraft(JSON.parse(JSON.stringify(res.config)));
      setDiff(res.diff ?? []);
      setSaved(`已保存，实验记录：${res.log_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-1">
        {CONFIG_NAMES.map((n) => (
          <button
            key={n}
            onClick={() => setName(n)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm",
              name === n ? "bg-primary/15 text-primary shadow-glow" : "bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            {CONFIG_LABELS[n]}
          </button>
        ))}
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => void load(name)}
            className="flex items-center gap-1.5 rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs hover:bg-muted"
          >
            <RefreshCw size={12} /> 重新加载
          </button>
          <button
            onClick={() => void save()}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
          >
            <Save size={12} /> 保存配置
          </button>
        </div>
      </div>

      <div className="glass p-5">
        {!draft ? (
          <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
        ) : (
          <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
            {Object.entries(draft).map(([k, v]) => (
              <ValueEditor key={k} label={k} value={v} onChange={(nv) => setDraft({ ...draft, [k]: nv })} />
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="mt-3 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>
      )}
      {saved && (
        <div className="mt-3 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success">{saved}</div>
      )}
      {diff.length > 0 && (
        <div className="glass mt-3 p-4">
          <div className="mb-2 text-sm font-medium">本次变更 diff</div>
          <pre className="whitespace-pre-wrap font-mono text-xs text-accent-foreground">
            {diff.map((d) => `- ${d}`).join("\n")}
          </pre>
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, fmt }: { label: string; value: number | null; fmt?: (v: number) => string }) {
  return (
    <div className="glass p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value === null ? "—" : fmt ? fmt(value) : value.toFixed(4)}</div>
    </div>
  );
}

function BacktestPanel() {
  const [params, setParams] = useState({ n_symbols: 60, n_days: 400, seed: 42, window: 20, top_n: 20 });
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!result || !chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { left: 60, right: 16, top: 20, bottom: 40 },
      xAxis: { type: "category", data: result.equity_curve.map(([d]) => d), axisLabel: { color: "#a8a29e" } },
      yAxis: { type: "value", scale: true, axisLabel: { color: "#a8a29e" } },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 6 }],
      series: [
        {
          type: "line",
          name: "净值",
          data: result.equity_curve.map(([, v]) => v),
          showSymbol: false,
          lineStyle: { color: "#f97316", width: 2 },
          areaStyle: { color: "rgba(249,115,22,.12)" },
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [result]);

  const run = async () => {
    setRunning(true);
    setError("");
    try {
      setResult(await quantApi.runBacktest(params));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const num = (v: number | null) => (v === null ? "—" : `${(v * 100).toFixed(2)}%`);
  const m = result?.metrics;
  const fields: Array<[keyof typeof params, string]> = [
    ["n_symbols", "股票数"],
    ["n_days", "交易日"],
    ["seed", "随机种子"],
    ["window", "动量窗口"],
    ["top_n", "持仓只数"],
  ];

  return (
    <div>
      <div className="glass mb-4 flex flex-wrap items-end gap-3 p-4">
        {fields.map(([key, label]) => (
          <div key={key}>
            <div className="mb-1 text-xs text-muted-foreground">{label}</div>
            <input
              type="number"
              value={params[key]}
              onChange={(e) => setParams({ ...params, [key]: Number(e.target.value) })}
              className="w-28 rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
        ))}
        <button
          onClick={() => void run()}
          disabled={running}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          <Play size={14} /> {running ? "运行中…" : "运行回测"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>
      )}

      {m && (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard label="年化收益" value={m.annual_return} fmt={num} />
            <MetricCard label="最大回撤" value={m.max_drawdown} fmt={num} />
            <MetricCard label="夏普率" value={m.sharpe} />
            <MetricCard label="换手率" value={m.turnover} fmt={num} />
            <MetricCard label="总成本" value={m.total_cost} fmt={(v) => v.toFixed(0)} />
            <MetricCard label="入选股票数" value={m.selection_count} fmt={(v) => v.toFixed(0)} />
            <MetricCard label="RankIC 均值" value={result?.diagnostics.rank_ic_mean ?? null} />
            <MetricCard
              label="分组单调性"
              value={result?.diagnostics.monotonicity.monotonic ? 1 : 0}
              fmt={(v) => (v === 1 ? "是" : "否")}
            />
          </div>

          <div className="glass mb-4 p-4">
            <div className="mb-2 text-sm font-medium">净值曲线</div>
            <div ref={chartRef} className="h-72 w-full" />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="glass p-4">
              <div className="mb-2 text-sm font-medium">消融实验（基线 + 流动性过滤）</div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="py-1">组合</th>
                    <th>年化</th>
                    <th>回撤</th>
                    <th>夏普</th>
                  </tr>
                </thead>
                <tbody>
                  {result?.ablation.map((a) => (
                    <tr key={a.name} className="border-t border-border">
                      <td className="py-1.5">{a.name}</td>
                      <td>{num(a.annual_return)}</td>
                      <td>{num(a.max_drawdown)}</td>
                      <td>{a.sharpe === null ? "—" : a.sharpe.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="glass p-4">
              <div className="mb-2 text-sm font-medium">因子衰减（RankIC by 持有期）</div>
              {result?.diagnostics.decay && (
                <div className="flex flex-wrap gap-3">
                  {Object.entries(result.diagnostics.decay).map(([h, v]) => (
                    <div key={h} className="rounded-lg bg-muted/40 px-3 py-2 text-center">
                      <div className="text-[11px] text-muted-foreground">{h} 日</div>
                      <div className="text-sm font-semibold">{v === null ? "—" : v.toFixed(3)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ExperimentsPanel() {
  const [rows, setRows] = useState<ExperimentRow[]>([]);
  const [total, setTotal] = useState(0);
  const [successRate, setSuccessRate] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await quantApi.experiments();
      setRows(res.rows);
      setTotal(res.total);
      setSuccessRate(res.success_rate);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div>
      <div className="mb-4 flex items-center gap-2">
        <span className="text-sm text-muted-foreground">
          共 {total} 次实验 · 成功率 {(successRate * 100).toFixed(1)}%（失败实验保留是可信度的一部分）
        </span>
        <button
          onClick={() => void load()}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs hover:bg-muted"
        >
          <RefreshCw size={12} /> 刷新
        </button>
      </div>
      {error && (
        <div className="mb-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{error}</div>
      )}
      <div className="glass overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/30 text-left text-muted-foreground">
            <tr>
              <th className="px-3 py-2">编号</th>
              <th className="px-3 py-2">假设</th>
              <th className="px-3 py-2">唯一修改</th>
              <th className="px-3 py-2">预期</th>
              <th className="px-3 py-2">开发集</th>
              <th className="px-3 py-2">验证集</th>
              <th className="px-3 py-2">成本后</th>
              <th className="px-3 py-2">结果</th>
              <th className="px-3 py-2">时间</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                  暂无实验记录
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.experiment_id} className="border-t border-border">
                <td className="px-3 py-2 font-mono">{r.experiment_id}</td>
                <td className="px-3 py-2">{r.hypothesis}</td>
                <td className="max-w-[220px] truncate px-3 py-2" title={r.unique_change}>
                  {r.unique_change}
                </td>
                <td className="px-3 py-2">{r.expected}</td>
                <td className="px-3 py-2">{r.dev_result}</td>
                <td className="px-3 py-2">{r.val_result}</td>
                <td className="px-3 py-2">{r.cost_result}</td>
                <td className="px-3 py-2">
                  <span className={r.passed ? "text-success" : "text-danger"}>{r.passed ? "通过" : "失败"}</span>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{r.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const TABS: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
  { id: "config", label: "配置管理", icon: <Settings2 size={15} /> },
  { id: "backtest", label: "回测与诊断", icon: <FlaskConical size={15} /> },
  { id: "experiments", label: "实验日志", icon: <ScrollText size={15} /> },
];

export function QuantResearch() {
  const [tab, setTab] = useState<Tab>("config");
  return (
    <div>
      <div className="mb-5">
        <h1 className="text-xl font-bold">量化研究</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          AI 只改因子，不改回测底座 · 一条漂亮的净值曲线不是终点，而是审计的起点
        </p>
      </div>
      <div className="mb-5 flex gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm",
              tab === t.id ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>
      {tab === "config" && <ConfigPanel />}
      {tab === "backtest" && <BacktestPanel />}
      {tab === "experiments" && <ExperimentsPanel />}
    </div>
  );
}
