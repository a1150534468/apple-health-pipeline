"""LLM 上下文渲染的测试。"""

from healthpipe import context


def _series():
    return {
        "2026-01-01": {
            "sleep_asleep_h": 7.0,
            "hrv_ms": 40.0,
            "hr_resting": 58,
            "steps": 8000,
            "active_kcal": 400,
            "sleep": {"deep": 60, "core": 300, "rem": 60, "awake": 30},
        },
        "2026-01-02": {
            "sleep_asleep_h": 6.0,
            "hrv_ms": 44.0,
            "hr_resting": 56,
            "steps": 12000,
            "active_kcal": 600,
            "sleep": {"deep": 60, "core": 240, "rem": 60, "awake": 30},
        },
        "2026-01-03": {
            "sleep_asleep_h": 8.0,
            "hrv_ms": 48.0,
            "hr_resting": 54,
            "steps": 10000,
            "active_kcal": 500,
            "sleep": {"deep": 90, "core": 300, "rem": 90, "awake": 30},
            "qc": ["步数 ≥18000，疑似户外长距离活动日"],
        },
    }


def test_render_context_empty_series():
    assert "没有可用的健康数据" in context.render_context({})


def test_render_context_reports_latest_day_and_window():
    text = context.render_context(_series(), days=3)
    assert "2026-01-01 → 2026-01-03" in text
    assert "## 最新一天 · 2026-01-03" in text
    assert "## 近 3 天趋势" in text


def test_render_context_marks_quality_flags():
    text = context.render_context(_series(), days=3)
    assert "`2026-01-03`" in text and "18000" in text


def test_render_context_omits_compare_column_without_history():
    # 总天数 <= days，没有"前一个窗口"可比
    text = context.render_context(_series(), days=7)
    assert "对比前" not in text


def test_render_context_adds_compare_column_when_history_exists():
    text = context.render_context(_series(), days=1)
    assert "对比前" in text


def test_render_daily_defaults_to_latest():
    text = context.render_daily(_series())
    assert text.startswith("# 2026-01-03")
    assert "深睡" in text


def test_render_daily_falls_back_to_nearest_earlier_date():
    text = context.render_daily(_series(), "2026-01-02")
    assert text.startswith("# 2026-01-02")


def test_render_daily_before_all_data():
    assert "没有" in context.render_daily(_series(), "2025-12-01")


def test_render_series_unknown_metric_lists_available():
    text = context.render_series(_series(), "nope")
    assert "未知指标" in text and "hrv_ms" in text


def test_render_series_outputs_csv_rows():
    text = context.render_series(_series(), "hrv_ms", days=2)
    assert "date,value" in text
    assert text.strip().endswith("48.0")
    assert "2026-01-01" not in text        # 被 days=2 截掉
