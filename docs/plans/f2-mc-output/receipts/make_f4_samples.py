"""生成 F4 交付样例：真实跑普通入口，把交付文件原样拷进 receipts。

用法（在仓库根目录）::

    python -B docs/plans/f2-mc-output/receipts/make_f4_samples.py

四个场景各跑一次真实子进程（普通 CLI 入口，默认交付映射到临时状态根），
然后把交付三件套（``feedback-<id>.jsonl`` / ``.details.jsonl`` / ``.ready``）
拷贝到 receipts/ 下固定名字：

- ``f4-sample-startup-rejected.*`` —— 无输入，请求拒绝；
- ``f4-sample-translation-unavailable.*`` —— 默认请求翻译、翻译器初始化失败，
  原文照常产出（RED #1 对应场景）；
- ``f4-sample-fallback-degraded.*`` —— 主引擎 TimeoutError、备用成功，
  终态 ``published_degraded``（RED #2 对应场景）；
- ``f4-sample-started-only.*`` —— 替身引擎进入转录后被强停，只有启动收据。

样例里的 step/input_id 由临时路径散列而来，随运行变化；收据只证明行为。
脚本收尾移除全部临时目录；样例与收据文本不含机器绝对路径。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
RUNNER = REPO_ROOT / "tests" / "f4_child_runner.py"

SCENARIOS = (
    # (场景, 子进程准备, receipts 文件名前缀)
    ("no-input", None, "f4-sample-startup-rejected"),
    ("translator-init", None, "f4-sample-translation-unavailable"),
    ("fallback-timeout", None, "f4-sample-fallback-degraded"),
    ("kill", "kill", "f4-sample-started-only"),
)

_ALLOWED_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME",
    "USERPROFILE", "SYSTEMDRIVE", "COMSPEC", "APPDATA", "LOCALAPPDATA",
}
_ABS_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"\n]*")
_PYTEST_TMP = re.compile(r"[A-Za-z]:[\\/][^\s'\"\n]*pytest-of-[^\s'\"\n]*")


def scrub(text: str) -> str:
    text = _PYTEST_TMP.sub("<PYTEST_TMP>", text)
    return _ABS_PATH.sub("<ABS_PATH>", text)


def child_env(root: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k.upper() in _ALLOWED_ENV}
    env["PYTHONUTF8"] = "1"
    for name in ("RESEARCH_FEEDBACK_OUT", "RESEARCH_FEEDBACK_DIR",
                 "RESEARCH_FEEDBACK_RUN_ID", "RESEARCH_FEEDBACK_ATTEMPT_ID",
                 "RESEARCH_FEEDBACK_STATE_ROOT"):
        env.pop(name, None)
    env["RESEARCH_FEEDBACK_STATE_ROOT"] = str(root / "state")
    return env


def wait_for(path: Path, timeout: float = 20.0) -> None:
    until = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > until:
            raise RuntimeError(f"signal not reached: {path.name}")
        time.sleep(0.02)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mc-f4-samples-"))
    summary = []
    try:
        for scenario, prepare, name in SCENARIOS:
            root = tmp / name
            root.mkdir()
            if scenario != "no-input":
                (root / "audio.wav").write_bytes(b"stub audio for local engine")
            command = [
                sys.executable, "-B", "-X", "utf8", str(RUNNER),
                "--child", str(REPO_ROOT), str(root), scenario,
            ]
            with subprocess.Popen(
                command, cwd=str(root), env=child_env(root),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ) as child:
                if prepare == "kill":
                    wait_for(root / "engine-calls")
                    child.kill()
                stdout, stderr = child.communicate(timeout=60)
            observations = root / "state" / "observations"
            delivered = [
                p for p in sorted(observations.glob("feedback-*.jsonl"))
                if not p.name.endswith(".details.jsonl")
            ]
            if len(delivered) != 1:
                print(f"{scenario}: expected one delivery, found {len(delivered)}")
                return 1
            source = delivered[0]
            shutil.copy2(source, HERE / f"{name}.jsonl")
            shutil.copy2(
                source.with_name(source.name + ".details.jsonl"),
                HERE / f"{name}.jsonl.details.jsonl",
            )
            ready = source.with_name(source.stem + ".ready")
            if ready.is_file():
                shutil.copy2(ready, HERE / f"{name}.ready")
            summary.append(
                f"{name}: exit={child.returncode} file={source.name} "
                f"ready={ready.is_file()}"
            )
        (HERE / "f4-samples-summary.txt").write_text(
            "# F4 交付样例生成摘要（真实运行）\n\n"
            + "\n".join(scrub(line) for line in summary)
            + "\n",
            encoding="utf-8", newline="\n",
        )
        print("\n".join(summary))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
