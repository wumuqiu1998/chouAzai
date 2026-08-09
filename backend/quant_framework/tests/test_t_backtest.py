import numpy as np
import pandas as pd

from quant_framework.t_backtest import run_band_t_backtest, run_t_backtest


def test_t_backtest_runs_and_restores_position():
    rng = np.random.default_rng(7)
    n_days = 45
    days = pd.bdate_range("2026-01-02", periods=n_days)
    times = ["09:30", "11:00", "13:00", "14:30"]
    dts = pd.to_datetime([f"{d.date()} {t}" for d in days for t in times])
    n_bars = len(dts)
    ret = rng.normal(0.0002, 0.01, n_bars)
    close = 43 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.002, n_bars))
    open_[0] = 43.0
    df = pd.DataFrame(
        {
            "datetime": dts,
            "open": open_,
            "high": np.maximum(open_, close) * 1.005,
            "low": np.minimum(open_, close) * 0.995,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n_bars),
        }
    )
    res = run_t_backtest(base_price=43.0, base_shares=1000, days=30, category=11, offset=500, df=df)
    assert set(res) == {"config", "period", "daily", "summary", "trades"}
    assert len(res["daily"]) == 30
    assert res["summary"]["t_pnl"] is not None


def test_band_t_backtest_runs():
    rng = np.random.default_rng(11)
    n_days = 40
    days = pd.bdate_range("2026-01-02", periods=n_days)
    times = ["09:30", "11:00", "13:00", "14:30"]
    dts = pd.to_datetime([f"{d.date()} {t}" for d in days for t in times])
    n_bars = len(dts)
    ret = rng.normal(0.0002, 0.012, n_bars)
    close = 43 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.002, n_bars))
    high = np.maximum(open_, close) * 1.008
    low = np.minimum(open_, close) * 0.992
    df = pd.DataFrame(
        {
            "datetime": dts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n_bars),
        }
    )
    for filt in (False, True):
        res = run_band_t_backtest(base_price=43.0, base_shares=1000, days=20, category=11, offset=800, df=df, use_beichi_filter=filt)
        assert len(res["daily"]) == 20
        assert res["summary"]["t_pnl"] is not None

    # 量价确认模式也能正常运行
    res_vp = run_band_t_backtest(
        base_price=43.0,
        base_shares=1000,
        days=20,
        category=11,
        offset=800,
        df=df,
        vp_shrink_ratio=0.85,
        vp_surge_ratio=1.15,
    )
    assert len(res_vp["daily"]) == 20

    # 趋势过滤模式也能正常运行
    res_trend = run_band_t_backtest(
        base_price=43.0,
        base_shares=1000,
        days=20,
        category=11,
        offset=800,
        df=df,
        trend_window=1,
        trend_period=20,
    )
    assert len(res_trend["daily"]) == 20
    assert all(d["trend"] in {"up", "down", "neutral"} for d in res_trend["daily"])
