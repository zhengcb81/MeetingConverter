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

from core.batch import get_audio_files, run_batch
from core.formatter import fmt_ts
from core.pipeline import merge_into_paragraphs, transcribe_one
from core.output import write_original, write_translated, write_bilingual
from engines.factory import create_engine
from translator import Translator, load_config

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
    parser = argparse.ArgumentParser(
        description="MeetingConverter v2 - 音频转文字+翻译"
    )
    parser.add_argument("input", help="音频文件或目录")
    parser.add_argument("-o", "--output", default="output")
    parser.add_argument(
        "-m",
        "--model",
        default="small",
        choices=["tiny", "base", "small", "medium", "large-v3", "turbo"],
    )
    parser.add_argument("-l", "--language", default=None)
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--no-translate", action="store_true")
    parser.add_argument("--prompt", default=None)
    parser.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "mimo", "whisper"],
        help="转写引擎: auto(MiMo优先回退Whisper)/mimo/whisper",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="详细日志输出"
    )
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    parser.add_argument(
        "--compute-type", default="int8", choices=["int8", "float16", "float32"]
    )
    parser.add_argument(
        "--force", action="store_true", help="强制重新处理已完成的文件"
    )
    args = parser.parse_args()

    # 配置 logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
    )

    audio_files = get_audio_files(args.input)
    if not audio_files:
        logger.info("错误: 未找到音频文件")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = None
    try:
        cfg = load_config()
    except Exception as e:
        logger.info(f"配置加载失败 (使用默认): {e}")

    translator_obj = None
    if not args.no_translate and cfg:
        try:
            translator_obj = Translator(cfg)
            logger.info(f"翻译引擎: DeepSeek ({translator_obj.model})")
        except Exception as e:
            logger.info(f"翻译器不可用 (仅转写): {e}")

    whisper_model = (cfg or {}).get("whisper_model", args.model)
    whisper_device = (cfg or {}).get("whisper_device", args.device)
    whisper_compute_type = (cfg or {}).get("whisper_compute_type", args.compute_type)
    merge_gap = (cfg or {}).get("paragraph_merge_gap_sec", 2.0)
    para_max = (cfg or {}).get("paragraph_max_chars", 2000)
    language = args.language or (cfg or {}).get("language")
    engine_choice = args.engine or (cfg or {}).get("transcription_engine", "auto")

    prompt = args.prompt or {"zh": FINANCIAL_PROMPT_ZH, "en": FINANCIAL_PROMPT_EN}.get(
        language, FINANCIAL_PROMPT_MIXED
    )

    engine = create_engine(
        engine_choice, cfg, whisper_model, whisper_device, whisper_compute_type
    )
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
        merge_gap_sec=merge_gap,
        paragraph_max_chars=para_max,
        force=args.force,
    )

    if stats["failures"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
