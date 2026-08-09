# ATR 通道与顶/底信号

## 算法

- TR = max(high-low, |high-prev_close|, |low-prev_close|)
- ATR = TR 的 Wilder 平滑（period=14）
- mid = MA20；upper = mid + mult*ATR；lower = mid - mult*ATR（mult=2.5）
- 超涨：close > upper（预警）；超跌：close < lower（预警）

## 顶/底确认（过滤版，默认参数）

- confirm_amp_mult=1.0：超涨段结束后回落 >= 1×ATR 才算顶（超跌对称）。
- max_confirm_bars=3：幅度不足时延迟最多 3 根确认；价格反向则作废，继续创新低/新高则顺延基准。
- min_same_kind_gap=5：同类顶/底最小间隔。
- 顶/底价格取段内真实极值（超涨段最高 high / 超跌段最低 low），不是确认日收盘。
- 作用：主升浪中 6 个连续小回调顶 → 收敛为 1 个真实顶（例：600487 6-26 确认顶 124.89）。

## 注意

- 通道基于 MA20 有滞后，确认日通常比真实极值晚 1~3 根。
- 任意周期可用（1/5/15/30/60 分、日/周/月）；盘中用 exclude_last 排除未收盘末根。
- ATR 顶 ≈ “最高点回撤 10%”止盈（样本上常同日触发）。
