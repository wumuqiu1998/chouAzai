import numpy as np
import pandas as pd

from quant_framework.market_regime import _regime_label
from quant_framework.smc import analyze_smc
from quant_framework.wyckoff import analyze_wyckoff


def _df_from_closes(closes: np.ndarray, vols: np.ndarray | None = None) -> pd.DataFrame:
    n = len(closes)
    dates = pd.bdate_range("2025-01-02", periods=n)
    o = closes * 0.999
    v = vols if vols is not None else np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": o,
            "high": np.maximum(o, closes) * 1.006,
            "low": np.minimum(o, closes) * 0.994,
            "close": closes,
            "volume": v,
        }
    )


def test_wyckoff_markup_and_markdown():
    up = _df_from_closes(10 * (1.004 ** np.arange(160)))
    res = analyze_wyckoff(up)
    assert res["current"]["phase"] in ("markup",)
    down = _df_from_closes(10 * (0.996 ** np.arange(160)))
    res2 = analyze_wyckoff(down)
    assert res2["current"]["phase"] in ("markdown",)


def test_wyckoff_accumulation_and_spring():
    # 低位横盘 120 天，最后一天放量长下影
    closes = np.full(140, 10.0)
    closes[40:] = 10.0 + 0.2 * np.sin(np.arange(100) / 6.0)
    closes[-1] = 10.0
    df = _df_from_closes(closes)
    # 最后一天：开盘 10，最低 8.8（长下影），收盘 10.1，放量
    df.loc[df.index[-1], "open"] = 10.0
    df.loc[df.index[-1], "low"] = 8.8
    df.loc[df.index[-1], "close"] = 10.1
    df.loc[df.index[-1], "high"] = 10.15
    df.loc[df.index[-1], "volume"] = 3_000_000.0
    res = analyze_wyckoff(df)
    assert res["current"]["phase"] in ("accumulation",)
    assert any(s["kind"] == "spring" for s in res["signals"])
    assert res["cost_zone"] is not None


def test_smc_fvg_ob_sweep():
    rng = np.random.default_rng(9)
    closes = 10 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, 150)))
    df = _df_from_closes(closes)
    # 构造一个看涨 FVG：在中间某处让 K3 低点明显高于 K1 高点（跳空）
    idx = 80
    df.loc[df.index[idx], "high"] = df.loc[df.index[idx], "high"] * 1.03
    df.loc[df.index[idx + 2], "low"] = df.loc[df.index[idx], "high"] * 1.02
    res = analyze_smc(df)
    assert "fvg" in res and "ob" in res and "sweeps" in res and "structure" in res
    assert any(g["kind"] == "bullish" for g in res["fvg"])
    # 结构输出必须可序列化
    assert res["structure"]["state"] in {"bullish", "bearish", "range"}


def test_market_regime_labels():
    assert _regime_label(0.8) == "strong_up"
    assert _regime_label(0.3) == "up"
    assert _regime_label(0.0) == "range"
    assert _regime_label(-0.3) == "down"
    assert _regime_label(-0.8) == "strong_down"
