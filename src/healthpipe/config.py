"""配置加载：把个人路径从代码里赶出去。

所有路径都走 config.toml（见 config.example.toml），代码里不留任何硬编码目录。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAME = "config.toml"


def _expand(value: str) -> Path:
    return Path(value).expanduser()


@dataclass
class Config:
    """运行期配置。"""

    # 必填：iPhone 快捷指令的导出目录
    shortcut_dir: Path
    # 产物输出目录
    output_dir: Path = Path("./output")
    # 可选：第三方 App（如 HealthExport）的导出目录
    healthexport_dir: Path | None = None

    dashboard_title: str = "健康数据仪表盘"
    dashboard_subtitle: str = "Apple Watch · 本地数据管道"
    report_filename: str = "健康记录.md"

    # 生成公开版本时按比例缩放真实值，保留趋势形态
    anonymize: bool = False
    anonymize_seed: int = 20261011

    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        p = Path(path or DEFAULT_CONFIG_NAME).expanduser()
        if not p.exists():
            raise FileNotFoundError(
                f"找不到配置文件：{p}\n"
                f"请先复制 config.example.toml 为 {DEFAULT_CONFIG_NAME}，再按实际情况修改路径。"
            )
        with p.open("rb") as f:
            return cls.from_dict(tomllib.load(f))

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        paths = raw.get("paths") or {}
        shortcut_dir = paths.get("shortcut_dir")
        if not shortcut_dir:
            raise ValueError("config.toml 缺少必填项 [paths] shortcut_dir")

        he = (paths.get("healthexport_dir") or "").strip() or None
        dash = raw.get("dashboard") or {}
        rep = raw.get("report") or {}
        priv = raw.get("privacy") or {}

        return cls(
            shortcut_dir=_expand(shortcut_dir),
            output_dir=_expand(paths.get("output_dir") or "./output"),
            healthexport_dir=_expand(he) if he else None,
            dashboard_title=dash.get("title") or "健康数据仪表盘",
            dashboard_subtitle=dash.get("subtitle") or "Apple Watch · 本地数据管道",
            report_filename=rep.get("filename") or "健康记录.md",
            anonymize=bool(priv.get("anonymize", False)),
            anonymize_seed=int(priv.get("anonymize_seed", 20261011)),
        )

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir
