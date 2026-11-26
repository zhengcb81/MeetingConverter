# MeetingConverter 独审返工交接

基线 `fa1f840d37e91df3fc79006dff1b19e4afdd3d6b`。在冻结候选目录运行下列定向复验。已有 CI 收集 `tests/`，新增用例沿用同一入口。

```powershell
$env:PYTHONUTF8 = '1'
python -B -m pytest -q -o addopts= -p no:cacheprovider --tb=short --basetemp .review-r2-independent tests/test_provider_exchange_contract.py tests/test_s2_mimo_diagnostics.py tests/test_s1_logging_resilience.py tests/test_translator.py tests/test_f4_ordinary_failures.py
```

独审查看实际 MiMo 和翻译调用对合成 HTTP 503 都在退避前关闭响应。`dispatch_started`、`response_headers` 和错误共用原运行号、尝试号及请求序号。测试使用离线 transport 替身。核对已收 200 后的正文异常只调用一次，冷查费用仍未知。`implementation_sha256` 由发布的源文件重新计算，`projection_version` 由公开反馈协议提供。实际安装、真实请求和费用不在本次验证范围内。
