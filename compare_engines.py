"""compare_engines.py - 对比 MiMo 和 Whisper 引擎的转写质量。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from engines.factory import create_engine
from translator import load_config


def compare_engines(audio_path: str, language: str = None):
    """对比 MiMo 和 Whisper 引擎的转写结果。"""
    cfg = load_config()

    print(f"\n{'='*60}")
    print(f"对比测试: {Path(audio_path).name}")
    print(f"{'='*60}\n")

    # 测试 MiMo
    print("[1/2] 测试 MiMo-V2.5-ASR...")
    try:
        mimo_engine = create_engine("mimo", cfg)
        t0 = time.time()
        mimo_result = mimo_engine.transcribe(audio_path, language=language)
        mimo_time = time.time() - t0
        mimo_text = " ".join(seg.text for seg in mimo_result.segments)
        print(f"  耗时: {mimo_time:.1f}秒")
        print(f"  段落数: {len(mimo_result.segments)}")
        print(f"  语言: {mimo_result.language}")
        print(f"  文本长度: {len(mimo_text)} 字符")
    except Exception as e:
        print(f"  错误: {e}")
        mimo_text = None
        mimo_time = 0

    # 测试 Whisper
    print("\n[2/2] 测试 Whisper (small)...")
    try:
        whisper_engine = create_engine("whisper", cfg)
        t0 = time.time()
        whisper_result = whisper_engine.transcribe(audio_path, language=language)
        whisper_time = time.time() - t0
        whisper_text = " ".join(seg.text for seg in whisper_result.segments)
        print(f"  耗时: {whisper_time:.1f}秒")
        print(f"  段落数: {len(whisper_result.segments)}")
        print(f"  语言: {whisper_result.language}")
        print(f"  文本长度: {len(whisper_text)} 字符")
    except Exception as e:
        print(f"  错误: {e}")
        whisper_text = None
        whisper_time = 0

    # 输出对比
    print(f"\n{'='*60}")
    print("对比结果")
    print(f"{'='*60}")

    if mimo_text and whisper_text:
        # 计算相似度（简单比较）
        mimo_lines = mimo_text.split("。")
        whisper_lines = whisper_text.split("。")

        print(f"\nMiMo 段落数: {len(mimo_result.segments)}")
        print(f"Whisper 段落数: {len(whisper_result.segments)}")
        print(f"\nMiMo 耗时: {mimo_time:.1f}秒")
        print(f"Whisper 耗时: {whisper_time:.1f}秒")

        # 输出前500字符对比
        print(f"\n{'─'*60}")
        print("MiMo 转写（前500字符）:")
        print(f"{'─'*60}")
        print(mimo_text[:500] + "..." if len(mimo_text) > 500 else mimo_text)

        print(f"\n{'─'*60}")
        print("Whisper 转写（前500字符）:")
        print(f"{'─'*60}")
        print(whisper_text[:500] + "..." if len(whisper_text) > 500 else whisper_text)

        # 保存完整结果
        output_dir = Path("comparison")
        output_dir.mkdir(exist_ok=True)
        stem = Path(audio_path).stem

        with open(output_dir / f"{stem}_mimo.txt", "w", encoding="utf-8") as f:
            f.write(mimo_text)
        with open(output_dir / f"{stem}_whisper.txt", "w", encoding="utf-8") as f:
            f.write(whisper_text)

        print(f"\n完整结果已保存到 comparison/ 目录")

    elif mimo_text:
        print("\n仅 MiMo 转写成功")
    elif whisper_text:
        print("\n仅 Whisper 转写成功")
    else:
        print("\n两个引擎都失败了")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python compare_engines.py <音频文件> [语言]")
        sys.exit(1)

    audio_file = sys.argv[1]
    lang = sys.argv[2] if len(sys.argv) > 2 else None
    compare_engines(audio_file, lang)
