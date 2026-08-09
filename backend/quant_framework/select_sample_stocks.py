"""按方向随机抽取 20 支样本股（AI应用/科技/医疗/电力/电网，排除科创板/北交所/ST）。

数据源：东财 push2delay 板块成分（公开接口）。
随机种子固定（20260809），结果可复现；最终清单写入 data/sample_stocks_20.json。
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import requests

OUT_DIR = Path(__file__).resolve().parent / "data"
SEED = 20260809
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def em_get(url: str, params: dict, tries: int = 3) -> list[dict]:
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=20, proxies={"http": None, "https": None})
            d = r.json()
            diff = (d.get("data") or {}).get("diff") or []
            if diff:
                return diff
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 请求失败({i+1}/{tries}): {e}")
        time.sleep(1.5)
    return []


def all_boards(fs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pn in range(1, 7):
        rows = em_get(
            "https://push2delay.eastmoney.com/api/qt/clist/get",
            {"pn": pn, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2, "fs": fs, "fields": "f12,f14"},
        )
        if not rows:
            break
        for r in rows:
            out[str(r.get("f14", ""))] = str(r.get("f12", ""))
        time.sleep(1.0)
    return out


def constituents(bk: str) -> list[dict]:
    rows = em_get(
        "https://push2delay.eastmoney.com/api/qt/clist/get",
        {
            "pn": 1, "pz": 200, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fid": "f6", "fs": f"b:{bk}", "fields": "f12,f14,f3,f20,f21,f6",
        },
    )
    out = []
    for r in rows:
        code = str(r.get("f12", ""))
        name = str(r.get("f14", ""))
        if code.startswith(("688", "689", "8", "4")):
            continue  # 科创板/北交所
        if "ST" in name.upper() or "退" in name:
            continue
        try:
            amount = float(r.get("f6") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            continue
        out.append({"code": code, "name": name, "amount": amount})
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ind = all_boards("m:90+t:2")
    time.sleep(1.0)
    con = all_boards("m:90+t:3")
    (OUT_DIR / "boards_debug.json").write_text(
        json.dumps({"industry": ind, "concept": con}, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    targets = {
        "AI应用": ("concept", con.get("人工智能") or con.get("AIGC概念")),
        "科技": ("industry", ind.get("半导体")),
        "医疗": ("industry", ind.get("医疗器械")),
        "电力": ("industry", ind.get("电力")),
        "电网": ("industry", ind.get("电网设备")),
    }
    rng = random.Random(SEED)
    picked: list[dict] = []
    for label, (kind, bk) in targets.items():
        if not bk:
            print(f"[warn] {label} 板块代码缺失")
            continue
        rows = constituents(bk)
        rows.sort(key=lambda x: x["amount"], reverse=True)
        top = rows[:30]
        if not top:
            print(f"[warn] {label}({bk}) 无成分")
            continue
        sel = rng.sample(top, min(4, len(top)))
        print(f"{label} ({bk}): 可用 {len(rows)} 支，随机选中: {[(s['code'], s['name']) for s in sel]}")
        for s in sel:
            picked.append({"direction": label, "code": s["code"], "name": s["name"]})
        time.sleep(1.0)

    out = {
        "seed": SEED,
        "count": len(picked),
        "stocks": picked,
    }
    path = OUT_DIR / "sample_stocks_20.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n样本清单已保存：{path}")
    print("codes =", [s["code"] for s in picked])


if __name__ == "__main__":
    main()
