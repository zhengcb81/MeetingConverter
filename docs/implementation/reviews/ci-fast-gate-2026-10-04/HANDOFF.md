# HANDOFF — MeetingConverter CI 快速可靠门

Status: DONE
Card: `docs/plans/narrative-evidence-pilot-2026-09-26/harness_lanes/meetingconverter_ci_fast_gate.md`
Card date: 2026-10-04
Repository: `C:/Users/郑曾波/Projects/MeetingConverter`
Worktree: `C:/Users/郑曾波/Projects/MeetingConverter-ci-fast-gate`（独立干净 worktree）
Branch: `ci/fast-gate`（未合并 master/main）

## 1. SHA

| 项 | SHA |
|---|---|
| base（开工基准 = origin/master） | `3c0b0531637589b3c4b14b83da8e1b3c3e1adf9b` |
| head（本卡代码交付） | `f1272fdc63df8ed885e1da4bd22d087a6c288ce8` |
| origin/master（交付后复核） | `3c0b0531637589b3c4b14b83da8e1b3c3e1adf9b`（未改动） |
| 本地 master branch / HEAD | `master` / `3c0b053…`（未改动） |

分支提交：

- `d0fb843` fix: 修复 CI workflow 表达式错误导致 jobs=0，改为单版本快速测试门
- `f1272fd` ci: push 触发扩展到全部分支，确保每次 push 都实际跑测试

## 2. 根因：jobs=0、测试未运行（重新核对，问题仍存在）

已验收只读收据只覆盖 HEAD `3c0b053`。开工重新查询远端，结论：**该问题在最新状态下仍然存在，未被修复**（`3c0b053` 之后 master 无新提交）。

根因 run：https://github.com/zhengcb81/MeetingConverter/actions/runs/29117635443

| 证据项 | 取值 |
|---|---|
| event / head_sha / branch | `push` / `3c0b0531…` / `master` |
| created_at / updated_at / run_started_at | 2026-07-10T19:20:00Z（三者同秒，run 生命周期 0 秒） |
| status / conclusion | `completed` / `failure` |
| `GET …/runs/29117635443/jobs` | `total_count = 0`（`filter=all` 同样为 0） |
| `GET …/commits/3c0b053/check-runs` | `total_count = 0` |
| `GET …/commits/3c0b053/check-suites` | 1 个 suite `78789483974`，conclusion=`failure` |
| run logs 端点 | 404（没有 job ⇒ 没有任何日志，测试无从执行） |

根因原文（run 页面 annotation）：

```
Invalid workflow file: .github/workflows/ci.yml#L1
(Line: 39, Col: 13): Unexpected symbol: '"3'.
Located at position 26 within expression: matrix.python-version == "3.13"
```

- 旧行 39 = `if: matrix.python-version == "3.13"`（`Upload coverage` 步骤）。
- GitHub 在**创建 job 之前**就拒绝了整个 workflow，因此 `jobs=0`，`Run tests` 步骤根本不存在。
- 这不是触发条件、也不是 path filter；workflow 的 push/pull_request 触发器本身是有效的（`on: push.branches: [master, main]` 能命中 master）。
- 结论：**“YAML 能被 PyYAML 解析”不等于 CI 通过**。本地 `yaml.safe_load()` 对原文件返回合法 dict，但 GitHub 表达式校验在 L39 失败。

### 次级阻断（即使修好 L39，原 workflow 依然会红）

开工核查中实测，两条均为复现证据：

1. `ruff check .` → **60 errors, exit 1**：`F401×33`、`I001×18`、`F841×5`、`E402×1`、`E731×1`、`F541×1`、`F821×1`。其中 `F821 = engines/mimo.py:137 Undefined name logger`（真实潜在缺陷）。
2. `pytest tests/ --cov=.` → 194 passed，但 `pyproject.toml` 的 `fail_under = 80` 未达标（全仓 69.58%）→ **exit 1**。原 CI 的 `--cov=.` 把 pytest.ini 只测 engines/translator/company 的 88% 覆盖摊成全仓 70%，从而必然红灯。

## 3. 改动路径（全部在允许写集内）

- `.github/workflows/ci.yml`
- `tests/test_ci_workflow_config.py`（新增，独立 CI 配置合同测试）
- `docs/implementation/reviews/ci-fast-gate-2026-10-04/HANDOFF.md`（本文）

未改动：应用 src、业务测试、`pytest.ini`、`pyproject.toml`、`requirements.txt`、依赖锁文件、配置密钥、PWF 其他阶段、任何公司/音频/转录资料。company-wiki、StockQAbyLLM、invest-quick-scan 未读取、未操作。

### ci.yml 变更明细

| 项 | 旧 | 新 | 理由 |
|---|---|---|---|
| push 触发 | `branches: [master, main]` | `branches: ["**"]` | 原配置下分支 push 完全不触发；卡片要求“每次代码 push”都跑 |
| pull_request 触发 | `branches: [master, main]` | 不变 | 仓库当前支持，保留 |
| Python 版本 | matrix `3.8/3.10/3.13`（3 job） | 单一 `3.13` | 卡片“单 Python 版本优先”；同时消除 L39 的 matrix 表达式 |
| 安装 | 升级 pip + 装 requirements + 装 ruff | `python -m pip install -r requirements.txt` | 去掉无收益耗时；不再需要 ruff |
| Lint | `ruff check .`（红） | 移除 | 60 个既有违规无法在“禁止改 src”约束下变绿；见未解决事项 1 |
| 测试 | `pytest tests/ --cov=. --cov-report=xml --cov-report=term-missing` | `python -m pytest tests/` | 去掉全仓 coverage 门；选择器与本地验证一致 |
| 上传 | `codecov/codecov-action@v4` + `if: matrix…` | 移除 | 去掉易抖动/慢速上传，也去掉唯一一处裸 `if` 表达式 |
| 防挂死 | 无（默认 360 分钟） | `timeout-minutes: 5` | 保证 120s 预算不会退化成挂死 |

无 `always()`、无 `continue-on-error`、测试步骤无 `if`，任何脚本非零退出都会让 job 失败。

### 新增合同测试（仓库已有工具：PyYAML 6.0.3）

`tests/test_ci_workflow_config.py`，10 个用例，静态校验 workflow：YAML 可解析、push 覆盖所有分支且 pull_request 指向主干、单 job 无 matrix、Python 版本钉死 3.13、pytest 步骤带显式选择器且不含 `--cov=.` 且不可被跳过、无 `continue-on-error`/`always()` 掩盖、`if` 表达式禁用双引号字面量、只允许 checkout/setup-python 两个 action、job 超时 ≤5 分钟。

## 4. 确实执行的测试与耗时

### 本机（worktree，Python 3.13.9 = CI 同版本，选择器 `tests/` = CI 同选择器）

全量：`python -m pytest tests/` → **204 passed, exit 0**；pytest 自报 4.39s，含解释器启动与 coverage 的墙钟 8.894s。覆盖率 88.04% ≥ `fail_under=80`。`ruff check tests/test_ci_workflow_config.py` → All checks passed。

分测试文件时长（单文件单跑）：

| 文件 | 结果 | 时长 |
|---|---|---|
| tests/test_audio_utils.py | 15 passed | 0.41s |
| tests/test_batch.py | 10 passed | 0.30s |
| tests/test_ci_workflow_config.py | 10 passed | 0.33s |
| tests/test_company.py | 12 passed | 0.71s |
| tests/test_company_manager.py | 13 passed | 1.31s |
| tests/test_config.py | 13 passed | 0.62s |
| tests/test_config_validator.py | 8 passed | 0.79s |
| tests/test_corrections.py | 17 passed | 1.03s |
| tests/test_engine_factory.py | 12 passed | 0.30s |
| tests/test_fallback.py | 4 passed | 0.90s |
| tests/test_mimo_engine.py | 14 passed | 1.08s |
| tests/test_output.py | 6 passed | 1.05s |
| tests/test_pipeline.py | 19 passed | 1.25s |
| tests/test_text_merger.py | 14 passed | 0.26s |
| tests/test_transcribe_integration.py | 9 passed | 0.69s |
| tests/test_translator.py | 17 passed | 0.78s |
| tests/test_whisper_engine.py | 11 passed | 0.93s |

对照基线：原选择器 `pytest tests/ --cov=.` 在同一 worktree 为 194 passed 但 **exit 1**（覆盖门 69.58% < 80）。

### CI 端（新 push run，确认测试真的跑了）

Run：https://github.com/zhengcb81/MeetingConverter/actions/runs/37240423879
job/step：https://github.com/zhengcb81/MeetingConverter/actions/runs/37240423879/job/111547864013

- `jobs total_count = 1`，job `test` conclusion=`success`，job 18s（22:32:48Z → 22:33:06Z）。
- 步骤全部 success：`Set up job` → `Run actions/checkout@v4` → `Set up Python 3.13` → `Install dependencies` → `Run tests` → post 步骤。
- job 日志原文：`collected 204 items` … `204 passed in 1.21s`。
- step 时长（由 job 日志时间戳推算）：checkout ≈0.5s，setup-python ≈0.2s（工具缓存命中），**Install dependencies ≈12.3s（本 job 唯一瓶颈，占 68%）**，Run tests ≈2.1s。
- 安装实测解析出 `faster-whisper-1.2.1 / huggingface-hub-1.33.0 / pytest-9.1.1 / pytest-cov-7.1.0 / pytest-mock-3.16.0 / PyYAML-6.0.3`，与本机版本一致。

### 最新 run

| run | event | 结果 | 总时长 |
|---|---|---|---|
| https://github.com/zhengcb81/MeetingConverter/actions/runs/37240423879 | push @ `f1272fd` | **success**，jobs=1 | **21s** |
| https://github.com/zhengcb81/MeetingConverter/actions/runs/37240511159 | pull_request #1 | **success**，jobs=1 | **21s** |

两个事件均确认“至少一个 job 实际运行且执行了测试”。21s ≤ 180s 上限，且远低于 120s 目标，无需为时长砍测试。head commit `f1272fd` 的 check-runs：2 条 `test`，全部 success。

PR：https://github.com/zhengcb81/MeetingConverter/pull/1（open，**未合并**；仅用于验证 pull_request 触发）。

## 5. 保护文件状态确认（交付后复核）

主 checkout `C:/Users/郑曾波/Projects/MeetingConverter`：

- tracked `.coverage`：**53,248 B**，mtime `2026-07-09 21:59:58` — 未清理、未还原、未重命名、未重新生成、未暂存（`git diff --cached` 为空）。
- `config.json`：597 B，mtime `2026-07-09 19:33:57` — 未动。
- `output/`：内容 mtime 均为 2026-07-09 — 未动。
- 全部既有 ignored/untracked（`.pytest_cache/`、`__pycache__/`、`.ruff_cache/0.12.5/`、`config.json`、`output/` 等）保持原样，未清理/还原/暂存。
- `git status --porcelain=v1 --ignored=matching`：与开工记录一致，仅 `.coverage` 为 ` M`（开工前已如此）、ignored 项原样。
- branch = `master`，HEAD = origin/master = `3c0b053`，本次作业未在 master 上产生任何提交。
- 测试全程只在独立 worktree 内运行，主 checkout 未执行 pytest/ruff。

披露一项工具副作用：编辑器 LSP 在主 checkout 生成了**空目录** `.ruff_cache/0.15.18/`（gitignored，无缓存条目，未暂存）。按“不得清理 ignored 内容”未删除，仅在此披露；它不在审计收据的既有清单内，也未触碰任何受保护文件。

## 6. 未解决事项

1. **CI 的 lint 门被移除**：`ruff check .` 在 `3c0b053` 上有 60 个既有违规（含 `engines/mimo.py:137` 的 `F821 Undefined name logger`）。在“禁止修改应用 src/业务测试”的约束下无法变绿，按“最终状态须 success”只能移除。建议开独立卡片修复后恢复 lint 步骤。本地已验证新增的合同测试文件自身 `ruff check` 通过。
2. **codecov 上传已移除且无替代**：coverage 仍在本地/CI 以 pytest.ini 的 `--cov=engines --cov=translator --cov=company` + `fail_under=80` 形式生效（88.04%），但不再上传，也没有全仓 coverage 报告。
3. **push 与 pull_request 双触发**：对同一 PR 分支的同一次 push 会产生 2 条 run（各 21s）。保留双触发是为同时满足“每次 push 都跑”与“PR 也跑”两条要求。
4. **PR #1 保持 open，未合并 master**（按卡片“不合并到 main”）。是否合并/关闭由上层决定。
5. **真实缺陷待修**：`engines/mimo.py:137` 引用了未定义的 `logger`，现有测试未覆盖该路径。
6. 主 checkout 新增空目录 `.ruff_cache/0.15.18/`（见第 5 节披露）。

本卡无外部公司数据、模型、API 或成本依赖；未读取或操作 invest-quick-scan。
