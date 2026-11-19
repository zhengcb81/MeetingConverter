"""在基线提交上实际跑出根因收据（本卡收据，不是手写结论）。

用法（在仓库根目录）::

    python -B docs/plans/f2-mc-output/receipts/make_base_receipt.py

脚本在系统临时目录里开一个基线提交 ``b43a76a`` 的 git worktree，跑两件事并把
真实输出写回本目录：

- ``base-commit-fixture-failures.txt``：基线上 ``tests/test_transcribe_integration.py``
  的四个真实失败（夹具把两段合并成一段，已验收的 writer 按契约拒绝）。
- ``base-commit-stale-output.txt``：基线上翻译失败时，进程退出 0、译文文件保留
  上一版字节，而仓里没有任何机制能说明这一点（基线没有反馈适配器）。

跑完脚本会移除临时 worktree 与临时目录。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
BASE = "b43a76a"

#: pytest 的临时根与其下的绝对路径：收据里不留机器的绝对路径。
_PYTEST_TMP = re.compile(r"[A-Za-z]:[\\/][^\s'\"\n]*pytest-of-[^\s'\"\n]*")
_ABS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"\n]*")


def scrub(text: str) -> str:
    """把收据里的机器绝对路径换成占位词。"""
    text = _PYTEST_TMP.sub("<PYTEST_TMP>", text)
    return _ABS_PATH.sub("<ABS_PATH>", text)


FIXTURE_COMMAND = (
    "python -B -m pytest -q -o addopts= -p no:cacheprovider "
    "tests/test_transcribe_integration.py"
)

STALE_PROBE = """
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, {root!r})

from core import transcribe_one
from engines.base import Segment, TranscriptionResult
from exceptions import TranslationError

out = Path({out!r})
out.mkdir(parents=True, exist_ok=True)
audio = Path({audio!r})
audio.write_bytes(b"\\x00" * 1024)

(out / "meeting_原文.txt").write_text("旧原文\\n", encoding="utf-8")
(out / "meeting_翻译.txt").write_text("旧译文\\n", encoding="utf-8")
(out / "meeting_中英对照.txt").write_text("旧对照\\n", encoding="utf-8")

engine = MagicMock()
engine.transcribe.return_value = TranscriptionResult(
    language="en", language_probability=0.95, duration=60.0,
    segments=[Segment(start=0.0, end=30.0, text="Revenue grew 30%.")],
)
translator = MagicMock()
translator.model = "deepseek-v4-flash"
translator.translate_paragraphs.side_effect = TranslationError("翻译失败")

result = transcribe_one(engine, audio, out, translator_obj=translator, force=True)
print("return_value_is_not_none:", result is not None)
print("translation_file_kept_previous_bytes:",
      (out / "meeting_翻译.txt").read_text(encoding="utf-8") == "旧译文\\n")
print("bilingual_file_kept_previous_bytes:",
      (out / "meeting_中英对照.txt").read_text(encoding="utf-8") == "旧对照\\n")
print("original_is_this_round:",
      "Revenue grew 30%" in (out / "meeting_原文.txt").read_text(encoding="utf-8"))
print("sidecar_capability_in_repo:", (Path({root!r}) / "core" / "feedback.py").exists())
print("process_exit_code: 0 (no exception raised)")
"""


def run(command, cwd, env=None):
    completed = subprocess.run(
        command, cwd=str(cwd), env=env, capture_output=True, text=True
    )
    return completed


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mc-base-receipt-"))
    worktree = tmp / "base"
    try:
        created = run(
            ["git", "worktree", "add", "--detach", str(worktree), BASE], REPO_ROOT
        )
        if created.returncode != 0:
            print(created.stderr)
            return 1

        fixture = run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-o", "addopts=",
             "-p", "no:cacheprovider", "tests/test_transcribe_integration.py"],
            worktree,
        )
        header = (
            f"# 基线 {BASE} 上 tests/test_transcribe_integration.py 的真实失败\n"
            f"# 命令：{FIXTURE_COMMAND}\n"
            f"# worktree：git worktree add --detach <TMP>/base {BASE}\n\n"
        )
        (HERE / "base-commit-fixture-failures.txt").write_text(
            header + scrub(fixture.stdout + fixture.stderr),
            encoding="utf-8",
            newline="\n",
        )
        print("fixture failures:", fixture.stdout.strip().splitlines()[-1])

        probe_root = tmp / "probe"
        probe_root.mkdir()
        probe = STALE_PROBE.format(
            root=str(worktree), out=str(probe_root / "out"), audio=str(probe_root / "meeting.mp3")
        )
        stale = run([sys.executable, "-c", probe], worktree)
        header = (
            f"# 基线 {BASE} 上翻译失败时的真实行为：退出 0、译文保留上一版字节\n"
            "# 命令：在基线 worktree 里运行 core.transcribe_one，翻译器抛 TranslationError\n"
            "# 说明：基线没有任何反馈适配器，因此外部无法分辨这一轮是否产出了译文。\n\n"
        )
        (HERE / "base-commit-stale-output.txt").write_text(
            header + scrub(stale.stdout + stale.stderr),
            encoding="utf-8",
            newline="\n",
        )
        print(stale.stdout.strip())
        return 0
    finally:
        run(
            ["git", "worktree", "remove", "--force", str(worktree)], REPO_ROOT
        )
        shutil.rmtree(tmp, ignore_errors=True)
        print("cleaned", tmp)


if __name__ == "__main__":
    raise SystemExit(main())
