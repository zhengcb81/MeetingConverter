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

- RED：`tests/test_output_feedback.py` 先写，27 个用例在实现前全部失败
  （收据 `receipts/red-output-feedback.txt`）。
- 实施：新增 `core/feedback.py`（可选的 `feedback-observation/1` 投影，只写旁路
  与同名的 `*.details.jsonl` / `*.diagnostics.jsonl`）；`core/pipeline.py` 在流程
  边界记录每个 writer 的角色、产物标识与阶段结果，并保留既有 writer、原子替换、
  批处理与 CLI 返回语义。
- 词表：`requested-outputs` 取请求模式，`actual` 取本轮真正提交的结果；
  `previous_translations_only` / `partial_current` / `original_current` 三种情况
  分开；`reused_existing` 记跳过；`engine_started` / `engine_not_started` 记引擎
  是否真启动；费用恒为 `cost_unknown`（本仓没有用量收据）。
- GREEN：`tests/test_output_feedback.py` 29 过；定向包（output / pipeline /
  transcribe_integration / output_feedback）113 过；全量 283 过。

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

## 待办

- 独立 agent 独审（未参与实现），逐项修复后在最终实现 SHA 上复审。
- 写 `handoff.md`（含机器可读 JSON 摘要）、清理收据、提交并推送施工分支。
