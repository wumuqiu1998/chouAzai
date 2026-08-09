"""20 支样本股验证新手信号量：顶/底分布 + 离场规则保护率。

假设卡（简化）：
- 市场观察：综合信号量应在大涨顶部转空、在暴跌底部转多。
- 信号定义：quant_framework.signal_score.compute_signal_score（-100~+100）。
- 数据时间：T 日收盘后计算，T+1 开盘成交。
- 预测目标：顶部后 10 根内“信号量转负”的触发率与回撤保护率（vs 回撤8%）；
  底部后 5 根内信号量回正比例（右侧确认质量）。
- 失败标准：转负触发率过低、保护率显著低于回撤止盈、底部回正比例过低。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.signal_score import compute_signal_score  # noqa: E402
from run_top_exit_study import detect_event  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "data"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def score_at(df: pd.DataFrame, idx: int) -> dict:
    """用截至 idx 收盘的数据计算信号量（不含未来）。"""
    if idx < 59:
        return {"score": 0, "level": "观望"}
    return compute_signal_score(df.iloc[: idx + 1])


def exit_protection(df: pd.DataFrame, ev: dict, rule_name: str, exit_idx: int | None) -> dict:
    """离场规则评估：T 收盘确认、T+1 开盘成交。"""
    if exit_idx is None or exit_idx + 1 >= len(df):
        return {"rule": rule_name, "trigger": None}
    peak_h = ev["peak_high"]
    trough_low = ev["trough_low"]
    base_dd = trough_low / peak_h - 1.0
    exit_px = float(df["open"].iloc[exit_idx + 1])
    avoid = trough_low / exit_px - 1.0
    return {
        "rule": rule_name,
        "trigger": str(df["datetime"].iloc[exit_idx].date()),
        "exit_price": round(exit_px, 2),
        "give_up_pct": round((exit_px / peak_h - 1.0) * 100, 2),
        "avoid_dd_pct": round(avoid * 100, 2),
        "protect_pct": round(avoid / base_dd * 100, 1) if base_dd < 0 else None,
        "days_after_peak": exit_idx - ev["peak_idx"],
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sample = json.loads((OUT_DIR / "sample_stocks_20.json").read_text(encoding="utf-8"))
    stocks = sample["stocks"]
    rows: list[dict] = []
    for s in stocks:
        code = s["code"]
        try:
            klines = astock.kline(code, category=4, offset=300)
        except Exception as e:  # noqa: BLE001
            print(f"{code} {s['name']}: K线失败 {e}")
            continue
        if len(klines) < 120:
            print(f"{code} {s['name']}: 仅{len(klines)}根，跳过（次新/数据不足）")
            continue
        df = pd.DataFrame(klines)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        ev = detect_event(df)
        if ev is None:
            print(f"{code} {s['name']}: 近130根无≥25%暴涨-回撤事件，跳过")
            continue

        top = score_at(df, ev["peak_idx"])
        bottom = score_at(df, ev["trough_idx"])
        # 信号量转负离场：峰值后 10 根内第一个 score<0 的收盘
        score_exit = None
        for i in range(ev["peak_idx"] + 1, min(ev["trough_idx"] + 1, ev["peak_idx"] + 11)):
            if score_at(df, i)["score"] < 0:
                score_exit = i
                break
        # 回撤8%离场（盘中触发）
        stop_exit = None
        for i in range(ev["peak_idx"] + 1, ev["trough_idx"] + 1):
            if float(df["low"].iloc[i]) <= ev["peak_high"] * 0.92:
                stop_exit = i
                break
        r_score = exit_protection(df, ev, "信号量转负", score_exit)
        r_stop = exit_protection(df, ev, "回撤8%", stop_exit)
        # 底部确认：见底后 5 根内信号量是否回到 0 以上
        bottom_ok = False
        for i in range(ev["trough_idx"] + 1, min(len(df), ev["trough_idx"] + 6)):
            if score_at(df, i)["score"] >= 0:
                bottom_ok = True
                break
        rows.append(
            {
                "code": code,
                "name": s["name"],
                "direction": s["direction"],
                "peak_date": ev["peak_date"],
                "trough_date": ev["trough_date"],
                "max_dd": round(ev["max_dd"] * 100, 1),
                "score_at_top": top["score"],
                "level_at_top": top["level"],
                "score_at_bottom": bottom["score"],
                "level_at_bottom": bottom["level"],
                "bottom_ok_5d": bottom_ok,
                **{f"exit_{k}": v for k, v in r_score.items()},
                **{f"stop_{k}": v for k, v in r_stop.items()},
            }
        )
        print(
            f"{code} {s['name']}: 顶 {ev['peak_date']} score={top['score']}({top['level']}) "
            f"| 底 {ev['trough_date']} score={bottom['score']}({bottom['level']}) "
            f"| 信号量离场={r_score.get('trigger') or '未触发'} 保护={r_score.get('protect_pct')}% "
            f"| 回撤8%离场={r_stop.get('trigger') or '未触发'} 保护={r_stop.get('protect_pct')}%"
        )

    dfr = pd.DataFrame(rows)
    if dfr.empty:
        print("无有效样本")
        return
    top_scores = dfr["score_at_top"]
    bot_scores = dfr["score_at_bottom"]
    score_hits = dfr[dfr["exit_trigger"].notna()]
    stop_hits = dfr[dfr["stop_trigger"].notna()]

    lines = [
        "# 新手信号量 20 股验证报告",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　样本：{len(dfr)} 支（排除科创板/北交所/ST，数据不足或近130根无暴涨-回撤事件者跳过）",
        "",
        "## 汇总",
        "",
        f"- 事件顶部信号量平均：**{top_scores.mean():+.1f}**（≤0 占比 {100 * (top_scores <= 0).mean():.0f}%）",
        f"- 事件底部信号量平均：**{bot_scores.mean():+.1f}**（≥0 占比 {100 * (bot_scores >= 0).mean():.0f}%）",
        f"- 顶部后 10 根内“信号量转负”离场：触发 {len(score_hits)}/{len(dfr)}，平均保护率 "
        f"{score_hits['exit_protect_pct'].mean():.0f}%（平均让利 {score_hits['exit_give_up_pct'].mean():+.1f}%）",
        f"- “回撤8%”离场：触发 {len(stop_hits)}/{len(dfr)}，平均保护率 "
        f"{stop_hits['stop_protect_pct'].mean():.0f}%（平均让利 {stop_hits['stop_give_up_pct'].mean():+.1f}%）",
        f"- 见底后 5 根内信号量回到 0 以上：{100 * dfr['bottom_ok_5d'].mean():.0f}%（底部右侧确认质量）",
        "",
        "## 逐股明细",
        "",
        "| 方向 | 代码 | 名称 | 顶日期 | 顶部score | 底部日期 | 底部score | 底后5日回正 | 信号量离场日 | 信号量保护% | 回撤8%离场日 | 回撤8%保护% |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in dfr.iterrows():
        lines.append(
            "| {d} | {c} | {n} | {pd} | {ts} | {td} | {bs} | {bok} | {ed} | {ep} | {sd} | {sp} |".format(
                d=r["direction"], c=r["code"], n=r["name"], pd=r["peak_date"], ts=r["score_at_top"],
                td=r["trough_date"], bs=r["score_at_bottom"],
                bok="是" if r["bottom_ok_5d"] else "否",
                ed=r["exit_trigger"] or "-", ep=r["exit_protect_pct"] if pd.notna(r["exit_protect_pct"]) else "-",
                sd=r["stop_trigger"] or "-", sp=r["stop_protect_pct"] if pd.notna(r["stop_protect_pct"]) else "-",
            )
        )
    lines += ["", "## 结论（小样本筛选）", ""]
    lines += ["- 信号量是右侧确认工具：顶部转负、底部回正都要等结构确认，天然滞后于价格极值。"]
    lines += ["- 离场以“信号量转负”为准（新手看到分数翻绿就减仓），底部以“见底后5日内回正”衡量右侧确认质量。"]
    out = OUT_DIR / "signal_score_study.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{out}")


if __name__ == "__main__":
    main()
