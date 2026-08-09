import numpy as np
import pandas as pd

from quant_framework.atr import atr_signal_stats, compute_atr


def _make_df(closes: np.ndarray, opens: np.ndarray | None = None) -> pd.DataFrame:
    n = len(closes)
    dates = pd.bdate_range("2026-01-02", periods=n)
    o = opens if opens is not None else closes * 0.999
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": o,
            "high": np.maximum(o, closes) * 1.005,
            "low": np.minimum(o, closes) * 0.995,
            "close": closes,
            "volume": np.full(n, 1_000_000.0),
        }
    )


def test_compute_atr_basic():
    n = 120
    closes = 10 * (1.005 ** np.arange(n))
    df = _make_df(closes)
    res = compute_atr(df)
    assert len(res["bars"]) == n
    assert len(res["signals"]) >= 1
    kinds = {s["kind"] for s in res["signals"]}
    assert {"overheat", "top"} & kinds  # 持续上涨必然出现超涨与顶确认
    # 通道关系：upper >= mid >= lower
    valid = [b for b in res["bars"] if b["upper"] is not None]
    assert all(b["upper"] >= b["mid"] >= b["lower"] for b in valid)


def test_compute_atr_oversold_bottom():
    n = 120
    closes = 10 * (0.995 ** np.arange(n))
    df = _make_df(closes)
    res = compute_atr(df)
    kinds = {s["kind"] for s in res["signals"]}
    assert {"oversold", "bottom"} & kinds


def test_atr_signal_stats_shape():
    rng = np.random.default_rng(3)
    closes = 10 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, 160)))
    df = _make_df(closes)
    stats = atr_signal_stats(df, horizon=5)
    assert set(stats) == {"top", "bottom"}
    for v in stats.values():
        assert v["n"] >= 0
        assert 0 <= v["hit_rate"] <= 100


def test_atr_small_pullback_no_top():
    # 超涨段结束后小幅回落（< 1×ATR，但已跌破上轨）→ 不应确认顶
    closes = [10.0] * 25 + [10.1, 10.3, 10.6, 11.0, 10.55]
    df = _make_df(np.array(closes))
    res = compute_atr(df, mult=0.2, confirm_amp_mult=1.0, max_confirm_bars=3)
    tops = [s for s in res["signals"] if s["kind"] == "top"]
    assert tops == []


def test_atr_big_pullback_confirms_top_with_extreme_price():
    # 超涨段后大幅回落（≥ 1×ATR）→ 确认顶，且价格取超涨段最高价而非确认日收盘
    closes = [10.0] * 25 + [10.1, 10.3, 10.6, 11.0, 9.4]
    df = _make_df(np.array(closes))
    res = compute_atr(df, mult=0.2, confirm_amp_mult=1.0, max_confirm_bars=3)
    tops = [s for s in res["signals"] if s["kind"] == "top"]
    assert len(tops) == 1
    assert tops[0]["price"] > 11.0  # 超涨段最高价（11.0 × 1.005 附近），而非确认日收盘 9.4


def test_atr_delayed_confirmation():
    # 超涨段结束第一根回落幅度不足，随后一根继续大跌 → 延迟确认顶
    closes = [10.0] * 25 + [10.1, 10.3, 10.6, 11.0, 10.55, 9.4]
    df = _make_df(np.array(closes))
    res = compute_atr(df, mult=0.2, confirm_amp_mult=1.0, max_confirm_bars=3)
    tops = [s for s in res["signals"] if s["kind"] == "top"]
    assert len(tops) == 1
    assert tops[0]["date"] == str(df["datetime"].iloc[-1].date())  # 延迟确认日 = 最后一根


def test_atr_min_same_kind_gap():
    # 两段超涨-大回落，间隔较近时被 gap 过滤；gap=0 时保留两个顶
    closes = [10.0] * 25 + [10.1, 10.3, 10.6, 11.0, 9.4, 9.6, 9.8, 10.0, 10.2, 10.5, 10.9, 11.3, 9.6]
    df = _make_df(np.array(closes))
    res0 = compute_atr(df, mult=0.2, confirm_amp_mult=1.0, min_same_kind_gap=0)
    res50 = compute_atr(df, mult=0.2, confirm_amp_mult=1.0, min_same_kind_gap=50)
    assert len([s for s in res0["signals"] if s["kind"] == "top"]) >= 2
    assert len([s for s in res50["signals"] if s["kind"] == "top"]) == 1
