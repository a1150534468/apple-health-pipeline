"""单文件仪表盘生成的测试。"""

import json
import re

from healthpipe import dashboard


SERIES = {
    "2026-01-01": {"steps": 8000, "hrv_ms": 40.0},
    "2026-01-02": {"steps": 12000, "hrv_ms": 44.0},
}


def test_payload_always_sets_days_total():
    """模板读的是 sources.days_total，缺了会渲染成 undefined。"""
    payload = dashboard.build_payload(SERIES)
    assert payload["sources"]["days_total"] == 2


def test_payload_keeps_caller_days_total():
    payload = dashboard.build_payload(SERIES, {"days_total": 99, "demo": True})
    assert payload["sources"]["days_total"] == 99
    assert payload["sources"]["demo"] is True


def test_payload_on_empty_series():
    payload = dashboard.build_payload({})
    assert payload["date_range"] == []
    assert payload["latest_date"] is None
    assert payload["sources"]["days_total"] == 0


def test_render_inlines_assets_and_fills_placeholders(tmp_path):
    out = dashboard.build(SERIES, tmp_path / "d.html")
    html = out.read_text(encoding="utf-8")

    assert dashboard.DATA_PLACEHOLDER not in html        # 数据已灌进去
    assert dashboard.ECHARTS_PLACEHOLDER not in html     # 图表库已内联
    # 单文件：不应引用任何外部脚本
    assert "<script src=" not in html

    # 灌进去的 payload 里必须真有 days_total，否则模板会渲染成 undefined
    # （注意：内联的 ECharts 源码本身含 "undefined" 字样，所以只在 payload 上判断）
    m = re.search(r"const DATA\s*=\s*(\{.*?\});\s*$", html, re.S | re.M)
    assert m, "模板里的 DATA 赋值没找到"
    payload = json.loads(m.group(1))
    assert payload["sources"]["days_total"] == 2
