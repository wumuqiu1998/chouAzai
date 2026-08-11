"""暴跌性质判别研究：洗盘 / 出货 / 利空 能否用量价特征区分（2026-08-11）。

对“单日暴跌<=-7%”事件按三个维度分组，比较未来行业中性收益：
1. 量能：D日量/20日均量（缩量<0.8 / 放量>1.5）；
2. 位置：事件前60日涨幅（低位<-10% / 中位 / 高位>30%）；
3. 结构：D日收盘是否跌破 MA20 且 MA60（破位 vs 未破位）；
4. 板块共振：行业指数同日跌幅（<-2% 板块利空 vs 个股利空）。

组合判别：
- 疑似洗盘 = 缩量 + 未破位；
- 疑似出货 = 放量 + 高位 + 破位；
- 疑似利空 = 放量 + 破位 + 板块共振。

若各组未来收益差异显著，说明特征有判别力；若无差异，说明只能一刀切风控。
"""

from __future__ import annotations

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

OUT = Path(__file__).resolve().parent / "data" / "crash_classify.md"
LOG_PATH = Path(__file__).resolve().parent / "data" / "experiments.csv"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def st(x: pd.Series) -> dict:
    n = len(x)
    return {
        "n": n,
        "mean": x.mean() if n else float("nan"),
        "t": (x.mean() / (x.std(ddof=1) / np.sqrt(n))) if n > 1 and x.std(ddof=1) > 0 else float("nan"),
        "pos": (x > 0).mean() if n else float("nan"),
    }


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
        if len(df) < 80:
            continue
        df["code"] = code
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)
    data["date"] = pd.to_datetime(data["datetime"]).dt.date
    data = data.sort_values(["code", "date"]).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        data[col] = data[col].astype(float)
    data["industry"] = data["code"].map(code_ind)
    data["ret"] = data.groupby("code")["close"].pct_change()
    data["vol20"] = data.groupby("code")["volume"].transform(lambda x: x.rolling(20).mean())
    data["vol_ratio"] = data["volume"] / data["vol20"]
    data["pos60"] = data.groupby("code")["close"].transform(lambda x: x / x.shift(60) - 1)
    data["ma20"] = data.groupby("code")["close"].transform(lambda x: x.rolling(20).mean())
    data["ma60"] = data.groupby("code")["close"].transform(lambda x: x.rolling(60).mean())
    data["broken"] = (data["close"] < data["ma20"]) & (data["close"] < data["ma60"])
    for h in (5, 10, 20):
        data[f"fwd{h}"] = data.groupby("code")["close"].transform(lambda x, o=h: x.shift(-o) / x - 1)
        data[f"ind_fwd{h}"] = np.nan
    for ind_name, s in bench_close.items():
        idx = data["industry"] == ind_name
        if not idx.any():
            continue
        closes = pd.Series(s.reindex(data.loc[idx, "date"].values).values)
        for h in (5, 10, 20):
            data.loc[idx, f"ind_fwd{h}"] = (closes.shift(-h) / closes - 1).values
    # 行业指数当日收益（板块共振）
    ind_ret: dict[str, float] = {}
    for ind_name, s in bench_close.items():
        r = s.pct_change()
        ind_ret[ind_name] = r
    data["ind_ret_today"] = np.nan
    for ind_name, r in ind_ret.items():
        idx = data["industry"] == ind_name
        if idx.any():
            data.loc[idx, "ind_ret_today"] = r.reindex(data.loc[idx, "date"].values).values
    for h in (5, 10, 20):
        data[f"ex{h}"] = data[f"fwd{h}"] - data[f"ind_fwd{h}"]
    data = data.replace([np.inf, -np.inf], np.nan)

    data["crash"] = (data["ret"] <= -0.07) & (data.groupby("code")["ret"].shift(1) > -0.09)
    ev = data[data["crash"]].dropna(subset=["vol_ratio", "pos60", "broken"]).copy()
    print(f"暴跌事件 {len(ev)}", flush=True)

    groups = {
        "全部暴跌": np.ones(len(ev), dtype=bool),
        "缩量(<0.8)": ev["vol_ratio"] < 0.8,
        "放量(>1.5)": ev["vol_ratio"] > 1.5,
        "低位(前60日<-10%)": ev["pos60"] < -0.10,
        "高位(前60日>30%)": ev["pos60"] > 0.30,
        "未破位(MA20/60)": ~ev["broken"],
        "破位(MA20/60)": ev["broken"],
        "板块共振(行业同日<-2%)": ev["ind_ret_today"] < -0.02,
        "个股利空(行业同日>-2%)": ev["ind_ret_today"] >= -0.02,
        "疑似洗盘(缩量+未破位)": (ev["vol_ratio"] < 1.0) & (~ev["broken"]),
        "疑似出货(放量+高位+破位)": (ev["vol_ratio"] > 1.5) & (ev["pos60"] > 0.20) & ev["broken"],
        "疑似利空(放量+破位+板块共振)": (ev["vol_ratio"] > 1.5) & ev["broken"] & (ev["ind_ret_today"] < -0.02),
    }

    log = ExperimentLog(LOG_PATH)
    lines = [
        "# 暴跌性质判别：洗盘 / 出货 / 利空（2026-08-11）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　暴跌事件 {len(ev)}",
        "> 行业中性超额=个股-行业指数；D+1 起持有。",
        "",
        "| 分组 | n | D+1~5 | D+1~10 | D+1~20 |",
        "|---|---|---|---|---|",
    ]
    for label, mask in groups.items():
        sub = ev[mask]
        cells = [label]
        for h in (5, 10, 20):
            s = st(sub[f"ex{h}"].dropna())
            cells.append(f"n={s['n']} {s['mean'] * 100:+.2f}% t={s['t']:+.2f} 正{s['pos'] * 100:.0f}%")
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## 结论", ""]
    lines.append("- 若“疑似洗盘”与“疑似出货/利空”的未来收益差异显著，量价特征有判别力，可做分级风控；")
    lines.append("- 若无差异，说明暴跌性质无法从公开量价区分，只能统一按风险处理（不接飞刀）。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    code_version = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "dev"
    for label in ("疑似洗盘(缩量+未破位)", "疑似出货(放量+高位+破位)", "疑似利空(放量+破位+板块共振)"):
        sub = ev[groups[label]]
        x = sub["ex20"].dropna()
        s = st(x)
        log.append(
            ExperimentRecord(
                experiment_id=f"CLASSIFY-{label[:6]}",
                hypothesis=f"暴跌性质判别：{label}",
                unique_change=f"group={label}, n={s['n']}",
                expected="洗盘组>出货/利空组 且差异显著",
                dev_result=f"D+1~20 {s['mean'] * 100:+.2f}% t={s['t']:+.2f}",
                val_result="",
                cost_result=f"正比例 {s['pos'] * 100:.0f}%",
                passed=False,
                failure_reason="量价特征为代理判别/单一年窗口/无消息面确认",
                code_version=code_version,
            )
        )
    print(f"\n报告已生成：{OUT}，日志追加 3 条")
    for label in ("疑似洗盘(缩量+未破位)", "疑似出货(放量+高位+破位)", "疑似利空(放量+破位+板块共振)"):
        sub = ev[groups[label]]
        x = sub["ex20"].dropna()
        s = st(x)
        print(label, f"n={s['n']}", f"{s['mean']*100:+.2f}%", f"t={s['t']:+.2f}", flush=True)


if __name__ == "__main__":
    main()
