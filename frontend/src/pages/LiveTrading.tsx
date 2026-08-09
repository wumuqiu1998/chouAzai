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

interface DayRefData {
  ref_date: string;
  ref_bar: { open: number; high: number; low: number; close: number; volume: number };
  prev_close: number;
  chan_points: Array<{ kind: string; date: string; price: number; note: string }>;
  atr: { mid: number | null; upper: number | null; lower: number | null };
  zhongshu: Array<{ start_date: string; end_date: string; zd: number; zg: number }>;
}

interface MinuteSignal {
  time?: string;
  date?: string;
  label: string;
  kind: string;
  price: number;
  note: string;
}

interface MinuteSignalsData {
  intraday: MinuteSignal[];
  recent: MinuteSignal[];
}

interface ChanData {
  points: Array<{ kind: string; date: string; price: number; note: string }>;
  zhongshu: Array<{ start_date: string; end_date: string; zd: number; zg: number }>;
  bi: Array<{ date: string; price: number; kind: string }>;
}

interface AtrData {
  config: { period: number; mult: number; ma_period: number };
  bars: Array<{ date: string; mid: number | null; upper: number | null; lower: number | null; atr: number | null }>;
  signals: Array<{ date: string; kind: "overheat" | "oversold" | "top" | "bottom"; price: number; note: string }>;
}

interface WyckoffData {
  bars: Array<{ date: string; state: string }>;
  phases: Array<{ start: string; end: string; phase: string }>;
  current: { phase: string; since: string; days: number };
  cost_zone: { phase: string; start: string; end: string; low: number; high: number; mid: number } | null;
  signals: Array<{ date: string; kind: "spring" | "upthrust"; price: number; note: string }>;
  last_close: number;
}

interface SmcData {
  fvg: Array<{ date: string; kind: "bullish" | "bearish"; bottom: number; top: number; filled: boolean }>;
  ob: Array<{ date: string; kind: "bullish" | "bearish"; bottom: number; top: number }>;
  sweeps: Array<{ date: string; kind: "bullish" | "bearish"; price: number; note: string }>;
  structure: {
    state: "bullish" | "bearish" | "range";
    last_bos: { date: string; kind: string; price: number; note: string } | null;
    last_choch: { date: string; kind: string; price: number; note: string } | null;
  };
}

interface MarketRegime {
  market: {
    state: "strong_up" | "up" | "range" | "down" | "strong_down";
    score: number;
    label: string;
    up_count: number;
    down_count: number;
    total: number;
  };
  indices: Array<{
    name: string;
    code: string;
    state: "up" | "range" | "down";
    last: number;
    ma20: number | null;
    ret20_pct: number;
    structure: "higher_high" | "lower_low" | "mixed";
  }>;
}

interface ResonanceData {
  score: number;
  rating: string;
  note: string;
  weights: { market: number; wyckoff: number; smc: number };
  market: { score: number; state: string; label: string };
  wyckoff: { score: number; phase: string; phase_label: string; signals: string[] };
  smc: { score: number; structure: string; notes: string[] };
  notes: string[];
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

async function fetchKline(code: string, category: number, offset: number): Promise<Array<Record<string, unknown>>> {
  const resp = await fetch(`/api/kline?code=${code}&category=${category}&offset=${offset}`, { headers: authHeaders() });
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

async function fetchDayRef(code: string): Promise<DayRefData> {
  const resp = await fetch(`/api/quant/day-ref?code=${code}&offset=120`, { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as DayRefData;
}

async function fetchMinuteSignals(code: string): Promise<MinuteSignalsData> {
  const resp = await fetch(`/api/quant/minute-signals?code=${code}`, { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as MinuteSignalsData;
}

async function fetchChan(code: string, category: number, offset: number, window?: number, excludeLast = false): Promise<ChanData> {
  const resp = await fetch(
    `/api/quant/chan/analyze?code=${code}&category=${category}&offset=${offset}&window=${window ?? ""}&exclude_last=${excludeLast ? 1 : 0}`,
    {
    headers: authHeaders(),
    },
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as ChanData;
}

async function fetchAtr(code: string, category: number, offset: number, window?: number, excludeLast = false): Promise<AtrData> {
  const resp = await fetch(
    `/api/quant/atr/analyze?code=${code}&category=${category}&offset=${offset}&window=${window ?? ""}&exclude_last=${excludeLast ? 1 : 0}`,
    {
    headers: authHeaders(),
    },
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as AtrData;
}

async function fetchWyckoff(code: string, category: number, offset: number, excludeLast = false): Promise<WyckoffData> {
  const resp = await fetch(
    `/api/quant/smc/wyckoff?code=${code}&category=${category}&offset=${offset}&exclude_last=${excludeLast ? 1 : 0}`,
    { headers: authHeaders() },
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as WyckoffData;
}

async function fetchSmc(code: string, category: number, offset: number, excludeLast = false): Promise<SmcData> {
  const resp = await fetch(
    `/api/quant/smc/analyze?code=${code}&category=${category}&offset=${offset}&exclude_last=${excludeLast ? 1 : 0}`,
    { headers: authHeaders() },
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as SmcData;
}

async function fetchMarketRegime(): Promise<MarketRegime> {
  const resp = await fetch("/api/quant/smc/market-regime", { headers: authHeaders() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as MarketRegime;
}

async function fetchResonance(code: string, category: number, offset: number, excludeLast = false): Promise<ResonanceData> {
  const resp = await fetch(
    `/api/quant/smc/resonance?code=${code}&category=${category}&offset=${offset}&exclude_last=${excludeLast ? 1 : 0}`,
    { headers: authHeaders() },
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as ResonanceData;
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
  const [maximized, setMaximized] = useState(false);
  const [bars, setBars] = useState<Array<Record<string, unknown>>>([]);
  const [minute, setMinute] = useState<MinuteData | null>(null);
  const [dayRefData, setDayRefData] = useState<DayRefData | null>(null);
  const [minuteSignals, setMinuteSignals] = useState<MinuteSignalsData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);
  const [prevClose, setPrevClose] = useState<number | null>(null);
  // 图表容器常驻 + 单一 chart 实例：切换周期只 clear/setOption，避免 React 卸载 ECharts DOM 冲突
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const cacheRef = useRef<Record<string, { bars?: Array<Record<string, unknown>>; minute?: MinuteData }>>({});
  const chanCacheRef = useRef<Record<string, ChanData>>({});
  const atrCacheRef = useRef<Record<string, AtrData>>({});
  const wyckoffCacheRef = useRef<Record<string, WyckoffData>>({});
  const smcCacheRef = useRef<Record<string, SmcData>>({});
  const resonanceCacheRef = useRef<Record<string, ResonanceData>>({});
  const [chanOn, setChanOn] = useState(true);
  const [chanData, setChanData] = useState<ChanData | null>(null);
  const [atrOn, setAtrOn] = useState(true);
  const [atrData, setAtrData] = useState<AtrData | null>(null);
  const [wyckoffOn, setWyckoffOn] = useState(true);
  const [wyckoffData, setWyckoffData] = useState<WyckoffData | null>(null);
  const [smcOn, setSmcOn] = useState(true);
  const [smcData, setSmcData] = useState<SmcData | null>(null);
  const [resonance, setResonance] = useState<ResonanceData | null>(null);
  // 盘中实时：最后一根 K 线未收盘，指标只使用已收盘数据（排除末根）
  const excludeLast = tab !== "minute" && isTradingHours();
  const [barCount, setBarCount] = useState(250);
  // 跟随缩放：dataZoom 后按可见根数重算指标（K 线本体固定，不重载）
  const [viewCount, setViewCount] = useState(250);
  // 指标分析窗口 = 可见根数 + 左侧缓冲（保证窗口内 MA20/ATR/缠论完整）
  const atrWindow = Math.min(barCount, viewCount + 120);
  const [followZoom, setFollowZoom] = useState(true);
  const zoomTimerRef = useRef<number | null>(null);
  const ignoreZoomRef = useRef(false);
  const followZoomRef = useRef(followZoom);
  const tabRef = useRef(tab);
  const barsRef = useRef(bars);
  const viewCountRef = useRef(viewCount);
  const barCountRef = useRef(barCount);
  useEffect(() => {
    followZoomRef.current = followZoom;
    tabRef.current = tab;
    barsRef.current = bars;
    viewCountRef.current = viewCount;
    barCountRef.current = barCount;
  }, [followZoom, tab, bars, viewCount, barCount]);

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
      const cacheKey = `${code}-${tab}-${barCount}-${excludeLast ? "u" : "c"}`;
      const cached = cacheRef.current[cacheKey]?.bars;
      if (cached) {
        setBars(cached);
        setLoading(false);
        return;
      }
      fetchKline(code, category, barCount)
        .then((rows) => {
          if (cancelled) return;
          cacheRef.current[cacheKey] = {
            ...cacheRef.current[cacheKey],
            bars: rows,
          };
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
  }, [code, tab, reload, barCount, excludeLast]);

  // 缠论结构（买卖点/中枢/笔）
  useEffect(() => {
    if (!chanOn || tab === "minute") {
      setChanData(null);
      return;
    }
    let cancelled = false;
    const key = `${code}-${tab}-${atrWindow}-${excludeLast ? "u" : "c"}`;
    const cached = chanCacheRef.current[key];
    if (cached) {
      setChanData(cached);
      return;
    }
    fetchChan(code, Number(tab), barCount, atrWindow, excludeLast)
      .then((d) => {
        if (cancelled) return;
        chanCacheRef.current[key] = d;
        setChanData(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [chanOn, code, tab, barCount, atrWindow, excludeLast]);

  // 分时“昨日参考位”：昨高低/ATR通道/中枢/缠论买卖点（仅分时 tab）
  useEffect(() => {
    if (tab !== "minute") {
      setDayRefData(null);
      return;
    }
    let cancelled = false;
    fetchDayRef(code)
      .then((d) => {
        if (!cancelled) setDayRefData(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [code, tab]);

  // 分时通俗信号（顶/底/B/S/扫/突/破/变 + 近期积/派/扫/突/破/变参考位）
  useEffect(() => {
    if (tab !== "minute") {
      setMinuteSignals(null);
      return;
    }
    let cancelled = false;
    fetchMinuteSignals(code)
      .then((d) => {
        if (!cancelled) setMinuteSignals(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [code, tab]);

  // ATR 通道（超涨/超跌/顶底）
  useEffect(() => {
    if (!atrOn || tab === "minute") {
      setAtrData(null);
      return;
    }
    let cancelled = false;
    const key = `${code}-${tab}-${atrWindow}-${excludeLast ? "u" : "c"}`;
    const cached = atrCacheRef.current[key];
    if (cached) {
      setAtrData(cached);
      return;
    }
    fetchAtr(code, Number(tab), barCount, atrWindow, excludeLast)
      .then((d) => {
        if (cancelled) return;
        atrCacheRef.current[key] = d;
        setAtrData(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [atrOn, code, tab, barCount, atrWindow, excludeLast]);

  // 通俗信号：积（吸筹）/派（派发）
  useEffect(() => {
    if (!wyckoffOn || tab === "minute") {
      setWyckoffData(null);
      return;
    }
    let cancelled = false;
    const key = `${code}-${tab}-${barCount}-${excludeLast ? "u" : "c"}`;
    const cached = (wyckoffCacheRef.current as Record<string, WyckoffData>)[key];
    if (cached) {
      setWyckoffData(cached);
      return;
    }
    fetchWyckoff(code, Number(tab), barCount, excludeLast)
      .then((d) => {
        if (cancelled) return;
        wyckoffCacheRef.current[key] = d;
        setWyckoffData(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [wyckoffOn, code, tab, barCount, excludeLast]);

  // 通俗信号：扫（洗盘）/突（突破）/破（破位）/变（结构变化）
  useEffect(() => {
    if (!smcOn || tab === "minute") {
      setSmcData(null);
      return;
    }
    let cancelled = false;
    const key = `${code}-${tab}-${barCount}-${excludeLast ? "u" : "c"}`;
    const cached = (smcCacheRef.current as Record<string, SmcData>)[key];
    if (cached) {
      setSmcData(cached);
      return;
    }
    fetchSmc(code, Number(tab), barCount, excludeLast)
      .then((d) => {
        if (cancelled) return;
        smcCacheRef.current[key] = d;
        setSmcData(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [smcOn, code, tab, barCount, excludeLast]);

  // 三信号共振评分（市场+威科夫+ICT/SMC）
  useEffect(() => {
    if (tab === "minute") {
      setResonance(null);
      return;
    }
    let cancelled = false;
    const key = `${code}-${tab}-${barCount}-${excludeLast ? "u" : "c"}`;
    const cached = (resonanceCacheRef.current as Record<string, ResonanceData>)[key];
    if (cached) {
      setResonance(cached);
      return;
    }
    fetchResonance(code, Number(tab), barCount, excludeLast)
      .then((d) => {
        if (cancelled) return;
        resonanceCacheRef.current[key] = d;
        setResonance(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [code, tab, barCount, excludeLast]);

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
          const rows = await fetchKline(code, Number(tab), barCount);
          if (!cancelled) {
            const cacheKey = `${code}-${tab}-${barCount}-${excludeLast ? "u" : "c"}`;
            cacheRef.current[cacheKey] = {
              ...cacheRef.current[cacheKey],
              bars: rows,
            };
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
  }, [code, tab, barCount, excludeLast]);

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

  // 跟随窗口：dataZoom 后按可见根数重新拉数据并重算 MA/缠论/ATR
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const onZoom = () => {
      if (!followZoomRef.current || tabRef.current === "minute") return;
      if (ignoreZoomRef.current) {
        ignoreZoomRef.current = false;
        return;
      }
      if (zoomTimerRef.current !== null) window.clearTimeout(zoomTimerRef.current);
      zoomTimerRef.current = window.setTimeout(() => {
        zoomTimerRef.current = null;
        const opt = chart.getOption();
        const dz = (Array.isArray(opt.dataZoom) ? opt.dataZoom : opt.dataZoom ? [opt.dataZoom] : []) as Array<{
          start?: number;
          end?: number;
        }>;
        const start = dz[0]?.start ?? 0;
        const end = dz[0]?.end ?? 100;
        const total = barsRef.current.length || viewCountRef.current;
        const visible = Math.max(20, Math.min(barCountRef.current, Math.round(((end - start) / 100) * total)));
        if (Math.abs(visible - viewCountRef.current) >= 5) {
          setViewCount(visible);
        }
      }, 450);
    };
    chart.on("datazoom", onZoom);
    return () => {
      chart.off("datazoom", onZoom);
      if (zoomTimerRef.current !== null) window.clearTimeout(zoomTimerRef.current);
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
    // K 线固定 barCount 根：默认只显示末尾 viewCount 根（指标基于 atrWindow 含缓冲计算）
    const zoomStart = barCount > viewCount ? Math.round((1 - viewCount / barCount) * 100) : 0;
    const legendData = ["K线", "MA5", "MA10", "MA20", "MA60", "成交量"];
    const extraSeries: object[] = [];
    const chartRange = Math.max(...data.map((b) => b.h)) - Math.min(...data.map((b) => b.l));
    // MA 基于末尾 atrWindow 根（含左侧缓冲），前面补 null 与 K 线索引对齐；
    // 盘中实时再排除未收盘末根，末尾补 null 保持索引对齐
    const maRaw = excludeLast ? data.slice(-atrWindow, -1) : data.slice(-atrWindow);
    const maPad = data.length - maRaw.length;
    const maCloses = maRaw.map((b) => b.c);
    if (chanOn && chanData && (chanData.points.length > 0 || chanData.bi.length > 0)) {
      const idxOf = new Map(data.map((b, i) => [b.date.slice(0, 16), i]));
      const biLine = chanData.bi
        .map((b) => {
          const i = idxOf.get(b.date);
          return i === undefined ? null : [i, b.price];
        })
        .filter((v): v is [number, number] => v !== null);
      if (biLine.length >= 2) {
        extraSeries.push({
          name: "笔",
          type: "line",
          data: biLine,
          showSymbol: false,
          lineStyle: { width: 1, color: "#f59e0b", opacity: 0.85 },
          z: 2,
        });
      }
      const marker = (kindPrefix: string, color: string, label: string, isBuy: boolean) => {
        const items = chanData.points
          .filter((p) => p.kind.startsWith(kindPrefix))
          .map((p) => {
            const i = idxOf.get(p.date);
            if (i === undefined) return null;
            const bar = data[i];
            const gap = chartRange * 0.025;
            const y = isBuy ? bar.l - gap : bar.h + gap;
            return { value: [i, y], name: p.kind.toUpperCase() };
          })
          .filter((v) => v !== null);
        if (items.length === 0) return;
        extraSeries.push({
          name: label,
          type: "scatter",
          data: items,
          symbol: "triangle",
          symbolSize: 14,
          symbolRotate: isBuy ? 0 : 180,
          itemStyle: { color, borderColor: "#ffffff", borderWidth: 1 },
          label: {
            show: true,
            position: isBuy ? "bottom" : "top",
            color,
            fontSize: 11,
            fontWeight: 700,
            backgroundColor: "rgba(0,0,0,.6)",
            padding: [2, 4],
            borderRadius: 3,
            formatter: (p: unknown) => (p as { name: string }).name,
          },
          tooltip: {
            show: true,
            formatter: (p: unknown) => {
              const name = (p as { name?: string }).name ?? "";
              const pt = chanData.points.find((x) => x.kind.toUpperCase() === name);
              return pt ? `<b>${name}</b>（${pt.date}）<br/>${pt.note}` : "";
            },
          },
          z: 6,
        });
      };
      marker("buy", "#ef4444", "买点", true);
      marker("sell", "#3b82f6", "卖点", false);
      if (chanData.zhongshu.length > 0) {
        const areas = chanData.zhongshu
          .map((z) => {
            const s = idxOf.get(z.start_date);
            const e = idxOf.get(z.end_date);
            return s === undefined || e === undefined ? null : [{ xAxis: s, yAxis: z.zd }, { xAxis: e, yAxis: z.zg }];
          })
          .filter((v) => v !== null);
        if (areas.length > 0) {
          extraSeries.push({
            name: "中枢",
            type: "line",
            data: [],
            markArea: { silent: true, itemStyle: { color: "rgba(96,165,250,.12)" }, data: areas },
            z: 1,
          });
        }
      }
      legendData.push("买点", "卖点", "笔", "中枢");
    }
    if (atrOn && atrData && atrData.bars.length > 0) {
      const idxOf = new Map(data.map((b, i) => [b.date.slice(0, 16), i]));
      const bandLine = (field: "upper" | "mid" | "lower", color: string, label: string) => {
        const pts = atrData.bars
          .map((b) => {
            const i = idxOf.get(b.date.slice(0, 16));
            return i === undefined || b[field] == null ? null : [i, b[field] as number];
          })
          .filter((v): v is [number, number] => v !== null);
        if (pts.length < 2) return;
        extraSeries.push({
          name: label,
          type: "line",
          data: pts,
          showSymbol: false,
          lineStyle: { width: 1, color, type: "dashed", opacity: 0.75 },
          emphasis: { disabled: true },
          z: 3,
        });
        legendData.push(label);
      };
      bandLine("upper", "#f97316", "ATR上轨");
      bandLine("lower", "#06b6d4", "ATR下轨");
      bandLine("mid", "#c084fc", "ATR中轨");
      const atrMarker = (
        kind: "overheat" | "oversold" | "top" | "bottom",
        color: string,
        label: string,
        isTop: boolean,
        symbol: string,
        rotate: number,
      ) => {
        const items = atrData.signals
          .filter((s) => s.kind === kind)
          .map((s) => {
            const i = idxOf.get(s.date.slice(0, 16));
            if (i === undefined) return null;
            const bar = data[i];
            const gap = chartRange * 0.02;
            return { value: [i, isTop ? bar.h + gap : bar.l - gap], name: label, note: s.note, date: s.date };
          })
          .filter((v) => v !== null);
        if (items.length === 0) return;
        extraSeries.push({
          name: label,
          type: "scatter",
          data: items,
          symbol,
          symbolSize: kind === "overheat" || kind === "oversold" ? 12 : 15,
          symbolRotate: rotate,
          itemStyle: { color, borderColor: "#ffffff", borderWidth: 1 },
          label: {
            show: true,
            position: isTop ? "top" : "bottom",
            color,
            fontSize: 10,
            fontWeight: 700,
            backgroundColor: "rgba(0,0,0,.65)",
            padding: [1, 3],
            borderRadius: 3,
          },
          tooltip: {
            show: true,
            formatter: (p: unknown) => {
              const it = p as { data?: { date?: string; note?: string } };
              return it.data?.date ? `<b>${label}</b>（${it.data.date.slice(0, 16)}）<br/>${it.data.note ?? ""}` : "";
            },
          },
          z: 7,
        });
        legendData.push(label);
      };
      atrMarker("overheat", "#f97316", "超涨", true, "triangle", 180);
      atrMarker("oversold", "#06b6d4", "超跌", false, "triangle", 0);
      atrMarker("top", "#ef4444", "顶", true, "diamond", 0);
      atrMarker("bottom", "#22c55e", "底", false, "diamond", 0);
    }
    // 通俗信号标签：积（吸筹）/派（派发）/扫（洗盘扫荡）/突（突破）/破（破位）/变（结构变化）
    const plainMarker = (
      label: string,
      color: string,
      items: Array<{ value: [number, number]; note?: string; date?: string }>,
      labelPos: "top" | "bottom" | "inside" = "inside",
    ) => {
      if (items.length === 0) return;
      extraSeries.push({
        name: label,
        type: "scatter",
        data: items,
        symbol: "circle",
        symbolSize: 7,
        itemStyle: { color, borderColor: "#fff", borderWidth: 1 },
        label: {
          show: true,
          position: labelPos,
          color,
          fontSize: 11,
          fontWeight: 800,
          backgroundColor: "rgba(0,0,0,.55)",
          padding: [1, 3],
          borderRadius: 3,
          formatter: label,
        },
        tooltip: {
          show: true,
          formatter: (p: unknown) => {
            const it = p as { data?: { date?: string; note?: string } };
            return it.data?.date ? `<b>${label}</b>（${it.data.date.slice(0, 16)}）<br/>${it.data.note ?? ""}` : "";
          },
        },
        z: 8,
      });
      legendData.push(label);
    };

    if (wyckoffOn && wyckoffData) {
      const idxOf = new Map(data.map((b, i) => [b.date.slice(0, 16), i]));
      const springItems = wyckoffData.signals
        .filter((s) => s.kind === "spring")
        .map((s) => {
          const i = idxOf.get(s.date.slice(0, 16));
          if (i === undefined) return null;
          const bar = data[i];
          return { value: [i, bar.l - chartRange * 0.025], note: s.note, date: s.date };
        })
        .filter((v): v is { value: [number, number]; note: string; date: string } => v !== null);
      plainMarker("积", "#22c55e", springItems, "bottom");
      const upthrustItems = wyckoffData.signals
        .filter((s) => s.kind === "upthrust")
        .map((s) => {
          const i = idxOf.get(s.date.slice(0, 16));
          if (i === undefined) return null;
          const bar = data[i];
          return { value: [i, bar.h + chartRange * 0.025], note: s.note, date: s.date };
        })
        .filter((v): v is { value: [number, number]; note: string; date: string } => v !== null);
      plainMarker("派", "#f97316", upthrustItems, "top");
    }

    if (smcOn && smcData) {
      const idxOf = new Map(data.map((b, i) => [b.date.slice(0, 16), i]));
      const sweepItems = smcData.sweeps
        .map((s) => {
          const i = idxOf.get(s.date.slice(0, 16));
          if (i === undefined) return null;
          const bar = data[i];
          return {
            value: [i, s.kind === "bullish" ? bar.l - chartRange * 0.025 : bar.h + chartRange * 0.025],
            note: s.note,
            date: s.date,
          };
        })
        .filter((v): v is { value: [number, number]; note: string; date: string } => v !== null);
      plainMarker("扫", "#e11d48", sweepItems, "inside");
      const bos = smcData.structure?.last_bos;
      if (bos) {
        const i = idxOf.get(bos.date.slice(0, 16));
        if (i !== undefined) {
          const bar = data[i];
          plainMarker(
            bos.kind === "bullish" ? "突" : "破",
            bos.kind === "bullish" ? "#ef4444" : "#22c55e",
            [{ value: [i, bos.kind === "bullish" ? bar.h + chartRange * 0.025 : bar.l - chartRange * 0.025], note: bos.note, date: bos.date }],
            bos.kind === "bullish" ? "top" : "bottom",
          );
        }
      }
      const choch = smcData.structure?.last_choch;
      if (choch) {
        const i = idxOf.get(choch.date.slice(0, 16));
        if (i !== undefined) {
          const bar = data[i];
          plainMarker(
            "变",
            "#f59e0b",
            [{ value: [i, bar.h + chartRange * 0.04], note: choch.note, date: choch.date }],
            "top",
          );
        }
      }
    }
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
      legend: { data: legendData, textStyle: { color: "#a8a29e" }, top: 0 },
      graphic: [
        {
          type: "text",
          right: 16,
          top: 4,
          style: { text: chgStr, fill: chgColor, fontSize: 12, fontWeight: 600 },
        },
        ...(excludeLast
          ? [
              {
                type: "text" as const,
                right: 16,
                top: 20,
                style: { text: "末根未收盘·指标仅用已收盘数据", fill: "#f59e0b", fontSize: 10 },
              },
            ]
          : []),
      ],
      grid: [
        { left: 56, right: 16, top: 28, height: "66%" },
        { left: 56, right: 16, top: "78%", height: "16%" },
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
        { type: "inside", xAxisIndex: [0, 1], start: zoomStart, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], bottom: 0, height: 14, start: zoomStart, end: 100 },
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
          data: [...Array<number | null>(maPad).fill(null), ...movingAverage(maCloses, period as number)],
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
        ...extraSeries,
      ],
    });
  }, [tab, bars, prevClose, chanOn, chanData, atrOn, atrData, wyckoffOn, wyckoffData, smcOn, smcData, barCount, viewCount, atrWindow, excludeLast]);

  // 分时 option
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || tab !== "minute" || !minute || minute.points.length === 0) return;
    const pts = minute.points;
    const times = pts.map((p) => fmtMinuteTime(p.time));
    const timeIdx = new Map(pts.map((p, i) => [p.time, i]));
    const minuteLabelColor = (label: string) =>
      label === "积" ? "#22c55e"
      : label === "派" ? "#f97316"
      : label === "扫" ? "#e11d48"
      : label === "突" ? "#ef4444"
      : label === "破" ? "#22c55e"
      : label === "变" ? "#f59e0b"
      : label === "顶" || label.startsWith("S") || label === "警" ? "#3b82f6"
      : "#ef4444"; // 底 / B1/B2/B3 等看涨
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
    const maConfs: Array<[number, string, string]> = [
      [5, "MA5", "#f5f5f4"],
      [10, "MA10", "#fbbf24"],
      [20, "MA20", "#c084fc"],
    ];
    const maSeries = maConfs.map(([period, maName, maColor]) => {
      const vals: (number | null)[] = pts.map((_, i) => {
        if (i < period - 1) return null;
        let s = 0;
        for (let j = i - period + 1; j <= i; j++) s += pts[j].price;
        return s / period;
      });
      return {
        name: maName,
        type: "line" as const,
        data: vals,
        showSymbol: false,
        lineStyle: { width: 1, color: maColor },
        emphasis: { disabled: true },
        z: 2,
      };
    });
    chart.clear();
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        formatter: (params: unknown) => {
          const list = params as Array<{ dataIndex: number }>;
          const idx = list[0]?.dataIndex ?? 0;
          const p = pts[idx];
          if (!p) return "";
          const chgPct = pc ? ((p.price - pc) / pc) * 100 : 0;
          const col = chgPct >= 0 ? "#ef4444" : "#22c55e";
          const maText = maConfs
            .map(([period, maName]) => {
              if (idx < period - 1) return "";
              let s = 0;
              for (let j = idx - period + 1; j <= idx; j++) s += pts[j].price;
              return `${maName} ${(s / period).toFixed(2)}`;
            })
            .filter(Boolean)
            .join("　");
          return `${fmtMinuteTime(p.time)}<br/>价 ${p.price.toFixed(2)}　均价 ${p.avg_price.toFixed(2)}<br/>涨幅 <span style="color:${col}">${chgPct >= 0 ? "+" : ""}${chgPct.toFixed(2)}%</span><br/>${maText}<br/>量 ${fmt(p.volume)}`;
        },
      },
      legend: {
        data: ["价格", "均价", "成交量", "MA5", "MA10", "MA20", ...(minuteSignals && minuteSignals.intraday.length > 0 ? ["分时信号"] : [])],
        textStyle: { color: "#a8a29e" },
        top: 0,
      },
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
              ...(dayRefData
                ? [
                    {
                      yAxis: dayRefData.ref_bar.high,
                      lineStyle: { color: "rgba(251,191,36,.7)", type: "dashed", width: 1 },
                      label: { color: "#fbbf24", formatter: `昨高 ${dayRefData.ref_bar.high}` },
                    },
                    {
                      yAxis: dayRefData.ref_bar.low,
                      lineStyle: { color: "rgba(52,211,153,.7)", type: "dashed", width: 1 },
                      label: { color: "#34d399", formatter: `昨低 ${dayRefData.ref_bar.low}` },
                    },
                    ...(dayRefData.atr.upper != null
                      ? [
                          {
                            yAxis: dayRefData.atr.upper,
                            lineStyle: { color: "rgba(249,115,22,.65)", type: "dashed", width: 1 },
                            label: { color: "#f97316", formatter: `ATR上 ${dayRefData.atr.upper}` },
                          },
                        ]
                      : []),
                    ...(dayRefData.atr.lower != null
                      ? [
                          {
                            yAxis: dayRefData.atr.lower,
                            lineStyle: { color: "rgba(6,182,212,.65)", type: "dashed", width: 1 },
                            label: { color: "#06b6d4", formatter: `ATR下 ${dayRefData.atr.lower}` },
                          },
                        ]
                      : []),
                    ...(dayRefData.zhongshu.slice(-1).flatMap((z) => [
                      {
                        yAxis: z.zd,
                        lineStyle: { color: "rgba(96,165,250,.6)", type: "dotted", width: 1 },
                        label: { color: "#60a5fa", formatter: `中枢下 ${z.zd}` },
                      },
                      {
                        yAxis: z.zg,
                        lineStyle: { color: "rgba(96,165,250,.6)", type: "dotted", width: 1 },
                        label: { color: "#60a5fa", formatter: `中枢上 ${z.zg}` },
                      },
                    ])),
                    ...dayRefData.chan_points.slice(-4).map((p) => ({
                      yAxis: p.price,
                      lineStyle: {
                        color: p.kind.startsWith("buy") ? "rgba(239,68,68,.65)" : "rgba(59,130,246,.65)",
                        type: "dashed" as const,
                        width: 1,
                      },
                      label: {
                        color: p.kind.startsWith("buy") ? "#ef4444" : "#3b82f6",
                        formatter: `${p.kind.toUpperCase()} ${p.price}`,
                      },
                    })),
                  ]
                : []),
              ...(minuteSignals && minuteSignals.recent.length > 0
                ? minuteSignals.recent.slice(-6).map((s) => ({
                    yAxis: s.price,
                    lineStyle: { color: "rgba(168,162,158,.4)", type: "dotted", width: 1 },
                    label: { color: "#a8a29e", formatter: `${s.label} ${s.price}` },
                  }))
                : []),
            ],
          },
        },
        ...maSeries,
        ...(minuteSignals && minuteSignals.intraday.length > 0
          ? [
              {
                name: "分时信号",
                type: "scatter" as const,
                data: minuteSignals.intraday
                  .map((s) => {
                    const i = timeIdx.get(s.time ?? "");
                    if (i === undefined) return null;
                    const gap = (hi - lo) * 0.012;
                    const bullish = ["底", "B1", "B2", "B3", "积", "突"].includes(s.label);
                    return {
                      value: [i, bullish ? pts[i].price - gap : pts[i].price + gap],
                      color: minuteLabelColor(s.label),
                      label: s.label,
                      time: s.time,
                      note: s.note,
                    };
                  })
                  .filter((v): v is { value: [number, number]; color: string; label: string; time: string; note: string } => v !== null),
                symbol: "circle",
                symbolSize: 6,
                itemStyle: { color: "#a8a29e", opacity: 0.65 },
                label: {
                  show: true,
                  position: "inside",
                  color: (p: unknown) => (p as { data?: { color?: string } }).data?.color ?? "#fff",
                  fontSize: 10,
                  fontWeight: 800,
                  backgroundColor: "rgba(0,0,0,.55)",
                  padding: [1, 2],
                  borderRadius: 2,
                },
                tooltip: {
                  show: true,
                  formatter: (p: unknown) => {
                    const it = p as { data?: { label?: string; time?: string; note?: string } };
                    return it.data ? `<b>${it.data.label}</b>（${fmtMinuteTime(it.data.time ?? "")}）<br/>${it.data.note ?? ""}` : "";
                  },
                },
                z: 10,
              },
            ]
          : []),
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
  }, [tab, minute, minuteSignals]);

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

  // 点击 BS 点：把图定位（缩放）到该点附近
  const locate = (date: string) => {
    const chart = chartRef.current;
    if (!chart) return;
    const list = parseBars(bars);
    const idx = list.findIndex((b) => b.date.slice(0, 16) === date);
    if (idx < 0 || list.length === 0) return;
    const windowSize = Math.max(30, Math.floor(list.length / 5));
    const start = Math.max(0, Math.min(idx - Math.floor(windowSize / 2), list.length - windowSize));
    ignoreZoomRef.current = true;
    chart.dispatchAction({
      type: "dataZoom",
      startValue: list[start].date,
      endValue: list[Math.min(start + windowSize, list.length - 1)].date,
    });
    window.setTimeout(() => {
      ignoreZoomRef.current = false;
    }, 800);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className={
          maximized
            ? "glass fixed inset-0 z-[60] flex h-full w-full flex-col p-2"
            : "glass flex h-[88vh] w-[min(94vw,980px)] flex-col p-4"
        }
        onClick={(e) => e.stopPropagation()}
      >
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
          <button
            onClick={() => setChanOn((v) => !v)}
            className={cn(
              "ml-2 rounded-md px-2 py-1 text-xs",
              chanOn ? "bg-warning/15 font-medium text-warning" : "bg-muted/40 text-muted-foreground hover:text-foreground",
            )}
            title="缠论买卖点/中枢/笔（简化口径）"
          >
            缠论{chanOn ? "开" : "关"}
          </button>
          <button
            onClick={() => setAtrOn((v) => !v)}
            className={cn(
              "ml-1 rounded-md px-2 py-1 text-xs",
              atrOn ? "bg-orange-500/15 font-medium text-orange-400" : "bg-muted/40 text-muted-foreground hover:text-foreground",
            )}
            title="ATR 通道：超涨/超跌标记 + 潜在顶底（任意周期）"
          >
            ATR{atrOn ? "开" : "关"}
          </button>
          <button
            onClick={() => setWyckoffOn((v) => !v)}
            className={cn(
              "ml-1 rounded-md px-2 py-1 text-xs",
              wyckoffOn ? "bg-cyan-500/15 font-medium text-cyan-400" : "bg-muted/40 text-muted-foreground hover:text-foreground",
            )}
            title="通俗信号：积=低位吸筹（看涨）、派=高位派发（看跌）"
          >
            积派{wyckoffOn ? "开" : "关"}
          </button>
          <button
            onClick={() => setSmcOn((v) => !v)}
            className={cn(
              "ml-1 rounded-md px-2 py-1 text-xs",
              smcOn ? "bg-fuchsia-500/15 font-medium text-fuchsia-400" : "bg-muted/40 text-muted-foreground hover:text-foreground",
            )}
            title="通俗信号：扫=洗盘扫荡、突=向上突破、破=向下破位、变=结构变化"
          >
            扫突{smcOn ? "开" : "关"}
          </button>
          <select
            value={barCount}
            onChange={(e) => {
              const v = Number(e.target.value);
              setBarCount(v);
              setViewCount(v);
            }}
            className="ml-1 rounded-md bg-muted/40 px-1.5 py-1 text-xs text-muted-foreground outline-none hover:text-foreground"
            title="K 线最大根数（缩放时按可见范围重新计算指标）"
          >
            <option value={250}>250根</option>
            <option value={500}>500根</option>
            <option value={800}>800根</option>
          </select>
          <button
            onClick={() => setFollowZoom((v) => !v)}
            className={cn(
              "ml-1 rounded-md px-2 py-1 text-xs",
              followZoom ? "bg-sky-500/15 font-medium text-sky-400" : "bg-muted/40 text-muted-foreground hover:text-foreground",
            )}
            title="缩放时按可见窗口重新计算均线/缠论/ATR；关闭后指标基于全量数据（专业模式）"
          >
            跟随{followZoom ? "开" : "关"}
          </button>
          <button
            onClick={() => {
              setMaximized((v) => !v);
              window.setTimeout(() => chartRef.current?.resize(), 80);
            }}
            className="ml-2 text-muted-foreground hover:text-foreground"
            title={maximized ? "还原窗口" : "最大化窗口"}
          >
            {maximized ? "还原" : "全屏"}
          </button>
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
        {resonance && (
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
            <span
              className={cn(
                "rounded-md px-2 py-0.5 font-bold",
                resonance.score >= 30
                  ? "bg-danger/15 text-danger"
                  : resonance.score <= -30
                    ? "bg-success/15 text-success"
                    : "bg-muted/40 text-muted-foreground",
              )}
              title={`${resonance.note ?? ""}\n${resonance.notes.join("\n")}`}
            >
              共振 {resonance.score > 0 ? "+" : ""}
              {resonance.score} {resonance.rating}
            </span>
            <span className="text-muted-foreground" title={`市场权重 ${Math.round(resonance.weights.market * 100)}% · 得分 ${resonance.market.score}`}>
              市场 {resonance.market.label}
            </span>
            <span className="text-muted-foreground" title={`威科夫权重 ${Math.round(resonance.weights.wyckoff * 100)}% · 得分 ${resonance.wyckoff.score}\n${resonance.wyckoff.signals.join("\n")}`}>
              威科夫 {resonance.wyckoff.phase_label}
            </span>
            <span className="text-muted-foreground" title={`SMC 权重 ${Math.round(resonance.weights.smc * 100)}% · 得分 ${resonance.smc.score}\n${resonance.smc.notes.join("\n")}`}>
              SMC {resonance.smc.structure === "bullish" ? "多" : resonance.smc.structure === "bearish" ? "空" : "震荡"}
            </span>
          </div>
        )}
        {chanOn && chanData && chanData.points.length > 0 && (
          <div className="mb-2 flex max-h-16 flex-wrap gap-1.5 overflow-auto">
            {chanData.points.map((p) => {
              const isBuy = p.kind.startsWith("buy");
              return (
                <button
                  key={`${p.kind}-${p.date}`}
                  onClick={() => locate(p.date)}
                  title={`点击定位：${p.note}`}
                  className={cn(
                    "rounded border px-2 py-0.5 text-[11px] font-semibold transition-colors",
                    isBuy
                      ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/20"
                      : "border-blue-400/40 bg-blue-400/10 text-blue-400 hover:bg-blue-400/20",
                  )}
                >
                  {p.kind.toUpperCase()} {p.date.slice(5)} {p.price.toFixed(2)}
                </button>
              );
            })}
          </div>
        )}
        {atrOn && atrData && atrData.signals.filter((s) => s.kind === "top" || s.kind === "bottom").length > 0 && (
          <div className="mb-2 flex max-h-16 flex-wrap gap-1.5 overflow-auto">
            {atrData.signals
              .filter((s) => s.kind === "top" || s.kind === "bottom")
              .map((s) => (
                <button
                  key={`${s.kind}-${s.date}`}
                  onClick={() => locate(s.date)}
                  title={s.note}
                  className={cn(
                    "rounded border px-2 py-0.5 text-[11px] font-semibold transition-colors",
                    s.kind === "top"
                      ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/20"
                      : "border-emerald-400/40 bg-emerald-400/10 text-emerald-400 hover:bg-emerald-400/20",
                  )}
                >
                  {s.kind === "top" ? "顶" : "底"} {s.date.slice(5)} {s.price.toFixed(2)}
                </button>
              ))}
          </div>
        )}
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

export { KLineModal };

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
  const { data: marketRegime } = usePolling<MarketRegime>(fetchMarketRegime, 300_000, true, false);

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

      {/* 市场趋势（道士理论 + 趋势跟踪：宽基指数状态聚合） */}
      {marketRegime && (
        <GlassCard className="mb-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Activity className="h-3.5 w-3.5" /> 市场趋势
            </span>
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs font-semibold",
                marketRegime.market.state.startsWith("up")
                  ? "bg-danger/15 text-danger"
                  : marketRegime.market.state.startsWith("down")
                    ? "bg-success/15 text-success"
                    : "bg-muted/40 text-muted-foreground",
              )}
              title={`趋势得分 ${marketRegime.market.score}`}
            >
              {marketRegime.market.label}
            </span>
            <span className="text-[11px] text-muted-foreground">
              上升 {marketRegime.market.up_count} / 下跌 {marketRegime.market.down_count}
            </span>
            <div className="ml-auto flex flex-wrap gap-x-3 gap-y-0.5">
              {marketRegime.indices.map((ix) => (
                <span key={ix.code} className="text-[11px]">
                  <b className={cn(ix.state === "up" ? "text-danger" : ix.state === "down" ? "text-success" : "text-muted-foreground")}>
                    {ix.name}
                  </b>{" "}
                  <span className={cn("font-mono", ix.ret20_pct >= 0 ? "text-danger" : "text-success")}>
                    {ix.ret20_pct > 0 ? "+" : ""}
                    {ix.ret20_pct.toFixed(1)}%
                  </span>
                  <span className="ml-1 text-muted-foreground/60">
                    {ix.state === "up" ? "升" : ix.state === "down" ? "跌" : "震荡"}
                    {ix.structure === "higher_high" ? "·高点新高" : ix.structure === "lower_low" ? "·低点新低" : ""}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </GlassCard>
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
