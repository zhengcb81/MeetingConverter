"""audio_utils.py - 音频格式检测、大小估算、静音切片（用于 MiMo 长音频处理）。"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

MIMO_SUPPORTED = {"wav", "mp3"}
MAX_BASE64_MB = 4.0


def detect_format(path) -> Optional[str]:
    """检测音频格式，返回 MiMo 支持的格式名或 None。"""
    ext = Path(path).suffix.lower().lstrip(".")
    return ext if ext in MIMO_SUPPORTED else None


def estimate_base64_size_mb(path) -> float:
    """估算文件 base64 编码后大小（MB），base64 膨胀系数约 4/3。"""
    size = os.path.getsize(path)
    return size * 4 / 3 / (1024 * 1024)


def get_audio_duration(path) -> float:
    """用 ffprobe 获取音频时长（秒）。"""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
    )
    return float(result.stdout.decode("utf-8", errors="replace").strip())


def _parse_silence_starts(stderr_output: str) -> List[float]:
    """解析 ffmpeg silencedetect 输出，返回静音起点时间戳列表。"""
    starts = []
    for m in re.finditer(r"silence_start:\s*([\d.]+)", stderr_output):
        starts.append(float(m.group(1)))
    return starts


def _choose_split_points(
    silence_starts: List[float],
    total_duration: float,
    max_chunk_duration: float,
) -> List[Tuple[float, float]]:
    """根据静音点和最大片段时长选择切分点，每个片段不超过 max_chunk_duration。"""
    if total_duration <= max_chunk_duration:
        return [(0.0, total_duration)]

    chunks: List[Tuple[float, float]] = []
    chunk_start = 0.0
    while total_duration - chunk_start > max_chunk_duration:
        target = chunk_start + max_chunk_duration
        best = None
        for ts in silence_starts:
            if ts <= chunk_start:
                continue
            if ts > target:
                break
            best = ts
        if best is not None:
            chunks.append((chunk_start, best))
            chunk_start = best
        else:
            chunks.append((chunk_start, target))
            chunk_start = target
    chunks.append((chunk_start, total_duration))
    return chunks


def _estimate_max_chunk_duration(
    path, total_duration: float, max_size_mb: float = MAX_BASE64_MB
) -> float:
    """根据文件大小与时长估算不超过 max_size_mb 的最大片段时长。"""
    file_size = os.path.getsize(path)
    bytes_per_sec = file_size / total_duration if total_duration > 0 else 0
    if bytes_per_sec == 0:
        return total_duration
    max_bytes = max_size_mb * 1024 * 1024 * 3 / 4
    return max(max_bytes / bytes_per_sec, 1.0)


def split_by_silence(
    path,
    max_size_mb: float = MAX_BASE64_MB,
) -> List[Tuple[Path, float, float]]:
    """按静音点切分音频，返回 [(临时文件路径, start, end), ...]。"""
    total_duration = get_audio_duration(path)
    max_chunk_duration = _estimate_max_chunk_duration(path, total_duration, max_size_mb)

    if total_duration <= max_chunk_duration:
        return [(Path(path), 0.0, total_duration)]

    detect = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            "silencedetect=noise=-30dB:d=0.5",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
    )
    silence_starts = _parse_silence_starts(detect.stderr.decode("utf-8", errors="replace"))

    if not silence_starts:
        silence_starts = [
            max_chunk_duration * (i + 1)
            for i in range(int(total_duration / max_chunk_duration))
            if max_chunk_duration * (i + 1) < total_duration
        ]

    chunks = _choose_split_points(silence_starts, total_duration, max_chunk_duration)
    result: List[Tuple[Path, float, float]] = []
    src_ext = Path(path).suffix
    for i, (start, end) in enumerate(chunks):
        tmp = Path(tempfile.gettempdir()) / f"mimo_chunk_{i}{src_ext}"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                str(path),
                "-c",
                "copy",
                str(tmp),
            ],
            capture_output=True,
        )
        result.append((tmp, start, end))
    return result
