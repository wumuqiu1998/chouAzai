import numpy as np
import pandas as pd

from quant_framework.signal_score import compute_signal_score


def _make_df(closes: np.ndarray, seed: int = 0) -> pd.DataFrame:
    n = len(closes)
    rng = np.random.default_rng(seed)
    o = np.maximum(closes * 0.995, 0.1)
    high = np.maximum(o, closes) * 1.01
    low = np.minimum(o, closes) * 0.99
    vol = rng.integers(500_000, 2_000_000, n).astype(float)
    return pd.DataFrame(
        {
            "datetime": pd.bdate_range("2025-01-02", periods=n),
            "open": o,
            "high": high,
            "low": low,
            "close": closes,
            "volume": vol,
        }
    )


def test_score_range_and_levels():
    rng = np.random.default_rng(7)
    closes = 10 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, 200)))
    df = _make_df(closes)
    res = compute_signal_score(df)
    assert -100 <= res["score"] <= 100
    assert res["level"] in {"加仓", "偏多", "观望", "偏空", "规避"}
    assert res["trailing_stop"] is not None
    assert set(res["parts"]) == {"trend", "atr", "chan", "volume"}


def test_score_negative_after_crash():
    # 先暴涨再极速暴跌，信号量应明显转负
    up = 10 * np.linspace(1, 4, 80)
    crash = up[-1] * np.linspace(1, 0.55, 40)
    closes = np.concatenate([up, crash])
    df = _make_df(closes)
    res = compute_signal_score(df)
    assert res["score"] < 0
    assert res["level"] in {"偏空", "规避"}


def test_deterministic_and_truncation_consistent():
    rng = np.random.default_rng(11)
    closes = 10 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, 180)))
    df = _make_df(closes)
    res1 = compute_signal_score(df)
    res2 = compute_signal_score(df.copy())
    assert res1["score"] == res2["score"]
    # 截断一致性：在 i 点计算只用 ≤i 的数据，与全量数据在 i 点截断后的结果一致
    i = 120
    assert compute_signal_score(df.iloc[: i + 1])["score"] == compute_signal_score(df.iloc[: i + 1].copy())["score"]
