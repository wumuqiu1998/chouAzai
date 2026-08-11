"""combo_top5 抗多重检验诊断 + trail 盘中触发参数扫描。

Part A（置换检验）：在“全量卖出信号实验”同一事件池（原 50 只、最近一年、
新浪日K、seed=20260810）上，从 14 个卖出信号中随机抽取 200 组 5 信号组合
（seed=20260811），每组跑 10 持仓/20% 仓位组合回测，报告 combo_top5
（divergence+overheat+warn+trail12+sweep）总收益在随机分布中的百分位。
这直接回应“在众多组合里挑出收益最高者=多重检验”的质疑。

Part B（trail 盘中触发）：原 trailing_exit 用收盘价判断回撤，真实盘中应先被
low 触发。改为“low 触发、触发日收盘成交”（保守口径），扫描 5/8/10/12/14/16
六档，分别做单信号与组合（divergence+overheat+warn+trail{pct}+sweep）。
"""

from __future__ import annotations

import random
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_framework.chan import analyze_chan_locked  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402
from run_chan_buy_portfolio import fetch_sina_kline, run_portfolio  # noqa: E402
from run_exit_signals_all import MAX_HOLD, build_signal_maps, first_exit, trailing_exit  # noqa: E402

SEED_POOL = 20260810
SEED_PERM = 20260811
N = 50
N_PERM = 200
COMBO = ("divergence", "overheat", "warn", "trail12", "sweep")
MAP_SIGNALS = ("chan", "warn", "atr_top", "overheat", "upthrust", "sweep", "break", "choch", "vol_div", "ma20", "divergence")
TRAIL_PCTS = (5, 8, 10, 12, 14, 16)
OUT = Path(__file__).resolve().parent / "data" / "combo_diagnostics.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def build_events(df: pd.DataFrame, lows_mode: bool, code: str) -> list[dict]:
    """复制 run_exit_signals_all.main 的事件口径，trail 可按收盘/盘中触发。"""
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    lows = df["low"].astype(float).values
    dates = df["datetime"].dt.strftime("%Y-%m-%d").values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    maps = build_signal_maps(df)
    events: list[dict] = []
    for p in analyze_chan_locked(df)["points"]:
        j = im.get(p["date"])
        if j is None or not p["kind"].startswith("buy"):
            continue
        known = p.get("known_at", j)
        b = max(j + 2, known + 1)
        if b + 5 >= len(closes):
            continue
        prev = closes[b - 1]
        buy = opens[b]
        if prev <= 0 or buy <= 0 or buy / prev - 1.0 >= 0.098:
            continue
        i_synth = b - 2
        e: dict = {
            "code": code,
            "type": p["kind"],
            "buy_date": dates[b],
            "buy_px": buy,
            "blocked": False,
            "exits": {},
        }
        for sig in MAP_SIGNALS:
            ex = first_exit(maps[sig], dates, i_synth)
            if ex:
                e["exits"][sig] = ex
        for pct in TRAIL_PCTS:
            key = f"trail{pct}"
            if lows_mode:
                ex = trailing_exit(closes, dates, i_synth, pct / 100.0, lows=lows)
            else:
                ex = trailing_exit(closes, dates, i_synth, pct / 100.0)
            if ex:
                e["exits"][key] = ex
        fallback_k = min(b + MAX_HOLD, len(closes) - 1)
        e["fallback"] = (dates[fallback_k], closes[fallback_k])
        events.append(e)
    return events


def collect(code: str, df: pd.DataFrame, close_map: dict) -> list[dict]:
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    for _, row in df.iterrows():
        d = str(row["datetime"].date())
        close_map.setdefault(d, {})[code] = float(row["close"])
    evs = build_events(df, lows_mode=True, code=code)
    evs_close = build_events(df, lows_mode=False, code=code)
    # 合并两套 trail 口径：Part A 用收盘口径（与原始实验一致），Part B 用盘中口径
    # 同一 df 的两遍分析顺序一致，按索引配对（同一天可能有多个买点）
    for e, base in zip(evs, evs_close):
        e["exits_close"] = base["exits"]
        e["fallback_close"] = base["fallback"]
    return evs


def run_combo(events: list[dict], combo: tuple[str, ...], close_map: dict, use_close: bool = False) -> dict:
    evs_round = []
    for e in events:
        src = e["exits_close"] if use_close else e["exits"]
        cands = [(src[s][0], src[s][1]) for s in combo if s in src]
        ex = min(cands, key=lambda x: x[0]) if cands else e["fallback_close" if use_close else "fallback"]
        evs_round.append({**e, "sell_date": ex[0], "sell_px": ex[1]})
    return run_portfolio(evs_round, 10, 0.2, close_map, exit_rule="fixed")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED_POOL)
    sample = rng.sample(universe, min(N, len(universe)))
    close_map: dict[str, dict[str, float]] = {}
    events: list[dict] = []
    for s in sample:
        code = s["code"]
        df = fetch_sina_kline(code, 260)
        if df is None or len(df) < 250:
            continue
        events.extend(collect(code, df, close_map))
        print(f"{code} done, events={len(events)}", flush=True)

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# combo_top5 抗多重检验诊断 + trail 盘中触发扫描",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　事件数：{len(events)}　"
        f"组合：{' + '.join(COMBO)}",
        "",
        "## Part A：随机 5 信号置换检验（200 组）",
        "",
        "在 14 个卖出信号中随机抽 5 个（不放回，seed=20260811），口径与全量实验一致"
        "（trail 为收盘触发），10 持仓/20% 仓位，含费用与涨跌停约束。",
        "",
    ]

    base = run_combo(events, COMBO, close_map, use_close=True)
    base_ret = base["total_ret"]
    all_sigs = MAP_SIGNALS + ("trail5", "trail8", "trail12")
    perm_rng = random.Random(SEED_PERM)
    dist: list[tuple[tuple[str, ...], float, float, float]] = []
    for _ in range(N_PERM):
        combo = tuple(sorted(perm_rng.sample(all_sigs, 5)))
        r = run_combo(events, combo, close_map, use_close=True)
        dist.append((combo, r["total_ret"], r["mdd"], r["win_rate"]))
    rets = [d[1] for d in dist]
    below = sum(1 for v in rets if v < base_ret)
    ge = sum(1 for v in rets if v >= base_ret)
    percentile = below / max(1, len(rets)) * 100
    lines += [
        f"| 指标 | combo_top5（基准） | 200 组随机组合分布 |",
        "|---|---|---|",
        f"| 总收益 | {base_ret * 100:+.1f}% | 均值 {np.mean(rets) * 100:+.1f}% / 中位 {np.median(rets) * 100:+.1f}% / 最大 {max(rets) * 100:+.1f}% |",
        f"| 胜率 | {base['win_rate'] * 100:.0f}% | 均值 {np.mean([d[3] for d in dist]) * 100:.0f}% |",
        f"| 回撤 | {base['mdd'] * 100:.1f}% | 均值 {np.mean([d[2] for d in dist]) * 100:.1f}% |",
        f"| 超越组合数 | — | {ge}/{N_PERM}（{ge / max(1, len(rets)) * 100:.1f}%） |",
        "",
        f"combo_top5 位于随机分布第 **{percentile:.1f}** 百分位"
        f"（{below}/{N_PERM} 组低于基准）。",
        "",
    ]
    top5 = sorted(dist, key=lambda d: d[1], reverse=True)[:5]
    lines += ["随机分布中收益最高的 5 组组合：", "", "| 组合 | 总收益 | 胜率 | 回撤 |", "|---|---|---|---|"]
    for combo, tr, mdd, wr in top5:
        lines.append(f"| {'+'.join(combo)} | {tr * 100:+.1f}% | {wr * 100:.0f}% | {mdd * 100:.1f}% |")
    log.append(
        ExperimentRecord(
            experiment_id="COMBO-PERM-200",
            hypothesis="combo_top5 的总收益显著高于随机 5 信号组合，选择非多重检验偶然",
            unique_change=f"n_perm={N_PERM}, seed={SEED_PERM}, combo={'+'.join(COMBO)}",
            expected="随机组合均值远低于基准，超越组合数 <=5%",
            dev_result=f"基准 {base_ret * 100:+.1f}%；随机均值 {np.mean(rets) * 100:+.1f}%、最大 {max(rets) * 100:+.1f}%",
            val_result=f"百分位 {percentile:.1f}%，超越组合 {ge}/{N_PERM}",
            cost_result=f"基准回撤 {base['mdd'] * 100:.1f}%，随机均值回撤 {np.mean([d[2] for d in dist]) * 100:.1f}%",
            passed=False,
            failure_reason="单一年窗口/单一样本池；随机组合仍有超过基准的可能需样本外复核",
            code_version=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev",
        )
    )

    lines += [
        "",
        "## Part B：trail 盘中触发（low 触发、触发日收盘成交）参数扫描",
        "",
        "| 触发口径 | 信号 | 笔数 | 触发率 | 单笔 | 胜率 | 总收益 | 回撤 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    base_close = run_combo(events, COMBO, close_map, use_close=True)
    base_low = run_combo(events, COMBO, close_map, use_close=False)
    for label, r in (("收盘触发 trail12（原口径）", base_close), ("盘中触发 trail12（新口径）", base_low)):
        nets = [t["ret"] for t in r["trades"] if t.get("ret") is not None]
        lines.append(
            f"| {label} | combo_top5 | {r['n_trades']} | — | {np.mean(nets) * 100:+.2f}% | "
            f"{r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% |"
        )
    for pct in TRAIL_PCTS:
        key = f"trail{pct}"
        for label, sigs, cname in (
            ("单信号", (key,), f"TRAIL-LOW-{pct}"),
            ("组合", COMBO[:3] + (key,) + COMBO[4:], f"COMBO-TRAIL-LOW-{pct}"),
        ):
            trig = 0
            evs_round = []
            for e in events:
                cands = [(e["exits"][s][0], e["exits"][s][1]) for s in sigs if s in e["exits"]]
                if cands:
                    ex = min(cands, key=lambda x: x[0])
                    trig += 1
                else:
                    ex = e["fallback"]
                evs_round.append({**e, "sell_date": ex[0], "sell_px": ex[1]})
            r = run_portfolio(evs_round, 10, 0.2, close_map, exit_rule="fixed")
            nets = [t["ret"] for t in r["trades"] if t.get("ret") is not None]
            avg = float(np.mean(nets)) if nets else 0.0
            lines.append(
                f"| 盘中触发 | {label} trail{pct}% | {r['n_trades']} | {trig / max(1, len(events)) * 100:.0f}% | "
                f"{avg * 100:+.2f}% | {r['win_rate'] * 100:.0f}% | {r['total_ret'] * 100:+.1f}% | {r['mdd'] * 100:.1f}% |"
            )
            log.append(
                ExperimentRecord(
                    experiment_id=f"{cname}-10-20",
                    hypothesis=f"trail 盘中触发（low）参数 {pct}%：{label}",
                    unique_change=f"trail_intraday={pct}, low_trigger=True, fill=close",
                    expected="盘中触发早于收盘触发，回撤下降但可能损失收益",
                    dev_result=f"触发率 {trig / max(1, len(events)) * 100:.0f}%，单笔 {avg * 100:+.2f}%，胜率 {r['win_rate'] * 100:.0f}%",
                    val_result="",
                    cost_result=f"总收益 {r['total_ret'] * 100:+.1f}%，回撤 {r['mdd'] * 100:.1f}%",
                    passed=False,
                    failure_reason="单一年窗口/单一样本池，未做样本外与盲测",
                    code_version=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev",
                )
            )
    lines += ["", "## 结论", ""]
    lines.append("- 若基准位于随机分布高位（如 >95 百分位），多重检验质疑不成立；否则组合选择可能含偶然成分。")
    lines.append("- 盘中触发比收盘触发更贴近真实：触发更早，观察回撤是否下降、收益是否损失，选择性价比最高的档位。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}，日志追加 {1 + len(TRAIL_PCTS) * 2} 条")


if __name__ == "__main__":
    main()
