"""Use the actual config reader, CLI, engines and output in a network-free child."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Union

import pytest

REPO = Path(__file__).resolve().parents[1]
MIMO_DEFAULT = "https://api.xiaomimimo.com/v1/chat/completions"
TOKEN_PLAN = "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
DEEPSEEK_DEFAULT = "https://api.deepseek.com/v1/chat/completions"

CLI_CHILD = r"""
import builtins
import json
import socket
import sys
import urllib.request
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

repo, root = Path(sys.argv[1]), Path(sys.argv[2])
options = sys.argv[3:]
sys.path.insert(0, str(repo))

def deny_network(*args, **kwargs):
    raise AssertionError("the configuration test cannot use a real transport")

socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network
socket.getaddrinfo = deny_network

called = []

def fake_urlopen(request, *, timeout):
    body = json.loads(request.data)
    model = body["model"]
    speech = "asr_options" in body
    called.append({"kind": "speech" if speech else "translation",
                   "endpoint": request.full_url, "model": model, "timeout": timeout})
    assert request.method == "POST"
    content = "Revenue rose during the quarter." if speech else "本季度营收增长。"
    return BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8"))

urllib.request.urlopen = fake_urlopen

class WhisperModel:
    def __init__(self, model, *, device, compute_type):
        called.append({"kind": "local_engine", "model": model,
                       "device": device, "compute_type": compute_type})

    def transcribe(self, *args, **kwargs):
        called.append({"kind": "local_transcription", "language": kwargs["language"]})
        segment = SimpleNamespace(start=0.0, end=1.0, text="Revenue rose during the quarter.")
        info = SimpleNamespace(language="en", language_probability=1.0, duration=1.0)
        return [segment], info

sys.modules["faster_whisper"] = SimpleNamespace(WhisperModel=WhisperModel)

import config
import translator
import engines.mimo
import transcribe

# The standard implicit file lookup uses only the owned test directory for
# both the historical module and the configuration owner it moves to.
config.__file__ = str(root / "config.py")
translator.__file__ = str(root / "translator.py")
engines.mimo.get_audio_duration = lambda _path: 1.0
raw_open = builtins.open
config_path = root / "config.json"
open_count = 0

def track_open(path, *args, **kwargs):
    global open_count
    if isinstance(path, (str, Path)) and Path(path) == config_path:
        open_count += 1
    return raw_open(path, *args, **kwargs)

builtins.open = track_open
sys.argv = ["transcribe.py", str(root / "audio.wav"), "-o", str(root / "out"), *options]
exit_code = transcribe.main()
cli_opens = open_count
builtins.open = raw_open
typed_endpoint = typed_error = None
if "--no-translate" not in options:
    try:
        typed_endpoint = config.Config.load().mimo_base_url
    except (json.JSONDecodeError, config.ConfigError) as error:
        typed_error = type(error).__name__
(root / "result.json").write_text(json.dumps({
    "calls": called, "config_opens": cli_opens,
    "typed_endpoint": typed_endpoint, "typed_error": typed_error,
}), encoding="utf-8")
raise SystemExit(exit_code)
"""


def _run_cli(root: Path, config: Union[dict, str], *options: str) -> dict:
    config_text = config if isinstance(config, str) else json.dumps(config)
    (root / "config.json").write_text(config_text, encoding="utf-8")
    (root / "audio.wav").write_bytes(b"synthetic audio bytes")
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP")
           if key in os.environ}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               RESEARCH_FEEDBACK_DIR=str(root / "feedback"),
               RESEARCH_FEEDBACK_STATE_ROOT=str(root / "state"))
    process = subprocess.run(
        [sys.executable, "-B", "-c", CLI_CHILD, str(REPO), str(root), *options],
        cwd=root, env=env, capture_output=True, encoding="utf-8", timeout=20,
    )
    assert process.returncode == 0, (process.stdout, process.stderr)
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    assert result["config_opens"] == 1
    original = (root / "out/audio_原文.txt").read_text(encoding="utf-8").strip().splitlines()
    assert original[0] == "音频文件: audio.wav"
    assert original[-1] == "Revenue rose during the quarter."
    return result


@pytest.mark.parametrize("explicit_url", [None, TOKEN_PLAN, "https://mimo.invalid/custom/asr"])
def test_cli_engine_and_typed_load_agree_on_the_same_config(tmp_path, explicit_url):
    config = {"mimo_api_key": "fake-mimo-key", "deepseek_api_key": "fake-deepseek-key"}
    translation_url = DEEPSEEK_DEFAULT
    translation_model = "deepseek-v4-flash"
    timeout = 120
    if explicit_url is not None:
        config.update(mimo_base_url=explicit_url, deepseek_base_url="https://translation.invalid",
                      deepseek_model="fixture-explicit-model", translate_api_timeout=17)
        translation_url = "https://translation.invalid/v1/chat/completions"
        translation_model = "fixture-explicit-model"
        timeout = 17
    outcome = _run_cli(tmp_path, config, "--engine", "mimo", "--language", "en")
    expected_mimo = explicit_url or MIMO_DEFAULT
    assert outcome["calls"] == [
        {"kind": "speech", "endpoint": expected_mimo, "model": "mimo-v2.5-asr", "timeout": 300},
        {"kind": "translation", "endpoint": translation_url,
         "model": translation_model, "timeout": timeout},
    ]
    assert outcome["typed_endpoint"] == expected_mimo
    translated = (tmp_path / "out/audio_翻译.txt").read_text(encoding="utf-8").strip().splitlines()
    assert translated[-1] == "本季度营收增长。"
    assert (tmp_path / "out/audio_中英对照.txt").is_file()


def test_cli_explicit_parameters_override_the_config(tmp_path):
    config = {
        "transcription_engine": "mimo",
        "whisper_model": "medium",
        "whisper_device": "cpu",
        "whisper_compute_type": "int8",
        "language": "zh",
        "deepseek_api_key": "YOUR_API_KEY_HERE",
    }
    outcome = _run_cli(
        tmp_path, config, "--engine", "whisper", "--model", "tiny", "--device", "cuda",
        "--compute-type", "float16", "--language", "en", "--no-translate",
    )
    assert outcome["calls"] == [
        {"kind": "local_engine", "model": "tiny", "device": "cuda", "compute_type": "float16"},
        {"kind": "local_transcription", "language": "en"},
    ]
    assert {f.name for f in (tmp_path / "out").iterdir()} == {"audio_原文.txt"}


def test_cli_without_engine_flags_uses_the_config(tmp_path):
    config = {
        "transcription_engine": "whisper",
        "mimo_api_key": "synthetic-mimo-key",
        "whisper_model": "medium",
        "whisper_device": "cuda",
        "whisper_compute_type": "float16",
        "language": "en",
    }
    outcome = _run_cli(tmp_path, config, "--no-translate")
    assert outcome["calls"] == [
        {"kind": "local_engine", "model": "medium", "device": "cuda", "compute_type": "float16"},
        {"kind": "local_transcription", "language": "en"},
    ]


def test_explicit_auto_still_prefers_mimo(tmp_path):
    config = {"transcription_engine": "whisper", "mimo_api_key": "synthetic-mimo-key"}
    outcome = _run_cli(tmp_path, config, "--engine", "auto", "--no-translate")
    assert len(outcome["calls"]) == 1
    assert outcome["calls"][0]["kind"] == "speech"


def test_bad_translation_setting_does_not_discard_transcription_settings(tmp_path):
    config = {
        "transcription_engine": "whisper",
        "whisper_model": "medium",
        "deepseek_api_key": "synthetic-translation-key",
        "translate_max_retries": True,
    }
    result = _run_cli(tmp_path, config, "--language", "en")
    assert result["typed_error"] == "ConfigError"
    assert result["calls"] == [
        {"kind": "local_engine", "model": "medium", "device": "cpu", "compute_type": "int8"},
        {"kind": "local_transcription", "language": "en"},
    ]
    assert {f.name for f in (tmp_path / "out").iterdir()} == {"audio_原文.txt"}


def test_legacy_config_loader_is_the_owner_export(tmp_path):
    from config import load_config
    from translator import load_config as legacy_load

    path = tmp_path / "custom.json"
    value = {"caller_note": "preserve unknown raw keys"}
    path.write_text(json.dumps(value), encoding="utf-8")
    assert legacy_load is load_config and legacy_load(str(path)) == value
    assert load_config.__module__ == "config"



def test_bad_config_keeps_the_transcript_and_records_the_translation_cause(tmp_path):
    result = _run_cli(tmp_path, "{", "--engine", "whisper", "--language", "en")
    assert result["typed_error"] == "JSONDecodeError"
    assert [call["kind"] for call in result["calls"]] == ["local_engine", "local_transcription"]
    assert {f.name for f in (tmp_path / "out").iterdir()} == {"audio_原文.txt"}

    details, = (tmp_path / "feedback").glob("*.details.jsonl")
    rows = [json.loads(line) for line in details.read_text(encoding="utf-8").splitlines()]
    finished, = [row for row in rows if row.get("phase") == "finished"]
    translation = finished["translation"]
    assert translation["requested"] is True and translation["ran"] is False
    assert translation["unavailable_error_type"] == "JSONDecodeError"
