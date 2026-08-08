import numpy as np
import pandas as pd
import pytest

from quant_framework.factor_lib import FACTORS, compute


@pytest.fixture
def panel():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2024-01-02", periods=60)
    syms = ["A", "B", "C"]
    close = pd.DataFrame(
        10 * np.exp(np.cumsum(rng.normal(0.001, 0.01, (60, 3)), axis=0)),
        index=dates,
        columns=syms,
    )
    volume = pd.DataFrame(rng.integers(100_000, 1_000_000, (60, 3)), index=dates, columns=syms)
    return close, volume


def test_all_factors_shape_and_no_inf(panel):
    close, volume = panel
    for name in FACTORS:
        f = compute(name, close, volume=volume, window=10)
        assert f.shape == close.shape
        assert not np.isinf(f.values).any()


def test_momentum_warmup_nan(panel):
    close, _ = panel
    f = compute("momentum", close, window=20)
    assert f.iloc[:19].isna().all().all()
    assert f.iloc[20:].notna().all().all()


def test_unknown_factor_raises(panel):
    close, _ = panel
    with pytest.raises(KeyError):
        compute("no_such_factor", close)


def test_volume_factor_requires_volume(panel):
    close, _ = panel
    with pytest.raises(ValueError):
        compute("volume_surge", close, volume=None)
