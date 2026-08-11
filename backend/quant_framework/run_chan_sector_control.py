"""缠论买点同板块异股对照：信号组 vs 同行业不同股票对照组。

设计（回应“随机基准不能只看同一批股票的随机日期”的质疑）：
- 信号组：原 50 只随机股（seed=20260810）的缠论买点（锁定口径）；
- 对照组：为每只信号股按东财行业（f100）配对 1 只**同行业、不同股票**，
  对照组样本 = 配对股票的全部非信号日期（排除其自身缠论买点 ±2 根）；
- 两组完全同口径：执行日 max(点+2, 首次可见+1) 开盘买入、持有 H 日收盘卖出，
  佣金 0.0003×2 + 印花税 0.0005 + 滑点 0.0001×2，涨停买不进跳过、跌停按估值。
"""

from __future__ import annotations

import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.chan import analyze_chan_locked  # noqa: E402
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_blind_test import fetch_universe  # noqa: E402

SEED = 20260810
SEED_PAIR = 20260811
N = 50
HORIZONS = (5, 10, 15, 20)
LIMIT = 0.098
COMMISSION = 0.0003
STAMP = 0.0005
SLIPPAGE = 0.0001
OUT = Path(__file__).resolve().parent / "data" / "chan_sector_control.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def fetch_industries(max_pages: int = 45) -> dict[str, str]:
    """东财全市场 code -> 行业（f100），分页 + 限流。"""
    out: dict[str, str] = {}
    for pn in range(1, max_pages + 1):
        try:
            r = astock.em_get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                    "fields": "f12,f14,f100",
                },
                headers=UA, timeout=12,
            )
            diff = (r.json().get("data") or {}).get("diff") or []
            if not diff:
                break
            for d in diff:
                code = str(d.get("f12", ""))
                ind = str(d.get("f100", "") or "").strip()
                name = str(d.get("f14", "") or "")
                if code and ind not in ("", "-") and "ST" not in name.upper() and "退" not in name:
                    out[code] = ind
        except Exception as e:  # noqa: BLE001
            print("industry page warn", pn, e, flush=True)
        time.sleep(1.0)
    return out


def net_of(base: float, sell: float) -> float:
    buy_px = base * (1 + SLIPPAGE)
    sell_px = sell * (1 - SLIPPAGE)
    return sell_px / buy_px - 1.0 - COMMISSION * 2 - STAMP


def load(code: str) -> pd.DataFrame | None:
    try:
        rows = astock.kline(code, category=4, offset=260)
    except Exception:  # noqa: BLE001
        return None
    if not rows or len(rows) < 250:
        return None
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.sort_values("datetime").reset_index(drop=True)


def collect(df: pd.DataFrame, h_max: int) -> tuple[list[int], set[int]]:
    """锁定口径买点执行日列表 + 集合。"""
    opens = df["open"].astype(float).values
    closes = df["close"].astype(float).values
    im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
    buys: list[int] = []
    for p in analyze_chan_locked(df)["points"]:
        j = im.get(p["date"])
        if j is None or not p["kind"].startswith("buy"):
            continue
        b = max(j + 2, p.get("known_at", j) + 1)
        if b + h_max < len(closes):
            buys.append(b)
    return buys, set(buys)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))
    print("拉行业映射...", flush=True)
    ind_map = fetch_industries()
    rng2 = random.Random(SEED_PAIR)
    pairs: list[tuple[str, str, str]] = []  # (sig_code, ctrl_code, industry)
    skipped: list[tuple[str, str]] = []
    for s in sample:
        code = s["code"]
        ind = ind_map.get(code, "")
        if not ind:
            skipped.append((code, "无行业"))
            continue
        cands = [c for c, i in ind_map.items() if i == ind and c != code]
        if not cands:
            skipped.append((code, f"行业[{ind}]无配对"))
            continue
        pairs.append((code, rng2.choice(cands), ind))
    print(f"配对 {len(pairs)}/{len(sample)}，跳过 {len(skipped)}", flush=True)

    sig_nets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    ctrl_nets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    sig_rets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    ctrl_rets: dict[int, list[float]] = {h: [] for h in HORIZONS}
    h_max = max(HORIZONS)

    for sig_code, ctrl_code, ind in pairs:
        sdf = load(sig_code)
        cdf = load(ctrl_code)
        if sdf is None or cdf is None:
            continue
        s_buys, s_set = collect(sdf, h_max)
        c_buys, c_set = collect(cdf, h_max)
        # 信号组：只统计缠论买点
        s_opens = sdf["open"].astype(float).values
        s_closes = sdf["close"].astype(float).values
        for h in HORIZONS:
            for b in s_buys:
                if b + h >= len(s_closes):
                    continue
                prev = s_closes[b - 1]
                if prev <= 0 or s_opens[b] <= 0 or s_opens[b] / prev - 1.0 >= LIMIT - 1e-6:
                    continue
                sell = s_closes[b + h]
                sig_rets[h].append(sell / s_opens[b] - 1.0)
                sig_nets[h].append(net_of(s_opens[b], sell))
        # 对照组：只统计同行业对照股的全日期（排除其自身缠论买点 ±2 根）
        c_opens = cdf["open"].astype(float).values
        c_closes = cdf["close"].astype(float).values
        for h in HORIZONS:
            for i in range(1, len(c_closes) - h):
                if any((i + d) in c_set for d in (-2, -1, 0, 1, 2)):
                    continue
                prev = c_closes[i - 1]
                if prev <= 0 or c_opens[i] <= 0 or c_opens[i] / prev - 1.0 >= LIMIT - 1e-6:
                    continue
                sell = c_closes[i + h]
                ctrl_rets[h].append(sell / c_opens[i] - 1.0)
                ctrl_nets[h].append(net_of(c_opens[i], sell))
        print(f"{sig_code}<->{ctrl_code} [{ind}] done", flush=True)

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 缠论买点同板块异股对照（信号组 vs 同行业不同股票）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　配对 {len(pairs)} 组，跳过 {len(skipped)}",
        "> 信号组=配对股票中“信号股”的缠论买点（锁定口径）；",
        "> 对照组=配对股票中“对照股”的全部非信号日期（排除自身缠论买点±2根）。",
        "> 同口径费用/涨跌停约束。",
        "",
        "| 持有日 | 信号样本 | 信号净收益 | 信号正概率 | 对照样本 | 对照净收益 | 对照正概率 | 超额净收益 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for h in HORIZONS:
        a = np.array(sig_nets[h]); b = np.array(ctrl_nets[h])
        ar = np.array(sig_rets[h]); br = np.array(ctrl_rets[h])
        avg_a = a.mean() if len(a) else 0.0
        avg_b = b.mean() if len(b) else 0.0
        lines.append(
            f"| {h} | {len(a)} | {avg_a * 100:+.2f}% | {(a > 0).mean() * 100:.0f}% | "
            f"{len(b)} | {avg_b * 100:+.2f}% | {(b > 0).mean() * 100:.0f}% | "
            f"{(avg_a - avg_b) * 100:+.2f}% |"
        )
        log.append(
            ExperimentRecord(
                experiment_id=f"CHAN-SECTOR-H{h}",
                hypothesis=f"同板块异股对照：缠论买点持有 {h} 日是否优于同行业随机日期",
                unique_change=f"hold={h}, sector_ctrl=True, pairs={len(pairs)}",
                expected="若信号有独立于板块的择时能力，超额应为正",
                dev_result=f"信号 {len(a)} 样本 {avg_a * 100:+.2f}% / {(a > 0).mean() * 100:.0f}%",
                val_result=f"对照 {len(b)} 样本 {avg_b * 100:+.2f}% / {(b > 0).mean() * 100:.0f}%",
                cost_result=f"超额 {(avg_a - avg_b) * 100:+.2f}%",
                passed=False,
                failure_reason="单一年窗口/单一样本池；行业分类为东财f100粗口径",
                code_version=subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev",
            )
        )
    lines += ["", "## 结论", ""]
    lines.append("- 若超额≈0或为负，说明缠论买点没有超出同行业随机日期的择时能力（板块β解释）。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}，日志追加 {len(HORIZONS)} 条")


if __name__ == "__main__":
    main()
