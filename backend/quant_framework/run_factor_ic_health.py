"""混合体检 Part 1：量价因子 + 行业轮动因子横截面 IC（2026-08-11）。

目的：在投入策略开发前，先量化“当前 A 股到底由什么驱动”。

Part A 量价因子（分层抽样 300 只，最近一年）：
- ret20（20日反转）、mom60（60日动量，跳过最近5日）、vol20（20日波动）、
  turn20（20日成交额代理）、size（ln 流通市值）；
- 未来 5/20 日收益；每 5 个交易日取一个截面，RankIC / IC_IR / 正截面占比 /
  5 分组单调性。

Part B 行业轮动（东财全部行业指数，最近一年）：
- 行业 1/3/12 周动量 → 未来 1/2/4 周行业收益；
- RankIC / 分组（Q1-Q5）/ 多空差（Q5-Q1）。

全部因子只用截至 T 的数据；未来收益仅用于评估预测力。
局限：抽样池非全市场；流通市值为当前值（近似）；单一年窗口。
"""

from __future__ import annotations

import math
import random
import requests
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
from quant_framework.experiments import ExperimentLog  # noqa: E402
from quant_framework.models import ExperimentRecord  # noqa: E402
from run_chan_buy_portfolio import fetch_sina_kline  # noqa: E402

SEED = 20260811
N_PER_LAYER = 100  # 大/中/小 各 100 只，共 300
OUT = Path(__file__).resolve().parent / "data" / "factor_ic_health.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"
CACHE_DIR = Path(__file__).resolve().parent / "data" / "factor_cache"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def fetch_market_with_size(max_pages: int = 55) -> list[dict]:
    """全市场 code/name/industry/float_cap/amount（东财 clist 分页+限流）。"""
    out: list[dict] = []
    for pn in range(1, max_pages + 1):
        try:
            r = astock.em_get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                    "fields": "f12,f14,f100,f21,f6",
                },
                headers=UA, timeout=12,
            )
            diff = (r.json().get("data") or {}).get("diff") or []
            if not diff:
                break
            for d in diff:
                code = str(d.get("f12", ""))
                name = str(d.get("f14", "") or "")
                ind = str(d.get("f100", "") or "").strip()
                cap = d.get("f21")
                amount = d.get("f6")
                if not code or code.startswith(("688", "689", "8", "4")):
                    continue
                if "ST" in name.upper() or "退" in name:
                    continue
                if not ind or ind in ("-", "") or not isinstance(cap, (int, float)) or cap <= 0:
                    continue
                out.append({"code": code, "name": name, "industry": ind, "float_cap": float(cap),
                            "amount": float(amount) if isinstance(amount, (int, float)) else 0.0})
        except Exception as e:  # noqa: BLE001
            print("market page warn", pn, e, flush=True)
        time.sleep(1.0)
    return out


def load_kline(code: str) -> pd.DataFrame | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{code}.csv"
    if cache.exists():
        try:
            df = pd.read_csv(cache, parse_dates=["datetime"])
            if len(df) >= 120:
                return df
        except Exception:  # noqa: BLE001
            pass
    df = fetch_sina_kline(code, 300)
    if df is None or len(df) < 120:
        return None
    df = df.sort_values("datetime").reset_index(drop=True)
    df.to_csv(cache, index=False, encoding="utf-8")
    return df


def rank_ic(a: np.ndarray, b: np.ndarray) -> float:
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 10:
        return float("nan")
    aa = pd.Series(a[m]).rank().values
    bb = pd.Series(b[m]).rank().values
    if np.std(aa) == 0 or np.std(bb) == 0:
        return float("nan")
    return float(np.corrcoef(aa, bb)[0, 1])


def part_a(rows: list[dict], rng: random.Random) -> dict:
    """量价因子横截面 IC。"""
    by_cap = sorted(rows, key=lambda x: x["float_cap"])
    n = len(by_cap)
    layers = [by_cap[: n // 3], by_cap[n // 3 : 2 * n // 3], by_cap[2 * n // 3 :]]
    sample = []
    for lay in layers:
        sample.extend(rng.sample(lay, min(N_PER_LAYER, len(lay))))
    print(f"PartA 抽样 {len(sample)} 只（大/中/小各 {min(N_PER_LAYER, len(layers[0]))}）", flush=True)

    frames: list[pd.DataFrame] = []
    for s in sample:
        df = load_kline(s["code"])
        if df is None:
            continue
        df["code"] = s["code"]
        df["industry"] = s["industry"]
        df["size"] = math.log(s["float_cap"])
        frames.append(df)
        if len(frames) % 50 == 0:
            print(f"PartA 已加载 {len(frames)}", flush=True)
    if not frames:
        return {}
    data = pd.concat(frames, ignore_index=True)
    data = data.sort_values(["datetime", "code"]).reset_index(drop=True)
    data["ret"] = data.groupby("code")["close"].pct_change()
    data["ret20"] = data.groupby("code")["close"].transform(lambda x: x / x.shift(20) - 1)
    data["mom60"] = data.groupby("code")["close"].transform(lambda x: x.shift(5) / x.shift(60) - 1)
    data["vol20"] = data.groupby("code")["ret"].transform(lambda x: x.rolling(20).std())
    data["amount_est"] = data["volume"] * data["close"]
    data["turn20"] = data.groupby("code")["amount_est"].transform(lambda x: x.rolling(20).mean() / 1e6)
    data["fwd5"] = data.groupby("code")["close"].transform(lambda x: x.shift(-5) / x - 1)
    data["fwd20"] = data.groupby("code")["close"].transform(lambda x: x.shift(-20) / x - 1)
    data = data.replace([np.inf, -np.inf], np.nan)

    factors = {"ret20": "20日反转", "mom60": "60日动量", "vol20": "20日波动", "turn20": "20日换手", "size": "流通市值"}
    horizons = {"fwd5": "未来5日", "fwd20": "未来20日"}
    dates = sorted(data["datetime"].unique())
    valid = [d for d in dates if 80 <= dates.index(d) < len(dates) - 20]
    cut_dates = valid[::5]
    stats: dict[str, dict] = {}
    for fname, flabel in factors.items():
        stats[fname] = {"label": flabel}
        for hname, hlabel in horizons.items():
            ics = []
            group_q1, group_q5, group_ret = [], [], []
            for d in cut_dates:
                sub = data[data["datetime"] == d][[fname, hname]].dropna()
                if len(sub) < 30:
                    continue
                ic = rank_ic(sub[fname].values, sub[hname].values)
                if not math.isnan(ic):
                    ics.append(ic)
                sub = sub.copy()
                sub["q"] = pd.qcut(sub[fname].rank(method="first"), 5, labels=False)
                if sub["q"].nunique() == 5:
                    group_q1.append(sub.loc[sub["q"] == 0, hname].mean())
                    group_q5.append(sub.loc[sub["q"] == 4, hname].mean())
                    group_ret.append(sub[hname].mean())
            arr = np.array(ics)
            stats[fname][hname] = {
                "ic": float(np.nanmean(arr)) if len(arr) else float("nan"),
                "ic_ir": float(np.nanmean(arr) / np.nanstd(arr)) if len(arr) > 1 and np.nanstd(arr) > 0 else float("nan"),
                "pos": float((arr > 0).mean()) if len(arr) else float("nan"),
                "n": len(arr),
                "q1": float(np.mean(group_q1)) if group_q1 else float("nan"),
                "q5": float(np.mean(group_q5)) if group_q5 else float("nan"),
                "spread": float(np.mean(group_q5) - np.mean(group_q1)) if group_q1 else float("nan"),
            }
    return {"sample": len(sample), "loaded": len(frames), "stats": stats}


def part_b() -> dict:
    """行业轮动因子 IC（东财行业指数）。"""
    blocks: list[dict] = []
    seen: set[str] = set()
    for host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        for pn in range(1, 6):
            try:
                r = requests.get(
                    f"https://{host}/api/qt/clist/get",
                    params={
                        "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                        "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3",
                    },
                    headers=UA, timeout=15, proxies={"http": None, "https": None},
                )
                diff = (r.json().get("data") or {}).get("diff") or []
                if not diff:
                    break
                items = diff.values() if isinstance(diff, dict) else diff
                for it in items:
                    code = str(it.get("f12", ""))
                    if code and code not in seen:
                        seen.add(code)
                        blocks.append({"code": code, "name": str(it.get("f14", "") or "")})
            except Exception as e:  # noqa: BLE001
                print("industry list warn", host, pn, e, flush=True)
            time.sleep(1.0)
        if blocks:
            break
    print(f"PartB 行业数 {len(blocks)}", flush=True)
    frames = []
    for b in blocks:
        try:
            cache = CACHE_DIR / f"bk_{b['code']}.csv"
            if cache.exists():
                kdf = pd.read_csv(cache, parse_dates=["datetime"])
            else:
                k = astock.block_kline(b["code"], days=200)
                if not k:
                    continue
                kdf = pd.DataFrame(k)
                kdf.to_csv(cache, index=False, encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        if kdf is None or len(kdf) < 120:
            continue
        df = kdf.copy()
        df = df.sort_values("datetime").reset_index(drop=True)
        df["name"] = b["name"]
        frames.append(df)
    if not frames:
        return {}
    data = pd.concat(frames, ignore_index=True)
    data = data.sort_values(["datetime", "name"]).reset_index(drop=True)
    data["ret"] = data.groupby("name")["close"].pct_change()
    data["mom1w"] = data.groupby("name")["close"].transform(lambda x: x / x.shift(5) - 1)
    data["mom1m"] = data.groupby("name")["close"].transform(lambda x: x / x.shift(20) - 1)
    data["mom3m"] = data.groupby("name")["close"].transform(lambda x: x / x.shift(60) - 1)
    data["fwd1w"] = data.groupby("name")["close"].transform(lambda x: x.shift(-5) / x - 1)
    data["fwd2w"] = data.groupby("name")["close"].transform(lambda x: x.shift(-10) / x - 1)
    data["fwd4w"] = data.groupby("name")["close"].transform(lambda x: x.shift(-20) / x - 1)
    data = data.replace([np.inf, -np.inf], np.nan)
    factors = {"mom1w": "1周动量", "mom1m": "1月动量", "mom3m": "3月动量"}
    horizons = {"fwd1w": "未来1周", "fwd2w": "未来2周", "fwd4w": "未来4周"}
    dates = sorted(data["datetime"].unique())
    cut_dates = dates[80::5]
    stats: dict[str, dict] = {}
    for fname, flabel in factors.items():
        stats[fname] = {"label": flabel}
        for hname, hlabel in horizons.items():
            ics, q1s, q5s = [], [], []
            for d in cut_dates:
                sub = data[data["datetime"] == d][[fname, hname]].dropna()
                if len(sub) < 20:
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
                "ic_ir": float(np.nanmean(arr) / np.nanstd(arr)) if len(arr) > 1 and np.nanstd(arr) > 0 else float("nan"),
                "pos": float((arr > 0).mean()) if len(arr) else float("nan"),
                "n": len(arr),
                "q1": float(np.mean(q1s)) if q1s else float("nan"),
                "q5": float(np.mean(q5s)) if q5s else float("nan"),
                "spread": float(np.mean(q5s) - np.mean(q1s)) if q1s else float("nan"),
            }
    return {"blocks": len(blocks), "loaded": len(frames), "stats": stats}


def fmt_row(item: dict) -> str:
    return (f"{item['ic'] * 100:+.2f}%　IR={item['ic_ir']:+.2f}　正截面 {item['pos'] * 100:.0f}%"
            f"　Q1 {item['q1'] * 100:+.2f}% Q5 {item['q5'] * 100:+.2f}% 多空 {item['spread'] * 100:+.2f}%")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print("拉全市场列表...", flush=True)
    market = fetch_market_with_size()
    print(f"市场有效股票 {len(market)}", flush=True)
    rng = random.Random(SEED)
    res_a = part_a(market, rng)
    res_b = part_b()

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 混合体检 Part 1：量价因子 + 行业轮动因子 IC（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　seed={SEED}",
        "> 口径：因子只用截至 T 的数据；未来收益仅评估预测力；",
        "> 每 5 个交易日取截面，RankIC=截面 Spearman 均值，IR=IC 均值/标准差。",
        "",
        "## Part A 量价因子（抽样 " + str(res_a.get("sample")) + " 只，加载 " + str(res_a.get("loaded")) + "）",
        "",
    ]
    for fname, fitem in (res_a.get("stats") or {}).items():
        lines.append(f"### {fitem['label']}（{fname}）")
        for hname, item in fitem.items():
            if isinstance(item, dict):
                lines.append(f"- {hname}：{fmt_row(item)}")
    lines += ["", "## Part B 行业轮动（行业数 " + str(res_b.get("blocks")) + "，加载 " + str(res_b.get("loaded")) + "）", ""]
    for fname, fitem in (res_b.get("stats") or {}).items():
        lines.append(f"### {fitem['label']}（{fname}）")
        for hname, item in fitem.items():
            if isinstance(item, dict):
                lines.append(f"- {hname}：{fmt_row(item)}")
    lines += ["", "## 结论", ""]
    lines.append("- |IC|>0.03 且 IR>0.5 才算初步值得研究；多空差>3% 才算有经济意义。")
    lines.append("- 局限：抽样池非全市场、市值用当前值、单一年窗口；体检结果只用于选方向，不构成策略验证。")
    OUT.write_text("\n".join(lines), encoding="utf-8")

    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for name, res in (("量价因子", res_a), ("行业轮动", res_b)):
        top = []
        for fname, fitem in (res.get("stats") or {}).items():
            for hname, item in fitem.items():
                if isinstance(item, dict):
                    top.append(f"{fitem['label']}/{hname} IC={item['ic'] * 100:+.2f}% IR={item['ic_ir']:+.2f}")
        log.append(
            ExperimentRecord(
                experiment_id=f"IC-HEALTH-{name}",
                hypothesis=f"{name}横截面IC体检：找出当前市场有预测力的因子方向",
                unique_change=f"seed={SEED}, 抽样{res.get('sample', res.get('blocks'))}",
                expected="|IC|>0.03且IR>0.5的因子值得进入下一步",
                dev_result="；".join(top[:6]) or "无数据",
                val_result="",
                cost_result="",
                passed=False,
                failure_reason="单一年窗口/抽样池/当前市值近似，仅作方向选择",
                code_version=code_version,
            )
        )
    print(f"\n报告已生成：{OUT}，日志追加 2 条")


if __name__ == "__main__":
    main()
