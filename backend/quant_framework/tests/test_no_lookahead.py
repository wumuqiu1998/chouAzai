"""无未来函数回归测试：截断一致性验证。

核心思想：如果指标 T 时刻的值只用 <=T 的数据，那么"用全量数据计算"与
"用截至 T 的数据计算"在 T 及以前的结果必须完全一致。任何不一致都说明
指标引用了未来数据。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_framework.atr import compute_atr
from quant_framework.chan import analyze_chan
from quant_framework.regime import build_regime_map


def _make_df(n: int = 220, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=n)
    times = ["09:30", "11:00", "13:00", "14:30"]
    dts = pd.to_datetime([f"{d.date()} {t}" for d in dates for t in times])
    ret = rng.normal(0.0003, 0.012, len(dts))
    close = 40 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.002, len(dts)))
    open_[0] = 40.0
    return pd.DataFrame(
        {
            "datetime": dts,
            "open": open_,
            "high": np.maximum(open_, close) * 1.006,
            "low": np.minimum(open_, close) * 0.994,
            "close": close,
            "volume": rng.integers(1e5, 1e6, len(dts)),
        }
    )


def _key_of(dt) -> str:
    return str(pd.Timestamp(dt))[:16]


def test_atr_no_lookahead():
    df = _make_df()
    full = compute_atr(df)
    for cut in (60, 100, 160, len(df) - 20):
        part = compute_atr(df.iloc[:cut])
        for i in range(min(len(part["bars"]), cut - 1)):
            bf = full["bars"][i]
            bp = part["bars"][i]
            assert bf["date"] == bp["date"]
            for f in ("mid", "upper", "lower", "atr"):
                assert (bf[f] is None and bp[f] is None) or abs(float(bf[f]) - float(bp[f])) < 1e-9, (
                    f"ATR 字段 {f} 在 {i} 不一致：全量 {bf[f]} vs 截断 {bp[f]}"
                )
        full_sigs = {(s["date"], s["kind"]) for s in full["signals"]}
        part_sigs = {(s["date"], s["kind"]) for s in part["signals"]}
        # 截断结果必须 ⊆ 全量结果（全量可能多出依赖后续数据确认的信号，属正常）
        assert part_sigs <= full_sigs, f"ATR 信号泄漏：截断多出 {part_sigs - full_sigs}"


def test_chan_no_lookahead():
    df = _make_df()
    full = analyze_chan(df)
    full_points = {(p["kind"], p["date"]) for p in full["points"]}
    for cut in (80, 120, 200, len(df) - 2):
        part = analyze_chan(df.iloc[:cut])
        # 截断分析的所有已确认点，必须都能在全量分析中找到（date/kind 一致）
        part_points = {(p["kind"], p["date"]) for p in part["points"]}
        assert part_points <= full_points, (
            f"缠论信号泄漏：截断到 {cut} 多出 {part_points - full_points}"
        )
        # 全量分析中"在截断范围内且已被右侧确认"的点也应出现在截断结果中
        cutoff_key = _key_of(df["datetime"].iloc[cut - 1])
        for p in full["points"]:
            if p["date"] < cutoff_key and (p["kind"], p["date"]) not in part_points:
                # 二买/二卖/三买卖依赖中枢之后出现的笔，若该笔在截断范围内已出现，
                # 截断结果必须包含；这里只做宽断言：不在截断中的点必须紧贴截断边界
                assert p["date"] >= _key_of(df["datetime"].iloc[cut - 4]), (
                    f"缠论点 {p} 在截断 {cut} 中消失（疑似未来函数）"
                )


def test_regime_no_lookahead():
    df = _make_df()
    daily = df.groupby(df["datetime"].dt.date).agg(
        close=("close", "last"), high=("high", "max"), low=("low", "min")
    ).reset_index().rename(columns={"datetime": "date"})
    full = build_regime_map(daily)
    for cut in (80, 120, 200):
        part = build_regime_map(daily.iloc[:cut])
        common = set(full) & set(part)
        assert common, "无共同日期"
        for d in common:
            assert full[d] == part[d], f"板块状态在 {d} 不一致：全量 {full[d]} vs 截断 {part[d]}"
