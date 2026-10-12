"""生成 examples/ 里的公开 demo 数据。

**全部是合成数据**，不含任何真实健康数据。
用真实数据脱敏（`config.toml` 里的 `[privacy] anonymize`）也能出一份，
但脱敏会丢掉密集的 `hr_points` / `sleep_segments`（点太密，缩放后仍可能被反推），
那两张图就会空着。公开 demo 直接用合成数据更干净，图也满。

用法：

    python examples/build_demo.py
"""

from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

from healthpipe import dashboard, metrics

SEED = 20261011
DAYS = 31
END = date(2026, 10, 11)
OUT = Path(__file__).resolve().parent


def _hhmm(minutes: int) -> str:
    minutes %= 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _split(rnd: random.Random, total: float, n: int) -> list[float]:
    """把 total 随机切成 n 份。"""
    if total <= 0 or n <= 0:
        return []
    cuts = sorted(rnd.uniform(0.15, 0.85) for _ in range(n - 1))
    pts = [0.0, *[c * total for c in cuts], float(total)]
    return [pts[i + 1] - pts[i] for i in range(n)]


def _sleep_stages(rnd: random.Random, deep: float, core: float,
                  rem: float, awake: float) -> list[dict]:
    """按"深睡偏前半夜、REM 偏后半夜"的规律排一宿的分期。"""
    pool: list[tuple[float, str, float]] = []          # (位置 0~1, 类型, 分钟)
    for m in _split(rnd, deep, 2):
        pool.append((rnd.uniform(0.0, 0.55), "Deep", m))
    for m in _split(rnd, rem, 3):
        pool.append((rnd.uniform(0.35, 1.0), "REM", m))
    for m in _split(rnd, core, 4):
        pool.append((rnd.uniform(0.0, 1.0), "Core", m))
    for m in _split(rnd, awake, 2):
        pool.append((rnd.uniform(0.1, 0.95), "Awake", m))
    pool.sort(key=lambda x: x[0])

    segments, cursor = [], 23 * 60 + rnd.randint(-40, 40)   # 约 23:00 入睡
    for _pos, kind, minutes in pool:
        minutes = max(1, round(minutes))
        segments.append({"start": _hhmm(cursor), "end": _hhmm(cursor + minutes), "type": kind})
        cursor += minutes
    return segments


def _hr_points(rnd: random.Random) -> list[list]:
    """一天从 08:00 到 23:00、每 5 分钟一个点的合成心率。"""
    pts = []
    trained = rnd.random() < 0.7
    for m in range(8 * 60, 23 * 60 + 1, 5):
        base = 66 + 11 * math.sin((m - 8 * 60) / 900 * math.pi)
        if trained and 18 * 60 <= m <= 19 * 60:
            base += rnd.uniform(35, 55)                     # 傍晚一次运动
        v = base + rnd.gauss(0, 3.5)
        pts.append([_hhmm(m), round(max(48.0, min(168.0, v)), 1)])
    return pts


def build_demo() -> dict[str, dict]:
    rnd = random.Random(SEED)
    start = END - timedelta(days=DAYS - 1)
    days: dict[str, dict] = {}

    for i in range(DAYS):
        d = start + timedelta(days=i)
        weekend = d.weekday() >= 5

        steps = rnd.gauss(10500 if weekend else 7200, 2600)
        steps = float(max(900, min(16000, steps)))
        active = max(120.0, steps * 0.052 + rnd.gauss(0, 35))
        exercise = 0.0 if rnd.random() < 0.25 else float(max(0, rnd.gauss(38, 20)))

        sleep_ok = rnd.random() > 0.07                       # 少数几天睡眠异常
        if sleep_ok:
            deep = rnd.gauss(75, 18)
            core = rnd.gauss(285, 35)
            rem = rnd.gauss(85, 22)
            awake = rnd.gauss(25, 10)
        else:
            deep, core, rem, awake = 12, 35, 8, 5            # 触发"疑似未佩戴手表"

        dd: dict = {
            "_source": "demo",
            "steps": round(steps, 2),
            "distance_km": round(steps * 0.00072, 2),
            "active_kcal": round(active, 2),
            "basal_kcal": round(rnd.gauss(1555, 22), 2),
            "exercise_min": round(exercise, 1),
            "hrv_ms": round(rnd.gauss(48, 7), 1),
            "hr_resting": round(rnd.gauss(62, 3), 1),
            "sleep": {
                "deep": round(max(0, deep)), "core": round(max(0, core)),
                "rem": round(max(0, rem)), "awake": round(max(0, awake)),
            },
        }

        hr = _hr_points(rnd)
        vals = [v for _t, v in hr]
        dd["hr_points"] = hr
        dd["hr_avg"] = round(sum(vals) / len(vals), 1)
        dd["hr_max"] = max(vals)
        dd["hr_min"] = min(vals)
        dd["captured_at"] = hr[-1][0]

        segs = _sleep_stages(rnd, dd["sleep"]["deep"], dd["sleep"]["core"],
                             dd["sleep"]["rem"], dd["sleep"]["awake"])
        dd["sleep_segments"] = segs

        # 制造一天步数异常，展示离群标记
        if i == DAYS - 6:
            dd["steps"] = 19480.0
            dd["distance_km"] = round(19480 * 0.00072, 2)

        days[d.isoformat()] = dd

    return metrics.enrich(days)


def main() -> None:
    series = build_demo()
    dates = sorted(series)
    (OUT / "demo-data.json").write_text(
        json.dumps(series, ensure_ascii=False, indent=1), encoding="utf-8")

    meta = {"demo": True, "days_total": len(dates), "generator": "examples/build_demo.py"}
    dashboard.build(series, OUT / "demo-dashboard.html", meta)

    qc = [d for d, dd in series.items() if dd.get("qc")]
    print(f"✅ 合成 {len(dates)} 天数据（{dates[0]} → {dates[-1]}）")
    print(f"   数据质量存疑 {len(qc)} 天：" + "、".join(sorted(qc)))
    print(f"   → examples/demo-data.json")
    print(f"   → examples/demo-dashboard.html（"
          f"{(OUT / 'demo-dashboard.html').stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
