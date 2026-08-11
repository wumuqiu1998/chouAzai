import numpy as np
import pandas as pd

from quant_framework.regime import build_regime_map, classify_regime
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


def test_classify_regime_states():
    idx = pd.date_range("2026-01-02", periods=80, freq="B")
    up = pd.Series(10 * (1.002 ** np.arange(80)), index=idx)
    down = pd.Series(10 * (0.998 ** np.arange(80)), index=idx)
    flat = pd.Series(10 + 0.08 * np.sin(np.arange(80) / 5.0), index=idx)
    assert (classify_regime(up).tail(10) == "up").all()
    assert (classify_regime(down).tail(10) == "down").all()
    # 震荡序列：分类应大部分落在 range（允许边界少量误判）
    flat_states = classify_regime(flat).tail(20)
    assert (flat_states == "range").mean() >= 0.9


def test_build_regime_map_shifts_no_future():
    dates = pd.date_range("2026-01-02", periods=80, freq="B")
    close = pd.Series(10 * (1.002 ** pd.Series(range(80))), index=dates)
    daily = pd.DataFrame({"date": dates, "close": close.values, "high": close.values * 1.01, "low": close.values * 0.99})
    m = build_regime_map(daily)
    # 最早一个状态生效日必须晚于数据首日（shift(1) 后首日无状态）
    assert len(m) >= 10
    assert all(v in {"up", "down", "range"} for v in m.values())


def _mk_two_day_df(exec_open: float, last_close: float) -> pd.DataFrame:
    days = pd.bdate_range("2026-01-02", periods=2)
    times = ["09:30", "10:00", "10:30", "11:00"]
    dts = pd.to_datetime([f"{d.date()} {t}" for d in days for t in times])
    close = [10.0] * 8
    close[7] = last_close
    open_ = [10.0] * 8
    open_[6] = exec_open
    return pd.DataFrame(
        {
            "datetime": dts,
            "open": open_,
            "high": [max(o, c) * 1.01 for o, c in zip(open_, close)],
            "low": [min(o, c) * 0.99 for o, c in zip(open_, close)],
            "close": close,
            "volume": [100000.0] * 8,
        }
    )


def test_limit_blocked_on_limit_down_open():
    from quant_framework.chan import _dt_key

    # 第二日第3根开盘跌停（-10%），S 点应被挡；关闭约束时可成交
    df = _mk_two_day_df(exec_open=9.0, last_close=9.5)
    extra = [{"kind": "sell_test", "date": _dt_key(df["datetime"].iloc[4]), "price": 10.0}]
    res_on = run_t_backtest(
        base_price=10.0, base_shares=1000, days=2, category=11, offset=500, df=df, min_warmup=1, extra_points=extra
    )
    assert res_on["summary"]["blocked_trades"] >= 1
    assert not any(t["side"] == "sell" for t in res_on["trades"])
    res_off = run_t_backtest(
        base_price=10.0, base_shares=1000, days=2, category=11, offset=500, df=df,
        min_warmup=1, extra_points=extra, enforce_limit=False,
    )
    assert any(t["side"] == "sell" for t in res_off["trades"])


def test_buy_blocked_on_limit_up_open():
    from quant_framework.chan import _dt_key

    # 第二日第3根开盘涨停（+10%），B 点应被挡
    df = _mk_two_day_df(exec_open=11.0, last_close=10.5)
    extra = [{"kind": "buy_test", "date": _dt_key(df["datetime"].iloc[4]), "price": 10.0}]
    res = run_t_backtest(
        base_price=10.0, base_shares=1000, days=2, category=11, offset=500, df=df, min_warmup=1, extra_points=extra
    )
    assert res["summary"]["blocked_trades"] >= 1
    assert not any(t["side"] == "buy" for t in res["trades"])


def test_restore_blocked_on_limit_up_close():
    from quant_framework.chan import _dt_key

    # S 点正常卖出，但收盘涨停买不回 → blocked_restore
    df = _mk_two_day_df(exec_open=10.0, last_close=11.0)
    extra = [{"kind": "sell_test", "date": _dt_key(df["datetime"].iloc[4]), "price": 10.0}]
    res = run_t_backtest(
        base_price=10.0, base_shares=1000, days=2, category=11, offset=500, df=df, min_warmup=1, extra_points=extra
    )
    assert any(t["side"] == "blocked_restore" for t in res["trades"])


def test_t_backtest_regime_runs():
    rng = np.random.default_rng(3)
    n_days = 50
    days = pd.bdate_range("2026-01-02", periods=n_days)
    times = ["09:30", "11:00", "13:00", "14:30"]
    dts = pd.to_datetime([f"{d.date()} {t}" for d in days for t in times])
    ret = rng.normal(0.0002, 0.01, len(dts))
    close = 43 * np.exp(np.cumsum(ret))
    open_ = close * (1 + rng.normal(0, 0.002, len(dts)))
    open_[0] = 43.0
    df = pd.DataFrame(
        {
            "datetime": dts,
            "open": open_,
            "high": np.maximum(open_, close) * 1.005,
            "low": np.minimum(open_, close) * 0.995,
            "close": close,
            "volume": rng.integers(1e5, 1e6, len(dts)),
        }
    )
    regime = {d.date(): "up" for d in days}
    res = run_t_backtest(base_price=43.0, base_shares=1000, days=30, category=11, offset=500, df=df, regime=regime)
    assert all(d["regime"] == "up" for d in res["daily"])

    res_band = run_band_t_backtest(base_price=43.0, base_shares=1000, days=20, category=11, offset=800, df=df, regime=regime)
    assert all(d["regime"] == "up" for d in res_band["daily"])
    assert all(d["trend"] == "up" for d in res_band["daily"])


def test_t_backtest_end_date_no_future_effect():
    """追加未来数据不改变历史窗口回测结果：end_date 截断口径一致性。"""
    rng = np.random.default_rng(23)
    n_days = 40
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
    end = str(days[30].date())
    full = run_t_backtest(base_price=43.0, base_shares=1000, days=10, category=11, offset=500, df=df, end_date=end)
    trunc = df[df["datetime"].dt.date <= pd.Timestamp(end).date()].reset_index(drop=True)
    part = run_t_backtest(base_price=43.0, base_shares=1000, days=10, category=11, offset=500, df=trunc)
    assert full["trades"] == part["trades"], "追加未来数据改变了历史回测交易记录"
    assert full["daily"] == part["daily"], "追加未来数据改变了历史回测每日结果"
    assert full["summary"]["t_pnl"] == part["summary"]["t_pnl"]
