"""在基线提交上跑出 F4 新测试的真实 RED 收据。

用法（在仓库根目录）::

    python -B docs/plans/f2-mc-output/receipts/make_f4_red_receipt.py

脚本在系统临时目录里开一个基线提交的 git worktree，把本卡的新测试
``tests/test_f4_ordinary_failures.py`` 与子进程运行器
``tests/f4_child_runner.py`` 放回基线（基线没有默认交付、没有翻译意图/
回退投影），跑真实 pytest，把输出写成 ``red-f4-ordinary-failures.txt``。
基线上这些用例必须因**行为**而失败——普通入口失败时一行观察都不会产生。

跑完脚本会移除临时 worktree 与临时目录；收据里不留机器绝对路径。
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
BASE = "101124f"
TEST_FILES = (
    Path("tests/test_f4_ordinary_failures.py"),
    Path("tests/f4_child_runner.py"),
)

#: pytest 的临时根与其下的绝对路径：收据里不留机器的绝对路径。
_PYTEST_TMP = re.compile(r"[A-Za-z]:[\\/][^\s'\"\n]*pytest-of-[^\s'\"\n]*")
_ABS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"\n]*")


def scrub(text: str) -> str:
    """把收据里的机器绝对路径换成占位词。"""
    text = _PYTEST_TMP.sub("<PYTEST_TMP>", text)
    return _ABS_PATH.sub("<ABS_PATH>", text)


HEADER = f"""# RED 收据 —— tests/test_f4_ordinary_failures.py 在实现之前（基线 {BASE}）的真实失败
#
# 复现命令（在仓库根目录）：
#   python -B docs/plans/f2-mc-output/receipts/make_f4_red_receipt.py
#
# 手工等价步骤：
#   git worktree add --detach <TMP>/red-f4 {BASE}
#   cp tests/test_f4_ordinary_failures.py tests/f4_child_runner.py <TMP>/red-f4/tests/
#   cd <TMP>/red-f4 && python -B -m pytest -q -o addopts= -p no:cacheprovider \\
#       tests/test_f4_ordinary_failures.py
#   git worktree remove --force <TMP>/red-f4
#
# 说明：基线提交的普通 CLI 没有默认交付，也没有翻译意图/引擎回退投影，
# 因此这些用例因“一行观察都没有产生/默认交付不存在”而失败（对应审计
# failure-coverage-20261121 第 23/24 行），不是因 import 错误失败。
#
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mc-red-f4-"))
    worktree = tmp / "red-f4"
    try:
        created = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), BASE],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        if created.returncode != 0:
            print(created.stderr)
            return 1

        for relative in TEST_FILES:
            destination = worktree / relative
            destination.write_bytes((REPO_ROOT / relative).read_bytes())

        run = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-o", "addopts=",
             "-p", "no:cacheprovider", str(TEST_FILES[0])],
            cwd=str(worktree), capture_output=True, text=True,
        )
        output = run.stdout + run.stderr
        receipt = "\n".join(line.rstrip() for line in scrub(output).splitlines()) + "\n"
        (HERE / "red-f4-ordinary-failures.txt").write_text(
            HEADER + receipt, encoding="utf-8", newline="\n"
        )
        print(output.strip().splitlines()[-1])
        return 0
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        shutil.rmtree(tmp, ignore_errors=True)
        print("cleaned", tmp)


if __name__ == "__main__":
    raise SystemExit(main())
