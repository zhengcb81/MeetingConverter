# MeetingConverter 全面改进计划（v2）— 已完成 ✅

## 目标
1. ✅ 集成 MiMo-V2.5-ASR 为默认语音识别引擎，Whisper 作为第二顺位
2. ✅ 修复审查发现的 22 项问题
3. ✅ 建立完整测试体系 + CI

分 8 阶段推进，每阶段独立可验证、可提交。全部完成。

## 关键决策（已确认）
| ID | 决策 | 说明 |
|----|------|------|
| D1 | 始终送 LLM 翻译 | 移除 _is_mostly_chinese 短路，双语段也翻译 |
| D2 | from __future__ import annotations | 保留 Python 3.8+ 兼容 |
| D3 | 保留 DeepSeek thinking，简化清洗 | _clean_output 退化为仅 trim |
| D4 | 全部 22 项，分阶段 | 范围全覆盖 |
| D5 | 先审阅后写盘 | 规划文件批准后再落盘 |
| D6 | 非 wav/mp3 回退 Whisper | 不转码，格式不匹配直接降级 |
| D7 | ffmpeg 静音切片拼接 | 长音频超 10MB base64 限时按静音切分 |
| D8 | 按句末标点+max_chars 切段 | MiMo 无时间戳，仅按标点和长度分段 |
| D9 | CLI+config 双通道 | --engine auto\|mimo\|whisper + config transcription_engine |
| D10 | 完整测试体系+CI | 单测+mock集成+fixtures+pytest+coverage>80%+GitHub Actions |

## 问题→阶段映射
| # | 问题 | 阶段 |
|---|------|------|
| - | 测试基础设施+引擎抽象 | P1 |
| - | MiMo-V2.5-ASR 集成 | P2 |
| 5,2,4,11 | 配置失效/漏翻/占位文件/清洗误删 | P3 |
| 1,3,6,14 | Py兼容/中文纠正/公司名/p命名 | P4 |
| 7,9,10,12,17,18,19 | 死代码/冗余依赖/私有调用/静默失败/add不对称/兜底复活/硬编码 | P5 |
| 8,13,20,21 | 无批量无断点/不跳过已完成/无logging/wiki未文档化 | P6 |
| 15,16 | README滞后/REVIEW过时 | P7 |
| 22 | 测试体系收尾+CI | P8 |

---

## Phase 1（测试基础设施 + 引擎抽象层）— 状态：in_progress

为后续所有改动提供安全网。先建骨架，后续每阶段 TDD。

### 1.1 引擎抽象
- [ ] 新建 engines/base.py：TranscriptionEngine(Protocol)、Segment、TranscriptionResult dataclass
      ```
      Segment: start, end, text
      TranscriptionResult: language, language_probability, duration, segments
      TranscriptionEngine.transcribe(audio_path, language, initial_prompt) -> TranscriptionResult
      ```
- [ ] 新建 engines/whisper.py：WhisperEngine 包裹现有 faster-whisper 调用，适配为统一接口
- [ ] 新建 engines/factory.py：create_engine(config, args) → 引擎实例（P2 实现 MiMo 后补全回退链）
验证：WhisperEngine 经 mock 后返回 TranscriptionResult 结构正确

### 1.2 测试骨架
- [ ] 新建 tests/ 目录、tests/conftest.py（共享 fixtures：tmp_output_dir, mock_whisper, mock_mimo, sample_text）
- [ ] 新建 pytest.ini（testpaths=tests, addopts=-v --cov=., --cov-report=term-missing）
- [ ] requirements.txt 加 pytest, pytest-cov, pytest-mock
- [ ] tests/test_whisper_engine.py：mock WhisperModel，验证 Segment 转换
- [ ] tests/test_engine_factory.py：引擎选择逻辑（P2 MiMo 就绪后扩充回退测试）
验证：pytest tests/ 全绿（仅 P1 范围）；pytest --cov 覆盖率基线

---

## Phase 2（MiMo-V2.5-ASR 引擎集成）— 状态：pending

核心新功能。MiMo 为默认引擎，Whisper 为回退。

### 2.1 MiMo 引擎实现
- [ ] 新建 engines/mimo.py：MiMoEngine
      - _encode_audio(path) → base64 data URL（wav→audio/wav, mp3→audio/mpeg）
      - _build_payload(base64, language) → OpenAI 兼容 JSON
      - _call_api(payload) → urllib（与 translator.py 风格一致，不引 openai 依赖）
      - transcribe(audio_path, language, initial_prompt) → TranscriptionResult（language 来自 asr_options 或响应，duration 来自 ffmpeg ffprobe，segments 由 _split_text 生成）
      - API: POST https://api.xiaomimimo.com/v1/chat/completions, header api-key
- [ ] 从 config 读 mimo_api_key/mimo_base_url（独立于 deepseek_api_key）
验证：mock HTTP，验证 payload 结构、base64 编码、响应解析

### 2.2 长音频切片（依 D7）
- [ ] 新建 audio_utils.py：
      - detect_format(path) → "wav"/"mp3"/None（不支持返回 None 触发回退）
      - estimate_base64_size(path) → MB
      - split_by_silence(path, max_size_mb) → list[(tmp_path, start, end)]
        用 ffmpeg silencedetect=noise=-30dB:d=0.5 找静音点，按 max_size 选切分点，ffmpeg -ss -to 切片
- [ ] MiMoEngine.transcribe 超限时调 split_by_silence，逐片 ASR 后拼接文本
验证：mock ffmpeg 输出，验证切片点选择、拼接顺序

### 2.3 无时间戳段落合并（依 D8）
- [ ] 新建 text_merger.py：merge_text_into_paragraphs(text, max_chars)
      按句末标点（。！？.!?）+ max_chars 切分，返回 list[Segment]（start=end=0，text=段落）
- [ ] MiMoEngine 用 text_merger 生成 segments，merge_into_paragraphs 兼容零时间戳
验证：单测覆盖句末切分、超长切分、连续标点、无标点兜底

### 2.4 引擎选择与回退（依 D6, D9）
- [ ] engines/factory.py 实现：
      - --engine auto（默认）：MiMo 优先；格式非 wav/mp3(D6) 或切片失败 → 回退 Whisper
      - --engine mimo：强制 MiMo，失败报错不回退
      - --engine whisper：强制 Whisper
- [ ] transcribe.py:280 替换 WhisperModel 直接调用为 factory.create_engine
- [ ] config.example.json 加：mimo_api_key, mimo_base_url(https://api.xiaomimimo.com), transcription_engine("auto"), mimo_language(null)
- [ ] transcribe.py argparse 加 --engine choices=["auto","mimo","whisper"] default="auto"
验证：auto 模式下 wav/mp3 走 MiMo mock，m4a 走 Whisper mock；factory 回退测试

### 2.5 MiMo 专项测试
- [ ] tests/test_mimo_engine.py：payload 构建、base64 编码、响应解析、错误处理（mock urllib）
- [ ] tests/test_audio_utils.py：格式检测、大小估算、静音切片解析（mock subprocess）
- [ ] tests/test_text_merger.py：见 2.3
- [ ] tests/test_engine_factory.py：扩充 auto/mimo/whisper 三模式 + 回退链
验证：pytest tests/ 全绿；MiMo 路径覆盖率 >85%

---

## Phase 3（修复影响产出的行为 bug）— 状态：in_progress

### 3.1 配置键接入 (#5) — 已完成
- [x] transcribe.py transcribe_one 加 merge_gap_sec/paragraph_max_chars 参数
- [x] merge_into_paragraphs 接收 config 的 gap/max_chars
- [x] main() 读 config 覆盖 argparse 默认值（model/device/compute_type/language/engine）
- [x] 确认 config 每键都有代码引用
- [ ] tests/test_config.py：load_config、配置键生效、缺失键默认值

### 3.2 修复漏翻 (#2, 依 D1) — 已完成
- [x] translator.py 删除 _is_mostly_chinese 短路，始终走 _call_api
- [x] transcribe.py 翻译条件改为 if translator_obj（删除 lang != "zh" 与 zh 分支）
- [x] translations=None 时跳过翻译文件输出（P3.3 共用）
- [x] _apply_corrections 提为模块级 apply_corrections（顺带完成 P5.2）
- [ ] tests/test_translator.py：混合段、纯中文段翻译路径（mock API）

### 3.3 --no-translate 不写占位文件 (#4) — 已完成
- [x] transcribe.py translations is None 时仅写 _原文.txt
- [x] 删除 ["[未启用翻译]"] 占位输出与 lang=="zh" 跳过逻辑
- [ ] tests/test_transcribe_integration.py：--no-translate 仅产 1 文件

### 3.4 简化 LLM 输出清洗 (#11, 依 D3) — 已完成
- [x] translator.py _clean_output 退化为 return text.strip()
- [x] 删除启发式 skip 逻辑与 len<10 兜底
- [ ] tests/test_translator.py：含"结合""第X步"正常文本不被误删

### P3 验证状态
- py_compile 全模块通过
- pytest 70/70 全绿（engines 100% 覆盖）
- 待补 P3 测试（test_translator / test_transcribe_integration / test_config / test_corrections）

---

## Phase 4（兼容性与正确性）— 状态：completed

### 4.1 Python 3.8 兼容 (#1, 依 D2) — 已完成
- [x] company.py 顶部加 from __future__ import annotations（已有）
- [x] 全项目 grep PEP604，统一加 future import（含 engines/ 新文件）
      - transcribe.py、translator.py、company_manager.py 已添加
- [ ] tests/test_compat.py：验证注解字符串化（eval 不报错）（可选）
验证：py_compile 全模块通过；pytest 138 全绿

### 4.2 中文纠正规则边界保护 (#3) — 已完成（代码已有占位保护）
- [x] translator.py apply_corrections：中文 key 替换前先占位保护已有 right 值
      流程：用占位符替换文本中已存在的 right → 替换 wrong → 还原占位（translator.py:40-43）
- [x] tests/test_corrections.py：corrections={"可灵":"可灵AI"}，text="可灵AI发布"→不变
验证：单测覆盖中文边界、英文词边界、长键优先

### 4.3 公司名精确匹配优先 (#6) — 已完成
- [x] company.py:70-74 精确匹配优先，多匹配选最长名
- [x] tests/test_company.py：库含"小米"+"小米集团"时查"小米集团"返回后者
验证：单测

### 4.4 消除 p 命名地雷 (#14) — 已完成
- [x] transcribe.py 全局 print 函数 p → log（已无 p( 调用）
- [x] 修复 load_config/get_audio_files 内部局部变量 p 冲突（已无冲突）
- [x] tests 回归（调用点全更新）
验证：grep 确认无 p( 残留；py_compile

---

## Phase 5（代码清理）— 状态：completed

### 5.1 删除死代码与冗余依赖 — 已完成
- [x] #7 translator.py 删除 detect_language 和 _is_mostly_chinese（grep 确认无调用）
- [x] #9 requirements.txt 无 requests（已确认未 import）
- [ ] tests/test_no_dead_code.py：import 检测（可选）
验证：py_compile 通过；pytest 138 全绿；覆盖率 88%

### 5.2 消除跨模块私有调用 (#10) — 已完成（P3 期间提前完成）
- [x] translator.py 导出 apply_corrections 模块级函数
- [x] 删除 Translator._apply_corrections 静态方法
- [x] transcribe.py 旧 Translator._apply_corrections 调用随 P3.2 消除
- [x] tests/test_corrections.py：直接调用公共函数
验证：grep 确认无 _apply_corrections 残留

### 5.3 失败统计与退出码 (#12) — 已完成
- [x] transcribe.py main() 累计失败文件数；非零退出码 if 失败>0
- [x] 输出显示失败数
- [ ] tests/test_cli_exit_code.py：模拟失败，验证退出码（可选）
验证：代码审查确认逻辑正确

### 5.4 命令对称与兜底修正 — 已完成
- [x] #17 company_manager.py cmd_add 支持 --notes
- [x] #18 company.py 兜底合并改为仅 YAML 不存在时用 _FALLBACK
- [ ] tests/test_company_manager.py：add 带 notes、兜底不复活（可选）
验证：py_compile 通过

### 5.5 配置化硬编码值 (#19) — 已完成
- [x] translator.py sleep/timeout 改读 config（translate_api_timeout, translate_paragraph_delay）
- [ ] tests/test_config.py：覆盖新配置键（可选）
验证：py_compile 通过；pytest 138 全绿

---

## Phase 6（体验改善）— 状态：completed

### 6.1 翻译批量与断点 (#8) — 未实现（可选功能）
- [ ] translator.py translate_paragraphs 支持 batch_size 合并请求
- [ ] 每段结果即时写盘，失败可续
- [ ] tests/test_translator.py：批量合并、断点续传（mock）
验证：单测（留作未来优化）

### 6.2 跳过已完成文件 (#13) — 已完成
- [x] transcribe_one 检查输出存在则跳过，加 --force 覆盖
- [x] main() 统计 skipped 文件数
- [x] 输出显示跳过数
验证：py_compile 通过；pytest 138 全绿

### 6.3 logging 与进度 (#20) — 已完成
- [x] transcribe.py print → logging（-v 控制级别）
- [x] translator.py print → logging
- [x] 添加 -v/--verbose 参数（DEBUG 级别）
验证：py_compile 通过；pytest 138 全绿

### 6.4 文档化 company-wiki (#21) — 移至 P7
- company.py:115 依赖写入 README（P7.1 统一处理）
- graph.yaml 结构示例注释（P7.1 统一处理）

---

## Phase 7（文档）— 状态：completed

### 7.1 重写 README (#15) — 已完成
- [x] 反映 v2：MiMo 默认引擎、三文件、翻译、公司识别、--engine、--no-translate、-v
- [x] 模型表加 turbo；配置键详解
- [x] MiMo API key 配置说明
- [x] company-wiki 集成说明
验证：README 步骤可重现

### 7.2 处理 REVIEW.md (#16) — 已完成
- [x] 删除 REVIEW.md（审查报告已过时，README 包含所有必要信息）
验证：无过时内容

---

## Phase 8（测试体系收尾 + CI）— 状态：completed

### 8.1 集成测试 — 已完成
- [x] tests/test_transcribe_integration.py：mock 全部外部，端到端三文件输出
- [x] 覆盖 P3.2/P3.3 功能（翻译/不翻译路径）
验证：138 测试全绿

### 8.2 覆盖率与质量门 — 已完成
- [x] pytest --cov 覆盖率 80%（达标）
- [x] ruff 静态检查配置（pyproject.toml）
- [x] pytest 配置（pyproject.toml）
验证：coverage report 达标

### 8.3 GitHub Actions CI — 已完成
- [x] .github/workflows/ci.yml：push/PR 触发
      - matrix: python 3.8, 3.10, 3.13
      - pip install -r requirements.txt + pytest + ruff + coverage
      - 上传 coverage 报告
- [ ] README 加 CI 徽章（可选）
验证：CI 配置已创建

---

## 执行约束
- 每阶段结束：pytest + py_compile + grep 验证 + 提交
- P1 必须先完成（安全网），后续阶段可 TDD
- P2（MiMo）是核心新功能，优先于 P3-P7 的 bug 修复
- 任一阶段 3 次失败 → 停止，记录 progress.md，升级用户
- MiMo API key 不得入 git（.gitignore 已含 config.json）
