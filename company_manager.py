#!/usr/bin/env python3
"""
company_manager.py - 公司知识库管理工具
动态维护 companies.yaml，无需改代码。

用法:
  python company_manager.py list                          # 列出所有公司
  python company_manager.py show 小米集团                  # 查看详情
  python company_manager.py add 公司名 --en XX --ticker XX # 添加公司
  python company_manager.py update 公司名 --products "A,B" # 更新字段
  python company_manager.py correct 公司名 --from U7 --to YU7 GT  # 添加纠正规则
  python company_manager.py correct 小米集团 --list        # 查看纠正规则
  python company_manager.py import-corr 公司名 --file corrections.txt  # 批量导入纠正
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

COMPANIES_FILE = os.path.join(os.path.dirname(__file__) or ".", "companies.yaml")


def load_companies() -> dict:
    if not os.path.exists(COMPANIES_FILE):
        return {}
    with open(COMPANIES_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_companies(data: dict):
    with open(COMPANIES_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"已保存: {COMPANIES_FILE}")


def cmd_list(args):
    data = load_companies()
    if not data:
        print("知识库为空")
        return
    print(f"{'公司名':<12} {'英文名':<25} {'代码':<12} {'行业':<20} {'纠正规则数'}")
    print("-" * 85)
    for name, info in data.items():
        en = info.get("en", "")
        ticker = info.get("ticker", "")
        sector = info.get("sector", "")
        corrs = len(info.get("corrections", {}))
        print(f"{name:<12} {en:<25} {ticker:<12} {sector:<20} {corrs}")


def cmd_show(args):
    data = load_companies()
    name = args.name
    if name not in data:
        print(f"未找到: {name}")
        print(f"已知公司: {', '.join(data.keys())}")
        return
    info = data[name]
    print(f"\n{'='*40}")
    print(f"公司: {name}")
    print(f"{'='*40}")
    for k, v in info.items():
        if k == "corrections":
            print(f"\n纠正规则 ({len(v)} 条):")
            for wrong, right in v.items():
                print(f"  \"{wrong}\" → \"{right}\"")
        else:
            print(f"{k}: {v}")


def cmd_add(args):
    data = load_companies()
    if args.name in data:
        print(f"公司已存在: {args.name}，用 update 修改")
        return
    entry = {"en": args.en or "", "ticker": args.ticker or "", "sector": args.sector or ""}
    if args.aliases:
        entry["aliases"] = [a.strip() for a in args.aliases.split(",")]
    if args.products:
        entry["products"] = [p.strip() for p in args.products.split(",")]
    if args.notes:
        entry["notes"] = args.notes
    entry["corrections"] = {}
    data[args.name] = entry
    save_companies(data)
    print(f"已添加: {args.name}")


def cmd_update(args):
    data = load_companies()
    if args.name not in data:
        print(f"未找到: {args.name}")
        return
    entry = data[args.name]
    if args.en:
        entry["en"] = args.en
    if args.ticker:
        entry["ticker"] = args.ticker
    if args.sector:
        entry["sector"] = args.sector
    if args.aliases:
        entry["aliases"] = [a.strip() for a in args.aliases.split(",")]
    if args.products:
        entry["products"] = [p.strip() for p in args.products.split(",")]
    if args.notes:
        entry["notes"] = args.notes
    save_companies(data)
    print(f"已更新: {args.name}")


def cmd_correct(args):
    data = load_companies()
    if args.name not in data:
        print(f"未找到: {args.name}")
        return

    entry = data[args.name]
    corrs = entry.setdefault("corrections", {})

    if args.list:
        if not corrs:
            print(f"{args.name} 暂无纠正规则")
        else:
            print(f"\n{args.name} 纠正规则:")
            for wrong, right in corrs.items():
                print(f"  \"{wrong}\" → \"{right}\"")
        return

    if args.delete:
        if args.delete in corrs:
            del corrs[args.delete]
            save_companies(data)
            print(f"已删除: \"{args.delete}\"")
        else:
            print(f"未找到规则: \"{args.delete}\"")
        return

    if args.from_key and args.to:
        corrs[args.from_key] = args.to
        save_companies(data)
        print(f"已添加: \"{args.from_key}\" → \"{args.to}\"")
    else:
        print("需要 --from 和 --to 参数")


def cmd_import_corr(args):
    """从文件批量导入纠正规则，格式: wrong<tab>to 或 wrong|to"""
    data = load_companies()
    if args.name not in data:
        print(f"未找到: {args.name}")
        return

    corrs = data[args.name].setdefault("corrections", {})
    count = 0

    with open(args.file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 支持 tab 或 | 分隔
            parts = line.split("\t") if "\t" in line else line.split("|")
            if len(parts) >= 2:
                wrong, right = parts[0].strip(), parts[1].strip()
                if wrong and right:
                    corrs[wrong] = right
                    count += 1

    save_companies(data)
    print(f"已导入 {count} 条纠正规则到 {args.name}")


def main():
    parser = argparse.ArgumentParser(description="公司知识库管理工具")
    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser("list", help="列出所有公司")

    # show
    p_show = sub.add_parser("show", help="查看公司详情")
    p_show.add_argument("name", help="公司名")

    # add
    p_add = sub.add_parser("add", help="添加公司")
    p_add.add_argument("name")
    p_add.add_argument("--en", help="英文名")
    p_add.add_argument("--ticker", help="股票代码")
    p_add.add_argument("--sector", help="行业")
    p_add.add_argument("--aliases", help="别名(逗号分隔)")
    p_add.add_argument("--products", help="产品(逗号分隔)")
    p_add.add_argument("--notes", help="注意事项")

    # update
    p_upd = sub.add_parser("update", help="更新公司信息")
    p_upd.add_argument("name")
    p_upd.add_argument("--en")
    p_upd.add_argument("--ticker")
    p_upd.add_argument("--sector")
    p_upd.add_argument("--aliases")
    p_upd.add_argument("--products")
    p_upd.add_argument("--notes")

    # correct
    p_corr = sub.add_parser("correct", help="管理纠正规则")
    p_corr.add_argument("name")
    p_corr.add_argument("--from", dest="from_key", help="Whisper误识别文本")
    p_corr.add_argument("--to", help="正确文本")
    p_corr.add_argument("--delete", help="删除指定规则")
    p_corr.add_argument("--list", action="store_true", help="列出所有规则")

    # import-corr
    p_imp = sub.add_parser("import-corr", help="批量导入纠正规则")
    p_imp.add_argument("name")
    p_imp.add_argument("--file", required=True, help="规则文件(wrong\\tright)")

    args = parser.parse_args()
    cmds = {"list": cmd_list, "show": cmd_show, "add": cmd_add,
            "update": cmd_update, "correct": cmd_correct, "import-corr": cmd_import_corr}

    if args.command in cmds:
        cmds[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
