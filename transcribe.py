"""
MeetingConverter - 投资者会议音频转文字引擎 (v2)
基于 faster-whisper + DeepSeek LLM，支持段落合并、翻译、三文件输出。

输出三个文件:
  {name}_原文.txt      - 原始转写文本 (按段落)
  {name}_翻译.txt      - 中文翻译
  {name}_中英对照.txt   - 一段原文 + 一段翻译

用法:
  python transcribe.py input.mp3                     # 转写 + 翻译
  python transcribe.py input.mp3 --no-translate      # 仅转写
  python transcribe.py input.mp3 --timestamps        # 带时间戳
  python transcribe.py input/                        # 批量处理
  python transcribe.py input.mp3 -v                  # 详细日志
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from config import load_config, normalize_config
from core.batch import get_audio_files, run_batch
from core.feedback import (
    STARTUP_ACCEPTED,
    STARTUP_INITIALIZATION_FAILED,
    STARTUP_LOCAL_IO_FAILED,
    STARTUP_REQUEST_REJECTED,
    begin_startup,
)
from core.formatter import fmt_ts
from core.local_diagnostics import cli_diagnostics, record_event, record_failure
from core.pipeline import merge_into_paragraphs, transcribe_one
from core.output import write_original, write_translated, write_bilingual
from engines.factory import create_engine
from translator import Translator

logger = logging.getLogger(__name__)
from company import extract_company_from_filename, get_company_context, get_corrections

FINANCIAL_PROMPT_ZH = (
    "以下是投资者电话会议的内容，涉及财务报告、营收、净利润、毛利率、"
    "EBITDA、每股收益、同比增长、环比增长、资本开支、自由现金流等财务术语。"
)
FINANCIAL_PROMPT_EN = (
    "This is an investor earnings call transcript discussing revenue, net income, "
    "gross margin, EBITDA, EPS, year-over-year growth, capital expenditure, "
    "free cash flow, guidance, outlook, dividend, buyback."
)
FINANCIAL_PROMPT_MIXED = (
    "This is a bilingual investor earnings call with both Chinese and English. "
    "涉及营收、利润、毛利率、EPS、EBITDA、guidance、outlook等财务术语。"
)


def main():
    """普通入口：身份先于参数解析建立；启动失败按阶段记录，退出码保持原口径。"""
    with cli_diagnostics("transcribe"):
        startup = begin_startup()
        record_event("command", "started", step_id=startup.step_id)
        try:
            result = _run(startup)
        except SystemExit as exc:
            record_event("command", "exited", step_id=startup.step_id,
                         exit_code=exc.code if type(exc.code) is int else None)
            raise
        except Exception as exc:
            record_failure("command", exc)
            raise
        else:
            record_event("command", "exited", step_id=startup.step_id, exit_code=result)
            return result
        finally:
            startup.finalize()


def _run(startup) -> int:
    parser = argparse.ArgumentParser(
        description="MeetingConverter v2 - 音频转文字+翻译"
    )
    parser.add_argument("input", help="音频文件或目录")
    parser.add_argument("-o", "--output", default="output")
    parser.add_argument(
        "-m",
        "--model",
        choices=["tiny", "base", "small", "medium", "large-v3", "turbo"],
    )
    parser.add_argument("-l", "--language", default=None)
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--no-translate", action="store_true")
    parser.add_argument("--prompt", default=None)
    parser.add_argument(
        "--engine",
        choices=["auto", "mimo", "whisper"],
        help="转写引擎: auto(MiMo优先回退Whisper)/mimo/whisper",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="详细日志输出"
    )
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"])
    parser.add_argument("--compute-type", choices=["int8", "float16", "float32"])
    parser.add_argument(
        "--force", action="store_true", help="强制重新处理已完成的文件"
    )
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        # 解析未完成：只记录能确定的身份与阶段。argparse 的原生退出码保留。
        code = exc.code
        if not isinstance(code, int):
            code = 0 if code is None else 1
        if code:
            record_failure("parsing", exc)
        startup.record_outcome(
            STARTUP_ACCEPTED if code == 0 else STARTUP_REQUEST_REJECTED,
            stage="parsing",
            exit_code=code,
        )
        raise

    # 配置 logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
    )

    # 请求意图在初始边界保存：翻译是否被请求与翻译器是否可用是两件事。
    translate_requested = not args.no_translate

    audio_files = get_audio_files(args.input)
    if not audio_files:
        logger.info("错误: 未找到音频文件")
        record_failure("input", FileNotFoundError())
        startup.record_outcome(
            STARTUP_REQUEST_REJECTED,
            stage="input",
            exit_code=1,
            translate_requested=translate_requested,
        )
        return 1

    output_dir = Path(args.output)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.info("错误: 输出目录不可用: %s", type(exc).__name__)
        record_failure("output_dir", exc)
        startup.record_outcome(
            STARTUP_LOCAL_IO_FAILED,
            stage="output_dir",
            exit_code=1,
            errors=[exc],
            translate_requested=translate_requested,
        )
        return 1

    cfg = None
    config_error = None
    cli_values = dict(
        transcription_engine=args.engine,
        language=args.language,
        whisper_model=args.model,
        whisper_device=args.device,
        whisper_compute_type=args.compute_type,
    )
    overrides = {key: value for key, value in cli_values.items() if value is not None}
    try:
        raw = load_config()
        if raw is not None:
            candidate = normalize_config({**raw, **overrides})
            candidate.validate_transcription()
            cfg = candidate
    except Exception as e:
        config_error = e
        logger.info("配置加载失败 (使用默认): %s", type(e).__name__)
        record_failure("config", e)
    settings = cfg if cfg is not None else normalize_config(overrides)

    translator_obj = None
    translator_error = None
    if translate_requested:
        if cfg is None:
            # 请求了翻译但配置不可用：如实记录"翻译未运行"的原因。
            translator_error = config_error
            logger.info("翻译器不可用 (仅转写): 配置加载失败")
        else:
            try:
                translator_obj = Translator(cfg)
                logger.info(f"翻译引擎: DeepSeek ({translator_obj.model})")
            except Exception as e:
                translator_error = e
                logger.info("翻译器不可用 (仅转写): %s", type(e).__name__)
                record_failure("translator_init", e)
    translator_ready = translator_obj is not None
    translator_error_type = (
        type(translator_error).__name__ if translator_error is not None else None
    )

    language = settings.language
    engine_choice = settings.transcription_engine

    prompt = args.prompt or {"zh": FINANCIAL_PROMPT_ZH, "en": FINANCIAL_PROMPT_EN}.get(
        language, FINANCIAL_PROMPT_MIXED
    )

    try:
        engine = create_engine(
            engine_choice, settings, settings.whisper_model,
            settings.whisper_device, settings.whisper_compute_type,
        )
    except Exception as exc:
        logger.info("错误: 转写引擎初始化失败: %s", type(exc).__name__)
        record_failure("engine_init", exc)
        startup.record_outcome(
            STARTUP_INITIALIZATION_FAILED,
            stage="engine_init",
            exit_code=1,
            errors=[exc],
            translate_requested=translate_requested,
            translator_ready=translator_ready if translate_requested else None,
            translator_error_type=translator_error_type,
            engine_choice=engine_choice,
        )
        return 1
    logger.info(f"\n转写引擎: {engine_choice}")
    logger.info("引擎就绪\n")

    def get_company_ctx(filename):
        cname = extract_company_from_filename(filename)
        return get_company_context(cname) if cname else ""

    def get_corrections_for(filename):
        cname = extract_company_from_filename(filename)
        return get_corrections(cname) if cname else {}

    stats = run_batch(
        engine,
        audio_files,
        output_dir,
        translator_obj,
        language=language,
        timestamps=args.timestamps,
        initial_prompt=prompt,
        company_context_fn=get_company_ctx,
        corrections_fn=get_corrections_for,
        merge_gap_sec=settings.paragraph_merge_gap_sec,
        paragraph_max_chars=settings.paragraph_max_chars,
        force=args.force,
        translate_requested=translate_requested,
        translator_ready=translator_ready,
        translator_error_type=translator_error_type,
    )

    exit_code = 1 if stats["failures"] > 0 else 0
    startup.record_outcome(
        STARTUP_ACCEPTED,
        stage="batch",
        exit_code=exit_code,
        engine_started=True,
        translation_attempted=translate_requested and translator_ready,
        translate_requested=translate_requested,
        translator_ready=translator_ready if translate_requested else None,
        translator_error_type=translator_error_type,
        engine_choice=engine_choice,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
