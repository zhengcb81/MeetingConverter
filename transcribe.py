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
"""

import argparse
import sys
import time
from pathlib import Path

from faster_whisper import WhisperModel
from translator import Translator, load_config
from company import extract_company_from_filename, get_company_context, get_corrections

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma", ".aac", ".opus", ".webm"}

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


def p(msg):
    print(msg, flush=True)


# ── 段落合并 ──────────────────────────────────────────────────────

class Paragraph:
    def __init__(self):
        self.start = 0.0
        self.end = 0.0
        self.segments = []
        self.text = ""

    def add_segment(self, seg):
        if not self.segments:
            self.start = seg["start"]
        self.end = seg["end"]
        self.segments.append(seg)
        self.text += seg["text"].strip() + " "

    def finalize(self):
        self.text = self.text.strip()


def merge_into_paragraphs(segments_iter, gap_threshold=2.0, max_chars=2000):
    paragraphs = []
    current = Paragraph()
    prev_end = 0.0
    sentence_enders = set(".!?。！？")

    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue
        seg_data = {"start": seg.start, "end": seg.end, "text": text}
        gap = seg.start - prev_end if prev_end > 0 else 0
        cur_len = len(current.text)

        should_split = False
        if current.segments:
            if gap > gap_threshold:
                should_split = True
            elif current.text and current.text[-1] in sentence_enders and cur_len > 100:
                should_split = True
            elif cur_len > max_chars:
                should_split = True

        if should_split:
            current.finalize()
            paragraphs.append(current)
            current = Paragraph()

        current.add_segment(seg_data)
        prev_end = seg.end

    if current.segments:
        current.finalize()
        paragraphs.append(current)

    return paragraphs


# ── 格式化 ────────────────────────────────────────────────────────

def fmt_ts(sec):
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def write_original(path, paragraphs, meta, timestamps):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"音频文件: {meta['filename']}\n")
        f.write(f"检测语言: {meta['language']} ({meta['language_prob']:.1%})\n")
        f.write(f"音频时长: {fmt_ts(meta['duration'])}\n")
        f.write(f"段落数量: {len(paragraphs)}\n")
        f.write(f"转写时间: {meta['elapsed']:.1f}秒\n")
        f.write(f"{'='*60}\n\n")
        for para in paragraphs:
            if timestamps:
                f.write(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
            f.write(para.text + "\n\n")


def write_translated(path, paragraphs, translations, meta, timestamps):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"音频文件: {meta['filename']}\n")
        f.write(f"翻译引擎: DeepSeek ({meta.get('translator_model', 'N/A')})\n")
        f.write(f"公司背景: {meta.get('company_name', '未识别')}\n")
        f.write(f"{'='*60}\n\n")
        for para, trans in zip(paragraphs, translations):
            if timestamps:
                f.write(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
            f.write(trans + "\n\n")


def write_bilingual(path, paragraphs, translations, meta, timestamps):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"音频文件: {meta['filename']}\n")
        f.write(f"翻译引擎: DeepSeek ({meta.get('translator_model', 'N/A')})\n")
        f.write(f"公司背景: {meta.get('company_name', '未识别')}\n")
        f.write(f"{'='*60}\n\n")
        for para, trans in zip(paragraphs, translations):
            if timestamps:
                f.write(f"[{fmt_ts(para.start)} -> {fmt_ts(para.end)}]\n")
            f.write(f"【原文】\n{para.text}\n\n")
            f.write(f"【中文】\n{trans}\n\n")
            f.write(f"{'- '*30}\n\n")


# ── 主流程 ────────────────────────────────────────────────────────

def get_audio_files(path):
    p = Path(path)
    if p.is_file():
        return [p] if p.suffix.lower() in AUDIO_EXTENSIONS else []
    if p.is_dir():
        files = []
        for ext in AUDIO_EXTENSIONS:
            files.extend(p.glob(f"*{ext}"))
            files.extend(p.glob(f"*{ext.upper()}"))
        files.sort()
        return files
    return []


def transcribe_one(model, audio_path, output_dir, translator_obj,
                   language=None, timestamps=False, initial_prompt=None,
                   company_context="", corrections=None):
    p(f"\n{'='*60}")
    p(f"转写: {audio_path.name}")
    p(f"{'='*60}")

    t0 = time.time()
    kwargs = {"beam_size": 5, "vad_filter": True, "vad_parameters": {"min_silence_duration_ms": 500}}
    if language:
        kwargs["language"] = language
    if initial_prompt:
        kwargs["initial_prompt"] = initial_prompt

    segments, info = model.transcribe(str(audio_path), **kwargs)
    lang, lang_prob, duration = info.language, info.language_probability, info.duration
    p(f"语言: {lang} ({lang_prob:.1%})  时长: {fmt_ts(duration)}")

    p("合并段落...")
    paragraphs = merge_into_paragraphs(segments)
    elapsed_stt = time.time() - t0
    p(f"转写完成: {len(paragraphs)} 段, {elapsed_stt:.1f}秒")

    # 翻译
    translations = None
    if translator_obj and lang != "zh":
        p(f"\n翻译中 (DeepSeek {translator_obj.model}, 公司: {company_context.split(chr(10))[0] if company_context else '无'})")
        t_trans = time.time()
        raw = translator_obj.translate_paragraphs(
            [para.text for para in paragraphs],
            company_context=company_context,
            corrections=corrections,
            progress_callback=lambda c, n: p(f"  翻译: {c}/{n}"),
        )
        translations = raw
        p(f"翻译完成: {time.time() - t_trans:.1f}秒")
    elif lang == "zh":
        p("纯中文音频，跳过翻译")
        # 中文也要应用纠正规则
        if corrections:
            translations = [Translator._apply_corrections(para.text, corrections) for para in paragraphs]
        else:
            translations = [para.text for para in paragraphs]
    else:
        translations = ["[未启用翻译]"] * len(paragraphs)

    # 输出
    stem = audio_path.stem
    meta = {
        "filename": audio_path.name, "language": lang, "language_prob": lang_prob,
        "duration": duration, "elapsed": elapsed_stt,
        "company_name": company_context.split("\n")[0] if company_context else "",
        "translator_model": translator_obj.model if translator_obj else "N/A",
    }

    orig = output_dir / f"{stem}_原文.txt"
    write_original(orig, paragraphs, meta, timestamps)
    p(f"  原文: {orig}")

    if lang == "zh":
        p("  纯中文音频，跳过翻译和中英对照文件")
    else:
        tr = output_dir / f"{stem}_翻译.txt"
        write_translated(tr, paragraphs, translations, meta, timestamps)
        p(f"  翻译: {tr}")

        bi = output_dir / f"{stem}_中英对照.txt"
        write_bilingual(bi, paragraphs, translations, meta, timestamps)
        p(f"  对照: {bi}")

    return {
        "input": str(audio_path), "paragraphs": len(paragraphs),
        "language": lang, "duration": duration, "elapsed": time.time() - t0,
        "text_length": sum(len(para.text) for para in paragraphs),
    }


def main():
    parser = argparse.ArgumentParser(description="MeetingConverter v2 - 音频转文字+翻译")
    parser.add_argument("input", help="音频文件或目录")
    parser.add_argument("-o", "--output", default="output")
    parser.add_argument("-m", "--model", default="small",
                        choices=["tiny", "base", "small", "medium", "large-v3", "turbo"])
    parser.add_argument("-l", "--language", default=None)
    parser.add_argument("--timestamps", action="store_true")
    parser.add_argument("--no-translate", action="store_true")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    parser.add_argument("--compute-type", default="int8", choices=["int8", "float16", "float32"])
    args = parser.parse_args()

    audio_files = get_audio_files(args.input)
    if not audio_files:
        p("错误: 未找到音频文件"); sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = args.prompt or {
        "zh": FINANCIAL_PROMPT_ZH, "en": FINANCIAL_PROMPT_EN
    }.get(args.language, FINANCIAL_PROMPT_MIXED)

    translator_obj = None
    if not args.no_translate:
        try:
            cfg = load_config()
            translator_obj = Translator(cfg)
            p(f"翻译引擎: DeepSeek ({translator_obj.model})")
        except Exception as e:
            p(f"翻译器不可用 (仅转写): {e}")

    p(f"\n加载 Whisper 模型: {args.model} ({args.device}, {args.compute_type})")
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    p("模型就绪\n")

    results = []
    for af in audio_files:
        cname = extract_company_from_filename(af.name)
        ctx = get_company_context(cname) if cname else ""
        corrs = get_corrections(cname) if cname else {}
        if ctx:
            p(f"识别公司: {cname}")
        if corrs:
            p(f"纠正规则: {len(corrs)} 条")

        try:
            results.append(transcribe_one(
                model, af, output_dir, translator_obj,
                language=args.language, timestamps=args.timestamps,
                initial_prompt=prompt, company_context=ctx, corrections=corrs,
            ))
        except Exception as e:
            import traceback; traceback.print_exc()
            p(f"错误: {af.name} - {e}")

    if results:
        total_dur = sum(r["duration"] for r in results)
        total_time = sum(r["elapsed"] for r in results)
        total_chars = sum(r["text_length"] for r in results)
        p(f"\n{'='*60}")
        p(f"全部完成! 文件:{len(results)} 总时长:{fmt_ts(total_dur)} 耗时:{total_time:.0f}s 文字:{total_chars:,}")
        p(f"输出: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
