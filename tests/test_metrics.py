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


def test_anonymize_touches_every_numeric_field():
    """白名单式脱敏最容易漏字段（漏了就是隐私泄露），这里守住。

    只要没被处理过，脱敏后应当与真值不同。标签类（_source / captured_at）
    和列表（qc）不算敏感数值，跳过。
    """
    series = {
        "2026-01-01": {
            "_source": "shortcut",
            "captured_at": "18:02",
            "steps": 8123,
            "distance_km": 5.83,
            "active_kcal": 401.7,
            "basal_kcal": 1503.9,
            "exercise_min": 31,
            "hrv_ms": 47.19,
            "hr_avg": 71.8,
            "hr_resting": 72,
            "hr_max": 103.0,
            "hr_min": 53.0,
            "sleep_asleep_h": 9.63,
            "sleep_inbed_h": 10.57,
            "sleep_efficiency": 91.2,
            "sleep": {"deep": 30, "core": 400, "rem": 100, "awake": 30},
            "qc": [],
            "workouts": [
                {"type": "swimming", "calories": 330, "duration_min": 183.5,
                 "distance_km": 2.13, "source": "watch"}
            ],
        }
    }
    src = series["2026-01-01"]
    anon = metrics.anonymize(series, seed=3)["2026-01-01"]

    for k, v in src.items():
        if k in ("_source", "captured_at", "qc"):
            continue
        if isinstance(v, (int, float)):
            assert anon[k] != v, f"{k} 没有被脱敏"

    for k, v in src["sleep"].items():
        assert anon["sleep"][k] != v, f"sleep.{k} 没有被脱敏"

    for k in ("calories", "duration_min", "distance_km"):
        assert anon["workouts"][0][k] != src["workouts"][0][k], f"workouts.{k} 没有被脱敏"


def test_anonymize_keeps_non_sensitive_labels():
    """脱敏不该误伤来源标签 —— 否则仪表盘/报告里看不出数据是哪来的。"""
    series = {"2026-01-01": {"_source": "shortcut", "captured_at": "18:02", "steps": 8000}}
    anon = metrics.anonymize(series, seed=3)["2026-01-01"]
    assert anon["_source"] == "shortcut"
    assert anon["captured_at"] == "18:02"
