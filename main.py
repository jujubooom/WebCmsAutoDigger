"""PHP 代码审计入口。

用法:
    python main.py --dir /path/to/dede/project [--name task_name]
    python main.py --checkmodel
    python main.py --dir /path --buildinfo /path/to/info.md
    python main.py --dir /path --autobuild
    python main.py --dir /path --loadjson /path/to/dede.json

工作流:
    1. 在项目目录下创建 workspace/{task_name}/ 作为隔离工作区
    2. 写入 opencode.json 定义 Agent
    3. 在 workspace 中启动 opencode serve
    4. 读取源码目录下的 dede.json（取第 1 条）
    5. tracer Agent 进行反向污点追溯
    6. verifier Agent 进行漏洞验证
    7. 生成审计报告到源码目录
"""

import argparse
import json
import sys
import os
import tempfile
from datetime import datetime

# 支持直接 python main.py 启动
_self_dir = os.path.dirname(os.path.abspath(__file__))
if _self_dir not in sys.path:
    sys.path.insert(0, _self_dir)

from orchestrate.graph import build_audit_graph
from orchestrate.presets import new_audit_task


def cmd_checkmodel():
    """启动临时 opencode serve，列出所有 provider 及其模型、key 配置状态。"""
    from server import task as task_mgr
    from server.providers import inject_keys, discover_models

    tmpdir = tempfile.mkdtemp(prefix="opencode_checkmodel_")
    print(f"[checkmodel] 临时工作区: {tmpdir}")

    config_path = os.path.join(tmpdir, "opencode.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"agent": {}}, f)

    task = None
    try:
        task = task_mgr.open_serve(tmpdir, startup_timeout=60)
        print(f"[checkmodel] 服务已启动 → {task}\n")
        inject_keys(task)
        print()
        discover_models(task)
    finally:
        if task is not None and task.is_running:
            task.cleanup_my_sessions()
            task.stop()
            print(f"\n[checkmodel] 服务已停止")


def load_build_info(path: str) -> str:
    """读取 --buildinfo 指定的 markdown 文件内容。"""
    if not os.path.exists(path):
        print(f"错误: --buildinfo 文件不存在: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def main():
    parser = argparse.ArgumentParser(
        description="PHP 代码审计 —— 反向污点追溯 + 漏洞验证"
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="源码项目目录，该目录下需包含 dede.json",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="本次审计任务名称，不传则用时间戳",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="启用 mock 模式，使用预置响应不调 LLM",
    )
    parser.add_argument(
        "--checkmodel",
        action="store_true",
        default=False,
        help="查看当前环境中可用的 AI 模型列表",
    )
    parser.add_argument(
        "--buildinfo",
        default=None,
        help="CMS 搭建信息 markdown 文件，内容拼入漏洞验证提示词",
    )
    parser.add_argument(
        "--autobuild",
        action="store_true",
        default=False,
        help="自动搭建 CMS 环境（Docker 构建 + Web 安装，生成 build_info.md）",
    )
    parser.add_argument(
        "--loadjson",
        default=None,
        help="从指定文件加载 sink 点 JSON（跳过 sss 扫描），如 dede.json",
    )
    args = parser.parse_args()

    # ── checkmodel 模式 ──────────────────────────────────────────────
    if args.checkmodel:
        cmd_checkmodel()
        if not args.dir:
            return  # 纯 checkmodel，直接退出

    # ── 审计模式需要 --dir ───────────────────────────────────────────
    if not args.dir:
        parser.print_help()
        print("\n错误: 审计模式需要 --dir 参数")
        sys.exit(1)

    if args.mock:
        from mock import enable
        enable()

    source_dir = os.path.abspath(args.dir)
    if not os.path.isdir(source_dir):
        print(f"错误: 目录不存在: {source_dir}")
        sys.exit(1)

    # ── buildinfo ────────────────────────────────────────────────────
    build_info = ""
    if args.buildinfo:
        build_info = load_build_info(args.buildinfo)
        print(f"[审计] 已加载 build_info: {args.buildinfo} ({len(build_info)} 字符)")

    task_name = args.name or datetime.now().strftime("%Y%m%d_%H%M%S")

    # workspace 放在 src 根目录下
    project_root = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.join(project_root, "workspace", task_name)
    os.makedirs(workspace_dir, exist_ok=True)

    print(f"源码目录:   {source_dir}")
    print(f"工作区目录: {workspace_dir}")
    print(f"任务名称:   {task_name}")

    graph = build_audit_graph()

    state = new_audit_task(
        source_dir=source_dir,
        workspace_dir=workspace_dir,
        mock=args.mock,
        build_info=build_info,
        auto_build=args.autobuild,
        check_model=args.checkmodel,
        loadjson=args.loadjson or "",
    )
    print(f"已加载Agents: {list(state['agents'].keys())}")
    try:
        final_state = graph.invoke(state)
        if final_state.get("error"):
            print(f"\n[审计] 错误: {final_state['error']}")
            sys.exit(1)
        print(f"\n[审计] 报告已生成: {os.path.join(workspace_dir, 'audit_report.md')}")
    except Exception as e:
        print(f"\n[审计] 异常: {e}")
        sys.exit(1)
    finally:
        task = state.get("task")
        if task is not None and task.is_running:
            task.cleanup_my_sessions()
            task.stop()
            print("[审计] 服务已停止")


if __name__ == "__main__":
    main()
