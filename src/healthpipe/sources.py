"""数据源适配层。

把不同来源统一成同一个中间结构：``{date: {...metrics}}``。

目前支持两个来源：
  - shortcut   —— iPhone 快捷指令导出（坏 JSON，走 repair 容错）
  - healthexport —— 第三方 App（如 HealthExport）导出（合法 JSON）

同一日期，后加载的覆盖先加载的。
"""

from __future__ import annotations

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


def merge(*sources: dict[str, dict] | None) -> dict[str, dict]:
    """按顺序合并，后者的同日期字段覆盖前者。"""
    out: dict[str, dict] = {}
    for src in sources:
        if not src:
            continue
        for date, dd in src.items():
            out.setdefault(date, {}).update(dd)
    return out
