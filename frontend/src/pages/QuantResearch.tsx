import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { FlaskConical, Play, RefreshCw, Save, ScrollText, Settings2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { quantApi, type BacktestResponse, type ExperimentRow } from "@/lib/quant";

const CONFIG_NAMES = ["backtest", "risk", "protocol", "hypothesis"] as const;
const CONFIG_LABELS: Record<string, string> = {
  backtest: "固定回测底座",
  risk: "硬性风控",
  protocol: "实验协议",
  hypothesis: "研究假设卡",
};

const FIELD_LABELS: Record<string, string> = {
  initial_cash: "初始资金",
  commission_rate: "佣金率",
  stamp_duty_rate: "印花税率（卖出）",
  slippage: "滑点",
  lot_size: "每手股数",
  fill_price: "成交价格模式",
  rebalance_freq_days: "调仓频率（交易日）",
  holding_period_days: "持有周期（交易日）",
  top_n: "持仓只数",
  limit_up_pct: "涨停幅度",
  limit_down_pct: "跌停幅度",
  enforce_limit: "涨跌停不可成交",
  t_plus_one: "T+1 规则",
  metrics: "绩效指标",
  max_position_per_stock: "单票最大仓位",
  max_total_position: "总仓位上限",
  max_daily_turnover: "单日最大换手",
  max_daily_loss: "单日最大亏损",
  max_order_amount: "单笔最大金额",
  price_sanity_band: "价格异动检查幅度",
  max_duplicate_orders: "重复下单次数上限",
  disconnect_guard: "数据断线保护",
  emergency_stop: "紧急停止交易",
  dev_ratio: "开发集比例",
  val_ratio: "验证集比例",
  blind_ratio: "盲测集比例",
  walk_forward: "滚动验证",
  max_changes_per_experiment: "单次实验最大变量数",
  keep_failed_experiments: "保留失败实验",
  pass_criteria: "通过标准",
  failure_criteria: "失败标准",
  train_days: "训练天数",
  test_days: "测试天数",
  label_horizon_days: "标签期（天）",
  embargo_days: "隔离区（天）",
  oos_rank_ic_positive: "样本外 RankIC 为正",
  cost_after_return_positive: "成本后收益为正",
  yearly_positive_ratio: "年度正收益占比",
  max_drawdown_upper: "最大回撤上限（负数）",
  market_observation: "市场观察",
  possible_mechanism: "可能机制",
  signal_definition: "信号定义",
  data_timing: "数据时间",
  prediction_target: "预测目标",
  benchmarks: "基准",
  confounders: "混杂变量",
};

const FACTOR_LABELS: Record<string, string> = {
  momentum: "动量",
  ma_bias: "均线乖离",
  rsi: "RSI",
  macd: "MACD柱",
  volatility: "波动率",
  volume_surge: "量能异动",
  volume_price: "量价配合",
};

const SOURCE_LABELS: Record<string, string> = {
  synthetic: "合成数据",
  real: "真实A股",
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
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
    return <ListEditor label={label} value={value as string[]} onChange={(nv) => onChange(nv)} />;
  }
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const obj = value as Record<string, unknown>;
    return (
      <div className="py-1.5">
        <div className="mb-1 text-xs text-muted-foreground">{label}</div>
        <div className="space-y-1 rounded-lg border border-border/50 bg-muted/20 p-2">
          {Object.entries(obj).map(([k, v]) => (
            <ValueEditor
              key={k}
              label={FIELD_LABELS[k] ?? k}
              value={v}
              onChange={(nv) => onChange({ ...obj, [k]: nv })}
            />
          ))}
        </div>
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

function ListEditor({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [text, setText] = useState("");
  return (
    <div className="py-1.5">
      <div className="mb-1 text-xs text-muted-foreground">{label}</div>
      <div className="mb-1.5 flex flex-wrap gap-1.5">
        {value.map((item, i) => (
          <span key={`${item}-${i}`} className="inline-flex items-center gap-1 rounded bg-muted/40 px-2 py-0.5 text-xs">
            {item}
            <button
              onClick={() => onChange(value.filter((_, j) => j !== i))}
              className="text-muted-foreground hover:text-danger"
              title="删除"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              if (text.trim()) {
                onChange([...value, text.trim()]);
                setText("");
              }
            }
          }}
          placeholder="输入一项后回车添加"
          className="flex-1 rounded bg-muted/50 px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          onClick={() => {
            if (text.trim()) {
              onChange([...value, text.trim()]);
              setText("");
            }
          }}
          className="rounded bg-primary/15 px-2 text-xs text-primary hover:bg-primary/25"
        >
          添加
        </button>
      </div>
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
              <ValueEditor key={k} label={FIELD_LABELS[k] ?? k} value={v} onChange={(nv) => setDraft({ ...draft, [k]: nv })} />
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
  const [params, setParams] = useState({
    source: "synthetic",
    codes: "600519,000858,300750,601318,600036,000333,002594,688981,600887,000001",
    factor: "momentum",
    hypothesis: "动量策略实验",
    n_symbols: 60,
    n_days: 400,
    seed: 42,
    window: 20,
    top_n: 20,
  });
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const yearlyRef = useRef<HTMLDivElement>(null);
  const icRef = useRef<HTMLDivElement>(null);
  const groupRef = useRef<HTMLDivElement>(null);

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

  // 分年度收益柱状图
  useEffect(() => {
    if (!result || !yearlyRef.current) return;
    const years = Object.entries(result.metrics.yearly);
    if (years.length === 0) return;
    const chart = echarts.init(yearlyRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        formatter: (ps: unknown) => {
          const p = (ps as Array<{ value: number; axisValue: string }>)[0];
          return p ? `${p.axisValue} 年：${(p.value * 100).toFixed(2)}%` : "";
        },
      },
      grid: { left: 56, right: 16, top: 20, bottom: 32 },
      xAxis: { type: "category", data: years.map(([y]) => y), axisLabel: { color: "#a8a29e" } },
      yAxis: { type: "value", axisLabel: { color: "#a8a29e", formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
      series: [
        {
          type: "bar",
          data: years.map(([, v]) => ({
            value: v,
            itemStyle: { color: (v as number) >= 0 ? "#ef4444" : "#22c55e" },
          })),
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

  // IC 时间序列
  useEffect(() => {
    if (!result || !icRef.current || result.diagnostics.ic_by_date.length === 0) return;
    const chart = echarts.init(icRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      grid: { left: 56, right: 16, top: 20, bottom: 32 },
      xAxis: {
        type: "category",
        data: result.diagnostics.ic_by_date.map(([d]) => d),
        axisLabel: { color: "#a8a29e", interval: Math.max(0, Math.floor(result.diagnostics.ic_by_date.length / 8)) },
      },
      yAxis: { type: "value", axisLabel: { color: "#a8a29e" } },
      series: [
        {
          type: "line",
          data: result.diagnostics.ic_by_date.map(([, v]) => v),
          showSymbol: false,
          lineStyle: { color: "#60a5fa", width: 1.5 },
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

  // 分组收益（单调性）柱状图
  useEffect(() => {
    if (!result || !groupRef.current || result.diagnostics.groups.length === 0) return;
    const chart = echarts.init(groupRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        formatter: (ps: unknown) => {
          const p = (ps as Array<{ value: number; axisValue: string }>)[0];
          return p ? `第 ${p.axisValue} 组：${(p.value * 100).toFixed(2)}%` : "";
        },
      },
      grid: { left: 56, right: 16, top: 20, bottom: 32 },
      xAxis: { type: "category", data: result.diagnostics.groups.map((g) => String(g.group)), axisLabel: { color: "#a8a29e" } },
      yAxis: { type: "value", axisLabel: { color: "#a8a29e", formatter: (v: number) => `${(v * 100).toFixed(1)}%` } },
      series: [
        {
          type: "bar",
          data: result.diagnostics.groups.map((g) => ({
            value: g.mean_ret,
            itemStyle: { color: g.mean_ret >= 0 ? "#ef4444" : "#22c55e" },
          })),
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
  const fields: Array<{ key: "n_symbols" | "n_days" | "seed" | "window" | "top_n"; label: string }> = [
    { key: "n_symbols", label: "股票数" },
    { key: "n_days", label: "交易日" },
    { key: "seed", label: "随机种子" },
    { key: "window", label: "因子参数(窗口)" },
    { key: "top_n", label: "持仓只数" },
  ];
  const FACTOR_OPTIONS: Array<[string, string]> = [
    ["momentum", "动量"],
    ["ma_bias", "均线乖离"],
    ["rsi", "RSI"],
    ["macd", "MACD柱"],
    ["volatility", "波动率"],
    ["volume_surge", "量能异动"],
    ["volume_price", "量价配合"],
  ];

  return (
    <div>
      <div className="glass mb-4 flex flex-wrap items-end gap-3 p-4">
        <div>
          <div className="mb-1 text-xs text-muted-foreground">数据源</div>
          <select
            value={params.source}
            onChange={(e) => setParams({ ...params, source: e.target.value })}
            className="rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
          >
            <option value="synthetic">合成数据</option>
            <option value="real">真实A股</option>
          </select>
        </div>
        {params.source === "real" && (
          <div>
            <div className="mb-1 text-xs text-muted-foreground">股票代码（逗号分隔）</div>
            <input
              value={params.codes}
              onChange={(e) => setParams({ ...params, codes: e.target.value })}
              className="w-72 rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
        )}
        <div>
          <div className="mb-1 text-xs text-muted-foreground">因子（可组合，逗号分隔）</div>
          <input
            list="factor-options"
            value={params.factor}
            onChange={(e) => setParams({ ...params, factor: e.target.value })}
            className="w-44 rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
          />
          <datalist id="factor-options">
            {FACTOR_OPTIONS.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
            <option value="momentum,rsi">动量+RSI</option>
            <option value="momentum,volume_price">动量+量价</option>
          </datalist>
        </div>
        <div>
          <div className="mb-1 text-xs text-muted-foreground">实验假设</div>
          <input
            value={params.hypothesis}
            onChange={(e) => setParams({ ...params, hypothesis: e.target.value })}
            className="w-40 rounded-md bg-muted/50 px-2 py-1.5 text-sm outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        {fields.map(({ key, label }) => (
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
          {result?.experiment && (
            <div
              className={cn(
                "mb-3 rounded-lg border px-3 py-2 text-sm",
                result.experiment.passed
                  ? "border-success/30 bg-success/10 text-success"
                  : "border-danger/30 bg-danger/10 text-danger",
              )}
            >
              {result.experiment.passed
                ? `实验通过 ✓（记录 ${result.experiment.log_id}）`
                : `实验未通过 ✗：${result.experiment.unmet.join("；") || "未满足协议标准"}（记录 ${result.experiment.log_id}）`}
            </div>
          )}
          <div className="mb-3 text-xs text-muted-foreground">
            {result?.universe &&
              `样本：${result.universe.n_symbols} 只 · ${result.universe.start} ~ ${result.universe.end} · 因子 ${FACTOR_LABELS[result.factor.name] ?? result.factor.name}(${result.factor.window}) · 数据源 ${SOURCE_LABELS[result.universe.source] ?? result.universe.source}`}
          </div>
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

          <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="glass p-4">
              <div className="mb-2 text-sm font-medium">分年度收益</div>
              <div ref={yearlyRef} className="h-48 w-full" />
            </div>
            <div className="glass p-4">
              <div className="mb-2 text-sm font-medium">IC 时间序列（RankIC by 日期）</div>
              <div ref={icRef} className="h-48 w-full" />
            </div>
          </div>

          <div className="glass mb-4 p-4">
            <div className="mb-2 text-sm font-medium">分组收益（10 组单调性）</div>
            {result.diagnostics.groups.length === 0 ? (
              <p className="py-10 text-center text-sm text-muted-foreground/60">
                样本股票数不足 10 只，无法分组（真实数据建议至少 10 只股票）
              </p>
            ) : (
              <div ref={groupRef} className="h-48 w-full" />
            )}
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
