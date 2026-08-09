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
