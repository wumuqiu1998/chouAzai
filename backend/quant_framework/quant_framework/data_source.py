"""数据源适配层：Vibe-Research（a-stock-data）为信息源，另有合成数据用于示例。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


class VibeDataSource:
    """桥接 F:\\Code\\Vibe-Research\\a-stock-data 的端点。

    依赖可用时优先走 a-stock-data；否则返回空并给出安装提示。
    端点参考：tencent_quote / baidu_kline_with_ma / tdx_client / eastmoney_reports。
    """

    VIBE_ASTOCK_DIR = Path(r"F:\Code\Vibe-Research\a-stock-data")

    def __init__(self, skill_dir: str | Path | None = None):
        self.skill_dir = Path(skill_dir) if skill_dir else self.VIBE_ASTOCK_DIR
        self._module = None
        if self.skill_dir.exists() and (self.skill_dir / "SKILL.md").exists():
            self._module = self._try_load()

    def _try_load(self):
        if not importlib.util.find_spec("mootdx"):
            return None
        for name in ("astock", "a_stock_data", "stock_data"):
            p = self.skill_dir / f"{name}.py"
            if p.exists():
                spec = importlib.util.spec_from_file_location(name, p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[name] = mod
                spec.loader.exec_module(mod)
                return mod
        return None

    @property
    def available(self) -> bool:
        return self._module is not None

    def get_kline(
        self,
        code: str,
        start: str = "",
        end: str = "",
        source: str = "baidu",
    ) -> pd.DataFrame:
        """统一返回 date/open/high/low/close/volume DataFrame。"""
        if not self.available:
            raise RuntimeError(
                "Vibe-Research a-stock-data 数据源不可用：请确认 F:\\Code\\Vibe-Research\\a-stock-data "
                "存在且已安装 mootdx（pip install mootdx requests pandas）"
            )
        fn = getattr(self._module, "baidu_kline_with_ma", None)
        if fn is None:
            raise RuntimeError("a-stock-data 未提供 baidu_kline_with_ma 端点")
        raw = fn(code, start_time=start)
        if isinstance(raw, dict) and "data" in raw:
            raw = raw["data"]
        df = pd.DataFrame(raw)
        df = df.rename(
            columns={"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
        )
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)


class SyntheticDataSource:
    """确定性的合成数据源：用于示例/测试，避免依赖网络。"""

    def __init__(self, n_symbols: int = 60, n_days: int = 400, seed: int = 42):
        self.n_symbols = n_symbols
        self.n_days = n_days
        self.seed = seed

    def load_panel(self) -> dict[str, pd.DataFrame]:
        rng = np.random.default_rng(self.seed)
        dates = pd.bdate_range("2024-01-02", periods=self.n_days)
        symbols = [f"S{i:04d}" for i in range(self.n_symbols)]
        ret = rng.normal(0.0004, 0.01, size=(self.n_days, self.n_symbols))
        # 注入 20 日动量：过去涨幅高的股票未来略强
        for t in range(20, self.n_days):
            past = np.mean(ret[t - 20 : t], axis=0)
            ret[t] = ret[t] + 0.05 * np.tanh(past)
        close = 10.0 * np.exp(np.cumsum(ret, axis=0))
        open_ = close * (1 + rng.normal(0, 0.002, size=close.shape))
        open_[0] = close[0]
        volume = rng.integers(100_000, 1_000_000, size=close.shape)
        return {
            "open": pd.DataFrame(open_, index=dates, columns=symbols),
            "close": pd.DataFrame(close, index=dates, columns=symbols),
            "volume": pd.DataFrame(volume, index=dates, columns=symbols),
        }

    def momentum_factor(self, panel: dict[str, pd.DataFrame], window: int = 20) -> pd.DataFrame:
        close = panel["close"]
        return close / close.shift(window) - 1.0
