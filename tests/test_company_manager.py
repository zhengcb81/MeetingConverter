"""tests/test_company_manager.py - company_manager 单元测试。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import company_manager as cm


@pytest.fixture
def companies_file(tmp_path, monkeypatch):
    """临时 companies.yaml 文件。"""
    f = tmp_path / "companies.yaml"
    monkeypatch.setattr(cm, "COMPANIES_FILE", str(f))
    return f


@pytest.fixture
def sample_data():
    return {
        "小米集团": {
            "en": "Xiaomi Corporation",
            "ticker": "1810.HK",
            "sector": "消费电子",
            "aliases": ["Xiaomi", "小米"],
            "corrections": {"U7": "YU7"},
        },
    }


class TestLoadSave:
    def test_load_empty_when_no_file(self, companies_file):
        data = cm.load_companies()
        assert data == {}

    def test_load_existing(self, companies_file, sample_data):
        with open(companies_file, "w", encoding="utf-8") as f:
            yaml.dump(sample_data, f, allow_unicode=True)
        data = cm.load_companies()
        assert "小米集团" in data

    def test_save_and_reload(self, companies_file, sample_data):
        cm.save_companies(sample_data)
        data = cm.load_companies()
        assert data == sample_data


class TestCmdList:
    def test_empty(self, companies_file, capsys):
        cm.cmd_list(None)
        captured = capsys.readouterr()
        assert "空" in captured.out

    def test_with_data(self, companies_file, sample_data, capsys):
        cm.save_companies(sample_data)
        cm.cmd_list(None)
        captured = capsys.readouterr()
        assert "小米集团" in captured.out


class TestCmdShow:
    def test_existing_company(self, companies_file, sample_data, capsys):
        cm.save_companies(sample_data)
        args = type("Args", (), {"name": "小米集团"})()
        cm.cmd_show(args)
        captured = capsys.readouterr()
        assert "Xiaomi" in captured.out
        assert "U7" in captured.out

    def test_nonexistent_company(self, companies_file, capsys):
        args = type("Args", (), {"name": "不存在"})()
        cm.cmd_show(args)
        captured = capsys.readouterr()
        assert "未找到" in captured.out


class TestCmdAdd:
    def test_add_new(self, companies_file):
        args = type("Args", (), {
            "name": "比亚迪", "en": "BYD", "ticker": "1211.HK",
            "sector": "汽车", "aliases": "BYD", "products": None, "notes": None,
        })()
        cm.cmd_add(args)
        data = cm.load_companies()
        assert "比亚迪" in data
        assert data["比亚迪"]["en"] == "BYD"

    def test_add_existing_skips(self, companies_file, sample_data, capsys):
        cm.save_companies(sample_data)
        args = type("Args", (), {
            "name": "小米集团", "en": None, "ticker": None,
            "sector": None, "aliases": None, "products": None, "notes": None,
        })()
        cm.cmd_add(args)
        captured = capsys.readouterr()
        assert "已存在" in captured.out


class TestCmdCorrect:
    def test_add_correction(self, companies_file, sample_data):
        cm.save_companies(sample_data)
        args = type("Args", (), {
            "name": "小米集团", "from_key": "SU7", "to": "SU7 Ultra",
            "delete": None, "list": False,
        })()
        cm.cmd_correct(args)
        data = cm.load_companies()
        assert data["小米集团"]["corrections"]["SU7"] == "SU7 Ultra"

    def test_list_corrections(self, companies_file, sample_data, capsys):
        cm.save_companies(sample_data)
        args = type("Args", (), {
            "name": "小米集团", "from_key": None, "to": None,
            "delete": None, "list": True,
        })()
        cm.cmd_correct(args)
        captured = capsys.readouterr()
        assert "U7" in captured.out

    def test_delete_correction(self, companies_file, sample_data):
        cm.save_companies(sample_data)
        args = type("Args", (), {
            "name": "小米集团", "from_key": None, "to": None,
            "delete": "U7", "list": False,
        })()
        cm.cmd_correct(args)
        data = cm.load_companies()
        assert "U7" not in data["小米集团"]["corrections"]

    def test_nonexistent_company(self, companies_file, capsys):
        args = type("Args", (), {
            "name": "不存在", "from_key": "A", "to": "B",
            "delete": None, "list": False,
        })()
        cm.cmd_correct(args)
        captured = capsys.readouterr()
        assert "未找到" in captured.out
