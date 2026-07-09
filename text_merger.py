"""text_merger.py - 无时间戳文本的段落合并（用于 MiMo 等无时间戳 ASR）。"""

from __future__ import annotations

from typing import List

from engines.base import Segment

SENTENCE_ENDERS = set("。！？.!?")
MAX_BASE64_MB = 9.5


def _split_sentences(text: str) -> List[str]:
    """按句末标点切分，保留标点在句尾。换行符强制断句。"""
    sentences = []
    buf = []
    for ch in text:
        buf.append(ch)
        if ch == "\n":
            sentences.append("".join(buf))
            buf = []
        elif ch in SENTENCE_ENDERS:
            sentences.append("".join(buf))
            buf = []
    if buf:
        sentences.append("".join(buf))
    return sentences


def _hard_split(sentence: str, max_chars: int) -> List[str]:
    """对超长单句强制按 max_chars 切分。"""
    return [sentence[i : i + max_chars] for i in range(0, len(sentence), max_chars)]


def merge_text_into_paragraphs(text: str, max_chars: int = 2000) -> List[Segment]:
    """将无时间戳整段文本按句末标点 + max_chars 切分为段落。

    返回 Segment 列表，start=end=0（无时间戳）。
    """
    if not text or not text.strip():
        return []
    text = text.strip()
    paragraphs: List[str] = []
    current: List[str] = []
    current_len = 0

    for sentence in _split_sentences(text):
        sent = sentence.strip()
        if not sent:
            continue
        if len(sent) > max_chars:
            if current:
                paragraphs.append("".join(current))
                current = []
                current_len = 0
            paragraphs.extend(_hard_split(sent, max_chars))
            continue
        if current and current_len + len(sent) > max_chars:
            paragraphs.append("".join(current))
            current = []
            current_len = 0
        current.append(sent)
        current_len += len(sent)

    if current:
        paragraphs.append("".join(current))

    return [Segment(start=0.0, end=0.0, text=p) for p in paragraphs if p]
