"""healthsync 数据源（health-sync-data 仓库的 3 个 CSV）的解析测试。"""

import json

import pytest

from healthpipe.cli import _load_series
from healthpipe.config import Config
from healthpipe.sources import load_healthsync


def _write(root, name, lines):
    rows = [",".join(l) if isinstance(l, (tuple, list)) else l for l in lines]
    p = root / name
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p


def _make_repo(root, daily=None, sleep=None, workouts=None):
    if daily is not None:
        _write(root, "daily_metrics.csv", daily)
    if sleep is not None:
        _write(root, "sleep_sessions.csv", sleep)
    if workouts is not None:
        _write(root, "workout_sessions.csv", workouts)
    return root


# ---------------------------------------------------------------- 每日指标

def test_daily_mapping_and_units(tmp_path):
    _make_repo(tmp_path, daily=[
        ("date,step_count,distance_walking_running_meters,active_energy_burned_kcal,"
         "basal_energy_burned_kcal,apple_exercise_time_sum,heart_rate_variability_ms,"
         "resting_hr_average_bpm,hr_average_bpm,hr_max_bpm,heart_rate_min"),
        ("2026-10-15,2993,2329.2162405251197,139.93,793.85,15,49.56,73,68.88,131,51"),
    ])
    days = load_healthsync(tmp_path)
    dd = days["2026-10-15"]
    assert dd["steps"] == 2993.0
    assert dd["distance_km"] == 2.33          # 米 → 公里
    assert dd["active_kcal"] == 139.93
    assert dd["basal_kcal"] == 793.85
    assert dd["exercise_min"] == 15.0
    assert dd["hrv_ms"] == 49.56              # HealthKit 原生 SDNN
    assert dd["hr_resting"] == 73.0
    assert dd["hr_avg"] == 68.88
    assert dd["hr_max"] == 131.0
    assert dd["hr_min"] == 51.0
    assert dd["_source"] == "healthsync"


def test_daily_resting_hr_fallback(tmp_path):
    """resting_hr_average_bpm 缺失时退回 resting_heart_rate_min。"""
    _make_repo(tmp_path, daily=[
        ("date,resting_hr_average_bpm,resting_heart_rate_min"),
        ("2026-10-15,,64"),
        ("2026-10-14,63,63"),
    ])
    days = load_healthsync(tmp_path)
    assert days["2026-10-15"]["hr_resting"] == 64.0
    assert days["2026-10-14"]["hr_resting"] == 63.0


def test_empty_daily_row_dropped(tmp_path):
    """只有日期没有指标的行是空天，直接丢掉。"""
    _make_repo(tmp_path, daily=[
        "date,step_count",
        "2026-10-15,",
        "2026-10-14,100",
    ])
    days = load_healthsync(tmp_path)
    assert "2026-10-15" not in days
    assert days["2026-10-14"]["steps"] == 100.0


# ---------------------------------------------------------------- 睡眠


def test_sleep_grouped_by_wake_date_and_aggregated(tmp_path):
    """主睡 + 午睡归到同一天；未分期睡眠并入 core；只有总时长可信。"""
    _make_repo(tmp_path, sleep=[
        ("id,start_datetime,end_datetime,sleep_deep_duration_sec,"
         "sleep_core_duration_sec,sleep_rem_duration_sec,sleep_awake_duration_sec,"
         "sleep_asleep_unspecified_duration_sec"),
        ("a", "2026-10-15 00:37:26", "2026-10-15 08:13:53",
         "2191.23", "16244.26", "7239.02", "1712.09", ""),
        ("b", "2026-10-15 13:53:43", "2026-10-15 15:04:24",
         "", "", "", "120.30", "4120.45"),
    ])
    dd = load_healthsync(tmp_path)["2026-10-15"]
    sl = dd["sleep"]
    assert sl["deep"] == pytest.approx(2191.23 / 60, abs=0.06)
    assert sl["core"] == pytest.approx((16244.26 + 4120.45) / 60, abs=0.06)  # 午睡的未分期时间并入 core
    assert sl["rem"] == pytest.approx(7239.02 / 60, abs=0.06)
    assert sl["awake"] == pytest.approx((1712.09 + 120.30) / 60, abs=0.06)
    assert sl["bed_start"] == "00:37"
    assert sl["bed_end"] == "15:04"
    # 合成分段：每段长度 ≥ 1 分钟，且各类型时长与汇总一致（±每段 1 分钟的取整）
    segs = dd["sleep_segments"]
    assert segs, "应有合成分段"
    for s in segs:
        assert s["start"] != s["end"]
    for key, label in (("deep", "Deep"), ("core", "Core"), ("rem", "REM"), ("awake", "Awake")):
        seg_total = 0.0
        for s in segs:
            if s["type"] != label:
                continue
            a, b = s["start"], s["end"]
            am, bm = int(a[:2]) * 60 + int(a[3:]), int(b[:2]) * 60 + int(b[3:])
            if bm <= am:
                bm += 1440
            seg_total += bm - am
        assert abs(seg_total - sl[key]) <= 2.0


def test_sleep_assigned_to_wake_date(tmp_path):
    """23:50 入睡、07:00 醒 → 记在 07:00 那天。"""
    _make_repo(tmp_path, sleep=[
        ("id,start_datetime,end_datetime,sleep_core_duration_sec"),
        ("a", "2026-10-14 23:50:00", "2026-10-15 07:00:00", "25200"),
    ])
    days = load_healthsync(tmp_path)
    assert "2026-10-14" not in days
    assert days["2026-10-15"]["sleep"]["bed_start"] == "23:50"
    assert days["2026-10-15"]["sleep"]["bed_end"] == "07:00"


def test_sleep_duplicate_id_deduped(tmp_path):
    _make_repo(tmp_path, sleep=[
        ("id,start_datetime,end_datetime,sleep_core_duration_sec"),
        ("a", "2026-10-15 00:00:00", "2026-10-15 08:00:00", "25200"),
        ("a", "2026-10-15 00:00:00", "2026-10-15 08:00:00", "25200"),
    ])
    sl = load_healthsync(tmp_path)["2026-10-15"]["sleep"]
    assert sl["core"] == 420.0               # 只算一次


# ---------------------------------------------------------------- 运动记录


def test_workouts_mapped_and_translated(tmp_path):
    _make_repo(tmp_path, workouts=[
        ("id,start_datetime,end_datetime,active_duration_sec,distance_meters,"
         "energy_burned_kcal,hr_average_bpm,workout_type"),
        ("w1", "2026-10-03 19:19:16", "2026-10-03 19:36:08",
         "1012.55", "936.16", "33.30", "103.73", "walking"),
        ("w2", "2026-10-13 18:01:06", "2026-10-13 20:05:01",
         "7435.36", "4997.00", "70.49", "79.43", "cycling"),
    ])
    days = load_healthsync(tmp_path)
    w = days["2026-10-03"]["workouts"][0]
    assert w["type"] == "步行"                # 类型翻译成中文
    assert w["start"] == "19:19"
    assert w["end"] == "19:36"
    assert w["duration_min"] == 16.9         # 秒 → 分钟
    assert w["calories"] == 33.3
    assert w["distance_km"] == 0.94
    assert w["avg_hr"] == 103.73
    assert days["2026-10-13"]["workouts"][0]["type"] == "骑行"


def test_workout_unknown_type_passthrough_and_dedup(tmp_path):
    _make_repo(tmp_path, workouts=[
        ("id,start_datetime,active_duration_sec,workout_type"),
        ("w1", "2026-10-13 20:05:21", "877.68", "traditionalStrengthTraining"),
        ("w2", "2026-10-13 21:00:00", "600", "underwaterBasketweaving"),
        ("w2", "2026-10-13 21:00:00", "600", "underwaterBasketweaving"),
    ])
    ws = load_healthsync(tmp_path)["2026-10-13"]["workouts"]
    assert len(ws) == 2                       # 重复 id 只留一条
    assert ws[0]["type"] == "力量训练"
    assert ws[1]["type"] == "underwaterBasketweaving"   # 认不出的原样保留


# ---------------------------------------------------------------- 入口与优先级


def test_load_healthsync_missing_dir(tmp_path):
    assert load_healthsync(None) == {}
    assert load_healthsync(tmp_path / "不存在") == {}


def test_healthsync_replaces_whole_day(tmp_path):
    """同一天 healthsync 整天覆盖旧来源，不允许字段级拼接出混合口径。"""
    shortcut = tmp_path / "sc"
    shortcut.mkdir()
    (shortcut / "health_2026-10-15.txt").write_text(json.dumps({
        "date": "2026-10-15",
        "steps": 111,
        "heart_rate": [{"t": "08:00", "v": 60}],
    }, ensure_ascii=False), encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo, daily=[
        "date,step_count",
        "2026-10-15,999",
    ])

    cfg = Config(shortcut_dir=shortcut, output_dir=tmp_path / "out", healthsync_dir=repo)
    series, _export, _shortcut, healthsync = _load_series(cfg)
    assert len(healthsync) == 1
    dd = series["2026-10-15"]
    assert dd["steps"] == 999.0
    assert "hr_points" not in dd              # 旧来源的字段不允许残留
    assert "sleep_asleep_h" not in dd         # 没有睡眠数据就是没有，不从旧来源补
