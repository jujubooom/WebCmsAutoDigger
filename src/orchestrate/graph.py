"""工作流图构建 —— 定义节点编排和条件路由。"""

from langgraph.graph import StateGraph, START, END

from orchestrate.state import OrchState
from orchestrate.nodes import (
    node_write_agent_config,
    node_scan_sinks,
    node_start_task,
    node_inject_keys,
    node_patch_config,
    node_discover_models,
    node_setup_agents,
    node_autobuild,
    node_cleanup,
    node_load_dede,
    node_reverse_trace,
    node_verify_vuln,
    node_save_sink,
    node_generate_audit_report,
)


def _route_after_write_config(state: OrchState) -> str:
    """mock 模式跳过扫描和服务启动，直接进入审计"""
    if state.get("mock"):
        return "load_dede"
    return "scan_sinks"


def _route_after_setup_agents(state: OrchState) -> str:
    """autobuild 模式下先执行自动搭建再进入审计"""
    if state.get("auto_build"):
        return "autobuild"
    return "load_dede"


def _route_after_scan(state: OrchState) -> str:
    """sss 扫描失败则直接生成报告"""
    if state.get("error"):
        return "generate_report"
    return "start_task"


def _route_after_load_dede(state: OrchState) -> str:
    if state.get("error"):
        return "after_audit"
    if state.get("group_index", 0) >= state.get("group_total", 0):
        return "after_audit"
    return "reverse_trace"


def _route_after_save_sink(state: OrchState) -> str:
    """还有未处理的分组 → 循环回 reverse_trace，全部完成 → 生成报告"""
    if state.get("group_index", 0) < state.get("group_total", 0):
        return "reverse_trace"
    return "generate_report"


def _route_after_reverse_trace(state: OrchState) -> str:
    if state.get("error"):
        return "after_audit"
    if state.get("trace_verdict") == "uncontrollable":
        return "save_sink"
    return "verify_vuln"


def _route_after_report(state: OrchState) -> str:
    """mock 模式跳过 cleanup（无 serve 需关闭）"""
    if state.get("mock"):
        return "__end__"
    return "cleanup"


def build_audit_graph() -> StateGraph:
    """构建 PHP 代码审计工作流图。

    图结构:
      START → write_config
        ├── mock → load_dede
        └── normal → scan_sinks → start_task → inject_keys → patch_config
            → discover_models → setup_agents
            ├── autobuild → load_dede
            └── load_dede
              ├── error → generate_report
              └── reverse_trace
                   ├── 不可控 → save_sink
                   └── 可控 → verify_vuln → save_sink
                        ├── (还有) → reverse_trace  (循环)
                        └── (完成) → generate_report
                            ├── mock → END
                            └── normal → cleanup → END
    """
    builder = StateGraph(OrchState)

    builder.add_node("write_config",     node_write_agent_config)
    builder.add_node("scan_sinks",       node_scan_sinks)
    builder.add_node("start_task",       node_start_task)
    builder.add_node("inject_keys",      node_inject_keys)
    builder.add_node("patch_config",     node_patch_config)
    builder.add_node("discover_models",  node_discover_models)
    builder.add_node("setup_agents",     node_setup_agents)
    builder.add_node("autobuild",        node_autobuild)
    builder.add_node("load_dede",        node_load_dede)
    builder.add_node("reverse_trace",    node_reverse_trace)
    builder.add_node("verify_vuln",      node_verify_vuln)
    builder.add_node("save_sink",        node_save_sink)
    builder.add_node("generate_report",  node_generate_audit_report)
    builder.add_node("cleanup",          node_cleanup)

    builder.add_edge(START, "write_config")

    builder.add_conditional_edges(
        "write_config",
        _route_after_write_config,
        {"load_dede": "load_dede", "scan_sinks": "scan_sinks"},
    )

    builder.add_conditional_edges(
        "scan_sinks",
        _route_after_scan,
        {"start_task": "start_task", "generate_report": "generate_report"},
    )
    builder.add_edge("start_task", "inject_keys")
    builder.add_edge("inject_keys", "patch_config")
    builder.add_edge("patch_config", "discover_models")
    builder.add_edge("discover_models", "setup_agents")
    builder.add_conditional_edges(
        "setup_agents",
        _route_after_setup_agents,
        {"autobuild": "autobuild", "load_dede": "load_dede"},
    )
    builder.add_edge("autobuild", "load_dede")

    builder.add_conditional_edges(
        "load_dede",
        _route_after_load_dede,
        {"reverse_trace": "reverse_trace", "after_audit": "generate_report"},
    )

    builder.add_conditional_edges(
        "reverse_trace",
        _route_after_reverse_trace,
        {"verify_vuln": "verify_vuln", "save_sink": "save_sink", "after_audit": "generate_report"},
    )

    builder.add_edge("verify_vuln", "save_sink")

    builder.add_conditional_edges(
        "save_sink",
        _route_after_save_sink,
        {"reverse_trace": "reverse_trace", "generate_report": "generate_report"},
    )

    builder.add_conditional_edges(
        "generate_report",
        _route_after_report,
        {"cleanup": "cleanup", "__end__": END},
    )

    builder.add_edge("cleanup", END)

    return builder.compile()
