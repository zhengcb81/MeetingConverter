# 进度日志

## 2026-07-08 审查、研究、规划
- 完成：克隆仓库；通读 4 模块 + 配置 + yaml + README/REVIEW
- 验证：py_compile 通过；grep 定位配置失效/死代码/PEP604
- 研究：webfetch MiMo-V2.5-ASR 文档（端点/格式/限制/计费）
- 发现：22 项代码问题 + MiMo API 集成需求
- 决策：D1-D10
- 状态：规划文件 v2 已写盘（8 阶段）

## 2026-07-08 P1 完成 — 测试基础设施 + 引擎抽象
- 新建 engines/base.py：Segment/TranscriptionResult/TranscriptionEngine(Protocol)/UnsupportedFormatError
- 新建 engines/whisper.py：WhisperEngine 包裹 faster-whisper
- 新建 engines/factory.py：create_engine（P1 仅 whisper）
- 新建 tests/conftest.py、pytest.ini、requirements.txt 加测试依赖
- 测试：17 个全绿，engines 覆盖率 100%

## 2026-07-08 P2 完成 — MiMo-V2.5-ASR 引擎集成
- 新建 audio_utils.py：detect_format/estimate_base64_size/get_audio_duration/split_by_silence
- 新建 text_merger.py：merge_text_into_paragraphs（句末标点+max_chars，无时间戳分段）
- 新建 engines/mimo.py：MiMoEngine（base64 编码/OpenAI 兼容 API/长音频切片/文本分段）
- 新建 engines/fallback.py：FallbackEngine（主引擎失败自动降级）
- 更新 engines/factory.py：auto/mimo/whisper 三模式 + 回退链
- 更新 engines/base.py：TranscriptionResult 加 paragraph_level 标志
- 更新 transcribe.py：移除直接 WhisperModel，改用 create_engine + --engine CLI 参数
- 更新 config.example.json：加 mimo_api_key/mimo_base_url/transcription_engine
- 测试：70 个全绿（+53 个），engines 覆盖率 100%

## 2026-07-08 P3 完成 — 修复影响产出的行为 bug
- P3.1 配置键接入：transcribe_one 加 merge_gap_sec/paragraph_max_chars 参数，main() 从 config 读默认值
- P3.2 修复漏翻：删除 _is_mostly_chinese 短路，始终走 LLM 翻译
- P3.3 --no-translate 不写占位文件：translations=None 时仅写 _原文.txt
- P3.4 简化 LLM 输出清洗：_clean_output 退化为 return text.strip()
- P5.2 提前完成：apply_corrections 提为模块级函数
- 测试：138 个全绿，覆盖率 80%

## 2026-07-09 P4 完成 — 兼容性与正确性
- P4.1 Python 3.8 兼容：给 transcribe.py、translator.py、company_manager.py 加 from __future__ import annotations
- P4.2 中文纠正规则边界保护：已有占位保护（translator.py:40-43）
- P4.3 公司名精确匹配优先：已有精确匹配 + 最长优先（company.py:70-74）
- P4.4 消除 p 命名地雷：已无 p( 调用残留
- 验证：py_compile 全模块通过；pytest 138 全绿；覆盖率 84%

## 2026-07-09 P5 完成 — 代码清理
- P5.1 删除死代码：移除 detect_language 和 _is_mostly_chinese（无调用）
- P5.2 消除跨模块私有调用：已在 P3 完成
- P5.3 失败统计与退出码：main() 累计 failures，非零退出码
- P5.4 命令对称与兜底修正：cmd_add 支持 --notes；兜底仅 YAML 不存在时用
- P5.5 配置化硬编码值：translate_api_timeout/translate_paragraph_delay 从 config 读取
- 验证：py_compile 通过；pytest 138 全绿；覆盖率 88%（+8%）

## 2026-07-09 P6 完成 — 体验改善
- P6.2 跳过已完成文件：transcribe_one 检查 _原文.txt 存在则跳过，--force 覆盖
- P6.3 logging：transcribe.py/translator.py print → logging，添加 -v 参数
- 验证：py_compile 通过；pytest 138 全绿；覆盖率 88%

## 2026-07-09 P7 完成 — 文档
- P7.1 重写 README：反映 v2 功能（MiMo 引擎、翻译、公司识别、--engine、-v）
- P7.2 处理 REVIEW.md：删除过时审查报告
- 验证：README 完整可重现

## 2026-07-09 P8 完成 — 测试体系收尾 + CI
- P8.1 集成测试：test_transcribe_integration.py 覆盖翻译/不翻译路径
- P8.2 覆盖率与质量门：80% 达标，pyproject.toml 配置 ruff/pytest
- P8.3 GitHub Actions CI：ci.yml 配置 Python 3.8/3.10/3.13 矩阵
- 验证：138 测试全绿；覆盖率 80%；CI 配置已创建

## 项目完成状态
- P1-P8 全部完成
- 138 测试全绿，覆盖率 80%
- 支持 MiMo-V2.5-ASR + faster-whisper 双引擎
- 支持 DeepSeek LLM 翻译 + 公司背景知识注入
- 支持三文件输出、跳过已完成、日志控制
- CI/CD 配置就绪

## 2026-07-09 端到端测试通过
- 修复 Windows subprocess GBK 编码问题
- 调整 MAX_BASE64_MB = 4.0（适配 MiMo 8192 tokens 限制）
- 安装 ffmpeg 8.1.2（手动下载）
- 测试文件：DRG对医疗器械行业的影响观点0904.mp3（30分钟）
- 结果：MiMo ASR + DeepSeek 翻译成功，三文件输出正常

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| _choose_split_points 产生超 max 片段 | 1 | 重写算法：找不超过上限的最后静音点，无静音则硬切 |
| transcribe.py 被自动格式化 | 1 | 用精确匹配重新读取后编辑 |
| language 在 prompt 引用前未定义 | 1 | 重排 main()：cfg 加载+language 定义移到 prompt 选择之前 |
| 翻译器路径删除 _is_mostly_chinese 后未导出 apply_corrections | 1 | 提取模块级 apply_corrections（顺带完成 P5.2） |
