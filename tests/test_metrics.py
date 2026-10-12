"""派生指标 / 质量守门 / 脱敏 的测试。"""

from healthpipe import metrics


def test_summarize_sleep_handles_cross_midnight():
    segs = [
        {"start": "23:00", "end": "23:30", "type": "Core"},
        {"start": "23:30", "end": "00:00", "type": "Core"},
    ]
    out = metrics.summarize_sleep(segs)
    assert out["core"] == 60
    assert out["bed_start"] == "23:00"
    assert out["bed_end"] == "00:00"


def test_summarize_sleep_splits_stages():
    segs = [
        {"start": "23:00", "end": "23:30", "type": "Deep"},
        {"start": "23:30", "end": "00:30", "type": "REM"},
        {"start": "00:30", "end": "00:45", "type": "Awake"},
    ]
    out = metrics.summarize_sleep(segs)
    assert out["deep"] == 30
    assert out["rem"] == 60
    assert out["awake"] == 15


def test_enrich_computes_asleep_and_efficiency():
    series = {"2026-01-01": {"sleep": {"deep": 60, "core": 300, "rem": 60, "awake": 30}}}
    out = metrics.enrich(series)
    dd = out["2026-01-01"]
    assert dd["sleep_asleep_h"] == 7.0
    assert dd["sleep_inbed_h"] == 7.5
    assert dd["sleep_efficiency"] == 93.3


def test_qc_flags_short_inbed_time():
    assert metrics.qc_flags({"sleep_inbed_h": 0.5}) == ["在床不足 1.5h，疑似未佩戴手表"]


def test_qc_flags_high_steps():
    flags = metrics.qc_flags({"steps": 21000})
    assert len(flags) == 1 and "18000" in flags[0]


def test_qc_flags_clean_day():
    assert metrics.qc_flags({"sleep_inbed_h": 7.5, "steps": 8000}) == []


def test_stat_of_ignores_missing_values():
    series = {"a": {"x": 1}, "b": {"x": 3}, "c": {}}
    assert metrics.stat_of(series, "x") == {"mean": 2.0, "n": 2}
    assert metrics.stat_of(series, "nope") == {"mean": None, "n": 0}


def test_anonymize_drops_dense_series_and_shifts_values():
    series = {
        "2026-01-01": {
            "steps": 10000,
            "hr_points": [["08:00", 70]],
            "sleep_segments": [{"start": "23:00", "end": "07:00", "type": "Core"}],
        }
    }
    out = metrics.anonymize(series, seed=1)
    dd = out["2026-01-01"]
    assert "hr_points" not in dd
    assert "sleep_segments" not in dd
    assert dd["steps"] != 10000


def test_anonymize_is_deterministic_for_a_seed():
    series = {"2026-01-01": {"steps": 10000}}
    assert metrics.anonymize(series, seed=7) == metrics.anonymize(series, seed=7)
