"""扫描最近两个交易日出现缠论买点（B1/B2/B3）的股票。

方法：东财全市场按成交额排序取前 200 只（排除 ST/退市/科创板/北交所），
逐只拉日K算缠论，筛选点日期落在最近两个交易日的买点。
仅按规则输出信号，不构成投资建议。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astock  # noqa: E402
from quant_framework.chan import analyze_chan_locked  # noqa: E402

OUT = Path(__file__).resolve().parent / "data" / "buy_signal_candidates.md"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36", "Referer": "https://quote.eastmoney.com/"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def top_by_amount(n: int = 200) -> list[dict]:
    out: list[dict] = []
    for pn in range(1, 10):
        if len(out) >= n:
            break
        try:
            r = requests.get(
                "https://push2delay.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fid": "f6", "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                    "fields": "f12,f14,f6,f3,f2",
                },
                headers=UA, timeout=20, proxies={"http": None, "https": None},
            )
            diff = (r.json().get("data") or {}).get("diff") or []
            if not diff:
                break
            for x in diff:
                code = str(x.get("f12", ""))
                name = str(x.get("f14", ""))
                if code.startswith(("688", "689", "8", "4")):
                    continue
                if "ST" in name.upper() or "退" in name:
                    continue
                out.append(
                    {
                        "code": code,
                        "name": name,
                        "amount": float(x.get("f6") or 0),
                        "pct": x.get("f3"),
                        "price": x.get("f2"),
                    }
                )
                if len(out) >= n:
                    break
        except Exception as e:  # noqa: BLE001
            print("warn", e)
        time.sleep(0.8)
    return out[:n]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = top_by_amount(200)
    candidates: list[dict] = []
    for s in universe:
        code = s["code"]
        try:
            rows = astock.kline(code, category=4, offset=260)
        except Exception:  # noqa: BLE001
            continue
        if not rows or len(rows) < 120:
            continue
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        last_two = sorted({str(d.date()) for d in df["datetime"]})[-2:]
        im = {str(pd.Timestamp(ts))[:16].replace(" 00:00", ""): i for i, ts in enumerate(df["datetime"])}
        for p in analyze_chan_locked(df)["points"]:
            d = str(p["date"])[:10]
            if d in last_two and p["kind"] in ("buy1", "buy2", "buy3"):
                candidates.append(
                    {
                        "code": code,
                        "name": s["name"],
                        "kind": p["kind"].upper(),
                        "date": d,
                        "price": p["price"],
                        "cur": s["price"],
                        "pct": s["pct"],
                    }
                )
                break
        print(f"{code} {s['name']} done", flush=True)

    lines = [
        "# 最近两个交易日缠论买点候选（规则扫描）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　扫描：全市场成交额前 200 只",
        "> 仅按缠论规则输出，不构成投资建议。",
        "",
        "| 代码 | 名称 | 信号 | 点日期 | 信号价 | 现价 | 今日涨幅% |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in candidates:
        lines.append(f"| {c['code']} | {c['name']} | {c['kind']} | {c['date']} | {c['price']} | {c['cur']} | {c['pct']} |")
    lines.append("")
    codes = ",".join(c["code"] for c in candidates)
    lines.append(f"**可直接粘贴到自选输入框的代码串**：`{codes}`")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n候选数：{len(candidates)}")
    print(f"代码串：{codes}")
    print(f"报告：{OUT}")


if __name__ == "__main__":
    main()
