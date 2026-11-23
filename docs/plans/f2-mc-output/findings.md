# 调查依据

- 以 MeetingConverter 公共转录入口、现有 writer 与 mock fixture 为基线。实际 RED 和根因在本卡执行期间补录。
- 本仓 mock 固定两条译文，而两个相邻段被正常合并为一段。定向基线 81 过、4 失败，已纳入卡片第 0 步并保留 writer 负例。

## 本卡执行期间补录的发现

### F2-01 旧成功夹具的相邻段会被合并（归因：测试夹具）

`tests/test_transcribe_integration.py` 的成功夹具第二段 `start=30.0` 与第一段
`end=30.0` 相接，间隔 `0.0` 不大于现有 2 秒合并阈值，因此被
`merge_into_paragraphs` 合并为一段；而译文夹具固定返回两段，已验收的 writer
按契约在写盘前抛 `OutputCountMismatchError`（expected 1 / actual 2）。四个失败
不是产品缺陷，是夹具与已验收契约对不上。已按卡片第 0 步把第二段改为
`start=35.0`（间隔 5 秒 > 2 秒），并新增断言证明 translator 真的收到两段。
`tests/test_output.py` 的真实段数不符拒绝断言原样保留。

### F2-02 流程边界没有“本轮产出”的证据（归因：本仓产品）

`core/pipeline.py` 只决定**要不要**写某个输出，从不记录**写了没有**。三个
writer 只有单文件原子性，流程既没有跨文件事务也没有逐轮来源。因此：

- 翻译被 `TranslationError` 捕获时，原文照常产出，译文与对照保持上一版字节，
  进程退出 0 —— 与“一次完整的翻译发布”在外面**无法区分**；
- writer 抛错时，已替换的文件保持新内容、失败文件保持旧内容，同样无法区分；
- 命中“原文已存在则跳过”的规则时，本轮引擎调用数为 0，但外部只看到“文件存在”。

这就是计划里说的“输出有残留旧件、只提交了部分目标和一次成功原文模式是三种
不同的情况”，而修复前它们共用同一个外部信号。本卡在流程边界加一个可选投影
（`core/feedback.py`），把这三种情况分别记成 `previous_translations_only` /
`partial_current` / `original_current`，另加 `reused_existing` 记跳过。

### F2-03 本仓没有用量收据，费用只能是 unknown

`translator.py` 调用 DeepSeek 但不产出用量收据，转写引擎侧同样没有费用回执。
因此对账时费用恒为 `cost_unknown`，`disposition` 为 `unknown`，不能凭空补一个
数字。

### F2-04 旁路必须是可选且无副作用的

- 旁路开启前后，业务 stdout、stderr、返回值与三个产物文件的字节必须一致；
  旁路自己的写入耗时不得落进任何计时区间，否则发布的「转写时间」会变，
  产物字节随之改变（观察行先缓冲，只在没有任何计时器打开时 flush）；
- 旁路写不进去时，只在本仓已有的本地诊断通道（logging）上报告，主任务按
  自己的退出状态处理，不重做转录也不重做模型调用；
- 跨仓观察行只带稳定结果词与不含主体信息的逻辑引用。**本仓的步骤日志
  （`*.details.jsonl`）同样是脱敏的**：没有绝对路径、音频名、逐字稿正文与
  凭证，只保留原生异常类别、脱敏后的一句话、逐角色散列与 metrics；未脱敏
  的事实留在本仓自己的日志输出里。

### F2-05 身份规则

`step_id` 为 `meeting-operation/<input_id>`，`input_id` 是输入文件解析路径的
散列：同一文件重投沿用原 ID，同一批两个同名音频仍然可区分。重投同一份结果
（同身份同内容）不新增行；同一 step 的 check 内容不同（先转录后跳过）是两件
不同的事，仍然各记一行。真实重试应当使用新的 `attempt_id`。

### F2-06 本卡结论

两个可重放的根因卡写在 `issues/`：`stale-output-success`（生产问题，状态
verified）与 `transcribe-integration-fixture-merge`（测试夹具问题，状态
verified）。两者分别归因，互不掩盖。

## F4 普通入口失败的事实

### F4-01 启动失败与转录失败的观察身份不同

普通 CLI 在参数解析前没有运行身份，是四案启动失败零观察的根因（审计锚
`transcribe.py:83`）。修复把 `run-started` 行放在解析之前：解析未完成只记录
能确定的身份与阶段（parsing）；无输入/坏 CLI 是 `request_rejected`，输出目录
不可用是 `local_io_failed`，引擎创建失败是 `initialization_failed`。启动收据
step 前缀 `mc-startup/`，与逐文件操作的 `meeting-operation/` 互不混淆；强停
之后新进程至少能读回启动行，把未确认区间标出来。

### F4-02 翻译意图必须显式传入，不能从对象缺席推导

审计锚 `core/pipeline.py:129` 的 `translate_requested=translator_obj is not None`
把"翻译器创建失败"伪装成"用户主动关翻译"。修复后调用边界显式传
`translate_requested` / `translator_ready` / `translator_error_type`，旧口径
仅在参数缺省时保留（旧调用方行为不变）。`requested-outputs` 的 expected 因此
仍如实报 `original_translated_bilingual_current`；actual 新增
`translation_unavailable`（翻译被请求但从未运行），与 `previous_translations_only`
等"翻译运行了但失败"的词分开；writer 行新增 `not_run` 与主动
`not_requested` 分开。`transcribe.py` 配置加载失败导致翻译器缺席时，原因
（如 FileNotFoundError）进入 details。

### F4-03 成功回退是"成功与降级同时成立"

审计锚 `engines/fallback.py` 吞掉主失败。修复后 FallbackEngine 按 transcribe
调用记录事件：主失败脱敏因果链（只含异常类别，`__cause__`/`__context__`
有界遍历）、备用引擎类名、备用创建失败原因。管道在计时器关闭后取走事件。
一次成功的回退产生三处事实：`engine-fallback` 行（deviation）、终态
`published_degraded`（deviation）、`requested-outputs` 照常 expected——产物
符合请求与业务降级是两件事。`feedback_owner` 把 `published_degraded` 归入
SUCCEEDED：对账说"作业已交付"，deviation 说"要审视主引擎"。

### F4-04 默认交付：owner 自有持久收件目录

普通入口失败必须能在"宿主没有设置任何反馈变量"时被读回（审计结论
"根本没有默认观察"）。没有 `RESEARCH_FEEDBACK_OUT` 时，投影改为默认交付：
`RESEARCH_FEEDBACK_DIR` 指定隔离收件目录，否则 `RESEARCH_FEEDBACK_STATE_ROOT`
状态根下 `observations`，都缺省落本仓 `output/.feedback/observations`。
交付文件 `feedback-<32 位小写 UUID hex>.jsonl` 用同目录临时文件整体重写 +
原子替换发布，`.details.jsonl` 同法；进程终局补一次发布再原子写 `.ready`
JSON 标记（owner/run_id/attempt_id/step_id，不含路径与命令）。三个窗口：
强停在终局前 = 数据已落而 ready 未发（行仍可读、可对账）；ready 已发且回告
丢失 = 按记录过的交付身份重开同一文件补发，观察身份去重保证只登记一次；
并发读方只见完整文件（原子替换）。每个进程一个独立文件名，并发任务天然隔离。
交付失败只影响交付状态：业务返回、原请求、计量原样。

### F4-05 费用与用量保持未知

本仓没有用量收据，`cost-receipt` 恒为 unknown；details 的 `usage` 写
`{"known": false, "basis": "no_usage_receipt"}`。强停场景只保留启动/开始行，
不编造终态与用量；reconcile 的 job_status 与 cost_state 均如实。

## F4 独立接收发现

- 多步日志外层曾沿用旧单步字段，总控的身份校验合理。生产者使用既有多步 wire，绑定步号、行数和原字节，接收方仍采用同一机制。
- 只依赖单一位置会丢失普通操作反馈。原子写入失败时把同一身份投递到第二耐久目录。公开 owner 冷查询两处，Windows 长路径只在实际物理 I/O 边界处理。
- 总控确认整包和业务费用结算应独立。原作业有明确终态但未留付费凭据时，保留费用 unknown 并禁止重发。
