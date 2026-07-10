"""core/pipeline.py - 单文件转写主流程。"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from core.output import write_original, write_translated, write_bilingual
from core.formatter import fmt_ts
from engines.base import Segment
from exceptions import TranslationError
from metrics import TranscribeMetrics, Timer

logger = logging.getLogger(__name__)


# ── 段落合并 ──────────────────────────────────────────────────────


class Paragraph:
    """转写段落，包含时间戳和文本。"""

    def __init__(self):
        self.start = 0.0
        self.end = 0.0
        self.segments: list[Segment] = []
        self.text = ""

    def add_segment(self, seg: Segment):
        if not self.segments:
            self.start = seg.start
        self.end = seg.end
        self.segments.append(seg)
        self.text += seg.text.strip() + " "

    def finalize(self):
        self.text = self.text.strip()


def merge_into_paragraphs(segments_iter, gap_threshold=2.0, max_chars=2000):
    """将 whisper 段落合并为更大的逻辑段落。"""
    paragraphs = []
    current = Paragraph()
    prev_end = 0.0
    sentence_enders = set(".!?。！？")

    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        gap = seg.start - prev_end if prev_end > 0 else 0
        cur_len = len(current.text)

        should_split = False
        if current.segments:
            if gap > gap_threshold:
                should_split = True
            elif current.text and current.text[-1] in sentence_enders and cur_len > 100:
                should_split = True
            elif cur_len > max_chars:
                should_split = True

        if should_split:
            current.finalize()
            paragraphs.append(current)
            current = Paragraph()

        current.add_segment(Segment(start=seg.start, end=seg.end, text=text))
        prev_end = seg.end

    if current.segments:
        current.finalize()
        paragraphs.append(current)

    return paragraphs


# ── 主流程 ────────────────────────────────────────────────────────


def transcribe_one(
    engine,
    audio_path: Path,
    output_dir: Path,
    translator_obj=None,
    language: Optional[str] = None,
    timestamps: bool = False,
    initial_prompt: Optional[str] = None,
    company_context: str = "",
    corrections: Optional[dict] = None,
    merge_gap_sec: float = 2.0,
    paragraph_max_chars: int = 2000,
    force: bool = False,
) -> Optional[dict]:
    """转写单个音频文件，返回结果摘要或 None（跳过时）。

    Args:
        engine: 转写引擎实例
        audio_path: 音频文件路径
        output_dir: 输出目录
        translator_obj: 翻译器实例（None 表示不翻译）
        language: 语言代码（None 表示自动检测）
        timestamps: 是否输出时间戳
        initial_prompt: 转写提示词
        company_context: 公司背景知识
        corrections: 纠正规则
        merge_gap_sec: 段落合并间隔（秒）
        paragraph_max_chars: 段落最大字符数
        force: 是否强制重新处理

    Returns:
        结果摘要 dict 或 None（文件已存在且未 force）
    """
    stem = audio_path.stem
    original_file = output_dir / f"{stem}_原文.txt"
    if not force and original_file.exists():
        logger.info(f"跳过 (已完成): {audio_path.name}")
        return None

    logger.info(f"\n{'=' * 60}")
    logger.info(f"转写: {audio_path.name}")
    logger.info(f"{'=' * 60}")

    total_timer = Timer()
    metrics = TranscribeMetrics(filename=audio_path.name)

    with total_timer:
        with Timer() as stt_timer:
            result = engine.transcribe(
                str(audio_path), language=language, initial_prompt=initial_prompt
            )
            lang, lang_prob, duration = (
                result.language,
                result.language_probability,
                result.duration,
            )
            logger.info(f"语言: {lang} ({lang_prob:.1%})  时长: {fmt_ts(duration)}")

            if result.paragraph_level:
                paragraphs = result.segments
            else:
                logger.info("合并段落...")
                paragraphs = merge_into_paragraphs(
                    result.segments,
                    gap_threshold=merge_gap_sec,
                    max_chars=paragraph_max_chars,
                )
        metrics.stt_elapsed = stt_timer.elapsed
        metrics.duration = duration
        logger.info(f"转写完成: {len(paragraphs)} 段, {stt_timer.elapsed:.1f}秒")

        # 翻译
        translations = None
        if translator_obj:
            logger.info(
                f"\n翻译中 (DeepSeek {translator_obj.model}, "
                f"公司: {company_context.split(chr(10))[0] if company_context else '无'})"
            )
            with Timer() as trans_timer:
                try:
                    translations = translator_obj.translate_paragraphs(
                        [para.text for para in paragraphs],
                        company_context=company_context,
                        corrections=corrections,
                        progress_callback=lambda c, n: logger.info(f"  翻译: {c}/{n}"),
                    )
                except TranslationError as e:
                    logger.warning(f"翻译失败，跳过翻译文件: {e}")
                    translations = None
            metrics.translate_elapsed = trans_timer.elapsed
            if translations is not None:
                logger.info(f"翻译完成: {trans_timer.elapsed:.1f}秒")

        # 输出
        meta = {
            "filename": audio_path.name,
            "language": lang,
            "language_prob": lang_prob,
            "duration": duration,
            "elapsed": metrics.stt_elapsed,
            "company_name": company_context.split("\n")[0] if company_context else "",
            "translator_model": translator_obj.model if translator_obj else "N/A",
        }

        with Timer() as output_timer:
            orig = output_dir / f"{stem}_原文.txt"
            write_original(orig, paragraphs, meta, timestamps)
            logger.info(f"  原文: {orig}")

            if translations is None:
                logger.info("  未启用翻译，跳过翻译和中英对照文件")
            else:
                tr = output_dir / f"{stem}_翻译.txt"
                write_translated(tr, paragraphs, translations, meta, timestamps)
                logger.info(f"  翻译: {tr}")

                bi = output_dir / f"{stem}_中英对照.txt"
                write_bilingual(bi, paragraphs, translations, meta, timestamps)
                logger.info(f"  对照: {bi}")
        metrics.output_elapsed = output_timer.elapsed

    metrics.total_elapsed = total_timer.elapsed
    metrics.paragraphs = len(paragraphs)
    metrics.text_length = sum(len(para.text) for para in paragraphs)
    logger.info(f"性能: {metrics.summary()}")

    return {
        "input": str(audio_path),
        "paragraphs": metrics.paragraphs,
        "language": lang,
        "duration": duration,
        "elapsed": metrics.total_elapsed,
        "text_length": metrics.text_length,
        "rtf": metrics.rtf,
    }
