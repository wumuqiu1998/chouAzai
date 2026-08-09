"""板块/概念状态切换做T全样本对比（可复现脚本）。

每只股票：先解析所属板块指数日K → 均线法三态（up/down/range，T+1 生效），
然后逐股票 × 30/15分 × (B/S+板块状态 / 中枢+板块状态)，输出逐股票报告
到 data/regime_report.md（gitignored）。

状态策略：
- up   → 顺趋势做多T（B点/中枢下轨买入，S点/中枢上轨卖出）；
- down → 顺趋势做空T（S点/中枢上轨卖出，B点/中枢下轨买回）；
- range→ 双向做T（B/S 原逻辑 / 中枢双向）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.regime import build_regime_map, resolve_regime_source  # noqa: E402
from quant_framework.t_backtest import run_band_t_backtest, run_t_backtest  # noqa: E402

CODES = [
    ("000636", None),
    ("300223", None),
    ("600487", None),
    ("000063", None),
    ("516080", "创新药"),
]
PLAN = [("30分", 2, 100), ("15分", 1, 50)]

OUT = Path(__file__).resolve().parent / "data" / "regime_report.md"


def split_by_regime(daily: list[dict]) -> dict:
    out = {s: {"days": 0, "pnl": 0.0} for s in ("up", "down", "range")}
    for d in daily:
        s = str(d.get("regime") or "range")
        if s not in out:
            s = "range"
        out[s]["days"] += 1
        out[s]["pnl"] += float(d.get("t_pnl", 0.0))
    return out


def fmt_split(sp: dict) -> str:
    parts = []
    for s in ("up", "down", "range"):
        v = sp[s]
        parts.append(f"{s}={v['days']}天/{v['pnl']:.0f}元")
    return "；".join(parts)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# 板块/概念状态切换做T报告（半仓500股，逐股票独立）", ""]
    for code, etf_block in CODES:
        stamp = 0.0 if code.startswith("5") else 0.0005
        lines.append(f"## {code}")
        try:
            concept = astock.concept_blocks(code)
        except Exception:
            concept = None
        src_type, block_name, daily_rows = resolve_regime_source(code, concept=concept, etf_block=etf_block)
        if not daily_rows:
            lines.append("- 数据获取失败（无日K可判定趋势），跳过")
            OUT.write_text("\n".join(lines), encoding="utf-8")
            continue
        ddf = pd.DataFrame(daily_rows)
        if "datetime" not in ddf.columns:
            ddf = ddf.rename(columns={"date": "datetime"})
        ddf["datetime"] = pd.to_datetime(ddf["datetime"])
        regime_map = build_regime_map(ddf)
        if src_type == "block":
            lines.append(f"趋势源：板块指数 {block_name}（{len(ddf)} 天日K）")
        else:
            lines.append(f"趋势源：板块数据不可用，用自身日K兜底（{len(ddf)} 天）")
        daily_agg = ddf.groupby(ddf["datetime"].dt.date).agg(
            close=("close", "last"), high=("high", "max"), low=("low", "min")
        )
        # 状态分布（回测窗口内，用 T+1 生效后的有效状态）
        lines.append(f"状态分布：{fmt_split({s: {'days': sum(1 for d in regime_map.values() if d == s), 'pnl': 0.0} for s in ('up', 'down', 'range')})}")
        lines.append("")
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
            variants = [
                ("B/S+板块状态", {"regime": regime_map}),
                ("中枢+板块状态", {"regime": regime_map}),
                ("中枢+个股MA20趋势", {"trend_window": 1, "trend_period": 20}),
            ]
            for label, kw in variants:
                try:
                    if label.startswith("B/S"):
                        res = run_t_backtest(base_price=first_close, base_shares=1000, days=days, category=cat, offset=800, df=df, trade_pct=0.5, stamp_duty=stamp, **kw)
                    else:
                        res = run_band_t_backtest(base_price=first_close, base_shares=1000, days=days, category=cat, offset=800, df=df, trade_pct=0.5, stamp_duty=stamp, **kw)
                    s = res["summary"]
                    sp = split_by_regime(res["daily"])
                    lines.append(f"- {label} | 配对={s['total_pairs']} 胜率={s['win_rate']:.1%} T净收益={s['t_pnl']:.2f} 费用={s['total_fees']:.2f} 正日={s['positive_days']}/{days}")
                    lines.append(f"  - 分状态收益：{fmt_split(sp)}")
                except Exception as e:
                    lines.append(f"- {label}: {e}")
            lines.append("")
            OUT.write_text("\n".join(lines), encoding="utf-8")
            print(f"{code} {name} done", flush=True)
    lines.append("DONE")
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"finished in {time.time() - t0:.0f}s", flush=True)
