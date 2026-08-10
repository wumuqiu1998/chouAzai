"""盲测样本画像：50 只随机股票的行业/市值构成。

用于辩驳分析“数据集是什么板块、结论是否被样本构成解释”。
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_blind_combination import fetch_universe_rich  # noqa: E402

SEED = 20260810
N = 50
OUT = Path(__file__).resolve().parent / "data" / "blind_sample_profile.md"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    universe = fetch_universe_rich()
    rng = random.Random(SEED)
    sample = rng.sample(universe, min(N, len(universe)))

    ind = Counter(s["industry"] or "未知" for s in sample)
    mcap_buckets = defaultdict(int)
    for s in sample:
        m = s.get("mcap") or 0
        if m < 1e9:
            mcap_buckets["<10亿"] += 1
        elif m < 5e9:
            mcap_buckets["10-50亿"] += 1
        elif m < 1e10:
            mcap_buckets["50-100亿"] += 1
        elif m < 5e10:
            mcap_buckets["100-500亿"] += 1
        else:
            mcap_buckets[">500亿"] += 1

    lines = [
        "# 盲测样本画像（50 只随机）",
        "",
        f"> seed={SEED}　总数：{len(sample)}",
        "",
        "## 行业分布",
        "",
        "| 行业 | 数量 | 占比 |",
        "|---|---|---|",
    ]
    for ind_name, n in ind.most_common():
        lines.append(f"| {ind_name} | {n} | {n / len(sample) * 100:.0f}% |")
    lines += ["", "## 市值分布", "", "| 分桶 | 数量 | 占比 |", "|---|---|---|"]
    for bucket, n in sorted(mcap_buckets.items()):
        lines.append(f"| {bucket} | {n} | {n / len(sample) * 100:.0f}% |")
    lines += ["", "## 个股清单", "", "| 代码 | 名称 | 行业 | 总市值(亿) |", "|---|---|---|---|"]
    for s in sample:
        lines.append(f"| {s['code']} | {s['name']} | {s['industry']} | {s.get('mcap', 0) / 1e8:.0f} |")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已生成：{OUT}")


if __name__ == "__main__":
    main()
