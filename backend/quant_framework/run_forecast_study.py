"""利空业绩预告事件研究：全市场扩样本 + 披露次日对齐 + 伪事件对照（2026-08-11）。

针对 Part 2 发现的“利空业绩预告后 2~20 日 +5.59% 反弹”，做三件事：
1. 扩样本：全市场业绩预告（2025 中报/三季报/年报 + 2026 一季报/中报预告），
   事件股逐只拉新浪日K（缓存复用 factor_cache）；
2. 披露时点保守对齐：事件日 = 公告日之后第一个交易日（盘后披露的公告
   不能归因公告日当天），并另报公告日当天反应作参考；
3. 伪事件对照：每只事件股随机取 5 个交易日做同口径行业中性 CAR，
   区分“事件效应”与“该股票本来就超跌/均值回归”。

基准：东财行业指数（同板块对照）；无行业指数用全池等权。
"""

from __future__ import annotations

import random
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
from run_factor_ic_health import CACHE_DIR, fetch_market_with_size, load_kline  # noqa: E402

SEED = 20260811
OUT = Path(__file__).resolve().parent / "data" / "forecast_study.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"
WINDOW_START = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
WINDOW_END = datetime.now().strftime("%Y-%m-%d")
REPORT_DATES = ("20250630", "20250930", "20251231", "20260331", "20260630")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def load_forecasts() -> list[dict]:
    out: list[dict] = []
    ak = astock._akshare()
    for report_date in REPORT_DATES:
        try:
            df = ak.stock_yjyg_em(date=report_date)
        except Exception as e:  # noqa: BLE001
            print("yjyg warn", report_date, e, flush=True)
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            notice = str(row.get("公告日期", ""))[:10]
            if not notice or not (WINDOW_START <= notice <= WINDOW_END):
                continue
            out.append(
                {"code": str(row.get("股票代码", "")), "notice": notice,
                 "type": str(row.get("预告类型", "")), "change": row.get("业绩变动幅度")}
            )
        time.sleep(1.0)
    return out


def group_of(t: str) -> str:
    if t in ("预增", "略增", "扭亏", "续盈"):
        return "利好"
    if t in ("预减", "略减", "首亏", "续亏", "增亏", "减亏"):
        return "利空"
    return "不确定"


def load_bench() -> tuple[dict[str, str], dict[str, pd.Series]]:
    """code->行业名 与 行业名->指数收益序列。"""
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
    bench: dict[str, pd.Series] = {}
    for f in CACHE_DIR.glob("bk_*.csv"):
        name = blocks.get(f.stem[3:])
        if not name:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["datetime"])
        except Exception:  # noqa: BLE001
            continue
        s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["datetime"]).dt.date)
        bench[name] = s.pct_change()
    return code_ind, bench


def ret_series(code: str) -> pd.Series | None:
    df = load_kline(code)
    if df is None:
        return None
    s = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["datetime"]).dt.date)
    return s.pct_change()


def car_around(sr: pd.Series, br: pd.Series | None, e: str, offsets: tuple[tuple[str, int, int], ...]) -> dict | None:
    """以事件日 e（交易日）为中心，计算行业中性 CAR。"""
    e0 = pd.Timestamp(e).date()
    dates = list(sr.index)
    if e0 not in dates:
        return None
    pos = dates.index(e0)
    if pos < 10 or pos + 21 >= len(dates):
        return None
    ar = sr - (br.reindex(sr.index).fillna(0.0) if br is not None else 0.0)
    out = {}
    for label, a, b in offsets:
        out[label] = float(ar.iloc[pos + a : pos + b + 1].sum())
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    events = load_forecasts()
    print(f"业绩预告事件（窗口内）{len(events)}", flush=True)
    code_ind, bench = load_bench()
    print(f"行业映射 code={len(code_ind)} bench={len(bench)}", flush=True)
    rng = random.Random(SEED)

    # 事件日 = 公告日后第一个交易日（保守：盘后披露归因次日）
    rows: list[dict] = []
    pool_ret_cache: pd.Series | None = None
    stock_series: dict[str, pd.Series] = {}
    for ev in events:
        code = ev["code"]
        if code not in stock_series:
            sr = ret_series(code)
            if sr is None:
                continue
            stock_series[code] = sr
        sr = stock_series[code]
        dates = list(sr.index)
        notice = pd.Timestamp(ev["notice"]).date()
        nxt = next((d for d in dates if d > notice), None)
        if nxt is None:
            continue
        ind = code_ind.get(code)
        br = bench.get(ind) if ind else None
        c = car_around(
            sr, br, str(nxt),
            (("d0", 0, 0), ("post15", 1, 5), ("post110", 1, 10), ("post120", 1, 20), ("notice_day", -1, -1)),
        )
        if c is None:
            continue
        c["code"] = code
        c["group"] = group_of(ev["type"])
        c["change"] = ev["change"]
        c["notice"] = ev["notice"]
        c["event_date"] = str(nxt)
        rows.append(c)
        # 伪事件：同股票随机 5 个交易日（避开事件日±10）
        bad = {d for d in dates if abs((d - nxt).days) <= 10}
        cands = [d for d in dates if d not in bad and 10 < dates.index(d) < len(dates) - 21]
        for pseudo in rng.sample(cands, min(5, len(cands))):
            pc = car_around(sr, br, str(pseudo), (("post120", 1, 20),))
            if pc:
                pc["code"] = code
                pc["group"] = "伪事件"
                rows.append(pc)
        if len(stock_series) % 100 == 0:
            print(f"已处理股票 {len(stock_series)}，事件行 {len(rows)}", flush=True)

    df = pd.DataFrame(rows)
    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 利空业绩预告事件研究：全市场 + 次日对齐 + 伪事件对照（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　事件窗口 {WINDOW_START} ~ {WINDOW_END}",
        "> 事件日 = 公告日后第一个交易日（盘后披露不归因公告日）；基准 = 东财行业指数；",
        "> 伪事件 = 同股票随机交易日（避开事件±10日）同口径行业中性 CAR。",
        "",
        "| 分组 | n | 公告日CAR | 后1-5日 | 后1-10日 | 后1-20日 | t(20) | 正比例(20) | 中位(20) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    stats_rows = []
    for g in ("利好", "利空", "不确定", "伪事件"):
        sub = df[df["group"] == g]
        if sub.empty:
            continue
        x = sub["post120"].astype(float)
        n = len(sub)
        row = {
            "group": g, "n": n,
            "d0": sub["d0"].mean() if "d0" in sub else float("nan"),
            "post15": sub["post15"].mean() if "post15" in sub else float("nan"),
            "post110": sub["post110"].mean() if "post110" in sub else float("nan"),
            "post120": x.mean(), "t20": x.mean() / (x.std(ddof=1) / np.sqrt(n)) if n > 1 and x.std(ddof=1) > 0 else float("nan"),
            "pos20": (x > 0).mean(), "med20": x.median(),
        }
        stats_rows.append(row)
        lines.append(
            f"| {g} | {n} | {row['d0'] * 100:+.2f}% | {row['post15'] * 100:+.2f}% | "
            f"{row['post110'] * 100:+.2f}% | {row['post120'] * 100:+.2f}% | "
            f"{row['t20']:+.2f} | {row['pos20'] * 100:.0f}% | {row['med20'] * 100:+.2f}% |"
        )
    lines += ["", "## 利空组按变动幅度分档（业绩变动幅度 %）", "", "| 分档 | n | 后1-20日CAR | t | 正比例 |", "|---|---|---|---|---|"]
    for lo, hi, label in ((float("-inf"), -50, "大幅利空(<=-50%)"), (-50, -10, "中幅利空(-50%~-10%)"), (-10, float("inf"), "小幅利空(>=-10%)")):
        sub = df[(df["group"] == "利空") & pd.to_numeric(df["change"], errors="coerce").between(lo, hi, inclusive="left")]
        if sub.empty:
            continue
        x = sub["post120"].astype(float)
        n = len(sub)
        t = x.mean() / (x.std(ddof=1) / np.sqrt(n)) if n > 1 and x.std(ddof=1) > 0 else float("nan")
        lines.append(f"| {label} | {n} | {x.mean() * 100:+.2f}% | {t:+.2f} | {(x > 0).mean() * 100:.0f}% |")
    lines += ["", "## 结论", ""]
    lines.append("- 利空组后1-20日CAR相对伪事件的正增量，才是事件本身的信息；若与伪事件无差异，则只是超跌回归。")
    lines.append("- 局限：披露时点按次日保守对齐，未区分盘前披露；K线为新浪不复权；单一年窗口。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for r in stats_rows[:5]:
        log.append(
            ExperimentRecord(
                experiment_id=f"FORECAST-{r['group']}",
                hypothesis=f"业绩预告{('利空' if r['group'] == '利空' else '事件')}后行业中性CAR全市场复测",
                unique_change=f"group={r['group']}, n={r['n']}, event=notice+1",
                expected="利空组相对伪事件有正增量才算事件效应",
                dev_result=f"CAR(1,20)={r['post120'] * 100:+.2f}%，t={r['t20']:+.2f}",
                val_result="",
                cost_result=f"正比例 {r['pos20'] * 100:.0f}%",
                passed=False,
                failure_reason="单一年窗口/披露时点按次日保守对齐/不复权",
                code_version=code_version,
            )
        )
    print(f"\n报告已生成：{OUT}，日志追加 {len(stats_rows)} 条")


if __name__ == "__main__":
    main()
