"""exceptions.py - MeetingConverter 统一异常层级。"""

from typing import List, Optional


class MeetingConverterError(Exception):
    """所有 MeetingConverter 异常的基类。"""


class TranscriptionError(MeetingConverterError):
    """转写过程中发生的错误。"""


class TranslationError(MeetingConverterError):
    """翻译过程中发生的错误。"""


class EngineError(MeetingConverterError):
    """转写引擎相关错误（API 调用失败、格式不支持等）。"""


class ConfigError(MeetingConverterError):
    """配置相关错误（缺失必需配置、格式无效等）。"""


def explicit_cause_types(
    error: BaseException, *, max_items: int = 8
) -> Optional[List[str]]:
    """读取本仓异常自带的、已脱敏的底层异常类别链。

    只信任 ``EngineError`` 的属性，第三方异常无法用同名属性污染归因；
    空列表不短路（否则会盖掉真实的 ``__cause__``）；最多 ``max_items``
    项，每项必须是合法标识符。不满足条件时返回 ``None``，由调用方沿
    原生 ``__cause__``/``__context__`` 继续投影。
    """
    if not isinstance(error, EngineError):
        return None
    explicit = getattr(error, "cause_types", None)
    if (
        not isinstance(explicit, (list, tuple))
        or not explicit
        or len(explicit) > max_items
        or not all(isinstance(name, str) and name.isidentifier() for name in explicit)
    ):
        return None
    return [str(name) for name in explicit]
