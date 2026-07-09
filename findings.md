# 审查与研究发现

## F1-F19: 代码审查发现（详见 task_plan.md 问题→阶段映射）
- F1 配置键失效(#5)→P3.1
- F2 双语漏翻(#2)→P3.2
- F3 --no-translate 占位文件(#4)→P3.3
- F4 DeepSeek 清洗误删(#11)→P3.4
- F5 Py3.8 不兼容(#1)→P4.1
- F6 中文纠正无边界(#3)→P4.2
- F7 公司名子串错配(#6)→P4.3
- F8 p 命名地雷(#14)→P4.4
- F9 死代码/冗余依赖(#7,#9)→P5.1
- F10 跨模块私有调用(#10)→P5.2
- F11 失败静默(#12)→P5.3
- F12 命令不对称/兜底复活(#17,#18)→P5.4
- F13 硬编码(#19)→P5.5
- F14 无批量无断点(#8)→P6.1
- F15 不跳过已完成(#13)→P6.2
- F16 无 logging(#20)→P6.3
- F17 wiki 未文档化(#21)→P6.4
- F18 README/REVIEW 滞后(#15,#16)→P7
- F19 0 测试(#22)→P1+P8

## F20: MiMo-V2.5-ASR API 研究
- 日期：2026-07-08
- 来源：https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/Speech-Recognition
- 要点：
  - 端点：POST https://api.xiaomimimo.com/v1/chat/completions（OpenAI 兼容）
  - 认证：header `api-key: $MIMO_API_KEY`（注意非 Bearer）
  - 模型名：mimo-v2.5-asr（唯一 ASR 模型）
  - 请求体：messages[].content[].type="input_audio", input_audio.data=data URL 或 base64+format
  - 参数：asr_options.language = auto/zh/en（未配置则自动检测）
  - 格式：仅 wav/mp3；MIME: audio/wav, audio/mpeg
  - 大小：base64 后 ≤ 10MB（原始约 7.5MB）
  - 输出：choices[0].message.content（整段文本，无 segment 时间戳）
  - 计费：¥0.5/小时按音频时长
  - 独立 API key，与 deepseek_api_key 分开
- 影响：
  - 需 TranscriptionEngine 抽象层（P1）
  - 需音频切片处理长会议（D7, P2.2）
  - 需无时间戳段落合并（D8, P2.3）
  - 非 wav/mp3 回退 Whisper（D6, P2.4）

## F21: 架构决策
- D1 始终送 LLM 翻译（移除 _is_mostly_chinese）
- D2 from __future__ import annotations（Py3.8 兼容）
- D3 保留 DeepSeek thinking，_clean_output 仅 trim
- D6 非 wav/mp3 回退 Whisper（不转码）
- D7 ffmpeg 静音切片拼接长音频
- D8 按句末标点+max_chars 切段（无时间戳）
- D9 CLI --engine + config transcription_engine 双通道
- D10 完整测试体系+CI（单测+mock集成+fixtures+pytest+coverage>80%+GitHub Actions）

## F22: 新增模块规划
- engines/base.py：TranscriptionEngine(Protocol), Segment, TranscriptionResult
- engines/whisper.py：WhisperEngine（包裹 faster-whisper）
- engines/mimo.py：MiMoEngine（MiMo API + 切片 + 文本分段）
- engines/factory.py：引擎选择与回退链
- audio_utils.py：格式检测、大小估算、静音切片
- text_merger.py：无时间戳文本分段
- tests/：完整测试目录（conftest + 各模块测试 + fixtures）
- .github/workflows/ci.yml：CI 管道
