# 故障排除指南

## 常见问题

### 1. MiMo API 错误

#### 401 Unauthorized
```
错误: MiMo API 失败: 401 Unauthorized
```
**原因**: API Key 无效或过期
**解决**:
1. 检查 `config.json` 中的 `mimo_api_key` 是否正确
2. 确认 API Key 未过期
3. 确认使用的是中国区 endpoint: `https://token-plan-cn.xiaomimimo.com/v1/chat/completions`

#### 400 tokens too long
```
错误: MiMo API 失败: 400 tokens too long
```
**原因**: 音频文件过大，超出 token 限制
**解决**:
- MiMo 单次请求限制约 8192 tokens
- 系统会自动切片，但如果单个切片仍过大，尝试减小 `audio_utils.py` 中的 `MAX_BASE64_MB` 值

#### 404 Not Found
```
错误: MiMo API 失败: 404 Not Found
```
**原因**: API endpoint URL 错误
**解决**: 确认 `mimo_base_url` 为 `https://token-plan-cn.xiaomimimo.com/v1/chat/completions`

### 2. Whisper 错误

#### ffmpeg not found
```
错误: FileNotFoundError: ffmpeg not found
```
**解决**:
1. 下载 ffmpeg: https://www.gyan.dev/ffmpeg/builds/
2. 解压到目录，如 `C:\ffmpeg\`
3. 将 `C:\ffmpeg\bin` 添加到系统 PATH
4. 重启终端

#### 模型下载失败
```
错误: faster-whisper 模型下载失败
```
**解决**:
- 模型会自动下载到 `~/.cache/huggingface/`
- 如网络问题，可手动下载后放到对应目录
- 或使用 `whisper_model: tiny` 减小下载量

### 3. 翻译错误

#### DeepSeek API 超时
```
警告: 翻译重试 1/3 (4s): timeout
```
**解决**:
- 增加 `translate_api_timeout` 配置值（默认 120 秒）
- 检查网络连接
- 翻译会自动重试 3 次

#### 翻译失败跳过
```
警告: 翻译失败，跳过翻译文件
```
**解决**:
- 检查 `deepseek_api_key` 是否正确
- 检查 DeepSeek API 余额
- 原文文件仍会生成

### 4. 配置错误

#### 找不到配置文件
```
错误: 找不到配置文件
```
**解决**:
```bash
cp config.example.json config.json
# 编辑 config.json 填入真实 API Key
```

#### 配置验证失败
```
错误: deepseek_api_key 未配置（仍为默认占位符）
```
**解决**: 将 `YOUR_API_KEY_HERE` 替换为真实 API Key

### 5. 音频格式问题

#### 格式不支持
```
警告: 格式不支持，回退到备用引擎
```
**说明**: MiMo 不支持该格式，已自动回退到 Whisper
**解决**: 无需处理，系统会自动处理

#### 损坏的音频文件
```
错误: ffmpeg 无法解析音频
```
**解决**:
- 检查文件是否完整
- 尝试用其他播放器打开确认文件有效
- 重新下载或获取音频文件

### 6. Windows 编码问题

#### GBK 编码错误
```
错误: 'gbk' codec can't decode
```
**说明**: 已在 v2 中修复，所有 subprocess 调用使用二进制模式
**解决**: 更新到最新版本

### 7. 性能问题

#### 转写速度慢
**Whisper CPU 优化**:
- 使用 `whisper_model: tiny` 或 `base` 进行快速预览
- 使用 `whisper_compute_type: int8` 减少内存占用
- 如有 GPU，设置 `whisper_device: cuda`

#### 内存不足
**解决**:
- 使用较小的 Whisper 模型（tiny/base/small）
- 关闭其他占用内存的程序
- 使用 `whisper_compute_type: int8` 减少内存占用

## 日志调试

启用详细日志：
```bash
python transcribe.py input.mp3 -v
```

日志会显示：
- 引擎选择过程
- 每段转写耗时
- 翻译进度
- 性能指标（RTF、速度）

## 获取帮助

1. 检查本文档是否有对应错误
2. 运行 `pytest tests/` 确认代码正常
3. 查看 `progress.md` 了解已知问题
4. 提交 issue 附上错误日志
