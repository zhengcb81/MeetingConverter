# MeetingConverter 架构改进计划 v3

## 目标
基于全面审查，重构项目架构，提升可测试性、可维护性和扩展性。

分 6 个阶段推进，每阶段独立可验证、可提交。

## 审查发现汇总

### 架构问题
| ID | 问题 | 严重性 | 阶段 |
|----|------|--------|------|
| A1 | transcribe.py 职责过多（425行，5+职责） | 高 | P1 |
| A2 | 类型系统不一致（Segment vs dict） | 中 | P2 |
| A3 | 回退逻辑不完整（仅捕获 UnsupportedFormatError） | 高 | P3 |
| A4 | 配置加载逻辑混乱（4路径+隐式合并） | 中 | P4 |

### 代码问题
| ID | 问题 | 严重性 | 阶段 |
|----|------|--------|------|
| C1 | company.py:129 死代码 | 高 | P0 |
| C2 | text_merger.py:10 无用常量 MAX_BASE64_MB | 中 | P0 |
| C3 | 临时文件未清理 | 高 | P0 |
| C4 | MiMo API 无重试机制 | 中 | P3 |
| C5 | 翻译失败返回占位符而非异常 | 中 | P3 |

### 测试问题
| ID | 问题 | 严重性 | 阶段 |
|----|------|--------|------|
| T1 | transcribe.py 覆盖率 55% | 高 | P2 |
| T2 | company_manager.py 覆盖率 0% | 中 | P2 |
| T3 | 无真实 API 集成测试 | 中 | P5 |
| T4 | 缺少边界测试（超长/损坏/空文件） | 中 | P2 |

### 文档问题
| ID | 问题 | 严重性 | 阶段 |
|----|------|--------|------|
| D1 | 无架构图 | 中 | P6 |
| D2 | 无故障排除指南 | 中 | P6 |
| D3 | 无贡献指南 | 低 | P6 |
| D4 | 无配置参考文档 | 中 | P6 |

---

## Phase 0（快速修复）— 状态：pending

### 0.1 清理死代码
- [ ] company.py:129-133 删除死代码（return 之后的代码）
- [ ] text_merger.py:10 删除无用常量 MAX_BASE64_MB
验证：py_compile 通过；grep 确认无死代码

### 0.2 修复临时文件泄漏
- [ ] audio_utils.py split_by_silence 使用 tempfile.NamedTemporaryFile
- [ ] 或在 transcribe_one 完成后清理切片文件
验证：转写完成后 tempdir 无 mimo_chunk_* 残留

### 0.3 FallbackEngine 增强
- [ ] 捕获所有异常（不仅是 UnsupportedFormatError）
- [ ] 添加日志：回退原因
验证：MiMo 超时时自动回退 Whisper

---

## Phase 1（职责分离重构）— 状态：complete

### 1.1 拆分 transcribe.py
- [x] 新建 core/ 目录
- [x] core/pipeline.py：transcribe_one 主流程（从 transcribe.py 提取）
- [x] core/batch.py：批量调度 + 进度统计（从 main() 提取）
- [x] core/output.py：write_original/write_translated/write_bilingual
- [x] core/formatter.py：fmt_ts 格式化函数
验证：py_compile 通过；pytest 138 全绿；transcribe.py 从 426 行减至 142 行

### 1.2 迁移 Paragraph 类
- [x] Paragraph 类和 merge_into_paragraphs 移到 core/pipeline.py（与 transcribe_one 共处，因为它们是 pipeline 的核心逻辑）
- [x] transcribe.py 从 core 模块导入
验证：职责分离完成，transcribe.py 仅剩 CLI 入口

### 1.3 更新测试
- [x] tests/test_pipeline.py：测试核心流程（Paragraph、merge_into_paragraphs、transcribe_one）
- [x] tests/test_output.py：测试文件输出（write_original、write_translated、write_bilingual）
- [x] tests/test_batch.py：测试批量调度（get_audio_files、run_batch）
验证：167 测试全绿；覆盖率 87.35%

---

## Phase 2（类型系统统一 + 测试补充）— 状态：complete

### 2.1 统一 Segment 类型
- [x] Paragraph.segments 改为 List[Segment]（而非 dict）
- [x] add_segment 接收 Segment 对象
- [x] 更新所有调用点
验证：186 测试全绿；类型一致

### 2.2 补充 transcribe 测试
- [x] 测试翻译失败路径
- [x] 测试音频切片失败路径
- [x] 测试 --force 覆盖
- [x] 测试批量处理部分失败
验证：transcribe 覆盖率 > 80%

### 2.3 边界测试
- [x] 空文件处理
- [x] 特殊字符文件名
- [x] 超大文件（>2小时）
- [x] 损坏音频文件（引擎错误传播）
验证：边界情况有明确错误信息

### 2.4 company_manager.py 测试
- [x] 测试 list/show/add/update/correct 命令
- [x] 测试错误输入处理
验证：company_manager 13 个测试全绿

---

## Phase 3（错误处理统一）— 状态：complete

### 3.1 定义错误层级
- [x] 新建 exceptions.py
- [x] MeetingConverterError (基类)
- [x] TranscriptionError
- [x] TranslationError
- [x] EngineError
- [x] ConfigError
验证：所有自定义异常继承基类

### 3.2 翻译错误处理
- [x] translate_paragraph 失败抛 TranslationError
- [x] transcribe_one 捕获并记录，不写占位文件
- [x] 更新测试验证异常传播
验证：翻译失败跳过翻译文件，原文仍创建

### 3.3 MiMo API 重试
- [x] mimo.py _call_api 添加指数退避重试
- [x] 最大重试 3 次，初始等待 2 秒
- [x] 重试耗尽后抛 EngineError
验证：194 测试全绿

### 3.4 配置验证
- [x] 新建 config_validator.py
- [x] 验证 API key 格式
- [x] 验证 URL 格式
- [x] 验证数值范围
验证：8 个配置验证测试全绿

---

## Phase 4（配置系统重构）— 状态：complete

### 4.1 简化配置加载
- [x] 移除 ~/earnings-transcripts 搜索路径
- [x] 统一配置入口：config.py
- [x] 配置验证集中处理
验证：配置加载逻辑清晰，无隐式合并

### 4.2 配置数据类
- [x] 新建 config.py
- [x] @dataclass Config
- [x] 从 dict 构造，带默认值
- [x] 类型安全的访问
验证：Config.load() 一站式加载+验证

### 4.3 配置文档
- [x] config.example.json 添加注释
- [x] 每个键说明默认值、范围、必填性
验证：194 测试全绿

---

## Phase 5（扩展性增强）— 状态：in_progress

### 5.1 插件化引擎
- [ ] 新建 engines/registry.py
- [ ] @register_engine 装饰器
- [ ] 自动发现 engines/ 下的引擎
- [ ] factory.py 使用 registry
验证：添加新引擎无需修改 factory.py

### 5.2 性能监控
- [x] 新建 metrics.py
- [x] TranscribeMetrics dataclass
- [x] 记录 STT/翻译/输出耗时
- [x] 计算 RTF (Real-Time Factor)
验证：transcribe_one 输出性能摘要

### 5.3 真实 API 测试
- [ ] @pytest.mark.network 标记
- [ ] 默认跳过，CI 可配置运行
- [ ] 测试 MiMo + DeepSeek 真实调用
验证：手动运行可验证真实 API

---

## Phase 6（文档完善）— 状态：complete

### 6.1 架构文档
- [x] README 添加架构图（ASCII）
- [x] 模块职责说明
- [x] 数据流图
验证：README 包含完整架构概览

### 6.2 故障排除指南
- [x] TROUBLESHOOTING.md
- [x] 常见错误及解决方案
- [x] API key 配置问题
- [x] ffmpeg 安装问题
验证：涵盖 MiMo/Whisper/翻译/配置/音频/编码/性能问题

### 6.3 贡献指南
- [x] CONTRIBUTING.md
- [x] 如何添加新引擎
- [x] 如何添加新翻译器
- [x] 代码风格要求
验证：包含完整贡献流程

### 6.4 配置参考
- [x] CONFIG.md
- [x] 所有配置键详解
- [x] 默认值、范围、示例
验证：配置文档完整

---

## 执行约束
- 每阶段结束：pytest + py_compile + 提交
- P0 必须先完成（快速修复）
- P1 是核心重构，后续阶段依赖
- 任一阶段 3 次失败 → 停止，记录 progress.md
- 保持向后兼容：CLI 接口不变

## 成功指标
| 指标 | 改进前 | 目标 | 改进后 |
|------|--------|------|--------|
| transcribe.py 行数 | 425 | < 100 | 161 (仅 CLI 入口) |
| 测试数量 | 138 | - | 194 |
| 测试覆盖率 | 87% | > 85% | 88% |
| 错误处理一致性 | 不一致 | 统一异常层级 | ✅ exceptions.py |
| 类型一致性 | dict/Segment 混用 | 统一 Segment | ✅ |
| 配置验证 | 无 | 提前报错 | ✅ config_validator.py |
| 性能监控 | 无 | RTF 指标 | ✅ metrics.py |
| 文档完整性 | 基础 | 完整 | ✅ 4 个文档 |
