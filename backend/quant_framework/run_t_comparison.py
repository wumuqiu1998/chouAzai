"""组合型做T全样本对比（可复现脚本）。

逐股票 × 30/15分 × (B/S + 中枢 + 量价 + 趋势 + 量价&趋势)，结果写入
data/t_comparison_report.md（gitignored）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.t_backtest import run_band_t_backtest, run_t_backtest  # noqa: E402

CODES = ["000636", "300223", "600487", "000063", "516080"]
PLAN = [("30分", 2, 100), ("15分", 1, 50)]
VARIANTS = [
    ("中枢", {}),
    ("中枢+量价", {"vp_shrink_ratio": 0.85, "vp_surge_ratio": 1.15, "vol_window": 20}),
    ("中枢+趋势", {"trend_window": 1, "trend_period": 20}),
    ("中枢+量价+趋势", {"vp_shrink_ratio": 0.85, "vp_surge_ratio": 1.15, "vol_window": 20, "trend_window": 1, "trend_period": 20}),
]

OUT = Path(__file__).resolve().parent / "data" / "t_comparison_report.md"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# 做T策略对比报告（半仓500股，逐股票独立）", ""]
    for code in CODES:
        stamp = 0.0 if code.startswith("5") else 0.0005
        lines.append(f"## {code}")
        for name, cat, max_days in PLAN:
            try:
                rdata = astock.kline(code, category=cat, offset=800)
                df = pd.DataFrame(rdata)
                df["datetime"] = pd.to_datetime(df["datetime"])
            except Exception as e:
                lines.append(f"- {name}: 数据获取失败 {e}")
                continue
            avail = len(pd.Series(df["datetime"].dt.date).unique())
            days = min(max_days, avail)
            first_close = float(df["close"].iloc[0])
            note = f"（仅{avail}天）" if avail < max_days else ""
            lines.append(f"### {name}（{days}天{note}，参考成本 {first_close:.2f}）")
            rows = []
            try:
                res = run_t_backtest(base_price=first_close, base_shares=1000, days=days, category=cat, offset=800, df=df, trade_pct=0.5, stamp_duty=stamp)
                s = res["summary"]
                rows.append(f"- B/S | 配对={s['total_pairs']} 胜率={s['win_rate']:.1%} T净收益={s['t_pnl']:.2f} 费用={s['total_fees']:.2f} 正日={s['positive_days']}/{days}")
            except Exception as e:
                rows.append(f"- B/S: {e}")
            for label, kw in VARIANTS:
                try:
                    res = run_band_t_backtest(base_price=first_close, base_shares=1000, days=days, category=cat, offset=800, df=df, trade_pct=0.5, stamp_duty=stamp, **kw)
                    s = res["summary"]
                    rows.append(f"- {label} | 配对={s['total_pairs']} 胜率={s['win_rate']:.1%} T净收益={s['t_pnl']:.2f} 费用={s['total_fees']:.2f} 正日={s['positive_days']}/{days}")
                except Exception as e:
                    rows.append(f"- {label}: {e}")
            lines.extend(rows)
            lines.append("")
            # 边跑边落盘，方便中途查看
            OUT.write_text("\n".join(lines), encoding="utf-8")
            print(f"{code} {name} done", flush=True)
    lines.append("DONE")
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"finished in {time.time()-t0:.0f}s", flush=True)
