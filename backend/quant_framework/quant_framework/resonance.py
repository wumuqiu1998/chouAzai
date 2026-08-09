"""三信号共振评分：市场趋势（道士）+ 威科夫筹码阶段 + ICT/SMC 结构。

评分范围 -100 ~ +100，各分项先归一化到 [-1, 1] 再按权重合成：
- 市场趋势 30%：强上升=+1、上升=+0.6、震荡=0、下跌=-0.6、强下跌=-1
- 威科夫 40%：阶段（拉升+0.5/吸筹+0.4/震荡0/派发-0.4/下跌-0.5）
  + Spring(+0.3)/Upthrust(-0.3) + 成本区位置（现价在主力成本下方+0.15/上方-0.15）
- ICT/SMC 30%：结构方向 + BOS/CHoCH + 最近流动性扫荡 + 未回补FVG方向

全部输入都只用已收盘数据（T 日收盘后可用，T+1 生效），与各模块口径一致。
"""

from __future__ import annotations

import pandas as pd

from quant_framework.market_regime import analyze_market
from quant_framework.smc import analyze_smc
from quant_framework.wyckoff import analyze_wyckoff

MARKET_SCORE = {"strong_up": 1.0, "up": 0.6, "range": 0.0, "down": -0.6, "strong_down": -1.0}
PHASE_SCORE = {"markup": 0.5, "accumulation": 0.4, "range": 0.0, "distribution": -0.4, "markdown": -0.5}


def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def score_resonance(
    code: str,
    category: int = 4,
    offset: int = 250,
    exclude_last: bool = False,
    market_weight: float = 0.3,
    wyckoff_weight: float = 0.4,
    smc_weight: float = 0.3,
) -> dict:
    import astock

    rows = astock.kline(code, category=category, offset=offset)
    if not rows:
        raise ValueError("K线数据为空")
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    analyze_df = df.iloc[:-1] if exclude_last else df

    # 1) 市场趋势
    mkt = analyze_market()
    market_state = mkt["market"]["state"]
    market_score = MARKET_SCORE.get(market_state, 0.0)

    # 2) 威科夫
    wk = analyze_wyckoff(analyze_df)
    wk_score = PHASE_SCORE.get(wk["current"]["phase"], 0.0)
    wk_notes: list[str] = []
    for s in wk["signals"]:
        if s["kind"] == "spring":
            wk_score += 0.3
            wk_notes.append("Spring 吸筹确认")
        elif s["kind"] == "upthrust":
            wk_score -= 0.3
            wk_notes.append("Upthrust 派发确认")
    cz = wk.get("cost_zone")
    if cz and wk["last_close"]:
        if wk["last_close"] < cz["mid"]:
            wk_score += 0.15
            wk_notes.append("现价在主力成本区下方")
        elif wk["last_close"] > cz["high"]:
            wk_score -= 0.15
            wk_notes.append("现价高于主力成本区")
    wk_score = _clip(wk_score)

    # 3) ICT/SMC
    smc = analyze_smc(analyze_df)
    smc_score = 0.0
    smc_notes: list[str] = []
    st = smc["structure"]
    if st["state"] == "bullish":
        smc_score += 0.3
    elif st["state"] == "bearish":
        smc_score -= 0.3
    if st.get("last_bos"):
        if st["last_bos"]["kind"] == "bullish":
            smc_score += 0.2
            smc_notes.append("BOS 向上突破（趋势延续）")
        else:
            smc_score -= 0.2
            smc_notes.append("BOS 向下突破（趋势延续）")
    if st.get("last_choch"):
        if st["last_choch"]["kind"] == "bullish":
            smc_score += 0.2
            smc_notes.append("CHoCH 转多（结构变化）")
        else:
            smc_score -= 0.2
            smc_notes.append("CHoCH 转空（结构变化）")
    if smc["sweeps"]:
        last = smc["sweeps"][-1]
        if last["kind"] == "bullish":
            smc_score += 0.25
            smc_notes.append("最近流动性扫荡偏多（SSL 被扫后收回）")
        else:
            smc_score -= 0.25
            smc_notes.append("最近流动性扫荡偏空（BSL 被扫后收回）")
    unfilled = [g for g in smc["fvg"] if not g["filled"]]
    if unfilled:
        last_fvg = unfilled[-1]
        if last_fvg["kind"] == "bullish":
            smc_score += 0.1
            smc_notes.append("存在未回补看涨 FVG")
        else:
            smc_score -= 0.1
            smc_notes.append("存在未回补看跌 FVG")
    smc_score = _clip(smc_score)

    total = round(
        market_score * market_weight + wk_score * wyckoff_weight + smc_score * smc_weight,
        2,
    )
    total = round(_clip(total, -100, 100) * 100, 1)

    if total >= 60:
        rating = "强多"
    elif total >= 30:
        rating = "偏多"
    elif total > -30:
        rating = "中性"
    elif total > -60:
        rating = "偏空"
    else:
        rating = "强空"

    return {
        "score": total,
        "rating": rating,
        "weights": {
            "market": market_weight,
            "wyckoff": wyckoff_weight,
            "smc": smc_weight,
        },
        "market": {
            "score": round(market_score * 100, 1),
            "state": market_state,
            "label": mkt["market"]["label"],
        },
        "wyckoff": {
            "score": round(wk_score * 100, 1),
            "phase": wk["current"]["phase"],
            "phase_label": {
                "markup": "拉升",
                "accumulation": "吸筹",
                "range": "震荡",
                "distribution": "派发",
                "markdown": "下跌",
            }.get(wk["current"]["phase"], wk["current"]["phase"]),
            "signals": wk_notes,
        },
        "smc": {
            "score": round(smc_score * 100, 1),
            "structure": st["state"],
            "notes": smc_notes,
        },
        "notes": [
            *([f"市场：{mkt['market']['label']}"] if mkt["indices"] else []),
            *([f"威科夫：{wk['current']['phase']}"] if wk["current"]["phase"] else []),
            *smc_notes,
        ],
        "note": "共振评分=市场30%+威科夫40%+ICT/SMC 30%，仅供参考，不构成交易建议",
    }
