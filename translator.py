"""
translator.py - DeepSeek LLM 翻译模块 (v2)
支持段落级翻译，公司背景知识注入，LLM 自审校纠正。
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Union

from config import Config, normalize_config
from config import load_config as load_config
from core.local_diagnostics import record_failure
from exceptions import TranslationError

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TRANSLATE = """你是专业的财务翻译专家，精通中英文。

任务：将英文翻译为中文，结合公司背景知识审校纠正后，只输出最终翻译结果。

规则：
1. 只输出最终校正后的中文翻译，不要输出审校过程、分析步骤、注释说明
2. 保持专业财务术语准确性
3. 公司名、产品名、人名保留英文原文
4. 数字和单位保持原样
5. 保持段落结构
6. 如果发现原文中公司名/产品名有明显拼写错误（如U7应为SU7），直接在翻译中纠正，不要解释

术语参考：revenue=营收, net profit=净利润, gross margin=毛利率, EBITDA=息税折旧摊销前利润, EPS=每股收益, YoY=同比, QoQ=环比, CapEx=资本开支, free cash flow=自由现金流, guidance=指引, dividend=股息, buyback=股票回购, R&D=研发, P/E=市盈率, market share=市场份额, ASP=平均售价, shipment=出货量, delivery=交付量, pre-order=预订"""


def apply_corrections(text: str, corrections: dict = None) -> str:
    """应用公司知识库中的纠正规则（按长度降序，避免子串误替换）。

    英文 key 用 \\b 词边界；中文 key 用普通 replace。
    中文替换前先占位已有 right 值，避免"可灵"→"可灵AI"误伤已存在的"可灵AI"
    （否则会产生"可灵AIAI"）。
    """
    if not corrections or not text:
        return text
    sorted_corrs = sorted(corrections.items(), key=lambda x: len(x[0]), reverse=True)
    for wrong, right in sorted_corrs:
        if any("\u4e00" <= c <= "\u9fff" for c in wrong):
            placeholder = f"\x00CORR{abs(hash(right)) % 100000}\x00"
            protected = text.replace(right, placeholder)
            protected = protected.replace(wrong, right)
            text = protected.replace(placeholder, right)
        else:
            pattern = r"\b" + re.escape(wrong) + r"\b"
            text = re.sub(pattern, right, text)
    return text


class Translator:
    """DeepSeek LLM 翻译器 (带公司背景 + 自审校)"""

    def __init__(self, config: Union[Config, Mapping[str, Any]]):
        settings = normalize_config(config)
        if not settings.deepseek_api_key or settings.deepseek_api_key == "YOUR_API_KEY_HERE":
            raise ValueError("请在 MeetingConverter 的 config.json 中设置 deepseek_api_key")
        settings.validate_translation()
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url
        self.model = settings.deepseek_model
        self.max_retries = settings.translate_max_retries
        self.api_timeout = settings.translate_api_timeout
        self.paragraph_delay = settings.translate_paragraph_delay

    def translate_paragraph(
        self, text: str, company_context: str = "", corrections: dict = None
    ) -> str:
        if not text.strip():
            return ""

        max_attempts = max(1, self.max_retries)
        for attempt in range(max_attempts):
            try:
                raw = self._call_api(text, company_context)
                cleaned = self._clean_output(raw)
                return apply_corrections(cleaned, corrections)
            except Exception as e:
                record_failure("translate_request", e)
                if attempt < max_attempts - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning(
                        "  翻译重试 %d/%d (%ds): %s",
                        attempt + 1, max_attempts, wait, type(e).__name__,
                    )
                    time.sleep(wait)
                else:
                    logger.error("  翻译失败: %s", type(e).__name__)
                    raise TranslationError(f"翻译失败（{max_attempts}次尝试后）") from e

    @staticmethod
    def _clean_output(text: str) -> str:
        """清理 LLM 输出（v3 简化）：保留 thinking 模式输出，仅去首尾空白。
        原 v2 启发式清洗会误删以"结合""第X步"开头的合法翻译。"""
        return text.strip() if text else ""

    def translate_paragraphs(
        self, paragraphs, company_context="", corrections=None, progress_callback=None
    ):
        results = []
        total = len(paragraphs)
        for i, para in enumerate(paragraphs):
            if progress_callback:
                progress_callback(i + 1, total)
            results.append(self.translate_paragraph(para, company_context, corrections))
            if i < total - 1:
                time.sleep(self.paragraph_delay)
        return results

    def _call_api(self, text: str, company_context: str = "") -> str:
        url = f"{self.base_url}/v1/chat/completions"
        user_content = "请翻译以下内容为中文，并审校纠正不合理之处。\n\n"
        if company_context:
            user_content += f"【公司背景】\n{company_context}\n\n"
        user_content += f"【待翻译内容】\n{text}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT_TRANSLATE},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
            "max_tokens": 4096,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.api_timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
