"""混合体检 Part 2：事件驱动 CAR 体检（2026-08-11）。

三类事件 × 抽样池 297 只（复用 factor_cache K 线）：
- 龙虎榜：东财 RPT_DAILYBILLBOARD_DETAILSNEW，最近 6 个月；
- 限售解禁：东财 RPT_LIFT_STAGE，最近 6 个月；
- 业绩预告：akshare stock_yjyg_em（2025 中报/三季报/年报 + 2026 一季报），
  公告日作为事件日。

基准：东财行业指数（同板块对照，复用 factor_cache/bk_*.csv）；
无行业指数的事件用抽样池等权基准兜底。
窗口：CAR(-10,-1) 事件前 / CAR(0,1) 事件日+次日 / CAR(2,5) / CAR(2,10) / CAR(2,20)。
局限：业绩预告未区分盘前/盘后披露；事件股仅限抽样池；单一年窗口。
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_factor_ic_health import CACHE_DIR, fetch_market_with_size  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "event_health.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"
LOOKBACK_START = (datetime.now() - timedelta(days=183)).strftime("%Y-%m-%d")
LOOKBACK_END = datetime.now().strftime("%Y-%m-%d")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def dc_all(report: str, filter_str: str, sort_columns: str, sort_types: str, page_size: int = 500, max_pages: int = 100) -> list[dict]:
    out: list[dict] = []
    for pn in range(1, max_pages + 1):
        params = {
            "reportName": report, "columns": "ALL", "filter": filter_str,
            "pageNumber": str(pn), "pageSize": str(page_size),
            "sortColumns": sort_columns, "sortTypes": sort_types,
            "source": "WEB", "client": "WEB",
        }
        try:
            d = astock.em_get(astock._DATACENTER_URL, params=params, timeout=20).json()
        except Exception as e:  # noqa: BLE001
            print("dc warn", report, pn, e, flush=True)
            break
        rows = ((d.get("result") or {}).get("data")) or []
        if not rows:
            break
        out.extend(rows)
        if len(rows) < page_size:
            break
        time.sleep(1.0)
    return out


def load_events() -> dict[str, list[dict]]:
    print("拉龙虎榜...", flush=True)
    lhb = dc_all(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        f"(TRADE_DATE>='{LOOKBACK_START}')(TRADE_DATE<='{LOOKBACK_END}')",
        "TRADE_DATE", "-1",
    )
    lhb_ev = [
        {"code": str(r.get("SECURITY_CODE", "")), "date": str(r.get("TRADE_DATE", ""))[:10],
         "type": "龙虎榜", "detail": str(r.get("EXPLANATION", "")),
         "net_buy": r.get("BILLBOARD_NET_AMT") or 0, "turnover": r.get("TURNOVERRATE") or 0}
        for r in lhb if r.get("SECURITY_CODE")
    ]
    print(f"龙虎榜事件 {len(lhb_ev)}", flush=True)

    print("拉解禁...", flush=True)
    lift = dc_all(
        "RPT_LIFT_STAGE",
        f"(FREE_DATE>='{LOOKBACK_START}')(FREE_DATE<='{LOOKBACK_END}')",
        "FREE_DATE", "1",
    )
    lift_ev = [
        {"code": str(r.get("SECURITY_CODE", "")), "date": str(r.get("FREE_DATE", ""))[:10],
         "type": "解禁", "detail": str(r.get("FREE_SHARES_TYPE", "")),
         "ratio": r.get("FREE_RATIO") or 0}
        for r in lift if r.get("SECURITY_CODE")
    ]
    print(f"解禁事件 {len(lift_ev)}", flush=True)

    print("拉业绩预告...", flush=True)
    yjyg_ev: list[dict] = []
    for report_date in ("20250630", "20250930", "20251231", "20260331"):
        try:
            ak = astock._akshare()
            df = ak.stock_yjyg_em(date=report_date)
        except Exception as e:  # noqa: BLE001
            print("yjyg warn", report_date, e, flush=True)
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            notice = str(row.get("公告日期", ""))[:10]
            if not notice or not (LOOKBACK_START <= notice <= LOOKBACK_END):
                continue
            yjyg_ev.append(
                {"code": str(row.get("股票代码", "")), "date": notice,
                 "type": "业绩预告", "detail": str(row.get("预告类型", "")),
                 "change": row.get("业绩变动幅度")}
            )
        time.sleep(1.0)
    print(f"业绩预告事件 {len(yjyg_ev)}", flush=True)
    return {"龙虎榜": lhb_ev, "解禁": lift_ev, "业绩预告": yjyg_ev}


def industry_map() -> tuple[dict[str, str], dict[str, str]]:
    """code->行业名（全市场 f100）与 BK code->行业名（行业指数列表）。"""
    market = fetch_market_with_size()
    code_ind = {m["code"]: m["industry"] for m in market}
    blocks: dict[str, str] = {}
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        for pn in range(1, 6):
            try:
                import requests

                r = requests.get(
                    f"https://{host}/api/qt/clist/get",
                    params={
                        "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                        "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3",
                    },
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                    timeout=15, proxies={"http": None, "https": None},
                )
                diff = (r.json().get("data") or {}).get("diff") or []
                if not diff:
                    break
                items = diff.values() if isinstance(diff, dict) else diff
                for it in items:
                    blocks[str(it.get("f12", ""))] = str(it.get("f14", "") or "")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
        if blocks:
            break
    return code_ind, blocks


def load_pool() -> dict[str, pd.DataFrame]:
    out = {}
    for f in CACHE_DIR.glob("*.csv"):
        if f.name.startswith("bk_"):
            continue
        code = f.stem
        try:
            df = pd.read_csv(f, parse_dates=["datetime"])
        except Exception:  # noqa: BLE001
            continue
        if len(df) >= 120:
            out[code] = df.sort_values("datetime").reset_index(drop=True)
    return out


def ret_series(df: pd.DataFrame) -> pd.Series:
    s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["datetime"]).dt.date)
    return s.pct_change()


def car_for(code: str, d: str, stock_rets: dict, bench_rets: dict, pool_rets: pd.Series) -> dict | None:
    d0 = pd.Timestamp(d).date()
    sr = stock_rets.get(code)
    if sr is None:
        return None
    dates = list(sr.index)
    if d0 not in dates:
        return None
    pos = dates.index(d0)
    if pos < 10 or pos + 21 >= len(dates):
        return None
    br = bench_rets.get(code, pool_rets)
    ar = sr - br.reindex(sr.index).fillna(0.0)
    car = {}
    for label, a, b in (("pre10", -10, -1), ("post01", 0, 1), ("post25", 2, 5), ("post210", 2, 10), ("post220", 2, 20)):
        car[label] = float(ar.iloc[pos + a : pos + b + 1].sum())
    return car


def summarize(events: list[dict], stock_rets: dict, bench_rets: dict, pool_rets: pd.Series, group_key=None) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for e in events:
        g = group_key(e) if group_key else "全部"
        c = car_for(e["code"], e["date"], stock_rets, bench_rets, pool_rets)
        if c:
            groups.setdefault(g, []).append(c)
    out = []
    for g, cars in groups.items():
        a = np.array([c["pre10"] for c in cars])
        b = np.array([c["post01"] for c in cars])
        c2 = np.array([c["post25"] for c in cars])
        d2 = np.array([c["post210"] for c in cars])
        e2 = np.array([c["post220"] for c in cars])
        n = len(cars)
        row = {
            "group": g, "n": n,
            "pre10": a.mean() if n else float("nan"), "post01": b.mean() if n else float("nan"),
            "post25": c2.mean() if n else float("nan"), "post210": d2.mean() if n else float("nan"),
            "post220": e2.mean() if n else float("nan"),
            "t20": (e2.mean() / (e2.std(ddof=1) / np.sqrt(n))) if n > 1 and e2.std(ddof=1) > 0 else float("nan"),
            "pos20": (e2 > 0).mean() if n else float("nan"),
        }
        out.append(row)
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    events = load_events()
    code_ind, blocks = industry_map()
    print(f"行业映射 code={len(code_ind)} blocks={len(blocks)}", flush=True)
    pool = load_pool()
    print(f"股票池 {len(pool)}", flush=True)
    stock_rets = {c: ret_series(df) for c, df in pool.items()}
    pool_ret = pd.concat([s for s in stock_rets.values()], axis=1).mean(axis=1)
    pool_ret = pool_ret.sort_index()
    bench_rets: dict[str, pd.Series] = {}
    for f in CACHE_DIR.glob("bk_*.csv"):
        bk = f.stem[3:]
        name = blocks.get(bk)
        if not name:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["datetime"])
        except Exception:  # noqa: BLE001
            continue
        bench_rets[name] = ret_series(df)
    code_bench: dict[str, pd.Series] = {}
    for c, ind in code_ind.items():
        b = bench_rets.get(ind)
        if b is not None:
            code_bench[c] = b
    print(f"行业基准 {len(bench_rets)} 个，事件股可用行业基准 {sum(1 for c in code_bench)}", flush=True)

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 混合体检 Part 2：事件驱动 CAR（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　窗口 {LOOKBACK_START} ~ {LOOKBACK_END}",
        "> 基准：东财行业指数（同板块对照），无行业指数用抽样池等权；",
        "> CAR = 个股累计收益 − 行业指数累计收益；业绩预告以公告日为事件日。",
        "",
        "| 事件 | 分组 | n | CAR(-10,-1) | CAR(0,1) | CAR(2,5) | CAR(2,10) | CAR(2,20) | t(2,20) | 正比例 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def lhb_group(e):
        t = e["detail"]
        if "换手" in t:
            return "高换手"
        if "涨跌幅偏离" in t or "涨幅" in t:
            return "涨跌幅偏离"
        if "连续" in t:
            return "连板"
        return "其他"

    def yjyg_group(e):
        t = e["detail"]
        if t in ("预增", "略增", "扭亏", "续盈"):
            return "利好(预增/扭亏)"
        if t in ("预减", "略减", "首亏", "续亏", "增亏", "减亏"):
            return "利空(预减/亏损)"
        return "不确定"

    def lift_group(e):
        return "高比例(>=3%)" if (e["ratio"] or 0) >= 0.03 else "低比例(<3%)"

    rows = []
    for ev_type, gk in (("龙虎榜", lhb_group), ("解禁", lift_group), ("业绩预告", yjyg_group)):
        evs = events[ev_type]
        for r in summarize(evs, stock_rets, code_bench, pool_ret, gk):
            rows.append(r)
            lines.append(
                f"| {ev_type} | {r['group']} | {r['n']} | {r['pre10'] * 100:+.2f}% | {r['post01'] * 100:+.2f}% | "
                f"{r['post25'] * 100:+.2f}% | {r['post210'] * 100:+.2f}% | {r['post220'] * 100:+.2f}% | "
                f"{r['t20']:+.2f} | {r['pos20'] * 100:.0f}% |"
            )
    lines += ["", "## 结论", ""]
    lines.append("- |t|>2 且 CAR 方向一致才算事件有可交易信息；样本<30 只作方向提示。")
    lines.append("- 局限：抽样池内事件股、业绩预告未区分盘前/盘后披露、单一年窗口。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for r in rows[:8]:
        log.append(
            ExperimentRecord(
                experiment_id=f"EVENT-{r['group']}",
                hypothesis=f"事件驱动体检：{r['group']} 事件后 20 日行业超额收益",
                unique_change=f"event={r['group']}, n={r['n']}",
                expected="|t|>2 且 CAR 为正/负方向一致",
                dev_result=f"CAR(2,20)={r['post220'] * 100:+.2f}%，t={r['t20']:+.2f}",
                val_result="",
                cost_result=f"正比例 {r['pos20'] * 100:.0f}%",
                passed=False,
                failure_reason="抽样池内事件股/单一年窗口/披露时点未区分",
                code_version=code_version,
            )
        )
    print(f"\n报告已生成：{OUT}，日志追加 {len(rows)} 条")


if __name__ == "__main__":
    main()
