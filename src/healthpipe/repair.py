"""容错解析器 —— 本项目最核心的一小块代码。

iPhone 快捷指令没有可靠的 JSON 构造方式（多数人是用「文本」动作手写字符串拼接），
产出的文件几乎一定不是合法 JSON。拿真实文件数过，固定只有三类损坏：

  1. ``"v":79 "}``    —— 每个数字值后面多一个引号（每条心率都有，约 280 处）
  2. ``］``            —— 中文输入法打出的全角闭合括号
  3. ``", ]"``        —— 数组 / 对象尾随逗号

所以：**绝对不要拿 json.loads() 直接读快捷指令的输出**，先过这里。

修复顺序不能调换 —— 必须先去多余引号，否则全角替换会把它变成合法引号，
问题反而被藏起来。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 中文输入法常见的全角标点
FULLWIDTH_MAP = {
    "［": "[", "］": "]", "｛": "{", "｝": "}",
    "：": ":", "，": ",", "＂": '"', "“": '"', "”": '"',
    "＇": "'", "／": "/", "　": " ",
}

# 类型 1：`"v":79 "}` —— 数字值后多一个引号
_RE_STRAY_QUOTE = re.compile(r'("v"\s*:\s*)([0-9.]+)\s*"\s*\}')

# 类型 3：`, ]` / `, }` —— 尾随逗号
_RE_TRAILING_COMMA = re.compile(r",\s*([\]\}])")


def repair_text(raw: str) -> tuple[Any, list[str]]:
    """把「近似 JSON」修成可解析对象，返回 (对象, 修复说明列表)。"""
    fixes: list[str] = []
    s = raw

    n = len(_RE_STRAY_QUOTE.findall(s))
    if n:
        s = _RE_STRAY_QUOTE.sub(r"\1\2}", s)
        fixes.append(f"数字值后多余引号 x{n}")

    if any(fw in s for fw in FULLWIDTH_MAP):
        for fw, hw in FULLWIDTH_MAP.items():
            s = s.replace(fw, hw)
        fixes.append("全角标点 → 半角")

    c = len(_RE_TRAILING_COMMA.findall(s))
    if c:
        s = _RE_TRAILING_COMMA.sub(r"\1", s)
        fixes.append(f"尾随逗号 x{c}")

    return json.loads(s), fixes


def load_text(raw: str) -> tuple[Any, list[str]]:
    """先按合法 JSON 解析；失败再走修复流程。"""
    try:
        return json.loads(raw), []
    except json.JSONDecodeError:
        return repair_text(raw)


def load_file(path: str | Path) -> tuple[Any, list[str]]:
    """读取并解析一个快捷指令导出文件。"""
    p = Path(path)
    return load_text(p.read_text(encoding="utf-8"))


def detect_issues(raw: str) -> list[str]:
    """只探测不修复 —— 用于 doctor 命令体检历史文件。"""
    issues: list[str] = []
    n = len(_RE_STRAY_QUOTE.findall(raw))
    if n:
        issues.append(f"数字值后多余引号 x{n}")
    fw = [k for k in FULLWIDTH_MAP if k in raw]
    if fw:
        issues.append("全角标点：" + "".join(fw))
    c = len(_RE_TRAILING_COMMA.findall(raw))
    if c:
        issues.append(f"尾随逗号 x{c}")
    return issues
