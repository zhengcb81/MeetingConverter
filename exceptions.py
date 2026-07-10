"""exceptions.py - MeetingConverter 统一异常层级。"""


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
