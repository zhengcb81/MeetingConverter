# F4 MeetingConverter 本仓运行端口

**当前普通入口与故障覆盖**见[转录启动、翻译意图和备用引擎](F4-MC-FAILURES.md)。这份卡以普通 CLI 的原生失败为起点，覆盖两条已经登记的 F4 发生。下文保留原运行端口与此前验收范围。

总控接原始转录发布观察。MC 自己核对同一发生的终态和已保存的 writer 详情。从已确认有旧译文的偏差重建可消费的发布清单。清单列出原操作真正提交的角色与内容指纹，同时保留旧件、缺件及原终态。转录、翻译、旧产物和费用账单由原任务继续负责。

## 2026-11-20 本机独立复验

正式 MeetingConverter 工作目录的运行脚本来自 `master@8b8e574f6162c6011890ce52b7383e796958aae1`。真实配置核对了分诊、修理、复验、回告四个执行路由及原作业对账路由。四个执行路由共用只读 `get-action`，宿主 30 秒接收单个 owner 命令结果。原作业不存在时本机实际对账回 unknown，查原动作回空对象，配置的本仓回执库未写入。

在该正式代码根执行总控 `test_feedback_f4_mc_control.py` 和 `test_feedback_f4_mc_intake.py`，两项通过。原场景只证明本次原语言文件的 writer 指纹，旧译文件登记为保留件。分别在修理与回告事务落盘后强退，两次并发恢复查回同一 action、原请求和版本。原文本字节及写入时间核对一致。恢复和重复消费阶段转录、翻译各新增 0 次，历史无收据仍保留未知。复验使用隔离样例与状态库。

## 入口

从本仓使用 `python -B feedback_owner.py --db DB --sidecar FILE COMMAND`。可重复 `--sidecar`，或为运维设置 `--sidecar-dir DIR` 读取目录下的原始 JSONL（同名 `.details.jsonl` 作详情）。ROOT 将同一原始侧车作为 `tick` 或 `recover` 的输入。每个 producer 调用使用独占的 JSONL。部署可将其放在本仓已有的 `output/.feedback/observations`，把小型回执库放进 `output/.feedback/owner.sqlite`。部署保持原生业务入口与各模块状态独立。

### 直启默认交付（2026-11-21 起）

- 主收件目录为 C:/Users/郑曾波/Projects/MeetingConverter/output/.feedback/observations。写入故障使用本仓耐久恢复目录 C:/Users/郑曾波/Projects/MeetingConverter/output/.feedback/recovery。
- ROOT 用现有 native_observation_dirs 订阅两处，owner 公开端口为每处各传一次 --sidecar-dir。RESEARCH_FEEDBACK_STATE_ROOT 可同时隔离 observations 与 recovery；RESEARCH_FEEDBACK_DIR 只改主收件路径。显式 RESEARCH_FEEDBACK_OUT 沿用单次文件契约。
- 普通 CLI 每个进程使用独立的反馈名称、run/attempt 与明细。数据和明细写入后才生成 feedback-delivery-ready/1，记录 step_ids、两份行数和真实字节 SHA-256。中断时仍可读已有行。已确认的同内容交付不会重新打开 ready。
- owner 的 reconcile 只读原作业。备用成功保持 succeeded 与 published_degraded，并保留原异常链。缺原用量凭证时保持 cost_unknown。恢复不调用转录或翻译。

| 命令 | 输入和结果 |
|---|---|
| `triage` | stdin 的原发生动作。定位到支持的偏差与实际写入证据时返回修复引用。合法结果为 expected，其他完整但证据不足的问题保留 needs_evidence。 |
| `repair` | 查原分诊，持久化 `mc-publication/1` 清单，按内容 SHA 返回 fixed_version。 |
| `get-publication ACTION_ID` | 只读取对应修复动作的已发布清单，核对它与原版本摘要一致。 |
| `replay` | 以 reuse_only 和原发现实际读取修复产物，绑定来源与版本再给 verified、regressed 或 unknown。 |
| `report` | 核对原 replay 收据，以事务写入原发现、复验版本及可判定结果。 |
| `get-action ACTION_ID` | 只读原动作完整提交和完成结果。供真实宿主中断恢复，重复调用不新增回执。 |
| `reconcile` | 只读同 run、attempt、step、版本和证据引用的终态。未完成或无法确认的作业保持 unconfirmed，费用没有原生收据时一直是 unknown。 |

ROOT 的四个执行路由可将同一命令前缀的 `get-action` 用作 `lookup_argv`，持久收据与完整原请求一致时恢复原 action。选用完整或继续追加的原始侧车。显式开始已经出现但同尝试的终态还没写到时，ROOT 暂时查证，不提前分诊同一步骤的偏差。

## 验收边界

当前观察版本 meeting-converter-feedback/1.1.0，源码 0e3c4a396ef9f571989cc4543d23b34a840564bd。见[独立验收与交接](handoff.md)。以下说明适用于保留的历史 writer 收据。

`meeting-converter-feedback/1.0.3` 由原子写入者提供实际提交字节的 SHA 和大小。历史路径补读证据可用于诊断和追查，补建可消费清单需有本次 writer 指纹。相同目标之后被另一轮覆盖时，本轮提交指纹仍准确，消费方可用它判断现文件与发布版本是否相符。

当前自动修复范围是已有完整 writer 证据的旧译文发布归属。其他根因沿用本仓的[修复技能](../../../skills/repair-meeting-converter-issue/SKILL.md)。已有文件与中断导致的不确定用量不进入再次转录或翻译。本端点只使用标准库、已有诊断和小型收据。

本仓回归使用 `python -B -m pytest -o addopts= -q tests/test_feedback_owner.py tests/test_output_feedback.py`。总控的 `test_feedback_f4_mc_control.py` 在实际修复落盘和回告落盘后强制终止宿主，随后两次并发恢复，保留同一 action ID。生产工作区使用相同发布脚本，合成输入和故障只存在于隔离验收环境。
