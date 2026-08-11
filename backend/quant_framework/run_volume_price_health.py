"""量价关系代理“主力行为”因子体检（2026-08-11）。

不依赖东财资金流估算接口（批量不可用），直接用价格+成交量构造主力行为代理：
- close_loc5：5日均收盘位置 (close-low)/(high-low)，高=收在高位（控盘/强势）；
- vol_ratio5：5日均量/20日均量（放量程度）；
- up_down_vol5：5日上涨日均量/下跌日均量（涨放量跌缩量=吸筹特征）；
- obv_chg20：OBV 20日变化量/20日均量（量能趋势）；
- 组合：主力做多 = close_loc5>0.6 且 vol_ratio5>1 且 up_down_vol5>1.2；
- 组合：横盘吸筹 = up_down_vol5>1.5 且 5日收益在 ±3% 内。

全部因子只用截至 T 的数据，未来收益 T+1 起；超额=个股-行业指数。
股票池：factor_cache 全部个股K线（~2900只，新浪300根）。
"""

from __future__ import annotations

import math
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
from run_factor_ic_health import CACHE_DIR, fetch_market_with_size  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "volume_price_health.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def rank_ic(a: np.ndarray, b: np.ndarray) -> float:
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 10:
        return float("nan")
    aa = pd.Series(a[m]).rank().values
    bb = pd.Series(b[m]).rank().values
    if np.std(aa) == 0 or np.std(bb) == 0:
        return float("nan")
    return float(np.corrcoef(aa, bb)[0, 1])


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print("拉行业映射...", flush=True)
    market = fetch_market_with_size()
    code_ind = {m["code"]: m["industry"] for m in market}
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
    print(f"行业列表 {len(blocks)}", flush=True)

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
    print(f"行业基准 {len(bench_close)} 个", flush=True)

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
    print(f"缓存股票 {len(frames)}", flush=True)
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["datetime"]).dt.date
    data = data.sort_values(["code", "date"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        data[col] = data[col].astype(float)
    data["industry"] = data["code"].map(code_ind)

    data["ret"] = data.groupby("code")["close"].pct_change()
    span = (data["high"] - data["low"]).replace(0, np.nan)
    data["close_loc"] = ((data["close"] - data["low"]) / span).fillna(0.5)
    data["close_loc5"] = data.groupby("code")["close_loc"].transform(lambda x: x.rolling(5).mean())
    data["vol_ratio5"] = data.groupby("code")["volume"].transform(lambda x: x.rolling(5).mean() / x.rolling(20).mean())
    data["up_vol"] = data["volume"].where(data["ret"] > 0)
    data["down_vol"] = data["volume"].where(data["ret"] < 0)
    data["up_vol5"] = data.groupby("code")["up_vol"].transform(lambda x: x.rolling(5, min_periods=1).mean())
    data["down_vol5"] = data.groupby("code")["down_vol"].transform(lambda x: x.rolling(5, min_periods=1).mean())
    data["up_down_vol5"] = data["up_vol5"] / data["down_vol5"].replace(0, np.nan)
    data["obv_delta"] = np.sign(data["ret"].fillna(0)) * data["volume"]
    data["obv"] = data.groupby("code")["obv_delta"].cumsum()
    data["obv_chg20"] = data.groupby("code")["obv"].transform(lambda x: x - x.shift(20)) / data.groupby("code")["volume"].transform(lambda x: x.rolling(20).mean())
    data["ret5"] = data.groupby("code")["close"].transform(lambda x: x / x.shift(5) - 1)
    for h in (5, 10, 20):
        data[f"fwd{h}"] = data.groupby("code")["close"].transform(lambda x, o=h: x.shift(-o) / x - 1)
        data[f"ind_fwd{h}"] = np.nan
    for ind_name, s in bench_close.items():
        idx = data["industry"] == ind_name
        if not idx.any():
            continue
        sub_dates = data.loc[idx, "date"].values
        closes = s.reindex(sub_dates).values
        cs = pd.Series(closes)
        for h in (5, 10, 20):
            data.loc[idx, f"ind_fwd{h}"] = (cs.shift(-h) / cs - 1).values
    for h in (5, 10, 20):
        data[f"excess{h}"] = data[f"fwd{h}"] - data[f"ind_fwd{h}"]
    data = data.replace([np.inf, -np.inf], np.nan)
    print(f"面板 {len(data)} 行", flush=True)

    factors = {"close_loc5": "5日收盘位置", "vol_ratio5": "5日量比", "up_down_vol5": "涨跌量比5", "obv_chg20": "OBV斜率20"}
    horizons = {"fwd5": "未来5日", "fwd10": "未来10日", "fwd20": "未来20日"}
    dates = sorted(data["date"].unique())
    cut_dates = dates[40::5]
    stats: dict[str, dict] = {}
    for fname, flabel in factors.items():
        stats[fname] = {"label": flabel}
        for hname, hlabel in horizons.items():
            ics, q1s, q5s = [], [], []
            for d in cut_dates:
                sub = data[data["date"] == d][[fname, hname]].dropna()
                if len(sub) < 50:
                    continue
                ic = rank_ic(sub[fname].values, sub[hname].values)
                if not math.isnan(ic):
                    ics.append(ic)
                sub = sub.copy()
                sub["q"] = pd.qcut(sub[fname].rank(method="first"), 5, labels=False)
                if sub["q"].nunique() == 5:
                    q1s.append(sub.loc[sub["q"] == 0, hname].mean())
                    q5s.append(sub.loc[sub["q"] == 4, hname].mean())
            arr = np.array(ics)
            stats[fname][hname] = {
                "ic": float(np.nanmean(arr)) if len(arr) else float("nan"),
                "ir": float(np.nanmean(arr) / np.nanstd(arr)) if len(arr) > 1 and np.nanstd(arr) > 0 else float("nan"),
                "pos": float((arr > 0).mean()) if len(arr) else float("nan"),
                "q1": float(np.mean(q1s)) if q1s else float("nan"),
                "q5": float(np.mean(q5s)) if q5s else float("nan"),
                "spread": float(np.mean(q5s) - np.mean(q1s)) if q1s else float("nan"),
            }

    combos = {
        "主力做多(收高+放量+涨放量跌缩量)": (data["close_loc5"] > 0.6) & (data["vol_ratio5"] > 1.0) & (data["up_down_vol5"] > 1.2),
        "横盘吸筹(涨放量跌缩量+窄幅)": (data["up_down_vol5"] > 1.5) & (data["ret5"].abs() < 0.03),
        "对照(其余)": np.ones(len(data), dtype=bool),
    }
    combo_stats: dict[str, dict] = {}
    for label, mask in combos.items():
        sub = data[mask]
        combo_stats[label] = {}
        for h in (5, 10, 20):
            x = sub[f"excess{h}"].dropna()
            n = len(x)
            combo_stats[label][h] = {
                "n": n,
                "car": x.mean() if n else float("nan"),
                "t": (x.mean() / (x.std(ddof=1) / np.sqrt(n))) if n > 1 and x.std(ddof=1) > 0 else float("nan"),
                "pos": (x > 0).mean() if n else float("nan"),
            }

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 量价关系代理主力行为：因子体检 + 组合对照（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　股票池 {len(frames)} 只",
        "> 因子只用截至 T 的数据；未来收益 T+1 起；超额=个股-行业指数。",
        "",
        "## 一、RankIC 体检",
        "",
        "| 因子 | 未来5日 | 未来10日 | 未来20日 |",
        "|---|---|---|---|",
    ]
    for fname, fitem in stats.items():
        cells = []
        for hname in horizons:
            it = fitem[hname]
            cells.append(f"IC {it['ic'] * 100:+.2f}% / IR {it['ir']:+.2f} / 多空 {it['spread'] * 100:+.2f}%")
        lines.append(f"| {fitem['label']} | {' | '.join(cells)} |")
    lines += ["", "## 二、组合（行业中性超额）", "", "| 组合 | 未来5日 | 未来10日 | 未来20日 |", "|---|---|---|---|"]
    for label, t in combo_stats.items():
        cells = []
        for h in (5, 10, 20):
            it = t[h]
            cells.append(f"n={it['n']} {it['car'] * 100:+.2f}% t={it['t']:+.2f} 正{it['pos'] * 100:.0f}%")
        lines.append(f"| {label} | {' | '.join(cells)} |")
    lines += ["", "## 结论", ""]
    lines.append("- 组合相对对照的正增量才是“主力做多”的真实信息；|t|<2 只能算方向提示。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for fname, fitem in stats.items():
        for hname in horizons:
            it = fitem[hname]
            log.append(
                ExperimentRecord(
                    experiment_id=f"VP-{fname}-{hname}",
                    hypothesis=f"量价因子 {fitem['label']} 对{hname}收益的预测力",
                    unique_change=f"factor={fname}, horizon={hname}",
                    expected="|IC|>0.03",
                    dev_result=f"IC={it['ic'] * 100:+.2f}% IR={it['ir']:+.2f} 多空 {it['spread'] * 100:+.2f}%",
                    val_result="",
                    cost_result="",
                    passed=False,
                    failure_reason="缓存股票池有选择偏差/单一年窗口",
                    code_version=code_version,
                )
            )
    print(f"\n报告已生成：{OUT}，日志追加 {len(stats) * len(horizons)} 条")
    print("\n组合对照：")
    for label, t in combo_stats.items():
        print(label, {h: (t[h]["n"], f"{t[h]['car'] * 100:+.2f}%", f"{t[h]['t']:+.2f}") for h in (5, 10, 20)}, flush=True)


if __name__ == "__main__":
    main()
