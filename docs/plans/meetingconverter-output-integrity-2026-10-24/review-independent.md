# 独立审查报告 — MC-OUTPUT-INTEGRITY

- 审查人：独立代码审查 agent（未参与实现）
- 日期：2026-10-24
- worktree：`C:/Users/郑曾波/Projects/MeetingConverter-output-integrity`，分支 `codex/meetingconverter-output-integrity-20261024`
- 冻结基准：`8a33a7f96292af8e6574d98b959703c6d11919eb`（= origin/master）；实现提交 `ad620c1`
- 审查对象：`git diff 8a33a7f96292af8e6574d98b959703c6d11919eb..HEAD`，涉及 `core/output.py`、`tests/test_output.py`、`docs/plans/meetingconverter-output-integrity-2026-10-24/plan.md`

## 审查方法

1. 逐行审阅 `core/output.py` 新实现全文与完整 diff；
2. 全仓 grep 核对三个 writer 的全部调用方与生产代码中所有 `zip(paragraphs, translations)` 使用点，排查绕过路径；
3. 对照 plan.md 的设计声明逐项验证实现与测试是否兑现；
4. 质疑测试真实性：代理字符用例的失败阶段、快照是否逐字节 SHA、autouse 孤儿扫描是否匹配实现的临时文件命名；
5. 原样运行两条验收命令并复跑；
6. 追加独立反例测试（flush 阶段失败、临时文件工厂失败），在当前实现下运行验证；
7. `git diff --stat` / `--name-status` 逐文件核对写入范围。

## 四个重点挑战的结论

### 1. zip 静默截断是否真的不可能再发生 — 成立

- `_render_translated`（core/output.py:58）与 `_render_bilingual`（:75）在构建任何正文行之前调用 `_check_paired_lengths`（:30-36），长度不等即抛 `OutputCountMismatchError`；
- 两个渲染函数完全在内存完成，之后 writer（:150-151、:162-163）才调用 `_atomic_write_text`；因此校验严格先于任何临时文件创建，也先于 :65/:82 处的 `zip` 消费——此时长度必然相等，zip 无从截断；
- `write_original`（:131-139）不接收 translations，天然不受影响；
- 绕过路径排查：生产代码中引用这三个 writer 的只有 `transcribe.py:29`、`core/__init__.py`、`core/pipeline.py:10,189,196,200`，全部经本模块；生产代码中 `zip(paragraphs, translations)` 仅 `core/output.py:65,82` 两处，均已受前置校验保护（`tests/test_output.py:119` 的 zip 属测试自身，输入等长）。

### 2. Windows 替换语义 — 成立

- 临时文件 `dir=path.parent`（:105）与目标同目录即同卷，`os.replace`（:115）是同卷 rename，Windows 上为 `MoveFILEExW(REPLACE_EXISTING)` 语义，原子替换，不存在跨文件系统问题；
- 目标被其他句柄占用时 replace 抛 `PermissionError`，进入 except 清理，旧字节不动——有真实 win32 用例实证（tests/test_output.py:307-322，非 mock）；
- 句柄在 replace 之前已 `close()`（:113-115），无自锁；目标只读属性、父目录缺失等情形分别在 replace/工厂阶段抛错并清理，不触碰旧字节。

### 3. 失败清理完备性 — 基本完备，一处极端场景缺口（见发现 #1）

- 渲染失败：发生在任何磁盘动作之前，无 tmp 可泄漏（writer 先 render 后 write）；
- 工厂失败：`handle=None, tmp=None`，直接 re-raise；
- write/flush 失败：except 关闭未关句柄（:118-122）→ unlink tmp（:123-127）→ 裸 `raise`（:128）重抛原始异常；内层清理的 OSError 被逐层捕获且不影响外层活动异常——原始异常不会被吞，正确；
- `except BaseException`（:117）覆盖 KeyboardInterrupt/SystemExit 路径，正确；
- 替换成功后误删最终文件：不可能——`os.replace`（:115）与 `tmp = None`（:116）之间无任何可抛语句；
- 缺口：若 `handle.close()` 本身失败（close 时才暴露的写错误、句柄卡死），`closed` 保持 False，Windows 上删除仍被打开的文件（CRT 打开不含 FILE_SHARE_DELETE）通常抛 PermissionError，被 :126-127 吞掉 → 可能残留 .tmp 孤儿。异常传播与旧字节保留不受影响，属清理残留而非数据完整性问题。

### 4. 旧目标字节保留 — 在所有失败路径成立

所有失败阶段（渲染/工厂/write/flush/close/replace）都发生在 `os.replace` 之前或 replace 原子失败；新实现从未以 `"w"` 模式打开目标路径，旧实现的截断窗口已彻底消除。测试用 `_snapshot`（sha256(read_bytes())，tests/test_output.py:101-110）在 :215、:233、:260、:287、:305、:322 逐字节验证。

## 测试真实性抽查

- 代理字符用例（:263-287）：`\ud800` lone surrogate 在 Python str 渲染/拼接阶段不抛错，长度校验通过（2==2），失败发生在 `handle.write` 的 UTF-8 编码——确实走到写入阶段而非渲染阶段；
- 快照对比：`_snapshot` 用 SHA-256 逐文件比对原始字节，非字符串比较；
- autouse 孤儿断言（:30-35）：`rglob("*.tmp")` 匹配实现生成的 `.{name}.*.tmp` 命名（suffix=".tmp"），覆盖正确；
- Windows 占用测试为真实句柄持有、真实 PermissionError，非模拟。

## 测试运行结果（原样命令、原样计数）

    python -B -m pytest -q -o addopts="" tests/test_output.py
    → 47 passed in 1.11s

    python -B -m ruff check core/output.py tests/test_output.py
    → All checks passed!

追加反例后复跑：53 passed in 1.10s（47 既有 + 6 反例），ruff 仍 All checks passed。

## 独立反例测试说明

提交 `66e31db` 在 `tests/test_output.py` 追加 `TestIndependentReviewerCounterexample`（含 `_FlushBoomHandle` 辅助类），机制与既有三类注入（代理字符 write 中途 UnicodeEncodeError、monkeypatch `os.replace`、Windows 真实占用）不同：

1. `test_flush_failure_preserves_target_and_cleans_tmp`（3 writer × 1）：monkeypatch `core.output.tempfile.NamedTemporaryFile` 为包装真实临时文件的假句柄（提供 name/write/flush/close/closed，write 透传成功、flush 抛 OSError）。真实临时文件已落盘、内容已写入后失败。断言：OSError 原样传播、失败确由 flush 抛出、泄漏句柄被清理关闭、目标旧字节 SHA 不变、无 `*.tmp` 残留。
2. `test_factory_failure_preserves_target_and_leaves_no_tmp`（3 writer × 1）：工厂创建即抛 OSError（模拟目录只读/配额）。断言：异常传播、目标 SHA 不变、无 `*.tmp`。

两个反例在当前实现下全部通过（6/6），未暴露实现缺陷。

## 范围合规

`git diff --name-status 8a33a7f..ad620c1` 仅：`M core/output.py`、`M tests/test_output.py`、`A docs/plans/meetingconverter-output-integrity-2026-10-24/plan.md`，全部在允许范围；未触碰 `core/pipeline.py`、`core/batch.py`、`engines/**`、`translator.py`、`.github/workflows/**` 与配置。

## 发现清单

| # | 严重度 | 位置 | 内容 |
|---|--------|------|------|
| 1 | minor | core/output.py:118-127 | `handle.close()` 自身失败的极端场景下，句柄保持打开，Windows 上 unlink 该文件通常抛 PermissionError 且被吞 → 可能残留 `.tmp` 孤儿。异常传播与旧字节保留不受影响，非数据完整性缺陷；模块 docstring（:9-10 "任一阶段失败都会删除临时文件"）在该场景略有夸大。建议实现方后续考虑记录清理失败或尽力善后，无需阻塞本卡。 |
| 2 | info | core/output.py:34-35 | `expected/actual` 仅存在于 message 字符串，无结构化属性（`self.expected`/`self.actual`）。卡要求"含 expected/actual"，消息满足；程序化消费方需解析字符串，可选改进。 |
| 3 | info | core/output.py:101-109 | POSIX 上 `NamedTemporaryFile` 产物权限为 0600，旧 `open()` 为 umask 默认（通常 0644）；plan.md:50-52 声明了换行符变化但未声明此点。Windows 环境无实际影响。 |
| 4 | info | core/output.py:104 | `newline=""` 使 Windows 输出换行从 CRLF 变为 LF——有意变更，plan.md:50-52 已声明，处理得当，仅作记录。 |
| 5 | info | core/output.py:11-13 | 三输出文件之间无跨文件事务（中途失败留"部分新+部分旧"）。该边界已在模块 docstring 与 plan.md:41-46 明确声明并要求调用方整体重跑，属已接受的显式限制。 |

无 blocker、无 major。

## 结论

**PASS-with-findings** — 实现达成卡片目标：zip 静默截断在本模块边界内不可能再发生，覆盖式直写改为内存渲染 + 同目录临时文件 + `os.replace` 原子替换，所有失败路径保留目标旧字节且原始异常不被清理吞掉。1 个 minor（close 阶段失败时 Windows 可能残留 tmp 孤儿）+ 4 个 info，均不阻塞。独立反例 6/6 通过，未发现实现缺陷。

## 本次审查产生的提交

- `66e31db` test: 独立审查写盘失败反例（flush 阶段失败与临时文件创建失败保留旧字节）
- 本报告的 docs 提交（见 `git log`）

---

# 复审（最终 SHA）

- 复审对象：`efbb51d`（fix: 独立审查发现修复——close 失败强关 fd 兜底清理，异常附结构化计数）
- 复审人：同一独立审查 agent（未参与实现与修复）
- 日期：2026-10-24；复审 diff：`git diff 604b6ca..efbb51d`

## 逐项发现处置核验

- **minor #1（close 失败残留 tmp）— 已修复，正确。** 清理分支在
  `handle.close()` 抛 OSError 时追加 `os.close(handle.fileno())`
  （core/output.py:126-138），`(OSError, ValueError)` 捕获覆盖
  EBADF/负 fd/已关句柄三类；成功路径 close() 正常不触发该分支；
  `os.close` 失败被局部吞掉但最外层裸 `raise`（:147）仍重抛原始
  异常；仅关闭本句柄 fd 且仅在句柄已放弃时执行，无误关风险。
  模块 docstring（:8-11）改为"尽力删除"并注明极端残留可能，消除
  原措辞夸大。**本机实证**：Windows 上打开态临时文件
  `unlink` → `PermissionError [WinError 32]`，`os.close(fd)` 后
  unlink 成功——强关分支确为必要且有效。
  残留理论缺口（非本次引入）：close() 抛非 OSError 异常时清理块
  直接传播并跳过 unlink；标准库句柄 close 只抛 OSError 族，理论性
  可接受。
- **info #2（结构化计数）— 已修复，正确。** `OutputCountMismatchError.__init__(expected, actual)`
  （core/output.py:31-36）消息文本逐字不变，既有 `raises(match=...)`
  用例不受影响（57 passed 佐证）；全仓唯一构造点 core/output.py:43，
  两参签名无破坏面。新增属性断言用例通过。
- **info #3（POSIX 0600）— 已补记，但补记内容有一处不准确（见新发现 #6）。**
- **info #4/#5 — 无需改动，确认未动。**

## TestCloseFailureCleanup 真实性挑战 — 成立

- `_CloseBoomHandle`：write/flush 透传真实句柄（成功）、close 抛
  OSError、`closed` 恒 False、`fileno` 透传真实 fd——失败精确落在
  close 阶段，清理时 `not handle.closed` 为真、二次 close 再抛、
  进入 `os.close(handle.fileno())` 强关分支，路径确实走到。
- 判别力实证：无强关修复时，本机 Windows unlink 打开态文件报
  WinError 32（已实测），tmp 必残留、用例必失败——测试非永真。
- `@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")`
  仅忽略该单一类别、仅类级作用域；噪音来源真实（GC 析构被强关 fd
  的包装层产生不可抛出 EBADF）；用例以目录扫描直接断言无残留，
  不依赖 warning 屏蔽掩盖泄漏——范围最小、理由成立。

## 复审测试运行（原样命令、原样计数）

    python -B -m pytest -q -o addopts="" tests/test_output.py
    → 57 passed in 1.28s（无 warning；53 既有 + TestCloseFailureCleanup 3 + 结构化属性 1）

    python -B -m ruff check core/output.py tests/test_output.py
    → All checks passed!

定向复跑 `TestCloseFailureCleanup` + `TestErrorContract` → 5 passed。

## 范围核验（8a33a7f..efbb51d）

`M core/output.py`、`M tests/test_output.py`、
`A docs/plans/meetingconverter-output-integrity-2026-10-24/plan.md`、
`A docs/plans/meetingconverter-output-integrity-2026-10-24/STATUS.md`、
`A docs/plans/meetingconverter-output-integrity-2026-10-24/review-independent.md`
——全部落在允许范围（STATUS.md 属 `docs/plans/meetingconverter-output-integrity-2026-10-24/**`）；
未触碰 pipeline/batch/engines/translator/CI/配置。

## 复审新发现

| # | 严重度 | 位置 | 内容 |
|---|--------|------|------|
| 6 | info | docs/plans/meetingconverter-output-integrity-2026-10-24/plan.md:54-56 | 权限补记中"被替换的最终文件沿用目标原有权限模型（新建目标为 umask 默认）"与 POSIX rename 语义不符：`os.replace` 后最终文件即 tmp 的 inode，权限恒为 mkstemp 的 0600，无论新建还是替换都不沿用旧目标权限或 umask 默认。仅文档准确性问题，Windows 环境无实际影响，不阻塞；建议下轮 handoff 文档中更正表述。 |

## 复审结论

**PASS** — minor #1 与 info #2/#3 均已按审查建议正确修复并有判别力
测试佐证；57 用例全过、无 warning、ruff 通过；最终 SHA `efbb51d`
相对 `8a33a7f` 的全部变更仍在允许范围。新发现仅 1 个 info 级文档
准确性问题（#6），不构成交接阻塞。本 SHA 可交接。
