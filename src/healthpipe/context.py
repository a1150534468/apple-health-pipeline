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
