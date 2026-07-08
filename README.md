# MeetingConverter - 投资者会议音频转文字引擎

基于 OpenAI Whisper 的 faster-whisper (CTranslate2) 实现，CPU 优化，支持中英文自动识别。

## 快速开始

```bash
# 转写单个文件
python transcribe.py meeting.mp3

# 批量转写目录
python transcribe.py input/

# 指定语言(更快更准)
python transcribe.py meeting.mp3 -l zh    # 中文
python transcribe.py meeting.mp3 -l en    # 英文

# 带时间戳输出
python transcribe.py meeting.mp3 --timestamps

# 使用更大模型(更准但更慢)
python transcribe.py meeting.mp3 -m medium
```

## 模型选择

| 模型    | 参数量  | 内存   | 速度(CPU) | 中文质量 | 推荐场景       |
|---------|---------|--------|-----------|----------|----------------|
| tiny    | 39M     | ~1GB   | 最快      | 一般     | 快速预览       |
| base    | 74M     | ~1GB   | 快        | 良好     | 日常使用 [默认]|
| small   | 244M    | ~2GB   | 中等      | 较好     | 重要内容       |
| medium  | 769M    | ~5GB   | 较慢      | 很好     | 高质量需求     |
| large-v3| 1550M   | ~6GB   | 最慢      | 最佳     | 最高精度       |

## 支持格式

MP3, WAV, M4A, FLAC, OGG, WMA, AAC, OPUS, WebM

## 输出

- 默认输出到 `output/` 目录
- 输出文件为 `.txt` 格式
- 包含文件头信息(语言、时长等)

## 依赖

- Python 3.8+
- faster-whisper
- ffmpeg

## 为投资者会议优化

脚本内置了财务术语提示词(prompt)，自动帮助 Whisper 更准确地识别：
- 营收/净利润/毛利率
- EBITDA/EPS/自由现金流
- 同比增长/环比增长
- 指引/展望/股息/回购
