# F4-MC-FAILURES 转录启动、翻译意图和引擎回退反馈

本仓源码与独立验收完成，冻结源码 0e3c4a396ef9f571989cc4543d23b34a840564bd，见[最终交接](handoff.md)。两处收件路径由 ROOT 统一接线。工作目录为 `C:/Users/郑曾波/Projects/MeetingConverter`，发布线 `master`，审计基线 `e7b6c021c532c55a15a271c4bf690891b8f9cb93`，生产运行代码 `8b8e574f` 的相关路径一致。本仓已提供[转录归属和原动作查询](runtime.md)。现有 `.coverage` 修改和未跟踪 `.mimosa/` 不属于本卡。

## 工作约定

先在下述唯一工作目录执行 `git status --short --branch`、`git worktree list`、`git diff --name-only HEAD --` 和 `git log -4 --oneline`，记录起点。以下源码位置是审计时的定位，按当前方法和行为接续。若现有 harness 已改同一路径，将本卡排在该线后，先读取其差异和验收再接续。三个 owner 各有自己的目录、状态库、测试和提交。保留并行作者的暂存区、配置和产物。遇到确实需要改公共 wire 或其他模块的事项，把最小输入与期望交 ROOT，继续本仓可完成的部分。

隔离测试在真实 Python 子进程中调用普通入口。配置、用户数据根、工作目录、日志、数据库、暂存与输出全部映射到同一测试专用临时根；使用进程自己的环境，清除继承的 `RESEARCH_FEEDBACK_OUT`、运行号、尝试号再测默认路径，并单测过去显式设置的调用。替身仅放在本仓的磁盘故障注入点或真正外部传输、计费、引擎边界。保留原生 CLI、父子进程、结算、查询及文件操作。收尾核对临时目录恢复到原样。

## 原发生与写入范围

发现方 company-wiki，运行号 `f4-coverage-audit-20261121`。中央证据 `company-wiki/docs/plans/feedback-loop-2026-11-17/issues/failure-coverage-20261121.jsonl` 和同级 `probes/mc.py` 可读。本仓独立复现，审计基线共 10 个场景。

| 原发生位置和编号 | 原生结果与根因 |
|---|---|
| 第 23 行，`baseline-e7b6c021 / initialization / failure-coverage`，`native-failure-not-forwarded` | 无输入、坏 CLI、输出目录错误、主引擎初始化失败四案无 F4。`transcribe.py:83` 解析早于运行身份，初始化的错误到不了 writer 反馈。 |
| 第 24 行，`baseline-e7b6c021 / fallback / failure-coverage`，`degraded-work-hidden` | 明确请求翻译但翻译器未能创建、主引擎失败后备用成功均显示发布成功。provider 故障只留下 RuntimeError，底层 TimeoutError 仅见于控制台。`core/pipeline.py:129` 从对象是否存在倒推意图，`core/feedback.py:597` 的发表结论不能代表所有处理阶段都成功。原强停案例能保留同一尝试和未知用量。 |

只写本仓 `transcribe.py`、`core/pipeline.py`、`core/feedback.py`、`engines/fallback.py`、`feedback_owner.py` 与为这些边界必需的本仓测试、计划。音频引擎的远端配置与原始音频、所有其他业务仓、宿主配置不属于本包。保留已有 writer 指纹、发布清单和历史付费对账。

## A 建立可复现的 RED

第一道 RED 用普通 `transcribe.py INPUT -o OUT`、测试引擎和临时 WAV，保持默认请求翻译，让翻译器初始化失败。在关闭可选 OUT 的情况下运行，另启一个进程读本次尝试，断言**原文真实产出、已请求翻译、翻译未运行及其原因**能够同时读回。原版只报告发布 current 或根本没有默认观察。第二道 RED 用主引擎 `RuntimeError` 由 `TimeoutError` 引起，备用引擎成功；再造同样外层但底因不同。比较首次调用、最终产物和冷读下的脱敏原因链。记录原版本与失败断言。

| 临时普通入口 | 实测检查点 |
|---|---|
| 输入缺失、传未知参数、把已有文件用作输出目录、所选引擎无法创建 | 区分请求拒绝、初始化和本地 I/O 失败；确知未调用时显示未发送。 |
| 无译器仍请求翻译；主动 `--no-translate`；主引擎失败而备用成功 | 三种结果分别显示请求和实际执行角色/引擎。降级时仍可交原文，主动关翻译是预期选择。 |
| 模型失败、writer 发布失败、已有原文正常复用、替身进入转录后强制结束子进程 | 失败记录到原步骤。核对 writer 对当前文件实际提交的 SHA，旧译文继续标保留。强停保持原 attempt 和未知用量；成功复用不触发远程服务。 |

## B 从原操作还原事实

在 `transcribe.py` 初始边界保存请求意图。解析未完成时仅记录能确定的身份和阶段；运行期分别记录引擎选择、开始、真实用到的引擎、翻译情况和产物角色。`engines/fallback.py` 保留主失败的稳定原因与是否启用备用；`core/pipeline.py` 不从对象缺席推导用户主动关闭翻译。沿用 `core/feedback.py` 原子 writer 证据，写出成功和业务降级可同时成立；真实 provider 异常带脱敏的因果链，至少能分辨 TimeoutError 与另一个内因。尽量复用现有反馈上下文传值，不另加权限/人工签收。

专用临时测试根中模拟日志暂时不可写，业务仍按真实产物结算；恢复时从原动作只读补投。再在替身引擎已启动、终态已写但回告未收到两处杀进程，发起两次并发 `reconcile` 或同一动作的 `get-action`。记录转录与翻译计数前后差值均为零。没拿到原收费凭证继续 unknown；不得借备用引擎、预算或重跑确认费用。既有旧译文恢复动作不能覆写原件。

新增 `tests/test_f4_ordinary_failures.py`，在临时目录通过普通命令跑阶段矩阵，让实际子进程写收据，另一个普通进程读回。以仓内已有依赖执行，测试音频和引擎替身禁止访问服务或读取真实 API 密钥。

```powershell
python -B -m pytest -o addopts= -q tests/test_f4_ordinary_failures.py
python -B -m pytest -o addopts= -q tests/test_feedback_owner.py tests/test_output_feedback.py tests/test_pipeline.py tests/test_transcribe_integration.py
```

## 持久化和公开交接

沿用本仓既有日志、动作回执及 `feedback-observation/1`。普通启动在参数解析和副作用前建立本次身份，父调用传入的 ID 原样关联，缺省时生成可跨进程查回的 ID，两个并发任务隔离。利用原生业务终态或本仓已有持久目录保留待投递记录；先保存再确认，导出失败不覆盖业务原返回。新进程依据同一 owner/run/attempt/step 或 action 只读对账、补投。断在落盘与确认之间、重复消费或并发恢复均只登记一次原发生。所有可写介质均不可用时，外层已有启动收据才能标出未确认区间，明确哪些原因已经不可恢复。成功的兄弟任务不能覆盖失败或未知的那个尝试。

交给 ROOT 的公开观察沿用 `owner`、`origin_owner`、`run_id`、`attempt_id`、`step_id`、`check_id`、`version`、`expected`、`actual`、`disposition`、`issue_key`（如适用）、`evidence_ref`、`details_ref` 及已有拒绝码。原生明细补足未执行/已尝试/未知、退出码、阶段/输入引用、业务结果、脱敏异常类型链及本仓相对代码位置、使用量和其依据。未知费用保留未知，确知未发送才可报零。发现拒绝先按业务目的审视，识别正常请求被误拒时在本仓 PWF 记根因和减门方案；正常拒绝如实留痕，不必启动修复。向外只给既有可解析引用；不复制原始 argv、原文、密钥、完整 URL 查询或未脱敏 stderr。

### 直启发布接口

显式 `RESEARCH_FEEDBACK_OUT` 沿用单次文件及其既有明细格式。未传 OUT 时写 owner 自有的持久状态根下 `observations`，`RESEARCH_FEEDBACK_DIR` 可指定隔离的公开收件目录；两个变量都有值时 OUT 优先。使用同目录临时文件、关闭写入，原子发布 `feedback-<32位小写UUID hex>.jsonl`，对应的脱敏明细就绪后，再原子写同 basename 的 `.ready`。该 JSON 标记写 `owner`、`run_id`、`attempt_id`、`step_id` 并绑定同一份原发生，不放路径或命令。ROOT 从公开收件目录消费并负责确认标记；owner 保留原生证据，用记录过的交付身份补发。覆盖数据已落而 ready 未发、已发但回告丢失、并发消费三个窗口。确认失败只影响交付状态；业务返回、原请求和计量保持原样。用三组隔离运行覆盖显式 OUT、仅 DIR，以及两者均未设置而将本机状态根映射至临时目录。交接写本机正式默认收件目录的**绝对路径**、相对状态根的计算方法以及示例文件名，供 ROOT 在 `native_observation_dirs` 配置。若已有实现符合这些语义直接复用。

## 大节点 C 与交付

用新进程逐项对照入口受理清单、原生终态和 F4，列出每次运行及尝试的实测结果。分母用本次实际注入的入口事件，另外标明已覆盖、原因仍未知、待投递和未在现场实测的路径。冷读两种同外层异常但不同内因，核对是否可分别复现。有效拒绝、降级成功、失败、强退未知及正常成功都要有对照。针对拒绝先看门禁是否必要及能否简化，再决定修复。

实现和集中测试完成后，调用**独立审查 agent**，给它实际候选提交、两条原始发生及隔离复现命令，要求检查本卡全部覆盖、真实入口、错误/费用语义、故障恢复、数据脱敏及并发幂等。发现的可修问题全部修完，审查 agent 在最终源码版本复核，完成后才交接。把卡号、工作目录、基线和最终源码 SHA、分支/远端、改动路径、对应原发生、RED 前后实测、独审发现与修复版本、回归/冷恢复命令与退出码、调用数和清理结果写入本目录的交接 Markdown。提供可直接冷读的一份脱敏观察和同一尝试的明细示例或生成命令。发布本仓修复和交接，ROOT 通过公开接口做跨仓组合。
