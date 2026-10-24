# 计划 — MC-OUTPUT-INTEGRITY：会议转写输出的完整性与安全写入

Card: `company-wiki docs/plans/du11-source-closure-2026-10-18/harness_lanes/20261024-independent/MC-OUTPUT-INTEGRITY.md`
日期：2026-10-24
仓库：`C:/Users/郑曾波/Projects/MeetingConverter`
独立工作目录：`C:/Users/郑曾波/Projects/MeetingConverter-output-integrity`（独立 worktree）
分支：`codex/meetingconverter-output-integrity-20261024`，基准 `master@8a33a7f96292af8e6574d98b959703c6d11919eb`（= origin/master）

## 根因

冻结点 `core/output.py` 存在两个输出完整性缺陷：

1. **zip 静默截断**：`write_translated` / `write_bilingual` 用
   `zip(paragraphs, translations)` 逐段输出。两者长度不等时，多出的
   尾段被静默丢弃，产出“看似成功”的不完整文件，无任何报错。
2. **覆盖式直写**：三个 writer 都以 `open(path, "w")` 直接打开最终
   路径。渲染中途异常（如段落属性抛错）发生在截断之后无影响，但
   任何写盘阶段失败都会把旧结果截断成半份文件；目标旧字节丢失。

## 修正设计（只动输出边界）

- **先校验后写盘**：`_check_paired_lengths` 在渲染入口（即任何临时
  文件创建之前）比对 `len(paragraphs)` 与 `len(translations)`，不等
  即抛 `OutputCountMismatchError`（`ValueError` 子类），消息含
  `expected {段落数}, actual {译文数}`。
- **内存完整渲染**：三个 writer 先各自把全文渲染成完整字符串
  （`_render_original/_translated/_bilingual`，输出格式与旧版逐行
  一致），格式化中途异常在任何磁盘动作之前发生，旧文件零接触。
- **同目录临时文件 + 原子替换**：`_atomic_write_text` 用
  `tempfile.NamedTemporaryFile(dir=path.parent, prefix=".{name}.",
  suffix=".tmp", delete=False)` 写入，`flush()` + `close()` 成功后
  `os.replace(tmp, path)`。临时文件与目标同目录即同文件系统，
  `os.replace` 在 POSIX 与 Windows 上都是原子替换（Windows 为
  `MoveFileExW(MOVEFILE_REPLACE_EXISTING)`）。
- **失败清理**：渲染、写入、flush/close、replace 任一阶段异常都会
  关闭未关句柄、删除临时文件并原样保留目标旧字节（`except
  BaseException` 兜底含 KeyboardInterrupt；清理自身的 OSError 不
  吞掉原始异常）。
- **成功即覆盖**：目标存在时成功路径照常整体替换为新内容。

明确不做的事：

- 不建多文件事务框架。三个输出文件之间**没有**跨文件原子性：
  pipeline 按 原文→翻译→对照 顺序调用，中途失败会留下“部分新文件
  + 部分旧文件”组合，需要调用方整体重跑。该边界已写入
  `core/output.py` 模块 docstring。
- 不改识别、ASR、批处理、翻译策略，不动 pipeline/batch/engines/
  translator/CI。

已知的行为变化（有意为之）：临时文件以 `newline=""` 写入，输出字节
统一为 LF；旧实现 Windows 上默认转换成 CRLF。内容语义不变，换来
跨平台确定的字节指纹（利于 SHA 校验与 diff）。

## 测试矩阵（tests/test_output.py，47 用例）

全部输入/输出仅在 pytest `tmp_path`；合成 `Paragraph`/`Segment`，
不触发 MiMo/DeepSeek、网络与真实音频。每用例前后记录目录快照
（相对路径 → SHA-256）作为开始/结束清单；autouse fixture 断言结束
时无 `*.tmp` 残留。

| 场景 | 覆盖 |
|---|---|
| 成功输出/逐段/UTF-8 | 三 writer × 正文逐条按序出现（中/英/混合），字节可 UTF-8 解码，快照=唯一目标文件 |
| 时间戳开关 | 三 writer × on/off，on 时三段时间戳齐全，off 时无时间戳行 |
| 空/单/多段 | 三 writer × 3 档；空段=仅表头、无正文标记 |
| 长度不足/过量 | 译文 -1/+1：在任何写盘前抛错（目录快照为空）、消息含 expected/actual、已存在目标字节不变 |
| 零段一译 | expected 0, actual 1 |
| 渲染中途异常 | `BoomParagraph.start` 抛 RuntimeError（timestamps=True 下三 writer 都读该属性）；旧字节保留 |
| 临时写入失败 | 段/译文含孤立代理字符 `\ud800` → 真实 `UnicodeEncodeError` 发生在 `write()` 中途；旧字节保留、临时文件被清理 |
| 替换失败（可移植） | monkeypatch `core.output.os.replace` 抛 OSError；旧字节保留、无残留 |
| Windows 真实占用 | 目标被另一句柄打开（`open()` 未含 FILE_SHARE_DELETE）→ 真实 `PermissionError`；旧字节保留（win32 only，已实证 WinError 5） |
| 成功重跑覆盖 | 旧正文文本全部消失、新正文完整、快照唯一文件、SHA 变化 |
| 失败后重试成功 | 先失败保留 `old bytes`，再成功后完整新文件且失败批次文本不存在 |
| 错误契约 | `OutputCountMismatchError` 是 `ValueError` 子类 |

## 运行记录（本卡精确范围）

    python -B -m pytest -q -o addopts="" tests/test_output.py
    → 47 passed in 1.49s（Windows，Python 3.13.9，pytest 9.1.1）

    python -B -m ruff check core/output.py tests/test_output.py
    → All checks passed!（ruff 0.15.18；顺带修复基线既存 F401/I001）

附带只读回归（非验收命令）：`tests/test_pipeline.py` → 19 passed。

范围声明：以上仅覆盖本卡聚焦测试与两文件 lint，**不**等价于全仓
coverage ≥80% 门通过，也**未**推远端、**未**跑远端 CI；`.github/
workflows/**` 零改动（`git status` 仅 `core/output.py`、
`tests/test_output.py` 与本卡 docs）。

## 边界与证据

- 基线（开工前）：冻结点测试 6 passed；ruff 基线 2 个既存错误
  （`Optional` 未用、测试 import 排序），均在改写范围内被移除。
- Windows `os.replace` 语义实证：目标被普通 `open()` 句柄持有时
  replace 抛 `WinError 5`，目标字节保持 `old`、临时文件仍在（由
  本实现清理）——见 `tests/test_output.py` win32 专用用例。
- 代理字符实证：UTF-8 文本句柄 `write("\ud800")` 立即抛
  `UnicodeEncodeError` 且句柄未自动关闭——真实写盘中途失败路径。
