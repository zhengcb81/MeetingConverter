"""Native fixture subprocesses with explicit stdin, owner state and no console."""

import os
import subprocess

_HOST_ENV = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC",
    "TEMP", "TMP", "TMPDIR",
}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def fixture_environment():
    env = {key: value for key, value in os.environ.items() if key.upper() in _HOST_ENV}
    return {**env, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "NO_PROXY": "*"}


def open_child(argv, **options):
    options.setdefault("env", fixture_environment())
    options.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(argv, creationflags=_NO_WINDOW, **options)


def run_child(argv, *, input=None, **options):
    options.setdefault("env", fixture_environment())
    if input is None:
        options.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(argv, input=input, creationflags=_NO_WINDOW, **options)
