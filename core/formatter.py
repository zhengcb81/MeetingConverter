"""core/formatter.py - 格式化工具函数。"""

from __future__ import annotations


def fmt_ts(sec: float) -> str:
    """格式化秒数为 HH:MM:SS。"""
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
