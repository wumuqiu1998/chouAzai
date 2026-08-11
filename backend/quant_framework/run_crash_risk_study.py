"""突发利空风控研究：个股暴跌事件 + 指数级外围冲击（2026-08-11）。

案例：行云科技(300209) 2026-08-11 盘中传 GPU 被海关扣押，收 -9.04% 放量长阴。

Part A 个股突发利空（暴跌代理，缓存 3606 只，最近一年）：
- 事件：单日收益 <= -7% 且前一日 > -9%（首次冲击，排除连续跌停第二天）；
- 行业中性收益：D+1 单日 / D+1~3 / D+1~5 / D+1~10 / D+1~20；
- 分组：暴跌幅度 / 市值 / 板块共振（行业指数同日跌幅）；
- 对照：同股票随机日期（伪事件）；
- 风控规则：R1 已持有者 D+1 开盘卖出 vs 持有；R2 暴跌后 1/5 日内不买入；
- 案例展示：300209 事件日形态。

Part B 指数级外围冲击（上证指数单日 <= -1.5% 代理外围/系统性利空）：
- 其后 1/3/5/10/20 日收益 vs 随机日期对照。
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

from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_chan_buy_portfolio import fetch_sina_kline  # noqa: E402
from run_factor_ic_health import CACHE_DIR, fetch_market_with_size  # noqa: E402

SEED = 20260811
OUT = Path(__file__).resolve().parent / "data" / "crash_risk_study.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def stats_of(x: pd.Series) -> dict:
    n = len(x)
    return {
        "n": n,
        "mean": x.mean() if n else float("nan"),
        "t": (x.mean() / (x.std(ddof=1) / np.sqrt(n))) if n > 1 and x.std(ddof=1) > 0 else float("nan"),
        "pos": (x > 0).mean() if n else float("nan"),
        "med": x.median() if n else float("nan"),
    }


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print("拉行业与市值映射...", flush=True)
    market = fetch_market_with_size()
    code_ind = {m["code"]: m["industry"] for m in market}
    cap = {m["code"]: m["float_cap"] for m in market}
    blocks: dict[str, str] = {}
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        for pn in range(1, 6):
            try:
                import requests

                r = requests.get(
                    f"https://{host}/api/qt/clist/get",
                    params={
                        "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                        "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3",
                    },
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                    timeout=15, proxies={"http": None, "https": None},
                )
                diff = (r.json().get("data") or {}).get("diff") or []
                if not diff:
                    break
                items = diff.values() if isinstance(diff, dict) else diff
                for it in items:
                    blocks[str(it.get("f12", ""))] = str(it.get("f14", "") or "")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.0)
        if blocks:
            break
    bench_close: dict[str, pd.Series] = {}
    for f in CACHE_DIR.glob("bk_*.csv"):
        name = blocks.get(f.stem[3:])
        if not name:
            continue
        try:
            df = pd.read_csv(f, parse_dates=["datetime"])
        except Exception:  # noqa: BLE001
            continue
        bench_close[name] = pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["datetime"]).dt.date)

    frames = []
    for f in CACHE_DIR.glob("*.csv"):
        if f.name.startswith("bk_"):
            continue
        code = f.stem
        try:
            df = pd.read_csv(f, parse_dates=["datetime"])
        except Exception:  # noqa: BLE001
            continue
        if len(df) < 60:
            continue
        df["code"] = code
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["datetime"]).dt.date
    data = data.sort_values(["code", "date"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        data[col] = data[col].astype(float)
    data["industry"] = data["code"].map(code_ind)
    data["ret"] = data.groupby("code")["close"].pct_change()
    for h in (1, 3, 5, 10, 20):
        data[f"fwd{h}"] = data.groupby("code")["close"].transform(lambda x, o=h: x.shift(-o) / x - 1)
        data[f"ind_fwd{h}"] = np.nan
    for ind_name, s in bench_close.items():
        idx = data["industry"] == ind_name
        if not idx.any():
            continue
        closes = pd.Series(s.reindex(data.loc[idx, "date"].values).values)
        for h in (1, 3, 5, 10, 20):
            data.loc[idx, f"ind_fwd{h}"] = (closes.shift(-h) / closes - 1).values
    for h in (1, 3, 5, 10, 20):
        data[f"ex{h}"] = data[f"fwd{h}"] - data[f"ind_fwd{h}"]
    data = data.replace([np.inf, -np.inf], np.nan)

    # 暴跌事件：单日 <= -7% 且前一日 > -9%
    data["crash"] = (data["ret"] <= -0.07) & (data.groupby("code")["ret"].shift(1) > -0.09)
    ev = data[data["crash"]].copy()
    rng = random.Random(SEED)
    code_dates = data.groupby("code")["date"].apply(lambda s: np.array(sorted(set(s)))).to_dict()
    pseudo_pairs: list[tuple[str, object]] = []
    for code, g in ev.groupby("code"):
        dates = code_dates.get(code, np.array([]))
        bad = set(g["date"].values)
        cands = [d for d in dates if d not in bad]
        for d in rng.sample(cands, min(3, len(cands))):
            pseudo_pairs.append((code, d))
    pseudo = data.merge(pd.DataFrame(pseudo_pairs, columns=["code", "date"]), on=["code", "date"], how="inner")

    def summarize(sub: pd.DataFrame, label: str) -> list[str]:
        cells = [label]
        for h in (1, 3, 5, 10, 20):
            x = sub[f"ex{h}"].dropna()
            st = stats_of(x)
            cells.append(f"n={st['n']} {st['mean'] * 100:+.2f}% t={st['t']:+.2f} 正{st['pos'] * 100:.0f}%")
        return cells

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 突发利空风控研究：个股暴跌 + 指数级外围冲击（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　股票池 {len(frames)} 只",
        "> 事件：单日收益<=-7% 且前一日>-9%（首次冲击）；行业中性超额=个股-行业指数。",
        "",
        "## Part A 个股暴跌事件（接飞刀风险）",
        "",
        "| 分组 | D+1 | D+1~3 | D+1~5 | D+1~10 | D+1~20 |",
        "|---|---|---|---|---|---|",
    ]
    groups = {
        "全部暴跌": ev,
        "深跌(-7~-9%)": ev[ev["ret"] > -0.09],
        "接近跌停(<=-9%)": ev[ev["ret"] <= -0.09],
        "伪事件对照": pseudo,
    }
    cap_med = np.nanmedian([cap.get(c, np.nan) for c in ev["code"].unique()])
    big = ev[ev["code"].map(lambda c: cap.get(c, np.nan) > cap_med)]
    small = ev[ev["code"].map(lambda c: cap.get(c, np.nan) <= cap_med)]
    groups["大盘股(市值>中位)"] = big
    groups["小盘股(市值<=中位)"] = small
    for label, sub in groups.items():
        lines.append("| " + " | ".join(summarize(sub, label)) + " |")
    lines += ["", "## Part B 指数级外围冲击（上证指数单日<=-1.5%）", "", "| 分组 | 后1日 | 后3日 | 后5日 | 后10日 | 后20日 |", "|---|---|---|---|---|---|"]
    idx = fetch_sina_kline("000001", 300, prefix="sh000001")
    if idx is not None:
        idx["datetime"] = pd.to_datetime(idx["datetime"])
        idx = idx.sort_values("datetime").reset_index(drop=True)
        idx["ret"] = idx["close"].astype(float).pct_change()
        for h in (1, 3, 5, 10, 20):
            idx[f"fwd{h}"] = idx["close"].astype(float).shift(-h) / idx["close"].astype(float) - 1
        idx_ev = idx[idx["ret"] <= -0.015].copy()
        rng2 = random.Random(SEED + 1)
        idx_pseudo = idx.sample(n=min(len(idx_ev) * 3, len(idx) - 20), random_state=SEED + 1).copy()
        for label, sub in (("指数暴跌(<=-1.5%)", idx_ev), ("随机日期对照", idx_pseudo)):
            cells = [label]
            for h in (1, 3, 5, 10, 20):
                x = sub[f"fwd{h}"].dropna()
                st = stats_of(x)
                cells.append(f"n={st['n']} {st['mean'] * 100:+.2f}% t={st['t']:+.2f} 正{st['pos'] * 100:.0f}%")
            lines.append("| " + " | ".join(cells) + " |")
        lines += ["", f"上证指数样本：{len(idx)} 根，指数暴跌事件 {len(idx_ev)} 个", ""]
    lines += ["", "## 300209 案例（2026-08-11，行云科技 GPU 扣押传闻）", ""]
    lines.append("开盘 38.15 / 最高 38.68 / 最低 34.88 / 收盘 34.92，当日 **-9.04%**，")
    lines.append("放量大阴线收在最低附近（振幅约 10%），属于 Part A 定义的首次暴跌冲击。")
    lines.append("风控含义：按 R1，持有者次日开盘应评估减仓；按 R2，至少 1~5 日内不接飞刀，")
    lines.append("待企稳信号（止跌+缩量+收复部分失地）后再评估。")
    lines += ["", "## 结论", ""]
    lines.append("- 若暴跌后 D+1~5 行业中性收益显著为负，接飞刀危险成立，R1/R2 风控有数据支撑；")
    lines.append("- 若 D+6~20 明显反弹，说明利空冲击后存在均值回归，但需等企稳信号而非次日抄底。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for label, sub in groups.items():
        x = sub["ex5"].dropna()
        st = stats_of(x)
        log.append(
            ExperimentRecord(
                experiment_id=f"CRASH-{label}",
                hypothesis=f"突发利空暴跌后行业中性收益（{label}）",
                unique_change=f"group={label}, n={st['n']}",
                expected="D+1~5 显著为负则接飞刀危险",
                dev_result=f"D+1~5 {st['mean'] * 100:+.2f}% t={st['t']:+.2f}",
                val_result="",
                cost_result=f"正比例 {st['pos'] * 100:.0f}%",
                passed=False,
                failure_reason="暴跌代理利空消息/单一年窗口/缓存池有选择偏差",
                code_version=code_version,
            )
        )
    print(f"\n报告已生成：{OUT}，日志追加 {len(groups)} 条")


if __name__ == "__main__":
    main()
