"""在基线提交上跑出本卡新测试的真实 RED 收据。

用法（在仓库根目录）::

    python -B docs/plans/f2-mc-output/receipts/make_red_receipt.py

脚本在系统临时目录里开一个基线提交 ``b43a76a`` 的 git worktree，把本卡的新测试
``tests/test_output_feedback.py`` 放回基线（基线没有 ``core/feedback.py``），跑
真实 pytest，把输出写成 ``red-output-feedback.txt``。基线上这些用例必须因
**行为**而失败——基线没有反馈旁路，因此一行观察都不会产生。

跑完脚本会移除临时 worktree 与临时目录。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
BASE = "b43a76a"
TEST_FILE = Path("tests/test_output_feedback.py")

HEADER = f"""# RED 收据 —— tests/test_output_feedback.py 在实现之前（基线 {BASE}）的真实失败
#
# 复现命令（在仓库根目录）：
#   python -B docs/plans/f2-mc-output/receipts/make_red_receipt.py
#
# 手工等价步骤：
#   git worktree add --detach <TMP>/red {BASE}
#   cp tests/test_output_feedback.py <TMP>/red/tests/
#   cd <TMP>/red && python -B -m pytest -q -o addopts= -p no:cacheprovider \\
#       tests/test_output_feedback.py
#   git worktree remove --force <TMP>/red
#
# 说明：基线提交没有本仓反馈适配器（core/feedback.py），因此这些用例因
# “一行观察都没有产生”而失败，而不是因 import 错误失败。
#
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mc-red-receipt-"))
    worktree = tmp / "red"
    try:
        created = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), BASE],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        if created.returncode != 0:
            print(created.stderr)
            return 1

        destination = worktree / TEST_FILE
        destination.write_bytes((REPO_ROOT / TEST_FILE).read_bytes())

        run = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", "-q", "-o", "addopts=",
             "-p", "no:cacheprovider", str(TEST_FILE)],
            cwd=str(worktree), capture_output=True, text=True,
        )
        output = run.stdout + run.stderr
        (HERE / "red-output-feedback.txt").write_text(
            HEADER + output, encoding="utf-8", newline="\n"
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
