"""
translator.py - DeepSeek LLM 翻译模块 (v2)
支持段落级翻译，公司背景知识注入，LLM 自审校纠正。
"""

import json
import time
import urllib.request
import urllib.error


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


class Translator:
    """DeepSeek LLM 翻译器 (带公司背景 + 自审校)"""

    def __init__(self, config: dict):
        self.api_key = config.get("deepseek_api_key", "")
        self.base_url = config.get("deepseek_base_url", "https://api.deepseek.com")
        self.model = config.get("deepseek_model", "deepseek-v4-flash")
        self.max_retries = config.get("translate_max_retries", 3)

        if not self.api_key or self.api_key == "YOUR_API_KEY_HERE":
            raise ValueError(
                "请在 config.json 中设置 deepseek_api_key，"
                "或确保 ~/earnings-transcripts/config.json 中有配置"
            )

    def translate_paragraph(self, text: str, company_context: str = "",
                           corrections: dict = None) -> str:
        if not text.strip():
            return ""
        if self._is_mostly_chinese(text):
            # 中文也要应用纠正规则
            return self._apply_corrections(text, corrections)

        for attempt in range(self.max_retries):
            try:
                raw = self._call_api(text, company_context)
                cleaned = self._clean_output(raw)
                return self._apply_corrections(cleaned, corrections)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  翻译重试 {attempt+1}/{self.max_retries} ({wait}s): {e}")
                    time.sleep(wait)
                else:
                    print(f"  翻译失败: {e}")
                    return f"[翻译失败] {text}"

    @staticmethod
    def _clean_output(text: str) -> str:
        """清理 LLM 输出，去除审核过程，只保留最终翻译"""
        import re
        lines = text.split("\n")
        clean = []
        skip = False

        for line in lines:
            stripped = line.strip()

            # 跳过审核过程标记
            if re.match(r'^#{1,3}\s*第.步', stripped):
                skip = True
                continue
            if stripped.startswith("【审校后"):
                skip = False
                continue
            if stripped.startswith("（注：") or stripped.startswith("(注："):
                continue
            if stripped.startswith("结合") and ("背景" in stripped or "公司" in stripped):
                skip = True
                continue
            if re.match(r'^\d+\.\s*["""]', stripped):
                continue
            if stripped in ("因此，审校后输出如下：", "审校后输出如下："):
                continue

            if not skip:
                clean.append(line)

        result = "\n".join(clean).strip()

        # 如果清理后为空，返回原文（可能是误清）
        if not result or len(result) < 10:
            return text.strip()

        return result

    def translate_paragraphs(self, paragraphs, company_context="",
                            corrections=None, progress_callback=None):
        results = []
        total = len(paragraphs)
        for i, para in enumerate(paragraphs):
            if progress_callback:
                progress_callback(i + 1, total)
            results.append(self.translate_paragraph(para, company_context, corrections))
            if i < total - 1:
                time.sleep(0.3)
        return results

    @staticmethod
    def _apply_corrections(text: str, corrections: dict = None) -> str:
        """应用公司知识库中的纠正规则（按长度降序，避免子串误替换）"""
        if not corrections or not text:
            return text
        import re
        # 按 key 长度降序排列，长的先替换（避免 "U7" 替换 "SU7" 中的子串）
        sorted_corrs = sorted(corrections.items(), key=lambda x: len(x[0]), reverse=True)
        for wrong, right in sorted_corrs:
            # 使用词边界匹配，避免替换子串
            # 对于中文字符不用词边界（\b 不支持中文）
            if any('\u4e00' <= c <= '\u9fff' for c in wrong):
                text = text.replace(wrong, right)
            else:
                # 英文用 word boundary: \bU7\b 不会匹配 SU7
                pattern = r'\b' + re.escape(wrong) + r'\b'
                text = re.sub(pattern, right, text)
        return text

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
            url, data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _is_mostly_chinese(text: str) -> bool:
        chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        total = len(text.replace(" ", "").replace("\n", ""))
        return total > 0 and chinese / total > 0.3


def detect_language(text: str) -> str:
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len(text.replace(" ", "").replace("\n", ""))
    if total == 0:
        return "unknown"
    ratio = chinese / total
    if ratio > 0.3:
        return "zh"
    elif ratio < 0.05:
        return "en"
    return "mixed"


def load_config(config_path: str = None) -> dict:
    import os
    search = [
        config_path,
        os.path.join(os.path.dirname(__file__) or ".", "config.json"),
        os.path.expanduser("~/MeetingConverter/config.json"),
        os.path.expanduser("~/earnings-transcripts/config.json"),
    ]
    for p in search:
        if p and os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if cfg.get("deepseek_api_key") in (None, "", "YOUR_API_KEY_HERE"):
                ep = os.path.expanduser("~/earnings-transcripts/config.json")
                if ep != p and os.path.exists(ep):
                    with open(ep, "r", encoding="utf-8") as f2:
                        ep_cfg = json.load(f2)
                    if ep_cfg.get("deepseek_api_key") and ep_cfg["deepseek_api_key"] != "YOUR_API_KEY_HERE":
                        cfg["deepseek_api_key"] = ep_cfg["deepseek_api_key"]
                        cfg.setdefault("deepseek_base_url", ep_cfg.get("deepseek_base_url"))
                        cfg.setdefault("deepseek_model", ep_cfg.get("deepseek_model"))
            return cfg
    raise FileNotFoundError("找不到配置文件，请确保 ~/MeetingConverter/config.json 存在")
