"""metrics.py - 性能监控指标。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TranscribeMetrics:
    """单次转写的性能指标。"""

    filename: str = ""
    duration: float = 0.0  # 音频时长（秒）
    stt_elapsed: float = 0.0  # STT 耗时（秒）
    translate_elapsed: float = 0.0  # 翻译耗时（秒）
    output_elapsed: float = 0.0  # 文件输出耗时（秒）
    total_elapsed: float = 0.0  # 总耗时（秒）
    paragraphs: int = 0  # 段落数
    text_length: int = 0  # 文字数

    @property
    def rtf(self) -> float:
        """Real-Time Factor = 处理时间 / 音频时长。越小越快。"""
        if self.duration <= 0:
            return 0.0
        return self.total_elapsed / self.duration

    @property
    def chars_per_second(self) -> float:
        """每秒处理字符数。"""
        if self.total_elapsed <= 0:
            return 0.0
        return self.text_length / self.total_elapsed

    def summary(self) -> str:
        """格式化的性能摘要。"""
        parts = [
            f"文件: {self.filename}",
            f"音频: {self.duration:.1f}s",
            f"STT: {self.stt_elapsed:.1f}s",
        ]
        if self.translate_elapsed > 0:
            parts.append(f"翻译: {self.translate_elapsed:.1f}s")
        parts.extend([
            f"总耗时: {self.total_elapsed:.1f}s",
            f"RTF: {self.rtf:.2f}",
            f"速度: {self.chars_per_second:.0f} 字/秒",
        ])
        return " | ".join(parts)


class Timer:
    """简易计时器上下文管理器。"""

    def __init__(self):
        self.elapsed: float = 0.0
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed = time.time() - self._start
