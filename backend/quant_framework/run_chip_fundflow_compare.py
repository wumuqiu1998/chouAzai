"""双口径对比：同花顺式筹码分布（方法一） vs 东财分单主力资金流（方法二）。

口径说明
--------
方法一（筹码分布，近似同花顺）：
    历史筹码按每日换手率衰减（当日筹码 = 昨日筹码 x (1-换手率)），
    当日成交量按价格分布填入 [low, high]，峰在 close。
    输出：平均成本（≈同花顺“主力成本”）、90% 成本区间、筹码峰、获利盘比例。

方法二（主力资金流，东财 push2his 分单）：
    超大单 + 大单 = 主力单，输出近 5/20/60 日主力净流入及占成交额比例。

对比：当前价 vs 平均成本；20 日主力资金方向 vs 20 日平均成本移动方向。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import astock  # noqa: E402

CODES = ["000636", "300223", "600487", "000063", "516080"]
OUT_DIR = Path(__file__).resolve().parent / "data"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def market_code(code: str) -> int:
    """东财 secid 市场位：5/6/9=上海，8=北交所，其余=深圳。"""
    if code.startswith(("5", "6", "9")):
        return 1
    if code.startswith("8"):
        return 0  # 北交所在东财用 0
    return 0


def _cache_path(kind: str, code: str) -> Path:
    return OUT_DIR / "cache" / f"{kind}_{code}.json"


def _load_cache(kind: str, code: str, max_age_hours: float = 4.0) -> list | None:
    p = _cache_path(kind, code)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > max_age_hours * 3600:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _save_cache(kind: str, code: str, data: list) -> None:
    p = _cache_path(kind, code)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _em_direct_get(url: str, params: dict | None = None, headers: dict | None = None,
                   timeout: int = 20, attempts: int = 3):
    """东财直连（完全禁用系统代理），带重试。em_get 的 8 秒直连探针在这种间歇网络下不够稳。"""
    import requests
    attempts = int(os.environ.get("EM_ATTEMPTS", str(attempts)))
    s = requests.Session()
    s.headers.update({"User-Agent": astock.UA})
    s.trust_env = False
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = s.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.2 * (i + 1))
    if last is not None:
        raise last
    raise RuntimeError("unreachable")


def eastmoney_daily_kline(code: str, lmt: int = 250) -> list[dict]:
    """东财前复权日 K（含换手率 f61），失败返回 []。"""
    cached = _load_cache("kline", code)
    if cached:
        return cached
    params = {
        "secid": f"{market_code(code)}.{code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(lmt),
    }
    headers = {"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"}
    klines: list[str] = []
    try:
        r = _em_direct_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params=params, headers=headers, timeout=15,
        )
        d = r.json()
        klines = (d.get("data") or {}).get("klines") or []
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 东财日K失败: {e}")
        if os.environ.get("EM_NO_FALLBACK"):
            return []
        try:
            r = astock.em_get(
                "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                params=params, headers=headers, timeout=15,
            )
            d = r.json()
            klines = (d.get("data") or {}).get("klines") or []
        except Exception as e2:  # noqa: BLE001
            print(f"  [warn] 东财日K(em_get)失败: {e2}")
            return []

    rows: list[dict] = []
    for line in klines:
        p = line.split(",")
        if len(p) < 7:
            continue
        try:
            rows.append({
                "datetime": p[0],
                "open": float(p[1]),
                "close": float(p[2]),
                "high": float(p[3]),
                "low": float(p[4]),
                "volume": float(p[5]),        # 手
                "amount": float(p[6]),        # 元
                "turnover": float(p[10]) / 100.0 if len(p) > 10 and p[10] not in ("-", "") else 0.0,
            })
        except (TypeError, ValueError):
            continue
    if rows:
        _save_cache("kline", code, rows)
    return rows


def tencent_daily_fallback(code: str, lmt: int = 250) -> list[dict]:
    """腾讯日 K + 新浪换手率（或流通股本估算）兜底。"""
    rows = astock.kline(code, category=4, offset=lmt)
    if not rows:
        return []
    turn_map = {}
    for r in sina_fund_flow(code, num=lmt):
        turn_map[r["date"]] = r["turnover_frac"]
    float_shares = 0.0
    try:
        q = astock.tencent_quote([code]).get(code, {})
        price = float(q.get("price") or 0)
        float_mcap = float(q.get("float_mcap_yi") or 0)
        if price > 0:
            float_shares = float_mcap * 1e8 / price
    except Exception:  # noqa: BLE001
        pass
    out = []
    for r in rows:
        vol = float(r.get("vol") or r.get("volume") or 0)
        date = str(r.get("datetime"))[:10]
        if date in turn_map:
            turnover = turn_map[date]
        else:
            turnover = min(vol * 100.0 / float_shares, 1.0) if float_shares > 0 else 0.0
        out.append({
            "datetime": date,
            "open": float(r.get("open") or 0),
            "close": float(r.get("close") or 0),
            "high": float(r.get("high") or 0),
            "low": float(r.get("low") or 0),
            "volume": vol,
            "amount": float(r.get("amount") or 0),
            "turnover": turnover,
            "source": "tencent_est",
        })
    return out


def fund_flow_120d(code: str) -> list[dict]:
    """东财个股资金流 120 日（修正 ETF 市场位），失败时降级新浪（仅超大单）。

    返回列表元素含 source 字段：
    - eastmoney：主力 = 超大单 + 大单
    - sina_super_only：主力近似 = 超大单（新浪历史未返回大单）
    """
    cached = _load_cache("flow", code)
    if cached:
        return cached
    params = {
        "secid": f"{market_code(code)}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    klines: list[str] = []
    try:
        r = _em_direct_get(
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
            params=params, headers=headers, timeout=15,
        )
        d = r.json()
        klines = (d.get("data") or {}).get("klines") or []
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 东财资金流失败: {e}")
        if os.environ.get("EM_NO_FALLBACK"):
            klines = []
        else:
            try:
                r = astock.em_get(
                    "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
                    params=params, headers=headers, timeout=15,
                )
                d = r.json()
                klines = (d.get("data") or {}).get("klines") or []
            except Exception as e2:  # noqa: BLE001
                print(f"  [warn] 东财资金流(em_get)失败: {e2}")
                klines = []

    def _f(x: str) -> float:
        try:
            return float(x) if x not in ("-", "") else 0.0
        except ValueError:
            return 0.0

    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) >= 6:
            rows.append({
                "date": p[0],
                "main_net": _f(p[1]),
                "small_net": _f(p[2]),
                "mid_net": _f(p[3]),
                "large_net": _f(p[4]),
                "super_net": _f(p[5]),
                "source": "eastmoney",
            })
    if rows:
        _save_cache("flow", code, rows)
        return rows

    sina = sina_fund_flow(code, num=120)
    return [{
        "date": r["date"],
        "main_net": r["r0_net"],
        "small_net": 0.0,
        "mid_net": 0.0,
        "large_net": 0.0,
        "super_net": r["r0_net"],
        "source": "sina_super_only",
    } for r in sina]


def sina_fund_flow(code: str, num: int = 120) -> list[dict]:
    """新浪个股资金流历史（超大单 r0 + 净额 + 换手率）。"""
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs"
    params = {"page": 1, "num": str(num), "sort": "opendate", "asc": 0, "daima": f"{prefix}{code}"}
    headers = {"User-Agent": astock.UA, "Referer": "https://finance.sina.com.cn/"}
    try:
        import requests
        r = requests.get(url, params=params, headers=headers, timeout=15)
        data = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 新浪资金流失败: {e}")
        return []
    out = []
    for d in data or []:
        try:
            out.append({
                "date": str(d.get("opendate", ""))[:10],
                "r0_net": float(d.get("r0_net") or 0),
                "netamount": float(d.get("netamount") or 0),
                "turnover_frac": float(d.get("turnover") or 0) / 10000.0,  # 新浪口径：换手率×100
            })
        except (TypeError, ValueError):
            continue
    return out


def eastmoney_today_flow(code: str) -> dict | None:
    """东财 push2delay 当日资金流（可达时返回精确主力=超大+大单）。"""
    params = {
        "secid": f"{market_code(code)}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "1",
    }
    headers = {"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = _em_direct_get(
            "https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get",
            params=params, headers=headers, timeout=15, attempts=2,
        )
        klines = (r.json().get("data") or {}).get("klines") or []
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 东财当日资金流失败: {e}")
        return None
    if not klines:
        return None
    p = klines[-1].split(",")

    def _f(x: str) -> float:
        try:
            return float(x) if x not in ("-", "") else 0.0
        except ValueError:
            return 0.0

    return {
        "date": p[0],
        "main_net": _f(p[1]),
        "super_net": _f(p[5]),
        "large_net": _f(p[4]),
    }


def calc_chip_distribution(bars: pd.DataFrame, range_days: int = 120, factor: int = 150) -> dict:
    """东财/同花顺式筹码衰减分布（移植东财 CYQCalculator）。

    - 窗口 120 个交易日（东财页面注释口径）；
    - 150 档价格，精度 = max(0.01, (max-min)/(factor-1))；
    - 每日按换手率衰减：xdata *= (1 - turnover)；
    - 当日成交量按三角分布填入 [low, high]，峰在 (o+c+h+l)/4；
    - 平均成本 = 累计筹码 50% 位价格；90% 区间 = 5%~95% 筹码位。
    """
    df = bars.sort_values("datetime").reset_index(drop=True)

    def cyq_at(idx: int) -> dict:
        start = max(0, idx - range_days + 1)
        kdata = df.iloc[start:idx + 1]
        maxprice = float(kdata["high"].max())
        minprice = float(kdata["low"].min())
        if maxprice <= minprice:
            maxprice = minprice + 1.0
        accuracy = max(0.01, (maxprice - minprice) / (factor - 1))
        xdata = np.zeros(factor, dtype=float)

        for _, e in kdata.iterrows():
            open_, close, high, low = float(e["open"]), float(e["close"]), float(e["high"]), float(e["low"])
            avg = (open_ + close + high + low) / 4.0
            turnover = float(e.get("turnover") or 0.0)
            turnover = max(0.0, min(turnover, 1.0))
            xdata *= 1.0 - turnover

            if high == low:
                gp1 = int(np.floor((avg - minprice) / accuracy))
                gp1 = max(0, min(factor - 1, gp1))
                xdata[gp1] += (factor - 1) * turnover / 2.0
                continue

            H = int(np.floor((high - minprice) / accuracy))
            L = int(np.ceil((low - minprice) / accuracy))
            gp0 = 2.0 / (high - low)
            for j in range(max(0, L), min(factor - 1, H) + 1):
                cur = minprice + accuracy * j
                if cur <= avg:
                    if abs(avg - low) < 1e-8:
                        xdata[j] += gp0 * turnover
                    else:
                        xdata[j] += (cur - low) / (avg - low) * gp0 * turnover
                else:
                    if abs(high - avg) < 1e-8:
                        xdata[j] += gp0 * turnover
                    else:
                        xdata[j] += (high - cur) / (high - avg) * gp0 * turnover

        total = float(xdata.sum())
        if total <= 0:
            return {"avg_cost": None}

        def cost(chip: float) -> float:
            s = 0.0
            for i, x in enumerate(xdata):
                if s + x > chip:
                    return minprice + i * accuracy
                s += x
            return minprice + (factor - 1) * accuracy

        prices = minprice + np.arange(factor, dtype=float) * accuracy
        current = float(kdata["close"].iloc[-1])
        return {
            "avg_cost": cost(total * 0.5),
            "p5": cost(total * 0.05),
            "p50": cost(total * 0.5),
            "p95": cost(total * 0.95),
            "p70_low": cost(total * 0.15),
            "p70_high": cost(total * 0.85),
            "peak": float(prices[int(np.argmax(xdata))]),
            "profit_ratio": float(xdata[prices <= current].sum() / total),
            "conc_90": (cost(total * 0.95) - cost(total * 0.05)) / (cost(total * 0.95) + cost(total * 0.05))
            if (cost(total * 0.95) + cost(total * 0.05)) > 0 else 0.0,
        }

    series = [cyq_at(i) for i in range(len(df))]
    valid = [r for r in series if r.get("avg_cost") is not None]
    if not valid:
        return {}
    latest = valid[-1]
    s = pd.DataFrame(valid).reset_index(drop=True)
    cost_20d_ago = float(s["avg_cost"].iloc[-21]) if len(s) > 21 else float(s["avg_cost"].iloc[0])
    conc_20d_ago = float(s["conc_90"].iloc[-21]) if len(s) > 21 else None
    return {
        "avg_cost": latest["avg_cost"],
        "p5": latest["p5"],
        "p50": latest["p50"],
        "p95": latest["p95"],
        "p70_low": latest["p70_low"],
        "p70_high": latest["p70_high"],
        "peak": latest["peak"],
        "profit_ratio": latest["profit_ratio"],
        "cost_20d_ago": cost_20d_ago,
        "cost_drift_20_pct": (latest["avg_cost"] / cost_20d_ago - 1.0) * 100 if cost_20d_ago else None,
        "conc_90": latest["conc_90"],
        "conc_90_20d_ago": conc_20d_ago,
        "n_days": len(valid),
    }


def fund_flow_stats(flow: list[dict], bars: pd.DataFrame) -> dict:
    """近 5/20/60 日主力净流入、占成交额比例、净流入天数。"""
    if not flow:
        return {}
    ff = pd.DataFrame(flow)
    ff["date"] = pd.to_datetime(ff["date"])
    kd = bars.copy()
    kd["date"] = pd.to_datetime(kd["datetime"].astype(str).str[:10])
    # 腾讯日 K 常缺成交额字段，缺时用 成交量 x 均价 估算
    kd["amount_est"] = np.where(
        kd["amount"].fillna(0) > 0,
        kd["amount"],
        kd["volume"] * 100.0 * (kd["open"] + kd["close"] + kd["high"] + kd["low"]) / 4.0,
    )
    merged = ff.merge(kd[["date", "amount_est"]], on="date", how="left").sort_values("date")

    def _win(n: int) -> dict:
        w = merged.tail(n)
        if w.empty:
            return {"main_net": 0.0, "amount": 0.0, "pos_days": 0, "days": 0}
        return {
            "main_net": float(w["main_net"].sum()),
            "super_net": float(w["super_net"].sum()),
            "large_net": float(w["large_net"].sum()),
            "amount": float(w["amount_est"].sum()),
            "pos_days": int((w["main_net"] > 0).sum()),
            "days": int(len(w)),
        }

    out = {}
    for n in (5, 20, 60):
        s = _win(n)
        out[f"main_net_{n}"] = s["main_net"]
        out[f"main_ratio_{n}"] = (s["main_net"] / s["amount"] * 100.0) if s["amount"] else None
        out[f"pos_days_{n}"] = s["pos_days"]
        out[f"days_{n}"] = s["days"]
        out[f"super_net_{n}"] = s["super_net"]
        out[f"large_net_{n}"] = s["large_net"]
    return out


def quote_info(code: str) -> dict:
    try:
        q = astock.tencent_quote([code]).get(code, {})
        return {
            "name": q.get("name", ""),
            "price": float(q.get("price") or 0),
            "float_mcap_yi": float(q.get("float_mcap_yi") or 0),
            "turnover_pct": float(q.get("turnover_pct") or 0),
        }
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 实时行情失败: {e}")
        return {"name": "", "price": 0.0, "float_mcap_yi": 0.0, "turnover_pct": 0.0}


def fmt_yi(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{x / 1e8:+.2f}亿" if abs(x) >= 1e8 else f"{x / 1e4:+.0f}万"


def analyze(code: str) -> dict:
    q = quote_info(code)
    bars_raw = eastmoney_daily_kline(code, lmt=250)
    kline_source = "eastmoney"
    if not bars_raw:
        bars_raw = tencent_daily_fallback(code, lmt=250)
        kline_source = "tencent_est"
    if not bars_raw:
        return {"code": code, "name": q.get("name", ""), "error": "K线数据为空"}

    bars = pd.DataFrame(bars_raw)
    bars["datetime"] = pd.to_datetime(bars["datetime"])
    bars = bars.sort_values("datetime").reset_index(drop=True)

    flow = fund_flow_120d(code)
    chip = calc_chip_distribution(bars)
    ff = fund_flow_stats(flow, bars)
    fund_source = flow[0].get("source") if flow else None
    today_flow = eastmoney_today_flow(code)

    price = q.get("price") or float(bars["close"].iloc[-1])
    avg_cost = chip.get("avg_cost")
    cost_drift = chip.get("cost_drift_20_pct")
    flow_20 = ff.get("main_net_20", 0.0)
    flow_20_ratio = ff.get("main_ratio_20")

    # 方向一致性：20 日主力净流入方向 vs 20 日平均成本移动方向
    if cost_drift is not None and abs(cost_drift) < 1e-9:
        cost_dir = 0
    elif cost_drift is not None:
        cost_dir = 1 if cost_drift > 0 else -1
    else:
        cost_dir = 0
    flow_dir = 1 if flow_20 > 1e4 else (-1 if flow_20 < -1e4 else 0)
    if flow_dir == 0 or cost_dir == 0:
        agree = "中性"
    elif flow_dir == cost_dir:
        agree = "一致"
    else:
        agree = "背离"

    if flow_dir > 0 and cost_dir > 0:
        verdict = "资金流入且成本上移：承接/推升结构，筹码成本抬升"
    elif flow_dir > 0 and cost_dir < 0:
        verdict = "资金流入但成本下移：低位承接/换手，筹码成本下降"
    elif flow_dir < 0 and cost_dir > 0:
        verdict = "资金流出但成本上移：高位派发嫌疑，需警惕"
    elif flow_dir < 0 and cost_dir < 0:
        verdict = "资金流出且成本下移：杀跌/出逃结构"
    else:
        verdict = "方向信号不明显，需结合量价确认"

    return {
        "code": code,
        "name": q.get("name", ""),
        "price": round(price, 3),
        "float_mcap_yi": q.get("float_mcap_yi"),
        "kline_source": kline_source,
        "chip": chip,
        "fund": ff,
        "cost_gap_pct": (price / avg_cost - 1.0) * 100 if avg_cost else None,
        "flow_20": flow_20,
        "flow_20_ratio": flow_20_ratio,
        "fund_source": fund_source,
        "today_flow": today_flow,
        "cost_drift_20_pct": cost_drift,
        "direction_agree": agree,
        "verdict": verdict,
        "latest_date": str(bars["datetime"].iloc[-1].date()),
    }


def build_report(results: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 筹码分布 vs 主力资金流 对比报告",
        "",
        f"> 生成时间：{now}　样本：{', '.join(CODES)}",
        "",
        "## 口径",
        "",
        "- **方法一（筹码分布）**：东财/同花顺式换手衰减模型（移植东财 CYQCalculator）。120 日窗口、150 档价格，每日按换手率衰减，当日成交量按三角分布填入 [low, high]，峰在 (开+收+高+低)/4。平均成本 = 50% 筹码位（≈同花顺“主力成本”），另输出 90% 成本区间、筹码峰、获利盘比例。K 线来源：东财前复权日 K（含换手率）；东财受阻时降级腾讯日 K + 新浪历史换手率。",
        "- **方法二（主力资金流）**：东财 push2his 分单口径，主力单 = 超大单 + 大单，输出近 5/20/60 日主力净流入及占成交额比例；东财历史受阻时降级为新浪 120 日超大单口径，并另附最近交易日东财精确主力净流入（push2delay）作对照。",
        "- **对比指标**：现价 vs 平均成本（浮盈/浮亏）、20 日主力资金方向 vs 20 日平均成本移动方向（一致/背离）。",
        "",
        "## 汇总表",
        "",
        "| 代码 | 名称 | 现价 | 平均成本 | 90%成本区间 | 筹码峰 | 获利盘 | 20日主力净流入* | 8/7主力(东财) | 20日成本变动 | 方向 | 判断 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.get("error"):
            lines.append(f"| {r['code']} | {r['name']} | - | 数据失败: {r['error']} |")
            continue
        c = r["chip"]
        lines.append(
            "| {code} | {name} | {price} | {avg:.2f} | {p5:.2f}~{p95:.2f} | {peak:.2f} | "
            "{profit:.1%} | {flow} | {today} | {drift} | {agree} | {verdict} |".format(
                code=r["code"], name=r["name"], price=r["price"],
                avg=c["avg_cost"], p5=c["p5"], p95=c["p95"], peak=c["peak"],
                profit=c["profit_ratio"],
                flow=fmt_yi(r["flow_20"]),
                today=fmt_yi((r.get("today_flow") or {}).get("main_net")),
                drift=f"{r['cost_drift_20_pct']:+.2f}%" if r["cost_drift_20_pct"] is not None else "-",
                agree=r["direction_agree"], verdict=r["verdict"],
            )
        )

    lines += ["", "> * 20日主力净流入：东财 120 日数据可用时为主力（超大+大单）；东财受阻时降级为新浪超大单口径（不含大单），逐股明细会标注数据来源。", ""]
    lines += ["", "## 逐股明细", ""]
    for r in results:
        if r.get("error"):
            lines.append(f"### {r['code']} {r['name']}（数据失败：{r['error']}）\n")
            continue
        c = r["chip"]
        f = r["fund"]
        lines.append(f"### {r['code']} {r['name']}")
        lines.append("")
        lines.append(f"- 数据日期：{r['latest_date']}（K线来源：{r['kline_source']}）")
        src_note = {
            "eastmoney": "东财 120 日分单（主力=超大单+大单）",
            "sina_super_only": "新浪历史（仅超大单，缺大单，主力口径偏窄）",
        }.get(r.get("fund_source"), "无资金流数据")
        lines.append(f"- 资金流来源：{src_note}")
        lines.append(f"- 现价：{r['price']}　流通市值：{r['float_mcap_yi']:.0f}亿" if r["float_mcap_yi"] else f"- 现价：{r['price']}")
        lines.append("")
        lines.append("**方法一 · 筹码分布**")
        lines.append("")
        lines.append(
            f"- 平均成本（主力成本近似）：{c['avg_cost']:.2f}　（20日前 {c['cost_20d_ago']:.2f}，"
            f"变动 {r['cost_drift_20_pct']:+.2f}%）"
        )
        lines.append(f"- 90% 成本区间：{c['p5']:.2f} ~ {c['p95']:.2f}（中位 {c['p50']:.2f}）")
        lines.append(f"- 筹码峰：{c['peak']:.2f}　获利盘：{c['profit_ratio']:.1%}")
        lines.append(f"- 90% 区间宽度/均价：{c['conc_90']:.2%}"
                     + (f"（20日前 {c['conc_90_20d_ago']:.2%}）" if c["conc_90_20d_ago"] is not None else ""))
        lines.append(f"- 现价相对平均成本：{r['cost_gap_pct']:+.2f}%")
        lines.append("")
        lines.append("**方法二 · 主力资金流**")
        lines.append("")
        lines.append(f"- 近5日主力净流入：{fmt_yi(f.get('main_net_5'))}　（占成交额 {f.get('main_ratio_5'):+.2f}%）" if f.get("main_ratio_5") is not None else "-")
        lines.append(f"- 近20日主力净流入：{fmt_yi(f.get('main_net_20'))}　（占成交额 {f.get('main_ratio_20'):+.2f}%，"
                     f"净流入天数 {f.get('pos_days_20')}/{f.get('days_20')}）" if f.get("main_ratio_20") is not None else "-")
        lines.append(f"- 近60日主力净流入：{fmt_yi(f.get('main_net_60'))}　（占成交额 {f.get('main_ratio_60'):+.2f}%）" if f.get("main_ratio_60") is not None else "-")
        lines.append(f"- 近20日超大单：{fmt_yi(f.get('super_net_20'))}　大单：{fmt_yi(f.get('large_net_20'))}")
        if r.get("today_flow"):
            tf = r["today_flow"]
            lines.append(
                f"- 最近交易日 {tf['date']} 东财精确主力净流入：{fmt_yi(tf['main_net'])}"
                f"（超大单 {fmt_yi(tf['super_net'])}，大单 {fmt_yi(tf['large_net'])}）"
            )
        lines.append("")
        lines.append(f"**对比结论**：方向一致性 = **{r['direction_agree']}**；{r['verdict']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for code in CODES:
        print(f"== {code} ==")
        try:
            r = analyze(code)
        except Exception as e:  # noqa: BLE001
            r = {"code": code, "name": "", "error": str(e)}
            print(f"  [err] {e}")
        results.append(r)
        if not r.get("error"):
            print(f"  现价={r['price']} 平均成本={r['chip']['avg_cost']:.2f} "
                  f"20日主力={fmt_yi(r['flow_20'])} 方向={r['direction_agree']}")

    md = build_report(results)
    out_path = OUT_DIR / "chip_fundflow_compare.md"
    out_path.write_text(md, encoding="utf-8")
    json_path = OUT_DIR / "chip_fundflow_compare.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n报告已生成：{out_path}")


if __name__ == "__main__":
    main()
