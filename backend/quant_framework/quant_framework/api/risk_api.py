"""暴跌风控标识 API：单字标定（爆/险/封），完整说明放 tooltip。

规则来源：《辩驳-暴跌风控-V3.md》三轮辩驳通过版（提示层，非交易策略）：
- 爆（红）：单日收益 <= -7% 且前一日 > -9%（首次冲击）→ 20 日内不接飞刀；
- 险（橙）：爆 且 高位（前60日>30%）+ 缩量（量比<0.8）+ 未破位（最高风险）；
- 封（紫）：当日一字跌停（open 相对昨收 <= -9.8% 且 high==low）→ 卖出不可执行。

数据：腾讯前复权日K（category=4），与 V3 回测口径一致，避免除权假暴跌；
无未来函数：爆/险只用截至当日收盘的数据；封为盘中实时判定。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import numpy as np
import pandas as pd

router = APIRouter(prefix="/api/quant/risk", tags=["quant-risk"])


@router.get("/alert")
def risk_alert(code: str = Query(...), category: int = Query(4), offset: int = Query(160, ge=80, le=400)):
    import astock as astock_mod

    qfq = True
    ex_dates: set[str] = set()
    try:
        rows = astock_mod.kline(code, category=category, offset=offset)
    except Exception as e:  # noqa: BLE001
        rows = None
    df = None
    if rows and len(rows) >= 80:
        df = pd.DataFrame(rows)
    else:
        # 腾讯（前复权）暂不可用时降级新浪（不复权），并用分红除权日排除假暴跌
        qfq = False
        try:
            from run_chan_buy_portfolio import fetch_sina_kline

            sdf = fetch_sina_kline(code, offset)
            if sdf is not None and len(sdf) >= 80:
                df = sdf
                try:
                    ex_dates = {
                        r["date"] for r in astock_mod.dividend_history(code, page_size=50) if r.get("date")
                    }
                except Exception:  # noqa: BLE001
                    ex_dates = set()
        except Exception:  # noqa: BLE001
            df = None
    if df is None:
        return {"code": code, "bars": [], "source": "unavailable"}
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    close = df["close"].astype(float).values
    open_ = df["open"].astype(float).values
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    volume = df["volume"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values

    ret = np.full(len(close), np.nan)
    ret[1:] = close[1:] / close[:-1] - 1.0
    vol20 = pd.Series(volume).rolling(20).mean().values
    vol_ratio = volume / vol20
    pos60 = pd.Series(close).pct_change(60).values
    ma20 = pd.Series(close).rolling(20).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values

    bars: list[dict] = []
    n = len(close)
    for i in range(61, n):
        if not qfq and dates[i] in ex_dates:
            continue  # 不复权降级：排除除权除息日跳空
        if np.isnan(ret[i]) or ret[i] > -0.07 or (i > 0 and not np.isnan(ret[i - 1]) and ret[i - 1] <= -0.09):
            continue
        label, level, note = "爆", 1, "单日跌超7%·20日内不接飞刀"
        broken = close[i] < ma20[i] and close[i] < ma60[i]
        if pos60[i] > 0.30 and vol_ratio[i] < 0.8 and not broken:
            label, level, note = "险", 2, "高位+缩量+未破位·最高风险"
        bars.append({"date": dates[i], "label": label, "level": level, "note": note})
    # 封：盘中实时，仅最后一根（一字跌停，卖出不可执行）
    if n >= 2 and open_[-1] / close[-2] - 1.0 <= -0.098 and high[-1] == low[-1]:
        bars.append({"date": dates[-1], "label": "封", "level": 3, "note": "一字跌停·无法卖出"})
    return {"code": code, "bars": bars[-60:], "source": "qfq" if qfq else "sina+exdiv"}
