"""通用因子库：AI 只改因子（这里），不改回测底座。

每个因子接收 date×symbol 的 close DataFrame（部分因子还需要 volume），
返回同形状的因子值 DataFrame。新增因子只需注册一个函数。
"""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd

FACTORS: dict[str, tuple] = {}


def register(defaults: dict | None = None):
    def deco(fn):
        FACTORS[fn.__name__] = (fn, defaults or {})
        return fn

    return deco


@register({"window": 20})
def momentum(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """N 日绝对动量：close / close.shift(N) - 1。"""
    return close / close.shift(window) - 1.0


@register({"window": 20})
def ma_bias(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """价格相对 N 日均线的乖离：close / MA(N) - 1。"""
    return close / close.rolling(window).mean() - 1.0


@register({"window": 14})
def rsi(close: pd.DataFrame, window: int = 14) -> pd.DataFrame:
    """RSI：N 日相对强弱指标。"""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


@register({"fast": 12, "slow": 26, "signal": 9})
def macd(close: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD 柱（DIF - DEA）。"""
    dif = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif - dea


@register({"window": 20})
def volatility(close: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """N 日收益波动率（日收益标准差）。"""
    return close.pct_change().rolling(window).std()


@register({"window": 20})
def volume_surge(close: pd.DataFrame, volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """量能异动：当日成交量 / N 日均量。"""
    return volume / volume.rolling(window).mean()


@register({"window": 20})
def volume_price(close: pd.DataFrame, volume: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """量价配合：N 日动量 × 量能比。"""
    mom = close / close.shift(window) - 1.0
    vs = volume / volume.rolling(window).mean()
    return mom * vs


def compute(name: str, close: pd.DataFrame, volume: pd.DataFrame | None = None, **params) -> pd.DataFrame:
    """按名称计算因子；只传入函数签名支持的参数。"""
    if name not in FACTORS:
        raise KeyError(f"未知因子：{name}，可用：{sorted(FACTORS)}")
    fn, defaults = FACTORS[name]
    allowed = set(inspect.signature(fn).parameters) - {"close", "volume"}
    kwargs = {k: v for k, v in {**defaults, **params}.items() if k in allowed}
    if "volume" in inspect.signature(fn).parameters:
        if volume is None:
            raise ValueError(f"因子 {name} 需要 volume 数据")
        return fn(close, volume=volume, **kwargs)
    return fn(close, **kwargs)
