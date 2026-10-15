"""运动记录：解析归一 / 汇总 / 给 AI 的渲染。"""

import json

from healthpipe import context, metrics, mcp_server, sources


# --------------------------------------------------------------------- 解析归一


def test_norm_workouts_normalises_fields_and_source():
    raw = [{"type": " 跑步 ", "start": "18:32 ", "end": "19:05", "duration_min": "33.2",
            "calories": "320.5", "distance_km": 5.12}]
    out = sources._norm_workouts(raw, "shortcut")
    assert out[0]["type"] == "跑步"
    assert out[0]["start"] == "18:32"
    assert out[0]["duration_min"] == 33.2          # 字符串转成了数字
    assert out[0]["calories"] == 320.5
    assert out[0]["source"] == "shortcut"


def test_norm_workouts_accepts_workout_type_alias():
    out = sources._norm_workouts([{"workout_type": "swimming", "duration_min": 30}], "x")
    assert out[0]["type"] == "swimming"


def test_norm_workouts_drops_empty_entries():
    raw = [{"type": "", "duration_min": None}, {"type": "跑步", "duration_min": 20}, "垃圾"]
    out = sources._norm_workouts(raw, "shortcut")
    assert len(out) == 1 and out[0]["type"] == "跑步"


def test_load_shortcut_reads_workouts(tmp_path):
    payload = {
        "date": "2026-10-12",
        "steps": 5000,
        "workouts": [
            {"type": "跑步", "start": "18:30", "end": "19:04",
             "duration_min": 34.0, "calories": 350.0, "distance_km": 5.2,
             "hr": {"v": 148}},
        ],
    }
    # 手工制造两类损坏（数字值后多余引号 / 尾随逗号），走的还是容错解析那条路
    raw = json.dumps(payload, ensure_ascii=False)
    raw = raw.replace('"v": 148', '"v": 148 "')
    raw = raw.replace("}]}", "},]}")
    (tmp_path / "health_2026-10-12.txt").write_text(raw, encoding="utf-8")

    days = sources.load_shortcut(tmp_path)
    ws = days["2026-10-12"]["workouts"]
    assert len(ws) == 1
    assert ws[0]["type"] == "跑步"
    assert ws[0]["source"] == "shortcut"
    assert ws[0]["duration_min"] == 34.0


def test_load_shortcut_without_workouts_leaves_key_absent(tmp_path):
    (tmp_path / "health_2026-10-12.txt").write_text(
        json.dumps({"date": "2026-10-12", "steps": 5000}), encoding="utf-8")
    assert "workouts" not in sources.load_shortcut(tmp_path)["2026-10-12"]


# --------------------------------------------------------------------- 汇总


def test_workout_summary_aggregates():
    dd = {"workouts": [
        {"type": "跑步", "duration_min": 30, "calories": 300, "distance_km": 5.0},
        {"type": "步行", "duration_min": 20, "calories": 60, "distance_km": 1.5},
    ]}
    s = metrics.workout_summary(dd)
    assert s["n"] == 2
    assert s["duration_min"] == 50.0
    assert s["calories"] == 360
    assert s["distance_km"] == 6.5
    assert s["types"] == ["步行", "跑步"]


def test_workout_summary_on_empty_day():
    s = metrics.workout_summary({})
    assert s == {"n": 0, "duration_min": None, "calories": None,
                 "distance_km": None, "types": []}


def test_workout_summary_tolerates_missing_numbers():
    s = metrics.workout_summary({"workouts": [{"type": "拉伸"}]})
    assert s["n"] == 1 and s["duration_min"] is None and s["types"] == ["拉伸"]


def test_workout_summary_skips_non_numeric():
    s = metrics.workout_summary({"workouts": [{"duration_min": "abc"}, {"duration_min": 10}]})
    assert s["duration_min"] == 10.0


# --------------------------------------------------------------------- 渲染


def _series():
    return {
        "2026-10-11": {"steps": 6000},
        "2026-10-12": {
            "steps": 9000,
            "workouts": [{"type": "跑步", "start": "18:30", "end": "19:04",
                          "duration_min": 34.0, "calories": 350.0,
                          "distance_km": 5.2, "avg_hr": 148.0}],
        },
    }


def test_workout_line_formats_all_fields():
    line = context.workout_line(_series()["2026-10-12"]["workouts"][0])
    assert line.startswith("跑步 18:30→19:04")
    assert "34 分钟" in line and "350 kcal" in line and "5.20 km" in line


def test_render_context_includes_workout_section():
    text = context.render_context(_series(), days=7)
    assert "## 运动记录（近 2 天）" in text
    assert "跑步 18:30→19:04" in text
    assert "**合计** 1 次" in text


def test_render_context_says_none_when_no_workouts():
    text = context.render_context({"2026-10-11": {"steps": 6000}}, days=7)
    assert "本区间没有运动记录" in text


def test_render_daily_includes_workouts():
    text = context.render_daily(_series())
    assert "运动记录：" in text and "跑步" in text


def test_render_daily_omits_section_without_workouts():
    assert "运动记录：" not in context.render_daily(_series(), "2026-10-11")


# --------------------------------------------------------------------- MCP


class _Store:
    def __init__(self, series):
        self._s = series

    def series(self):
        return self._s


def test_mcp_health_workouts_lists_entries():
    out = mcp_server._dispatch("tools/call", {"name": "health_workouts",
                                              "arguments": {"days": 30}},
                               _Store(_series()), {})
    text = out["content"][0]["text"]
    assert "跑步 18:30→19:04" in text
    assert "**合计** 1 次" in text


def test_mcp_health_workouts_hints_when_empty():
    out = mcp_server._dispatch("tools/call", {"name": "health_workouts", "arguments": {}},
                               _Store({"2026-10-11": {"steps": 1}}), {})
    text = out["content"][0]["text"]
    assert "本区间没有运动记录" in text
    assert "health-sync-data" in text     # 提示是采集端的问题，方便排查


# --------------------------------------------------------------------- 脱敏


def test_anonymize_scales_workouts_and_summary_stays_consistent():
    series = {"2026-10-12": {"workouts": [
        {"type": "跑步", "duration_min": 34.0, "calories": 350.0, "distance_km": 5.2},
    ]}}
    before = metrics.workout_summary(series["2026-10-12"])
    after = metrics.workout_summary(metrics.anonymize(series, seed=3)["2026-10-12"])
    assert after["duration_min"] != before["duration_min"]
    assert after["calories"] != before["calories"]
    assert after["types"] == ["跑步"]        # 类型是标签，保留
