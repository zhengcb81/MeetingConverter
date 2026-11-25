# 配置参考

## 配置文件位置

配置文件 `config.json` 应放在项目根目录。

```bash
cp config.example.json config.json
```

转写 CLI 中，显式引擎、语言、模型、设备与计算精度参数覆盖配置文件。其余字段沿用文件值，再使用默认值。显式 `--engine auto` 仍按配置的可用引擎选择。

## 完整配置示例

```json
{
    "deepseek_api_key": "sk-xxx",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-flash",
    "mimo_api_key": "tp-xxx",
    "mimo_base_url": "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
    "transcription_engine": "auto",
    "whisper_model": "small",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "language": null,
    "paragraph_merge_gap_sec": 2.0,
    "paragraph_max_chars": 2000,
    "translate_batch_size": 5,
    "translate_max_retries": 3,
    "translate_api_timeout": 120,
    "translate_paragraph_delay": 0.3
}
```

## 配置项详解

### DeepSeek 翻译配置

| 键 | 类型 | 必填 | 默认值 | 说明 |
|----|------|------|--------|------|
| `deepseek_api_key` | string | 是 | - | DeepSeek API 密钥 |
| `deepseek_base_url` | string | 否 | `https://api.deepseek.com` | API 地址 |
| `deepseek_model` | string | 否 | `deepseek-v4-flash` | 翻译模型 |

### MiMo ASR 配置

| 键 | 类型 | 必填 | 默认值 | 说明 |
|----|------|------|--------|------|
| `mimo_api_key` | string | MiMo引擎必填 | - | MiMo ASR API 密钥 |
| `mimo_base_url` | string | 否 | `https://api.xiaomimimo.com/v1/chat/completions` | 完整请求地址，显式值优先 |

上方样例显式选择了 token-plan 地址。省略此字段时使用表中的开放平台地址。

### Whisper 配置

| 键 | 类型 | 必填 | 默认值 | 说明 |
|----|------|------|--------|------|
| `whisper_model` | string | 否 | `small` | 模型大小：tiny/base/small/medium/large-v3/turbo |
| `whisper_device` | string | 否 | `cpu` | 运算设备：cpu/cuda/auto |
| `whisper_compute_type` | string | 否 | `int8` | 计算精度：int8/float16/float32 |

### 转写配置

| 键 | 类型 | 必填 | 默认值 | 说明 |
|----|------|------|--------|------|
| `transcription_engine` | string | 否 | `auto` | 引擎选择：auto/mimo/whisper |
| `language` | string | 否 | `null` | 语言代码：zh/en/null(自动检测) |
| `paragraph_merge_gap_sec` | float | 否 | `2.0` | 段落合并间隔（秒），>此值则分段 |
| `paragraph_max_chars` | int | 否 | `2000` | 段落最大字符数 |

### 翻译配置

| 键 | 类型 | 必填 | 默认值 | 说明 |
|----|------|------|--------|------|
| `translate_batch_size` | int | 否 | `5` | 批量翻译大小 |
| `translate_max_retries` | int | 否 | `3` | 正整数为总尝试次数，`0` 表示只尝试一次 |
| `translate_api_timeout` | int | 否 | `120` | API 超时（秒） |
| `translate_paragraph_delay` | float | 否 | `0.3` | 段落间延迟（秒） |

## 配置验证

整份配置由 `Config.load()` 校验。CLI 在实际入口校验转写公共字段，并在创建对应提供方时校验该提供方的配置。仅转写时可保留未启用的翻译配置。

- `deepseek_api_key` 不能为 `YOUR_API_KEY_HERE`
- URL 必须以 `http://` 或 `https://` 开头
- `paragraph_merge_gap_sec` 必须 >= 0
- `paragraph_max_chars` 必须 >= 100
- `translate_batch_size` 必须 >= 1
- 数值字段拒绝布尔值，翻译超时为正整数，段落间延迟为有限非负数

验证失败会抛出 `ConfigError` 异常。

## 使用配置类

代码中推荐使用 `Config` 数据类：

```python
from config import Config

# 加载并验证
cfg = Config.load()

# 类型安全访问
print(cfg.deepseek_api_key)
print(cfg.whisper_model)

# 从字典构造
cfg = Config.from_dict({"deepseek_api_key": "sk-xxx"})
```

## 环境变量

当前不支持环境变量配置，所有配置必须通过 `config.json` 文件。

## 多环境配置

可通过命令行参数指定配置文件：

```bash
python transcribe.py input.mp3 --config /path/to/config.json
```

（注：此功能需在 transcribe.py 中添加 --config 参数）
