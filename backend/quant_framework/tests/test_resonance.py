import numpy as np
import pandas as pd

from quant_framework.resonance import score_resonance


def _df_from_closes(closes: np.ndarray) -> pd.DataFrame:
    n = len(closes)
    dates = pd.bdate_range("2025-01-02", periods=n)
    o = closes * 0.999
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": o,
            "high": np.maximum(o, closes) * 1.006,
            "low": np.minimum(o, closes) * 0.994,
            "close": closes,
            "volume": np.full(n, 1_000_000.0),
        }
    )


def test_resonance_structure(monkeypatch):
    # 用合成数据替换 astock.kline（不依赖网络）
    df = _df_from_closes(10 * (1.003 ** np.arange(180)))

    class FakeAstock:
        @staticmethod
        def kline(code, category=4, offset=250):
            return df.to_dict("records")

        @staticmethod
        def index_kline(code, offset=320):
            return []

    monkeypatch.setitem(__import__("sys").modules, "astock", FakeAstock())
    res = score_resonance("TEST", category=4, offset=250)
    assert -100 <= res["score"] <= 100
    assert res["rating"] in {"强多", "偏多", "中性", "偏空", "强空"}
    assert set(res["weights"]) == {"market", "wyckoff", "smc"}
    for k in ("market", "wyckoff", "smc"):
        assert "score" in res[k]
