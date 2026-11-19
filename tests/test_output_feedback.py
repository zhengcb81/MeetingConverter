"""tests/test_output_feedback.py - 转录发布反馈旁路（feedback-observation/1）。

这些用例全部经公开入口 ``core.transcribe_one`` / ``core.batch.run_batch``
触发，只使用合成音频与 stub 引擎/翻译器：运行不接触网络、凭证、真实音频
或其他仓的服务。

断言分三层：

- 业务层：返回值、产物文件与字节、引擎/翻译调用次数。旁路启用、禁用或
  写入失败时三者都必须一致。
- 观察层：JSONL 旁路的行结构、check 词表、同一 step 的终态配对。
- 证据层：旧文件字节与旁路所报的新旧范围互相核对；记录中没有逐字稿正文
  与凭证。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import transcribe_one
from core.batch import run_batch
from core.output import OutputCountMismatchError
from engines.base import Segment, TranscriptionResult
from exceptions import TranslationError

REQUIRED_FIELDS = (
    "schema_version",
    "owner",
    "run_id",
    "attempt_id",
    "step_id",
    "check_id",
    "expected",
    "actual",
)

OLD_ORIGINAL = "旧原文内容-不应出现在本轮产物中\n"
OLD_TRANSLATION = "旧译文内容-不应出现在本轮产物中\n"
OLD_BILINGUAL = "旧对照内容-不应出现在本轮产物中\n"


# ── 夹具 ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_feedback_state():
    """每个用例从干净的旁路状态开始（进程内缓存的 recorder 也要清）。

    基线提交还没有本仓反馈适配器时，这里安静跳过，让 RED 落在行为断言上
    而不是落在 import 错误上。
    """
    try:
        from core import feedback
    except ImportError:
        yield
        return
    feedback.reset_state()
    yield
    feedback.reset_state()


@pytest.fixture
def audio_file(tmp_path):
    f = tmp_path / "meeting.mp3"
    f.write_bytes(b"\x00" * 1024)
    return f


@pytest.fixture
def engine():
    """两段间隔 5 秒（> 2 秒合并阈值），因此产生两段而不是一段。"""
    eng = MagicMock()
    eng.transcribe.return_value = TranscriptionResult(
        language="en",
        language_probability=0.95,
        duration=60.0,
        segments=[
            Segment(start=0.0, end=30.0, text="Revenue grew 30% year over year."),
            Segment(start=35.0, end=60.0, text="Gross margin improved to 21.5%."),
        ],
    )
    return eng


@pytest.fixture
def translator():
    tr = MagicMock()
    tr.model = "deepseek-v4-flash"
    tr.translate_paragraphs.return_value = ["营收同比增长30%", "毛利率提升至21.5%"]
    return tr


@pytest.fixture
def sidecar(tmp_path, monkeypatch):
    """本轮独占的旁路目的地与运行身份。"""
    out = tmp_path / "feedback" / "run-1.jsonl"
    monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(out))
    monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "run-1")
    monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "attempt-1")
    return out


class _FixedTimer:
    """确定性计时器：让启用/禁用两次对照运行的产物字节可比。"""

    def __init__(self):
        self.elapsed = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.elapsed = 1.0


@pytest.fixture
def fixed_timer(monkeypatch):
    monkeypatch.setattr("core.pipeline.Timer", _FixedTimer)
    return _FixedTimer


# ── 读取辅助 ─────────────────────────────────────────────────────


def read_rows(path: Path) -> list:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def rows_of(path: Path, step_id: str) -> list:
    return [r for r in read_rows(path) if r["step_id"] == step_id]


def row_for(rows: list, check_id: str) -> dict:
    matches = [r for r in rows if r["check_id"] == check_id]
    assert len(matches) == 1, f"期望恰好一行 {check_id}，实际 {matches}"
    return matches[0]


def only_step(path: Path) -> str:
    steps = {r["step_id"] for r in read_rows(path)}
    assert len(steps) == 1, f"期望恰好一个 step，实际 {steps}"
    return steps.pop()


def write_old_outputs(output_dir: Path, stem: str = "meeting") -> None:
    """放置上一轮的三个产物，用于陈旧输出场景。"""
    (output_dir / f"{stem}_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
    (output_dir / f"{stem}_翻译.txt").write_text(OLD_TRANSLATION, encoding="utf-8")
    (output_dir / f"{stem}_中英对照.txt").write_text(OLD_BILINGUAL, encoding="utf-8")


# ── 行结构 ───────────────────────────────────────────────────────


class TestObservationShape:
    """每行都必须满足 feedback-observation/1 的最小字段约定。"""

    def test_every_row_has_the_required_string_fields(self, engine, audio_file, tmp_output_dir, sidecar):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        rows = read_rows(sidecar)
        assert rows, "旁路启用后必须产生观察行"
        for row in rows:
            for field in REQUIRED_FIELDS:
                assert isinstance(row[field], str), f"{field} 必须是字符串: {row}"
                assert row[field], f"{field} 不得为空: {row}"
            assert row["schema_version"] == "feedback-observation/1"
            assert row["owner"] == "meeting-converter"
            assert row.get("disposition") in ("expected", "deviation", "unknown")

    def test_origin_owner_defaults_to_owner(self, engine, audio_file, tmp_output_dir, sidecar):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        for row in read_rows(sidecar):
            assert row.get("origin_owner", row["owner"]) == row["owner"]

    def test_start_row_points_at_the_terminal_check(self, engine, audio_file, tmp_output_dir, sidecar):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        rows = read_rows(sidecar)
        start = row_for(rows, "action-started")
        assert start["expected"] == "started"
        assert start["actual"] == "started"
        assert start["terminal_check_id"] == "publication-outcome"
        # 同身份的终态证明实际终态
        terminal = row_for(rows, "publication-outcome")
        assert terminal["step_id"] == start["step_id"]

    def test_observations_carry_no_transcript_body_or_credentials(
        self, engine, translator, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret-value")
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=translator)
        blob = sidecar.read_text(encoding="utf-8")
        assert "Revenue grew" not in blob
        assert "营收同比增长" not in blob
        assert "sk-secret-value" not in blob

    def test_evidence_ref_is_opaque_and_local(self, engine, audio_file, tmp_output_dir, sidecar):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        for row in read_rows(sidecar):
            reference = row.get("evidence_ref")
            assert reference, "每行观察都要带证据引用"
            assert reference.startswith("mc-output/")
            # 音频名里的主体信息留在本仓，不进入跨仓观察
            assert "meeting" not in reference

    def test_details_record_carries_no_path_no_audio_name_and_no_raw_error(
        self, engine, translator, tmp_path, tmp_output_dir, sidecar, monkeypatch
    ):
        """本仓的步骤日志也是脱敏的：没有绝对路径、音频名与原始异常正文。"""
        audio = tmp_path / "Xiaomi_Q3_Earnings_Call.mp3"
        audio.write_bytes(b"\x00" * 1024)
        monkeypatch.setattr(
            "core.pipeline.write_bilingual",
            lambda *a, **k: (_ for _ in ()).throw(OSError(f"写盘失败: {audio}")),
        )
        with pytest.raises(OSError):
            transcribe_one(
                engine, audio, tmp_output_dir, translator_obj=translator
            )

        details = sidecar.with_name(sidecar.name + ".details.jsonl")
        blob = details.read_text(encoding="utf-8")
        assert str(tmp_output_dir) not in blob
        assert str(audio) not in blob
        assert "Xiaomi" not in blob
        assert "写盘失败" not in blob
        finished = next(row for row in read_rows(details) if row["phase"] == "finished")
        assert finished["errors"] == [{"stage": "output", "role": "bilingual", "error_type": "OSError"}]


# ── 正例 ─────────────────────────────────────────────────────────


class TestOriginalOnlyMode:
    """原文模式：只请求原文，本轮原文确实是新的。"""

    def test_only_original_is_written_and_reported_current(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        result = transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        assert result is not None
        assert sorted(p.name for p in tmp_output_dir.iterdir()) == ["meeting_原文.txt"]

        rows = rows_of(sidecar, only_step(sidecar))
        requested = row_for(rows, "requested-outputs")
        assert requested["expected"] == "original_current"
        assert requested["actual"] == "original_current"
        assert requested["disposition"] == "expected"

        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "published_current"
        assert outcome["disposition"] == "expected"

        original = row_for(rows, "writer-original")
        assert original["expected"] == "committed_this_round"
        assert original["actual"] == "committed_this_round"

    def test_translation_writers_are_not_requested(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        rows = rows_of(sidecar, only_step(sidecar))
        for role in ("translated", "bilingual"):
            row = row_for(rows, f"writer-{role}")
            assert row["expected"] == "not_requested"
            assert row["actual"] == "not_requested"
            assert row["disposition"] == "expected"

    def test_engine_start_is_recorded(self, engine, audio_file, tmp_output_dir, sidecar):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        rows = rows_of(sidecar, only_step(sidecar))
        started = row_for(rows, "transcription-started")
        assert started["expected"] == "engine_started"
        assert started["actual"] == "engine_started"
        assert engine.transcribe.call_count == 1


class TestTranslationMode:
    """启用翻译：三件齐全，本轮全部是新的。"""

    def test_three_files_written_and_reported_current(
        self, engine, translator, audio_file, tmp_output_dir, sidecar
    ):
        result = transcribe_one(
            engine, audio_file, tmp_output_dir, translator_obj=translator
        )
        assert result is not None
        assert sorted(p.name for p in tmp_output_dir.iterdir()) == [
            "meeting_中英对照.txt",
            "meeting_原文.txt",
            "meeting_翻译.txt",
        ]

        rows = rows_of(sidecar, only_step(sidecar))
        requested = row_for(rows, "requested-outputs")
        assert requested["expected"] == "original_translated_bilingual_current"
        assert requested["actual"] == "original_translated_bilingual_current"
        assert requested["disposition"] == "expected"

        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "published_current"
        assert outcome["disposition"] == "expected"

        for role in ("original", "translated", "bilingual"):
            row = row_for(rows, f"writer-{role}")
            assert row["actual"] == "committed_this_round", role

        assert translator.translate_paragraphs.call_count == 1


class TestSkipExisting:
    """已有原件时跳过：引擎不启动，本轮没有新产物。"""

    def test_skip_is_a_reuse_not_a_transcription(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        (tmp_output_dir / "meeting_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
        result = transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        assert result is None
        assert engine.transcribe.call_count == 0

        rows = rows_of(sidecar, only_step(sidecar))
        started = row_for(rows, "transcription-started")
        assert started["actual"] == "engine_not_started"

        requested = row_for(rows, "requested-outputs")
        assert requested["expected"] == "reused_existing"
        assert requested["actual"] == "reused_existing"
        assert requested["disposition"] == "expected"

        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "reused_existing"
        assert outcome["disposition"] == "expected"

    def test_skipped_file_keeps_its_bytes(self, engine, audio_file, tmp_output_dir, sidecar):
        (tmp_output_dir / "meeting_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        assert (tmp_output_dir / "meeting_原文.txt").read_text(encoding="utf-8") == OLD_ORIGINAL


# ── 反例 ─────────────────────────────────────────────────────────


class TestTranslationFailureKeepsStaleOutput:
    """翻译失败：原文照常产出，译文与对照保留上一版。"""

    @pytest.fixture
    def failing_translator(self, translator):
        translator.translate_paragraphs.side_effect = TranslationError("翻译失败")
        return translator

    def test_original_is_current_and_translations_are_stale(
        self, engine, failing_translator, audio_file, tmp_output_dir, sidecar
    ):
        write_old_outputs(tmp_output_dir)
        result = transcribe_one(
            engine,
            audio_file,
            tmp_output_dir,
            translator_obj=failing_translator,
            force=True,
        )
        assert result is not None

        # 原文是本轮新产物，译文与对照仍是上一版
        assert "Revenue grew" in (tmp_output_dir / "meeting_原文.txt").read_text(encoding="utf-8")
        assert (tmp_output_dir / "meeting_翻译.txt").read_text(encoding="utf-8") == OLD_TRANSLATION
        assert (tmp_output_dir / "meeting_中英对照.txt").read_text(encoding="utf-8") == OLD_BILINGUAL

        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-original")["actual"] == "committed_this_round"
        assert row_for(rows, "writer-translated")["actual"] == "previous_kept"
        assert row_for(rows, "writer-bilingual")["actual"] == "previous_kept"

        requested = row_for(rows, "requested-outputs")
        assert requested["expected"] == "original_translated_bilingual_current"
        assert requested["actual"] == "previous_translations_only"
        assert requested["disposition"] == "deviation"

        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "published_incomplete"
        assert outcome["disposition"] == "deviation"

    def test_missing_translations_are_distinguished_from_stale_ones(
        self, engine, failing_translator, audio_file, tmp_output_dir, sidecar
    ):
        (tmp_output_dir / "meeting_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
        transcribe_one(
            engine,
            audio_file,
            tmp_output_dir,
            translator_obj=failing_translator,
            force=True,
        )
        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-translated")["actual"] == "absent"
        requested = row_for(rows, "requested-outputs")
        assert requested["actual"] == "missing_translations"
        assert requested["disposition"] == "deviation"
        # 连上一版都没有：没有可指认的旧件，根因虽同但不带 issue_key
        assert "issue_key" not in requested

    def test_mixed_stale_and_missing_translations_are_named_exactly(
        self, engine, failing_translator, audio_file, tmp_output_dir, sidecar
    ):
        """旧译文在、旧对照不在：与“全旧”与“全缺”都不同，因此有专属结果词。"""
        (tmp_output_dir / "meeting_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
        (tmp_output_dir / "meeting_翻译.txt").write_text(OLD_TRANSLATION, encoding="utf-8")
        transcribe_one(
            engine,
            audio_file,
            tmp_output_dir,
            translator_obj=failing_translator,
            force=True,
        )
        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-translated")["actual"] == "previous_kept"
        assert row_for(rows, "writer-bilingual")["actual"] == "absent"
        requested = row_for(rows, "requested-outputs")
        assert requested["actual"] == "stale_and_missing_translations"
        assert requested["disposition"] == "deviation"
        # 旧件确实留在了盘上，根因已确认
        assert requested["issue_key"] == "stale-output-success"

    def test_sidecar_range_matches_the_old_bytes_on_disk(
        self, engine, failing_translator, audio_file, tmp_output_dir, sidecar
    ):
        """侧车所报的新旧范围与磁盘上的旧文件字节互相核对。"""
        import hashlib

        write_old_outputs(tmp_output_dir)
        transcribe_one(
            engine,
            audio_file,
            tmp_output_dir,
            translator_obj=failing_translator,
            force=True,
        )
        details = sidecar.with_name(sidecar.name + ".details.jsonl")
        records = read_rows(details)
        finished = [r for r in records if r.get("phase") == "finished"]
        assert finished, "必须有一条完成的步骤日志"
        writers = {w["role"]: w for w in finished[-1]["writers"]}

        old_bytes = (tmp_output_dir / "meeting_翻译.txt").read_bytes()
        assert writers["translated"]["sha256"] == hashlib.sha256(old_bytes).hexdigest()
        assert writers["translated"]["bytes"] == len(old_bytes)
        assert writers["translated"]["this_round"] is False

        new_bytes = (tmp_output_dir / "meeting_原文.txt").read_bytes()
        assert writers["original"]["sha256"] == hashlib.sha256(new_bytes).hexdigest()
        assert writers["original"]["this_round"] is True


class TestSegmentCountMismatch:
    """段数错配：已验收的 writer 在写盘前拒绝。"""

    @pytest.fixture
    def mismatching_translator(self, translator):
        translator.translate_paragraphs.return_value = ["只有一段译文", "第二段", "第三段"]
        return translator

    def test_writer_rejects_and_nothing_translated_is_written(
        self, engine, mismatching_translator, audio_file, tmp_output_dir, sidecar
    ):
        with pytest.raises(OutputCountMismatchError):
            transcribe_one(
                engine, audio_file, tmp_output_dir, translator_obj=mismatching_translator
            )

        # 原文已写出，译文与对照一个都没有落盘
        assert (tmp_output_dir / "meeting_原文.txt").exists()
        assert not (tmp_output_dir / "meeting_翻译.txt").exists()
        assert not (tmp_output_dir / "meeting_中英对照.txt").exists()

        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-original")["actual"] == "committed_this_round"
        assert row_for(rows, "writer-translated")["actual"] == "failed"

        requested = row_for(rows, "requested-outputs")
        assert requested["actual"] == "partial_current"
        assert requested["disposition"] == "deviation"

        outcome = row_for(rows, "publication-outcome")
        # 原文已经提交，译文 writer 失败：终态是“部分提交”，不是“整体写入失败”
        assert outcome["actual"] == "published_partial"
        assert outcome["disposition"] == "deviation"

    def test_original_write_failure_is_a_total_write_failure(
        self, engine, translator, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        """一个目标都没提交时，终态才是 write_failed。"""

        def boom(*args, **kwargs):
            raise OSError("原文写盘失败")

        monkeypatch.setattr("core.pipeline.write_original", boom)
        with pytest.raises(OSError):
            transcribe_one(
                engine, audio_file, tmp_output_dir, translator_obj=translator
            )

        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-original")["actual"] == "failed"
        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "write_failed"
        assert outcome["disposition"] == "deviation"


class TestBilingualWriteFailure:
    """原文成功、对照写失败：部分目标已提交。"""

    def test_original_and_translation_survive_the_bilingual_failure(
        self, engine, translator, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        def boom(*args, **kwargs):
            raise OSError("对照写盘失败")

        monkeypatch.setattr("core.pipeline.write_bilingual", boom)
        with pytest.raises(OSError):
            transcribe_one(
                engine, audio_file, tmp_output_dir, translator_obj=translator
            )

        assert (tmp_output_dir / "meeting_原文.txt").exists()
        assert (tmp_output_dir / "meeting_翻译.txt").exists()
        assert not (tmp_output_dir / "meeting_中英对照.txt").exists()

        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-original")["actual"] == "committed_this_round"
        assert row_for(rows, "writer-translated")["actual"] == "committed_this_round"
        assert row_for(rows, "writer-bilingual")["actual"] == "failed"

        requested = row_for(rows, "requested-outputs")
        assert requested["actual"] == "partial_current"
        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "published_partial"

    def test_force_failure_keeps_previous_bytes_and_records_the_terminal_state(
        self, engine, translator, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        """force 重跑失败：旧件保持原样，终态是失败而不是成功。"""
        write_old_outputs(tmp_output_dir)

        def boom(*args, **kwargs):
            raise OSError("对照写盘失败")

        monkeypatch.setattr("core.pipeline.write_bilingual", boom)
        with pytest.raises(OSError):
            transcribe_one(
                engine,
                audio_file,
                tmp_output_dir,
                translator_obj=translator,
                force=True,
            )

        # 原文与译文是本轮新产物，对照写失败因此仍是旧字节
        assert (tmp_output_dir / "meeting_原文.txt").read_text(encoding="utf-8") != OLD_ORIGINAL
        assert (tmp_output_dir / "meeting_翻译.txt").read_text(encoding="utf-8") != OLD_TRANSLATION
        assert (tmp_output_dir / "meeting_中英对照.txt").read_text(encoding="utf-8") == OLD_BILINGUAL

        rows = rows_of(sidecar, only_step(sidecar))
        assert row_for(rows, "writer-bilingual")["actual"] == "failed"
        assert row_for(rows, "publication-outcome")["actual"] == "published_partial"
        assert row_for(rows, "requested-outputs")["actual"] == "partial_current"


class TestTranscriptionFailure:
    """引擎异常：本轮没有任何产物。"""

    def test_engine_failure_is_terminal_and_writes_nothing(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        engine.transcribe.side_effect = RuntimeError("Whisper crashed")
        with pytest.raises(RuntimeError):
            transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)

        assert list(tmp_output_dir.iterdir()) == []
        rows = rows_of(sidecar, only_step(sidecar))
        requested = row_for(rows, "requested-outputs")
        assert requested["actual"] == "transcription_failed"
        assert requested["disposition"] == "deviation"
        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "transcription_failed"

    def test_interrupted_run_keeps_the_terminal_state_unknown(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        """被中止时没有可信终态：终态保留 unknown，不编造成功。"""
        engine.transcribe.side_effect = KeyboardInterrupt("作业被中止")
        with pytest.raises(KeyboardInterrupt):
            transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)

        rows = rows_of(sidecar, only_step(sidecar))
        outcome = row_for(rows, "publication-outcome")
        assert outcome["actual"] == "unknown"
        assert outcome["disposition"] == "unknown"
        requested = row_for(rows, "requested-outputs")
        assert requested["actual"] == "unknown"
        assert requested["disposition"] == "unknown"
        # 本仓不因此重跑转录
        assert engine.transcribe.call_count == 1


# ── 旁路本身 ─────────────────────────────────────────────────────


class TestSidecarIsOptional:
    """旁路是可选的：禁用不产生文件，失败不改业务结果。"""

    def test_disabled_sidecar_writes_no_file(
        self, engine, audio_file, tmp_output_dir, monkeypatch
    ):
        monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
        target = tmp_output_dir.parent / "feedback.jsonl"
        result = transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        assert result is not None
        assert not target.exists()
        assert not (tmp_output_dir.parent / "feedback.jsonl.details.jsonl").exists()
        assert sorted(p.name for p in tmp_output_dir.iterdir()) == ["meeting_原文.txt"]

    def test_unwritable_sidecar_keeps_the_business_outcome(
        self, engine, translator, audio_file, tmp_output_dir, tmp_path, monkeypatch
    ):
        """旁路写不进去时，返回值、产物与调用次数与可写时一致。"""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(blocked))
        result = transcribe_one(
            engine, audio_file, tmp_output_dir, translator_obj=translator
        )
        assert result is not None
        assert sorted(p.name for p in tmp_output_dir.iterdir()) == [
            "meeting_中英对照.txt",
            "meeting_原文.txt",
            "meeting_翻译.txt",
        ]
        assert engine.transcribe.call_count == 1
        assert translator.translate_paragraphs.call_count == 1

    def test_sidecar_write_failure_is_reported_on_the_local_diagnostic_channel(
        self, engine, audio_file, tmp_output_dir, tmp_path, monkeypatch, caplog
    ):
        """旁路写不进去时，只在本仓已有的本地诊断通道上报告。"""
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(blocked))
        with caplog.at_level("WARNING"):
            transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)

        messages = [r.getMessage() for r in caplog.records]
        assert any("反馈旁路" in m for m in messages), messages

    def test_malformed_sidecar_path_does_not_break_the_run(
        self, engine, audio_file, tmp_output_dir, monkeypatch
    ):
        """目的地不合法时旁路不可用，但主任务照常完成。"""
        monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", "C:\\")
        result = transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        assert result is not None
        assert (tmp_output_dir / "meeting_原文.txt").exists()
        assert engine.transcribe.call_count == 1

    def test_sidecar_latency_does_not_enter_the_published_timing(
        self, engine, translator, audio_file, tmp_output_dir, monkeypatch
    ):
        """旁路自己的写入耗时不进被发布的耗时，因此不改产物字节。"""
        import time as _time

        # 这条是修复后的回归护栏，不是基线缺陷的复现：基线还没有本仓反馈
        # 适配器，因此跳过而不是因 import 失败。
        feedback = pytest.importorskip("core.feedback")

        delay = 0.2

        def slow_sink(line):
            _time.sleep(delay)

        real_from_env = feedback.recorder_from_env

        def patched(environ=None):
            out = real_from_env(environ)
            if out is not None:
                out._sink = slow_sink
            return out

        monkeypatch.setattr("core.feedback.recorder_from_env", patched)
        monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(tmp_output_dir.parent / "slow.jsonl"))
        monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "run-1")
        monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "attempt-1")

        result = transcribe_one(
            engine, audio_file, tmp_output_dir, translator_obj=translator
        )
        # 旁路写了 8 行，每行阻塞 0.2 秒；若写发生在计时区间内，
        # 总耗时会是秒级。
        assert result is not None
        assert result["elapsed"] < delay, result["elapsed"]

    def test_run_id_is_stable_without_the_host_supplied_identity(
        self, engine, tmp_path, monkeypatch
    ):
        """宿主不给运行身份时，同一进程的一批文件属于同一个运行。"""
        monkeypatch.delenv("RESEARCH_FEEDBACK_RUN_ID", raising=False)
        monkeypatch.delenv("RESEARCH_FEEDBACK_ATTEMPT_ID", raising=False)
        sidecar = tmp_path / "run.jsonl"
        monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(sidecar))

        out = tmp_path / "out"
        out.mkdir()
        first = tmp_path / "a.mp3"
        second = tmp_path / "b.mp3"
        first.write_bytes(b"\x00" * 1024)
        second.write_bytes(b"\x00" * 1024)
        transcribe_one(engine, first, out, translator_obj=None)
        transcribe_one(engine, second, out, translator_obj=None)

        runs = {r["run_id"] for r in read_rows(sidecar)}
        assert len(runs) == 1, runs

    def test_enabled_and_disabled_runs_agree_on_everything_business(
        self, engine, translator, tmp_path, monkeypatch, fixed_timer, caplog
    ):
        """固定计时器后，启用与禁用两次运行的返回值、日志与产物字节一致。"""
        audio = tmp_path / "meeting.mp3"
        audio.write_bytes(b"\x00" * 1024)

        def run(enabled: bool):
            out = tmp_path / ("out-enabled" if enabled else "out-disabled")
            out.mkdir()
            if enabled:
                monkeypatch.setenv(
                    "RESEARCH_FEEDBACK_OUT", str(tmp_path / "enabled.jsonl")
                )
                monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "run-1")
                monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "attempt-1")
            else:
                monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
            with caplog.at_level("INFO"):
                result = transcribe_one(
                    engine, audio, out, translator_obj=translator
                )
            # 输出目录本来就随对照而变：按同一条规则对齐后再比实质内容。
            records = [
                (r.levelname, r.getMessage().replace(str(out), "<OUT>"))
                for r in caplog.records
            ]
            caplog.clear()
            files = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
            return result, records, files

        result_enabled, log_enabled, files_enabled = run(True)
        result_disabled, log_disabled, files_disabled = run(False)

        assert result_enabled == result_disabled
        assert log_enabled == log_disabled
        assert files_enabled == files_disabled

    def test_three_diagnostic_settings_agree_on_the_business_outcome(
        self, engine, translator, tmp_path, monkeypatch, fixed_timer
    ):
        """启用、禁用、写入失败三种诊断设置：返回值、产物与调用次数一致。"""
        audio = tmp_path / "meeting.mp3"
        audio.write_bytes(b"\x00" * 1024)
        blocked = tmp_path / "blocked"
        blocked.mkdir()

        def run(setting: str):
            out = tmp_path / ("out-" + setting)
            out.mkdir()
            if setting == "disabled":
                monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
            elif setting == "enabled":
                monkeypatch.setenv(
                    "RESEARCH_FEEDBACK_OUT", str(tmp_path / "enabled.jsonl")
                )
                monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "run-1")
                monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "attempt-1")
            else:
                monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(blocked))
            engine.transcribe.reset_mock()
            translator.translate_paragraphs.reset_mock()
            result = transcribe_one(engine, audio, out, translator_obj=translator)
            files = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
            return (
                result,
                files,
                engine.transcribe.call_count,
                translator.translate_paragraphs.call_count,
            )

        enabled = run("enabled")
        disabled = run("disabled")
        write_failure = run("write-failure")

        assert enabled == disabled == write_failure
        assert enabled[2] == enabled[3] == 1


# ── 身份与去重 ───────────────────────────────────────────────────


class TestObservationIdentity:
    def test_two_same_named_inputs_are_distinguishable(
        self, engine, tmp_path, sidecar
    ):
        first_dir = tmp_path / "batch-a"
        second_dir = tmp_path / "batch-b"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "meeting.mp3"
        second = second_dir / "meeting.mp3"
        first.write_bytes(b"\x00" * 1024)
        second.write_bytes(b"\x00" * 1024)

        # 两个来源各自一个输出目录：两次都是真实转录，不是第二次命中跳过。
        first_out = tmp_path / "out-a"
        second_out = tmp_path / "out-b"
        first_out.mkdir()
        second_out.mkdir()
        transcribe_one(engine, first, first_out, translator_obj=None)
        transcribe_one(engine, second, second_out, translator_obj=None)

        assert engine.transcribe.call_count == 2
        rows = read_rows(sidecar)
        steps = {r["step_id"] for r in rows}
        assert len(steps) == 2, "同名不同来源的音频必须可区分"
        for step in steps:
            step_rows = rows_of(sidecar, step)
            assert row_for(step_rows, "transcription-started")["actual"] == "engine_started"
            assert (
                row_for(step_rows, "requested-outputs")["actual"] == "original_current"
            )

    def test_reuse_has_its_own_step_under_the_same_attempt(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        first_rows = read_rows(sidecar)
        assert transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None) is None
        assert engine.transcribe.call_count == 1

        rows = read_rows(sidecar)
        assert rows[: len(first_rows)] == first_rows
        starts = [row for row in rows if row["check_id"] == "action-started"]
        terminal = [row for row in rows if row["check_id"] == "publication-outcome"]
        assert len({row["step_id"] for row in starts}) == 2
        assert [row["step_id"] for row in starts] == [row["step_id"] for row in terminal]
        assert [row["actual"] for row in terminal] == ["published_current", "reused_existing"]
        assert len({row["evidence_ref"] for row in terminal}) == 1
        assert {row["attempt_id"] for row in terminal} == {"attempt-1"}
        assert len(rows) == len({(row["step_id"], row["check_id"]) for row in rows})

    def test_reading_an_old_sidecar_does_not_increase_call_counts(
        self, engine, translator, audio_file, tmp_output_dir, sidecar
    ):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=translator)
        assert engine.transcribe.call_count == 1
        assert translator.translate_paragraphs.call_count == 1

        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=translator)
        assert engine.transcribe.call_count == 1
        assert translator.translate_paragraphs.call_count == 1


class TestDifferentLanguages:
    def test_two_languages_are_independent_observations(
        self, tmp_path, sidecar
    ):
        out = tmp_path / "out"
        out.mkdir()

        english = MagicMock()
        english.transcribe.return_value = TranscriptionResult(
            language="en",
            language_probability=0.95,
            duration=60.0,
            segments=[Segment(start=0.0, end=30.0, text="Revenue grew 30%.")],
        )
        chinese = MagicMock()
        chinese.transcribe.return_value = TranscriptionResult(
            language="zh",
            language_probability=0.99,
            duration=60.0,
            segments=[Segment(start=0.0, end=30.0, text="营收同比增长30%。")],
        )

        first = tmp_path / "a.mp3"
        second = tmp_path / "b.mp3"
        first.write_bytes(b"\x00" * 1024)
        second.write_bytes(b"\x00" * 1024)

        transcribe_one(english, first, out, translator_obj=None)
        transcribe_one(chinese, second, out, translator_obj=None)

        rows = read_rows(sidecar)
        steps = {r["step_id"] for r in rows}
        assert len(steps) == 2
        # 两份样本各自产出自己的原文文件
        assert (out / "a_原文.txt").exists()
        assert (out / "b_原文.txt").exists()
        assert "Revenue grew" in (out / "a_原文.txt").read_text(encoding="utf-8")
        assert "营收同比增长" in (out / "b_原文.txt").read_text(encoding="utf-8")


# ── 公开入口的端到端 ─────────────────────────────────────────────


class TestPublicEntryIntegration:
    def test_batch_entry_writes_text_and_jsonl(self, tmp_path, sidecar):
        """从公开批处理入口走到真实文本写入与 JSONL。"""
        out = tmp_path / "out"
        out.mkdir()
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        first = audio_dir / "one.mp3"
        second = audio_dir / "two.mp3"
        first.write_bytes(b"\x00" * 1024)
        second.write_bytes(b"\x00" * 1024)

        engine = MagicMock()
        engine.transcribe.return_value = TranscriptionResult(
            language="en",
            language_probability=0.95,
            duration=60.0,
            segments=[Segment(start=0.0, end=30.0, text="Revenue grew 30%.")],
        )
        translator = MagicMock()
        translator.model = "deepseek-v4-flash"
        translator.translate_paragraphs.return_value = ["营收同比增长30%"]

        stats = run_batch(
            engine,
            [first, second],
            out,
            translator_obj=translator,
        )
        assert stats["processed"] == 2
        assert stats["failures"] == 0

        produced = sorted(p.name for p in out.iterdir())
        assert produced == [
            "one_中英对照.txt",
            "one_原文.txt",
            "one_翻译.txt",
            "two_中英对照.txt",
            "two_原文.txt",
            "two_翻译.txt",
        ]
        assert "Revenue grew 30%" in (out / "one_原文.txt").read_text(encoding="utf-8")
        assert "营收同比增长30%" in (out / "one_翻译.txt").read_text(encoding="utf-8")

        rows = read_rows(sidecar)
        steps = {r["step_id"] for r in rows}
        assert len(steps) == 2
        for step in steps:
            step_rows = rows_of(sidecar, step)
            requested = row_for(step_rows, "requested-outputs")
            assert requested["actual"] == "original_translated_bilingual_current"
            assert row_for(step_rows, "publication-outcome")["actual"] == "published_current"

    def test_exception_text_stays_out_of_the_feedback_details(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        secret_marker = "token=fake-only-value private-transcript"
        failure = RuntimeError(secret_marker)
        engine.transcribe.side_effect = failure
        with pytest.raises(RuntimeError) as raised:
            transcribe_one(engine, audio_file, tmp_output_dir)
        assert raised.value is failure
        details = sidecar.with_name(sidecar.name + ".details.jsonl")
        assert secret_marker not in details.read_text(encoding="utf-8")
        finished = next(row for row in read_rows(details) if row["phase"] == "finished")
        assert finished["errors"] == [{"stage": "transcription", "role": None, "error_type": "RuntimeError"}]

    def test_truncated_sidecar_tail_cannot_consume_the_next_start(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        sidecar.parent.mkdir()
        fragment = b'{"truncated":'
        sidecar.write_bytes(fragment)
        detail_path = sidecar.with_name(sidecar.name + ".details.jsonl")
        detail_path.write_bytes(fragment)

        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)

        old, *lines = sidecar.read_bytes().splitlines()
        assert old == fragment
        observations = [json.loads(line) for line in lines]
        assert observations[0]["check_id"] == "action-started"
        assert observations[-1]["check_id"] == "publication-outcome"
        old, *lines = detail_path.read_bytes().splitlines()
        assert old == fragment
        details = {row["details_id"] for row in map(json.loads, lines)}
        assert all(row["details_ref"] in details for row in observations)

    def test_output_directory_is_not_an_older_translation(
        self, engine, translator, audio_file, tmp_output_dir, sidecar
    ):
        (tmp_output_dir / "meeting_翻译.txt").mkdir()
        translator.translate_paragraphs.side_effect = TranslationError("offline provider failure")

        assert transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=translator) is not None

        rows = rows_of(sidecar, only_step(sidecar))
        outputs = row_for(rows, "requested-outputs")
        assert outputs["actual"] == "missing_translations"
        assert "issue_key" not in outputs

    @pytest.mark.parametrize("enabled", [False, True])
    def test_optional_probe_error_cannot_turn_reuse_into_business_failure(
        self, enabled, engine, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        write_old_outputs(tmp_output_dir)
        if not enabled:
            monkeypatch.delenv("RESEARCH_FEEDBACK_OUT")
        original_stat = Path.stat
        probes = []

        def stat(path, *args, **kwargs):
            if path == tmp_output_dir / "meeting_翻译.txt":
                probes.append(path)
                raise PermissionError("unreadable optional output")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat)
        assert transcribe_one(engine, audio_file, tmp_output_dir) is None
        engine.transcribe.assert_not_called()
        if enabled:
            assert len(probes) == 1
            details = sidecar.with_name(sidecar.name + ".details.jsonl")
            finished = next(row for row in read_rows(details) if row["phase"] == "finished")
            assert finished["reused_outputs"]["translated"] is None
            assert row_for(read_rows(sidecar), "publication-outcome")["actual"] == "reused_existing"
        else:
            assert not probes
            assert not sidecar.exists()

    def test_disabled_observation_never_reopens_committed_output(
        self, engine, audio_file, tmp_output_dir, monkeypatch
    ):
        monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
        native_open = Path.open
        probes = []

        def open_output(path, mode="r", *args, **kwargs):
            if path == tmp_output_dir / "meeting_原文.txt" and mode == "rb":
                probes.append(path)
            return native_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", open_output)
        assert transcribe_one(engine, audio_file, tmp_output_dir) is not None
        assert (tmp_output_dir / "meeting_原文.txt").is_file()
        assert not probes

    def test_details_ref_is_absent_when_the_details_never_landed(self, tmp_path):
        """details 写不进去时不写 details_ref：不留下悬挂引用。"""
        from core.feedback import FeedbackRecorder

        out = tmp_path / "run.jsonl"

        def refuse(line):
            raise OSError("details 写不进去")

        recorder = FeedbackRecorder(
            out, run_id="run-1", attempt_id="a1", details_sink=refuse
        )
        wrote = recorder.record(
            step_id="meeting-operation/x",
            check_id="action-started",
            expected="started",
            actual="started",
            details={"phase": "started", "input_id": "x"},
        )
        assert wrote
        rows = read_rows(out)
        assert len(rows) == 1
        assert "details_ref" not in rows[0], rows[0]

    def test_details_ref_is_present_when_the_details_did_land(self, tmp_path):
        """details 正常落盘时才有 details_ref。"""
        from core.feedback import FeedbackRecorder

        out = tmp_path / "run.jsonl"
        recorder = FeedbackRecorder(out, run_id="run-1", attempt_id="a1")
        recorder.record(
            step_id="meeting-operation/x",
            check_id="action-started",
            expected="started",
            actual="started",
            details={"phase": "started", "input_id": "x"},
        )
        rows = read_rows(out)
        assert "details_ref" in rows[0]
        details = out.with_name(out.name + ".details.jsonl")
        assert details.exists()
        assert rows[0]["details_ref"] == read_rows(details)[0]["details_id"]

    def test_failure_path_records_real_elapsed_times(
        self, engine, translator, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        """失败路径上耗时照样记账：消费方能区分立刻失败与干了一会儿才失败。"""
        import time as _time

        def slow_transcribe(*args, **kwargs):
            _time.sleep(0.2)
            raise RuntimeError("引擎干了一会儿才失败")

        engine.transcribe.side_effect = slow_transcribe
        with pytest.raises(RuntimeError):
            transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=translator)

        details = sidecar.with_name(sidecar.name + ".details.jsonl")
        finished = [r for r in read_rows(details) if r.get("phase") == "finished"]
        assert finished
        metrics = finished[-1]["metrics"]
        assert metrics["stt_elapsed"] >= 0.15, metrics
        assert metrics["total_elapsed"] >= 0.15, metrics

    def test_details_metrics_are_truthful_on_a_failure_path(
        self, engine, translator, audio_file, tmp_output_dir, sidecar, monkeypatch
    ):
        """失败路径上的步骤日志仍然说得清这一轮做了什么，不是一片 0。"""

        def boom(*args, **kwargs):
            raise OSError("对照写盘失败")

        monkeypatch.setattr("core.pipeline.write_bilingual", boom)
        with pytest.raises(OSError):
            transcribe_one(
                engine, audio_file, tmp_output_dir, translator_obj=translator
            )

        details = sidecar.with_name(sidecar.name + ".details.jsonl")
        finished = [r for r in read_rows(details) if r.get("phase") == "finished"]
        assert finished
        metrics = finished[-1]["metrics"]
        assert metrics["paragraphs"] == 2
        assert metrics["text_length"] > 0
        assert metrics["duration"] == 60.0

    def test_cost_is_unknown_without_a_usage_receipt(
        self, engine, audio_file, tmp_output_dir, sidecar
    ):
        transcribe_one(engine, audio_file, tmp_output_dir, translator_obj=None)
        rows = rows_of(sidecar, only_step(sidecar))
        cost = row_for(rows, "cost-receipt")
        assert cost["expected"] == "cost_unknown"
        assert cost["actual"] == "cost_unknown"
        assert cost["disposition"] == "unknown"


def test_committed_output_fingerprint_is_not_taken_from_a_later_writer(
    engine, audio_file, tmp_output_dir, sidecar, monkeypatch
):
    from hashlib import sha256

    from core.output import write_original

    committed = []

    def replaced_after_commit(path, *args, **kwargs):
        result = write_original(path, *args, **kwargs)
        committed.append(path.read_bytes())
        path.write_bytes(b"subsequent writer to the same destination")
        return result

    monkeypatch.setattr("core.pipeline.write_original", replaced_after_commit)
    transcribe_one(engine, audio_file, tmp_output_dir)
    details = sidecar.with_name(sidecar.name + ".details.jsonl")
    finished = next(row for row in read_rows(details) if row["phase"] == "finished")
    written, = [row for row in finished["writers"] if row["role"] == "original"]
    assert written["sha256"] == sha256(committed[0]).hexdigest()
    assert written["bytes"] == len(committed[0])
    assert written["fingerprint_source"] == "committed_writer"
