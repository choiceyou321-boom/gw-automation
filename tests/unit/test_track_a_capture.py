"""track_a_capture.py 단위 테스트 — Playwright 없이 순수 함수만 검증."""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture(scope="module")
def mod():
    return importlib.import_module("scripts.track_a_capture")


def test_pick_inquiry_selectors_filters(mod):
    """'조회'/'검색' 텍스트의 셀렉터만 추출."""
    buttons = [
        {"text": "저장", "selectors": ["button:has-text('저장')"]},
        {"text": "조회", "selectors": ["button:has-text('조회')", "#btnSearch"]},
        {"text": "취소", "selectors": ["button:has-text('취소')"]},
        {"text": "검색", "selectors": ["button:has-text('검색')"]},
        {"text": "조회", "selectors": ["button:has-text('조회')"]},  # 중복
    ]
    result = mod.pick_inquiry_selectors(buttons)
    assert "button:has-text('조회')" in result
    assert "#btnSearch" in result
    assert "button:has-text('검색')" in result
    assert "button:has-text('저장')" not in result
    # 중복 제거
    assert result.count("button:has-text('조회')") == 1


def test_pick_inquiry_selectors_empty(mod):
    assert mod.pick_inquiry_selectors([]) == []
    assert mod.pick_inquiry_selectors([{"text": "기타"}]) == []


def test_load_existing_returns_dict_when_missing(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "OUT", tmp_path / "missing.json")
    assert mod.load_existing() == {}


def test_load_existing_reads_valid_json(mod, monkeypatch, tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    monkeypatch.setattr(mod, "OUT", path)
    assert mod.load_existing() == {"a": 1}


def test_load_existing_corrupted_returns_empty(mod, monkeypatch, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("이건 JSON 아님", encoding="utf-8")
    monkeypatch.setattr(mod, "OUT", path)
    assert mod.load_existing() == {}


def test_save_writes_unicode(mod, monkeypatch, tmp_path):
    path = tmp_path / "save.json"
    monkeypatch.setattr(mod, "OUT", path)
    mod.save({"예실대비현황_상세": {"url_path": "/#/BN/NCC0630/NCC0630"}})
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["예실대비현황_상세"]["url_path"] == "/#/BN/NCC0630/NCC0630"


def test_module_constants(mod):
    """헬퍼 스크립트의 JS 상수가 비어있지 않은지 sanity check."""
    assert "querySelectorAll" in mod.JS_DETECT_BUTTONS
    assert "querySelectorAll" in mod.JS_DETECT_MODAL
    assert mod.OUT.name == "track_a_captures.json"
