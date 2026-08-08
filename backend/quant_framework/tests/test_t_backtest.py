import numpy as np
import pandas as pd

from quant_framework.t_backtest import run_t_backtest


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
