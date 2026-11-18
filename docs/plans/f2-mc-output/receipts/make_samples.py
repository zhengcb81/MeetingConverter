"""从公开入口实际跑出旁路 JSONL 样本（本卡收据，不是手写协议样例）。

用法（在仓库根目录）::

    python -B docs/plans/f2-mc-output/receipts/make_samples.py

脚本用合成音频与 stub 引擎/翻译器走真实公开入口 ``core.transcribe_one``，
把三个场景的实际旁路输出写到本目录：

- ``sample-success.jsonl``      —— 翻译模式，三件齐全，本轮全部是新的。
- ``sample-stale.jsonl``        —— 翻译失败，原文是本轮新产物，译文保留上一版。
- ``sample-started-only.jsonl`` —— 引擎启动后被中止：只有开始行，没有可信终态。

另外 ``sample-replay.jsonl`` 演示重放：同一输入重投沿用原 step_id，且不新增
引擎/翻译调用。

运行不接触网络、凭证或真实音频；所有临时文件都写在本脚本专属的临时目录里，
结束时清理。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core import transcribe_one  # noqa: E402
from engines.base import Segment, TranscriptionResult  # noqa: E402
from exceptions import TranslationError  # noqa: E402

HERE = Path(__file__).resolve().parent

OLD_ORIGINAL = "旧原文内容\n"
OLD_TRANSLATION = "旧译文内容\n"
OLD_BILINGUAL = "旧对照内容\n"


def make_engine() -> MagicMock:
    engine = MagicMock()
    engine.transcribe.return_value = TranscriptionResult(
        language="en",
        language_probability=0.95,
        duration=60.0,
        segments=[
            Segment(start=0.0, end=30.0, text="Revenue grew 30% year over year."),
            Segment(start=35.0, end=60.0, text="Gross margin improved to 21.5%."),
        ],
    )
    return engine


def make_translator() -> MagicMock:
    translator = MagicMock()
    translator.model = "deepseek-v4-flash"
    translator.translate_paragraphs.return_value = ["营收同比增长30%", "毛利率提升至21.5%"]
    return translator


def use_sidecar(path: Path, run_id: str, attempt_id: str) -> None:
    os.environ["RESEARCH_FEEDBACK_OUT"] = str(path)
    os.environ["RESEARCH_FEEDBACK_RUN_ID"] = run_id
    os.environ["RESEARCH_FEEDBACK_ATTEMPT_ID"] = attempt_id


def read_rows(path: Path) -> list:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def scenario_success(root: Path) -> Path:
    """翻译模式，三件齐全。"""
    sidecar = root / "success.jsonl"
    use_sidecar(sidecar, "mc-sample-success", "attempt-1")
    out = root / "out-success"
    out.mkdir()
    audio = root / "success.mp3"
    audio.write_bytes(b"\x00" * 1024)
    transcribe_one(make_engine(), audio, out, translator_obj=make_translator())
    return sidecar


def scenario_stale(root: Path) -> Path:
    """翻译失败：原文是本轮新产物，译文与对照保留上一版。"""
    sidecar = root / "stale.jsonl"
    use_sidecar(sidecar, "mc-sample-stale", "attempt-1")
    out = root / "out-stale"
    out.mkdir()
    audio = root / "stale.mp3"
    audio.write_bytes(b"\x00" * 1024)
    (out / "stale_原文.txt").write_text(OLD_ORIGINAL, encoding="utf-8")
    (out / "stale_翻译.txt").write_text(OLD_TRANSLATION, encoding="utf-8")
    (out / "stale_中英对照.txt").write_text(OLD_BILINGUAL, encoding="utf-8")
    translator = make_translator()
    translator.translate_paragraphs.side_effect = TranslationError("翻译失败")
    transcribe_one(
        make_engine(), audio, out, translator_obj=translator, force=True
    )
    return sidecar


def scenario_started_only(root: Path) -> Path:
    """硬停止：只有开始行，没有可信终态。

    子进程在转录途中用 ``os._exit`` 硬退出：``finally`` 不执行，缓冲里的行
    来不及落盘，旁路因此只剩一条已经写下的开始行——这正是“停止后只有开始行
    且没有可信终态”的真实形态。
    """
    sidecar = root / "started-only.jsonl"
    out = root / "out-started"
    out.mkdir()
    audio = root / "started.mp3"
    audio.write_bytes(b"\x00" * 1024)
    child = (
        "import os, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "from unittest.mock import MagicMock\n"
        "from core import transcribe_one\n"
        "engine = MagicMock()\n"
        "def stop(*args, **kwargs):\n"
        "    os._exit(9)\n"
        "engine.transcribe.side_effect = stop\n"
        f"transcribe_one(engine, Path({str(audio)!r}), Path({str(out)!r}), "
        "translator_obj=None)\n"
    )
    environment = dict(os.environ)
    environment["RESEARCH_FEEDBACK_OUT"] = str(sidecar)
    environment["RESEARCH_FEEDBACK_RUN_ID"] = "mc-sample-started-only"
    environment["RESEARCH_FEEDBACK_ATTEMPT_ID"] = "attempt-1"
    completed = subprocess.run(
        [sys.executable, "-c", child], env=environment, capture_output=True
    )
    if completed.returncode != 9:
        raise SystemExit(
            f"硬停止子进程意外退出：{completed.returncode}\n{completed.stderr.decode()}"
        )
    return sidecar


def scenario_replay(root: Path) -> Path:
    """重放：同一输入重投沿用原 step_id，且不新增引擎/翻译调用。"""
    sidecar = root / "replay.jsonl"
    use_sidecar(sidecar, "mc-sample-replay", "attempt-1")
    out = root / "out-replay"
    out.mkdir()
    audio = root / "replay.mp3"
    audio.write_bytes(b"\x00" * 1024)
    engine = make_engine()
    translator = make_translator()
    transcribe_one(engine, audio, out, translator_obj=translator)
    first = len(read_rows(sidecar))
    transcribe_one(engine, audio, out, translator_obj=translator)
    second = len(read_rows(sidecar))
    print(
        f"replay: engine_calls={engine.transcribe.call_count} "
        f"translator_calls={translator.translate_paragraphs.call_count} "
        f"rows_before={first} rows_after={second}"
    )
    return sidecar


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="mc-samples-"))
    try:
        produced = {
            "sample-success.jsonl": scenario_success(root),
            "sample-stale.jsonl": scenario_stale(root),
            "sample-started-only.jsonl": scenario_started_only(root),
            "sample-replay.jsonl": scenario_replay(root),
        }
        for name, source in produced.items():
            target = HERE / name
            shutil.copyfile(source, target)
            print(f"wrote {target} ({len(read_rows(target))} rows)")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        print(f"cleaned {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
