import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Globe2,
  LineChart,
  Newspaper,
  Plus,
  Radio,
  Radar as RadarIcon,
  RefreshCw,
  Star,
  Wallet,
  X,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  authHeaders,
  type GlobalIndex,
  type HeadlineNews,
  type Holding,
  type IndexQuote,
  type MarketOverview,
  type PortfolioData,
  type Quote,
  type ShortTermEmotion,
  type TurnoverTop,
} from "@/lib/api";
import { loadWatch, saveWatch, addCodes } from "@/lib/watchlist";
import { useLiveQuotes, isTradingHours } from "@/hooks/useLiveQuotes";
import { usePolling } from "@/hooks/usePolling";
import { cn } from "@/lib/utils";

interface LiveSnapshot {
  indices: IndexQuote[];
  global_indices: GlobalIndex[];
  overview: MarketOverview | null;
  emotion: ShortTermEmotion | null;
  turnover: TurnoverTop | null;
  headlines: { generated_at: string | null; news: HeadlineNews[] } | null;
  portfolio: PortfolioData | null;
}

interface RadarItem {
  title: string;
  url: string;
  time: string;
  source: string;
}
interface RadarData {
  generated_at: string | null;
  industries: Array<{ name: string; items: RadarItem[] }>;
}

interface MinuteData {
  code: string;
  name: string;
  prev_close: number;
  points: Array<{ time: string; price: number; avg_price: number; volume: number }>;
}

const color = (v: number | undefined | null) =>
  v == null ? "text-muted-foreground" : v > 0 ? "text-danger" : v < 0 ? "text-success" : "text-muted-foreground";
const pct = (v: number | undefined | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
const fmt = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("zh-CN", { maximumFractionDigits: 2 }));

const LIVE_KEY = "vr-live-on";
const ALERT_KEY = "vr-alert-on";
const loadLive = () => {
  try {
    return localStorage.getItem(LIVE_KEY) !== "off";
  } catch {
    return true;
  }
};
const loadAlert = () => {
  try {
    return localStorage.getItem(ALERT_KEY) === "on";
  } catch {
    return false;
  }
};

async function fetchSnapshot(): Promise<LiveSnapshot> {
  const resp = await fetch("/api/live/snapshot", { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as LiveSnapshot;
}

async function fetchRadar(): Promise<RadarData> {
  const resp = await fetch("/api/radar", { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const j = (await resp.json()) as { data?: RadarData };
  if (!j.data) throw new Error("雷达暂无数据");
  return j.data;
}

async function fetchKline(code: string, category: number): Promise<Array<Record<string, unknown>>> {
  const resp = await fetch(`/api/kline?code=${code}&category=${category}&offset=120`, { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const j = (await resp.json()) as { data?: Array<Record<string, unknown>> };
  return (j.data ?? []) as Array<Record<string, unknown>>;
}

async function fetchMinute(code: string): Promise<MinuteData> {
  const resp = await fetch(`/api/minute?code=${code}`, { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const j = (await resp.json()) as { data?: MinuteData };
  if (!j.data) throw new Error("分时暂无数据");
  return j.data;
}

function IndexCard({ name, price, change_pct }: IndexQuote) {
  return (
    <div className="glass p-3">
      <div className="text-xs text-muted-foreground">{name}</div>
      <div className={cn("mt-1 font-mono text-lg font-semibold", color(change_pct))}>{fmt(price)}</div>
      <div className={cn("font-mono text-xs", color(change_pct))}>{pct(change_pct)}</div>
    </div>
  );
}

const KLINE_TABS: Array<[string, string]> = [
  ["minute", "分时"],
  ["4", "日K"],
  ["5", "周K"],
  ["6", "月K"],
  ["11", "60分"],
  ["2", "30分"],
  ["1", "15分"],
  ["0", "5分"],
  ["7", "1分"],
];

function fmtMinuteTime(t: string): string {
  if (/^\d{4}$/.test(t)) return `${t.slice(0, 2)}:${t.slice(2)}`;
  return t;
}

function limitPctFor(code: string, name: string): number {
  const n = (name || "").toUpperCase();
  if (n.includes("ST")) return 0.05;
  if (/^(30|68)/.test(code)) return 0.2;
  if (/^(4|8|92)/.test(code)) return 0.3;
  return 0.1;
}

function parseBars(bars: Array<Record<string, unknown>>) {
  return bars
    .map((r) => ({
      date: String(r.datetime ?? r.date ?? r.day ?? "").slice(0, 19).replace("T", " "),
      o: Number(r.open),
      h: Number(r.high),
      l: Number(r.low),
      c: Number(r.close),
      v: Number(r.volume ?? r.vol ?? 0),
    }))
    .filter((b) => b.o && b.c && b.h && b.l)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}

function movingAverage(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

function KLineModal({
  code,
  name,
  quote,
  onClose,
}: {
  code: string;
  name: string;
  quote?: Quote;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<string>("minute");
  const [bars, setBars] = useState<Array<Record<string, unknown>>>([]);
  const [minute, setMinute] = useState<MinuteData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [prevClose, setPrevClose] = useState<number | null>(null);
  // 图表容器常驻 + 单一 chart 实例：切换周期只 clear/setOption，避免 React 卸载 ECharts DOM 冲突
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const cacheRef = useRef<Record<string, { bars?: Array<Record<string, unknown>>; minute?: MinuteData }>>({});

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    if (tab === "minute") {
      const cached = cacheRef.current[code]?.minute;
      if (cached) {
        setMinute(cached);
        setLoading(false);
        return;
      }
      fetchMinute(code)
        .then((d) => {
          if (cancelled) return;
          cacheRef.current[code] = { ...cacheRef.current[code], minute: d };
          setMinute(d);
          setPrevClose((p) => p ?? d.prev_close);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    } else {
      const category = Number(tab);
      const cached = cacheRef.current[code]?.bars;
      if (cached) {
        setBars(cached);
        setLoading(false);
        return;
      }
      fetchKline(code, category)
        .then((rows) => {
          if (cancelled) return;
          cacheRef.current[code] = { ...cacheRef.current[code], bars: rows };
          setBars(rows);
          // 顺带取昨收，用于涨跌停上下限
          fetchMinute(code)
            .then((d) => setPrevClose((p) => p ?? d.prev_close))
            .catch(() => {});
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [code, tab, reload]);

  // 盘中自动刷新：交易时段每 15 秒重拉当前周期数据，涨幅/图表实时更新
  useEffect(() => {
    let cancelled = false;
    let timer: number | null = null;
    const tick = async () => {
      if (cancelled) return;
      if (document.hidden || !isTradingHours()) {
        timer = window.setTimeout(tick, 30_000);
        return;
      }
      try {
        if (tab === "minute") {
          const d = await fetchMinute(code);
          if (!cancelled) {
            cacheRef.current[code] = { ...cacheRef.current[code], minute: d };
            setMinute(d);
            setPrevClose((p) => p ?? d.prev_close);
          }
        } else {
          const rows = await fetchKline(code, Number(tab));
          if (!cancelled) {
            cacheRef.current[code] = { ...cacheRef.current[code], bars: rows };
            setBars(rows);
          }
        }
      } catch {
        /* 轮询失败静默，下个周期再试 */
      }
      if (!cancelled) timer = window.setTimeout(tick, 15_000);
    };
    timer = window.setTimeout(tick, 15_000);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [code, tab]);

  // 初始化 chart 实例（容器常驻，只创建一次）
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let chart = echarts.getInstanceByDom(el);
    if (!chart) chart = echarts.init(el);
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (!chart.isDisposed()) chart.dispose();
      if (chartRef.current === chart) chartRef.current = null;
    };
  }, []);

  // K 线 option
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || tab === "minute" || bars.length === 0) return;
    const data = parseBars(bars);
    if (data.length === 0) return;
    const lastBar = data[data.length - 1];
    const prevBar = data[data.length - 2];
    const chg = prevBar ? ((lastBar.c - prevBar.c) / prevBar.c) * 100 : null;
    const chgStr = chg == null ? "" : `涨幅 ${chg > 0 ? "+" : ""}${chg.toFixed(2)}%`;
    const chgColor = chg == null ? "#a8a29e" : chg >= 0 ? "#ef4444" : "#22c55e";
    const pc = prevClose ?? prevBar?.c ?? null;
    const withPc = data.map((b, i) => ({ ...b, pc: i > 0 ? data[i - 1].c : pc ?? b.c }));
    // K线（分钟/日/周/月）常跨多天：Y 轴按可见数据自适应（scale:true），
    // 不再按“当天范围”钳制，否则历史K线会被压扁/裁掉。涨跌停虚线保留在真实价位。
    chart.clear();
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        formatter: (params: unknown) => {
          const list = params as Array<{ dataIndex: number; seriesName?: string; value?: unknown }>;
          const b = withPc[list[0]?.dataIndex ?? 0];
          if (!b) return "";
          const chgPct = b.pc ? ((b.c - b.pc) / b.pc) * 100 : 0;
          const col = chgPct >= 0 ? "#ef4444" : "#22c55e";
          const mas = list
            .filter((p) => typeof p.seriesName === "string" && p.seriesName.startsWith("MA"))
            .map((p) => `${p.seriesName} ${p.value == null ? "—" : Number(p.value).toFixed(2)}`)
            .join("　");
          return `${b.date}<br/>开 ${b.o.toFixed(2)}　收 ${b.c.toFixed(2)}<br/>高 ${b.h.toFixed(2)}　低 ${b.l.toFixed(2)}<br/>涨跌幅 <span style="color:${col}">${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%</span><br/>${mas}<br/>量 ${fmt(b.v)}`;
        },
      },
      legend: { data: ["K线", "MA5", "MA10", "MA20", "MA60", "成交量"], textStyle: { color: "#a8a29e" }, top: 0 },
      graphic: [
        {
          type: "text",
          right: 16,
          top: 4,
          style: { text: chgStr, fill: chgColor, fontSize: 12, fontWeight: 600 },
        },
      ],
      grid: [
        { left: 56, right: 16, top: 28, height: "56%" },
        { left: 56, right: 16, top: "72%", height: "18%" },
      ],
      xAxis: [
        { type: "category", data: data.map((b) => b.date), axisLabel: { color: "#a8a29e" } },
        { type: "category", gridIndex: 1, data: data.map((b) => b.date), axisLabel: { show: false } },
      ],
      yAxis: [
        {
          scale: true,
          axisLabel: { color: "#a8a29e" },
          splitLine: { lineStyle: { type: "dashed", color: "rgba(255,255,255,.07)" } },
        },
        {
          gridIndex: 1,
          axisLabel: { color: "#a8a29e" },
          splitLine: { lineStyle: { type: "dashed", color: "rgba(255,255,255,.05)" } },
        },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1] },
        { type: "slider", xAxisIndex: [0, 1], bottom: 0, height: 14 },
      ],
      series: [
        {
          name: "K线",
          type: "candlestick",
          data: data.map((b) => [b.o, b.c, b.l, b.h]),
          itemStyle: { color: "#ef4444", color0: "#22c55e", borderColor: "#ef4444", borderColor0: "#22c55e" },
        },
        ...[
          [5, "MA5", "#f5f5f4"],
          [10, "MA10", "#fbbf24"],
          [20, "MA20", "#c084fc"],
          [60, "MA60", "#34d399"],
        ].map(([period, maName, maColor]) => ({
          name: maName as string,
          type: "line" as const,
          data: movingAverage(data.map((b) => b.c), period as number),
          showSymbol: false,
          lineStyle: { width: 1, color: maColor as string },
          emphasis: { disabled: true },
          z: 2,
        })),
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: data.map((b) => ({
            value: b.v,
            itemStyle: { color: b.c >= b.o ? "rgba(239,68,68,.55)" : "rgba(34,197,94,.55)" },
          })),
        },
      ],
    });
  }, [tab, bars, prevClose]);

  // 分时 option
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || tab !== "minute" || !minute || minute.points.length === 0) return;
    const pts = minute.points;
    const times = pts.map((p) => fmtMinuteTime(p.time));
    const last = pts[pts.length - 1].price;
    const lineColor = last >= minute.prev_close ? "#ef4444" : "#22c55e";
    const chg = minute.prev_close ? ((last - minute.prev_close) / minute.prev_close) * 100 : null;
    const chgStr = chg == null ? "" : `涨幅 ${chg > 0 ? "+" : ""}${chg.toFixed(2)}%`;
    const limitPct = limitPctFor(code, name);
    const pc = minute.prev_close || 0;
    const dayHigh = Math.max(...pts.map((p) => p.price));
    const dayLow = Math.min(...pts.map((p) => p.price));
    const dayRange = Math.max((dayHigh - pc) / pc, (pc - dayLow) / pc);
    const maxMove = Math.max(dayRange, 0.005);
    const lo = pc * (1 - maxMove * 1.08);
    const hi = pc * (1 + maxMove * 1.08);
    chart.clear();
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        formatter: (params: unknown) => {
          const list = params as Array<{ dataIndex: number }>;
          const p = pts[list[0]?.dataIndex ?? 0];
          if (!p) return "";
          const chgPct = pc ? ((p.price - pc) / pc) * 100 : 0;
          const col = chgPct >= 0 ? "#ef4444" : "#22c55e";
          return `${fmtMinuteTime(p.time)}<br/>价 ${p.price.toFixed(2)}　均价 ${p.avg_price.toFixed(2)}<br/>涨幅 <span style="color:${col}">${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%</span><br/>量 ${fmt(p.volume)}`;
        },
      },
      legend: { data: ["价格", "均价", "成交量"], textStyle: { color: "#a8a29e" }, top: 0 },
      graphic: [
        {
          type: "text",
          right: 16,
          top: 4,
          style: { text: chgStr, fill: lineColor, fontSize: 12, fontWeight: 600 },
        },
      ],
      grid: [
        { left: 56, right: 72, top: 28, height: "56%" },
        { left: 56, right: 16, top: "72%", height: "18%" },
      ],
      xAxis: [
        { type: "category", data: times, axisLabel: { color: "#a8a29e", interval: Math.max(0, Math.floor(times.length / 8)) } },
        { type: "category", gridIndex: 1, data: times, axisLabel: { show: false } },
      ],
      yAxis: [
        {
          min: lo,
          max: hi,
          axisLabel: { color: "#a8a29e" },
          splitLine: { lineStyle: { type: "dashed", color: "rgba(255,255,255,.07)" } },
        },
        { gridIndex: 1, axisLabel: { color: "#a8a29e" }, splitLine: { lineStyle: { type: "dashed", color: "rgba(255,255,255,.05)" } } },
        {
          gridIndex: 0,
          position: "right",
          min: lo,
          max: hi,
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: "#a8a29e", formatter: (v: number) => `${((v / pc - 1) * 100).toFixed(1)}%` },
        },
      ],
      series: [
        {
          name: "价格",
          type: "line",
          data: pts.map((p) => p.price),
          showSymbol: false,
          lineStyle: { color: lineColor, width: 1.5 },
          markLine: {
            symbol: "none",
            silent: true,
            lineStyle: { color: "#78716c", type: "dashed" },
            label: { color: "#a8a29e", formatter: `昨收 ${minute.prev_close}` },
            data: [
              {
                yAxis: minute.prev_close,
                lineStyle: { color: "rgba(255,255,255,.45)", type: "dashed", width: 1 },
              },
              {
                yAxis: pc * (1 + limitPct),
                lineStyle: { color: "rgba(239,68,68,.7)", type: "dashed", width: 1.5 },
                label: { color: "#ef4444", formatter: `涨停 +${(limitPct * 100).toFixed(0)}%` },
              },
              {
                yAxis: pc * (1 - limitPct),
                lineStyle: { color: "rgba(34,197,94,.7)", type: "dashed", width: 1.5 },
                label: { color: "#22c55e", formatter: `跌停 -${(limitPct * 100).toFixed(0)}%` },
              },
            ],
          },
        },
        {
          name: "均价",
          type: "line",
          data: pts.map((p) => p.avg_price),
          showSymbol: false,
          lineStyle: { color: "#f59e0b", width: 1, type: "dashed" },
        },
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: pts.map((p) => ({
            value: p.volume,
            itemStyle: { color: p.price >= minute.prev_close ? "rgba(239,68,68,.45)" : "rgba(34,197,94,.45)" },
          })),
        },
      ],
    });
  }, [tab, minute]);

  const isMinute = tab === "minute";
  const hasData = isMinute ? !!minute && minute.points.length > 0 : bars.length > 0;

  // 行情统计：优先实时行情，其次分时/K线计算
  const klineData = parseBars(bars);
  const lastBar = klineData[klineData.length - 1];
  const prevBar = klineData[klineData.length - 2];
  const minutePoints = minute?.points ?? [];
  const minuteLast = minutePoints[minutePoints.length - 1];
  const statPrice = quote?.price ?? (isMinute ? minuteLast?.price : lastBar?.c) ?? null;
  const statPrev = quote?.last_close ?? (isMinute ? minute?.prev_close : prevBar?.c) ?? null;
  const statPct =
    quote?.change_pct ??
    (statPrice != null && statPrev ? ((statPrice - statPrev) / statPrev) * 100 : null);
  const statChg = statPrice != null && statPrev != null ? statPrice - statPrev : null;
  const statOpen = isMinute ? minutePoints[0]?.price : lastBar?.o ?? null;
  const statHigh = isMinute
    ? minutePoints.length
      ? Math.max(...minutePoints.map((p) => p.price))
      : null
    : lastBar?.h ?? null;
  const statLow = isMinute
    ? minutePoints.length
      ? Math.min(...minutePoints.map((p) => p.price))
      : null
    : lastBar?.l ?? null;
  const statVol = isMinute
    ? minutePoints.reduce((s, p) => s + p.volume, 0)
    : lastBar?.v ?? null;
  const statItem = (label: string, value: React.ReactNode, cls = "") => (
    <span>
      {label} <b className={cn("font-mono", cls)}>{value}</b>
    </span>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="glass flex h-[72vh] w-[min(92vw,860px)] flex-col p-4" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center gap-2">
          <LineChart className="h-4 w-4 text-primary" />
          <span className="font-semibold">{name}</span>
          <span className="font-mono text-xs text-muted-foreground">{code}</span>
          <div className="ml-4 flex flex-wrap gap-1">
            {KLINE_TABS.map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={cn(
                  "rounded-md px-2 py-1 text-xs",
                  tab === id ? "bg-primary/15 font-medium text-primary" : "bg-muted/40 text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <button onClick={onClose} className="ml-auto text-muted-foreground hover:text-foreground" title="关闭">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {statItem("现价", statPrice ?? "—", color(statPct))}
          {statItem(
            "涨幅",
            statPct == null ? "—" : `${statPct > 0 ? "+" : ""}${statPct.toFixed(2)}%`,
            color(statPct),
          )}
          {statItem("涨跌", statChg == null ? "—" : `${statChg > 0 ? "+" : ""}${statChg.toFixed(2)}`, color(statPct))}
          {statItem("今开", statOpen ?? "—")}
          {statItem("最高", statHigh ?? "—", "text-danger")}
          {statItem("最低", statLow ?? "—", "text-success")}
          {statItem("昨收", statPrev ?? "—")}
          {statItem("量", statVol == null ? "—" : fmt(statVol))}
        </div>
        <div className="relative min-h-0 flex-1">
          {/* 容器常驻，仅在无数据时隐藏，避免 chart 实例被卸载 */}
          <div ref={containerRef} className="absolute inset-0" style={{ visibility: hasData ? "visible" : "hidden" }} />
          {error ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-danger">
              {error}
              <button
                onClick={() => setReload((n) => n + 1)}
                className="rounded-lg bg-primary/15 px-3 py-1 text-xs text-primary hover:bg-primary/25"
              >
                重试
              </button>
            </div>
          ) : loading ? (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">加载中…</div>
          ) : !hasData ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              暂无数据（该周期可能不受当前行情源支持）
              <button
                onClick={() => setReload((n) => n + 1)}
                className="rounded-lg bg-primary/15 px-3 py-1 text-xs text-primary hover:bg-primary/25"
              >
                重试
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// 涨跌停判断：优先用行情接口的涨跌停价，缺失时回退到涨跌幅阈值
function limitState(q: Quote | undefined): "up" | "down" | null {
  if (!q) return null;
  if (q.limit_up && q.limit_up > 0 && q.price >= q.limit_up * 0.999) return "up";
  if (q.limit_down && q.limit_down > 0 && q.price <= q.limit_down * 1.001) return "down";
  if (q.change_pct >= 9.8) return "up";
  if (q.change_pct <= -9.8) return "down";
  return null;
}

export function LiveTrading() {
  const [codes, setCodes] = useState<string[]>(loadWatch);
  const [input, setInput] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [live, setLive] = useState(loadLive);
  const [alertOn, setAlertOn] = useState(loadAlert);
  const [sel, setSel] = useState<{ code: string; name: string } | null>(null);
  const [newsTab, setNewsTab] = useState<"headlines" | "radar">("headlines");
  const [alertList, setAlertList] = useState<Array<{ id: string; msg: string }>>([]);
  const prevQuotesRef = useRef<Record<string, Quote>>({});
  const alertedRef = useRef<Record<string, boolean>>({});

  const { quotes, loading, updatedAt: quoteAt, error: quoteError, refresh: refreshQuotes } = useLiveQuotes(codes, live);
  const { data, error, updatedAt, polling, refresh } = usePolling<LiveSnapshot>(fetchSnapshot, 5000, live, true);
  const { data: radar } = usePolling<RadarData>(fetchRadar, 60_000, live, false);

  const toggleLive = () => {
    setLive((on) => {
      const next = !on;
      try {
        localStorage.setItem(LIVE_KEY, next ? "on" : "off");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleAlert = () => {
    const next = !alertOn;
    setAlertOn(next);
    try {
      localStorage.setItem(ALERT_KEY, next ? "on" : "off");
    } catch {
      /* ignore */
    }
    if (next && "Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  };

  // 异动/涨跌停提醒：仅当条件从无到有时通知一次，条件解除后重新武装
  useEffect(() => {
    if (!alertOn) {
      prevQuotesRef.current = quotes;
      return;
    }
    const prev = prevQuotesRef.current;
    for (const c of codes) {
      const q = quotes[c];
      const p = prev[c];
      if (!q || !p) continue;
      const lim = limitState(q);
      const moved = Math.abs(q.change_pct) >= 5;
      const newlyLim = lim !== null && limitState(p) === null;
      const newlyMoved = moved && Math.abs(p.change_pct) < 5;
      if (alertedRef.current[c]) {
        if (!moved && lim === null) alertedRef.current[c] = false;
        continue;
      }
      if (newlyLim || newlyMoved) {
        alertedRef.current[c] = true;
        const kind = lim ? (lim === "up" ? "涨停" : "跌停") : "异动";
        const msg = `${q.name}(${c}) ${kind} 现价 ${q.price} 涨幅 ${pct(q.change_pct)}`;
        setAlertList((l) => [{ id: `${c}-${Date.now()}`, msg }, ...l].slice(0, 5));
        if ("Notification" in window && Notification.permission === "granted") {
          try {
            new Notification(`自选提醒 · ${q.name}`, { body: msg });
          } catch {
            /* ignore */
          }
        }
      }
    }
    prevQuotesRef.current = quotes;
  }, [quotes, codes, alertOn]);

  const add = () => {
    const { next, added } = addCodes(codes, input);
    if (added === 0) {
      setHint(input.trim() ? "没识别到新的 6 位代码（可能已在自选里）" : null);
      setInput("");
      return;
    }
    setCodes(next);
    saveWatch(next);
    setInput("");
    setHint(`已添加 ${added} 只`);
  };
  const remove = (c: string) => {
    const next = codes.filter((x) => x !== c);
    setCodes(next);
    saveWatch(next);
  };

  const bigMove = (q: Quote | undefined) => q && Math.abs(q.change_pct) >= 5;
  const emotion = data?.emotion;
  const overview = data?.overview;
  const portfolio = data?.portfolio;
  const radarItems = (radar?.industries ?? []).flatMap((sec) =>
    (sec.items ?? []).map((it) => ({ ...it, industry: sec.name })),
  );

  return (
    <div>
      <PageHeader
        title="实盘看盘"
        subtitle="盘中 3-5 秒自动刷新 · 点击自选股看分时/K线 · 快讯含全球头条与 12 赛道资讯雷达"
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={toggleLive}
              title={live ? "关闭自动刷新" : "开启自动刷新（交易时段每 3-5 秒）"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                live
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border/60 text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="relative flex h-2 w-2">
                {polling && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/70" />}
                <span className={cn("relative inline-flex h-2 w-2 rounded-full", live ? "bg-primary" : "bg-muted-foreground/40")} />
              </span>
              自动刷新
            </button>
            <button
              onClick={toggleAlert}
              title={alertOn ? "关闭异动/涨跌停提醒" : "开启异动/涨跌停提醒（需允许浏览器通知）"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                alertOn
                  ? "border-warning/50 bg-warning/10 text-warning"
                  : "border-border/60 text-muted-foreground hover:text-foreground",
              )}
            >
              <Bell className="h-3.5 w-3.5" />
              提醒
            </button>
            <button
              onClick={() => {
                refresh();
                refreshQuotes();
              }}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} /> 刷新
            </button>
            <span className="text-[11px] text-muted-foreground/70">
              {live && !polling ? (
                isTradingHours() ? "已暂停（页面未激活）" : "非交易时段 · 已暂停"
              ) : polling ? (
                <span className="text-primary/80">盘中实时</span>
              ) : (
                "已停止"
              )}
            </span>
            {(updatedAt || quoteAt) && (
              <span className="font-mono text-[11px] text-muted-foreground/60">
                {new Date(updatedAt || quoteAt || Date.now()).toLocaleTimeString("zh-CN", { hour12: false })}
              </span>
            )}
          </div>
        }
      />

      {error && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <AlertTriangle className="h-3.5 w-3.5" /> {error}
        </div>
      )}

      {alertList.length > 0 && (
        <div className="mb-4 space-y-1.5">
          {alertList.map((a) => (
            <div
              key={a.id}
              className="flex items-center gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-1.5 text-xs text-warning"
            >
              <Bell className="h-3.5 w-3.5 shrink-0" />
              <span className="flex-1">{a.msg}</span>
              <button onClick={() => setAlertList((l) => l.filter((x) => x.id !== a.id))} className="text-muted-foreground hover:text-foreground">
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 大盘 + 全球 */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {(data?.indices ?? []).map((i) => (
          <IndexCard key={i.name} {...i} />
        ))}
      </div>
      {data?.global_indices && data.global_indices.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Globe2 className="h-3.5 w-3.5" /> 外围
          </span>
          {data.global_indices.map((g) => (
            <span key={g.key} className="rounded-full border border-border/60 px-2.5 py-1 text-xs">
              {g.name} <b className={cn("font-mono", color(g.change_pct))}>{pct(g.change_pct)}</b>
            </span>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* 自选实时 */}
        <GlassCard>
          <div className="mb-2 flex items-center gap-1.5 font-semibold">
            <Star className="h-4 w-4 text-primary" /> 自选实时
            <span className="text-xs font-normal text-muted-foreground">（{codes.length}）</span>
            {quoteError && <span className="ml-auto text-[11px] text-warning">{quoteError}</span>}
          </div>
          <div className="mb-2 flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) add();
              }}
              placeholder="批量添加：600519 000858, 002463"
              className="flex-1 rounded-lg border border-border bg-black/20 px-3 py-1.5 text-sm outline-none focus:border-primary/50"
            />
            <button onClick={add} className="inline-flex items-center gap-1 rounded-lg bg-primary/15 px-3 text-sm font-medium text-primary hover:bg-primary/25">
              <Plus className="h-3.5 w-3.5" /> 添加
            </button>
          </div>
          {hint && <p className="mb-2 text-xs text-muted-foreground/70">{hint}</p>}
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["名称", "现价", "涨跌%", "PE", "PB", "换手%", ""].map((h) => (
                    <th key={h} className="px-2 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {codes.map((c) => {
                  const q = quotes[c];
                  return (
                    <tr
                      key={c}
                      className={cn(
                        "border-b border-border/30",
                        bigMove(q) && "bg-primary/10",
                        limitState(q) !== null && "animate-pulse",
                      )}
                    >
                      <td className="px-2 py-2 font-medium">
                        <button
                          onClick={() => setSel({ code: c, name: q?.name || c })}
                          className="hover:text-primary hover:underline"
                          title="点击看分时/K线"
                        >
                          {q?.name || "—"}
                        </button>
                      </td>
                      <td className={cn("px-2 py-2 font-mono", color(q?.change_pct))}>{q ? q.price : "—"}</td>
                      <td className={cn("px-2 py-2 font-mono", color(q?.change_pct))}>
                        {q ? pct(q.change_pct) : "—"}
                        {limitState(q) &&
                          (limitState(q) === "up" ? (
                            <ArrowUpRight className="ml-1 inline h-3 w-3" />
                          ) : (
                            <ArrowDownRight className="ml-1 inline h-3 w-3" />
                          ))}
                      </td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{q?.pe_ttm ?? "—"}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{q?.pb ?? "—"}</td>
                      <td className="px-2 py-2 font-mono text-muted-foreground">{q?.turnover_pct ?? "—"}</td>
                      <td className="px-2 py-2">
                        <button onClick={() => remove(c)} className="text-muted-foreground/50 hover:text-destructive" title="移除">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {codes.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-sm text-muted-foreground/60">
                      暂无自选股，粘贴代码批量添加
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </GlassCard>

        {/* 持仓实时盈亏 */}
        <GlassCard>
          <div className="mb-2 flex items-center gap-1.5 font-semibold">
            <Wallet className="h-4 w-4 text-primary" /> 持仓实时盈亏
            {portfolio && (
              <span className="ml-auto text-xs font-normal">
                总盈亏{" "}
                <b className={cn("font-mono", color(portfolio.totals?.pnl))}>
                  {fmt(portfolio.totals?.pnl)}（{pct(portfolio.totals?.pnl_pct)}）
                </b>
              </span>
            )}
          </div>
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                  {["名称", "持仓", "现价", "市值", "盈亏", "盈亏%"].map((h) => (
                    <th key={h} className="px-2 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {portfolio?.holdings?.map((h: Holding) => (
                  <tr key={h.code} className="border-b border-border/30">
                    <td className="px-2 py-2 font-medium">
                      <button
                        onClick={() => setSel({ code: h.code, name: h.name })}
                        className="hover:text-primary hover:underline"
                        title="点击看分时/K线"
                      >
                        {h.name}
                      </button>
                      <span className="ml-1 font-mono text-[11px] text-muted-foreground">{h.code}</span>
                    </td>
                    <td className="px-2 py-2 font-mono">{fmt(h.shares)}</td>
                    <td className={cn("px-2 py-2 font-mono", color(h.pnl))}>{fmt(h.price)}</td>
                    <td className="px-2 py-2 font-mono text-muted-foreground">{fmt(h.market_value)}</td>
                    <td className={cn("px-2 py-2 font-mono", color(h.pnl))}>{fmt(h.pnl)}</td>
                    <td className={cn("px-2 py-2 font-mono", color(h.pnl))}>{pct(h.pnl_pct)}</td>
                  </tr>
                ))}
                {(!portfolio || portfolio.holdings.length === 0) && (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-sm text-muted-foreground/60">
                      暂无持仓，去「我的持仓」录入
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </GlassCard>
      </div>

      {/* 情绪 + 板块资金 */}
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <GlassCard>
          <div className="mb-2 flex items-center gap-1.5 font-semibold">
            <Activity className="h-4 w-4 text-primary" /> 市场情绪
          </div>
          {emotion ? (
            <div className="grid grid-cols-3 gap-2 text-center text-sm">
              {[
                ["涨停", emotion.zt_count, "text-danger"],
                ["跌停", emotion.dt_count, "text-success"],
                ["连板", emotion.lianban_count, "text-primary"],
                ["炸板", emotion.zb_count, "text-warning"],
                ["封板率", emotion.seal_rate == null ? null : `${(emotion.seal_rate * 100).toFixed(1)}%`, "text-foreground"],
                ["晋级率", emotion.promotion_rate == null ? null : `${(emotion.promotion_rate * 100).toFixed(1)}%`, "text-foreground"],
              ].map(([label, value, cls]) => (
                <div key={String(label)} className="rounded-lg bg-muted/30 p-2">
                  <div className="text-[11px] text-muted-foreground">{String(label)}</div>
                  <div className={cn("font-mono text-base font-semibold", String(cls))}>{value ?? "—"}</div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground/60">暂无数据</p>
          )}
        </GlassCard>

        <GlassCard>
          <div className="mb-2 flex items-center gap-1.5 font-semibold">
            <Activity className="h-4 w-4 text-primary" /> 板块资金（涨跌前五）
          </div>
          {overview?.sectors?.length ? (
            <div className="space-y-1.5 text-sm">
              {overview.sectors.slice(0, 5).map((s) => (
                <div key={s.name} className="flex items-center justify-between rounded-lg bg-muted/20 px-2.5 py-1.5">
                  <span>{s.name}</span>
                  <span className={cn("font-mono", color(s.pct))}>{pct(s.pct)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground/60">暂无数据</p>
          )}
        </GlassCard>

        <GlassCard>
          <div className="mb-2 flex items-center gap-1.5 font-semibold">
            <Activity className="h-4 w-4 text-primary" /> 成交额榜 TOP10
          </div>
          {data?.turnover?.stocks?.length ? (
            <div className="space-y-1.5 text-sm">
              {data.turnover.stocks.slice(0, 10).map((s, i) => (
                <div key={`${s.code}-${i}`} className="flex items-center justify-between rounded-lg bg-muted/20 px-2.5 py-1.5">
                  <span>
                    <span className="mr-1.5 font-mono text-[11px] text-muted-foreground">{i + 1}</span>
                    {s.name}
                    <span className="ml-1.5 font-mono text-[11px] text-muted-foreground">{s.code}</span>
                  </span>
                  <span className={cn("font-mono", color(s.pct))}>{pct(s.pct)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground/60">暂无数据</p>
          )}
        </GlassCard>
      </div>

      {/* 快讯：全球头条 / 资讯雷达 */}
      <GlassCard className="mt-4">
        <div className="mb-2 flex items-center gap-2 font-semibold">
          <Newspaper className="h-4 w-4 text-primary" /> 盘中快讯
          <div className="flex gap-1">
            {(
              [
                ["headlines", "全球头条", <Newspaper key="n" className="h-3.5 w-3.5" />],
                ["radar", "资讯雷达", <RadarIcon key="r" className="h-3.5 w-3.5" />],
              ] as const
            ).map(([id, label, icon]) => (
              <button
                key={id}
                onClick={() => setNewsTab(id)}
                className={cn(
                  "flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-normal",
                  newsTab === id ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {newsTab === "headlines"
              ? data?.headlines?.generated_at
                ? `更新于 ${data.headlines.generated_at}`
                : ""
              : radar?.generated_at
                ? `更新于 ${radar.generated_at}`
                : ""}
          </span>
        </div>
        {newsTab === "headlines" ? (
          data?.headlines?.news?.length ? (
            <div className="divide-y divide-border/40">
              {data.headlines.news.map((n, i) => (
                <a
                  key={`${n.url}-${i}`}
                  href={n.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-start gap-3 py-2 text-sm hover:bg-muted/20"
                >
                  <span className="mt-0.5 shrink-0 font-mono text-[11px] text-muted-foreground">{n.time}</span>
                  <span className="flex-1">{n.title}</span>
                  <span className="shrink-0 text-[11px] text-muted-foreground">{n.src}</span>
                </a>
              ))}
            </div>
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground/60">暂无快讯</p>
          )
        ) : radarItems.length ? (
          <div className="divide-y divide-border/40">
            {radarItems.slice(0, 20).map((n, i) => (
              <a
                key={`${n.url}-${i}`}
                href={n.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-start gap-3 py-2 text-sm hover:bg-muted/20"
              >
                <span className="mt-0.5 shrink-0 font-mono text-[11px] text-muted-foreground">{n.time}</span>
                <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary">{n.industry}</span>
                <span className="flex-1">{n.title}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground">{n.source}</span>
              </a>
            ))}
          </div>
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground/60">
            雷达暂无缓存，可到「资讯雷达」页手动刷新
          </p>
        )}
      </GlassCard>

      <div className="mt-6 flex items-center gap-2 text-[11px] text-muted-foreground/70">
        <Radio className="h-3.5 w-3.5" />
        私有项目 · 数据来自公开接口 · 仅供个人使用 · 市场有风险，盈亏自负
      </div>

      {sel && (
        <KLineModal
          key={`${sel.code}-${sel.name}`}
          code={sel.code}
          name={sel.name}
          quote={quotes[sel.code]}
          onClose={() => setSel(null)}
        />
      )}
    </div>
  );
}
