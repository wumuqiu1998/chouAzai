"""缠论买点持有期扫描：5/10/15/20 日（锁定口径，含费用与涨跌停约束）。

口径与 run_blind_net.py 一致：
- 信号：analyze_chan_locked 的 B1/B2/B3 买点（点内时间锁定，历史点只增不减）；
- 买入：点日期 j、首次可见 known_at，执行日 b = max(j+2, known+1) 开盘；
- 卖出：b+H 日收盘（H=5/10/15/20）；
- 费用：佣金 0.0003×2 + 印花税 0.0005 + 滑点 0.0001×2；
- 约束：涨停开盘买不进跳过、跌停收盘卖不出按收盘估值（计入收益）；
- 基准：同池全部交易日（排除信号执行日 ±2 根），同口径净收益。
"""

from __future__ import annotations

import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.chan import analyze_chan_locked  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402

SEED = 20260810
N = 50
HORIZONS = (5, 10, 15, 20)
LIMIT = 0.098
COMMISSION = 0.0003
STAMP = 0.0005
SLIPPAGE = 0.0001
OUT = Path(__file__).resolve().parent / "data" / "chan_hold_horizons.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def net_of(base: float, sell: float) -> float:
    buy_px = base * (1 + SLIPPAGE)
    sell_px = sell * (1 - SLIPPAGE)
    return sell_px / buy_px - 1.0 - COMMISSION * 2 - STAMP


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    sig_nets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    sig_rets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    base_nets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    base_rets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    used = 0

    for s in sample:
        code = s["code"]
        try:
            rows = astock.kline(code, category=4, offset=260)
        except Exception:  # noqa: BLE001
            continue
        if len(rows) < 250:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        opens = df["open"].astype(float).values
        closes = df["close"].astype(float).values
        used += 1
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}

        buys: list[int] = []
        for p in analyze_chan_locked(df)["points"]:
            j = im.get(p["date"])
            if j is None or not p["kind"].startswith("buy"):
                continue
            b = max(j + 2, p.get("known_at", j) + 1)
            if b + max(HORIZONS) < len(closes):
                buys.append(b)
        sig_set = set(buys)
        for h in HORIZONS:
            for b in buys:
                if b + h >= len(closes):
                    continue
                prev = closes[b - 1]
                if prev <= 0 or opens[b] <= 0:
                    continue
                if opens[b] / prev - 1.0 >= LIMIT - 1e-6:
                    continue  # 涨停买不进
                sell = closes[b + h]
                if sell / closes[b + h - 1] - 1.0 <= -LIMIT + 1e-6:
                    pass  # 跌停按收盘估值，仍计入
                ret = sell / opens[b] - 1.0
                sig_rets[h].append(ret)
                sig_nets[h].append(net_of(opens[b], sell))
        for h in HORIZONS:
            for i in range(1, len(closes) - h):
                if any((i + d) in sig_set for d in (-2, -1, 0, 1, 2)):
                    continue
                prev = closes[i - 1]
                if prev <= 0 or opens[i] <= 0:
                    continue
                if opens[i] / prev - 1.0 >= LIMIT - 1e-6:
                    continue
                sell = closes[i + h]
                if sell / closes[i + h - 1] - 1.0 <= -LIMIT + 1e-6:
                    pass
                base_rets[h].append(sell / opens[i] - 1.0)
                base_nets[h].append(net_of(opens[i], sell))
        print(f"{code} {s['name']} done", flush=True)

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 缠论买点持有期扫描：5/10/15/20 日（锁定口径）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　有效股票：{used}",
        "> 口径：analyze_chan_locked 买点，执行日 max(点+2, 首次可见+1) 开盘买入，",
        "> 持有 H 日收盘卖出；佣金 0.0003×2 + 印花税 0.0005 + 滑点 0.0001×2；",
        "> 涨停买不进跳过、跌停按收盘估值；随机基准为同池全日期（排除信号±2根）。",
        "",
        "| 持有日 | 缠论样本 | 净收益均值 | 净正概率 | 毛收益均值 | 毛正概率 | 基准净收益均值 | 超额净收益 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h in HORIZONS:
        a = np.array(sig_nets[h]); b = np.array(base_nets[h])
        r = np.array(sig_rets[h])
        avg_net = a.mean() if len(a) else 0.0
        avg_base = b.mean() if len(b) else 0.0
        lines.append(
            f"| {h} | {len(a)} | {avg_net * 100:+.2f}% | {(a > 0).mean() * 100:.0f}% | "
            f"{r.mean() * 100:+.2f}% | {(r > 0).mean() * 100:.0f}% | "
            f"{avg_base * 100:+.2f}% | {(avg_net - avg_base) * 100:+.2f}% |"
        )
        log.append(
            ExperimentRecord(
                experiment_id=f"CHAN-HOLD-H{h}",
                hypothesis=f"缠论买点持有 {h} 日的净收益与方向准确率",
                unique_change=f"hold={h}, exec=max(j+2,known+1), locked=True",
                expected="更长持有期可能改变方向准确率与超额",
                dev_result=f"样本 {len(a)}，净收益 {avg_net * 100:+.2f}%，正概率 {(a > 0).mean() * 100:.0f}%",
                val_result=f"基准 {avg_base * 100:+.2f}%，超额 {(avg_net - avg_base) * 100:+.2f}%",
                cost_result=f"毛收益 {r.mean() * 100:+.2f}%，毛正概率 {(r > 0).mean() * 100:.0f}%",
                passed=False,
                failure_reason="单一年窗口/单一样本池；样本外未验证",
                code_version=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev",
            )
        )
    lines += ["", "## 结论", ""]
    lines.append("- 若超额随持有期单调改善，说明信号偏中期反转/趋势；若全为≈0，说明信号本身无方向信息。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}，日志追加 {len(HORIZONS)} 条")


if __name__ == "__main__":
    main()
