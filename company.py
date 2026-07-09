"""
company.py - 公司背景知识模块 (v2)
从 companies.yaml 动态加载公司信息，支持纠正规则。
"""

from __future__ import annotations

import os
import re
import yaml
from pathlib import Path

COMPANIES_FILE = os.path.join(os.path.dirname(__file__) or ".", "companies.yaml")
COMPANY_WIKI_PATH = os.path.expanduser("~/company-wiki")

# 兜底映射 (companies.yaml 不存在时使用)
_FALLBACK = {
    "小米集团": {
        "en": "Xiaomi Corporation",
        "ticker": "1810.HK",
        "sector": "消费电子/智能汽车/AI",
    },
    "阿里巴巴": {
        "en": "Alibaba Group",
        "ticker": "BABA/9988.HK",
        "sector": "电商/云计算/AI",
    },
    "腾讯": {"en": "Tencent Holdings", "ticker": "0700.HK", "sector": "互联网/游戏/云"},
    "比亚迪": {
        "en": "BYD Company",
        "ticker": "002594.SZ/1211.HK",
        "sector": "新能源汽车/电池",
    },
    "快手": {
        "en": "Kuaishou Technology",
        "ticker": "1024.HK",
        "sector": "短视频/直播/电商",
    },
    "拼多多": {"en": "PDD Holdings", "ticker": "PDD", "sector": "电商/社区团购"},
}


def _load_yaml() -> dict:
    """从 companies.yaml 加载公司数据"""
    if os.path.exists(COMPANIES_FILE):
        with open(COMPANIES_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_all_companies() -> dict:
    """获取所有公司数据 (YAML 不存在时用兜底)"""
    data = _load_yaml()
    if not data:
        return dict(_FALLBACK)
    return data


def _find_company_key(stem: str) -> str | None:
    """在 companies 中查找匹配 stem 的公司中文名。

    匹配优先级：精确 > 最长子串 > 别名/英文名。
    多个子串匹配时选最长名（避免"小米"覆盖"小米集团"）。
    """
    companies = get_all_companies()
    if stem in companies:
        return stem
    matches = [cn for cn in companies if cn in stem]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return max(matches, key=len)
    for cn_name, info in companies.items():
        en_first = info.get("en", "").split()[0].lower() if info.get("en") else ""
        if en_first and en_first in stem.lower():
            return cn_name
        for alias in info.get("aliases", []):
            if alias.lower() in stem.lower():
                return cn_name
    return None


def extract_company_from_filename(filename: str) -> str | None:
    """从文件名提取公司名"""
    stem = Path(filename).stem
    found = _find_company_key(stem)
    if found:
        return found
    name = re.sub(r"\d{8}", "", stem).strip()
    name = re.sub(r"[_\-\.]", " ", name).strip()
    return name if name else None


def get_company_context(company_name: str | None) -> str:
    """获取公司背景知识，用于翻译上下文"""
    if not company_name:
        return ""

    companies = get_all_companies()
    context_parts = []
    cn_name = _find_company_key(company_name) or company_name
    info = companies.get(cn_name)
    if info:
        parts = [
            f"公司: {cn_name} ({info.get('en', '')})",
            f"代码: {info.get('ticker', '')}",
            f"行业: {info.get('sector', '')}",
        ]
        if "products" in info:
            parts.append(f"主要产品: {', '.join(info['products'])}")
        if "notes" in info:
            parts.append(f"注意事项: {info['notes']}")
        context_parts.append("\n".join(parts))

    wiki = _load_wiki_context(company_name)
    if wiki:
        context_parts.append(wiki)
    return "\n\n".join(context_parts) if context_parts else ""


def get_corrections(company_name: str | None) -> dict[str, str]:
    """获取公司的 Whisper 误识别纠正规则"""
    if not company_name:
        return {}
    companies = get_all_companies()
    cn_name = _find_company_key(company_name) or company_name
    return companies.get(cn_name, {}).get("corrections", {})


def _load_wiki_context(company_name: str) -> str:
    """从 company-wiki 加载补充信息"""
    graph_path = os.path.join(COMPANY_WIKI_PATH, "graph.yaml")
    if not os.path.exists(graph_path):
        return ""

    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            graph = yaml.safe_load(f)
    except Exception:
        return ""

    for cname, company in graph.get("companies", {}).items():
        aliases = company.get("aliases", [])
        if company_name in cname or company_name in aliases:
            parts = []
            if "position" in company:
                parts.append(f"定位: {company['position']}")
            if "sectors" in company:
                parts.append(f"板块: {', '.join(company['sectors'])}")
            return "\n".join(parts)

    return ""
