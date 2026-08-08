import numpy as np
import pandas as pd

from quant_framework.chan import (
    analyze_chan,
    buy_sell_points,
    find_bi,
    find_fractals,
    find_zhongshu,
    merge_contained,
)


def test_merge_contained():
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]),
            "open": [10, 11, 11.5, 12],
            "high": [10.5, 11.0, 10.8, 12.0],
            "low": [9.5, 9.2, 9.6, 10.5],
            "close": [10.2, 10.8, 10.6, 12.0],
            "volume": [1, 1, 1, 1],
        }
    )
    merged = merge_contained(df)
    # 第 2 根包含第 3 根（11/9.8 包住 10.8/9.6），向上合并
    assert len(merged) < 4
    assert (merged["high"].diff().dropna() >= 0).all()
    assert (merged["low"].diff().dropna() >= 0).all()


def test_find_bi_alternates_and_gap():
    fractals = [
        {"pos": 0, "date": "d1", "price": 10, "kind": "top"},
        {"pos": 1, "date": "d2", "price": 9, "kind": "bottom"},   # 间隔 1 < min_gap -> 跳过
        {"pos": 5, "date": "d3", "price": 9.5, "kind": "top"},
        {"pos": 9, "date": "d4", "price": 8.8, "kind": "bottom"},
        {"pos": 9, "date": "d5", "price": 8.5, "kind": "bottom"},  # 同类型更低，替换
    ]
    bis = find_bi(fractals, min_gap=4)
    assert [b["kind"] for b in bis] == ["top", "bottom"]
    assert bis[-1]["price"] == 8.5


def test_zhongshu_overlap():
    bis = [
        {"pos": 0, "date": "d0", "price": 110, "kind": "top"},
        {"pos": 5, "date": "d1", "price": 90, "kind": "bottom"},
        {"pos": 10, "date": "d2", "price": 100, "kind": "top"},
        {"pos": 15, "date": "d3", "price": 92, "kind": "bottom"},
        {"pos": 20, "date": "d4", "price": 96, "kind": "top"},
    ]
    zs = find_zhongshu(bis)
    assert zs, "应识别出中枢"
    assert any(z["zd"] == 92 and z["zg"] == 96 for z in zs)


def test_buy_sell_points():
    bis = [
        {"pos": 0, "date": "2026-01-01", "price": 110, "kind": "top"},
        {"pos": 5, "date": "2026-01-06", "price": 90, "kind": "bottom"},
        {"pos": 10, "date": "2026-01-11", "price": 100, "kind": "top"},
        {"pos": 15, "date": "2026-01-16", "price": 92, "kind": "bottom"},
        {"pos": 20, "date": "2026-01-21", "price": 96, "kind": "top"},
        {"pos": 25, "date": "2026-01-26", "price": 85, "kind": "bottom"},
        {"pos": 30, "date": "2026-01-31", "price": 94, "kind": "top"},
        {"pos": 35, "date": "2026-02-05", "price": 88, "kind": "bottom"},
        {"pos": 40, "date": "2026-02-10", "price": 98, "kind": "top"},
        {"pos": 45, "date": "2026-02-15", "price": 97, "kind": "bottom"},
    ]
    zhongshu = find_zhongshu(bis)
    pts = buy_sell_points(bis, zhongshu)
    kinds = {p["kind"] for p in pts}
    assert {"buy1", "buy2", "buy3"} <= kinds
    b1 = next(p for p in pts if p["kind"] == "buy1")
    assert b1["price"] == 85


def test_analyze_chan_structure():
    rng = np.random.default_rng(3)
    n = 240
    close = 10 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    df = pd.DataFrame(
        {
            "datetime": pd.bdate_range("2025-01-02", periods=n),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(1e5, 1e6, n),
        }
    )
    res = analyze_chan(df)
    assert set(res) == {"bars", "points", "zhongshu", "bi", "params"}
    assert len(res["bars"]) == n
    for p in res["points"]:
        assert p["kind"] in {"buy1", "buy2", "buy3", "sell1", "sell2", "sell3"}
