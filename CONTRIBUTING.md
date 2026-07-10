# 贡献指南

## 如何添加新引擎

### 1. 创建引擎文件

在 `engines/` 目录创建新文件，如 `engines/new_engine.py`：

```python
"""engines/new_engine.py - 新转写引擎。"""

from __future__ import annotations

from typing import Optional

from engines.base import Segment, TranscriptionResult, TranscriptionEngine


class NewEngine:
    """新转写引擎实现。"""

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """转写音频文件。

        Args:
            audio_path: 音频文件路径
            language: 语言代码（None 表示自动检测）
            initial_prompt: 转写提示词

        Returns:
            TranscriptionResult 包含语言、时长、段落列表
        """
        # 实现转写逻辑
        segments = [Segment(start=0.0, end=10.0, text="转写结果")]
        return TranscriptionResult(
            language="zh",
            language_probability=0.95,
            duration=10.0,
            segments=segments,
        )
```

### 2. 注册引擎

在 `engines/factory.py` 中添加：

```python
from engines.new_engine import NewEngine

def create_engine(engine_type, config, ...):
    ...
    elif engine_type == "new":
        return NewEngine(
            api_key=config.get("new_api_key"),
            base_url=config.get("new_base_url"),
        )
```

### 3. 添加配置

在 `config.json` 和 `config.example.json` 中添加：

```json
{
    "new_api_key": "YOUR_API_KEY",
    "new_base_url": "https://api.example.com"
}
```

### 4. 编写测试

创建 `tests/test_new_engine.py`：

```python
from engines.new_engine import NewEngine

def test_transcribe():
    engine = NewEngine(api_key="test", base_url="https://test.com")
    result = engine.transcribe("test.mp3")
    assert result.language is not None
    assert len(result.segments) > 0
```

### 5. 运行测试

```bash
pytest tests/test_new_engine.py -v
```

## 如何添加新翻译器

### 1. 创建翻译器文件

参考 `translator.py` 的 Translator 类实现：

```python
class NewTranslator:
    def __init__(self, config: dict):
        self.api_key = config.get("new_translator_key")

    def translate_paragraph(self, text: str, **kwargs) -> str:
        # 实现翻译逻辑
        return translated_text

    def translate_paragraphs(self, paragraphs: list, **kwargs) -> list:
        return [self.translate_paragraph(p) for p in paragraphs]
```

### 2. 集成到 transcribe_one

在 `core/pipeline.py` 中修改翻译器创建逻辑。

## 代码风格

### Python 版本
- 支持 Python 3.8+
- 使用 `from __future__ import annotations` 启用延迟注解

### 命名规范
- 类名：`PascalCase`
- 函数/变量：`snake_case`
- 常量：`UPPER_SNAKE_CASE`
- 私有成员：`_leading_underscore`

### 类型注解
- 函数签名使用类型注解
- 使用 `Optional[X]` 而非 `X | None`（兼容 3.8）

```python
def process(text: str, limit: Optional[int] = None) -> list[str]:
    ...
```

### 文档字符串
- 使用 Google 风格 docstring
- 公共 API 必须有 docstring

```python
def transcribe(audio_path: str, language: Optional[str] = None) -> TranscriptionResult:
    """转写音频文件。

    Args:
        audio_path: 音频文件路径
        language: 语言代码，None 表示自动检测

    Returns:
        TranscriptionResult 包含转写结果

    Raises:
        EngineError: 转写失败
    """
```

### 导入顺序
1. 标准库
2. 第三方库
3. 项目内部模块

```python
import json
import time

import pytest

from engines.base import Segment
from translator import Translator
```

## 提交规范

### Commit Message 格式
```
<类型>(<范围>): <描述>

<详细说明>

<关联 issue>
```

### 类型
- `feat`: 新功能
- `fix`: 修复
- `refactor`: 重构
- `test`: 测试
- `docs`: 文档
- `style`: 格式
- `perf`: 性能

### 示例
```
feat(engines): 添加新 ASR 引擎支持

- 实现 NewEngine 类
- 注册到 factory.py
- 添加单元测试

Closes #123
```

## 测试要求

- 新功能必须有测试
- 运行 `pytest tests/` 确保全部通过
- 覆盖率不低于 80%

```bash
# 运行测试
pytest tests/

# 查看覆盖率
pytest tests/ --cov=. --cov-report=term-missing
```

## Pull Request 流程

1. Fork 项目
2. 创建功能分支：`git checkout -b feature/new-engine`
3. 提交代码：`git commit -m "feat(engines): 添加新引擎"`
4. 推送分支：`git push origin feature/new-engine`
5. 创建 Pull Request
6. 等待 CI 通过
7. 请求 review

## 问题反馈

- 使用 GitHub Issues
- 提供错误日志
- 描述复现步骤
- 附上环境信息（OS、Python 版本）
