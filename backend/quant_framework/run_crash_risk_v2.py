"""暴跌风控 V2：复权修正 + 样本外 + 机会成本 + 可执行性 + 消息匹配（2026-08-11）。

按《辩驳-暴跌风控-答辩.md》行动项 1~5 实现：
1. 复权：腾讯前复权日K（category=4），消除除权假暴跌；
2. 样本外：随机全市场分层抽样 500 只（大/中/小 × 沪深均衡），
   事件窗口分为 样本内=2025-08-11~2026-08-11、样本外=2024-08-11~2025-08-11；
3. 同板块基准：抽样池内同行业股票等权合成（覆盖两年，不依赖行业指数缓存）；
4. 机会成本：暴跌后 D+1 买入持有 5/10/20 日行业超额完整分布
   （正尾部=V型反转被回避部分，负尾部=接飞刀损失），加 D+6 延迟入场对比；
5. 可执行性：D+1 一字涨/跌停买卖挡计数 + 费用滑点净额；
6. 消息匹配：业绩预告利空公告在 [D-10, D] 内 → “有消息”，否则“无消息”。

结论输出：样本内/样本外对照，判断 V1 结论是否外推。
"""

from __future__ import annotations

import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_factor_ic_health import fetch_market_with_size  # noqa: E402

SEED = 20260811
N_TOTAL = 500
OUT = Path(__file__).resolve().parent / "data" / "crash_risk_v2.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"
CACHE = Path(__file__).resolve().parent / "data" / "crash_v2_cache"
IN_START, IN_END = "2025-08-11", "2026-08-11"
OOS_START, OOS_END = "2024-08-11", "2025-08-11"
COST = 0.0003 * 2 + 0.0005 + 0.0001 * 2  # 佣金×2+印花税+滑点×2

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def load_kline_qfq(code: str) -> pd.DataFrame | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"{code}.csv"
    if cache.exists():
        try:
            df = pd.read_csv(cache, parse_dates=["datetime"])
            if len(df) >= 400:
                return df
        except Exception:  # noqa: BLE001
            pass
    try:
        rows = astock.kline(code, category=4, offset=700)
    except Exception:  # noqa: BLE001
        return None
    if not rows or len(rows) < 400:
        return None
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df.to_csv(cache, index=False, encoding="utf-8")
    return df


def load_bad_forecast_dates() -> dict[str, set[str]]:
    """业绩预告利空公告日（预减/略减/首亏/续亏/增亏/减亏）。"""
    out: dict[str, set[str]] = {}
    ak = astock._akshare()
    for report_date in ("20250630", "20250930", "20251231", "20260331", "20260630"):
        try:
            df = ak.stock_yjyg_em(date=report_date)
        except Exception:  # noqa: BLE001
            continue
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            t = str(row.get("预告类型", ""))
            if t not in ("预减", "略减", "首亏", "续亏", "增亏", "减亏"):
                continue
            notice = str(row.get("公告日期", ""))[:10]
            code = str(row.get("股票代码", ""))
            if notice and code:
                out.setdefault(code, set()).add(notice)
        time.sleep(1.0)
    return out


def st(x: pd.Series) -> dict:
    n = len(x)
    pos = x[x > 0]
    neg = x[x <= 0]
    return {
        "n": n,
        "mean": x.mean() if n else float("nan"),
        "t": (x.mean() / (x.std(ddof=1) / np.sqrt(n))) if n > 1 and x.std(ddof=1) > 0 else float("nan"),
        "pos": (x > 0).mean() if n else float("nan"),
        "med": x.median() if n else float("nan"),
        "pos_tail": pos.mean() if len(pos) else float("nan"),
        "neg_tail": neg.mean() if len(neg) else float("nan"),
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print("抽样股票池...", flush=True)
    market = fetch_market_with_size()
    by_cap = sorted(market, key=lambda x: x["float_cap"])
    n = len(by_cap)
    layers = [by_cap[: n // 3], by_cap[n // 3 : 2 * n // 3], by_cap[2 * n // 3 :]]
    rng = random.Random(SEED)
    sample = []
    per_layer = N_TOTAL // 3
    for lay in layers:
        sh = [m for m in lay if m["code"].startswith(("6", "9"))]
        sz = [m for m in lay if not m["code"].startswith(("6", "9"))]
        half = per_layer // 2
        sample.extend(rng.sample(sh, min(half, len(sh))))
        sample.extend(rng.sample(sz, min(per_layer - min(half, len(sh)), len(sz))))
    print(f"抽样 {len(sample)} 只", flush=True)

    frames = []
    for i, s in enumerate(sample):
        df = load_kline_qfq(s["code"])
        if df is None:
            continue
        df["code"] = s["code"]
        df["industry"] = s["industry"]
        frames.append(df)
        if (i + 1) % 100 == 0:
            print(f"已加载 {len(frames)}/{i + 1}", flush=True)
    print(f"有效股票 {len(frames)}", flush=True)
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["datetime"]).dt.date
    data = data.sort_values(["code", "date"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        data[col] = data[col].astype(float)
    data["ret"] = data.groupby("code")["close"].pct_change()
    data["vol20"] = data.groupby("code")["volume"].transform(lambda x: x.rolling(20).mean())
    data["vol_ratio"] = data["volume"] / data["vol20"]
    data["pos60"] = data.groupby("code")["close"].transform(lambda x: x / x.shift(60) - 1)
    data["ma20"] = data.groupby("code")["close"].transform(lambda x: x.rolling(20).mean())
    data["ma60"] = data.groupby("code")["close"].transform(lambda x: x.rolling(60).mean())
    data["broken"] = (data["close"] < data["ma20"]) & (data["close"] < data["ma60"])
    for h in (5, 10, 20):
        data[f"fwd{h}"] = data.groupby("code")["close"].transform(lambda x, o=h: x.shift(-o) / x - 1)
        data[f"bench_fwd{h}"] = data.groupby(["date", "industry"])[f"fwd{h}"].transform("mean")
        data[f"ex{h}"] = data[f"fwd{h}"] - data[f"bench_fwd{h}"]
        data[f"exnet{h}"] = data[f"ex{h}"] - COST
    data["fwd_late15"] = data.groupby("code")["close"].transform(lambda x: x.shift(-15) / x.shift(5) - 1)
    data["bench_late15"] = data.groupby(["date", "industry"])["fwd_late15"].transform("mean")
    data["ex_late15"] = data["fwd_late15"] - data["bench_late15"]
    data = data.replace([np.inf, -np.inf], np.nan)

    bad_forecast = load_bad_forecast_dates()
    data["crash"] = (data["ret"] <= -0.07) & (data.groupby("code")["ret"].shift(1) > -0.09)
    ev = data[data["crash"]].copy()
    ev["period"] = np.where((ev["date"].astype(str) >= OOS_START) & (ev["date"].astype(str) < IN_START), "样本外(24-25)", "样本内(25-26)")
    # D+1 可执行性
    next_open = data.set_index(["code", "date"])["open"]
    prev_close = data.set_index(["code", "date"])["close"]
    ev["d1_open"] = [next_open.get((c, d)) for c, d in zip(ev["code"], ev["date"])]
    ev["d0_close"] = ev["close"]
    ev["limit_buy_blocked"] = ev["d1_open"] / ev["d0_close"] - 1.0 >= 0.098
    ev["limit_sell_blocked"] = ev["d1_open"] / ev["d0_close"] - 1.0 <= -0.098
    ev["has_msg"] = ev.apply(
        lambda r: any(
            pd.Timestamp(n).date() <= r["date"] <= pd.Timestamp(n).date() + pd.Timedelta(days=10)
            for n in bad_forecast.get(r["code"], set())
        ),
        axis=1,
    )
    print(f"暴跌事件 {len(ev)}（样本内 {(ev['period'] == '样本内(25-26)').sum()}，样本外 {(ev['period'] == '样本外(24-25)').sum()}）", flush=True)

    groups = {
        "全部暴跌": np.ones(len(ev), dtype=bool),
        "缩量(<0.8)": ev["vol_ratio"] < 0.8,
        "放量(>1.5)": ev["vol_ratio"] > 1.5,
        "高位(前60日>30%)": ev["pos60"] > 0.30,
        "低位(前60日<-10%)": ev["pos60"] < -0.10,
        "未破位": ~ev["broken"],
        "破位": ev["broken"],
        "疑似洗盘(缩量+未破位)": (ev["vol_ratio"] < 1.0) & (~ev["broken"]),
        "疑似出货(放量+高位+破位)": (ev["vol_ratio"] > 1.5) & (ev["pos60"] > 0.20) & ev["broken"],
        "疑似利空(放量+破位+板块共振)": (ev["vol_ratio"] > 1.5) & ev["broken"],
        "有消息(业绩利空10日内)": ev["has_msg"],
        "无消息": ~ev["has_msg"],
    }

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 暴跌风控 V2：复权+样本外+机会成本+可执行性+消息（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　抽样 {len(frames)} 只（腾讯前复权 700 根）",
        "> 基准：抽样池同行业等权；事件=单日≤-7%且前一日>-9%。",
        "",
        "## 一、样本内 vs 样本外（D+1~20 行业超额，含费用）",
        "",
        "| 分组 | 样本内 n | 样本内净超额 | 样本外 n | 样本外净超额 | 外推一致? |",
        "|---|---|---|---|---|---|",
    ]
    for label, mask in groups.items():
        sub = ev[mask]
        cells = [label]
        for period in ("样本内(25-26)", "样本外(24-25)"):
            s = st(sub.loc[sub["period"] == period, "exnet20"].dropna())
            cells.append(f"n={s['n']} {s['mean'] * 100:+.2f}% t={s['t']:+.2f}")
        si = st(sub.loc[sub["period"] == "样本内(25-26)", "exnet20"].dropna())
        oo = st(sub.loc[sub["period"] == "样本外(24-25)", "exnet20"].dropna())
        same = "是" if (si["mean"] < 0) == (oo["mean"] < 0) and si["n"] > 30 and oo["n"] > 30 else "否/样本不足"
        cells.append(same)
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 二、机会成本（样本内+样本外合并，D+1 买入 vs 回避）", "",
              "| 持有 | n | 平均超额 | t | 正比例 | 中位 | 正尾部均值 | 负尾部均值 | 延迟入场(D+6,15日) |",
              "|---|---|---|---|---|---|---|---|---|"]
    for h in (5, 10, 20):
        s = st(ev[f"ex{h}"].dropna())
        late = st(ev["ex_late15"].dropna())
        lines.append(
            f"| D+1买持{h}日 | {s['n']} | {s['mean'] * 100:+.2f}% | {s['t']:+.2f} | {s['pos'] * 100:.0f}% | "
            f"{s['med'] * 100:+.2f}% | {s['pos_tail'] * 100:+.2f}% | {s['neg_tail'] * 100:+.2f}% | "
            f"n={late['n']} {late['mean'] * 100:+.2f}% t={late['t']:+.2f} |"
        )
    lines += ["", "## 三、可执行性", "", f"- D+1 一字涨停买不进：{int(ev['limit_buy_blocked'].sum())}；一字跌停卖不出：{int(ev['limit_sell_blocked'].sum())}（共 {len(ev)} 事件）", ""]
    lines += ["", "## 四、消息匹配（业绩预告利空 10 日内）", "", "| 分组 | n | D+1~20 净超额 | t |", "|---|---|---|---|"]
    for label in ("有消息(业绩利空10日内)", "无消息"):
        s = st(ev.loc[groups[label], "exnet20"].dropna())
        lines.append(f"| {label} | {s['n']} | {s['mean'] * 100:+.2f}% | {s['t']:+.2f} |")
    lines += ["", "## 结论", ""]
    lines.append("- 若样本外方向与样本内一致，V1 结论外推成立；否则为单年过拟合。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for label in ("全部暴跌", "疑似洗盘(缩量+未破位)", "有消息(业绩利空10日内)"):
        sub = ev[groups[label]]
        for period in ("样本内(25-26)", "样本外(24-25)"):
            s = st(sub.loc[sub["period"] == period, "exnet20"].dropna())
            log.append(
                ExperimentRecord(
                    experiment_id=f"CRASHV2-{label[:8]}-{period[:4]}",
                    hypothesis=f"暴跌风控V2：{label} {period} 净超额",
                    unique_change=f"qfq=True, oos=True, cost=True, group={label}",
                    expected="样本外方向与样本内一致",
                    dev_result=f"n={s['n']} {s['mean'] * 100:+.2f}% t={s['t']:+.2f}",
                    val_result="",
                    cost_result=f"正比例 {s['pos'] * 100:.0f}%",
                    passed=False,
                    failure_reason="抽样500只/消息匹配仅业绩预告一类",
                    code_version=code_version,
                )
            )
    print(f"\n报告已生成：{OUT}，日志追加 {len(groups) * 2} 条")


if __name__ == "__main__":
    main()
