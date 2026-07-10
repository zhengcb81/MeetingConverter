"""core/batch.py - 批量转写调度。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

from core.formatter import fmt_ts
from core.pipeline import transcribe_one

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".wma",
    ".aac",
    ".opus",
    ".webm",
}


def get_audio_files(path: str) -> List[Path]:
    """获取音频文件列表（单个文件或目录）。"""
    p = Path(path)
    if p.is_file():
        return [p] if p.suffix.lower() in AUDIO_EXTENSIONS else []
    if p.is_dir():
        seen = set()
        files = []
        for ext in AUDIO_EXTENSIONS:
            for f in p.glob(f"*{ext}"):
                if f not in seen:
                    seen.add(f)
                    files.append(f)
        files.sort()
        return files
    return []


def run_batch(
    engine,
    audio_files: List[Path],
    output_dir: Path,
    translator_obj=None,
    language: Optional[str] = None,
    timestamps: bool = False,
    initial_prompt: Optional[str] = None,
    company_context_fn=None,
    corrections_fn=None,
    merge_gap_sec: float = 2.0,
    paragraph_max_chars: int = 2000,
    force: bool = False,
) -> dict:
    """批量转写音频文件，返回统计信息。

    Args:
        engine: 转写引擎实例
        audio_files: 音频文件列表
        output_dir: 输出目录
        translator_obj: 翻译器实例
        language: 语言代码
        timestamps: 是否输出时间戳
        initial_prompt: 转写提示词
        company_context_fn: 获取公司背景的函数 (filename) -> str
        corrections_fn: 获取纠正规则的函数 (filename) -> dict
        merge_gap_sec: 段落合并间隔
        paragraph_max_chars: 段落最大字符数
        force: 是否强制重新处理

    Returns:
        统计信息 dict
    """
    results = []
    skipped = 0
    failures = 0

    for af in audio_files:
        # 获取公司背景和纠正规则
        ctx = ""
        corrs = {}
        if company_context_fn:
            ctx = company_context_fn(af.name)
        if corrections_fn:
            corrs = corrections_fn(af.name)
        if ctx:
            logger.info(f"识别公司: {ctx.split(chr(10))[0]}")
        if corrs:
            logger.info(f"纠正规则: {len(corrs)} 条")

        try:
            result = transcribe_one(
                engine,
                af,
                output_dir,
                translator_obj,
                language=language,
                timestamps=timestamps,
                initial_prompt=initial_prompt,
                company_context=ctx,
                corrections=corrs,
                merge_gap_sec=merge_gap_sec,
                paragraph_max_chars=paragraph_max_chars,
                force=force,
            )
            if result is not None:
                results.append(result)
            else:
                skipped += 1
        except Exception as e:
            import traceback

            traceback.print_exc()
            logger.error(f"错误: {af.name} - {e}")
            failures += 1

    # 输出统计
    if results:
        total_dur = sum(r["duration"] for r in results)
        total_time = sum(r["elapsed"] for r in results)
        total_chars = sum(r["text_length"] for r in results)
        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"全部完成! 文件:{len(results)} 跳过:{skipped} 失败:{failures} "
            f"总时长:{fmt_ts(total_dur)} 耗时:{total_time:.0f}s 文字:{total_chars:,}"
        )
        logger.info(f"输出: {output_dir.resolve()}")
    elif skipped > 0:
        logger.info(f"\n全部跳过 ({skipped} 个文件已完成)")
    else:
        logger.info("\n无文件处理")

    return {
        "processed": len(results),
        "skipped": skipped,
        "failures": failures,
        "results": results,
    }
