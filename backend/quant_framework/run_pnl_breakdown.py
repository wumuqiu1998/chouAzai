"""做T回测收益集中度拆分：按 股票 × 年/月 统计 T 净收益。

目的（对抗审计 §3）：验证收益是否集中于少数股票/少数月份，
而不是稳定 Alpha。口径：30分K、最近 100 个交易日、半仓、含费用，
沿用 run_t_backtest（含涨跌停约束默认开启）。
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.regime import build_regime_map  # noqa: E402
from quant_framework.t_backtest import run_t_backtest  # noqa: E402

CODES = ["000063", "600487", "000636", "300223", "516080"]
OUT = Path(__file__).resolve().parent / "data" / "pnl_breakdown.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    by_month: dict[str, float] = defaultdict(float)
    by_code: dict[str, float] = defaultdict(float)
    by_regime: dict[str, float] = defaultdict(float)
    regime_days: dict[str, int] = defaultdict(int)
    by_code_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    detail: list[dict] = []

    for code in CODES:
        rows = astock.kline(code, category=2, offset=800)
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        try:
            drows = astock.kline(code, category=4, offset=120)
            ddf = pd.DataFrame(drows)
            ddf["datetime"] = pd.to_datetime(ddf["datetime"])
            regime_map = build_regime_map(ddf)
        except Exception:  # noqa: BLE001
            regime_map = None
        avail = len(pd.Series(df["datetime"].dt.date).unique())
        days = min(100, avail)
        res = run_t_backtest(
            base_price=float(df["close"].iloc[0]),
            base_shares=1000,
            days=days,
            category=2,
            offset=800,
            df=df,
            trade_pct=0.5,
            stamp_duty=0.0005,
            regime=regime_map,
        )
        for d in res["daily"]:
            ym = str(d["date"])[:7]
            pnl = float(d["t_pnl"])
            rg = str(d.get("regime") or "range")
            by_month[ym] += pnl
            by_code[code] += pnl
            by_regime[rg] += pnl
            regime_days[rg] += 1
            by_code_month[code][ym] += pnl
            detail.append({"code": code, "ym": ym, "pnl": pnl})
        print(f"{code}: T收益 {res['summary']['t_pnl']:+.0f}（{days}日，blocked={res['summary']['blocked_trades']}）")

    total = sum(by_code.values())
    lines = [
        "# 做T收益集中度拆分（股票 × 年/月）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　口径：30分K、最近100交易日、半仓、含费用、含涨跌停约束",
        "",
        f"**总 T 净收益：{total:+.0f}**",
        "",
        "## 按股票",
        "",
        "| 股票 | T收益 | 占比 |",
        "|---|---|---|",
    ]
    for code, pnl in sorted(by_code.items(), key=lambda x: -x[1]):
        lines.append(f"| {code} | {pnl:+.0f} | {pnl / total * 100:.1f}% |" if total else f"| {code} | {pnl:+.0f} | - |")

    lines += ["", "## 按月份", "", "| 月份 | T收益 | 占比 |", "|---|---|---|"]
    for ym, pnl in sorted(by_month.items(), key=lambda x: -x[1]):
        lines.append(f"| {ym} | {pnl:+.0f} | {pnl / total * 100:.1f}% |" if total else f"| {ym} | {pnl:+.0f} | - |")

    lines += ["", "## 按自身趋势状态（MA20/MA60）", "", "| 状态 | T收益 | 占比 | 天数 |", "|---|---|---|---|"]
    for rg in ("up", "down", "range"):
        pnl = by_regime.get(rg, 0.0)
        days = regime_days.get(rg, 0)
        lines.append(f"| {rg} | {pnl:+.0f} | {pnl / total * 100:.1f}% | {days} |" if total else f"| {rg} | {pnl:+.0f} | - | {days} |")

    top2_code = sum(v for _, v in sorted(by_code.items(), key=lambda x: -x[1])[:2])
    top2_month = sum(v for _, v in sorted(by_month.items(), key=lambda x: -x[1])[:2])
    lines += ["", "## 集中度", ""]
    lines.append(f"- 前 2 只股票贡献：**{top2_code / total * 100:.0f}%**" if total else "- 无收益")
    lines.append(f"- 前 2 个月份贡献：**{top2_month / total * 100:.0f}%**" if total else "- 无收益")
    lines.append("- 结论：若前2股票/前2月份占比过高（>70%），收益来自少数样本/单月行情，不是稳定 Alpha。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
