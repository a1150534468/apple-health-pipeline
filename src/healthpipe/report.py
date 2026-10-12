"""生成 Markdown 汇总表。"""

from __future__ import annotations

from pathlib import Path

HEADER = """# 健康记录

> 由 healthpipe 自动生成，请勿手动修改表头。

## 每日明细

| 日期 | 睡眠(h) | 深睡% | HRV(ms) | 静息心率 | 步数 | 运动(min) | 活动消耗 | 备注 |
|---|---|---|---|---|---|---|---|---|"""


def _fmt(v, digits: int = 0, dash: str = "—") -> str:
    if isinstance(v, (int, float)):
        return f"{v:.{digits}f}"
    return dash


def _deep_pct(dd: dict):
    sl = dd.get("sleep") or {}
    total = sum(sl.get(k) or 0 for k in ("deep", "core", "rem"))
    if total and sl.get("deep") is not None:
        return round(sl["deep"] / total * 100, 1)
    return None


def render_report(series: dict[str, dict], days: int | None = None) -> str:
    """按日期升序生成每日明细表。"""
    dates = sorted(series)
    if days:
        dates = dates[-days:]

    lines = [HEADER]
    for d in dates:
        dd = series[d]
        note = "；".join(dd.get("qc") or []) or "—"
        lines.append(
            "| {date} | {sleep} | {deep} | {hrv} | {rhr} | {steps} | {ex} | {act} | {note} |".format(
                date=d,
                sleep=_fmt(dd.get("sleep_asleep_h"), 2),
                deep=_fmt(_deep_pct(dd), 1),
                hrv=_fmt(dd.get("hrv_ms"), 1),
                rhr=_fmt(dd.get("hr_resting"), 0),
                steps=_fmt(dd.get("steps"), 0),
                ex=_fmt(dd.get("exercise_min"), 0),
                act=_fmt(dd.get("active_kcal"), 0),
                note=note,
            )
        )
    return "\n".join(lines) + "\n"


def write_report(series: dict[str, dict], out_path: str | Path, days: int | None = None) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(series, days), encoding="utf-8")
    return out
