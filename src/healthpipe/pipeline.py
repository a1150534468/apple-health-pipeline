"""统一的数据装载管线 —— CLI / MCP / 仪表盘共用的唯一加载路径。

曾经 CLI 和 MCP 各写了一份加载逻辑，MCP 那份漏接了 healthsync 源，
导致血氧、呼吸率、运动记录等字段在 MCP 里静默缺失（渲染层根本不报错）。
教训：加载逻辑只允许存在一份，所有出口都从这里拿数据。
"""

from __future__ import annotations

from . import metrics, sources
from .config import Config


def load_series(cfg: Config) -> tuple[dict, dict, dict, dict]:
    """读所有数据源 → 合并 → 补派生字段。

    返回 ``(series, export, shortcut, healthsync)`` 四元组，便于各出口统计来源。

    healthexport / shortcut 按字段合并；healthsync 是权威源，同日期整天替换 ——
    避免和旧来源的同名字段拼出一个混合口径的一天。
    """
    export = sources.load_healthexport(cfg.healthexport_dir)
    shortcut = sources.load_shortcut(cfg.shortcut_dir)
    healthsync = sources.load_healthsync(cfg.healthsync_dir)
    series = sources.merge(export, shortcut)
    for d, dd in healthsync.items():
        series[d] = dict(dd)
    series = {d: v for d, v in sorted(series.items()) if v}
    return metrics.enrich(series), export, shortcut, healthsync


def apply_privacy(series: dict, cfg: Config) -> dict:
    """配置了脱敏（anonymize）就套上，否则原样返回。"""
    return metrics.anonymize(series, cfg.anonymize_seed) if cfg.anonymize else series
