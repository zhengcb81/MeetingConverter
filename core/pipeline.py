"""core/pipeline.py - 单文件转写主流程。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.feedback import (
    ROLE_BILINGUAL,
    ROLE_ORIGINAL,
    ROLE_TRANSLATED,
    STAGE_OUTPUT,
    STAGE_TRANSCRIPTION,
    STAGE_TRANSLATION,
    begin_operation,
)
from core.formatter import fmt_ts
from core.output import write_bilingual, write_original, write_translated
from engines.base import Segment
from exceptions import TranslationError
from metrics import Timer, TranscribeMetrics

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
    translated_file = output_dir / f"{stem}_翻译.txt"
    bilingual_file = output_dir / f"{stem}_中英对照.txt"

    feedback = begin_operation(
        audio_path=audio_path,
        translate_requested=translator_obj is not None,
        force=force,
    )
    feedback.start()

    if not force and original_file.exists():
        logger.info(f"跳过 (已完成): {audio_path.name}")
        feedback.note_engine_not_started()
        feedback.note_reuse(translated_file, bilingual_file)
        feedback.finish()
        feedback.flush()
        return None

    logger.info(f"\n{'=' * 60}")
    logger.info(f"转写: {audio_path.name}")
    logger.info(f"{'=' * 60}")

    total_timer = Timer()
    metrics = TranscribeMetrics(filename=audio_path.name)

    try:
        with total_timer:
            stt_timer = Timer()
            try:
                with stt_timer:
                    feedback.set_stage(STAGE_TRANSCRIPTION)
                    feedback.note_engine_started()
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
                    # 段落数与字数在计时区间内如实记账：失败路径上的步骤日志
                    # 因此仍然是这一轮的真实事实，而不是一片 0。
                    metrics.paragraphs = len(paragraphs)
                    metrics.text_length = sum(len(para.text) for para in paragraphs)
            finally:
                # 引擎抛错时耗时照样记账：失败路径的步骤日志说得清工作了多久，
                # 消费方因此能区分“立刻失败”与“干了一会儿才失败”。
                metrics.stt_elapsed = stt_timer.elapsed
            metrics.duration = duration
            logger.info(f"转写完成: {len(paragraphs)} 段, {stt_timer.elapsed:.1f}秒")

            # 翻译
            translations = None
            translation_failed = False
            if translator_obj:
                logger.info(
                    f"\n翻译中 (DeepSeek {translator_obj.model}, "
                    f"公司: {company_context.split(chr(10))[0] if company_context else '无'})"
                )
                feedback.set_stage(STAGE_TRANSLATION)
                trans_timer = Timer()
                try:
                    with trans_timer:
                        try:
                            translations = translator_obj.translate_paragraphs(
                                [para.text for para in paragraphs],
                                company_context=company_context,
                                corrections=corrections,
                                progress_callback=lambda c, n: logger.info(f"  翻译: {c}/{n}"),
                            )
                        except TranslationError as e:
                            logger.warning(f"翻译失败，跳过翻译文件: {e}")
                            feedback.note_error(e)
                            translations = None
                            translation_failed = True
                finally:
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

            output_timer = Timer()
            try:
                with output_timer:
                    feedback.set_stage(STAGE_OUTPUT)
                    orig = output_dir / f"{stem}_原文.txt"
                    try:
                        write_original(orig, paragraphs, meta, timestamps)
                    except BaseException as exc:
                        # 连 BaseException 也记这一行：写盘中被打断时消费方
                        # 仍能看到这个角色的失败事实，异常照常向上抛。
                        feedback.note_writer_failed(ROLE_ORIGINAL, orig, exc)
                        raise
                    feedback.note_writer_committed(ROLE_ORIGINAL, orig)
                    logger.info(f"  原文: {orig}")

                    if translations is None:
                        logger.info("  未启用翻译，跳过翻译和中英对照文件")
                        if translation_failed:
                            # 本轮没有产出译文与对照：旧件仍在，或根本没有。
                            feedback.note_writer_not_produced(ROLE_TRANSLATED, translated_file)
                            feedback.note_writer_not_produced(ROLE_BILINGUAL, bilingual_file)
                        else:
                            feedback.note_writer_not_requested(ROLE_TRANSLATED)
                            feedback.note_writer_not_requested(ROLE_BILINGUAL)
                    else:
                        tr = output_dir / f"{stem}_翻译.txt"
                        try:
                            write_translated(tr, paragraphs, translations, meta, timestamps)
                        except BaseException as exc:
                            feedback.note_writer_failed(ROLE_TRANSLATED, tr, exc)
                            raise
                        feedback.note_writer_committed(ROLE_TRANSLATED, tr)
                        logger.info(f"  翻译: {tr}")

                        bi = output_dir / f"{stem}_中英对照.txt"
                        try:
                            write_bilingual(bi, paragraphs, translations, meta, timestamps)
                        except BaseException as exc:
                            feedback.note_writer_failed(ROLE_BILINGUAL, bi, exc)
                            raise
                        feedback.note_writer_committed(ROLE_BILINGUAL, bi)
                        logger.info(f"  对照: {bi}")
            finally:
                # writer 抛错时输出耗时照样记账：失败路径的步骤日志因此仍然
                # 说得清这一轮做了什么。
                metrics.output_elapsed = output_timer.elapsed

        metrics.total_elapsed = total_timer.elapsed
        logger.info(f"性能: {metrics.summary()}")
        feedback.finish(_metric_snapshot(metrics))
    except Exception as exc:
        # 异常终态是可知的：按阶段给出失败原因。
        metrics.total_elapsed = total_timer.elapsed
        feedback.note_abort()
        feedback.note_error(exc)
        feedback.finish(_metric_snapshot(metrics))
        raise
    except BaseException as exc:
        # 被中止：没有可信终态，终态保留 unknown。
        metrics.total_elapsed = total_timer.elapsed
        feedback.mark_unknown()
        feedback.note_error(exc)
        feedback.finish(_metric_snapshot(metrics))
        raise
    finally:
        # 此刻没有任何计时器打开：旁路自身的写入耗时不进任何被发布的字段，
        # 启用与禁用两次运行的产物字节因此一致。
        feedback.flush()

    return {
        "input": str(audio_path),
        "paragraphs": metrics.paragraphs,
        "language": lang,
        "duration": duration,
        "elapsed": metrics.total_elapsed,
        "text_length": metrics.text_length,
        "rtf": metrics.rtf,
    }


# ── 反馈辅助 ──────────────────────────────────────────────────────


def _metric_snapshot(metrics: TranscribeMetrics) -> dict:
    """本轮 metrics 的投影：只给旁路，不新增业务状态库。"""
    return {
        "paragraphs": metrics.paragraphs,
        "duration": metrics.duration,
        "stt_elapsed": metrics.stt_elapsed,
        "translate_elapsed": metrics.translate_elapsed,
        "output_elapsed": metrics.output_elapsed,
        "total_elapsed": metrics.total_elapsed,
        "text_length": metrics.text_length,
    }
