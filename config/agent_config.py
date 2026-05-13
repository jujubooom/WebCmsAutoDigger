import os


_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompt")


def _load(subpath: str) -> str:
    """加载 prompt 文件"""
    path = os.path.join(_PROMPT_DIR, subpath)
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


# ── User message 模板（含 {PLACEHOLDER}，由节点 .replace() 填充）────────
TRACER_TASK = _load("tracer/task_php.md")

# ── System prompt（作为 sess.send(system=...) 传入）────────────────────
TRACER_SYSTEM = _load("tracer/system_php.md")
VERIFIER_SYSTEM = _load("verifier/system_php.md")

# ── Agent 内嵌 prompt（写入 opencode.json agent.prompt 字段）───────────
BUILDER_SYSTEM = _load("builder/system.md")


class AgentConfig:
    """Agent 权限配置的快捷构建器。"""

    @staticmethod
    def full() -> dict:
        return {"*": "allow"}


AGENTS: dict = {
    "tracer": {
        "mode": "primary",
        "description": "反向污点追溯专家，具备完全权限",
        "permission": AgentConfig.full(),
        "prompt": TRACER_SYSTEM,
        "model": {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
    },
    "verifier": {
        "mode": "primary",
        "description": "漏洞验证专家，具备完全权限",
        "permission": AgentConfig.full(),
        "model": {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
    },
    "builder": {
        "mode": "primary",
        "description": "CMS 自动化构建部署专家",
        "permission": AgentConfig.full(),
        "prompt": BUILDER_SYSTEM,
        "model": {"providerID": "deepseek", "modelID": "deepseek-v4-flash"},
    },
}
