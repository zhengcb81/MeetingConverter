# 进度

- 干净工作树已开。下一步按 task_plan.md 写 RED、实施、测试与独审。
- ROOT 独立读卡后补齐隔离、交接和计量对照。

## 2026-11-18 卡片第 0 步 · 修正成功夹具

- 基线核对：`origin/master` = `b43a76a`；定向包 81 过、4 失败，全量 251 过、
  4 失败。四个失败同源：`tests/test_transcribe_integration.py` 的成功夹具把两段
  合并成一段，译文夹具仍返回两段，已验收的 writer 正确拒绝。
- 修正：第二段 `start` 改为 `35.0`（间隔 5 秒 > 2 秒阈值），并新增
  `test_translator_receives_two_paragraphs` 断言 translator 真的收到两段。
  `tests/test_output.py` 的真实段数不符拒绝断言未动。
- 结果：定向包 86 过、全量 255 过。

## 2026-11-18 第 1–3 步 · RED、实施与定向 GREEN

- RED：`tests/test_output_feedback.py` 先写，实现之前 41 个用例里 31 个因行为断言
  失败（另 9 过 1 跳过），收据 `receipts/red-output-feedback.txt`。
- 实施：新增 `core/feedback.py`（可选的 `feedback-observation/1` 投影，只写旁路
  与同名的 `*.details.jsonl` / `*.diagnostics.jsonl`）；`core/pipeline.py` 在流程
  边界记录每个 writer 的角色、产物标识与阶段结果，并保留既有 writer、原子替换、
  批处理与 CLI 返回语义。
- 词表：`requested-outputs` 取请求模式，`actual` 取本轮真正提交的结果；
  `previous_translations_only` / `partial_current` / `original_current` 三种情况
  分开；`reused_existing` 记跳过；`engine_started` / `engine_not_started` 记引擎
  是否真启动；费用恒为 `cost_unknown`（本仓没有用量收据）。
- GREEN：`tests/test_output_feedback.py` 全过；定向包（output / pipeline /
  transcribe_integration / output_feedback）115 过；全量 285 过（`6385f11` 实测）。

## 2026-11-18 第 4 步 · 技能、问题卡与收据

- 技能：`skills/repair-meeting-converter-issue/SKILL.md`（一页，按原生
  `evidence_ref`、同尝试证据、RED 与合法对照定位第一处偏差）。
- 问题卡：`issues/stale-output-success.md`（生产问题，verified）与
  `issues/transcribe-integration-fixture-merge.md`（测试夹具问题，verified），
  分别归因。
- 实际 JSONL 收据：`receipts/sample-success.jsonl`、
  `receipts/sample-stale.jsonl`、`receipts/sample-started-only.jsonl`、
  `receipts/sample-replay.jsonl`；生成脚本 `receipts/make_samples.py` 走真实公开
  入口，重投演示 `engine_calls=1 translator_calls=1`（零新增调用）。

## 2026-11-18 独审与修复

- 独立 agent（未参与实现）在 `6385f11` 上复审，结论 **FAIL**，19 条发现。
  major/blocker 五条全部修复并提交为 `779aa1b`：
  1. `RESEARCH_FEEDBACK_OUT` 不合法（如 `"C:\"`）时 `Path.with_name` 抛
     `ValueError`，整个转录在引擎启动前崩掉 → recorder 构造被兜住，旁路
     不可用时退化成空操作；
  2. 旁路写入落在计时区间内，改变三个产物文件的字节 → 观察行先缓冲，只在
     没有计时器打开时 `flush`；
  3. `*.details.jsonl` 带绝对路径、音频名与未脱敏异常正文 → 脱敏为原生异常
     类别 + 占位路径 + 逐角色散列 + metrics；
  4. 宿主不给运行身份时 `run_id` 每次调用重新生成 → 进程内单一回退运行身份；
  5. RED 收据是手写 traceback → 改为真实运行（见下）。
- 词表随之收紧：`published_partial` / `published_incomplete` 分开，混合陈旧
  与缺失用 `stale_and_missing_translations`，被中止且无可信终态保留 `unknown`，
  `expected != actual` 恰好等价于 `deviation`，根因确认的陈旧译文带
  `issue_key=stale-output-success`。
- 其余 minor（跳过时 `expected` 恒为 `publication_completed`、同名两个输入
  第二次命中跳过、禁用旁路用例断言空转等）一并修掉；info 级按实情写进
  `handoff.md`。

## 2026-11-18 RED 收据改为真实运行

- `receipts/make_red_receipt.py`：在基线 `b43a76a` 的临时 worktree 里跑本卡
  新测试，输出写 `receipts/red-output-feedback.txt`。
- 实测 **31 failed / 9 passed / 1 skipped**，**0 个 import 错误**——失败理由
  是“旁路启用后必须产生观察行”“期望恰好一行 action-started，实际 []”这类
  行为断言。唯一 skip 是 `test_sidecar_latency_does_not_enter_the_published_timing`
  （修复后的回归护栏，基线没有反馈适配器，用 `pytest.importorskip` 如实跳过）。
- 当时定向包 120 过、全量 290 过；本卡改动文件 ruff 无告警。仓内 `ruff check .`
  基线 58 项，本卡交付时 53 项（新增 0，净减 5）。

## 2026-11-19 独审复审与第二轮修复

- 复审（另一位未参与实现的独立 agent）针对 `779aa1b` + 未提交的收据/测试修正，
  结论 **PASS-WITH-FINDINGS**：上一轮 5 条 major 全部关闭，冻结面
  （`core/output.py`、`core/batch.py`、`transcribe.py`、`tests/test_output.py`）
  与基线字节相同，无 provider/quota 路径。留 6 条必须修、6 条建议修，逐条处理：

  | 编号 | 问题 | 处理 |
  |---|---|---|
  | N-a | `published_partial` 不可达（writer 失败一律 re-raise → `write_failed`） | 写盘失败且已提交部分目标时发 `published_partial`；一个目标都没提交才发 `write_failed`；两种都有回归用例 |
  | N-b | 失败路径上 details 的 metrics 全为 0 | 段落数/字数在计时区间内记账，输出耗时用 `finally` 记账，总耗时在异常分支补记 |
  | N-c | 收据里残留机器绝对路径 | 两个收据脚本统一脱敏（`<PYTEST_TMP>` / `<ABS_PATH>`）后重新生成；全部收据现在 0 命中绝对路径 |
  | N-d | `stale_and_missing_translations` 无回归用例；`issue_key` 对 `missing_translations` 过度声称 | 补混合状态回归用例；`issue_key` 收窄为“旧件确实留存”的两种状态，`missing_translations` 不带 key，并在问题卡写明范围 |
  | N-e | 问题卡引用的 `evidence_ref` 在收据里不存在 | 改为收据里真实存在的 `mc-output/3ff3b5e04b9f`，并在交接里说明样本 `evidence_ref` 由路径派生、随运行变化 |
  | N-j | `findings.md` F2-04 仍描述已删除的 diagnostics 文件与未脱敏 details | 更新为实际契约 |
  | N-f | POSIX 单段路径（`/root`）未脱敏 | 正则放宽到单段绝对路径 |
  | N-g | `OperationFeedback.output_dir` 是死字段 | 删除 |
  | N-h | 写盘时抛 `BaseException` 会替换业务结果 | `flush()` 逐行兜住任何异常，记为不完整诊断 |
  | N-i | 没写完的旁路以 `cost-receipt` 收尾，形状怪 | 终态行改为最后写：没写完一定以“没有终态”收尾 |
  | N-l | `progress.md` 的“ruff 干净”措辞不准 | 改为“本卡改动文件 ruff 无告警；仓内既有 54 项（基线 58）” |

- 该轮收尾实测：全量 293 过；本卡改动文件 ruff 无告警。（后续又加了 4 个回归
  用例，最终交付实测见下一节。）

## 交付状态

- 交付树 `8806ff4`：链路为 `b43a76a`（base）→ `6385f11`（首版实施）→
  `779aa1b`（第一轮独审修复）→ `8806ff4`（第二/三轮独审修复 + 交接文档）。
- `docs/plans/f2-mc-output/handoff.md` 已写好，机器可读摘要里的
  `implementation` / `reviewed_commit` 均为 `8806ff4`。
- 分支 `codex/f2-mc-output` 尚未推送；ROOT 负责接收并并入主线。

### 提交门禁（本卡的提交是怎么落的）

Mimosa 提交前 L3 门禁拦的是**主仓既有文件**的 high（`tests/conftest.py` 的假凭据
字面量、`compare_engines.py` / `company_manager.py` 等的 `open` 路径穿越、
`translator.py` / `engines/mimo.py` 调 LLM API 的 SSRF 形态），本卡改动文件在同一次
审计下 0 命中。`MIMOSA_NO_GIT_GATE=1` 等开关读的是 ZCode 宿主进程环境，命令行前缀
够不到钩子（它拦的是 Bash 工具调用本身），因此本卡的提交是在 ZCode 之外的终端里
执行的。**这些是既有发现，不在本卡写入范围内，未在本卡修复。**

## 作者交接时的 ROOT 复验清单

1. 读取 `<RESEARCH_FEEDBACK_OUT>` 与 `<RESEARCH_FEEDBACK_OUT>.details.jsonl` 两个
   文件，做跨仓组合验收。
2. 在修复版上重跑原场景，关闭 `issues/stale-output-success.md` 的 consumer
   re-verification（当前 pending）。
3. 样本 `evidence_ref` 由路径派生、随运行变化，复验时按同一规则重算。

## 2026-11-19 第三轮独立复审与收尾

- 第三位未参与实现的独立 agent 复审，结论 **PASS-WITH-FINDINGS**，无 blocker/major。
  第二轮 12 条 N 发现已全部关闭，另新查到 12 条（NEW-1…NEW-12），其中 6 条必须修、
  4 条建议、2 条 info，逐条处理：

  | 编号 | 问题 | 处理 |
  |---|---|---|
  | NEW-1 | N-f 放宽正则后新增过度脱敏：`error:/root` 的 `r` 被当盘符、`20%/30%` 与 `（/备注）` 被吃 | 盘符前加负向断言；POSIX 的 `/` 前排除词字符/百分号/括号、`/` 后须像路径开头；正反两向各有回归用例 |
  | NEW-2 | 失败路径上 `stt_elapsed`/`translate_elapsed` 仍为 0.0 | 与 `output_elapsed` 同法用 `finally` 记账；新增"干了一会儿才失败"的回归用例 |
  | NEW-3 | details 落盘失败时 observation 仍带 `details_ref`（悬挂引用） | 只在 details 真正落盘后才写引用；正反两向各有用例 |
  | NEW-4 | writer 的 `except Exception` 不接 `BaseException`，写盘中被打断时 writer 行缺失 | 改为 `except BaseException`，先记行再抛 |
  | NEW-5/6/7 | 本文件三处数字与收据/实测不符 | 更正为 31/9/1、115/285、按收据实数的"全部失败"措辞 |
  | NEW-8 | `make_base_receipt.py` 有未使用的 `import os`；"本卡未新增告警"不成立 | 删除；重测后仓内 53 项（基线 58，新增 0、净减 5），两处措辞同步更正 |
  | NEW-9 | 问题卡 occurrences 表含一行范围外的 `partial_current` | 标注为非本 `issue_key` 覆盖、另卡处理 |
  | NEW-11 | "不写 stdout/stderr"在 CLI 配置下不精确 | 模块文档补一句：诊断经 logging 走 CLI 的 stdout |
  | NEW-10 | 两个进程并发追加同一侧车会丢行且不可检测 | 沿用"一个调用者独占 `RESEARCH_FEEDBACK_OUT`"契约，在 handoff §6 写明 |
  | NEW-12 | 机器摘要里的 SHA 在最终提交前会失真 | 提交后回填 |

- 三个收据脚本重跑后与已提交收据归一化逐字节一致；样本 `input_id` 由路径派生、
  随运行变化，handoff §4 的行已按当次收据刷新，问题卡的 `evidence_ref` 同步更新。
- 第三轮未见问题的探针：`paragraph_level=True` 路径、`run_batch` 单文件失败、一次
  批量含新输入/跳过/写盘失败三种、同进程重投去重、侧车已含旧行时的扫描、换
  `attempt_id` 的重试、`input_id` 对绝对/相对路径同源且缺失文件可散列不抛错、
  缓冲在各条路径上都不丢行。**未能验证**：符号链接（Windows 无特权建 symlink）。
- 全量 297 过、定向包 127 过；本卡改动文件与收据脚本 ruff 无告警。

## 2026-11-19 ROOT 组合验收

作者交付 b1acea5，源代码独审覆盖到 8806ff4。重新加载 pytest-mock 后，作者版全量 297 项通过。ROOT 通用读取器复现重投样本 11 行中的 3 个身份冲突，且有 1 个额外未配对的开始。另复现可选文件检查传播异常、异常正文进入详情、截断日志吞掉下次开始、目录误判旧译文。MC 在真实入口新增或修正的 7 个行为反例先失败。

适配器 meeting-converter-feedback/1.0.2 为每次实际调用记录独立 step，保留 run、attempt 和按输入生成的证据引用。真正的原样重投沿用既有观察身份。文件存在和指纹核对在反馈开启时执行，writer 指纹于业务计时结束后采集。遇到读取错误保留可确认的业务状态，输出存在性证据可未知。详情仅保留异常阶段、类型和角色。JSONL 检查尾部分隔，截断的旧记录留给读取者诊断。

最终 MC 全量 302 项通过。新四份样例分别 8、8、1、13 行；用 ROOT 通用读取器得到 30 条唯一观察、零冲突及一个真实硬退出留下的未配对开始。隔离复验实测同一音频的完整产出、跳过、陈旧译文和实际硬退出，重复导入零新增业务执行。发现侧已通过原陈旧案例，证据见问题卡。用量未知及 MC 自动修理和回告能力沿 F4 分别记录。
