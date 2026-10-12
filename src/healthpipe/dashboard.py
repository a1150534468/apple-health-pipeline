"""生成单文件 HTML 仪表盘。

产物特点：ECharts 内联进 HTML，输出是一个**脱离本地依赖也能打开**的独立文件，
可以直接发给别人或放到静态托管上。
"""

from __future__ import annotations

import json
from datetime import datetime
from importlib import resources
from pathlib import Path

from . import metrics

# 模板里的两个占位符（见 data/dashboard.html）
DATA_PLACEHOLDER = "/*__DATA__*/null"
ECHARTS_PLACEHOLDER = "/*__ECHARTS__*/"

BASELINE_KEYS = (
    "steps", "active_kcal", "hr_avg", "hr_max", "hr_resting",
    "sleep_asleep_h", "sleep_efficiency", "hrv_ms", "exercise_min",
)


def _read_asset(name: str) -> str:
    base = resources.files("healthpipe")
    return (base / "data" / name).read_text(encoding="utf-8")


def build_payload(series: dict[str, dict], meta: dict | None = None) -> dict:
    """把时序数据整理成前端需要的形状。"""
    dates = sorted(series)
    latest = dates[-1] if dates else None
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "generator": "healthpipe",
        "date_range": [dates[0], latest] if dates else [],
        "sources": meta or {},
        "baseline": {k: metrics.stat_of(series, k) for k in BASELINE_KEYS},
        "qc_days": {d: dd["qc"] for d, dd in series.items() if dd.get("qc")},
        "latest_date": latest,
        "latest": series.get(latest, {}) if latest else {},
        "series": series,
    }


def render(payload: dict, out_path: str | Path) -> Path:
    """把 payload 灌进模板，写出单文件 HTML。"""
    tpl = _read_asset("dashboard.html")
    echarts = _read_asset("echarts.min.js")

    # 先内联图表库，再灌数据（顺序无所谓，但保持可读）
    html = tpl.replace(ECHARTS_PLACEHOLDER, echarts)
    html = html.replace(DATA_PLACEHOLDER, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def build(series: dict[str, dict], out_path: str | Path, meta: dict | None = None) -> Path:
    return render(build_payload(series, meta), out_path)
