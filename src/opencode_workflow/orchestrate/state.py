"""编排层状态定义 —— 流经整个 LangGraph 工作流的全局状态。"""

from typing import TypedDict

from ..server.task import OpenCodeTask


class OrchState(TypedDict, total=False):
    """编排层全局状态，所有字段可选（total=False），各节点按需读写。"""
    directory: str                        # 工作目录（opencode serve 启动目录）
    source_dir: str                       # 源码目录（审计目标，dede.json 所在位置）
    task: OpenCodeTask                    # 当前任务对象（启动后注入）
    sessions: list[str]                   # 本次任务创建的所有 session ID
    agents: dict[str, dict]               # {agent_name: {mode, permission, ...}}
    mock: bool                            # 是否启用 mock 模式
    error: str                            # 错误信息

    # ── 审计工作流专用字段 ──────────────────────────────────────────
    dede_items: list[dict]               # dede.json 中取出的 sink 点列表
    sink_index: int                       # 当前正在处理的 sink 下标（0-based）
    sink_total: int                       # sink 总数
    trace_report: str                     # 当前 sink 的追溯报告
    verify_report: str                    # 当前 sink 的漏洞验证报告
    final_report: str                     # 最终汇总报告
    build_info: str                      # CMS 搭建信息（markdown），拼入验证提示词
    auto_build: bool                      # 是否自动搭建 CMS 环境
    check_model: bool                     # 是否输出 provider/model 列表（仅 --checkmodel 时）
    session_urls: list[dict]              # 可视化链接 [{title, url}]，供报告展示
