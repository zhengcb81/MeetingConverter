# MeetingConverter 审查发现

## F1: transcribe.py 职责过多
- 日期：2026-07-09
- 位置：transcribe.py (425行)
- 问题：
  - 主入口 + 段落合并 + 文件I/O + 格式化 + 批量调度
  - Paragraph 类不应在此文件
  - write_* 函数应独立
  - 无法独立测试文件输出逻辑
- 影响：可测试性差，修改一处可能影响全局
- 建议：拆分为 core/pipeline.py + core/output.py + core/batch.py + core/formatter.py

## F2: 类型系统不一致
- 日期：2026-07-09
- 位置：transcribe.py:84 vs engines/base.py:10
- 问题：
  - Paragraph 用 dict 列表存储 segments
  - Segment 已定义为 dataclass
  - 两套类型系统混用
- 影响：类型不安全，IDE 无法提供完整提示
- 建议：Paragraph.segments 改为 List[Segment]

## F3: 回退逻辑不完整
- 日期：2026-07-09
- 位置：engines/fallback.py:26
- 问题：
  - 只捕获 UnsupportedFormatError
  - MiMo API 超时、网络错误、429 限流不触发回退
- 影响：网络不稳定时直接失败，而非降级到 Whisper
- 建议：捕获所有异常，记录日志后回退

## F4: company.py 死代码
- 日期：2026-07-09
- 位置：company.py:129-133
- 问题：
  - return 语句之后还有代码
  - 永远不会执行
- 影响：代码混淆，维护者困惑
- 建议：删除死代码

## F5: text_merger.py 无用常量
- 日期：2026-07-09
- 位置：text_merger.py:10
- 问题：
  - MAX_BASE64_MB = 9.5 是 audio_utils 的常量
  - text_merger.py 不需要此常量
- 影响：误导，暗示两个模块有关联
- 建议：删除

## F6: 临时文件未清理
- 日期：2026-07-09
- 位置：audio_utils.py:133
- 问题：
  - 切片文件写入 tempdir
  - 处理完成后不清理
  - 长期运行会累积大量临时文件
- 影响：磁盘空间泄漏
- 建议：使用 tempfile.NamedTemporaryFile 或处理后清理

## F7: MiMo API 无重试
- 日期：2026-07-09
- 位置：engines/mimo.py:121
- 问题：
  - translator.py 有重试机制
  - mimo.py 没有
  - 临时网络错误直接失败
- 影响：网络不稳定时用户体验差
- 建议：添加指数退避重试

## F8: 翻译错误处理不一致
- 日期：2026-07-09
- 位置：translator.py:90
- 问题：
  - 翻译失败返回 "[翻译失败] {text}" 占位符
  - transcribe.py 不检查，直接写入输出文件
  - 用户看到乱七八糟的输出
- 影响：输出质量下降
- 建议：抛 TranslationError，由调用方决定处理

## F9: 配置加载逻辑混乱
- 日期：2026-07-09
- 位置：translator.py:142-172
- 问题：
  - 搜索 4 个路径（含历史遗留 ~/earnings-transcripts）
  - 隐式合并 API key 的逻辑难以理解
  - 配置验证分散在各处
- 影响：配置问题难以排查
- 建议：统一配置入口，移除历史路径

## F10: 测试覆盖不均
- 日期：2026-07-09
- 位置：tests/
- 问题：
  - engines/ 100% 覆盖
  - transcribe.py 仅 55%
  - company_manager.py 0%
  - 缺少边界测试
- 影响：重构信心不足
- 建议：补充测试到 80%+

## F11: 无真实 API 测试
- 日期：2026-07-09
- 位置：tests/
- 问题：
  - 所有测试 mock 外部依赖
  - 无法发现真实 API 问题
- 影响：部署后才发现 API 兼容性问题
- 建议：添加 @pytest.mark.network 真实测试

## F12: 文档不完整
- 日期：2026-07-09
- 位置：README.md
- 问题：
  - 无架构图
  - 无故障排除指南
  - 无贡献指南
  - 无配置参考
- 影响：新人上手困难
- 建议：补充文档

## F13: 无插件系统
- 日期：2026-07-09
- 位置：engines/factory.py
- 问题：
  - 添加新引擎需修改 factory.py
  - 硬编码引擎选择逻辑
- 影响：扩展性差
- 建议：插件化引擎注册

## F14: 无性能监控
- 日期：2026-07-09
- 位置：transcribe.py
- 问题：
  - 只输出总耗时
  - 无 STT/翻译/输出分段耗时
  - 无 RTF 计算
- 影响：无法量化性能，难以优化
- 建议：添加 TranscribeMetrics

## F15: 日志不够结构化
- 日期：2026-07-09
- 位置：transcribe.py:59
- 问题：
  - log() 只是 logger.info 包装
  - 无结构化字段（文件名、耗时、段落数）
- 影响：难以做日志分析
- 建议：使用 structured logging
