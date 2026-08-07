"""数据时间审计：识别未来函数与数据泄漏。"""

from __future__ import annotations

from dataclasses import dataclass
import re

from quant_framework.models import DataFieldTiming


def _time_key(label: str) -> tuple:
    """把时间标签归一化为可排序的 key。

    支持 ISO 日期/日期时间（"2025-01-02"、"2025-01-02 15:00"），
    以及方法论中的 T 日标签（"T日开盘"、"T日收盘后"、"T+1日开盘"等）。
    """
    label = label.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?", label)
    if m:
        return (m.group(1), m.group(2) or "00:00")
    day_off = 1 if label.startswith("T+") else 0
    order = 0
    if "开盘" in label:
        order = 1
    elif "盘中" in label:
        order = 2
    elif "收盘后" in label or "盘后" in label:
        order = 4
    elif "收盘" in label:
        order = 3
    return (day_off, order)


@dataclass(frozen=True)
class AuditResult:
    field: DataFieldTiming
    order_time: str
    lookahead: bool
    reason: str = ""


def check_lookahead(available_time: str, order_time: str) -> bool:
    """字段可用时间晚于下单时间 => 存在未来函数/数据泄漏。"""
    return _time_key(available_time) > _time_key(order_time)


def audit_field_timing(
    field_name: str,
    event_time: str,
    available_time: str,
    signal_time: str,
    trade_time: str,
    order_time: str,
    note: str = "",
) -> AuditResult:
    """对单个字段做时间审计。

    例：年报报告期是 12-31，但可用时间应是实际披露日；
    收盘价因子：available=signal=收盘后，trade=次日，order=次日开盘。
    """
    timing = DataFieldTiming(
        field_name=field_name,
        event_time=event_time,
        available_time=available_time,
        signal_time=signal_time,
        trade_time=trade_time,
        note=note,
    )
    leak = check_lookahead(timing.available_time, order_time)
    reason = ""
    if leak:
        reason = (
            f"{field_name} 的可用时间 {available_time} 晚于下单时间 {order_time}，"
            "存在数据泄漏或未来函数风险"
        )
    return AuditResult(field=timing, order_time=order_time, lookahead=leak, reason=reason)


def audit_field_list(fields: list[DataFieldTiming], order_time: str) -> list[AuditResult]:
    return [
        AuditResult(
            field=f,
            order_time=order_time,
            lookahead=check_lookahead(f.available_time, order_time),
            reason=(
                f"{f.field_name} 的可用时间 {f.available_time} 晚于下单时间 {order_time}，"
                "存在数据泄漏或未来函数风险"
                if check_lookahead(f.available_time, order_time)
                else ""
            ),
        )
        for f in fields
    ]
