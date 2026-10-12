"""命令行入口。

    healthpipe sync        解析导出文件，合并成统一时序（output/series.json）
    healthpipe dashboard   生成单文件 HTML 仪表盘
    healthpipe report      生成 Markdown 汇总表
    healthpipe context     输出给 AI 用的健康数据上下文（可直接粘给模型）
    healthpipe mcp         启动 MCP server，供 AI 客户端直接挂载
    healthpipe doctor      体检数据质量与解析情况
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, context, dashboard, metrics, report, sources
from .config import Config

DEFAULT_CONFIG = "config.toml"


def _load_series(cfg: Config) -> tuple[dict, dict, dict]:
    """读所有数据源 → 合并 → 补派生字段。"""
    export = sources.load_healthexport(cfg.healthexport_dir)
    shortcut = sources.load_shortcut(cfg.shortcut_dir)
    series = sources.merge(export, shortcut)
    series = {d: v for d, v in sorted(series.items()) if v}
    return metrics.enrich(series), export, shortcut


def _apply_privacy(series: dict, cfg: Config) -> dict:
    return metrics.anonymize(series, cfg.anonymize_seed) if cfg.anonymize else series


def _meta(cfg: Config, export: dict, shortcut: dict) -> dict:
    return {
        "shortcut_dir": str(cfg.shortcut_dir),
        "healthexport_dir": str(cfg.healthexport_dir) if cfg.healthexport_dir else None,
        "days_from_shortcut": len(shortcut),
        "days_from_healthexport": len(export),
        "anonymized": cfg.anonymize,
    }


# --------------------------------------------------------------------------- 子命令


def cmd_sync(cfg: Config, args) -> int:
    series, export, shortcut = _load_series(cfg)
    if not series:
        print("⚠️ 没有找到任何数据，请检查 config.toml 里的路径。", file=sys.stderr)
        return 2

    series = _apply_privacy(series, cfg)
    out = cfg.ensure_output_dir() / "series.json"
    out.write_text(json.dumps(series, ensure_ascii=False, indent=1), encoding="utf-8")

    dates = sorted(series)
    print(f"✅ 已合并 {len(dates)} 天数据（{dates[0]} → {dates[-1]}）")
    print(f"   来源：快捷指令 {len(shortcut)} 天 / App 导出 {len(export)} 天")
    qc = [d for d, dd in series.items() if dd.get("qc")]
    if qc:
        print(f"   ⚠️ 数据质量存疑 {len(qc)} 天：" + "、".join(qc))
    print(f"   → {out}")
    return 0


def cmd_dashboard(cfg: Config, args) -> int:
    series, export, shortcut = _load_series(cfg)
    if not series:
        print("⚠️ 没有找到任何数据，请检查 config.toml 里的路径。", file=sys.stderr)
        return 2

    series = _apply_privacy(series, cfg)
    payload = dashboard.build_payload(series, _meta(cfg, export, shortcut))
    out = dashboard.render(payload, cfg.ensure_output_dir() / "health-dashboard.html")
    size_kb = out.stat().st_size / 1024
    print(f"✅ 仪表盘 → {out}（{size_kb:.0f} KB，单文件可直接分享）")
    return 0


def cmd_report(cfg: Config, args) -> int:
    series, _export, _shortcut = _load_series(cfg)
    if not series:
        print("⚠️ 没有找到任何数据，请检查 config.toml 里的路径。", file=sys.stderr)
        return 2

    series = _apply_privacy(series, cfg)
    out = report.write_report(series, cfg.ensure_output_dir() / cfg.report_filename, args.days)
    print(f"✅ 汇总表 → {out}")
    return 0


def cmd_doctor(cfg: Config, args) -> int:
    from . import repair

    print(f"healthpipe {__version__}")
    print(f"配置文件：{args.config}")
    print(f"快捷指令目录：{cfg.shortcut_dir}  {'✅ 存在' if cfg.shortcut_dir.exists() else '❌ 不存在'}")
    if cfg.healthexport_dir:
        ok = "✅ 存在" if cfg.healthexport_dir.exists() else "❌ 不存在"
        print(f"App 导出目录：{cfg.healthexport_dir}  {ok}")

    files = sorted(cfg.shortcut_dir.glob("*.txt")) if cfg.shortcut_dir.exists() else []
    print(f"\n快捷指令文件：{len(files)} 个")
    failed = 0
    total_fixes: dict[str, int] = {}
    for f in files:
        try:
            raw = f.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  ❌ {f.name}：{e}")
            failed += 1
            continue
        issues = repair.detect_issues(raw)
        for it in issues:
            key = it.split(" x")[0]
            total_fixes[key] = total_fixes.get(key, 0) + 1

    if failed:
        print(f"  ❌ 读取失败 {failed} 个")
    if total_fixes:
        print("  检测到的问题（sync 会自动修复）：")
        for k, n in sorted(total_fixes.items(), key=lambda x: -x[1]):
            print(f"    - {k}：{n}/{len(files)} 个文件")
    else:
        print("  ✅ 未检测到格式问题" if files else "  （无文件）")

    series, _e, _s = _load_series(cfg)
    if series:
        dates = sorted(series)
        print(f"\n可解析数据：{len(dates)} 天（{dates[0]} → {dates[-1]}）")
        qc = [d for d, dd in series.items() if dd.get("qc")]
        for d in sorted(qc):
            print(f"  ⚠️ {d}：" + "；".join(series[d]["qc"]))
    return 0


def cmd_context(cfg: Config, args) -> int:
    series, _e, _s = _load_series(cfg)
    if not series:
        print("⚠️ 没有找到任何数据，请检查 config.toml 里的路径。", file=sys.stderr)
        return 2

    text = context.render_context(_apply_privacy(series, cfg), days=args.days)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"✅ 上下文 → {out}")
    else:
        print(text)
    return 0


def cmd_mcp(cfg: Config, args) -> int:
    from . import mcp_server

    print("healthpipe MCP server 已启动（stdio）。客户端配置见 README「AI 集成」一节。",
          file=sys.stderr)
    return mcp_server.serve(cfg)


# --------------------------------------------------------------------------- 入口


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="healthpipe", description="Apple Health → 本地时序数据 + 可视化")
    p.add_argument("--config", default=DEFAULT_CONFIG, help=f"配置文件路径（默认 {DEFAULT_CONFIG}）")
    p.add_argument("--version", action="version", version=f"healthpipe {__version__}")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="解析导出文件，合并成统一时序")
    sub.add_parser("dashboard", help="生成单文件 HTML 仪表盘")
    rp = sub.add_parser("report", help="生成 Markdown 汇总表")
    rp.add_argument("--days", type=int, default=None, help="只输出最近 N 天")
    cp = sub.add_parser("context", help="输出给 AI 用的健康数据上下文")
    cp.add_argument("--days", type=int, default=7, help="回溯天数（默认 7）")
    cp.add_argument("--out", default=None, help="写入文件；不传则打印到 stdout")
    sub.add_parser("mcp", help="启动 MCP server（stdio），供 AI 客户端挂载")
    sub.add_parser("doctor", help="体检数据质量与解析情况")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        cfg = Config.load(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    handlers = {
        "sync": cmd_sync,
        "dashboard": cmd_dashboard,
        "report": cmd_report,
        "doctor": cmd_doctor,
        "context": cmd_context,
        "mcp": cmd_mcp,
    }
    return handlers[args.command](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
