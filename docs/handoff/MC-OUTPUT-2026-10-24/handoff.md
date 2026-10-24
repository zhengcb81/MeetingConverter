# HANDOFF — MC-OUTPUT-INTEGRITY：会议转写输出的完整性与安全写入

Status: DONE（独立审查 PASS-with-findings → 发现全部处置 → 最终 SHA 复审 PASS）
Card: `company-wiki:docs/plans/du11-source-closure-2026-10-18/harness_lanes/20261024-independent/MC-OUTPUT-INTEGRITY.md`
日期：2026-10-24
仓库：`C:/Users/郑曾波/Projects/MeetingConverter`
Worktree：`C:/Users/郑曾波/Projects/MeetingConverter-output-integrity`（独立 worktree）
分支：`codex/meetingconverter-output-integrity-20261024`（未合并、未推送）

## 1. SHA

| 项 | SHA |
|---|---|
| base（开工基准 = origin/master = 本地 master） | `8a33a7f96292af8e6574d98b959703c6d11919eb` |
| 代码交付 head（复审 PASS 对象） | `efbb51da26b98e990f97817a88e2b16bc66bb2f8` |
| 复审记录 commit | `f2de135`（docs-only） |
| 分支 tip | 本 handoff 所在的 docs-only commit（其后仅文档变更，代码 head 仍为 `efbb51d`） |

分支提交（8a33a7f..tip）：

- `ad620c1` fix: 输出长度校验防 zip 静默截断，三 writer 改为临时文件原子写入
- `66e31db` test: 独立审查写盘失败反例（flush 阶段失败与临时文件创建失败保留旧字节）
- `604b6ca` docs: 独立审查报告
- `efbb51d` fix: 独立审查发现修复——close 失败强关 fd 兜底清理，异常附结构化计数
- `f2de135` docs: 复审记录（最终 SHA efbb51d）
- docs-only：本 handoff + plan.md 权限措辞更正（复审 info #6）+ STATUS ALL-DONE

## 2. 根因与修复

冻结点 `core/output.py`：译文/双语 writer 用 `zip(paragraphs, translations)`，
长度不等时静默丢弃多出尾段；三个 writer 以 `open(path, "w")` 直写最终路径，
写盘阶段失败会把旧结果截断成半份文件。

修复（只动输出边界，未改识别/ASR/批处理/翻译策略）：

1. **先校验后写盘**：渲染入口（任何临时文件创建之前）校验
   `len(paragraphs) == len(translations)`，不符抛
   `OutputCountMismatchError`（`ValueError` 子类，带 `expected`/`actual`
   结构化属性，消息含 `expected {N}, actual {M}`）。
2. **内存完整渲染 → 原子写入**：三 writer 先渲染完整字符串（格式与旧版
   逐行一致），再经 `_atomic_write_text`：同目录临时文件
   （`tempfile.NamedTemporaryFile`，`dir=path.parent` 同卷保证）→
   `write` → `flush` → `close` → `os.replace` 原子替换。
3. **失败清理与旧字节保留**：渲染/工厂/写入/flush/close/replace 任一
   阶段异常都会删除临时文件、原样保留目标旧字节、裸 `raise` 原始异常；
   `close()` 自身失败时 `os.close(handle.fileno())` 强关底层 fd 使
   Windows 仍可 unlink（极端不可关时可能残留临时件，但目标旧字节
   始终安全）。
4. **非事务边界（显式声明）**：三输出文件之间没有跨文件原子性，
   pipeline 按原文→翻译→对照顺序写，中途失败留下"部分新+部分旧"，
   需调用方整体重跑。未建多文件事务框架。

有意的行为变化：输出字节统一 LF（旧 Windows 为 CRLF）；POSIX 上
最终文件权限为临时件 inode 的 0600（详见 plan.md"已知的行为变化"）。

## 3. 测试与验收（精确范围）

`tests/test_output.py` 57 用例（含独立审查方追加 6 个反例 + 实现方
4 个），全部输入/输出仅在 pytest `tmp_path`，合成 Paragraph/Segment，
未触发 MiMo/DeepSeek、网络与真实音频；每用例前后记录目录快照
（相对路径 → SHA-256），autouse 断言无 `*.tmp` 孤儿。

验收命令（原样）与结果：

    python -B -m pytest -q -o addopts="" tests/test_output.py
    → 57 passed（终值，无 warning；实现点 47、审查反例后 53、修复后 57）

    python -B -m ruff check core/output.py tests/test_output.py
    → All checks passed!（顺带消除基线既存 F401/I001 两项）

覆盖矩阵：成功输出/逐段按序/UTF-8 中英混合、时间戳开关、空/单/多段、
译文长度不足与过量（写盘前显式失败、expected/actual、旧字节 SHA 不变）、
渲染中途异常、写盘中途失败（孤立代理字符真实 UnicodeEncodeError）、
flush 阶段失败、close 阶段失败（fd 强关）、临时文件工厂失败、
os.replace 失败（monkeypatch）、Windows 真实占用（真句柄 → 真实
PermissionError，win32 only）、成功重跑整体覆盖、失败后重试恢复、
无孤儿临时文件、错误契约。

附带只读回归（非验收命令）：`tests/test_pipeline.py` → 19 passed。

**范围声明**：以上仅为本卡聚焦测试与两文件 lint，**不**等价于全仓
coverage ≥80% 门通过，也**未**推送远端、**未**运行远端 CI；
`.github/workflows/**` 零改动（`git diff --name-status 8a33a7f..tip`
可核：仅 core/output.py、tests/test_output.py 与本卡 docs）。

## 4. 独立审查与复审

- 审查人：未参与实现的独立 agent；报告
  `docs/plans/meetingconverter-output-integrity-2026-10-24/review-independent.md`。
- 初审：PASS-with-findings（1 minor + 4 info，无 blocker/major）；
  四个重点挑战（zip 截断、Windows 替换语义、失败清理、旧字节保留）
  逐项成立；审查方自行运行验收命令并追加 6 个写盘失败反例（6/6 过）。
- 发现处置：minor #1（close 失败残留 tmp）→ 修复 + 3 用例验证；
  info #2（结构化属性）→ 已加；info #3（POSIX 0600）→ plan.md 补记；
  info #4/#5（LF 换行、非事务边界）→ 已声明；复审新增 info #6
  （plan.md 权限措辞）→ 本 handoff 批次已更正。
- 复审（最终 SHA `efbb51d`）：**PASS**——强关 fd 分支经 Windows 实证
  （打开态 unlink 报 WinError 32，强关后成功）、反例测试有判别力、
  原样重跑 57 passed 无 warning、范围合规、原仓未动。复审章节见
  报告末尾，commit `f2de135`。

## 5. 原仓与环境保护

- 原仓 `C:/Users/郑曾波/Projects/MeetingConverter`：全程只读。
  派卡时既存修改 `M .coverage` **保持原状**（未复制、未暂存、未覆盖、
  未删除），且**不在**本分支任何提交中（本分支全部提交不含
  `.coverage`，`git log --all -- .coverage` 于本分支为空）。
- 原仓 HEAD 全程保持 `8a33a7f96292af8e6574d98b959703c6d11919eb`
  （= origin/master，无移动）。
- 临时目录恢复证据（终检于交付时）：本卡专属 basetemp 证据运行
  `--basetemp=/tmp/mc-output-integrity-evidence`（57 passed）后全树
  扫描 `*.tmp` 孤儿 = 0，证据目录随即删除（系统临时区恢复）；系统
  TEMP 根无本卡临时文件残留（命名模式 `.{目标名}.…….tmp`）；测试
  输入/输出仅存在于 pytest 自管 tmp_path。附注：共享
  `/tmp/pytest-of-*/pytest-*` 根下偶见其他并行 lane（vector 套件
  `active.json.tmp`）的目录，非本卡产物；本卡各次 verbatim 运行当期
  目录均已核为 0 孤儿。

## 6. 交付物清单

- `core/output.py` — 修复本体（ad620c1 + efbb51d）
- `tests/test_output.py` — 57 用例（ad620c1 + 66e31db + efbb51d）
- `docs/plans/meetingconverter-output-integrity-2026-10-24/plan.md` —
  计划、设计边界、测试矩阵、运行记录（含权限措辞更正）
- `docs/plans/meetingconverter-output-integrity-2026-10-24/review-independent.md` —
  独立审查报告 + 最终 SHA 复审 PASS 记录
- `docs/plans/meetingconverter-output-integrity-2026-10-24/STATUS.md` —
  可恢复执行状态（ALL-DONE）
- `docs/handoff/MC-OUTPUT-2026-10-24/handoff.md` / `handoff.json` — 本交接
