"""MCP server 协议层的测试（不依赖真实客户端）。"""

import io
import json

from healthpipe import mcp_server


class FakeStore:
    """只需要 .series()，与 DataStore 同形。"""

    def __init__(self, series):
        self._series = series

    def series(self):
        return self._series


SERIES = {
    "2026-01-01": {"steps": 8000, "hrv_ms": 40.0, "hr_resting": 58,
                   "sleep": {"deep": 60, "core": 300, "rem": 60, "awake": 30}},
    "2026-01-02": {"steps": 12000, "hrv_ms": 44.0, "hr_resting": 56,
                   "sleep": {"deep": 60, "core": 240, "rem": 60, "awake": 30},
                   "qc": ["睡眠不足 3h"]},
}


def _store():
    return FakeStore(SERIES)


def test_initialize_echoes_protocol_version():
    out = mcp_server._dispatch("initialize", {"protocolVersion": "2024-11-05"}, _store(), {})
    assert out["protocolVersion"] == "2024-11-05"
    assert out["serverInfo"]["name"] == "healthpipe"
    assert "tools" in out["capabilities"]


def test_initialize_without_client_version_uses_default():
    out = mcp_server._dispatch("initialize", {}, _store(), {})
    assert out["protocolVersion"] == mcp_server.PROTOCOL_VERSION


def test_tools_list_exposes_readonly_tools():
    out = mcp_server._dispatch("tools/list", {}, _store(), {})
    names = {t["name"] for t in out["tools"]}
    assert names == {"health_overview", "health_daily", "health_series",
                     "health_workouts", "health_quality"}
    for t in out["tools"]:
        assert t["description"] and t["inputSchema"]["type"] == "object"


def test_tools_call_returns_text_content():
    out = mcp_server._dispatch(
        "tools/call", {"name": "health_overview", "arguments": {"days": 2}}, _store(), {}
    )
    assert out["isError"] is False
    assert out["content"][0]["type"] == "text"
    assert "2026-01-02" in out["content"][0]["text"]


def test_tools_call_unknown_tool_raises():
    try:
        mcp_server._dispatch("tools/call", {"name": "nope"}, _store(), {})
    except ValueError as e:
        assert "未知工具" in str(e)
    else:
        raise AssertionError("应当抛出 ValueError")


def test_ping_supported():
    assert mcp_server._dispatch("ping", {}, _store(), {}) == {}


def test_serve_answers_handshake_and_reports_errors(monkeypatch):
    """整条 stdio 循环：握手 + 一次工具调用 + 一次非法方法。"""
    monkeypatch.setattr(mcp_server, "DataStore", lambda cfg: _store())
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),   # 通知，不应回包
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "health_quality", "arguments": {"days": 30}}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "bogus", "params": {}}),
        "",                                                                     # 空行应被跳过
    ]
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    assert mcp_server.serve(object(), stdin, stdout) == 0

    resp = [json.loads(s) for s in stdout.getvalue().splitlines()]
    assert [r["id"] for r in resp] == [1, 2, 3]
    assert "睡眠不足 3h" in resp[1]["result"]["content"][0]["text"]
    assert resp[2]["error"]["code"] == -32603
