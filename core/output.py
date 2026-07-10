"""core/output.py - 三文件输出逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from core.formatter import fmt_ts


def write_original(
    path: Path,
    paragraphs: list,
    meta: dict,
    timestamps: bool = False,
) -> None:
    """写入原文文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"音频文件: {meta['filename']}\n")
        f.write(f"检测语言: {meta['language']} ({meta['language_prob']:.1%})\n")
        f.write(f"音频时长: {fmt_ts(meta['duration'])}\n")
        f.write(f"段落数量: {len(paragraphs)}\n")
        f.write(f"转写时间: {meta['elapsed']:.1f}秒\n")
        f.write(f"{'=' * 60}\n\n")
        for para in paragraphs:
            if timestamps:
                f.write(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
            f.write(para.text + "\n\n")


def write_translated(
    path: Path,
    paragraphs: list,
    translations: List[str],
    meta: dict,
    timestamps: bool = False,
) -> None:
    """写入翻译文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"音频文件: {meta['filename']}\n")
        f.write(f"翻译引擎: DeepSeek ({meta.get('translator_model', 'N/A')})\n")
        f.write(f"公司背景: {meta.get('company_name', '未识别')}\n")
        f.write(f"{'=' * 60}\n\n")
        for para, trans in zip(paragraphs, translations):
            if timestamps:
                f.write(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
            f.write(trans + "\n\n")


def write_bilingual(
    path: Path,
    paragraphs: list,
    translations: List[str],
    meta: dict,
    timestamps: bool = False,
) -> None:
    """写入中英对照文件。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"音频文件: {meta['filename']}\n")
        f.write(f"翻译引擎: DeepSeek ({meta.get('translator_model', 'N/A')})\n")
        f.write(f"公司背景: {meta.get('company_name', '未识别')}\n")
        f.write(f"{'=' * 60}\n\n")
        for para, trans in zip(paragraphs, translations):
            if timestamps:
                f.write(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
            f.write(f"【原文】\n{para.text}\n\n")
            f.write(f"【中文】\n{trans}\n\n")
            f.write(f"{'- ' * 30}\n\n")
