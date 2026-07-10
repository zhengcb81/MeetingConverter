# MeetingConverter - 投资者会议音频转文字引擎 v2

基于 MiMo-V2.5-ASR / faster-whisper + DeepSeek LLM，支持段落合并、翻译、公司背景知识注入和三文件输出。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      transcribe.py (CLI)                     │
│                         ↓ 调用                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                  core/ (核心业务逻辑)                     │ │
│  │  pipeline.py    batch.py    output.py    formatter.py   │ │
│  │  单文件转写      批量调度     文件输出      时间格式化     │ │
│  └─────────────────────────────────────────────────────────┘ │
│         ↓                ↓                ↓                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                │
│  │ engines/ │    │translator│    │ company  │                │
│  │ 转写引擎 │    │ DeepSeek │    │ 公司知识 │                │
│  └──────────┘    └──────────┘    └──────────┘                │
│       ↓                                                ↓     │
│  ┌──────────┐                                  ┌──────────┐  │
│  │  MiMo    │  ← API 调用 →                    │companies │  │
│  │ Whisper  │  ← 本地模型 →                    │  .yaml   │  │
│  └──────────┘                                  └──────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**数据流**：音频文件 → 引擎转写 → 段落合并 → LLM 翻译 → 三文件输出

**模块职责**：
| 模块 | 职责 |
|------|------|
| `transcribe.py` | CLI 入口，参数解析 |
| `core/pipeline.py` | 单文件转写主流程 |
| `core/batch.py` | 批量调度与进度统计 |
| `core/output.py` | 文件输出（原文/翻译/对照） |
| `engines/` | 转写引擎抽象（MiMo/Whisper） |
| `translator.py` | DeepSeek LLM 翻译 |
| `company.py` | 公司背景知识管理 |
| `exceptions.py` | 统一异常层级 |
| `metrics.py` | 性能监控 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 API 密钥
cp config.example.json config.json
# 编辑 config.json，填入 mimo_api_key 和 deepseek_api_key

# 转写单个文件（自动选择引擎）
python transcribe.py meeting.mp3

# 批量转写目录
python transcribe.py input/

# 指定语言(更快更准)
python transcribe.py meeting.mp3 -l zh    # 中文
python transcribe.py meeting.mp3 -l en    # 英文

# 仅转写，不翻译
python transcribe.py meeting.mp3 --no-translate

# 强制使用 Whisper
python transcribe.py meeting.mp3 --engine whisper

# 强制使用 MiMo
python transcribe.py meeting.mp3 --engine mimo

# 详细日志
python transcribe.py meeting.mp3 -v

# 强制重新处理已完成的文件
python transcribe.py meeting.mp3 --force
```

## 引擎选择

| 引擎 | 说明 | 支持格式 | 适用场景 |
|------|------|----------|----------|
| **MiMo-V2.5-ASR** | 小米 MiMo ASR API | WAV, MP3 | 默认引擎，高质量转写 |
| **faster-whisper** | 本地 Whisper 模型 | 所有格式 | 离线使用，隐私保护 |

引擎选择逻辑（`--engine auto`）：
1. 配置了 `mimo_api_key` → 使用 MiMo
2. 未配置或音频格式不支持 → 回退到 Whisper
3. MiMo 调用失败 → 自动回退到 Whisper

## 输出

三个文件（默认输出到 `output/` 目录）：

| 文件 | 说明 |
|------|------|
| `{name}_原文.txt` | 原始转写文本（按段落） |
| `{name}_翻译.txt` | 中文翻译 |
| `{name}_中英对照.txt` | 一段原文 + 一段翻译 |

使用 `--no-translate` 时仅输出 `{name}_原文.txt`。

## 公司背景知识

自动从文件名识别公司名，加载背景知识用于翻译上下文和纠正规则。

```bash
# 查看所有公司
python company_manager.py list

# 查看公司详情
python company_manager.py show 小米集团

# 添加公司
python company_manager.py add 小米集团 --en "Xiaomi Corporation" --ticker 1810.HK --sector "消费电子/智能汽车/AI"

# 添加纠正规则（Whisper 误识别修正）
python company_manager.py correct 小米集团 --from U7 --to YU7

# 批量导入纠正规则
python company_manager.py import-corr 小米集团 --file corrections.txt
```

公司数据存储在 `companies.yaml`，支持：
- 中英文名、别名匹配
- 纠正规则（Whisper 误识别修正）
- 公司背景知识注入翻译上下文

### company-wiki 集成

可选：在 `~/company-wiki/graph.yaml` 添加公司补充信息，会自动加载到翻译上下文。

```yaml
# ~/company-wiki/graph.yaml 示例
companies:
  小米集团:
    position: "全球领先的智能硬件和IoT平台"
    sectors: ["消费电子", "智能汽车", "AI"]
    aliases: ["小米", "Xiaomi"]
```

## 配置

`config.json` 配置项：

| 键 | 说明 | 默认值 |
|----|------|--------|
| `mimo_api_key` | MiMo ASR API 密钥 | (必填，MiMo 引擎) |
| `mimo_base_url` | MiMo API 地址 | `https://api.xiaomimimo.com` |
| `transcription_engine` | 引擎选择 | `auto` |
| `deepseek_api_key` | DeepSeek 翻译 API 密钥 | (必填，翻译功能) |
| `deepseek_base_url` | DeepSeek API 地址 | `https://api.deepseek.com` |
| `deepseek_model` | 翻译模型 | `deepseek-v4-flash` |
| `whisper_model` | Whisper 模型 | `small` |
| `whisper_device` | 运算设备 | `cpu` |
| `whisper_compute_type` | 计算精度 | `int8` |
| `language` | 语言 | (自动检测) |
| `paragraph_merge_gap_sec` | 段落合并间隔(秒) | `2.0` |
| `paragraph_max_chars` | 段落最大字符数 | `2000` |
| `translate_max_retries` | 翻译重试次数 | `3` |
| `translate_api_timeout` | API 超时(秒) | `120` |
| `translate_paragraph_delay` | 段落间延迟(秒) | `0.3` |
| `corrections` | 全局纠正规则 | `{}` |

## 模型选择（Whisper）

| 模型 | 参数量 | 内存 | 速度(CPU) | 中文质量 | 推荐场景 |
|------|--------|------|-----------|----------|----------|
| tiny | 39M | ~1GB | 最快 | 一般 | 快速预览 |
| base | 74M | ~1GB | 快 | 良好 | 日常使用 |
| small | 244M | ~2GB | 中等 | 较好 | 默认 |
| medium | 769M | ~5GB | 较慢 | 很好 | 高质量需求 |
| large-v3 | 1550M | ~6GB | 最慢 | 最佳 | 最高精度 |
| turbo | 809M | ~3GB | 较快 | 很好 | 速度与质量平衡 |

## 依赖

- Python 3.8+
- faster-whisper（Whisper 引擎）
- PyYAML（公司知识库）
- ffmpeg（音频处理）

```bash
pip install -r requirements.txt
```

## 测试

```bash
# 运行测试
pytest tests/

# 运行测试并生成覆盖率报告
pytest tests/ --cov=. --cov-report=term-missing

# 详细输出
pytest tests/ -v
```

## 项目结构

```
MeetingConverter/
├── transcribe.py          # CLI 入口
├── config.py              # 配置数据类
├── config_validator.py    # 配置验证
├── exceptions.py          # 统一异常层级
├── metrics.py             # 性能监控
├── translator.py          # DeepSeek LLM 翻译
├── company.py             # 公司背景知识
├── company_manager.py     # 公司知识库管理
├── audio_utils.py         # 音频处理工具
├── text_merger.py         # 文本段落合并（无时间戳场景）
├── core/                  # 核心业务逻辑
│   ├── __init__.py
│   ├── pipeline.py        # 单文件转写主流程
│   ├── batch.py           # 批量调度
│   ├── output.py          # 文件输出
│   └── formatter.py       # 时间格式化
├── engines/               # 引擎抽象层
│   ├── base.py            # TranscriptionEngine 协议
│   ├── whisper.py         # Whisper 引擎
│   ├── mimo.py            # MiMo ASR 引擎
│   ├── fallback.py        # 回退引擎
│   └── factory.py         # 引擎工厂
├── tests/                 # 测试目录（194 个测试）
├── companies.yaml         # 公司知识库
├── config.json            # 配置文件（不入 git）
├── config.example.json    # 配置示例
└── requirements.txt       # 依赖列表
```

## 许可证

MIT
