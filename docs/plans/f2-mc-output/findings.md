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
