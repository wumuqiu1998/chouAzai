"""全球头条雷达数据层 —— 海外一手大新闻收口（新闻 + X 两个子模块）。

新闻模块（零依赖）：Techmeme —— 真人编辑运营的科技头版聚合站。
  优先扒 /river 时间流（倒序 + 分钟级时间戳，比 RSS 全），失败回退 RSS。
X 模块（选装）：几个高信号一手账号（分析师 / 企业 / 创始人），
  通过本机 x-cli 实时拉取；未安装则该模块为空，不影响新闻模块。

时间全部统一换算为北京时间（钉死 Asia/Shanghai，不随机器本地时区）。
可选中文翻译（默认关）：设 VR_TRANSLATE_BASE_URL / _API_KEY / _MODEL 即启用，
走任意 OpenAI 兼容接口；译文按 url 跨次缓存、只译增量；坏翻译自动回退英文。
命中产业关键词的条目标 relevant（机械匹配，不代表推荐、不预测涨跌）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(HERE, "headlines_sources.json")
CACHE_DIR = os.path.join(HERE, ".cache")
CACHE_FILE = os.path.join(CACHE_DIR, "headlines.json")
ZH_CACHE_FILE = os.path.join(CACHE_DIR, "headlines_zh.json")

# Windows 常缺 IANA 时区库（可 pip install tzdata 补齐）；缺失时兜底为固定偏移，保证不崩：
#   北京 = UTC+8（精确，无夏令时）；美东 = 按月近似夏令时（3-11 月 -4，其余 -5，边界几天可能差 1 小时，仅影响展示）
try:
    from zoneinfo import ZoneInfo
    BJ = ZoneInfo("Asia/Shanghai")
    US_ET = ZoneInfo("America/New_York")  # Techmeme river 时间戳是美东时间
except Exception:  # noqa: BLE001
    BJ = timezone(timedelta(hours=8))
    US_ET = None


def _us_et():
    if US_ET is not None:
        return US_ET
    m = datetime.now(timezone.utc).month
    return timezone(timedelta(hours=-4 if 3 <= m <= 11 else -5))

UA = "Mozilla/5.0 (vibe-research-headlines)"
TRANSLATE_BATCH = 10  # 小批翻译，降低编号错位


def _cfg() -> dict:
    return json.load(open(SOURCES_FILE, encoding="utf-8"))


def _to_bj(dt: datetime) -> str:
    return dt.astimezone(BJ).strftime("%Y-%m-%dT%H:%M")


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _hit(text: str, keywords: list[str]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


# ---------- 新闻模块：Techmeme ----------

def _techmeme_rss(cfg: dict, rel_kw: list[str]) -> list[dict]:
    """RSS 兜底：稳定但只有 15 条左右。标题尾部的 (来源名) 拆成 src。"""
    root = ET.fromstring(_fetch(cfg["news"]["rss_url"]).encode("utf-8"))
    out = []
    for it in root.findall(".//item"):
        raw_title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        m = re.search(r"\s*\(([^()]*)\)\s*$", raw_title)
        src = m.group(1).strip() if m else ""
        title = re.sub(r"\s*\([^()]*\)\s*$", "", raw_title).strip()
        try:
            iso = _to_bj(parsedate_to_datetime(pub))
        except Exception:  # noqa: BLE001
            iso = ""
        out.append({"title": title, "src": src, "url": link, "time": iso,
                    "rel": _hit(title, rel_kw), "zh": ""})
    return out


def _techmeme_river(cfg: dict, rel_kw: list[str]) -> list[dict]:
    """扒 river 时间流：倒序（最新在前）+ 分钟级时间戳（美东 → 北京）。"""
    html = _fetch(cfg["news"]["river_url"])
    max_items = cfg["news"].get("max_items", 30)
    out, seen = [], set()
    for row in re.findall(r'<tr class="ritem">(.*?)</tr>', html, re.I | re.S):
        tmatch = re.search(r"<td>\s*(\d{1,2}):(\d{2})\s*([AP])M", row, re.I)
        pmatch = re.search(r'pml="(\d{2})(\d{2})(\d{2})p\d+"', row)
        if not tmatch or not pmatch:
            continue
        hh, mm, ap = int(tmatch.group(1)), int(tmatch.group(2)), tmatch.group(3).upper()
        if ap == "P" and hh != 12:
            hh += 12
        if ap == "A" and hh == 12:
            hh = 0
        yy, mo, dd = pmatch.groups()
        try:
            iso = _to_bj(datetime(2000 + int(yy), int(mo), int(dd), hh, mm, tzinfo=_us_et()))
        except Exception:  # noqa: BLE001
            iso = ""
        cite = re.search(r"<cite>(.*?)</cite>", row, re.I | re.S)
        src = unescape(re.sub(r"<[^>]+>", "", cite.group(1))).strip().rstrip(":").strip() if cite else ""
        after = row[cite.end():] if cite else row
        a = re.search(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', after, re.I | re.S)
        if not a:
            continue
        url = a.group(1).strip()
        title = unescape(re.sub(r"<[^>]+>", "", a.group(2))).strip()
        if not title or not url or url in seen or len(title) < 25:  # 滤掉"仅刊名"短锚点
            continue
        seen.add(url)
        out.append({"title": title, "src": src[:40], "url": url, "time": iso,
                    "rel": _hit(title, rel_kw), "zh": ""})
        if len(out) >= max_items:
            break
    return out


def fetch_news(cfg: dict, rel_kw: list[str], redline: list[str]) -> list[dict]:
    """优先 river 时间流，失败或太少回退 RSS；合规过滤 + 最新在前。"""
    try:
        items = _techmeme_river(cfg, rel_kw)
    except Exception:  # noqa: BLE001
        items = []
    if len(items) < 16:  # river 失败或只解析出残缺结果 → RSS 成功即整体替换，失败保留残缺结果
        try:
            rss_items = _techmeme_rss(cfg, rel_kw)
            if rss_items:
                items = rss_items
        except Exception:  # noqa: BLE001
            pass
    items = [it for it in items if not _hit(it["title"], redline)]
    items.sort(key=lambda t: t.get("time") or "", reverse=True)
    return items[: cfg["news"].get("max_items", 30)]


# ---------- X 模块：高信号一手账号（选装，走本机 x-cli） ----------

def _x_cli_path(cfg: dict) -> str:
    return os.path.expanduser(os.environ.get("VR_X_CLI", "") or cfg["x"].get("cli", ""))


def x_available(cfg: dict | None = None) -> bool:
    return os.path.exists(_x_cli_path(cfg or _cfg()))


def _pull_one(cli: str, acc: dict, per: int, rel_kw: list[str]) -> list[dict]:
    """拉单个账号最近发帖，失败返回空（不拖累其它账号）。"""
    handle = re.sub(r"[^A-Za-z0-9_]", "", acc.get("handle", ""))  # 账号名只允许平台合法字符
    if not handle:
        return []
    try:
        r = subprocess.run([cli, "user-posts", handle, "-n", str(per), "--json"],
                           capture_output=True, text=True, timeout=70)
        posts = (json.loads(r.stdout) if r.stdout.strip() else {}).get("data") or []
    except Exception:  # noqa: BLE001
        return []
    out = []
    for p in posts:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        sn = (p.get("author") or {}).get("screenName") or handle
        pid = p.get("id") or ""
        try:
            bj = _to_bj(datetime.fromisoformat(p.get("createdAtISO") or ""))
        except Exception:  # noqa: BLE001
            bj = ""
        out.append({
            "name": acc["name"], "handle": "@" + sn, "role": acc.get("role", ""),
            "hub": bool(acc.get("hub")),
            "text": re.sub(r"\s+", " ", text)[:400], "zh": "",
            "time": bj,
            "url": f"https://x.com/{sn}/status/{pid}" if pid else (p.get("url") or ""),
            "rel": _hit(text, rel_kw),
        })
    return out


def fetch_x(cfg: dict, rel_kw: list[str], redline: list[str]) -> list[dict]:
    """全部账号并行实拉；只留最近 window_hours 内（北京时间），时间降序。"""
    cli = _x_cli_path(cfg)
    if not os.path.exists(cli):
        return []
    xcfg = cfg["x"]
    per = xcfg.get("per_account", 12)
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(max(len(xcfg["accounts"]), 1), 8)) as ex:
        futs = [ex.submit(_pull_one, cli, acc, per, rel_kw) for acc in xcfg["accounts"]]
        for f in as_completed(futs):
            items.extend(f.result())
    cutoff = _to_bj(datetime.now(BJ) - timedelta(hours=xcfg.get("window_hours", 72)))
    items = [it for it in items
             if it.get("time") and it["time"] >= cutoff and not _hit(it["text"], redline)]
    items.sort(key=lambda x: x.get("time") or "", reverse=True)
    return items[: xcfg.get("max_items", 80)]


# ---------- 可选翻译（任意 OpenAI 兼容接口；坏翻译回退英文） ----------

def _translate_env() -> dict | None:
    base = os.environ.get("VR_TRANSLATE_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("VR_TRANSLATE_API_KEY", "").strip()
    model = os.environ.get("VR_TRANSLATE_MODEL", "").strip()
    return {"base": base, "key": key, "model": model} if base and key and model else None


def _translate_chunk(texts: list[str], env: dict) -> dict[int, str]:
    numbered = "\n".join(f"{i + 1}. {t[:300]}" for i, t in enumerate(texts))
    prompt = (
        "把下列英文科技/半导体/AI 新闻（标题或帖子）翻成简洁准确的中文，保留公司/产品名（可中英混写）。"
        "严格按编号逐行输出译文，一条一行，不要加解释、不要合并。\n\n" + numbered
    )
    try:
        req = urllib.request.Request(
            env["base"] + "/chat/completions",
            data=json.dumps({
                "model": env["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            }).encode(),
            headers={"Authorization": f"Bearer {env['key']}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=90) as r:
            content = json.load(r)["choices"][0]["message"]["content"]
    except Exception:  # noqa: BLE001 —— 翻译是增强项，失败不影响头条本体
        return {}
    out = {}
    for line in content.splitlines():
        m = re.match(r"^\s*(\d+)[.、)]\s*(.+)$", line.strip())
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(texts):
                out[idx] = m.group(2).strip()
    return out


def _looks_bad(zh: str, en: str) -> bool:
    """长英文原文却翻出无中文/极短结果（如只回刊名）→ 判坏，回退英文。"""
    z = (zh or "").lstrip("⭐").strip()
    if len(en or "") <= 40:
        return False
    has_cjk = any("一" <= c <= "鿿" for c in z)
    return (not has_cjk) or len(z) < 6


def _load_zh_cache() -> dict:
    try:
        with open(ZH_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _atomic_write_json(path: str, obj) -> None:
    """独占临时文件 + 原子改名：并发刷新各写各的临时文件，不会互相覆盖。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save_zh_cache(cache: dict) -> None:
    _atomic_write_json(ZH_CACHE_FILE, cache)


def _translate_rows(rows: list[dict], text_key: str, env: dict | None, zh_cache: dict) -> None:
    """zh 为空的翻译回填：先按 url 走缓存，再增量小批调接口；命中关键词前缀 ⭐。"""
    for r in rows:
        cached = zh_cache.get(r.get("url"))
        if cached and not _looks_bad(cached, r.get(text_key, "")):
            r["zh"] = cached
    if env is None:
        return
    need = [i for i, r in enumerate(rows) if not r.get("zh")]
    for start in range(0, len(need), TRANSLATE_BATCH):
        batch = need[start:start + TRANSLATE_BATCH]
        zh_map = _translate_chunk([rows[i][text_key] for i in batch], env)
        for j, i in enumerate(batch):
            zh = zh_map.get(j, "")
            if _looks_bad(zh, rows[i][text_key]):
                zh = ""  # 坏翻译 → 留空，前端回退英文原文
            if zh:
                rows[i]["zh"] = ("⭐" if rows[i].get("rel") else "") + zh
                zh_cache[rows[i]["url"]] = rows[i]["zh"]


# ---------- 汇总 ----------

_REFRESH_LOCK = threading.Lock()  # single-flight：并发刷新串行化，防"旧结果覆盖新结果"


def fetch_headlines() -> dict:
    """新闻 + X 并行抓取 →（可选）翻译 → 落盘缓存。"""
    with _REFRESH_LOCK:
        return _fetch_headlines_locked()


def _fetch_headlines_locked() -> dict:
    cfg = _cfg()
    rel_kw = [k.lower() for k in cfg.get("relevant_keywords", [])]
    redline = [k.lower() for k in cfg.get("redline_keywords", [])]

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_news = ex.submit(fetch_news, cfg, rel_kw, redline)
        f_x = ex.submit(fetch_x, cfg, rel_kw, redline)
        news, xposts = f_news.result(), f_x.result()

    env = _translate_env()
    zh_cache = _load_zh_cache()
    with ThreadPoolExecutor(max_workers=2) as ex:
        for f in [ex.submit(_translate_rows, news, "title", env, zh_cache),
                  ex.submit(_translate_rows, xposts, "text", env, zh_cache)]:
            f.result()
    _save_zh_cache(zh_cache)

    data = {
        "generated_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"),
        "window_hours": cfg["x"].get("window_hours", 72),
        "news_provider": cfg["news"].get("provider", "Techmeme"),
        "x_available": x_available(cfg),
        "x_accounts": len(cfg["x"]["accounts"]),
        "news": news,
        "x": xposts,
    }
    _atomic_write_json(CACHE_FILE, data)
    return data


def load_cache():
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def skeleton() -> dict:
    """无缓存时返回空骨架，前端提示点刷新。"""
    cfg = _cfg()
    return {
        "generated_at": None,
        "window_hours": cfg["x"].get("window_hours", 72),
        "news_provider": cfg["news"].get("provider", "Techmeme"),
        "x_available": x_available(cfg),
        "x_accounts": len(cfg["x"]["accounts"]),
        "news": [],
        "x": [],
    }


def get_headlines(force: bool = False) -> dict:
    if force:
        return fetch_headlines()
    return load_cache() or skeleton()
