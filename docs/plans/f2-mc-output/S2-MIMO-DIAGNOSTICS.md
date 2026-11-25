# S2-MC-MIMO-DIAGNOSTICS · MiMo 错误边界脱敏诊断

施工卡：[company-wiki/docs/plans/feedback-loop-2026-11-17/owner-cards/S2-MC-MIMO-DIAGNOSTICS.md](C:/Users/郑曾波/Projects/company-wiki/docs/plans/feedback-loop-2026-11-17/owner-cards/S2-MC-MIMO-DIAGNOSTICS.md)

工作目录 `C:/Users/郑曾波/Projects/MeetingConverter`，发布线 `master`，基线
`8c97cc5622c41db0e6e9c7d5d8618da074ff1ef5`。状态：实施、定向/全量回归与冷读完成；
第一轮独立审查的 5 条发现已修复，待最终源码复核与提交。

## 范围

只改本仓 MiMo 引擎的错误边界及其测试：

- `engines/mimo.py`：重试/耗尽日志只投影尝试序号、异常类型、HTTP 状态和本仓
  源码位置；`EngineError` 保持原类型，归因放在结构化属性上；原始异常不进入
  失败消息、`__cause__`/`__context__` 或默认 traceback。
- `exceptions.py`、`core/feedback.py`、`engines/fallback.py`：`exceptions.py`
  新增共享的 `explicit_cause_types`（只信任 `EngineError`、非空、最多 8 项、
  每项为标识符）；两个投影侧优先读取它。MiMo 切断原始链后，F4 的
  `errors[].cause_types` 与 `engine.primary_error.cause_types` 仍保留
  `HTTPError` 等底层类别；事件形状与词表不变。
- `tests/test_s2_mimo_diagnostics.py`：真实 `MiMoEngine` 与普通 CLI 入口 +
  确定性 transport 替身，覆盖首错后成功、重试耗尽、耗尽后回退、缺音频合法
  反例和 owner 端口冷读。
- `tests/f4_child_runner.py`：新增 MiMo transport 场景；引擎调用信号改为原子
  追加，消除强停用例在文件可见但内容未落盘时的既有竞态。
- `tests/test_s1_logging_resilience.py`：S1 的 MiMo 重试回归改按 S2 契约断言
  （有脱敏字段、无 `exc_info`），不再要求物化原始 traceback。
- 本 PWF 与 RED 收据 `receipts/s2-mimo-red.txt`。

未改 `transcribe.py`、`core/pipeline.py`、`core/batch.py` 和 CLI 输出契约；
未新增 owner 事件或 F4 词表。

## RED

在基线 `8c97cc5` 的临时 worktree 上复制本卡测试与 harness 后运行：

```text
python -B -X utf8 -m pytest -o addopts= -q --tb=short \
  tests/test_s2_mimo_diagnostics.py tests/test_s1_logging_resilience.py
```

实测 **8 failed / 3 passed**（0 import 错误）。失败均为行为断言：重试日志直接
打印 `HTTP Error 503: <供应商正文>` 和 traceback；耗尽后的 `EngineError` 正文
带原文；fallback/批量出口复现同样的泄露。完整输出见
[`receipts/s2-mimo-red.txt`](receipts/s2-mimo-red.txt)。

## GREEN

```text
python -B -X utf8 -m pytest -o addopts= -q \
  tests/test_s2_mimo_diagnostics.py tests/test_s1_logging_resilience.py \
  tests/test_mimo_engine.py
# 26 passed

python -B -X utf8 -m pytest -o addopts= -q tests/test_f4_ordinary_failures.py
# 33 passed

python -B -X utf8 -m pytest -o addopts= -q
# 357 passed
```

`ruff check engines/mimo.py tests/test_s2_mimo_diagnostics.py
tests/test_s1_logging_resilience.py tests/f4_child_runner.py` 全通过；
`git diff --check` 无空白错误。

## 冷读与契约

- `mimo-retry-success`：真实 CLI 首错后成功，原文真实产出，F4
  `publication-outcome=published_current`；owner `reconcile` 冷读为
  `job_status=succeeded`、`cost_state=unknown`，transport 调用数不变。
- `mimo-retry-exhausted`：真实 CLI 退出 1，无原文，F4
  `publication-outcome=transcription_failed`、`cost-receipt=cost_unknown`；
  owner `reconcile` 冷读为 `job_status=failed`、`cost_state=unknown`，不建
  收据库、不重跑转录。
- `mimo-fallback-success`：主引擎三次耗尽后备用成功，F4
  `engine-fallback=fallback_engaged`、`publication-outcome=published_degraded`；
  fallback 日志只含脱敏后的 `EngineError` 正文。
- `no-input`：退出 1，stdout 保留 `错误: 未找到音频文件`，无 traceback；F4
  `startup-outcome=request_rejected`。
- 合成凭据与供应商正文只存在于 transport 输入；stdout、stderr、observation
  和 details 均断言无泄露。

## 临时数据与边界

- 所有测试使用 `tmp_path` 或临时 worktree；合成 WAV 只在用例临时根。
- 显式 `COVERAGE_FILE` 与 `-o addopts=` 运行，checkout 中既有 `.coverage`
  字节/时间保持原样；`findings.md`、`progress.md`、`task_plan.md` 与
  `.mimosa/` 未纳入本卡改动。
- 既有 F2 harness worktree `_harness_worktrees/f2f/mc`（`codex/f2-mc-output@b1acea5`）
  已核对：工作树干净，未改 `engines/mimo.py` 或 `tests/f4_child_runner.py`，
  与本卡无重叠。
- pytest 的临时目录由宿主 safe-delete 批量保护拦截清理，位于系统临时区，
  不在本仓；本仓无新增运行残留。

## 独审与交接

- 第一轮独立审查（未参与实现）结论 **PASS-WITH-FINDINGS**，无阻塞问题。5 条
  发现及处理：
  1. 中：切断原始链后 F4 的 `cause_types` 退化为 `[]`。修复：`engines/mimo.py`
     的 `EngineError.cause_types` 保留原始异常自身类别；`core/feedback.py` 与
     `engines/fallback.py` 的投影优先读取该已脱敏属性；测试锁住
     `errors[0].cause_types == ["HTTPError"]` 与
     `engine.primary_error.cause_types == ["HTTPError"]`。
  2. 低：`_http_status` 对任意带 `code/status` 的异常都可能误判。修复：只认
     `urllib.error.HTTPError.code`；新增 `code=200` 的非 HTTP 异常反例。
  3. 低：`mimo-missing-input` 未在 harness 注册。修复：改用既有 `no-input`
     场景，CLI 契约断言不变。
  4. 低：引擎调用信号原子写波及既有 kill 场景。已披露；F4 套件 33 项通过，
     该改动消除的是既有竞态，保留。
  5. 低：未断言合成音频 base64 不外泄；`mimo` 与 `fallback` 的因果链实现
     分叉。修复：增加 base64 断言；`mimo` 侧改名为 `_cause_chain` 并明确
     返回含自身的完整链，投影侧按既有 `cause_types` 语义消费。
- 第二轮独立复核：上述 5 条全部关闭；另提 2 条低/信息，已处理：
  - 投影侧原先信任任意异常的 `cause_types` 同名属性。修复：只信任本仓
    `EngineError`，并限制最多 8 项、每项须为标识符；新增伪造属性反例。
  - 音频 base64 只有反向断言。修复：transport 记录
    `audio_b64_present` 布尔值（不记录正文），正向证明真实引擎把合成音频
    编码进了 outbound payload。
  - 文档残留 `mimo-missing-input` 改为实际 `no-input`；位置断言不再依赖
    traceback 一定存在。
- 第三/四轮最终只读确认：**PASS-WITH-FINDINGS（仅信息级）**。空列表 `[]` 曾会
  短路真实 `__cause__`；已把策略合并到 `exceptions.explicit_cause_types`，
  要求非空、最多 8 项、每项为标识符，空列表回退原生链。transport 的音频
  匹配改为严格相等；两处重复策略随之收敛；三连空行等格式项已清理。最终
  定向 26 项、F4 33 项、全量 357 项通过。
- 最终复核：第三/四轮已绑定最终源码树；提交后回填 SHA。
- 最终提交：待提交（提交后回填 SHA）。
- 交接给 ROOT：base、commit、本 PWF 链接、测试命令及结果、冷读引用、独审
  绑定的最终源码、临时数据处理说明。
