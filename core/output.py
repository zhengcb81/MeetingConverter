"""core/output.py - 三文件输出逻辑（完整性安全写入）。

输出完整性边界：

- 译文/双语 writer 在任何写盘动作之前校验段落数与译文数一致，
  不一致抛 ``OutputCountMismatchError``（含 expected/actual），
  不再依赖 ``zip`` 静默丢弃多出的尾段；
- 三个 writer 都先在内存中完整渲染，再写入同目录临时文件，
  flush/close 成功后用 ``os.replace`` 原子替换目标；渲染、写入或
  替换任一阶段失败都会删除临时文件并保留目标旧字节；
- 只保证单文件原子性：三个输出文件之间没有跨文件事务。pipeline
  按原文→翻译→对照顺序调用，任一文件替换成功后后续文件失败时，
  已替换的文件保持新内容、失败文件保持旧内容，调用方需要整体重跑。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List

from core.formatter import fmt_ts


class OutputCountMismatchError(ValueError):
    """translations 数量与段落数不一致；expected=段落数，actual=译文数。"""


def _check_paired_lengths(paragraphs: list, translations: List[str]) -> None:
    expected = len(paragraphs)
    actual = len(translations)
    if expected != actual:
        raise OutputCountMismatchError(
            f"translations 数量与段落数不一致: expected {expected}, actual {actual}"
        )


def _render_original(paragraphs: list, meta: dict, timestamps: bool) -> str:
    lines = [
        f"音频文件: {meta['filename']}\n",
        f"检测语言: {meta['language']} ({meta['language_prob']:.1%})\n",
        f"音频时长: {fmt_ts(meta['duration'])}\n",
        f"段落数量: {len(paragraphs)}\n",
        f"转写时间: {meta['elapsed']:.1f}秒\n",
        f"{'=' * 60}\n\n",
    ]
    for para in paragraphs:
        if timestamps:
            lines.append(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
        lines.append(para.text + "\n\n")
    return "".join(lines)


def _render_translated(
    paragraphs: list, translations: List[str], meta: dict, timestamps: bool
) -> str:
    _check_paired_lengths(paragraphs, translations)
    lines = [
        f"音频文件: {meta['filename']}\n",
        f"翻译引擎: DeepSeek ({meta.get('translator_model', 'N/A')})\n",
        f"公司背景: {meta.get('company_name', '未识别')}\n",
        f"{'=' * 60}\n\n",
    ]
    for para, trans in zip(paragraphs, translations):
        if timestamps:
            lines.append(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
        lines.append(trans + "\n\n")
    return "".join(lines)


def _render_bilingual(
    paragraphs: list, translations: List[str], meta: dict, timestamps: bool
) -> str:
    _check_paired_lengths(paragraphs, translations)
    lines = [
        f"音频文件: {meta['filename']}\n",
        f"翻译引擎: DeepSeek ({meta.get('translator_model', 'N/A')})\n",
        f"公司背景: {meta.get('company_name', '未识别')}\n",
        f"{'=' * 60}\n\n",
    ]
    for para, trans in zip(paragraphs, translations):
        if timestamps:
            lines.append(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
        lines.append(f"【原文】\n{para.text}\n\n")
        lines.append(f"【中文】\n{trans}\n\n")
        lines.append(f"{'- ' * 30}\n\n")
    return "".join(lines)


def _atomic_write_text(path: Path, content: str) -> None:
    """把 content 原子写入 path：同目录临时文件 flush/close 成功后 os.replace。

    临时文件与目标同目录（同文件系统，replace 原子）。写入或替换失败时
    删除临时文件并原样保留目标旧字节；替换成功后临时文件即目标文件。
    """
    path = Path(path)
    tmp: Path | None = None
    handle = None
    try:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        tmp = Path(handle.name)
        handle.write(content)
        handle.flush()
        handle.close()
        handle = None
        os.replace(tmp, path)
        tmp = None
    except BaseException:
        if handle is not None and not handle.closed:
            try:
                handle.close()
            except OSError:
                pass
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def write_original(
    path: Path,
    paragraphs: list,
    meta: dict,
    timestamps: bool = False,
) -> None:
    """写入原文文件。渲染失败或写盘失败都不改动目标旧文件。"""
    content = _render_original(paragraphs, meta, timestamps)
    _atomic_write_text(Path(path), content)


def write_translated(
    path: Path,
    paragraphs: list,
    translations: List[str],
    meta: dict,
    timestamps: bool = False,
) -> None:
    """写入翻译文件。段落数与译文数不一致时在任何写盘前抛错。"""
    content = _render_translated(paragraphs, translations, meta, timestamps)
    _atomic_write_text(Path(path), content)


def write_bilingual(
    path: Path,
    paragraphs: list,
    translations: List[str],
    meta: dict,
    timestamps: bool = False,
) -> None:
    """写入中英对照文件。段落数与译文数不一致时在任何写盘前抛错。"""
    content = _render_bilingual(paragraphs, translations, meta, timestamps)
    _atomic_write_text(Path(path), content)
