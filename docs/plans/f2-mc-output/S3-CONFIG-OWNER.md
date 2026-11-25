# S3 会议转录配置归属

本仓 owner 候选基于已核对的远端 `master@9632b5048a120901605a2b68e290dfe8677d0db1`。在 `.worktrees/s3mc` 实施。主工区已有 `.coverage` 和三份 PWF 待提交文件，F2 原作者工区保持完整。

- 实际 `transcribe.py` 与 `compare_engines.py` 都经 `translator.load_config` 读取配置字典。未指定 MiMo URL 时，正式入口与直接引擎构造的默认是 `https://api.xiaomimimo.com/v1/chat/completions`，`Config.load` 和 `CONFIG.md` 则是 token-plan 地址。样例里的 token-plan 是显式配置。
- 保持正式 CLI 已有缺省目的地、显式 token-plan 和自定义地址、模型、翻译意图与 F4 结果。把文件读取、选项缺省与校验归属交给本仓 `config.py`。既有 `translator.load_config`、`config_validator.validate_config`、字典构造调用继续兼容。CLI 缺少可选翻译器时沿原业务降级，原有显式校验入口独立。
- CLI 仍以 JSON 中显式 Whisper 配置优先，缺省再用 CLI 参数；保留显式引擎和语言、输出衔接。实际 CLI 子进程仅发本地 fake transport，测试文件、反馈和输出均在临时目录。
- 写域为 `config.py`、`config_validator.py`、`transcribe.py`、`translator.py`、`compare_engines.py`、`engines/factory.py`、`engines/mimo.py`、`README.md`、`CONFIG.md`、新自有配置回归测试和本记录。编排部署、私有配置、音频原件和外部项目由其各自 owner 维护。
- 先复现同一配置实际 CLI 和类型读取目的地不一致。合法对照为显式 token-plan、独立 DeepSeek 地址和模型，以及未启用翻译时按明确 CLI 参数执行。定向复验和清理后请未参与实现的 reviewer 检查精确候选。


## 已执行的回归

按官方 `9632b50` 先执行真实 CLI 矩阵。2 RED、3 controls PASS。一例确认省略 MiMo URL 时，CLI 发向开放平台，类型入口返回 token-plan。另一例确认加载函数实现归属为翻译客户端。显式 token-plan、自定义地址/翻译模型、Whisper 和禁止翻译均作为合法对照。

CLI 现在一次读取并产生一个类型化配置。转录工厂和翻译器直接复用同一对象，既有独立字典调用沿用本仓默认值。公开 API 和 token-plan 选择都经同一完整地址字段，示例里的 token-plan 是显式选项。公开校验入口仍由调用者主动使用。旧路径 `translator.load_config` 及 `config_validator.validate_config` 分别指向配置 owner 的同一函数。

新增六项测试覆盖实际进程的原文输出、显式翻译和禁翻译，以及坏 JSON 后保留原文并冷读 `JSONDecodeError` 原因。实际发起请求的位置由确定性替身测量，网络调用和费用均为零。完整本仓套件 365 项通过，耗时 45.90 秒，Ruff 前后对比无新增并去掉 4 项既有警告。`git diff --check` 通过。测试关闭自动覆盖率写入，保留原 `.coverage`。Windows 常规测试目录清理遇到故意建立的超过 260 字符路径，使用确认归属的扩展路径彻底恢复本次临时目录并核实不存在。

8 个 Python 变更文件按路径排序，指纹算法为 `path + NUL + LF 正文 + NUL`，SHA-256 为 `43dd202eb95231d4e6176710d431d362ff73991c05258fab46f11c1f21c9d6a9`。总控依据同指纹独立复核通过，重跑 56 项通过，核对了实际默认地址、显式配置、翻译与不可用回告。

发布方式为从同一官方基线快进 master。已有覆盖率文件与在途 PWF 的 SHA-256 在发布前后核对。当前技能的安装与运行时切换另由其 owner 管理。
