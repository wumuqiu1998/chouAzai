"""板块/概念趋势状态判定（上升 / 下跌 / 震荡）。

口径（无未来函数）：
- 状态只用截至 T 日收盘的数据计算；
- build_regime_map 返回的 {date: state} 中，date 指该状态可用的首个交易日，
  即 T 日收盘算出的状态从 T+1 交易日开始生效。

策略含义（与 t_backtest 配合）：
- up   板块上升 → 顺趋势做多T（中枢下轨低吸 / B点买入，先买后卖）；
- down 板块下跌 → 顺趋势做空T（中枢上轨高抛 / S点卖出，先卖后买）；
- range 板块震荡 → 双向做T（B/S 双向或中枢双向）。
"""

from __future__ import annotations

import pandas as pd


def classify_regime(
    close: pd.Series,
    trend_period: int = 20,
    slow_period: int = 60,
    slope_window: int = 5,
    slope_threshold: float = 0.004,
) -> pd.Series:
    """均线法三态分类：up / down / range。

    up   : close > MA(trend) > MA(slow) 且 MA(trend) 近 slope_window 日斜率为正；
    down : close < MA(trend) < MA(slow) 且斜率为负；
    range: 其余（均线缠绕 / 斜率平缓 / 数据不足）。
    """
    ma_fast = close.rolling(trend_period, min_periods=trend_period).mean()
    ma_slow = close.rolling(slow_period, min_periods=slow_period).mean()
    slope = ma_fast / ma_fast.shift(slope_window) - 1.0

    states = pd.Series("range", index=close.index, dtype=object)
    up = (close > ma_fast) & (ma_fast > ma_slow) & (slope > slope_threshold)
    down = (close < ma_fast) & (ma_fast < ma_slow) & (slope < -slope_threshold)
    states[up] = "up"
    states[down] = "down"
    return states


def classify_regime_adx(
    daily: pd.DataFrame,
    adx_period: int = 14,
    adx_threshold: float = 22.0,
) -> pd.Series:
    """ADX 三态分类：ADX 高且 +DI > -DI → up；ADX 高且 -DI > +DI → down；否则 range。"""
    high = daily["high"].astype(float)
    low = daily["low"].astype(float)
    close = daily["close"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        ((up_move > down_move) & (up_move > 0)).astype(float) * up_move,
        index=daily.index,
    )
    minus_dm = pd.Series(
        ((down_move > up_move) & (down_move > 0)).astype(float) * down_move,
        index=daily.index,
    )
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)

    def wilder(s: pd.Series) -> pd.Series:
        return s.ewm(alpha=1.0 / adx_period, min_periods=adx_period, adjust=False).mean()

    atr = wilder(tr)
    plus_di = 100 * wilder(plus_dm) / atr.replace(0, pd.NA)
    minus_di = 100 * wilder(minus_dm) / atr.replace(0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx = wilder(dx)

    states = pd.Series("range", index=daily.index, dtype=object)
    states[(adx > adx_threshold) & (plus_di > minus_di)] = "up"
    states[(adx > adx_threshold) & (minus_di > plus_di)] = "down"
    return states


def build_regime_map(
    daily: pd.DataFrame,
    method: str = "ma",
    trend_period: int = 20,
    slow_period: int = 60,
    slope_window: int = 5,
    slope_threshold: float = 0.0,
    adx_threshold: float = 22.0,
) -> dict[str, str]:
    """把日线 DataFrame 转成 {date: state}。

    状态按 T 日收盘计算、从 T+1 交易日开始生效（无未来函数）。
    键为 datetime.date 对象（与 t_backtest 的 day 键一致）。
    """
    ddf = daily.copy()
    if "datetime" in ddf.columns:
        dts = pd.to_datetime(ddf["datetime"])
    else:
        dts = pd.to_datetime(ddf["date"])
    ddf = ddf.assign(_dt=dts).sort_values("_dt").reset_index(drop=True)
    g = ddf.groupby(ddf["_dt"].dt.date)
    close = g["close"].last()
    if method == "adx":
        daily_agg = pd.DataFrame({
            "close": g["close"].last(),
            "high": g["high"].max(),
            "low": g["low"].min(),
        })
        states = classify_regime_adx(daily_agg, adx_threshold=adx_threshold)
    else:
        states = classify_regime(
            close,
            trend_period=trend_period,
            slow_period=slow_period,
            slope_window=slope_window,
            slope_threshold=slope_threshold,
        )
    # T 日状态从 T+1 生效：状态序列整体后移一天
    effective = states.shift(1)
    return {d: str(state) for d, state in effective.items() if pd.notna(state)}


def pick_main_block(boards: list[dict]) -> dict | None:
    """从东财概念归属列表里挑“主行业板块”（排除地域/风格/资金类）。"""
    exclude_kw = (
        "板块", "概念", "融资融券", "深股通", "沪股通", "富时", "MSCI", "标普",
        "基金重仓", "证金", "汇金", "深成", "沪深", "创业板综", "中证",
        "央国企", "国企改革", "机构重仓", "QFII", "养老金", "社保",
    )
    candidates = [b for b in boards if not any(k in str(b.get("name", "")) for k in exclude_kw)]
    if not candidates:
        candidates = list(boards)
    if not candidates:
        return None
    return candidates[0]


def resolve_regime_source(
    code: str,
    concept: dict | None = None,
    etf_block: str | None = None,
) -> tuple[str, str | None, list[dict]]:
    """解析个股的趋势判断源，返回 (source_type, block_name, daily_rows)。

    source_type: "block"（板块指数日K） / "self"（个股/ETF自身日K兜底）。
    """
    import astock

    boards = (concept or {}).get("boards") or []
    etf_map = {"516080": ("化学制药", "881140")}

    # 0) ETF 手动映射：创新药ETF → 化学制药行业指数
    if code in etf_map:
        rows = astock.ths_block_kline(etf_map[code][1], days=320)
        if rows:
            return "block", f"{etf_map[code][0]}（同花顺{etf_map[code][1]}）", rows

    # 候选板块名：东财归属前几个（排除地域/风格）+ ETF 名称
    candidates: list[str] = []
    main = pick_main_block(boards)
    if main:
        candidates.append(str(main.get("name", "")))
    for b in boards[1:5]:
        candidates.append(str(b.get("name", "")))
    if etf_block:
        candidates.append(etf_block)
    seen: set[str] = set()
    for name in candidates:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        # 1) 东财板块K线（东财 BK 代码）
        bk_code = next(
            (str(b["code"]).upper() for b in boards if str(b.get("name", "")) == name and b.get("code")),
            None,
        )
        if bk_code:
            rows = astock.block_kline(bk_code, days=320)
            if rows:
                return "block", f"{name}（东财{bk_code}）", rows
        # 2) 同花顺板块指数（按名称匹配）
        ths_code = astock.ths_block_code_by_name(name)
        if ths_code:
            rows = astock.ths_block_kline(ths_code, days=320)
            if rows:
                return "block", f"{name}（同花顺{ths_code}）", rows
    rows = astock.kline(code, category=4, offset=320)
    return "self", None, rows


_BLOCK_NAME_CACHE: dict[str, str] = {}


def _find_block_code_by_name(name: str) -> str | None:
    """按板块名查东财概念板块代码；失败返回 None。"""
    import astock

    if name in _BLOCK_NAME_CACHE:
        return _BLOCK_NAME_CACHE[name] or None
    try:
        r = astock.em_get(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1", "pz": "1000", "po": "1", "np": "1", "fltt": "2", "invt": "2",
                "fid": "f3", "fs": "m:90+t:3", "fields": "f12,f14",
            },
            headers={"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=12,
        )
        items = r.json().get("data", {}).get("diff", [])
        if isinstance(items, dict):
            items = list(items.values())
        hit = next((it for it in items if str(it.get("f14", "")) == name), None)
        code = str(hit.get("f12", "")).upper() if hit else None
    except Exception:
        code = None
    _BLOCK_NAME_CACHE[name] = code or ""
    return code
