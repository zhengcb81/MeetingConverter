"""
company.py - 公司背景知识模块 (v2)
从 companies.yaml 动态加载公司信息，支持纠正规则。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

COMPANIES_FILE = os.path.join(os.path.dirname(__file__) or ".", "companies.yaml")

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
    return load_company_catalog(COMPANIES_FILE)


def load_company_catalog(path) -> dict:
    """Read company entries, including YAML's empty mapping values."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as stream:
            items = yaml.safe_load(stream) or {}
        return {name: {} if info is None else info for name, info in items.items()}
    return {}


def get_all_companies() -> dict:
    """获取所有公司数据 (YAML 不存在时用兜底)"""
    data = _load_yaml()
    if not data:
        return dict(_FALLBACK)
    return data


def _find_company_key(stem: str, companies: dict) -> str | None:
    """在 companies 中查找匹配 stem 的公司中文名。

    匹配优先级：精确 > 最长子串 > 别名/英文名。
    多个子串匹配时选最长名（避免"小米"覆盖"小米集团"）。
    """
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
    found = _find_company_key(stem, get_all_companies())
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
    cn_name = _find_company_key(company_name, companies) or company_name
    info = companies.get(cn_name)
    if not info:
        return ""

    parts = [
        f"公司: {cn_name} ({info.get('en', '')})",
        f"代码: {info.get('ticker', '')}",
        f"行业: {info.get('sector', '')}",
    ]
    if "products" in info:
        parts.append(f"主要产品: {', '.join(info['products'])}")
    if "notes" in info:
        parts.append(f"注意事项: {info['notes']}")

    position = info.get("position")
    if isinstance(position, str) and position.strip():
        parts.append(f"定位: {position.strip()}")
    sectors = info.get("sectors")
    if isinstance(sectors, list):
        labels = [label.strip() for label in sectors if isinstance(label, str) and label.strip()]
        if labels:
            parts.append(f"板块: {', '.join(labels)}")
    return "\n".join(parts)


def get_corrections(company_name: str | None) -> dict[str, str]:
    """获取公司的 Whisper 误识别纠正规则"""
    if not company_name:
        return {}
    companies = get_all_companies()
    cn_name = _find_company_key(company_name, companies) or company_name
    return companies.get(cn_name, {}).get("corrections", {})
