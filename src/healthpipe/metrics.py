"""派生指标、汇总统计、数据质量守门、脱敏。"""

from __future__ import annotations

import random

SLEEP_TYPES = ("Deep", "Core", "REM", "Awake")


def hm(t: str) -> int:
    """``"HH:MM"`` → 距零点的分钟数。"""
    h, m = str(t).strip().split(":")
    return int(h) * 60 + int(m)


def minute_of_day(t: str) -> int:
    """同 hm，语义化别名。"""
    return hm(t)


def summarize_sleep(segments: list[dict]) -> dict:
    """把睡眠分段 [{start,end,type}] 聚合成各分期分钟数。"""
    agg: dict[str, float] = {}
    for s in segments:
        k = str(s.get("type", "")).strip()
        a, b = hm(s["start"]), hm(s["end"])
        if b <= a:                      # 跨零点
            b += 1440
        agg[k] = agg.get(k, 0) + (b - a)
    return {
        "deep": agg.get("Deep"),
        "core": agg.get("Core"),
        "rem": agg.get("REM"),
        "awake": agg.get("Awake"),
        "bed_start": str(segments[0].get("start", "")).strip(),
        "bed_end": str(segments[-1].get("end", "")).strip(),
    }


def deep_pct(dd: dict):
    """深睡占实睡（deep+core+rem）的比例，%。"""
    sl = dd.get("sleep") or {}
    total = sum(sl.get(k) or 0 for k in ("deep", "core", "rem"))
    if total and sl.get("deep") is not None:
        return round(sl["deep"] / total * 100, 1)
    return None


def qc_flags(dd: dict) -> list[str]:
    """数据质量守门：标记不可信 / 需人工判读的日子。只标注，不删数据。"""
    flags: list[str] = []
    inbed = dd.get("sleep_inbed_h")
    asleep = dd.get("sleep_asleep_h")

    if isinstance(inbed, (int, float)) and inbed < 1.5:
        flags.append("在床不足 1.5h，疑似未佩戴手表")
    elif isinstance(asleep, (int, float)) and asleep < 3:
        flags.append("睡眠不足 3h")

    steps = dd.get("steps")
    if isinstance(steps, (int, float)) and steps >= 18000:
        flags.append("步数 ≥18000，疑似户外长距离活动日")

    return flags


def enrich(series: dict[str, dict]) -> dict[str, dict]:
    """补派生字段：实睡时长、睡眠效率、数据质量标记。"""
    for dd in series.values():
        sl = dd.get("sleep")
        if sl:
            asleep = sum(sl.get(k) or 0 for k in ("deep", "core", "rem"))
            inbed = asleep + (sl.get("awake") or 0)
            dd["sleep_asleep_h"] = round(asleep / 60, 2) if asleep else None
            dd["sleep_inbed_h"] = round(inbed / 60, 2) if inbed else None
            dd["sleep_efficiency"] = round(asleep / inbed * 100, 1) if inbed else None
        dd["qc"] = qc_flags(dd)
    return series


def stat_of(series: dict[str, dict], key: str) -> dict:
    """均值 + 样本数（样本太少时前端不显示对比，避免误导）。"""
    vals = [dd[key] for dd in series.values() if isinstance(dd.get(key), (int, float))]
    if not vals:
        return {"mean": None, "n": 0}
    return {"mean": round(sum(vals) / len(vals), 1), "n": len(vals)}


# 需要按比例缩放的字段（保趋势形态，抹绝对值）
_SCALE_KEYS = (
    "steps", "distance_km", "active_kcal", "basal_kcal", "exercise_min",
    "sleep_asleep_h", "sleep_inbed_h", "hrv_ms",
)
# 需要加性扰动的字段（心率类，缩放意义不大）
_OFFSET_KEYS = ("hr_avg", "hr_resting")


def _shifted_factor(rnd: random.Random) -> float:
    """生成一个明显偏离 1.0 的缩放因子。

    如果因子落在 1.0 附近，脱敏后数值和真值几乎一样，等于没脱敏 —— 所以显式避开。
    """
    while True:
        f = rnd.uniform(0.45, 1.65)
        if not (0.85 <= f <= 1.18):
            return f


def anonymize(series: dict[str, dict], seed: int = 20261011) -> dict[str, dict]:
    """生成对外公开用的脱敏数据：每个指标一个全局因子 + 每日小幅抖动。

    日期保持不变；原始 ``hr_points`` / ``sleep_segments`` 直接丢弃（点太密，
    缩放后仍可能被反推）。
    """
    rnd = random.Random(seed)
    scale = {k: _shifted_factor(rnd) for k in _SCALE_KEYS}

    out: dict[str, dict] = {}
    for date, dd in series.items():
        nd = dict(dd)
        nd.pop("hr_points", None)
        nd.pop("sleep_segments", None)

        for k in _SCALE_KEYS:
            if isinstance(nd.get(k), (int, float)):
                nd[k] = round(nd[k] * scale[k] * rnd.uniform(0.95, 1.05), 2)

        for k in _OFFSET_KEYS:
            if isinstance(nd.get(k), (int, float)):
                nd[k] = round(nd[k] + rnd.uniform(-6, 6), 1)

        sl = nd.get("sleep")
        if isinstance(sl, dict):
            nd["sleep"] = {
                k: (round(v * scale["sleep_asleep_h"]) if isinstance(v, (int, float)) else v)
                for k, v in sl.items()
            }

        out[date] = nd
    return out
