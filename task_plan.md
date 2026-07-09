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

## Phase 1（职责分离重构）— 状态：pending

### 1.1 拆分 transcribe.py
- [ ] 新建 core/ 目录
- [ ] core/pipeline.py：transcribe_one 主流程（从 transcribe.py 提取）
- [ ] core/batch.py：批量调度 + 进度统计（从 main() 提取）
- [ ] core/output.py：write_original/write_translated/write_bilingual
- [ ] core/formatter.py：fmt_ts 格式化函数
验证：py_compile 通过；pytest 全绿；transcribe.py < 100 行

### 1.2 迁移 Paragraph 类
- [ ] Paragraph 类移到 text_merger.py
- [ ] merge_into_paragraphs 移到 text_merger.py
- [ ] transcribe.py 从 text_merger 导入
验证：段落合并逻辑完全在 text_merger.py

### 1.3 更新测试
- [ ] tests/test_pipeline.py：测试核心流程
- [ ] tests/test_output.py：测试文件输出
- [ ] tests/test_batch.py：测试批量调度
验证：新测试全绿；覆盖率不下降

---

## Phase 2（类型系统统一 + 测试补充）— 状态：pending

### 2.1 统一 Segment 类型
- [ ] Paragraph.segments 改为 List[Segment]（而非 dict）
- [ ] add_segment 接收 Segment 对象
- [ ] 更新所有调用点
验证：类型一致；py_compile 通过

### 2.2 补充 transcribe 测试
- [ ] 测试翻译失败路径
- [ ] 测试音频切片失败路径
- [ ] 测试 --force 覆盖
- [ ] 测试批量处理部分失败
验证：transcribe 覆盖率 > 80%

### 2.3 边界测试
- [ ] 空文件处理
- [ ] 特殊字符文件名
- [ ] 超大文件（>2小时）
- [ ] 损坏音频文件
验证：边界情况有明确错误信息

### 2.4 company_manager.py 测试
- [ ] 测试 list/show/add/update/correct 命令
- [ ] 测试错误输入处理
验证：company_manager 覆盖率 > 50%

---

## Phase 3（错误处理统一）— 状态：pending

### 3.1 定义错误层级
- [ ] 新建 exceptions.py
- [ ] MeetingConverterError (基类)
- [ ] TranscriptionError
- [ ] TranslationError
- [ ] EngineError
- [ ] ConfigError
验证：所有自定义异常继承基类

### 3.2 翻译错误处理
- [ ] translate_paragraph 失败抛 TranslationError
- [ ] transcribe_one 捕获并记录，不写占位文件
- [ ] 更新测试验证异常传播
验证：翻译失败不产生 [翻译失败] 占位符

### 3.3 MiMo API 重试
- [ ] mimo.py _call_api 添加指数退避重试
- [ ] 最大重试 3 次，初始等待 2 秒
- [ ] 重试耗尽后抛 EngineError
验证：临时网络错误自动恢复

### 3.4 配置验证
- [ ] 新建 config_validator.py
- [ ] 验证 API key 格式
- [ ] 验证 URL 格式
- [ ] 验证数值范围
验证：无效配置提前报错，而非运行时崩溃

---

## Phase 4（配置系统重构）— 状态：pending

### 4.1 简化配置加载
- [ ] 移除 ~/earnings-transcripts 搜索路径
- [ ] 统一配置入口：config.py
- [ ] 配置验证集中处理
验证：配置加载逻辑清晰，无隐式合并

### 4.2 配置数据类
- [ ] 新建 config.py
- [ ] @dataclass Config
- [ ] 从 dict 构造，带默认值
- [ ] 类型安全的访问
验证：config.deepseek_api_key 而非 config.get("deepseek_api_key")

### 4.3 配置文档
- [ ] config.example.json 添加注释
- [ ] 每个键说明默认值、范围、必填性
验证：新用户可独立配置

---

## Phase 5（扩展性增强）— 状态：pending

### 5.1 插件化引擎
- [ ] 新建 engines/registry.py
- [ ] @register_engine 装饰器
- [ ] 自动发现 engines/ 下的引擎
- [ ] factory.py 使用 registry
验证：添加新引擎无需修改 factory.py

### 5.2 性能监控
- [ ] 新建 metrics.py
- [ ] TranscribeMetrics dataclass
- [ ] 记录 STT/翻译/输出耗时
- [ ] 计算 RTF (Real-Time Factor)
验证：每次转写输出性能指标

### 5.3 真实 API 测试
- [ ] @pytest.mark.network 标记
- [ ] 默认跳过，CI 可配置运行
- [ ] 测试 MiMo + DeepSeek 真实调用
验证：手动运行可验证真实 API

---

## Phase 6（文档完善）— 状态：pending

### 6.1 架构文档
- [ ] README 添加架构图（ASCII 或 Mermaid）
- [ ] 模块职责说明
- [ ] 数据流图
验证：新人可快速理解项目结构

### 6.2 故障排除指南
- [ ] TROUBLESHOOTING.md
- [ ] 常见错误及解决方案
- [ ] API key 配置问题
- [ ] ffmpeg 安装问题
验证：用户可自助解决常见问题

### 6.3 贡献指南
- [ ] CONTRIBUTING.md
- [ ] 如何添加新引擎
- [ ] 如何添加新翻译器
- [ ] 代码风格要求
验证：外部贡献者可参与开发

### 6.4 配置参考
- [ ] CONFIG.md
- [ ] 所有配置键详解
- [ ] 默认值、范围、示例
验证：配置文档完整

---

## 执行约束
- 每阶段结束：pytest + py_compile + 提交
- P0 必须先完成（快速修复）
- P1 是核心重构，后续阶段依赖
- 任一阶段 3 次失败 → 停止，记录 progress.md
- 保持向后兼容：CLI 接口不变

## 成功指标
| 指标 | 当前 | 目标 |
|------|------|------|
| transcribe.py 行数 | 425 | < 100 |
| 测试覆盖率 | 80% | > 85% |
| transcribe 覆盖率 | 55% | > 80% |
| company_manager 覆盖率 | 0% | > 50% |
| 最大函数行数 | 60+ | < 30 |
| 错误处理一致性 | 不一致 | 统一异常层级 |
