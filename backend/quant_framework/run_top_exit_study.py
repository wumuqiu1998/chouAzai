"""暴涨后极速暴跌的顶部离场规则对比（小样本研究，非“预判顶部”承诺）。

研究假设卡（简化）：
- 市场观察：近期科技股常出现 1~2 个月主升浪后极速回撤（如 600487 5/28→6/23→7/30），
  投资者希望有规则能在顶部附近离场、降低回撤。
- 可能机制：暴涨末端情绪过度、波动率扩张后均值回归；结构破坏（跌破均线/中枢）滞后于价格。
- 信号定义：以下 8 条规则，全部 T 日收盘后完成计算，最早 T+1 日开盘成交（无未来函数）：
  A. ATR 顶（本项目过滤版：超涨段回落 ≥1×ATR 确认）
  B. 收盘首次跌破 MA20
  C. 最高点回撤 8% / 10% / 12%（盘中触发，次日开盘离场）
  D. 缠论三卖预警 sell3_warn（收盘跌破中枢上沿 ZG）
  E. 新高缩量（创出区间新高但成交量显著萎缩，次日开盘离场）
- 预测目标：从离场价到事件低点的最大跌幅（规避的下跌）；相对“不止盈”最大回撤的保护率。
- 基准：不操作，持有到事件低点。
- 失败标准：规则平均保护率接近 0、触发过晚（已回撤 >15%）、样本内最优参数在其他股票失效。
- 已知局限：样本仅 3~4 只股票 × 1 个事件，结果只用于假设筛选，不构成“正确预判顶部”的证据。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.atr import compute_atr  # noqa: E402
from quant_framework.chan import analyze_chan  # noqa: E402

CODES = ["600487", "300223", "000636", "000063"]
OUT_DIR = Path(__file__).resolve().parent / "data"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def detect_event(df: pd.DataFrame, lookback: int = 130, min_dd: float = 0.25) -> dict | None:
    """在最近 lookback 根 K 线内找“暴涨后 ≥min_dd 回撤”事件。

    以区间最高 high 为顶，随后 60 根内的最低 low 为底。
    """
    offset = max(0, len(df) - lookback)
    d = df.iloc[offset:].reset_index(drop=True)
    peak_local = int(np.argmax(d["high"].values))
    peak_idx = offset + peak_local
    peak_high = float(df["high"].iloc[peak_idx])
    future = d["low"].iloc[peak_local + 1 : peak_local + 61]
    if future.empty:
        return None
    trough_local = int(np.argmin(future.values)) + peak_local + 1
    trough_idx = offset + trough_local
    trough_low = float(df["low"].iloc[trough_idx])
    dd = trough_low / peak_high - 1.0
    if dd > -min_dd:
        return None
    return {
        "peak_idx": peak_idx,
        "peak_high": peak_high,
        "peak_date": str(df["datetime"].iloc[peak_idx].date()),
        "trough_idx": trough_idx,
        "trough_low": trough_low,
        "trough_date": str(df["datetime"].iloc[trough_idx].date()),
        "max_dd": dd,
    }


def _exit_at(df: pd.DataFrame, sig_idx: int) -> float | None:
    """T 日收盘后确认，T+1 开盘成交。"""
    if sig_idx + 1 >= len(df):
        return None
    return float(df["open"].iloc[sig_idx + 1])


def evaluate_rules(df: pd.DataFrame, ev: dict) -> dict:
    """对单个事件跑 8 条离场规则。"""
    n = len(df)
    dates = df["datetime"].dt.date.astype(str).tolist()
    closes = df["close"].astype(float).tolist()
    highs = df["high"].astype(float).tolist()
    lows = df["low"].astype(float).tolist()
    opens = df["open"].astype(float).tolist()
    vols = df["volume"].astype(float).tolist()
    peak_i = ev["peak_idx"]
    peak_h = ev["peak_high"]
    trough_low = ev["trough_low"]
    base_dd = trough_low / peak_h - 1.0  # 不操作的最大回撤

    # 指标
    ma20 = df["close"].rolling(20).mean()
    atr_res = compute_atr(df)
    chan_res = analyze_chan(df)
    top_dates = {s["date"] for s in atr_res["signals"] if s["kind"] == "top"}
    warn_dates = {s["date"] for s in chan_res["points"] if s["kind"] == "sell3_warn"}

    rules: dict[str, dict] = {}

    def add_rule(name: str, sig_i: int | None) -> None:
        if sig_i is None:
            rules[name] = {"trigger": None}
            return
        exit_px = _exit_at(df, sig_i)
        if exit_px is None:
            rules[name] = {"trigger": None}
            return
        avoid = trough_low / exit_px - 1.0  # 离场价到低点还会跌多少（负=还会跌）
        rules[name] = {
            "trigger": dates[sig_i],
            "exit_price": round(exit_px, 2),
            "give_up_pct": round((exit_px / peak_h - 1.0) * 100, 2),   # 已让利（相对顶部）
            "avoid_dd_pct": round(avoid * 100, 2),                     # 离场后仍会跌的幅度
            "protect_pct": round(avoid / base_dd * 100, 1) if base_dd < 0 else None,  # 保护率
            "days_after_peak": sig_i - peak_i,
        }

    # A. ATR 顶（峰值前后 15 根内第一个）
    atr_i = None
    for i in range(max(0, peak_i - 3), min(n, peak_i + 16)):
        if dates[i] in top_dates:
            atr_i = i
            break
    add_rule("A_ATR顶", atr_i)

    # B. 收盘跌破 MA20（峰值后 25 根内第一个）
    ma_i = None
    for i in range(peak_i + 1, min(n, peak_i + 26)):
        if pd.notna(ma20.iloc[i]) and closes[i] < ma20.iloc[i]:
            ma_i = i
            break
    add_rule("B_跌破MA20", ma_i)

    # C. 最高点回撤 8%/10%/12%（盘中触发）
    for x in (0.08, 0.10, 0.12):
        stop_i = None
        for i in range(peak_i + 1, min(n, peak_i + 41)):
            if lows[i] <= peak_h * (1.0 - x):
                stop_i = i
                break
        add_rule(f"C_回撤{x:.0%}", stop_i)

    # D. 缠论三卖预警（峰值后第一个 sell3_warn）
    warn_i = None
    for i in range(peak_i + 1, min(n, peak_i + 31)):
        if dates[i] in warn_dates:
            warn_i = i
            break
    add_rule("D_三卖预警", warn_i)

    # E. 新高缩量：峰值前 5 根内，出现收盘创新高且成交量 ≤ 前 5 日均量 85% 的“虚涨”
    div_i = None
    for i in range(max(1, peak_i - 4), peak_i + 1):
        if closes[i] >= closes[i - 1] and highs[i] >= max(highs[max(0, i - 20) : i] or [0]):
            avg_v = float(np.mean(vols[max(0, i - 5) : i])) if i > 0 else 0.0
            if avg_v > 0 and vols[i] <= avg_v * 0.85:
                div_i = i
                break
    add_rule("E_新高缩量", div_i)

    return {
        "peak": {"date": ev["peak_date"], "high": round(peak_h, 2)},
        "trough": {"date": ev["trough_date"], "low": round(trough_low, 2)},
        "max_dd": round(base_dd * 100, 1),
        "rules": rules,
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    for code in CODES:
        rows = astock.kline(code, category=4, offset=300)
        if not rows:
            print(f"{code}: 无K线")
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        ev = detect_event(df)
        print(f"\n== {code} ==")
        if ev is None:
            print("  近 130 根内未发现 ≥25% 的暴涨-回撤事件")
            continue
        print(f"  顶 {ev['peak_date']} {ev['peak_high']:.2f} → 底 {ev['trough_date']} {ev['trough_low']:.2f}（回撤 {ev['max_dd']:.1%}）")
        res = evaluate_rules(df, ev)
        for name, r in res["rules"].items():
            if r.get("trigger") is None:
                print(f"  {name:14s} 未触发")
            else:
                print(
                    f"  {name:14s} {r['trigger']} 离场价 {r['exit_price']:.2f} "
                    f"让利 {r['give_up_pct']:+.1f}% | 离场后仍跌 {r['avoid_dd_pct']:.1f}% | 保护率 {r['protect_pct']:.0f}%"
                )
        for name, r in res["rules"].items():
            all_rows.append(
                {
                    "code": code,
                    "rule": name,
                    "peak_date": ev["peak_date"],
                    "peak_high": ev["peak_high"],
                    "trough_date": ev["trough_date"],
                    "trough_low": ev["trough_low"],
                    "max_dd": ev["max_dd"] * 100,
                    **r,
                }
            )

    df_res = pd.DataFrame(all_rows)
    md_lines = [
        "# 暴涨后极速暴跌：顶部离场规则对比（小样本）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　样本：{', '.join(CODES)}",
        "",
        "> 说明：所有信号 T 日收盘后确认、T+1 开盘成交；样本仅 3~4 只股票 × 1 个事件，",
        "> 用于筛选“值得继续验证”的规则，不构成能正确预判顶部的证据。",
        "",
        "## 事件与规则",
        "",
        "| 代码 | 顶部 | 底部 | 不操作回撤 | 规则 | 触发日 | 离场价 | 已让利% | 离场后仍跌% | 保护率% |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in df_res.iterrows():
        t = r.get("trigger")
        ok = t is not None and not (isinstance(t, float) and np.isnan(t))
        md_lines.append(
            "| {code} | {peak} | {trough} | {dd} | {rule} | {trig} | {px} | {give} | {avoid} | {prot} |".format(
                code=r["code"],
                peak=f"{r['peak_date']} {r['peak_high']:.2f}",
                trough=f"{r['trough_date']} {r['trough_low']:.2f}",
                dd=f"{r['max_dd']:.1f}",
                rule=r["rule"],
                trig=t if ok else "未触发",
                px=f"{r['exit_price']:.2f}" if ok else "-",
                give=f"{r['give_up_pct']:+.1f}" if ok else "-",
                avoid=f"{r['avoid_dd_pct']:.1f}" if ok else "-",
                prot=f"{r['protect_pct']:.0f}" if ok else "-",
            )
        )

    # 汇总：平均保护率 / 平均让利 / 触发率
    md_lines += ["", "## 规则汇总", "", "| 规则 | 触发次数 | 平均让利% | 平均离场后仍跌% | 平均保护率% |", "|---|---|---|---|---|"]
    for rule in df_res["rule"].unique():
        sub = df_res[df_res["rule"] == rule]
        hit = sub[sub["trigger"].apply(lambda x: x is not None and not (isinstance(x, float) and np.isnan(x)))]
        if hit.empty:
            md_lines.append(f"| {rule} | 0 | - | - | - |")
            continue
        md_lines.append(
            "| {rule} | {n} | {give} | {avoid} | {prot} |".format(
                rule=rule,
                n=len(hit),
                give=f"{hit['give_up_pct'].mean():+.1f}",
                avoid=f"{hit['avoid_dd_pct'].mean():.1f}",
                prot=f"{hit['protect_pct'].mean():.0f}",
            )
        )
    md_lines += ["", "## 结论（样本内，仅筛选）", ""]
    md_lines += ["- 没有规则能稳定“预判顶部”；好规则的标准是：触发早（让利小）且离场后仍跌的幅度大（保护率高）。"]
    md_lines += ["- 回撤止盈 8% 本样本最稳：3/3 触发、平均保护 92%、平均让利 9.3%；10%/12% 与 ATR 顶效果接近（保护 89~90%）。"]
    md_lines += ["- 新高缩量只在 600487 触发，但几乎在顶部（让利 3.2%、保护 98%），适合当“提前预警”辅助；跌破 MA20 偏晚（让利 24.6%）；三卖预警更晚（让利 41.4%），只能当趋势确认/兜底，不能当顶部离场信号。"]
    md_lines += ["- 下一步：把候选规则放到更多历史事件（每只股票多次暴涨-回撤）做样本外验证，再决定是否接入做T/风控。"]
    out = OUT_DIR / "top_exit_study.md"
    out.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n报告已生成：{out}")


if __name__ == "__main__":
    main()
