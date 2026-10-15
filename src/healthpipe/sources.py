"""数据源适配层。

把不同来源统一成同一个中间结构：``{date: {...metrics}}``。

支持三个来源：
  - shortcut    —— iPhone 快捷指令导出（坏 JSON，走 repair 容错）
  - healthexport —— 第三方 App（如 HealthExport）导出（合法 JSON）
  - healthsync  —— health-sync-data 仓库（iPhone 定时推到 GitHub 的 CSV 镜像）

合并规则：healthexport / shortcut 之间按字段合并，后加载的覆盖先加载的；
**healthsync 是权威源，同一日期整天替换**（它的采集端最完整，
避免和旧来源的同名字段拼接出混合口径的一天）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from . import repair
from .metrics import as_num, hm, summarize_sleep


def _norm_workouts(raw, default_source: str) -> list[dict]:
    """把不同来源的运动记录归一成同一个形状。

    统一后的字段：
      ``type``（运动类型，如 running / swimming / 跑步）、``start``/``end``（HH:MM）、
      ``duration_min``、``calories``、``distance_km``、``avg_hr``、``source``
    """
    out: list[dict] = []
    for w in raw or []:
        if not isinstance(w, dict):
            continue
        item = {
            "type": str(w.get("type") or w.get("workout_type") or "").strip(),
            "start": str(w.get("start") or "").strip(),
            "end": str(w.get("end") or "").strip(),
            "duration_min": as_num(w.get("duration_min")),
            "calories": as_num(w.get("calories")),
            "distance_km": as_num(w.get("distance_km")),
            "avg_hr": as_num(w.get("avg_hr")),
            "source": str(w.get("source") or default_source).strip(),
        }
        # 一个字段都没有的条目直接丢掉，别在数据里留空壳
        if any(item[k] not in (None, "") for k in
               ("type", "duration_min", "calories", "distance_km")):
            out.append(item)
    return out


def load_healthexport(dirpath: str | Path | None) -> dict[str, dict]:
    """读取 App 导出的 JSON（initial + incremental 会按日期自动合并）。"""
    days: dict[str, dict] = {}
    if not dirpath:
        return days
    root = Path(dirpath)
    if not root.exists():
        return days

    for f in sorted(root.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        metrics = doc.get("metrics") or {}

        for it in metrics.get("steps") or []:
            days.setdefault(it["date"], {})["steps"] = it.get("value")
        for it in metrics.get("active_calories") or []:
            days.setdefault(it["date"], {})["active_kcal"] = it.get("value")
        for it in metrics.get("heart_rate") or []:
            dd = days.setdefault(it["date"], {})
            dd["hr_avg"] = it.get("average_bpm")
            dd["hr_max"] = it.get("max_bpm")
            if it.get("resting_bpm"):
                dd["hr_resting"] = it["resting_bpm"]
        for it in metrics.get("sleep") or []:
            st = it.get("stages") or {}
            days.setdefault(it["date"], {})["sleep"] = {
                "deep": st.get("deep_min"),
                "core": st.get("core_min"),
                "rem": st.get("rem_min"),
                "awake": st.get("awake_min"),
            }
        for it in metrics.get("workouts") or []:
            ws = _norm_workouts([it], "healthexport")
            if ws:
                days.setdefault(it["date"], {}).setdefault("workouts", []).extend(ws)

    for dd in days.values():
        dd.setdefault("_source", "healthexport")
    return days


def load_shortcut(dirpath: str | Path) -> dict[str, dict]:
    """读取快捷指令导出目录下的全部 *.txt（内容其实是坏 JSON）。"""
    days: dict[str, dict] = {}
    root = Path(dirpath)
    if not root.exists():
        return days

    for f in sorted(root.glob("*.txt")):
        try:
            obj, _fixes = repair.load_file(f)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        date = obj.get("date")
        if not date:
            continue

        dd = days.setdefault(date, {})
        dd["_source"] = "shortcut"
        dd["steps"] = obj.get("steps")
        dd["distance_km"] = obj.get("distance_km")
        dd["active_kcal"] = obj.get("active_energy_kcal")
        dd["basal_kcal"] = obj.get("basal_energy_kcal")
        dd["exercise_min"] = obj.get("exercise_min")
        dd["hrv_ms"] = obj.get("hrv_ms")
        dd["hr_resting"] = obj.get("resting_hr")

        hr = obj.get("heart_rate") or []
        if hr:
            pts = [[str(x.get("t", "")).strip(), float(x["v"])] for x in hr]
            vals = [v for _t, v in pts]
            dd["hr_points"] = pts
            dd["hr_avg"] = round(sum(vals) / len(vals), 1)
            dd["hr_max"] = max(vals)
            dd["hr_min"] = min(vals)
            dd["captured_at"] = pts[-1][0]

        segs = obj.get("sleep") or []
        if segs:
            dd["sleep"] = summarize_sleep(segs)
            dd["sleep_segments"] = [
                {
                    "start": str(s.get("start", "")).strip(),
                    "end": str(s.get("end", "")).strip(),
                    "type": str(s.get("type", "")).strip(),
                }
                for s in segs
            ]

        ws = _norm_workouts(obj.get("workouts"), "shortcut")
        if ws:
            dd["workouts"] = ws

    return days


# ---------------------------------------------------------------- healthsync
# iPhone 端定时把 HealthKit 导成 3 个 CSV 推到 GitHub 私有仓库，Mac 端 git pull 即可。
# 字段是 HealthKit 类型名去掉前缀的 lowerCamelCase（如 apple_exercise_time_sum）。


# muse 导出的 workout_type 是 HealthKit 类型名去掉 HKWorkoutActivityType 前缀的
# lowerCamelCase。翻译成中文；认不出的原样保留（Mac 端本来就原样显示）。
_WORKOUT_TYPES_ZH = {
    "walking": "步行",
    "running": "跑步",
    "cycling": "骑行",
    "swimming": "游泳",
    "hiking": "徒步",
    "yoga": "瑜伽",
    "pilates": "普拉提",
    "hiit": "高强度间歇",
    "highintensityintervaltraining": "高强度间歇",
    "traditionalstrengthtraining": "力量训练",
    "functionalstrengthtraining": "功能性力量训练",
    "coretraining": "核心训练",
    "elliptical": "椭圆机",
    "rowing": "划船",
    "stairclimbing": "爬楼",
    "treadmill": "跑步机",
    "dance": "舞蹈",
    "kickboxing": "搏击操",
}

# 每日指标里参与「空天判定」的键：全是 None 就丢掉这一天
_DAILY_KEYS = (
    "steps", "distance_km", "active_kcal", "basal_kcal", "exercise_min",
    "hrv_ms", "hr_resting", "hr_avg", "hr_max", "hr_min",
    "spo2_avg", "resp_rate", "stand_min", "flights",
)


def _read_csv(path: Path) -> list[dict]:
    """读 CSV 成 list[dict]；文件不存在返回空表。"""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _cell(row: dict, key: str):
    """取单元格：去空白，空串归一成 None。"""
    v = row.get(key)
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _hhmm(dt: str) -> str:
    """``"2026-10-04 01:27:01"`` → ``"01:27"``。"""
    t = str(dt).strip()
    return t[11:16] if len(t) >= 16 else t


def _to_min(dt: str) -> int:
    """datetime 字符串 → 当天 0 点起的分钟数。"""
    t = _hhmm(dt)
    h, _, m = t.partition(":")
    return int(h) * 60 + int(m or 0)


def _from_min(m: int) -> str:
    """分钟数 → ``HH:MM``（超过 24h 取模回绕）。"""
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _load_healthsync_daily(path: Path) -> dict[str, dict]:
    """daily_metrics.csv：每天一行，直接映射到内部字段（含单位换算）。"""
    days: dict[str, dict] = {}
    for row in _read_csv(path):
        date = _cell(row, "date")
        if not date:
            continue
        dd = days.setdefault(date, {"_source": "healthsync"})
        dd["steps"] = as_num(row.get("step_count"))
        meters = as_num(row.get("distance_walking_running_meters"))
        dd["distance_km"] = round(meters / 1000, 2) if meters is not None else None
        dd["active_kcal"] = as_num(row.get("active_energy_burned_kcal"))
        dd["basal_kcal"] = as_num(row.get("basal_energy_burned_kcal"))
        dd["exercise_min"] = as_num(row.get("apple_exercise_time_sum"))
        dd["hrv_ms"] = as_num(row.get("heart_rate_variability_ms"))
        rhr = as_num(row.get("resting_hr_average_bpm"))
        if rhr is None:
            rhr = as_num(row.get("resting_heart_rate_min"))
        dd["hr_resting"] = rhr
        dd["hr_avg"] = as_num(row.get("hr_average_bpm"))
        dd["hr_max"] = as_num(row.get("hr_max_bpm"))
        dd["hr_min"] = as_num(row.get("heart_rate_min"))
        spo2 = as_num(row.get("oxygen_saturation_average"))
        # HealthKit 存小数（0.98 = 98%），统一换算成百分数
        dd["spo2_avg"] = round(spo2 * 100, 1) if spo2 is not None else None
        rr = as_num(row.get("respiratory_rate_average"))
        dd["resp_rate"] = round(rr, 1) if rr is not None else None
        dd["stand_min"] = as_num(row.get("apple_stand_time_sum"))
        dd["flights"] = as_num(row.get("flights_climbed"))
    return days


# 睡眠分段的合成顺序。muse 只有各分期的总时长，没有每段的时间戳，
# 所以段内布局是按这个顺序顺次铺出来的 —— **只有总时长可信**，
# 段与段的先后不代表 Apple 原始分期顺序。
_STAGE_ORDER = (("deep", "Deep"), ("core", "Core"), ("rem", "REM"), ("awake", "Awake"))


def _load_healthsync_sleep(path: Path, days: dict[str, dict]) -> None:
    """sleep_sessions.csv：一次睡眠一行（含午睡），归属到「醒来那天」。"""
    seen: set[str] = set()
    sessions: dict[str, list[dict]] = {}
    for row in _read_csv(path):
        sid = _cell(row, "id")
        if not sid or sid in seen:            # 按 id 去重，防重复行
            continue
        seen.add(sid)
        start, end = _cell(row, "start_datetime"), _cell(row, "end_datetime")
        if not start or not end:
            continue
        date = end[:10]
        sessions.setdefault(date, []).append({
            "start": start,
            "end": end,
            "deep": (as_num(row.get("sleep_deep_duration_sec")) or 0) / 60,
            "core": (as_num(row.get("sleep_core_duration_sec")) or 0) / 60,
            "rem": (as_num(row.get("sleep_rem_duration_sec")) or 0) / 60,
            "awake": (as_num(row.get("sleep_awake_duration_sec")) or 0) / 60,
            # Apple 的「未分期睡眠」（午睡等）归进 core：总时长不变，只是不再细分
            "unspec": (as_num(row.get("sleep_asleep_unspecified_duration_sec")) or 0) / 60,
        })

    for date in sorted(sessions):
        ss = sorted(sessions[date], key=lambda s: s["start"])
        agg = {k: 0.0 for k, _ in _STAGE_ORDER}
        segs: list[dict] = []
        for s in ss:
            agg["deep"] += s["deep"]
            agg["core"] += s["core"] + s["unspec"]
            agg["rem"] += s["rem"]
            agg["awake"] += s["awake"]
            cursor = _to_min(s["start"])
            for key, label in _STAGE_ORDER:
                mins = s[key] if key != "core" else s["core"] + s["unspec"]
                add = int(round(mins))
                if add < 1:                   # 不足 1 分钟的段不铺，避免产生零长度段
                    continue
                segs.append({"start": _from_min(cursor),
                             "end": _from_min(cursor + add),
                             "type": label})
                cursor += add
        dd = days.setdefault(date, {"_source": "healthsync"})
        dd["sleep"] = {
            "deep": round(agg["deep"], 1),
            "core": round(agg["core"], 1),
            "rem": round(agg["rem"], 1),
            "awake": round(agg["awake"], 1),
            "bed_start": _hhmm(ss[0]["start"]),
            "bed_end": _hhmm(ss[-1]["end"]),
        }
        dd["sleep_segments"] = segs


def _load_healthsync_workouts(path: Path, days: dict[str, dict]) -> None:
    """workout_sessions.csv：一次运动一行，归属到「开始那天」。"""
    seen: set[str] = set()
    raw: dict[str, list[dict]] = {}
    for row in _read_csv(path):
        sid = _cell(row, "id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        start, end = _cell(row, "start_datetime"), _cell(row, "end_datetime")
        if not start:
            continue
        dur = as_num(row.get("active_duration_sec"))
        dist = as_num(row.get("distance_meters"))
        wt = _cell(row, "workout_type") or ""
        raw.setdefault(start[:10], []).append({
            "type": _WORKOUT_TYPES_ZH.get(wt.lower(), wt),
            "start": _hhmm(start),
            "end": _hhmm(end or "") if end else "",
            "duration_min": round(dur / 60, 1) if dur is not None else None,
            "calories": as_num(row.get("energy_burned_kcal")),
            "distance_km": round(dist / 1000, 2) if dist is not None else None,
            "avg_hr": as_num(row.get("hr_average_bpm")),
        })

    for date, ws in raw.items():
        norm = _norm_workouts(sorted(ws, key=lambda w: w["start"]), "healthsync")
        if norm:
            days.setdefault(date, {"_source": "healthsync"})["workouts"] = norm


def load_healthsync(dirpath: str | Path | None) -> dict[str, dict]:
    """读取 health-sync-data 仓库（muse 推到 GitHub 的每日 CSV 镜像）。"""
    if not dirpath:
        return {}
    root = Path(dirpath)
    if not root.exists():
        return {}

    days = _load_healthsync_daily(root / "daily_metrics.csv")
    _load_healthsync_sleep(root / "sleep_sessions.csv", days)
    _load_healthsync_workouts(root / "workout_sessions.csv", days)

    # 只剩一个日期键的空天直接丢掉
    return {d: dd for d, dd in days.items()
            if any(dd.get(k) is not None for k in _DAILY_KEYS)
            or "sleep" in dd or "workouts" in dd}


def merge(*sources: dict[str, dict] | None) -> dict[str, dict]:
    """按顺序合并，后者的同日期字段覆盖前者。"""
    out: dict[str, dict] = {}
    for src in sources:
        if not src:
            continue
        for date, dd in src.items():
            out.setdefault(date, {}).update(dd)
    return out
