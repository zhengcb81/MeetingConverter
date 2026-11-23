"""F4 隔离子进程运行器：在真实 Python 子进程里调用普通入口 ``transcribe.py``。

父进程（测试）启动 ``python -B tests/f4_child_runner.py --child <repo> <root>
<scenario> [额外 CLI 参数...]``。替身只放在允许的边界上：

- 配置在加载边界映射到临时字典（子进程因此读不到仓库里的真实 config.json
  与其中的真实密钥）；
- 引擎替身放在引擎边界；翻译替身放在外部传输边界（真实 ``Translator`` 在
  无密钥时抛 ``ValueError`` 的路径保持原生，不被替换）；
- ``kill-after-terminal`` 场景用 ``run_batch`` 包装在「终态已写、交付确认
  未发」的窗口里停住进程，供父进程强杀。

其余路径（CLI 解析、输入发现、输出目录创建、批处理、文件操作）全部原生。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

SIGNAL = "engine-calls"


class WorkingEngine:
    """成功引擎替身（引擎边界）。"""

    def __init__(self, root: Path, *, sleep_after: float = 0.0):
        self._root = root
        self._sleep_after = sleep_after

    def transcribe(self, *args, **kwargs):
        with (self._root / SIGNAL).open("a", encoding="utf8") as stream:
            stream.write("called\n")
        if self._sleep_after:
            time.sleep(self._sleep_after)
        return _fixture_result()


class FailingPrimaryEngine:
    """主引擎替身：外层 RuntimeError，底层原因由 ``inner`` 决定。"""

    def __init__(self, root: Path, inner: Exception):
        self._root = root
        self._inner = inner

    def transcribe(self, *args, **kwargs):
        with (self._root / SIGNAL).open("a", encoding="utf8") as stream:
            stream.write("called\n")
        try:
            raise self._inner
        except Exception as inner:
            raise RuntimeError("fixture upstream failed") from inner


class BrokenFallbackFactory:
    """备用引擎创建失败（引擎边界）。"""

    def __call__(self):
        raise OSError("fixture fallback engine unavailable")


def _fixture_result():
    from engines.base import Segment, TranscriptionResult

    return TranscriptionResult(
        language="en",
        language_probability=0.99,
        duration=1.0,
        segments=[
            Segment(0.0, 30.0, "Revenue grew 30% year over year."),
            Segment(35.0, 60.0, "Gross margin improved to 21.5%."),
        ],
    )


def _install(repo: Path, root: Path, scenario: str):
    """按场景注入边界替身；返回额外 CLI 参数。"""
    sys.path.insert(0, str(repo))
    import transcribe
    from engines.fallback import FallbackEngine

    # 配置边界：隔离的临时配置，不含真实密钥。
    transcribe.load_config = lambda: {"isolated_fixture": True}

    engine = WorkingEngine(root)
    if scenario == "provider-fail":
        engine = FailingPrimaryEngine(root, TimeoutError(110, "fixture-timeout"))
    elif scenario == "provider-fail-valueerror":
        engine = FailingPrimaryEngine(root, ValueError("fixture-inner"))
    elif scenario == "fallback-timeout":
        engine = FallbackEngine(
            FailingPrimaryEngine(root, TimeoutError(110, "fixture-timeout")),
            lambda: WorkingEngine(root),
        )
    elif scenario == "fallback-valueerror":
        engine = FallbackEngine(
            FailingPrimaryEngine(root, ValueError("fixture-inner")),
            lambda: WorkingEngine(root),
        )
    elif scenario == "fallback-unavailable":
        engine = FallbackEngine(
            FailingPrimaryEngine(root, TimeoutError(110, "fixture-timeout")),
            BrokenFallbackFactory(),
        )
    elif scenario == "kill":
        engine = WorkingEngine(root, sleep_after=60)
    elif scenario == "kill-after-terminal":
        real_run_batch = transcribe.run_batch

        def run_batch_then_wait(*args, **kwargs):
            stats = real_run_batch(*args, **kwargs)
            # 终态已写、交付确认未发：在这里停住，等父进程强杀。
            (root / "terminal-written").write_text("1", encoding="utf8")
            time.sleep(60)
            return stats

        transcribe.run_batch = run_batch_then_wait
    elif scenario == "translation-failure":
        # 翻译替身放在外部传输边界；引擎照常替换，不提前返回。
        from exceptions import TranslationError

        class FailingTranslator:
            model = "fixture-translator"

            def translate_paragraphs(self, *args, **kwargs):
                raise TranslationError("fixture translation provider failed")

        transcribe.Translator = lambda cfg: FailingTranslator()

    # 引擎边界：除 engine-init（走真实工厂）外全部替换。
    if scenario != "engine-init":
        transcribe.create_engine = lambda *args, **kwargs: engine
    if scenario in ("writer-fail", "translation-failure"):
        # 原文名已被旧产物占用：不强制就会被跳过规则拦截。
        return ["--force"]
    return []


def main() -> None:
    if len(sys.argv) < 5 or sys.argv[1] != "--child":
        raise SystemExit("usage: f4_child_runner.py --child REPO ROOT SCENARIO [CLI...]")
    repo, root, scenario = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    extra = _install(repo, root, scenario)
    import transcribe

    source = root / "audio.wav"
    output = root / "out"
    argv = ["transcribe.py", str(source), "-o", str(output)]
    if scenario != "translator-init" and scenario != "translation-failure":
        # 除翻译路径场景外显式关闭翻译；translator-init/translation-failure
        # 保持默认「请求翻译」。
        argv.append("--no-translate")
    if scenario == "engine-init":
        argv.extend(["--engine", "mimo"])
    if scenario == "invalid-cli":
        argv.append("--unknown-fixture-option")
    argv.extend(extra)
    sys.argv = argv
    raise SystemExit(transcribe.main())


if __name__ == "__main__":
    main()
