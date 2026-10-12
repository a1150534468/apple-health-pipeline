"""最小 MCP (Model Context Protocol) server —— 零依赖，走 stdio。

让 Claude Desktop / Cursor / WorkBuddy 这类 AI 客户端**直接挂载**本地健康数据。
实现的是 tools 能力（只读查询），不含 resources / prompts。

之所以手写而不依赖 `mcp` SDK：这个项目本身零运行时依赖，而协议里我们只用到
initialize / tools.list / tools.call 三个方法，不值得为此引入一个依赖树。

客户端配置示例（Claude Desktop 的 claude_desktop_config.json）：

    {
      "mcpServers": {
        "healthpipe": {
          "command": "healthpipe",
          "args": ["--config", "/absolute/path/to/config.toml", "mcp"]
        }
      }
    }
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from . import __version__, context, metrics, sources
from .config import Config

PROTOCOL_VERSION = "2024-11-05"

TOOLS: list[dict] = [
    {
        "name": "health_overview",
        "description": (
            "获取最近 N 天的健康数据摘要：最新一天明细、各指标趋势、数据质量问题。"
            "回答『我最近身体状态怎么样』这类问题时先调它。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "回溯天数，默认 7", "default": 7},
            },
        },
    },
    {
        "name": "health_daily",
        "description": "获取某一天的完整健康明细。不传 date 则返回最新一天。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD；不传取最新一天"},
            },
        },
    },
    {
        "name": "health_series",
        "description": (
            "获取单个指标的逐日时序（CSV）。"
            "可用指标：sleep_asleep_h / deep_pct / hrv_ms / hr_resting / "
            "steps / active_kcal / exercise_min / distance_km"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "指标名"},
                "days": {"type": "integer", "description": "回溯天数，默认 30", "default": 30},
            },
            "required": ["metric"],
        },
    },
    {
        "name": "health_quality",
        "description": (
            "列出最近 N 天里数据质量存疑的日子（疑似未佩戴手表、步数异常等）。"
            "在下任何健康结论之前应先调用它，避免基于脏数据推断。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 30}},
        },
    },
]


class DataStore:
    """懒加载 + 缓存已解析的时序数据（一个进程内只解析一次）。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._series: dict[str, dict] | None = None

    def series(self) -> dict[str, dict]:
        if self._series is None:
            export = sources.load_healthexport(self.cfg.healthexport_dir)
            shortcut = sources.load_shortcut(self.cfg.shortcut_dir)
            merged = {d: v for d, v in sorted(sources.merge(export, shortcut).items()) if v}
            self._series = metrics.enrich(merged)
        return self._series


# --------------------------------------------------------------------------- 工具实现


def _overview(store: DataStore, args: dict) -> str:
    days = int(args.get("days") or 7)
    return context.render_context(store.series(), days=days)


def _daily(store: DataStore, args: dict) -> str:
    return context.render_daily(store.series(), args.get("date"))


def _series(store: DataStore, args: dict) -> str:
    return context.render_series(
        store.series(), str(args.get("metric") or ""), int(args.get("days") or 30)
    )


def _quality(store: DataStore, args: dict) -> str:
    days = int(args.get("days") or 30)
    series = store.series()
    if not series:
        return "（没有可用的健康数据）"
    window = sorted(series)[-days:]
    rows = [f"- {d}：{'；'.join(series[d]['qc'])}" for d in window if series[d].get("qc")]
    span = f"{window[0]} → {window[-1]}"
    if not rows:
        return f"# 数据质量\n\n{span} 未发现异常样本。"
    return f"# 数据质量存疑的日子（{span}）\n\n" + "\n".join(rows)


HANDLERS: dict[str, Callable[[DataStore, dict], str]] = {
    "health_overview": _overview,
    "health_daily": _daily,
    "health_series": _series,
    "health_quality": _quality,
}


# --------------------------------------------------------------------------- 协议


def _dispatch(method: str, params: dict, store: DataStore, negotiated: dict) -> Any:
    if method == "initialize":
        # 回显客户端版版本（若它给了我们支持的），否则报自己的
        requested = params.get("protocolVersion")
        negotiated["version"] = requested or PROTOCOL_VERSION
        return {
            "protocolVersion": negotiated["version"],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "healthpipe", "version": __version__},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(str(name))
        if handler is None:
            raise ValueError(f"未知工具：{name}")
        text = handler(store, params.get("arguments") or {})
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if method == "ping":
        return {}
    raise ValueError(f"不支持的方法：{method}")


def serve(cfg: Config, stdin=None, stdout=None) -> int:
    """跑 stdio 循环。stdout 只允许出现 JSON-RPC 报文。"""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    store = DataStore(cfg)
    negotiated: dict = {}

    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(req, dict) or "id" not in req:
            continue                       # 通知（如 notifications/initialized），忽略

        rid = req["id"]
        try:
            result = _dispatch(str(req.get("method")), req.get("params") or {}, store, negotiated)
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:             # 任何失败都回 error，不退出进程
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32603, "message": str(e)}}

        stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0
