"""容错解析器的测试。

fixture 是一份人工构造的、带全部三类语法错误的文件（数值是假的）——
对应真机导出的固定损坏形态。
"""

from pathlib import Path

from healthpipe import repair

FIXTURE = Path(__file__).parent / "fixtures" / "broken-shortcut.txt"


def test_repairs_the_daily_export():
    obj, fixes = repair.load_file(FIXTURE)

    assert obj["date"] == "2026-01-15"
    assert len(obj["heart_rate"]) == 4
    assert len(obj["sleep"]) == 4
    # 三类问题都要被识别出来
    assert len(fixes) == 3


def test_stray_quote_after_number_is_stripped():
    obj, _ = repair.load_file(FIXTURE)
    assert [p["v"] for p in obj["heart_rate"]] == [54, 57, 88, 96]


def test_trailing_comma_and_fullwidth_bracket():
    obj, fixes = repair.load_file(FIXTURE)
    assert obj["sleep"][-1]["type"] == "Core"
    assert any("尾随逗号" in f for f in fixes)
    assert any("全角" in f for f in fixes)


def test_valid_json_passes_through_untouched():
    obj, fixes = repair.load_text('{"a": 1}')
    assert obj == {"a": 1}
    assert fixes == []


def test_fullwidth_only():
    obj, _ = repair.repair_text('{"a": [1, 2］}')
    assert obj == {"a": [1, 2]}


def test_detect_issues_reports_without_modifying():
    raw = FIXTURE.read_text(encoding="utf-8")
    issues = repair.detect_issues(raw)
    assert len(issues) == 3
    # 只探测，原文不变
    assert "］" in raw
