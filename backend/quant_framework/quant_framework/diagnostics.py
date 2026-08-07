"""信号诊断：不只看总收益，检查信号本身。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _spearman(a: pd.Series, b: pd.Series) -> float:
    """免 scipy 的 Spearman 秩相关：对两个序列排名后计算 Pearson。"""
    ra = a.rank(method="average")
    rb = b.rank(method="average")
    return float(ra.corr(rb, method="pearson"))


def _forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """未来 horizon 日收益（date × symbol）。"""
    return close.shift(-horizon) / close - 1.0


def ic_series(factor: pd.Series, fwd_ret: pd.Series, method: str = "spearman") -> pd.Series:
    """按日期截面计算 IC / RankIC。"""
    dates = factor.index.get_level_values(0).unique().intersection(
        fwd_ret.index.get_level_values(0).unique()
    )
    out = {}
    for d in dates:
        f = factor.xs(d, level=0).dropna()
        r = fwd_ret.xs(d, level=0).reindex(f.index).dropna()
        common = f.index.intersection(r.index)
        if len(common) < 5:
            continue
        if method == "spearman":
            out[d] = _spearman(f.loc[common], r.loc[common])
        else:
            out[d] = f.loc[common].corr(r.loc[common], method="pearson")
    return pd.Series(out, name=f"ic_{method}")


def rank_ic(factor: pd.Series, fwd_ret: pd.Series) -> pd.Series:
    return ic_series(factor, fwd_ret, method="spearman")


def grouped_returns(factor: pd.Series, fwd_ret: pd.Series, n_groups: int = 10) -> pd.DataFrame:
    """按因子值从低到高分 n 组，返回每组未来收益均值（分组单调性）。"""
    dates = factor.index.get_level_values(0).unique().intersection(
        fwd_ret.index.get_level_values(0).unique()
    )
    rows = []
    for d in dates:
        f = factor.xs(d, level=0).dropna()
        r = fwd_ret.xs(d, level=0).reindex(f.index).dropna()
        common = f.index.intersection(r.index)
        if len(common) < n_groups:
            continue
        f = f.loc[common]
        r = r.loc[common]
        q = pd.qcut(f.rank(method="first"), n_groups, labels=False) + 1
        rows.append(
            pd.DataFrame(
                {
                    "date": d,
                    "group": q,
                    "ret": r.values,
                }
            )
        )
    if not rows:
        return pd.DataFrame(columns=["group", "mean_ret", "count"])
    df = pd.concat(rows)
    return df.groupby("group")["ret"].agg(["mean", "count"]).rename(
        columns={"mean": "mean_ret", "count": "count"}
    )


def monotonicity_check(groups: pd.DataFrame) -> dict:
    """分组收益是否单调。返回 spearman 相关与是否通过。"""
    if groups.empty or len(groups) < 3:
        return {"monotonic": False, "spearman": float("nan"), "top_minus_bottom": float("nan")}
    g = groups["mean_ret"]
    corr = g.rank().corr(pd.Series(g.index, index=g.index))
    tmb = float(g.iloc[-1] - g.iloc[0])
    return {
        "monotonic": bool(corr > 0.7),
        "spearman": float(corr),
        "top_minus_bottom": tmb,
    }


def factor_decay(
    factor: pd.Series, close: pd.DataFrame, horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
) -> pd.Series:
    """因子对未来不同持有期的预测能力（衰减）。"""
    dates = factor.index.get_level_values(0).unique()
    out = {}
    for h in horizons:
        fwd = _forward_returns(close, h)
        fwd = fwd.stack().dropna()
        common_dates = dates.intersection(fwd.index.get_level_values(0).unique())
        vals = []
        for d in common_dates:
            f = factor.xs(d, level=0).dropna()
            r = fwd.xs(d, level=0).reindex(f.index).dropna()
            common = f.index.intersection(r.index)
            if len(common) < 5:
                continue
            vals.append(_spearman(f.loc[common], r.loc[common]))
        vals = [v for v in vals if v == v]
        out[h] = float(np.mean(vals)) if vals else float("nan")
    return pd.Series(out, name="rank_ic_by_horizon")


def concentration(returns: pd.Series, by: str = "year", top: float = 0.2) -> dict:
    """收益集中度：总收益是否集中在少数股票/月份/年份/行业。"""
    if returns.empty:
        return {"top_share": float("nan"), "hhi": float("nan"), "n": 0}
    abs_ret = returns.abs()
    share = abs_ret / abs_ret.sum()
    n_top = max(1, int(len(share) * top))
    top_share = float(share.nlargest(n_top).sum())
    hhi = float((share**2).sum())
    return {"top_share": top_share, "hhi": hhi, "n": int(len(returns))}
