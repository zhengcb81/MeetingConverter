# F4-MC-FAILURES 交接 · 普通入口的启动、翻译意图与引擎回退反馈

**lane** `F4-MC-FAILURES` · **owner** `meeting-converter` · **状态** 作者独审三轮、本仓独立验收及补修均已完成，源码已在本仓 master。

> F2 卡（MC-OUTPUT）的历史交接保留在本文件后半部分；作者原文与样例可从 b1acea5 查询。

## 1. 身份与提交位置

| 项目 | 值 |
|---|---|
| 卡号 | F4-MC-FAILURES（[F4-MC-FAILURES.md](F4-MC-FAILURES.md)） |
| 工作目录 | `C:/Users/郑曾波/Projects/MeetingConverter`（主仓，发布线 `master`） |
| 基线 | `101124f`（HEAD；工卡引用的审计基线 `e7b6c021` 与生产码 `8b8e574f` 在本卡相关路径上与之一致） |
| 最终源码和独立复验版本 | 0e3c4a396ef9f571989cc4543d23b34a840564bd |
| 发布分支 | master，按正常 Git 流程发布。 |
| 对应原发生 | run `f4-coverage-audit-20261121`，attempt `baseline-e7b6c021`，`failure-coverage-20261121.jsonl` 第 23 行 `initialization/native-failure-not-forwarded` 与第 24 行 `fallback/degraded-work-hidden` |
| 本仓 PWF | `docs/plans/f2-mc-output/`（progress/findings/runtime/receipts 的 F4 段落） |

## 2. 写范围与披露

卡面写范围内的改动：`transcribe.py`、`core/pipeline.py`、`core/feedback.py`、
`engines/fallback.py`、`feedback_owner.py`、`tests/`（新测试 + 子进程运行器 +
conftest 隔离 + 三处既有断言按新语义更新）、`docs/plans/f2-mc-output/`。

一处超出卡面文件清单的披露：**`core/batch.py`** 仅新增
`translate_requested` / `translator_ready` / `translator_error_type` 三个可选
透传参数（默认 `None` 时行为与旧版逐字等价）。它是 `transcribe.py`（范围内）
把请求意图传到 `core/pipeline.py`（范围内）的唯一通道；独审 H 项复核为最小
改动、旧调用方零行为变化。

## 3. RED 与 GREEN（真实运行）

| 收据 | 命令 | 结果 |
|---|---|---|
| RED（基线 101124f 临时 worktree） | `python -B docs/plans/f2-mc-output/receipts/make_f4_red_receipt.py` | **25 failed / 2 passed**，0 import 错误（[red-f4-ordinary-failures.txt](receipts/red-f4-ordinary-failures.txt)）；独审重放 27 failed / 2 passed（重放时测试文件已多 2 用例，仍全红） |
| F4 包 | `python -B -m pytest -o addopts= -p no:cacheprovider -q tests/test_f4_ordinary_failures.py` | **31 passed** |
| 卡面回归四包 + f4 + fallback + batch + feedback_owner + output_feedback | 同上七个文件 | **130 passed**（8+48+19+10+31+4+10） |
| 全量 | `python -B -m pytest -o addopts= -p no:cacheprovider -q` | **343 passed, 0 failed, 0 skipped** |
| ruff | `python -B -m ruff check <13 个改动/新增文件>` | 告警构成与基线逐项相同（transcribe.py 9、conftest 2、batch 1 均为既有），**净增 0**，新文件 0 告警 |

以上为作者结果。独立接收全量为 **345 passed**，Windows Python 3.13，52.03 秒。新增 RED 查出 wire 不相容、主目录不可写后的漏报，另以隔离长路径用例覆盖 Windows 收据写入和冷对账。反馈、owner 和新测试通过 Ruff。

新测试全部以真实子进程调用普通 CLI（`tests/f4_child_runner.py` 只装配
`sys.argv` 后 `raise SystemExit(transcribe.main())`），环境白名单清除
`RESEARCH_FEEDBACK_*` 与一切密钥、桩住 config 读取；断言由测试进程在子进程
退出后**冷读**交付文件得出。独审用独立探针复放了 11 场景矩阵与脱敏扫描。

## 4. 对照清单（分母 = 审计探针 mc.py 注入的 10 个入口场景）

| 探针场景 | 实测（冷读交付文件） | 状态 |
|---|---|---|
| no-input | exit 1；`startup-outcome actual=request_rejected`（stage=input），`invocations` 显示 engine/translation 未发送 | 已覆盖 |
| invalid-cli | exit 2（argparse 原生保留）；`request_rejected`（stage=parsing，exit_code=2） | 已覆盖 |
| output-dir | exit 1；`local_io_failed`（stage=output_dir，OSError 家族类别 + 相对代码位置） | 已覆盖 |
| engine-init | exit 1；`initialization_failed`（stage=engine_init，ValueError），走真实工厂未桩 | 已覆盖 |
| translator-init | exit 0；expected 仍 `original_translated_bilingual_current`，actual=`translation_unavailable`，writer `not_run`，终态 `published_incomplete`；原文 SHA=盘上字节、`fingerprint_source=committed_writer`；details `translation.unavailable_error_type=ValueError` | 已覆盖（两条 issue 关闭） |
| fallback | exit 0；`engine-fallback primary_only→fallback_engaged`（deviation）、终态 `published_degraded`（deviation）、`requested-outputs` 仍 expected（成功与降级同时成立）；details 主失败链 `RuntimeError→TimeoutError` | 已覆盖 |
| provider | exit 1；终态 `transcription_failed`；details errors 因果链含 `TimeoutError`；同外层内因 ValueError 的对照冷读可分辨 | 已覆盖 |
| writer | exit 1；`writer-original failed`、sha256=None（失败角色不报提交指纹）；终态 `write_failed` | 已覆盖 |
| reuse | exit 0；引擎/翻译零调用（signal 文件不存在）；`engine_not_started` + `reused_existing`；旧字节原样 | 已覆盖 |
| kill | 强停后 `run-started` + `action-started` 可读、无终态无 cost 行；两次并发 reconcile 均 unconfirmed/unknown 且结果一致；engine_calls 前后差 0 | 已覆盖 |

**强停/交付三窗口**：终态已写被强停 → 行可读、`.ready` 缺失、reconcile=succeeded；
已发但回告丢失 → 按记录过的交付身份重开同一文件补发，观察身份去重零新增行；
并发消费 → 读方循环冷读只见完整 JSON 行、终态不丢。

**原因仍未知/未在现场实测**：符号链接输入（Windows 无特权建 symlink，沿 F2
口径由 `Path.resolve()` 语义推断）；真实网络级 provider 故障（探针边界与审计
一致，用本地替身）；`--help`（exit 0）记为 `accepted`（stage=parsing、
exit_code=0、不产生逐文件行）——受理的合法调用，独审 info 项，语义如实写明。

## 5. 直启发布接口（ROOT 接入要点）

- 主收件目录为 C:/Users/郑曾波/Projects/MeetingConverter/output/.feedback/observations。写入故障使用本仓耐久恢复目录 C:/Users/郑曾波/Projects/MeetingConverter/output/.feedback/recovery。
- ROOT 用现有 native_observation_dirs 订阅两处，owner 公开端口为每处各传一次 --sidecar-dir。RESEARCH_FEEDBACK_STATE_ROOT 可同时隔离 observations 与 recovery；RESEARCH_FEEDBACK_DIR 只改主收件路径。显式 RESEARCH_FEEDBACK_OUT 沿用单次文件契约。
- 普通 CLI 每个进程使用独立的反馈名称、run/attempt 与明细。数据和明细写入后才生成 feedback-delivery-ready/1，记录 step_ids、两份行数和真实字节 SHA-256。中断时仍可读已有行。已确认的同内容交付不会重新打开 ready。
- owner 的 reconcile 只读原作业。备用成功保持 succeeded 与 published_degraded，并保留原异常链。缺原用量凭证时保持 cost_unknown。恢复不调用转录或翻译。

## 6. 可直接冷读的脱敏观察与明细

四份样例均为真实运行产物（`python -B docs/plans/f2-mc-output/receipts/make_f4_samples.py` 再生）：

| 文件 | 场景 | 行数 | 关键行 |
|---|---|---|---|
| [f4-sample-startup-rejected.jsonl](receipts/f4-sample-startup-rejected.jsonl) | 无输入，请求拒绝 | 2 | `startup-outcome accepted→request_rejected`（deviation） |
| [f4-sample-translation-unavailable.jsonl](receipts/f4-sample-translation-unavailable.jsonl) | 默认请求翻译、翻译器初始化失败 | 10 | `requested-outputs →translation_unavailable`、writer-translated `not_run`、终态 `published_incomplete` |
| [f4-sample-fallback-degraded.jsonl](receipts/f4-sample-fallback-degraded.jsonl) | 主引擎 TimeoutError、备用成功 | 11 | `engine-fallback →fallback_engaged`、终态 `published_degraded` |
| [f4-sample-started-only.jsonl](receipts/f4-sample-started-only.jsonl) | 替身进入转录后强停 | 2 | 仅 `run-started` + `action-started`，**无 `.ready`** |

同尝试的明细在同名 `.jsonl.details.jsonl`：`engine`（fallback_engaged /
primary_error 链）、`translation`（requested/ran/unavailable/原因类别）、
`usage`（known=false + basis）、errors（error_type + cause_types + location）。
样例的 step/input_id 由临时路径散列而来、随运行变化；样例与 details 均无绝对
路径、音频名与原始异常正文（独审脱敏扫描零命中）。

## 7. 独审三轮发现与修复逐项关闭

第一轮（候选=工作树 vs 101124f）：**PASS-WITH-FINDINGS**，无 blocker，9 条
findings（4 minor / 5 info）；第二轮（当时树复核）：8 项全部 PASS，新发现
1 条 major（finalize 门槛）、1 条 minor（本文件当时未补齐）、2 条 info；
第三轮（finalize 修复后的最终树）：**PASS**——major 修复经穿过/耗尽两分支
二分探针、确定性回归与专属测试三重证实，`_drain` 边界全部符合声明，无新
blocker，无遗留必修项。
逐项关闭（详见 [progress.md](progress.md)「F4 独审与修复」）：

| # | 严重度 | 发现 | 关闭方式 |
|---|---|---|---|
| 1 | minor | progress.md 计数与树不符 | 按当前树更正（30/129/342），复审重跑一致 |
| 2 | minor | 默认交付发布失败无回归 | 新增 `test_delivery_publish_failure_keeps_the_business_outcome` |
| 3 | minor | `published_degraded` 无 reconcile 用例 | 新增 `test_degraded_publication_reconciles_as_a_delivered_job` |
| 4 | minor | 交接 Markdown 缺 F4 段 | 本文件补齐 |
| 5 | info | `--help` 记 accepted | 保留，语义写明（§4） |
| 6 | info | 并发测试名不副实 | 改名 + 新增真并发读方用例 |
| 7 | info | 发布失败的行不应进 `.ready` step 清单 | `record` 仅在落盘成功后计数 |
| 8 | 复审新增 | **Windows 并发读者使 `os.replace` 瞬时失败时，撤行策略丢最后一批行（终态丢失）** | 发布失败保留内存行（重投不重复追加）+ 替换退避重试 4×10ms；差分探针 2/50 → 50/50 |
| 9 | info | `.ready` step 清单口径 | 盘上播种 + 落盘成功才计数；表述为"盘上内容的下界" |
| 10 | **major（第二轮）** | `finalize_delivery` 对观察/明细发布结果取 OR：观察失败而明细成功仍写 `.ready`，缓冲行滞留丢失 | 观察与明细分别 `_drain` 有界补投，任一未落盘返回 False 且**不写 `.ready`**——缺 ready 即未确认区间；专属回归 `test_finalize_without_published_observations_writes_no_ready`；第三轮复审确认 **PASS**（二分探针：常规压力补投穿过 50/50+ready；极限压力 finalize=False、无 ready=未确认区间；不存在"ready 已写但行滞留"） |

## 8. 清理收据

| 项 | 结果 |
|---|---|
| 开工前既有脏项 | `.coverage`（M）与 `.mimosa/`（??）保持原样，未进本卡 |
| 测试临时根 | pytest 与两个收据脚本均用临时目录并在 finally 自清理；独审 agent 全部探针位于 `%TEMP%` 并自报清理完毕（两轮均核对了 `git status` 复原） |
| 默认收件目录 | 作者已标注的 no-input 样本 feedback-97c4febaf48145d0aed9f69733bd103a 三件移至本仓 output/.feedback/acceptance-samples/author-20261121，SHA-256 与原字节相符。 |
| 主仓工作树 | 仅本卡改动文件 + 上述既有脏项；独审一轮误写的 `.diff` 已由其自行删除并复核 |

## 9. 独立验收

作者的 ZCode 提交曾受 Mimosa 门禁影响。接收方按正常 Git 流程，在本仓 master 形成源码提交 0e3c4a396ef9f571989cc4543d23b34a840564bd。既有 .coverage、.mimosa/ 及其他工作树均未加入提交。

本仓实际调用普通入口，独立 owner 子进程从两个目录查回原终态，费用保持 unknown，转录、翻译或供应商调用零新增。已再生 4 份原生样例；3 份完成标记均绑定真实字节，强停样例只有可读开始行。

## 10. 总控组合边界

使用实际 company-wiki local_host recover 与隔离的两路原生普通 CLI 交付复验。首次登记 21 行，两个包有 ACK，剩余和诊断均为 0。新进程再次恢复处理 0 行。原始观察与明细 4 个文件的 SHA 不变。主、备原始调用数仍各为 1、2。旧总控把费用未知和整包确认混在一起。修复后能确认已查回终态的交付，费用事实仍为 unknown。正式总控接线和原发生回告由 ROOT 执行。

## 11. 机器摘要

```json
{"lane":"F4-MC-FAILURES","owner":"meeting-converter","base":"101124f","implementation":"0e3c4a396ef9f571989cc4543d23b34a840564bd","reviewed_commit":"0e3c4a396ef9f571989cc4543d23b34a840564bd","branch":"master","occurrences":["failure-coverage-20261121.jsonl#L23","failure-coverage-20261121.jsonl#L24"],"tests":[{"command":"python -B -m pytest -o addopts= -p no:cacheprovider -q tests/test_f4_ordinary_failures.py","result":"31 passed"},{"command":"python -B -m pytest -o addopts= -p no:cacheprovider -q tests/test_feedback_owner.py tests/test_output_feedback.py tests/test_pipeline.py tests/test_transcribe_integration.py tests/test_fallback.py tests/test_batch.py","result":"130 passed"},{"command":"python -B -m pytest -o addopts= -p no:cacheprovider -q","result":"343 passed"},{"command":"python -B -X utf8 -m pytest -q -p no:cacheprovider -o addopts= tests","result":"独立接收 Windows 3.13: 345 passed in 52.03s"}],"red":{"command":"python -B docs/plans/f2-mc-output/receipts/make_f4_red_receipt.py","result":"25 failed / 2 passed at 101124f"},"review":"作者独审 3 轮 + 独立接收 345 passed，补齐 wire、持久恢复和 Windows 长路径","sample_refs":["docs/plans/f2-mc-output/receipts/f4-sample-startup-rejected.jsonl","docs/plans/f2-mc-output/receipts/f4-sample-translation-unavailable.jsonl","docs/plans/f2-mc-output/receipts/f4-sample-fallback-degraded.jsonl","docs/plans/f2-mc-output/receipts/f4-sample-started-only.jsonl"],"default_inbox":"C:/Users/郑曾波/Projects/MeetingConverter/output/.feedback/observations","cleanup":"作者活样本保留原字节后迁至本仓试验归档。既有覆盖率和 Mimosa 产物未纳入提交。","remaining":["ROOT 订阅生产两处原生交付","ROOT 回告两条原发生"],"recovery_inbox":"C:/Users/郑曾波/Projects/MeetingConverter/output/.feedback/recovery"}
```

---

# MC-OUTPUT 交接 · F2-MC-OUTPUT 会议转录发布反馈（历史）

> 以下是 b1acea5 作者交接的历史说明和样例摘录。ROOT 复核后的源码、实测和再生样例以本卡 [进度](progress.md#2026-11-19-root-组合验收) 与现行 receipts 为准。作者原样例可从 b1acea5 查询。


**lane** `F2-MC-OUTPUT` · **owner** `meeting-converter` · **状态** 实现、独审、修复、复审均已完成；等待 ROOT 接收。

## 1. 身份与提交位置

| 项目 | 值 |
|---|---|
| 工作目录 | `C:/Users/郑曾波/Projects/_harness_worktrees/f2f/mc` |
| 分支 | `codex/f2-mc-output` |
| base SHA | `b43a76a3cdc25928a75e583b65a5a706802985ce`（`origin/master`） |
| 实施 SHA | `8806ff4`（交付树；链路为 `6385f11` 首版实施 → `779aa1b` 第一轮独审修复 → `8806ff4` 第二/三轮独审修复 + 交接文档） |
| 复审 SHA | `8806ff4`（三轮独立复审均覆盖到这棵树，逐项关闭表见 §5） |
| 提交位置 | 本分支 `codex/f2-mc-output`，未推送、未并入 `master`；ROOT 负责接收并并入主线 |
| 本仓 PWF | `docs/plans/f2-mc-output/`（`task_plan.md` / `findings.md` / `progress.md` / `issues/` / `receipts/`） |

## 2. 交付了什么

本仓在转录流程边界加一个**可选**的 `feedback-observation/1` 投影，使外部能区分
四件本来无法区分的事：

| 情形 | `requested-outputs` 的 actual |
|---|---|
| 一次成功的原文模式 | `original_current` |
| 启用翻译，三件齐全且都是本轮产出 | `original_translated_bilingual_current` |
| 译文/对照**只保留了上一版** | `previous_translations_only` / `stale_and_missing_translations` / `missing_translations` |
| 只提交了部分目标 | `partial_current` |
| 命中"原文已存在则跳过" | `reused_existing` |

- 新增 `core/feedback.py`：只写 `RESEARCH_FEEDBACK_OUT` 指定的 JSONL 与同名的
  `*.details.jsonl` 步骤日志；不写 stdout/stderr，不改返回值，不改任何产物字节。
- `core/pipeline.py`：在流程边界记录每个 writer 的角色、产物标识与阶段结果；
  **保留**既有 writer、单文件原子替换、段数守卫、跳过规则、批处理统计与 CLI
  返回语义。
- 修正 `tests/test_transcribe_integration.py` 的成功夹具（两段间隔 5 秒 > 2 秒
  合并阈值，并断言 translator 真的收到两段）；`tests/test_output.py` 的真实段数
  不符拒绝断言**原样未动**。
- 新增 `skills/repair-meeting-converter-issue/SKILL.md` 与 `issues/` 下两张根因卡
  （生产问题与测试夹具问题分别归因）。

### 冻结面（与基线字节相同，独审已用 blob 哈希核对）

`core/output.py`、`core/batch.py`、`transcribe.py`、`tests/test_output.py` 未被改动。

## 3. 测试命令与结果

```
python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_output.py tests/test_pipeline.py tests/test_transcribe_integration.py tests/test_output_feedback.py
# → 127 passed

python -B -m pytest -q -o addopts= -p no:cacheprovider
# → 297 passed

python -B -m ruff check core/feedback.py core/pipeline.py tests/test_output_feedback.py tests/test_transcribe_integration.py
# → All checks passed!
```

- `-o addopts=` 关闭覆盖率（`pytest.ini` 默认带 `--cov`），因此两处 `.coverage`
  按字节保留（见 §7）。
- 0 failed / 0 skipped（全量）。定向包 127 过。
- 仓内 `ruff check .` 基线 58 项，本卡交付时 53 项（**新增 0**，净减 5）；四项改动
  文件自身 0 告警。
- 本卡测试与收据脚本全部使用合成音频与 stub 引擎/翻译器，**不接触网络、凭证、
  真实音频或其他仓的服务**。

### RED 收据（真实运行，不是手写）

`receipts/red-output-feedback.txt`：在基线 `b43a76a` 的临时 worktree 里跑本卡新
测试，实测 **31 failed / 9 passed / 1 skipped**，**0 个 import 错误** —— 失败理由
是行为断言（"旁路启用后必须产生观察行"、"期望恰好一行 action-started，实际
[]"）。唯一的 skip 是修复后的回归护栏（基线没有反馈适配器，用
`pytest.importorskip` 如实跳过）。复现命令：

```powershell
python -B docs/plans/f2-mc-output/receipts/make_red_receipt.py
```

### 基线收据

- `receipts/base-commit-fixture-failures.txt`：基线上
  `tests/test_transcribe_integration.py` 真实 **4 failed / 5 passed**
  （`OutputCountMismatchError: expected 1, actual 2`）。
- `receipts/base-commit-stale-output.txt`：基线上翻译失败时**退出 0**、译文与对照
  **保留上一版字节**、原文是本轮的、仓里**没有任何机制**能说明这一点。

```powershell
python -B docs/plans/f2-mc-output/receipts/make_base_receipt.py
```

## 4. 实际输出的最小 JSONL 样例

四份样例都是真实跑出来的（`receipts/make_samples.py` 走公开入口
`core.transcribe_one`），不是手写协议样例。

| 文件 | 场景 | 行数 |
|---|---|---|
| `receipts/sample-success.jsonl` | 翻译模式，三件齐全 | 8 |
| `receipts/sample-stale.jsonl` | 翻译失败，原文是本轮、译文保留上一版 | 8 |
| `receipts/sample-started-only.jsonl` | 硬停止（子进程 `os._exit`），只剩开始行 | 1 |
| `receipts/sample-replay.jsonl` | 同一输入重投 | 11 |

复现命令：

```powershell
python -B docs/plans/f2-mc-output/receipts/make_samples.py
```

### 成功（`sample-success.jsonl`，step `meeting-operation/9666ea36a2c9`）

```jsonl
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-success","attempt_id":"attempt-1","step_id":"meeting-operation/9666ea36a2c9","check_id":"writer-translated","expected":"committed_this_round","actual":"committed_this_round","disposition":"expected","evidence_ref":"mc-output/9666ea36a2c9/translated","version":"meeting-converter-feedback/1.0.1","details_ref":"fb-bf4665083473f321"}
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-success","attempt_id":"attempt-1","step_id":"meeting-operation/9666ea36a2c9","check_id":"requested-outputs","expected":"original_translated_bilingual_current","actual":"original_translated_bilingual_current","disposition":"expected","evidence_ref":"mc-output/9666ea36a2c9","version":"meeting-converter-feedback/1.0.1","details_ref":"fb-bf4665083473f321"}
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-success","attempt_id":"attempt-1","step_id":"meeting-operation/9666ea36a2c9","check_id":"publication-outcome","expected":"published_current","actual":"published_current","disposition":"expected","evidence_ref":"mc-output/9666ea36a2c9","version":"meeting-converter-feedback/1.0.1","details_ref":"fb-bf4665083473f321"}
```

### 陈旧/部分（`sample-stale.jsonl`，step `meeting-operation/aed69f880538`）

```jsonl
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-stale","attempt_id":"attempt-1","step_id":"meeting-operation/aed69f880538","check_id":"writer-translated","expected":"committed_this_round","actual":"previous_kept","disposition":"deviation","evidence_ref":"mc-output/aed69f880538/translated","version":"meeting-converter-feedback/1.0.1","details_ref":"fb-0624bb01c99ecbb7"}
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-stale","attempt_id":"attempt-1","step_id":"meeting-operation/aed69f880538","check_id":"requested-outputs","expected":"original_translated_bilingual_current","actual":"previous_translations_only","disposition":"deviation","issue_key":"stale-output-success","evidence_ref":"mc-output/aed69f880538","version":"meeting-converter-feedback/1.0.1","details_ref":"fb-0624bb01c99ecbb7"}
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-stale","attempt_id":"attempt-1","step_id":"meeting-operation/aed69f880538","check_id":"publication-outcome","expected":"published_current","actual":"published_incomplete","disposition":"deviation","evidence_ref":"mc-output/aed69f880538","version":"meeting-converter-feedback/1.0.1","details_ref":"fb-0624bb01c99ecbb7"}
```

### 仅开始（`sample-started-only.jsonl`，step `meeting-operation/f60d0ce5ee1f`）

```json
{"schema_version":"feedback-observation/1","owner":"meeting-converter","run_id":"mc-sample-started-only","attempt_id":"attempt-1","step_id":"meeting-operation/f60d0ce5ee1f","check_id":"action-started","expected":"started","actual":"started","disposition":"expected","evidence_ref":"mc-output/f60d0ce5ee1f","version":"meeting-converter-feedback/1.0.1","terminal_check_id":"publication-outcome","details_ref":"fb-e951f73d7caa0d96"}
```

没有配对的 `publication-outcome` ⇒ 终态为 **unknown**，本卡不做任何自动重转录。

### 配对身份、evidence_ref 与重放的零新增计数

- **配对身份**：一次转录 = 一个 `step_id`（`meeting-operation/<input_id>`），
  该 step 下的 `action-started` 与 `publication-outcome` 通过
  `terminal_check_id=publication-outcome` 配对。
- **稳定 evidence_ref**：`mc-output/<input_id>` 与 `mc-output/<input_id>/<role>`；
  不含音频名、不含绝对路径。
- **原引擎启动次数**：`transcription-started` 行给出 `engine_started` /
  `engine_not_started`；`sample-replay.jsonl` 的第一次转写是 `engine_started`，
  第二次重投是 `engine_not_started`。
- **重放的零新增计数**：`make_samples.py` 实测输出
  `replay: engine_calls=1 translator_calls=1 rows_before=8 rows_after=11` ——
  重投**没有**再调引擎或翻译器；多出的 3 行是这一轮自己的复用事实
  （`engine_not_started` / `reused_existing` / `reused_existing`），同身份同内容
  的行不重复写。
- ⚠️ **样本的 `evidence_ref` 由输入路径散列而来**，因此随运行目录变化；上面引用的
  具体 ID 属于本仓当前这份收据，ROOT 复验时应按同一规则重新计算，不要假定跨机器
  相同。

## 5. 独审与发现逐项关闭

两次独立审查都由**未参与实现的 agent**完成，只读，不改实现。

### 第一轮（针对 `6385f11`）：结论 FAIL，19 条发现

5 条 major/blocker 已全部修复并提交为 `779aa1b`：

| # | 发现 | 关闭方式 |
|---|---|---|
| 1 | 目的地不合法（`RESEARCH_FEEDBACK_OUT="C:\"`）时 `Path.with_name` 抛 `ValueError`，整个转录在引擎启动前崩掉 | recorder 构造被兜住，旁路不可用时退化成空操作 |
| 2 | 旁路写入落在 STT/输出计时区间内，改变三个产物文件的字节 | 观察行先缓冲，只在没有计时器打开时 flush；开始行在计时前落盘 |
| 3 | `*.details.jsonl` 带绝对路径、音频名与未脱敏异常正文 | 脱敏为原生异常类别 + `<path>`/`<input>` 占位 + 逐角色散列 + metrics；未脱敏事实留在本仓日志 |
| 4 | RED 收据是手写 traceback | 改为真实运行（`make_red_receipt.py`） |
| 5 | 宿主不给运行身份时 `run_id` 每次重新生成 | 进程内单一回退运行身份 |

其余 minor/info（跳过时 `expected` 恒定、混合陈旧/缺失缺专属词、同名两个输入
第二次命中跳过、禁用旁路断言空转、问题卡缺基线收据、progress 计数过期、文档
字符串乱码、`issue_key` 未用、诊断通道是新建的、未使用的 `import time`）也一并
处理。

### 第二轮复审（针对 `779aa1b` + 已复核修正）：结论 PASS-WITH-FINDINGS

| # | 严重度 | 发现 | 关闭方式 |
|---|---|---|---|
| N-a | 必须修 | `published_partial` 不可达（writer 失败一律 re-raise → `write_failed`） | 写盘失败且**已提交部分目标**时发 `published_partial`；一个目标都没提交才发 `write_failed`；两者各有回归用例 |
| N-b | 必须修 | 失败路径上 details 的 metrics 全为 0 | 段落数/字数在计时区间内记账，输出耗时用 `finally` 记账，总耗时在异常分支补记；新增断言 |
| N-c | 必须修 | 收据里残留机器绝对路径 | 两个收据脚本统一脱敏（`<PYTEST_TMP>` / `<ABS_PATH>`）后重新生成；全部收据现为 0 命中 |
| N-d | 必须修 | `stale_and_missing_translations` 无回归用例；`issue_key` 对 `missing_translations` 过度声称 | 补混合状态回归用例；`issue_key` 收窄为"旧件确实留存"的两种状态；问题卡写明范围 |
| N-e | 必须修 | 问题卡引用的 `evidence_ref` 在收据里不存在 | 改为收据里真实存在的 `mc-output/aed69f880538` |
| N-j | 必须修 | `findings.md` F2-04 仍描述已删除的 diagnostics 文件与未脱敏 details | 更新为实际契约 |
| N-f | 建议 | POSIX 单段路径（`/root`）未脱敏 | 正则放宽到单段绝对路径 |
| N-g | 建议 | `OperationFeedback.output_dir` 是死字段 | 删除 |
| N-h | 建议 | 写盘时抛 `BaseException` 会替换业务结果 | `flush()` 逐行兜住任何异常，记为不完整诊断 |
| N-i | 建议 | 没写完的旁路以 `cost-receipt` 收尾 | 终态行改为最后写：没写完一定以"没有终态"收尾 |
| N-k | 建议 | details 是第二个产物，消费方要收两个文件 | 本文件 §2 与 SKILL.md 写明 |
| N-l | 建议 | `progress.md` 的"ruff 干净"措辞不准 | 改为"本卡改动文件 ruff 无告警；仓内 53 项（基线 58，本卡净减 5）" |

复审确认的正面结论：上一轮 5 条 major 全部关闭且有独立证据（修复前代码实测
`转写时间: 0.2秒`，修复后 `0.0秒`）；冻结面与基线**字节相同**；没有测试能到达
真实 provider；旁路启用前后返回值、stdout/stderr 与三个产物文件的字节一致。

### 第三轮复审（针对 `779aa1b` + 本轮全部修正）：结论 PASS-WITH-FINDINGS

无 blocker/major。第二轮的 12 条 N 发现已全部关闭，另新查到 12 条（NEW-1…NEW-12），
其中 6 条必须修、4 条建议、2 条 info。第三轮确认无回归：冻结面字节未动、CLI 退出码
与标志、批处理统计、`paragraph_level=True` 路径、重投/重试语义、缓冲丢失语义实测均
无问题；三个收据脚本重跑后与已提交收据归一化逐字节一致（样本的 `input_id` 由路径
派生、随运行变化，按文档描述的行为判定）。

| # | 严重度 | 发现 | 关闭方式 |
|---|---|---|---|
| NEW-1 | 必须修 | N-f 放宽正则后新增过度脱敏：`error:/root` 的 `r` 被当成盘符吞掉、`20%/30%` 与 `（/备注）` 被吃 | 盘符前加负向断言；POSIX 的 `/` 前排除词字符/百分号/括号、`/` 后须像路径开头。正反两向各有回归用例 |
| NEW-2 | 必须修 | 失败路径上 `stt_elapsed`/`translate_elapsed` 仍为 0.0 | 与 `output_elapsed` 同法用 `finally` 记账；新增"干了一会儿才失败"的回归用例 |
| NEW-3 | 必须修 | details 落盘失败时 observation 仍带 `details_ref`（悬挂引用） | 只在 details 真正落盘后才写 `details_ref`；正反两向各有用例 |
| NEW-4 | 必须修 | writer 的 `except Exception` 不接 `BaseException`，写盘中被打断时 writer 行缺失 | 改为 `except BaseException`，先记行再抛 |
| NEW-5/6/7 | 必须修 | `progress.md` 三处数字与收据/实测不符 | 逐处更正（24→27、113/283→115/285、"全部失败"→按收据实数） |
| NEW-8 | 必须修 | `make_base_receipt.py` 有未使用的 `import os`，"本卡未新增告警"不成立 | 删除；重测后仓内 53 项（基线 58，本卡新增 0、净减 5），措辞同步更正 |
| NEW-9 | 建议 | 问题卡 occurrences 表含一行范围外的 `partial_current` | 标注为非本 `issue_key` 覆盖、另卡处理 |
| NEW-11 | 建议 | "不写 stdout/stderr"在 CLI 配置下不精确（诊断经 logging 走 stdout） | 模块文档补一句说明 |
| NEW-10 | info | 两个进程并发追加同一侧车会丢行且不可检测 | 沿用"一个调用者独占 `RESEARCH_FEEDBACK_OUT`"的契约，§6 写明 |
| NEW-12 | info | 机器摘要里的 SHA 在最终提交前会失真 | 提交后回填 |

第三轮未见问题的探针：`paragraph_level=True` 路径（`paragraphs` 是 `Segment` 列表，
`len()`/`.text` 全链路正常）、`run_batch` 单文件失败时统计与反馈行、一次批量同时含
新输入/跳过/写盘失败三种、同进程重投去重、侧车已含旧行时的扫描、换
`RESEARCH_FEEDBACK_ATTEMPT_ID` 的重试、`input_id` 对绝对/相对路径同源且缺失文件可
散列不抛错、缓冲在各条路径上都不丢行。**未能验证**：符号链接（Windows 无特权建
symlink），由 `Path.resolve()` 语义推断同源归一。

### 仍需 ROOT 组合验收的事项

- 本卡只证明"本仓能区分"四类情形；**跨仓组合**（ROOT 读取旁路、登记 issue、
  派修）未做，需 ROOT 侧验证。
- 样本 `evidence_ref` 随路径变化，ROOT 复验时按同一规则重算。
- 消费方复验状态：`issues/stale-output-success.md` 的"consumer re-verification"
  仍为 **pending**，须由发现方在修复版上重跑原场景后关闭。

## 6. 仍需跨仓组合的事项（ROOT）

1. ROOT 读取 `<RESEARCH_FEEDBACK_OUT>` **与** `<RESEARCH_FEEDBACK_OUT>.details.jsonl`
   两个文件（后者是本仓的脱敏步骤日志）。
2. 本仓没有用量收据，费用恒为 `cost_unknown`（`cost-receipt` 行，
   disposition=`unknown`），ROOT 不能据此对账花费。
3. 真实重试应使用**新的 `attempt_id`**；同身份同内容的重投不新增行。
4. **一个调用者独占一个 `RESEARCH_FEEDBACK_OUT`**：两个进程并发追加同一个
   侧车文件会丢行且无法检测，本卡不设文件锁。跨进程共用目的地请改为各自
   分配独占文件，再由 ROOT 合并读取。
5. `published_partial`（部分提交）与 `published_incomplete`（本轮没产出译文）
   在 `publication-outcome` 上也是分开的两个词，ROOT 的分诊表要与词表一致。

## 7. 清理收据

| 项 | 结果 |
|---|---|
| 主仓 `.coverage` | 字节未变：`53248` 字节，sha256 `6670792e382d6b97dbb38bf06fdd719141692cfbe29f87bf703f1aa7cb3c5d9c`（与开工时一致，仍是既有的 ` M .coverage`） |
| 本卡 `.coverage` | 字节未变：`53248` 字节，sha256 `6c27350e89ce47b7804774455f9f9d04c4b23f479129df2fcf215b8571e20333`（未进任何提交） |
| 旧产物指纹 | 本卡**没有**产出真实转录产物；三个输出文件的旧字节由 `receipts/base-commit-stale-output.txt` 的 `translation_file_kept_previous_bytes: True` / `bilingual_file_kept_previous_bytes: True` 核对，`tests/test_output_feedback.py` 另用 sha256 与磁盘上的旧文件互相核对 |
| 测试根删除 | 收据脚本用 `tempfile.mkdtemp()` 建临时目录并在 `finally` 里 `shutil.rmtree`；临时 git worktree 用 `git worktree remove --force` 移除。终检 `git worktree list` 只有主仓与本卡两个；系统临时目录无本卡残留（`mc-ca-*` 是别条线的，与本卡无关） |
| 主工区变动 | 主仓 HEAD 仍 `b43a76a`，工作树只有既有的 ` M .coverage` 与 ZCode 插件自己的 `.mimosa/` 状态目录（插件产物，非本卡）。复审 agent 一度在主仓留下 `relative/out.jsonl*`（探针产物），已删除并复核 |
| 本卡工作树 | 提交后应为干净；提交门禁见 §8 |

## 8. 提交门禁（ROOT 接收时需要知道）

本仓的提交被 ZCode 的 **Mimosa 提交前 L3 安全门**拦过：它拦的是**主仓既有文件**
的 14 个 high（`tests/conftest.py` 的假凭据字面量、`compare_engines.py` /
`company_manager.py` 等的 `open` 路径穿越、`translator.py` / `engines/mimo.py`
调用 LLM API 的 SSRF 形态），**本卡改动的四个文件在同一次审计下 0 命中**：

```powershell
cd C:/Users/郑曾波/Projects/_harness_worktrees/f2f/mc
node "C:/Users/郑曾波/.zcode/cli/plugins/cache/zcode-plugins-official/mimosa/1.0.4/payload/dist/cli.js" audit . --json --no-deps
# → totals.high = 13，逐条落在 core/feedback.py 之外的既有文件上
```

门禁扫描的是**主仓目录**（报 14 条 high，含主仓工作树的既有文件），本卡工作树
自身的审计是 13 条；两者的差来自两个目录内容不同，不是本卡引入的。

`MIMOSA_NO_GIT_GATE=1` 等开关读的是 ZCode **宿主进程**的环境，命令行前缀够不到
（该钩子拦截的是 Bash 工具调用本身），因此本卡的提交是在 **ZCode 之外的终端**
里执行的。**这些是既有发现，不在本卡的写入范围内，未在本卡修复。**

## 9. 机器摘要

```json
{"lane":"F2-MC-OUTPUT","owner":"meeting-converter","base":"b43a76a3cdc25928a75e583b65a5a706802985ce","implementation":"8806ff4","reviewed_commit":"8806ff4","branch":"codex/f2-mc-output","review_ref":"docs/plans/f2-mc-output/handoff.md","tests":[{"command":"python -B -m pytest -q -o addopts= -p no:cacheprovider tests/test_output.py tests/test_pipeline.py tests/test_transcribe_integration.py tests/test_output_feedback.py","result":"127 passed, 0 failed, 0 skipped"},{"command":"python -B -m pytest -q -o addopts= -p no:cacheprovider","result":"297 passed, 0 failed, 0 skipped"},{"command":"python -B -m ruff check core/feedback.py core/pipeline.py tests/test_output_feedback.py tests/test_transcribe_integration.py","result":"All checks passed!"}],"sample_refs":["docs/plans/f2-mc-output/receipts/sample-success.jsonl","docs/plans/f2-mc-output/receipts/sample-stale.jsonl","docs/plans/f2-mc-output/receipts/sample-started-only.jsonl","docs/plans/f2-mc-output/receipts/sample-replay.jsonl","docs/plans/f2-mc-output/receipts/red-output-feedback.txt"],"cleanup":"两处 .coverage 字节未变；收据脚本的临时目录与临时 worktree 全部移除；主仓 HEAD 仍 b43a76a 且只有既有的 M .coverage 与插件状态目录 .mimosa/","remaining":["ROOT 侧跨仓组合验收：读取旁路与 .details.jsonl 两个文件并登记 issue","消费方复验 stale-output-success 卡（当前 pending）","样本 evidence_ref 由路径派生，复验时按同一规则重算","本卡无用量收据，费用恒为 cost_unknown"]}
```
