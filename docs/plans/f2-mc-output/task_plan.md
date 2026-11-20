# F2-MC-OUTPUT · 会议转录与发布反馈

**已交付并接入本机。** 历史施工范围与验收步骤保留下文。实际使用、负责范围和复验见 [F4 运行端口](runtime.md)。

| 项目 | 值 |
|---|---|
| 原施工目录 | C:/Users/郑曾波/Projects/_harness_worktrees/f2f/mc |
| 分支 | `codex/f2-mc-output` |
| 已核基线 | `b43a76a3cdc25928a75e583b65a5a706802985ce`（`origin/master`） |
| PWF 选择器 | PowerShell 下设置 `$env:PLAN_ID='f2-mc-output'`、`$env:PWF_PLAN_ROOT='docs/plans'` |
| 原计划 | [本仓转录反馈](../feedback-20261117.md) · [输出完整性验收](../meetingconverter-output-integrity-2026-10-24/STATUS.md) |

## 入口、写范围与目标

- 从 `core.transcribe_one`（实现 `core/pipeline.py`，CLI 和批处理共用）开始。读 `core/output.py` 的原子输出承诺和 `tests/test_transcribe_integration.py` 的本地 mock engine、translator。本卡写 `core/pipeline.py`、新建必要的 `core/` 本仓反馈适配器、定向测试、`skills/repair-meeting-converter-issue/SKILL.md` 和本 PWF 目录。写文件选择从实际实现出发，避免复制三个 writer 的输出逻辑。
- 保留已有 writer、单文件原子替换、批处理和 CLI 返回语义。若启用翻译而此轮 `TranslationError` 被捕获，原文仍可正常产出，译文与双语仍可保留原样；反馈应暴露未产出本轮译文。已存在原件的跳过沿用现有规则并且转录调用数为 0。转录、翻译供应商调用和模型预算沿本仓现有口径。
- 主目录的 `.coverage` 有历史改动，两个工作树各自保存其内容。音频、输出、配置和测试生成文件都用专用临时目录。所有合成输入自给，运行无需网络、凭证、真实音频、其他仓服务或 ROOT 代码改动。

## 输出接口

UTF-8 JSONL。一个调用者为一个进程分配独占的 `RESEARCH_FEEDBACK_OUT`。可从 `RESEARCH_FEEDBACK_RUN_ID`、`RESEARCH_FEEDBACK_ATTEMPT_ID` 继承运行上下文。每次处理不同输入时 `step_id` 含本次操作的稳定标识；同一批两个同名音频也要可区分；重投文件时沿用原 ID。启用前后业务 stdout、stderr 及返回值和产物字节一致。旁路无法写入时只在已有的独立本地诊断通道报告，主任务按本身的退出状态处理。对照行为时固定 mock Timer、时间、输入和输出位置。对本来可变的耗时及路径明确做同规则对齐，保留实质字段和音频文本的对比。

使用 `feedback-observation/1`。所有行有字符串 `schema_version, owner, run_id, attempt_id, step_id, check_id, expected, actual`，`owner=meeting-converter`，`origin_owner` 省略时等于 owner。可选 `disposition` 为 `expected/deviation/unknown`。中途开始行用 `check_id=action-started`、`actual=started`、`terminal_check_id=publication-outcome`，相同身份的 `publication-outcome` 证明实际终态；启用后从真实流程的起止产生。复用、转录已启动、写入失败与正常完成分别记录。停止后只有开始行且没有可信终态时保留 unknown，本卡无自动重转录动作。根因未确认时 issue_key 可省略。示例：

```json
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"offline-run","attempt_id":"a1","step_id":"meeting-operation/42","check_id":"requested-outputs","expected":"translated_and_bilingual_current","actual":"previous_translations_only","disposition":"deviation","issue_key":"stale-output-success","evidence_ref":"mc-output/1/42"}
```

expected 取请求模式，actual 取本次成功提交的 writer 结果和真实错误。输出有残留旧件、只提交了部分目标和一次成功原文模式是三种不同情况。逐字稿、音频名中的主体信息、原始异常、路径和凭证留在本仓。对账没有用量收据时，费用记 unknown。证据引用用本仓能解释的逻辑 ID。

## 实施和验收

0. ROOT 开工预检为 **81 passed、4 failed**。四个失败均来自 `test_transcribe_integration.py`：旧 mock 将两个相邻 segment 合并为一个段，但译文夹具固定返回两段，故被已验收的 writer 正确拒绝。在本卡先校正成功夹具，使两段间隔大于现有 2 秒合并阈值并断言实际给 translator 两段。保留 `test_output.py` 的真实段数不符拒绝断言。此次修理只涉及测试。
1. 在 `tests/test_output_feedback.py` 先写 RED。使用合成音频和 stub 引擎经 `transcribe_one` 触发译文异常或第二个 writer 失败，同时留有上一版文件。实际把原文写成功的计数、旧文件字节和侧车所报的新旧范围互相核对。
2. 在流程边界记录每个本轮成功 writer 的角色、该角色产物标识和阶段结果，基于已有的异常和 metrics 投影。沿用日志及原始错误，不增另一个业务状态库或逐步许可。检查批处理不同输入以及 `force` 失败后的状态。
3. 正反例一起跑。原文模式仅原文、启用翻译三件齐全、已存在跳过、翻译失败陈旧输出、段数错配、原文成功/对照写失败、sidecar 不可写、两份不同语言或不同输入身份的样本。对启用、禁用和写入失败三种诊断设置比较返回值、生成文件及引擎/翻译调用计数。重读旧 sidecar 时计数不增加。至少一个集成用例从公开转换入口走到实际文本写入和 JSONL。
4. 写一页本仓修复技能，指导按原生 evidence_ref、同尝试证据、RED 和合法对照定位第一处偏差。对实际发现的问题在本计划目录 `issues/` 写一张可重放根因卡。记录首次偏差、受影响范围、最小复现、合法对照、修复及复验版本。测试夹具与生产问题分别归因。更新 findings/progress。全部工作用本仓测试，不改总控或邻仓。

```powershell
python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_output.py tests/test_pipeline.py tests/test_transcribe_integration.py tests/test_output_feedback.py
```

测试中覆盖率用 `-o addopts=` 关闭，保留两处已有 `.coverage`。用 `TemporaryDirectory` 或可控测试根收尾，可用新建的短独占目录传给 `--basetemp`，收尾只移除本轮生成目录并记录清理。保留错误用例断言，完整运行上述定向包，无需全量 CI 前手动重跑。

## 独审与交接

实现和定向测试结束后请一位未参与实现的独立 agent 从本卡、最终 diff 和实际产物检查完整度和质量。至少复查上述全部正反例、真实公开入口、意外触发供应商的路径、旧文件保留、旁路可选性和记录中无正文/凭据。逐项修复并在最终实现 SHA 上复审，未解决的问题留在本卡继续做。交付时 `handoff.md` 给出：

- lane、owner、工作目录与分支、base SHA、implementation SHA、reviewed SHA、提交位置。测试命令及通过/失败/跳过数、审查报告与发现逐项关闭记录。
- 至少一份测试实际输出的最小 JSONL 示例（成功、陈旧/部分、unknown 或仅开始），写出复现命令、配对身份、稳定 evidence_ref、原引擎启动次数及重放的零新增计数。手工构造协议样例可附，不能替代实际输出。
- 清理收据，注明原 `.coverage` 与旧产物指纹核对、测试根删除、主工区变动。用公开 JSONL 交付 ROOT，注明仍需的跨仓组合事项。

`handoff.md` 尾部用一段 JSON 给机器摘要，详细证据放正文。路径相对本工作树，引用必须能让 ROOT 独立复验。

```json
{"lane":"F2-MC-OUTPUT","owner":"meeting-converter","base":"BASE_SHA","implementation":"IMPLEMENTATION_SHA","reviewed_commit":"REVIEWED_SHA","branch":"codex/f2-mc-output","review_ref":"REVIEW_FILE","tests":[{"command":"ACTUAL_COMMAND","result":"PASS_COUNT_AND_OTHER_OUTCOMES"}],"sample_refs":["TEST_EMITTED_JSONL"],"cleanup":"ACTUAL_CLEANUP","remaining":["ROOT_COMPOSITION"]}
```

在本分支正常 hooks 提交最终代码/测试与交接，可推同名施工分支。ROOT 负责接收和并入主线。
