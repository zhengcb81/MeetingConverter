"""tests/test_output.py - core.output 输出完整性与安全写入测试。

所有输入/输出都只落在 pytest tmp_path。每个用例前后用目录快照
（相对路径 -> SHA-256）核对清单与字节；autouse fixture 保证任何
用例结束都不残留 *.tmp 孤儿临时文件。不触发 MiMo/DeepSeek、网络
与真实音频：Paragraph/Segment 全部为合成对象。
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import pytest

from core.output import (
    OutputCountMismatchError,
    write_bilingual,
    write_original,
    write_translated,
)
from core.pipeline import Paragraph
from engines.base import Segment

ALL_WRITERS = [write_original, write_translated, write_bilingual]
PAIRED_WRITERS = [write_translated, write_bilingual]


@pytest.fixture(autouse=True)
def _no_orphan_tmp_files(tmp_path):
    """任何用例结束后 tmp_path 内不允许残留 .tmp 临时文件。"""
    yield
    orphans = sorted(str(p) for p in tmp_path.rglob("*.tmp") if p.is_file())
    assert not orphans, f"孤儿临时文件: {orphans}"


def _make_paragraph(start, end, text):
    p = Paragraph()
    p.start = start
    p.end = end
    p.text = text
    p.segments = [Segment(start=start, end=end, text=text)]
    return p


class BoomParagraph:
    """start 属性被读取时抛错：模拟渲染中途失败（timestamps=True 时三个
    writer 都会读取该属性）。"""

    def __init__(self):
        self.end = 1.0

    @property
    def start(self):
        raise RuntimeError("boom during render")

    @property
    def text(self):
        raise RuntimeError("boom during render")


@pytest.fixture
def sample_paragraphs():
    return [
        _make_paragraph(0.0, 10.0, "Revenue grew 30% year over year."),
        _make_paragraph(10.0, 20.0, "毛利率提升至21.5%，环比改善。"),
        _make_paragraph(20.0, 30.0, "Mixed 中英混合 paragraph number 3。"),
    ]


@pytest.fixture
def sample_translations():
    return [
        "营收同比增长30%",
        "毛利率提升至21.5%",
        "混合段落译文第三段",
    ]


@pytest.fixture
def sample_meta():
    return {
        "filename": "earnings_call.mp3",
        "language": "en",
        "language_prob": 0.95,
        "duration": 120.0,
        "elapsed": 5.3,
        "company_name": "Xiaomi",
        "translator_model": "deepseek-v4-flash",
    }


def _write(writer, path, paragraphs, translations, meta, timestamps=False):
    if writer is write_original:
        writer(path, paragraphs, meta, timestamps)
    else:
        writer(path, paragraphs, translations, meta, timestamps)


def _snapshot(root: Path) -> dict:
    """目录清单与字节指纹：{相对路径: SHA-256}，作为用例开始/结束状态记录。"""
    root = Path(root)
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _body_texts(writer, paragraphs, translations):
    """按 writer 返回会进入正文的文本，用于逐条出现与顺序断言。"""
    if writer is write_original:
        return [p.text for p in paragraphs]
    if writer is write_translated:
        return list(translations)
    return [frag for pair in zip((p.text for p in paragraphs), translations) for frag in pair]


class TestSuccessfulOutput:
    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_paragraph_by_paragraph_utf8_content(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        before = _snapshot(tmp_path)
        assert before == {}

        _write(writer, out, sample_paragraphs, sample_translations, sample_meta)

        raw = out.read_bytes()
        content = raw.decode("utf-8")  # 非 UTF-8 字节会在此失败
        texts = _body_texts(writer, sample_paragraphs, sample_translations)
        positions = [content.index(t) for t in texts]
        assert positions == sorted(positions), "段落/译文必须逐条按顺序出现"
        for t in texts:
            assert t in content

        after = _snapshot(tmp_path)
        assert after == {out.name: hashlib.sha256(raw).hexdigest()}

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    @pytest.mark.parametrize("timestamps", [True, False])
    def test_timestamp_toggle(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path, timestamps
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        _write(
            writer, out, sample_paragraphs, sample_translations, sample_meta, timestamps
        )
        content = out.read_text(encoding="utf-8")
        if timestamps:
            for stamp in (
                "[00:00:00 -> 00:00:10]",
                "[00:00:10 -> 00:00:20]",
                "[00:00:20 -> 00:00:30]",
            ):
                assert stamp in content
        else:
            assert "[00:00:00 ->" not in content
            assert "[00:00:10 ->" not in content

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    @pytest.mark.parametrize("kind", ["empty", "single", "multi"])
    def test_empty_single_multiple_paragraphs(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path, kind
    ):
        if kind == "empty":
            paragraphs, translations = [], []
        elif kind == "single":
            paragraphs, translations = sample_paragraphs[:1], sample_translations[:1]
        else:
            paragraphs, translations = sample_paragraphs, sample_translations

        out = tmp_path / f"{writer.__name__}.txt"
        _write(writer, out, paragraphs, translations, sample_meta)

        content = out.read_text(encoding="utf-8")
        assert "音频文件: earnings_call.mp3" in content
        if writer is write_original:
            assert f"段落数量: {len(paragraphs)}" in content
        expected_texts = _body_texts(writer, paragraphs, translations)
        if kind == "empty":
            assert "【原文】" not in content
            assert "【中文】" not in content
            for t in expected_texts:
                assert t not in content
        else:
            for t in expected_texts:
                assert t in content


class TestCountMismatch:
    @pytest.mark.parametrize("writer", PAIRED_WRITERS, ids=lambda w: w.__name__)
    @pytest.mark.parametrize("delta", [-1, 1], ids=["short-by-one", "long-by-one"])
    def test_mismatch_fails_before_touching_final_file(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path, delta
    ):
        translations = (
            sample_translations[:delta] if delta < 0 else sample_translations + ["多余译文"]
        )
        expected_count = len(sample_paragraphs)
        actual_count = len(translations)
        out = tmp_path / f"{writer.__name__}.txt"

        with pytest.raises(OutputCountMismatchError) as excinfo:
            _write(writer, out, sample_paragraphs, translations, sample_meta)

        message = str(excinfo.value)
        assert f"expected {expected_count}" in message
        assert f"actual {actual_count}" in message
        # 目标与临时文件都不存在：校验发生在任何写盘之前
        assert _snapshot(tmp_path) == {}

    @pytest.mark.parametrize("writer", PAIRED_WRITERS, ids=lambda w: w.__name__)
    @pytest.mark.parametrize("delta", [-1, 1], ids=["short-by-one", "long-by-one"])
    def test_mismatch_preserves_existing_target_bytes(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path, delta
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        _write(writer, out, sample_paragraphs, sample_translations, sample_meta)
        before = _snapshot(tmp_path)

        translations = (
            sample_translations[:delta] if delta < 0 else sample_translations + ["多余译文"]
        )
        with pytest.raises(ValueError) as excinfo:
            _write(writer, out, sample_paragraphs, translations, sample_meta)

        assert "expected 3" in str(excinfo.value)
        assert _snapshot(tmp_path) == before

    @pytest.mark.parametrize("writer", PAIRED_WRITERS, ids=lambda w: w.__name__)
    def test_zero_paragraphs_one_translation(
        self, writer, sample_meta, tmp_path
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        with pytest.raises(OutputCountMismatchError, match="expected 0, actual 1"):
            _write(writer, out, [], ["多出来的译文"], sample_meta)
        assert _snapshot(tmp_path) == {}


class TestRenderFailure:
    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_mid_render_failure_preserves_target(
        self, writer, sample_translations, sample_meta, tmp_path
    ):
        # timestamps=True 确保三个 writer 都会读取段落时间戳属性
        paragraphs = [_make_paragraph(0.0, 1.0, "正常段落。"), BoomParagraph()]
        translations = sample_translations[:2]
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"previous complete result")
        before = _snapshot(tmp_path)

        with pytest.raises(RuntimeError, match="boom during render"):
            _write(writer, out, paragraphs, translations, sample_meta, timestamps=True)

        assert _snapshot(tmp_path) == before


class TestTempWriteFailure:
    # 第二段原文与第二段译文都带孤代理字符：UTF-8 编码在写入中途失败

    @staticmethod
    def _surrogate_inputs():
        paragraphs = [
            _make_paragraph(0.0, 1.0, "正常段落。"),
            _make_paragraph(1.0, 2.0, "坏字符 \ud800 段落。"),
        ]
        translations = ["正常译文。", "坏译文 \ud800。"]
        return paragraphs, translations

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_mid_write_failure_preserves_target_and_cleans_tmp(
        self, writer, sample_meta, tmp_path
    ):
        paragraphs, translations = self._surrogate_inputs()
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"previous complete result")
        before = _snapshot(tmp_path)

        with pytest.raises(UnicodeEncodeError):
            _write(writer, out, paragraphs, translations, sample_meta)

        assert _snapshot(tmp_path) == before

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_replace_failure_preserves_target_and_cleans_tmp(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path,
        monkeypatch
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"previous complete result")
        before = _snapshot(tmp_path)

        def _deny_replace(src, dst):
            raise OSError("replace denied (simulated)")

        monkeypatch.setattr("core.output.os.replace", _deny_replace)
        with pytest.raises(OSError, match="replace denied"):
            _write(writer, out, sample_paragraphs, sample_translations, sample_meta)

        assert _snapshot(tmp_path) == before

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows 目标被占用语义")
    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_windows_open_target_blocks_replace(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path
    ):
        """目标被其他句柄打开时 os.replace 抛 PermissionError（真实场景）。"""
        out = tmp_path / f"{writer.__name__}.txt"
        _write(writer, out, sample_paragraphs, sample_translations, sample_meta)
        before = _snapshot(tmp_path)

        with open(out, "r", encoding="utf-8") as held:
            assert held.read(1)
            with pytest.raises(PermissionError):
                _write(writer, out, sample_paragraphs, sample_translations, sample_meta)

        assert _snapshot(tmp_path) == before


class TestRerunOverwrite:
    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_successful_rerun_replaces_whole_file(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        _write(writer, out, sample_paragraphs, sample_translations, sample_meta)
        first = _snapshot(tmp_path)

        new_paragraphs = [
            _make_paragraph(0.0, 5.0, "Completely new single paragraph."),
        ]
        new_translations = ["全新的单段译文。"]
        _write(writer, out, new_paragraphs, new_translations, sample_meta)
        after = _snapshot(tmp_path)

        content = out.read_text(encoding="utf-8")
        new_texts = _body_texts(writer, new_paragraphs, new_translations)
        for t in new_texts:
            assert t in content
        old_texts = set(_body_texts(writer, sample_paragraphs, sample_translations))
        for t in old_texts - set(new_texts):
            assert t not in content
        assert list(after) == [out.name]
        assert after[out.name] != first[out.name]

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_failure_then_success_recovers(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path
    ):
        """失败重试后成功：目标最终是完整新文件，且无临时残留。"""
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"old bytes")
        broken_paragraphs = sample_paragraphs + [BoomParagraph()]
        broken_translations = sample_translations + ["不会被写出的译文"]
        with pytest.raises(RuntimeError, match="boom during render"):
            _write(
                writer, out, broken_paragraphs, broken_translations, sample_meta,
                timestamps=True,
            )
        assert out.read_bytes() == b"old bytes"

        _write(writer, out, sample_paragraphs, sample_translations, sample_meta)
        content = out.read_text(encoding="utf-8")
        for t in _body_texts(writer, sample_paragraphs, sample_translations):
            assert t in content
        assert "old bytes" not in content
        assert "不会被写出的译文" not in content


class TestErrorContract:
    def test_mismatch_error_is_value_error(self):
        assert issubclass(OutputCountMismatchError, ValueError)

    def test_mismatch_error_has_structured_counts(
        self, sample_paragraphs, sample_translations, sample_meta, tmp_path
    ):
        out = tmp_path / "translated.txt"
        with pytest.raises(OutputCountMismatchError) as excinfo:
            write_translated(
                out, sample_paragraphs, sample_translations[:-1], sample_meta
            )
        assert excinfo.value.expected == len(sample_paragraphs)
        assert excinfo.value.actual == len(sample_translations) - 1


class _FlushBoomHandle:
    """包装真实 NamedTemporaryFile 句柄：flush() 抛 OSError，其余接口透传。

    真实临时文件已落盘、内容 write() 已成功，把失败精确注入 flush 阶段
    （模拟 flush 时磁盘满/配额），与既有注入机制（代理字符 write 中途
    UnicodeEncodeError、monkeypatch os.replace、Windows 真实占用）不同。
    """

    def __init__(self, real):
        self._real = real
        self.flush_failed = False

    @property
    def name(self):
        return self._real.name

    @property
    def closed(self):
        return self._real.closed

    def write(self, data):
        return self._real.write(data)

    def flush(self):
        self.flush_failed = True
        raise OSError("flush failed (simulated disk full at flush stage)")

    def close(self):
        return self._real.close()


class TestIndependentReviewerCounterexample:
    """独立审查反例：flush 阶段 OSError 与临时文件工厂创建失败。

    两种失败都发生在目标被触碰之前，必须：异常原样传播、目标旧字节
    SHA 不变、无 *.tmp 残留。
    """

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_flush_failure_preserves_target_and_cleans_tmp(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path,
        monkeypatch,
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"previous complete result")
        before = _snapshot(tmp_path)

        real_factory = tempfile.NamedTemporaryFile
        created = []

        def _factory(**kwargs):
            handle = _FlushBoomHandle(real_factory(**kwargs))
            created.append(handle)
            return handle

        monkeypatch.setattr("core.output.tempfile.NamedTemporaryFile", _factory)

        with pytest.raises(OSError, match="flush failed"):
            _write(writer, out, sample_paragraphs, sample_translations, sample_meta)

        # 失败确实发生在 flush 阶段（write 已成功、真实临时文件已建）
        assert created, "必须真正创建过临时文件"
        assert created[0].flush_failed, "失败必须由 flush() 抛出"
        assert created[0].closed, "清理阶段必须关闭泄漏的句柄"
        # 目标旧字节原样保留（SHA 逐文件比对）
        assert _snapshot(tmp_path) == before
        # 无临时文件残留
        assert not [p for p in tmp_path.rglob("*.tmp") if p.is_file()]

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_factory_failure_preserves_target_and_leaves_no_tmp(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path,
        monkeypatch,
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"previous complete result")
        before = _snapshot(tmp_path)

        def _deny_factory(**kwargs):
            raise OSError("tmpfile creation denied (simulated)")

        monkeypatch.setattr("core.output.tempfile.NamedTemporaryFile", _deny_factory)

        with pytest.raises(OSError, match="creation denied"):
            _write(writer, out, sample_paragraphs, sample_translations, sample_meta)

        assert _snapshot(tmp_path) == before
        assert not [p for p in tmp_path.rglob("*.tmp") if p.is_file()]


class _CloseBoomHandle:
    """包装真实 NamedTemporaryFile 句柄：close() 抛 OSError，fd 透传。

    真实临时文件已写入并 flush 成功，失败精确注入 close 阶段（模拟
    close 时才暴露的写错误）。句柄对外永远报告未关闭，暴露底层 fd
    供实现强关清理——对应审查发现 #1 的修复分支。
    """

    def __init__(self, real):
        self._real = real
        self.close_failed = False

    @property
    def name(self):
        return self._real.name

    @property
    def closed(self):
        return False

    def write(self, data):
        return self._real.write(data)

    def flush(self):
        return self._real.flush()

    def fileno(self):
        return self._real.fileno()

    def close(self):
        self.close_failed = True
        raise OSError("close failed (simulated write error at close stage)")


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestCloseFailureCleanup:
    """close 阶段失败：强关底层 fd 后仍必须清理临时件并保留目标旧字节。

    被测路径故意 os.close 底层 fd（数据本就要丢弃），真实临时文件包装层
    在 GC 析构时对已关 fd 再 close 会产生不可抛出的 EBADF 噪音——属预期
    副作用而非泄漏（文件已删、fd 已关），故定向忽略该 unraisable warning。
    """

    @pytest.mark.parametrize("writer", ALL_WRITERS, ids=lambda w: w.__name__)
    def test_close_failure_still_cleans_tmp(
        self, writer, sample_paragraphs, sample_translations, sample_meta, tmp_path,
        monkeypatch,
    ):
        out = tmp_path / f"{writer.__name__}.txt"
        out.write_bytes(b"previous complete result")
        before = _snapshot(tmp_path)

        real_factory = tempfile.NamedTemporaryFile
        handles = []

        def _factory(**kwargs):
            handle = _CloseBoomHandle(real_factory(**kwargs))
            handles.append(handle)
            return handle

        monkeypatch.setattr("core.output.tempfile.NamedTemporaryFile", _factory)

        with pytest.raises(OSError, match="close failed"):
            _write(writer, out, sample_paragraphs, sample_translations, sample_meta)

        assert handles and handles[0].close_failed, "失败必须由 close() 抛出"
        assert _snapshot(tmp_path) == before
        assert not [p for p in tmp_path.rglob("*.tmp") if p.is_file()]
