"""
OpenCode serve 前端 / 运行时配置。

修改此文件即可控制所有 agent 的行为和 UI 展示选项，
无需手动在浏览器齿轮菜单里逐个点击。

生效时机：serve 启动后由 node_patch_config 通过 PATCH /config 写入。
"""

# ═══════════════════════════════════════════════════════════════════════════════
#  全局权限
# ═══════════════════════════════════════════════════════════════════════════════
#
# "allow" — 全部自动允许，永不需要人工审批
# "ask"   — 默认询问
# "deny"  — 默认拒绝
#
# 也可以按工具细分，例如：
#   GLOBAL_PERMISSION = {
#       "*": "allow",
#       "bash": {"rm *": "deny"},
#   }

GLOBAL_PERMISSION = "allow"


# ═══════════════════════════════════════════════════════════════════════════════
#  各 Agent 独立选项
# ═══════════════════════════════════════════════════════════════════════════════
#
# 每个 agent 可配置的选项（对应齿轮菜单中的各项开关）：
#
#   autoApprove       — 自动接收权限，不弹出确认框
#   showReasoning     — 显示推理摘要
#   expandShell       — 展开 shell 工具输出
#   temperature       — 生成温度 (0.0 ~ 2.0)，None 使用全局默认

AGENT_OPTIONS = {
    "tracer": {
        "autoApprove": True,
        "showReasoning": True,
        "expandShell": True,
    },
    "verifier": {
        "autoApprove": True,
        "showReasoning": True,
        "expandShell": True,
    },
    "builder": {
        "autoApprove": True,
        "showReasoning": True,
        "expandShell": True,
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
#  会话行为
# ═══════════════════════════════════════════════════════════════════════════════

# 默认使用的 agent（不传 agent 参数时）
DEFAULT_AGENT = None  # "verifier"

# 会话分享模式: "manual" / "auto" / "disabled"
SHARE_MODE = "disabled"

# 上下文压缩配置
COMPACTION = {
    "auto": 0.8,       # 上下文占用比例达到此值时自动压缩 (0.0 ~ 1.0)
    "prune": 0.5,      # 压缩后保留的比例
    "reserved": 4096,  # 保留给回复的 token 数
}


# ═══════════════════════════════════════════════════════════════════════════════
#  构建运行时 patch 体（供 node_patch_config 调用）
# ═══════════════════════════════════════════════════════════════════════════════

def build_runtime_patch() -> dict:
    """组装 PATCH /config 的请求体。"""
    patch: dict = {}

    # 全局权限
    if GLOBAL_PERMISSION is not None:
        patch["permission"] = GLOBAL_PERMISSION

    # agent 独立选项
    agent_updates: dict = {}
    for name, opts in AGENT_OPTIONS.items():
        agent_updates[name] = {"options": opts}
    if agent_updates:
        patch["agent"] = agent_updates

    return patch
