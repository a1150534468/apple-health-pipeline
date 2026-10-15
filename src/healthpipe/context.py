"""把时序数据压成 LLM 直接能读的上下文。

「让 AI 托管健康数据」的核心就在这里：不要让模型自己去解析几十天 JSON，
而是先在本层算好「最新一天 + 趋势 + 异常」，输出一段紧凑的文本。

输出是 Markdown，人和模型都好读。
"""

from __future__ import annotations

from . import metrics

# (字段, 显示名, 小数位, 单位)
METRICS = [
    ("sleep_asleep_h", "睡眠（实睡）", 2, " h"),
    ("deep_pct", "深睡占比", 1, "%"),
    ("hrv_ms", "HRV (SDNN)", 1, " ms"),
    ("hr_resting", "静息心率", 0, " bpm"),
    ("steps", "步数", 0, ""),
    ("active_kcal", "活动消耗", 0, " kcal"),
    ("exercise_min", "运动时间", 0, " min"),
    ("distance_km", "步行距离", 2, " km"),
    ("spo2_avg", "血氧", 1, "%"),
    ("resp_rate", "呼吸率", 1, " 次/分"),
    ("stand_min", "站立时间", 0, " min"),
    ("flights", "爬楼", 0, " 层"),
]


def _value(dd: dict, key: str):
    if key == "deep_pct":
        return metrics.deep_pct(dd)
    return dd.get(key)


def _fmt(val, digits: int, unit: str = "", dash: str = "—") -> str:
    if not isinstance(val, (int, float)):
        return dash
    if digits == 0:
        return f"{int(round(val)):,}{unit}"
    return f"{val:.{digits}f}{unit}"


def _window_stats(series: dict[str, dict], dates: list[str], key: str) -> dict | None:
    vals = [v for d in dates if isinstance(v := _value(series[d], key), (int, float))]
    if not vals:
        return None
    return {
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
        "n": len(vals),
    }


def workout_line(w: dict) -> str:
    """把一条运动记录压成一行，例如「跑步 18:32→19:05 · 33 分钟 · 320 kcal · 5.12 km」。"""
    label = str(w.get("type") or "运动")
    if w.get("start") and w.get("end"):
        label += f" {w['start']}→{w['end']}"
    elif w.get("start"):
        label += f" {w['start']}"

    parts = [label]
    if isinstance(w.get("duration_min"), (int, float)):
        parts.append(f"{w['duration_min']:.0f} 分钟")
    if isinstance(w.get("calories"), (int, float)):
        parts.append(f"{w['calories']:.0f} kcal")
    if isinstance(w.get("distance_km"), (int, float)):
        parts.append(f"{w['distance_km']:.2f} km")
    if isinstance(w.get("avg_hr"), (int, float)):
        parts.append(f"平均心率 {w['avg_hr']:.0f} bpm")
    return " · ".join(parts)


def workout_totals(entries: list[tuple[str, dict]]) -> str:
    """把 ``[(日期, 运动记录), ...]`` 压成一行合计。"""
    if not entries:
        return ""
    mins = sum(w["duration_min"] for _d, w in entries
               if isinstance(w.get("duration_min"), (int, float)))
    kcals = sum(w["calories"] for _d, w in entries
                if isinstance(w.get("calories"), (int, float)))
    dist = sum(w["distance_km"] for _d, w in entries
               if isinstance(w.get("distance_km"), (int, float)))
    types = sorted({str(w.get("type") or "").strip() for _d, w in entries if w.get("type")})
    parts = [f"**合计** {len(entries)} 次"]
    if mins:
        parts.append(f"{mins:.0f} 分钟")
    if kcals:
        parts.append(f"{kcals:.0f} kcal")
    if dist:
        parts.append(f"{dist:.2f} km")
    if types:
        parts.append("类型：" + "、".join(types))
    return " · ".join(parts)


def render_context(series: dict[str, dict], days: int = 7, title: str = "健康数据上下文") -> str:
    """生成给 LLM 的摘要：最新一天明细 + N 天趋势 + 数据质量。"""
    dates = sorted(series)
    if not dates:
        return "（没有可用的健康数据）\n"

    window = dates[-days:]
    prev_window = dates[-2 * days:-days]           # 用于对比
    latest_date = window[-1]
    latest = series[latest_date]

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"数据区间：**{window[0]} → {latest_date}**（{len(window)} 条记录）")
    lines.append("")

    # ---- 最新一天 ----
    lines.append(f"## 最新一天 · {latest_date}")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    for key, label, digits, unit in METRICS:
        val = _value(latest, key)
        if val is None:
            continue
        lines.append(f"| {label} | {_fmt(val, digits, unit)} |")
    lines.append("")

    # ---- 趋势 ----
    lines.append(f"## 近 {len(window)} 天趋势")
    lines.append("")
    header = "| 指标 | 均值 | 范围 |"
    if prev_window:
        header += f" 对比前 {len(prev_window)} 天 |"
    lines.append(header)
    lines.append("|---|---|---|" + ("---|" if prev_window else ""))
    for key, label, digits, unit in METRICS:
        cur = _window_stats(series, window, key)
        if not cur:
            continue
        row = (f"| {label} | {_fmt(cur['mean'], digits, unit)} | "
               f"{_fmt(cur['min'], digits)}{unit} – {_fmt(cur['max'], digits)}{unit} |")
        if prev_window:
            prev = _window_stats(series, prev_window, key)
            if prev:
                delta = cur["mean"] - prev["mean"]
                sign = "+" if delta >= 0 else ""
                row += f" {sign}{_fmt(delta, digits, unit)} |"
            else:
                row += " — |"
        lines.append(row)
    lines.append("")

    # ---- 运动记录 ----
    lines.append(f"## 运动记录（近 {len(window)} 天）")
    lines.append("")
    entries = [(d, w) for d in window for w in (series[d].get("workouts") or [])]
    if entries:
        for d, w in reversed(entries):
            lines.append(f"- `{d}`　{workout_line(w)}")
        lines.append("")
        lines.append(workout_totals(entries))
    else:
        lines.append("- 本区间没有运动记录")
    lines.append("")

    # ---- 数据质量 ----
    qc = [(d, series[d]["qc"]) for d in window if series[d].get("qc")]
    lines.append("## 数据质量")
    lines.append("")
    if qc:
        for d, flags in qc:
            lines.append(f"- `{d}`：{'；'.join(flags)}")
    else:
        lines.append("- 本区间未发现异常样本")
    lines.append("")

    return "\n".join(lines)


def render_daily(series: dict[str, dict], date: str | None = None) -> str:
    """单日明细（供 MCP 的 health_daily 工具使用）。"""
    if not series:
        return "（没有可用的健康数据）"
    date = date or sorted(series)[-1]
    if date not in series:
        near = [d for d in sorted(series) if d <= date]
        if not near:
            return f"没有 {date} 及之前的数据"
        date = near[-1]

    dd = series[date]
    lines = [f"# {date}", ""]
    for key, label, digits, unit in METRICS:
        val = _value(dd, key)
        if val is not None:
            lines.append(f"- {label}：{_fmt(val, digits, unit)}")

    sl = dd.get("sleep") or {}
    if any(sl.get(k) is not None for k in ("deep", "core", "rem", "awake")):
        lines.append("")
        lines.append("睡眠分期（分钟）：")
        for k, name in (("deep", "深睡"), ("core", "核心"), ("rem", "REM"), ("awake", "清醒")):
            if sl.get(k) is not None:
                lines.append(f"- {name}：{sl[k]:.0f}")

    ws = dd.get("workouts") or []
    if ws:
        lines.append("")
        lines.append("运动记录：")
        for w in ws:
            lines.append(f"- {workout_line(w)}")

    if dd.get("qc"):
        lines.append("")
        lines.append("数据质量：" + "；".join(dd["qc"]))
    if dd.get("captured_at"):
        lines.append("")
        lines.append(f"采集时点：{dd['captured_at']}（累计型指标此时刻的值）")
    return "\n".join(lines)


def render_series(series: dict[str, dict], metric: str, days: int = 30) -> str:
    """单指标时序（供 MCP 的 health_series 工具使用）。"""
    known = {k for k, *_ in METRICS}
    if metric not in known:
        return f"未知指标 `{metric}`。可用：" + "、".join(sorted(known))
    labels = {k: label for k, label, *_ in METRICS}
    digits = {k: d for k, _l, d, _u in METRICS}
    unit = {k: u for k, _l, _d, u in METRICS}

    dates = sorted(series)[-days:]
    rows = []
    for d in dates:
        val = _value(series[d], metric)
        rows.append(f"{d},{_fmt(val, digits[metric]) if val is not None else ''}")
    header = f"# {labels[metric]}{unit[metric]} 时序（{dates[0]} → {dates[-1]}）\n\ndate,value"
    return header + "\n" + "\n".join(rows)


def render_fields(series: dict[str, dict], title: str = "数据字段一览") -> str:
    """列出时序里**实际存在**的全部字段和覆盖率（供 MCP 的 health_fields 工具使用）。

    动机：采集源一换字段就变（快捷指令 → health-sync → 以后还可能换），
    AI 应该能自己「发现」字段，而不是靠文档或代码里的硬编码清单。
    未进报表的原始字段（如 sleep_efficiency、hr_avg）在这里也能被看到，
    AI 可以直接用 health_daily / health_series 去查它们。
    """
    dates = sorted(series)
    if not dates:
        return "（没有可用的健康数据）"
    total = len(dates)
    known = {k: (label, digits, unit) for k, label, digits, unit in METRICS}

    # ---- 结构化字段（dict / list：睡眠分期、运动记录、分钟级心率……） ----
    struct_rows = []                                    # (key, 天数, 条数)
    struct_keys = sorted({k for dd in series.values() for k in dd
                          if isinstance(dd.get(k), (list, dict))})
    for key in struct_keys:
        days = sum(1 for d in dates if series[d].get(key))
        items = sum(len(series[d][key]) for d in dates if isinstance(series[d].get(key), list))
        struct_rows.append((key, days, items))

    # ---- 数值字段：METRICS 声明的（含派生） ∪ 数据里实际出现的 ----
    numeric_keys = [k for k, *_ in METRICS]
    numeric_keys += sorted({k for dd in series.values()
                            for k, v in dd.items() if isinstance(v, (int, float))
                            and k not in known})
    known_rows, raw_rows = [], []                       # (key, label, 天数, 最新有值日, 最新值)
    for key in numeric_keys:
        have = [(d, v) for d in dates
                if isinstance(v := _value(series[d], key), (int, float))]
        label, digits, unit = known.get(key, (key, 1, ""))
        if not have:
            if key in known:
                known_rows.append((key, label, 0, "—", "—"))
            continue
        latest_d, latest_v = have[-1]
        if key not in known:
            digits = 1 if isinstance(latest_v, float) else 0
        entry = (key, label, len(have), latest_d, _fmt(latest_v, digits, unit))
        (known_rows if key in known else raw_rows).append(entry)

    # ---- 字符串元数据（captured_at 之类） ----
    meta_rows = []                                      # (key, 天数)
    for key in sorted({k for dd in series.values() for k, v in dd.items()
                       if isinstance(v, str) and not k.startswith("_")}):
        meta_rows.append((key, sum(1 for d in dates if series[d].get(key))))

    def _table(rows):
        out = ["| 字段 | 名称 | 有值天数 | 最新有值日 | 最新值 |", "|---|---|---|---|---|"]
        for key, label, n, latest_d, latest_v in rows:
            cov = f"{n / total * 100:.0f}%" if n else "0%"
            out.append(f"| `{key}` | {label} | {n}（{cov}） | {latest_d} | {latest_v} |")
        return out

    lines = [f"# {title}", "",
             f"数据区间：**{dates[0]} → {dates[-1]}**（{total} 天）。"
             "查数值用 `health_series` / `health_daily`；这里回答「有哪些字段、覆盖几天」。", ""]

    lines.append("## 报表指标（进 overview / daily / series）")
    lines.append("")
    lines += _table(known_rows)
    lines.append("")

    if raw_rows:
        lines.append("## 原始字段（有数据但没进报表，AI 可直接使用）")
        lines.append("")
        lines += _table(raw_rows)
        lines.append("")

    if struct_rows:
        lines.append("## 结构化数据")
        lines.append("")
        for key, days, items in struct_rows:
            extra = f"，共 {items} 条" if items else ""
            lines.append(f"- `{key}`：{days} 天有{extra}")
        lines.append("")

    if meta_rows:
        lines.append("## 元数据")
        lines.append("")
        for key, n in meta_rows:
            lines.append(f"- `{key}`：{n} 天有")
        lines.append("")

    return "\n".join(lines)
