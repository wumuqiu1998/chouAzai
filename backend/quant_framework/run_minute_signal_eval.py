"""分时信号准确性对比（自选股 × 5分钟K 代理分时）。

口径：
- 数据：腾讯 5 分钟K（约 7 个交易日，320 根），按交易日逐日计算信号，
  与分时图“当日分时实时计算”一致；
- 信号：ATR 顶/底、缠论 B/S/三卖预警、SMC 扫荡/突/破/变、威科夫积/派；
- 评估：信号 bar 收盘为基准，统计未来 3/6 根（15/30 分钟）收益：
  卖点准确率 = 未来收益 <0 比例；买点准确率 = 未来收益 >0 比例；
  另统计“卖点后继续冲高幅度”“买点后继续探底幅度”衡量是否接近极值。
- 局限：样本约 5 股 × 7 日，仅用于筛选方向，不构成验证。
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.atr import compute_atr  # noqa: E402
from quant_framework.chan import analyze_chan  # noqa: E402
from quant_framework.smc import analyze_smc  # noqa: E402
from quant_framework.wyckoff import analyze_wyckoff  # noqa: E402

CODES = ["000636", "300223", "600487", "000063", "516080"]
CAT = 0  # 5分钟
OFFSET = 320
MIN_BARS_PER_DAY = 30
OUT = Path(__file__).resolve().parent / "data" / "minute_signal_eval.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _date_key(ts) -> str:
    return str(pd.Timestamp(ts))[:16].replace(" 00:00", "")


def collect_signals(day_df: pd.DataFrame) -> list[dict]:
    """对当日分钟K计算各策略信号，返回 [{time_idx, label, kind, strategy, price}]。"""
    d = day_df.copy().reset_index(drop=True)
    im = {_date_key(ts): i for i, ts in enumerate(d["datetime"])}
    out: list[dict] = []

    for s in compute_atr(d)["signals"]:
        i = im.get(s["date"])
        if i is not None and s["kind"] in ("top", "bottom"):
            out.append(
                {
                    "time_idx": i,
                    "label": "顶" if s["kind"] == "top" else "底",
                    "kind": s["kind"],
                    "strategy": "ATR",
                    "price": s["price"],
                    "side": "sell" if s["kind"] == "top" else "buy",
                }
            )

    chan_label = {
        "buy1": "B1", "buy2": "B2", "buy3": "B3",
        "sell1": "S1", "sell2": "S2", "sell3": "S3", "sell3_warn": "警",
    }
    for p in analyze_chan(d)["points"]:
        i = im.get(p["date"])
        label = chan_label.get(p["kind"])
        if i is None or label is None:
            continue
        out.append(
            {
                "time_idx": i,
                "label": label,
                "kind": p["kind"],
                "strategy": "缠论",
                "price": p["price"],
                "side": "sell" if p["kind"].startswith("sell") else "buy",
            }
        )

    smc = analyze_smc(d, sweep_min_gap=0)
    for s in smc.get("sweeps") or []:
        i = im.get(s["date"])
        if i is None:
            continue
        out.append(
            {
                "time_idx": i,
                "label": "扫",
                "kind": "sweep",
                "strategy": "SMC",
                "price": s["price"],
                "side": "buy" if s["kind"] == "bullish" else "sell",
            }
        )
    st = smc.get("structure") or {}
    for key, side_map in (("last_bos", {"bullish": ("突", "buy"), "bearish": ("破", "sell")}), ("last_choch", {"bullish": ("变", "sell"), "bearish": ("变", "sell")})):
        item = st.get(key)
        if not item:
            continue
        i = im.get(item["date"])
        if i is None:
            continue
        label, side = side_map.get(item["kind"], ("变", "sell"))
        out.append(
            {
                "time_idx": i,
                "label": label,
                "kind": key,
                "strategy": "SMC",
                "price": item["price"],
                "side": side,
            }
        )

    for s in (analyze_wyckoff(d).get("signals") or []):
        i = im.get(s["date"])
        if i is None:
            continue
        label = "积" if s["kind"] == "spring" else "派"
        out.append(
            {
                "time_idx": i,
                "label": label,
                "kind": s["kind"],
                "strategy": "威科夫",
                "price": s["price"],
                "side": "buy" if s["kind"] == "spring" else "sell",
            }
        )
    return out


def eval_signal(closes: np.ndarray, idx: int, horizon: int) -> dict | None:
    if idx + horizon >= len(closes):
        return None
    base = closes[idx]
    if base <= 0:
        return None
    ret = closes[idx + horizon] / base - 1.0
    fwd_high = closes[idx + 1 : idx + horizon + 1].max() / base - 1.0
    fwd_low = closes[idx + 1 : idx + horizon + 1].min() / base - 1.0
    return {"ret": ret, "fwd_high": fwd_high, "fwd_low": fwd_low}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stats: dict[str, dict] = defaultdict(lambda: {"n": 0, "rets3": [], "rets6": [], "fwd_high": [], "fwd_low": []})
    per_label: dict[str, dict] = defaultdict(lambda: {"n": 0, "rets3": [], "rets6": [], "fwd_high": [], "fwd_low": []})
    per_code: dict[str, int] = defaultdict(int)

    for code in CODES:
        rows = astock.kline(code, category=CAT, offset=OFFSET)
        if not rows:
            print(f"{code}: 无数据")
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        for day, g in df.groupby(df["datetime"].dt.date):
            g = g.reset_index(drop=True)
            if len(g) < MIN_BARS_PER_DAY:
                continue
            closes = g["close"].astype(float).values
            for sig in collect_signals(g):
                e3 = eval_signal(closes, sig["time_idx"], 3)
                e6 = eval_signal(closes, sig["time_idx"], 6)
                key = f"{sig['strategy']}|{sig['side']}"
                per_code[code] += 1
                if e3:
                    stats[key]["n"] += 1
                    stats[key]["rets3"].append(e3["ret"])
                    stats[key]["rets6"].append(e6["ret"] if e6 else e3["ret"])
                    stats[key]["fwd_high"].append(e3["fwd_high"])
                    stats[key]["fwd_low"].append(e3["fwd_low"])
                lk = f"{sig['label']}|{sig['side']}"
                if e6:
                    per_label[lk]["n"] += 1
                    per_label[lk]["rets6"].append(e6["ret"])

    lines = [
        "# 分时信号准确性对比（自选股 × 5分钟K 代理）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　样本：{', '.join(CODES)}",
        f"> 口径：逐日计算（与分时图一致），信号 bar 收盘为基准；15分钟=未来3根、30分钟=未来6根。",
        "",
        "## 策略维度（按 买点/卖点 汇总）",
        "",
        "| 策略 | 方向 | 样本 | 15分钟平均收益 | 15分钟方向准确率 | 30分钟平均收益 | 30分钟方向准确率 | 卖点后冲高/买点后探底均值 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    order = [("ATR", "buy"), ("ATR", "sell"), ("缠论", "buy"), ("缠论", "sell"), ("SMC", "buy"), ("SMC", "sell"), ("威科夫", "buy"), ("威科夫", "sell")]
    summary_rows = []
    for strategy, side in order:
        key = f"{strategy}|{side}"
        v = stats.get(key)
        if not v or v["n"] == 0:
            lines.append(f"| {strategy} | {side} | 0 | - | - | - | - | - |")
            continue
        r3 = np.mean(v["rets3"])
        r6 = np.mean(v["rets6"])
        acc3 = np.mean([1 if x < 0 else 0 for x in v["rets3"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets3"]])
        acc6 = np.mean([1 if x < 0 else 0 for x in v["rets6"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets6"]])
        extreme = np.mean(v["fwd_high"] if side == "sell" else v["fwd_low"])
        lines.append(
            f"| {strategy} | {'买点' if side == 'buy' else '卖点'} | {v['n']} | {r3 * 100:+.2f}% | {acc3 * 100:.0f}% | {r6 * 100:+.2f}% | {acc6 * 100:.0f}% | {extreme * 100:+.2f}% |"
        )
        summary_rows.append((strategy, side, v["n"], r3, acc3, r6, acc6, extreme))

    lines += ["", "## 信号标签维度（30分钟）", "", "| 标签 | 方向 | 样本 | 30分钟平均收益 | 方向准确率 |", "|---|---|---|---|---|"]
    for lk in sorted(per_label, key=lambda x: -per_label[x]["n"]):
        v = per_label[lk]
        label, side = lk.split("|")
        r6 = np.mean(v["rets6"])
        acc6 = np.mean([1 if x < 0 else 0 for x in v["rets6"]]) if side == "sell" else np.mean([1 if x > 0 else 0 for x in v["rets6"]])
        lines.append(f"| {label} | {'买' if side == 'buy' else '卖'} | {v['n']} | {r6 * 100:+.2f}% | {acc6 * 100:.0f}% |")

    lines += ["", "## 结论（小样本，仅筛选方向）", ""]
    if summary_rows:
        best_sell = max([r for r in summary_rows if r[1] == "sell"], key=lambda x: x[6], default=None)
        best_buy = max([r for r in summary_rows if r[1] == "buy"], key=lambda x: x[6], default=None)
        if best_sell:
            lines.append(f"- 卖点（顶/卖出）最准：**{best_sell[0]}**（30分钟方向准确率 {best_sell[6] * 100:.0f}%，样本 {best_sell[2]}）")
        if best_buy:
            lines.append(f"- 买点（底/买入）最准：**{best_buy[0]}**（30分钟方向准确率 {best_buy[6] * 100:.0f}%，样本 {best_buy[2]}）")
    lines.append("- 信号方向准确率高于 50% 越多越可信；样本约 5 股 × 7 日，仍需更长窗口验证。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
