"""Vibe-Astock 短线复盘 API —— 并入 Vibe-Research 后端。

路由前缀 /api/review/*、/api/weekly/*、/api/verification/*、/api/market/session 等。
数据落盘 ~/.duanxian-agents/，与独立部署的 vibe-astock 共用缓存。
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.responses import JSONResponse

from duanxian import live_emotion, overseas, preflight, reflection, review_store, trade_calendar
from duanxian.util import (
    china_now,
    china_today,
    is_a_share_closed,
    is_weekend,
    safe_join,
    strip_model_noise,
    validate_trade_date,
)

router = APIRouter()

_REVIEW_DIR = os.path.expanduser("~/.duanxian-agents/reviews")
_WK_DIR = os.path.expanduser("~/.duanxian-agents/weekly")
os.makedirs(_REVIEW_DIR, exist_ok=True)
os.makedirs(_WK_DIR, exist_ok=True)

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"} | {
    h.strip() for h in os.environ.get("VIBE_ALLOW_HOSTS", "").split(",") if h.strip()
}

_lock = threading.Lock()
_job = {
    "running": False, "job_id": None, "date": None, "error": None,
    "started": None, "elapsed": 0, "finished_at": None,
}
_JOB_TIMEOUT = 15 * 60


def initial_state(trade_date: str) -> dict:
    return {
        "trade_date": trade_date,
        "sentiment_report": "",
        "capital_report": "",
        "theme_report": "",
        "dragon_tiger_report": "",
        "leader_report": "",
        "macro_sector_report": "",
        "emotion_metrics": {},
        "market_facts": {},
        "tomorrow_focus": "",
        "focus_struct": None,
        "past_context": reflection.get_past_context(),
    }


def _origin_ok(request: Request) -> bool:
    ref = request.headers.get("origin") or request.headers.get("referer") or ""
    if not ref:
        return True
    return (urlparse(ref).hostname or "") in _ALLOWED_HOSTS


def _force_flag(request: Request) -> bool:
    return str(request.query_params.get("force", "")).strip().lower() in ("1", "true", "yes")


def _job_stuck(job: dict, limit: int) -> bool:
    return bool(job.get("running") and job.get("started") and time.time() - job["started"] > limit)


def _atomic_write(path: str, payload: dict) -> None:
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _capture_theme_reasons() -> None:
    try:
        from duanxian import theme_tree

        r = theme_tree.capture()
        if not r.get("ok"):
            print(f"⚠️ 题材串囤积失败（{r.get('date')}）：{r.get('reason')}")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 题材串囤积异常：{type(exc).__name__}: {exc}")


def _run_review(date: str, job_id: str) -> None:
    try:
        pre = preflight.check(date)
        if not pre["ok"]:
            raise RuntimeError(preflight.refuse_reason(pre, date))

        from duanxian.review_graph import build_review_graph

        graph = build_review_graph()
        final = graph.invoke(initial_state(date), {"recursion_limit": 50})
        reflection.auto_evaluate_prior(date)
        payload = review_store.serialize(final, date, pre["warnings"])
        res = review_store.save(payload, date)
        if not res.written:
            raise RuntimeError(res.reason)
        _capture_theme_reasons()
    except Exception as exc:  # noqa: BLE001
        with _lock:
            if _job["job_id"] == job_id:
                _job["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        with _lock:
            if _job["job_id"] == job_id:
                _job["running"] = False
                if _job["started"]:
                    _job["elapsed"] = int(time.time() - _job["started"])
                _job["finished_at"] = china_now().strftime("%Y-%m-%d %H:%M:%S") + " CST"


@router.post("/api/review/run")
def api_run(request: Request, date: str | None = None):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        if not date:
            date = trade_calendar.latest_session() or china_today()
        date = validate_trade_date(date)
        if is_weekend(date):
            return JSONResponse({"error": f"{date} 为周末非交易日"}, status_code=400)
        if not trade_calendar.is_settled(date):
            latest = trade_calendar.latest_session()
            return JSONResponse(
                {"error": f"{date} 还没收盘，复盘要用当天的收盘数据",
                 "suggest_date": latest,
                 "hint": f"最近已收盘的是 {latest}" if latest else None},
                status_code=409,
            )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if not _force_flag(request) and review_store.usable(review_store.load(date)):
        return {"running": False, "date": date, "already_done": True,
                "message": f"{date} 已复盘"}

    with _lock:
        if _job["running"] and not _job_stuck(_job, _JOB_TIMEOUT):
            return {"running": True, "date": _job["date"]}
        if _job["running"]:
            _job["error"] = f"上一个任务（{_job.get('date')}）超过 {_JOB_TIMEOUT // 60} 分钟无响应，已判为卡死"
        job_id = uuid.uuid4().hex
        _job.update(running=True, job_id=job_id, date=date, error=None,
                    started=time.time(), elapsed=0, finished_at=None)
    threading.Thread(target=_run_review, args=(date, job_id), daemon=True).start()
    return {"running": True, "date": date, "job_id": job_id}


@router.get("/api/review/status")
def api_status():
    with _lock:
        snap = dict(_job)
    if snap["running"] and snap["started"]:
        snap["elapsed"] = int(time.time() - snap["started"])
    snap.pop("started", None)
    return snap


@router.post("/api/review/evaluate")
def api_evaluate(request: Request, date: str):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    try:
        date = validate_trade_date(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    res = reflection.evaluate(date)
    return res or {"error": "无可评估数据（缺该日预测，或次一交易日数据尚未出）"}


@router.get("/api/market/session")
def api_market_session():
    today = china_today()
    quotes_of = trade_calendar.quote_trade_day()
    is_today = bool(quotes_of) and quotes_of == today
    closed = is_a_share_closed()

    now = china_now()
    hhmm = now.hour * 60 + now.minute
    if not quotes_of:
        phase, label = "未知", "行情时间取不到"
    elif is_today and not closed and hhmm < 9 * 60 + 25:
        phase, label = "集合竞价", "集合竞价 · 尚未成交"
    elif is_today and not closed:
        phase, label = "盘中", "盘中 · 实时"
    elif is_today:
        phase, label = "已收盘", f"{today} 收盘"
    elif is_weekend(today):
        phase, label = "非交易日", f"非交易日 · 显示 {quotes_of} 收盘"
    elif not closed:
        phase, label = "盘前", f"盘前 · 显示 {quotes_of} 收盘"
    else:
        phase, label = "非交易日", f"今日无成交 · 显示 {quotes_of} 收盘"

    return {"now": now.strftime("%Y-%m-%d %H:%M"), "today": today,
            "quotes_of": quotes_of, "is_today": is_today,
            "phase": phase, "label": label}


@router.get("/api/market/live-emotion")
def api_market_live_emotion():
    return live_emotion.snapshot()


@router.get("/api/market/overseas")
def api_market_overseas():
    return overseas.overseas_snapshot()


@router.get("/api/review/dates")
def api_review_dates():
    return {"dates": review_store.dates()}


@router.get("/api/review/latest")
def api_latest(date: Optional[str] = None):
    if date:
        try:
            date = validate_trade_date(date)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    payload = review_store.load(date)
    if payload is None or not review_store.usable(payload):
        return JSONResponse({"requested_date": date} if date else {}, status_code=200)
    try:
        if date is None:
            payload["reflection"] = reflection.latest_reflection()
        payload["scoreboard"] = reflection.scoreboard()
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 战绩统计失败：{type(exc).__name__}: {exc}")
    return JSONResponse(payload)


# ---- 近 5 天热度 ----
_wk_lock = threading.Lock()


def _wk_load():
    path = os.path.join(_WK_DIR, "latest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return None


def _wk_fresh(cached: dict) -> bool:
    from duanxian.weekly import LINEAGE_SCHEMA

    days = cached.get("days") or []
    if not days:
        return False
    if cached.get("lineage_schema") != LINEAGE_SCHEMA:
        return False
    try:
        from duanxian.weekly import _last_trade_dates

        latest = _last_trade_dates(1)
        expected = latest[-1] if latest else None
    except Exception:  # noqa: BLE001
        expected = None
    return expected is None or days[-1].get("date") == expected


def _wk_good(w: dict) -> bool:
    return not w.get("error") and any((d.get("limit_up") is not None) for d in (w.get("days") or []))


def _weekly(force: bool):
    from duanxian.weekly import build_weekly

    cached = _wk_load()
    if not force and cached and _wk_fresh(cached):
        return JSONResponse(cached)

    if not _wk_lock.acquire(blocking=False):
        if cached:
            return JSONResponse({**cached, "busy": True})
        return JSONResponse({"error": "正在计算中，请稍后重试", "busy": True}, status_code=409)
    try:
        cached2 = _wk_load()
        if not force and cached2 and _wk_fresh(cached2):
            return JSONResponse(cached2)
        w = build_weekly(5)
        w["generated_at"] = china_now().strftime("%Y-%m-%d %H:%M")
        days = w.get("days") or []
        w["last_trade_date"] = days[-1].get("date") if days else None
        if _wk_good(w):
            try:
                _atomic_write(safe_join(_WK_DIR, "latest.json"), w)
            except Exception:  # noqa: BLE001
                pass
            return JSONResponse(w)
        if cached2 and (cached2.get("days")):
            stale = dict(cached2)
            stale["stale"] = True
            stale["warnings"] = (stale.get("warnings") or []) + ["刷新失败，展示上一份有效数据"]
            return JSONResponse(stale)
        return JSONResponse(w)
    finally:
        _wk_lock.release()


@router.get("/api/weekly")
def api_weekly(request: Request, refresh: int = 0):  # noqa: ARG001
    return _weekly(force=False)


@router.post("/api/weekly/refresh")
def api_weekly_refresh(request: Request):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    return _weekly(force=True)


# ---- 复盘对话 ----
_chat_llm = None
_ROLE_MAP = {"user": "human", "assistant": "ai"}
_CHAT_MAX_MESSAGES = 40
_CHAT_MAX_CHARS_EACH = 4000
_CHAT_MAX_CHARS_TOTAL = 24000


def _sanitize_messages(msgs: object) -> tuple[list, Optional[str]]:
    if not isinstance(msgs, list) or not msgs:
        return [], "空消息"
    if len(msgs) > _CHAT_MAX_MESSAGES:
        msgs = msgs[-_CHAT_MAX_MESSAGES:]
    out, total = [], 0
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        if role not in _ROLE_MAP:
            return [], f"不支持的 role：{role!r}（只接受 user / assistant）"
        content = str(m.get("content", ""))[:_CHAT_MAX_CHARS_EACH]
        total += len(content)
        if total > _CHAT_MAX_CHARS_TOTAL:
            return [], "对话内容过长，请开新会话"
        out.append({"role": role, "content": content})
    return (out, None) if out else ([], "空消息")


def _chat_model():
    global _chat_llm
    if _chat_llm is None:
        from duanxian.config import make_llm

        _chat_llm = make_llm(deep=False)
    return _chat_llm


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _load_latest_json(dirpath: str) -> dict:
    path = os.path.join(dirpath, "latest.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError, FileNotFoundError):
        return {}


def _review_context() -> str:
    d = _load_latest_json(_REVIEW_DIR)
    if not d:
        return "（暂无复盘数据，请先在复盘看板生成一次复盘。）"
    parts = [f"复盘交易日 {d.get('target_date', '')}", f"【明天关注点】\n{d.get('focus_md', '')}"]
    if d.get("macro_sector"):
        parts.append(f"【大板块本周】\n{d['macro_sector']}")
    for a in d.get("analysts", []):
        parts.append(f"【{a.get('title', '')}】\n{_strip_html(a.get('html', ''))}")
    return "\n\n".join(parts)[:8000]


def _chat(context: str, role_desc: str, messages: list) -> dict:
    from duanxian.prompts import PACK

    system = (
        f"你是{role_desc}。下面是刚才多 agent 产出的结论与数据，用户会就它追问或让你展开。\n"
        f"{PACK.chat_guidance}\n"
        "不要提及你自己的身份或模型名。\n\n" + context
    )
    try:
        chain = [("system", system)] + [
            (_ROLE_MAP.get(m["role"], "human"), m["content"])
            for m in messages[-12:]
        ]
        ans = _chat_model().invoke(chain).content
        return {"answer": strip_model_noise(ans)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


@router.post("/api/review/chat")
def api_review_chat(request: Request, body: dict = Body(...)):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    msgs, err = _sanitize_messages(body.get("messages"))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    return _chat(_review_context(), "A 股短线复盘助手", msgs)


@router.get("/api/verification/menu")
def api_verify_menu():
    from duanxian.verification import DIRECTIONS, METRICS

    return JSONResponse({
        "directions": DIRECTIONS,
        "metrics": [{"key": m.key, "label": m.label, "hint": m.hint,
                     "unit": m.unit, "higher_is_hotter": m.higher_is_hotter}
                    for m in METRICS],
    })


@router.get("/api/verification/items")
def api_verify_items(date: str):
    from duanxian import verification

    try:
        date = validate_trade_date(date)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"date": date, "items": verification.load_user_items(date)})


@router.post("/api/verification/items")
def api_verify_save(request: Request, date: str, body: dict = Body(...)):
    if not _origin_ok(request):
        return JSONResponse({"error": "非法来源"}, status_code=403)
    from duanxian import verification

    try:
        date = validate_trade_date(date)
        return JSONResponse(verification.save_user_items(date, body.get("items") or []))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def pin_pool_to_settled_session() -> None:
    """未收盘的交易日，涨停池视为「还没有」——复盘类块自然落到上一场。"""
    import astock as astock_mod

    if getattr(astock_mod, "_pool_pinned", False):
        return
    if not hasattr(astock_mod, "em_zt_topic_pool"):
        return

    orig = astock_mod.em_zt_topic_pool

    def guarded(kind, date, sort, *a, **kw):
        ymd = str(date)
        if len(ymd) == 8 and ymd.isdigit():
            iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            if not trade_calendar.is_settled(iso):
                return []
        return orig(kind, date, sort, *a, **kw)

    astock_mod.em_zt_topic_pool = guarded
    astock_mod._pool_pinned = True
    astock_mod._pool_unpinned = orig


def register(app: FastAPI) -> None:
    """挂载短线复盘路由，并在启动时钉住涨停池日期口径。"""
    pin_pool_to_settled_session()
    app.include_router(router)
