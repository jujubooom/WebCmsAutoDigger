import os


_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompt")


def _load(subpath: str) -> str:
    """加载 prompt 文件"""
    path = os.path.join(_PROMPT_DIR, subpath)
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


# ── User message 模板（含 {PLACEHOLDER}，由节点 .replace() 填充）────────
REVERSE_TRACE_TASK = _load("sink_reverse_digger/task_php.md")

# ── System prompt（作为 sess.send(system=...) 传入）────────────────────
DEBUUGER_SYSTEM = _load("debuuger/system_php.md")

# ── Agent 内嵌 prompt（写入 opencode.json agent.prompt 字段）───────────
BUILDER_SYSTEM = _load("webcms_builder/system.md")


class AgentConfig:
    """Agent 权限配置的快捷构建器。"""

    @staticmethod
    def readonly() -> dict:
        return {
            "*": "deny",
            "read": "allow",
            "grep": "allow",
            "glob": "allow",
            "list": "allow",
            "lsp": "allow",
            "external_directory": {
                "*": "allow",
            },
        }

    @staticmethod
    def full() -> dict:
        return {"*": "allow"}

AGENTS: dict = {
    "sink_reverse_digger": {
        "mode": "primary",
        "description": "sink点反向溯源专家，只读，追踪污点传播链",
        "permission": AgentConfig.readonly(),
        "model": {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
    },
    "debuuger": {
        "mode": "primary",
        "description": "调用链跟踪调试漏洞验证专家，具备完全权限",
        "permission": AgentConfig.full(),
        "model": {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
    },
    "webcms_builder": {
        "mode": "primary",
        "description": "Web CMS 自动化构建部署专家，使用 Docker 安装并启动 CMS",
        "permission": AgentConfig.full(),
        "prompt": BUILDER_SYSTEM,
        "model": {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
    },
}
