import os
from base64 import b64encode
from dataclasses import dataclass
from typing import Optional

import requests

# ═══════════════════════════════════════════════════════════════════════════════
#  配置区
# ═══════════════════════════════════════════════════════════════════════════════
BASE_URL = os.environ.get("OPENCODE_URL", "")
USERNAME = os.environ.get("OPENCODE_USER", "opencode")
PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "")


def _build_auth_header() -> dict:
    """根据是否设置了密码来构建认证头"""
    if PASSWORD:
        token = b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        return {"Authorization": f"Basic {token}"}
    return {}


AUTH_HEADER = _build_auth_header()


# ═══════════════════════════════════════════════════════════════════════════════
#  HTTP 请求底层封装
# ═══════════════════════════════════════════════════════════════════════════════
def _req(method: str, path: str, **kwargs) -> requests.Response:
    """统一 HTTP 请求封装：自动拼接 Base URL、注入认证头、设置超时。

    所有上层 API 调用都经过此函数，避免重复代码。
    """
    kwargs.setdefault("headers", {})
    kwargs["headers"].update(AUTH_HEADER)
    kwargs["headers"].setdefault("Accept", "application/json")
    kwargs.setdefault("timeout", 600)
    url = f"{BASE_URL.rstrip('/')}{path}"
    r = requests.request(method, url, **kwargs)
    r.raise_for_status()
    return r


# ═══════════════════════════════════════════════════════════════════════════════
#  Session 数据类 —— 封装所有会话相关 API
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class Session:
    """OpenCode 会话的 Python 封装。

    提供完整的 CRUD、消息交互、子会话管理、分享、回退等能力。
    实例方法操作当前会话，类方法可操作任意会话（无需先实例化）。
    """
    id: str
    title: str = ""

    # ── 会话 CRUD ──────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        title: str = "Audit",
        parent_id: Optional[str] = None,
        *,
        directory: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> "Session":
        """创建新会话。

        directory:  工作目录的绝对路径，决定 session 的 projectID 归属。
                    不传则使用服务端当前实例目录。
        project_id: 显式指定项目 ID，通常无需传（由 directory 自动推导）。
        """
        from mock import MOCK_ENABLED
        if MOCK_ENABLED:
            import uuid
            fake_id = "mock_" + uuid.uuid4().hex[:12]
            return cls(id=fake_id, title=title)

        body: dict = {"title": title}
        if parent_id:
            body["parentID"] = parent_id
        if directory:
            body["directory"] = directory
        if project_id:
            body["projectID"] = project_id
        data = _req("POST", "/session", json=body).json()
        return cls(id=data["id"], title=data.get("title", title))

    @classmethod
    def get(cls, session_id: str) -> "Session":
        """根据 ID 获取单个会话"""
        data = _req("GET", f"/session/{session_id}").json()
        return cls(id=data["id"], title=data.get("title", ""))

    @classmethod
    def list_all(cls) -> list[dict]:
        """列出所有会话"""
        return _req("GET", "/session").json()

    @classmethod
    def get_all_status(cls) -> dict:
        """获取所有会话的运行状态（idle / running / aborted 等）"""
        return _req("GET", "/session/status").json()

    @classmethod
    def delete_by_id(cls, session_id: str) -> bool:
        """【类方法】根据 ID 删除任意会话，不需要先持有 Session 实例。"""
        from mock import MOCK_ENABLED
        if MOCK_ENABLED:
            return True
        return _req("DELETE", f"/session/{session_id}").json()

    def update_title(self, title: str) -> dict:
        """修改当前会话标题"""
        return _req("PATCH", f"/session/{self.id}", json={"title": title}).json()

    def delete(self) -> bool:
        """删除当前会话（实例方法）"""
        return _req("DELETE", f"/session/{self.id}").json()

    def fork(self, message_id: Optional[str] = None) -> "Session":
        """从指定消息处派生（fork）一个新会话。

        如果不指定 message_id，则从当前最新状态派生。
        """
        body: dict = {}
        if message_id:
            body["messageID"] = message_id
        data = _req("POST", f"/session/{self.id}/fork", json=body).json()
        return Session(id=data["id"], title=data.get("title", ""))

    # ── 消息操作 ──────────────────────────────────────────────────────────

    def send(
        self,
        text: str,
        *,
        agent: Optional[str] = None,
        model: Optional[dict] = None,
        no_reply: bool = False,
        system: Optional[str] = None,
        message_id: Optional[str] = None,
        _timeout: Optional[float] = None,
    ) -> dict:
        """发送提示词并同步等待完整响应。

        model:   指定模型，格式 {"providerID": "deepseek", "modelID": "deepseek-chat"}
                 不传则使用默认模型。
        agent:   指定 Agent（名称），不传则使用默认 Agent。
        system:  覆盖 system prompt，仅本次消息生效。
        no_reply: True 时只注入上下文不触发 AI 回复。
        _timeout: HTTP 请求超时秒数，不传则使用默认 600s。

        返回: {"info": Message, "parts": [Part, ...]}
        """
        from mock import MOCK_ENABLED, get_response
        if MOCK_ENABLED:
            print(f"  [MOCK] 返回预置响应: {self.title}")
            return get_response(self.title)

        body: dict = {"parts": [{"type": "text", "text": text}]}
        if agent:
            body["agent"] = agent
        if model:
            body["model"] = model
        if no_reply:
            body["noReply"] = True
        if system:
            body["system"] = system
        if message_id:
            body["messageID"] = message_id
        return _req("POST", f"/session/{self.id}/message", json=body, timeout=_timeout or 600).json()

    def send_async(
        self, text: str, *, agent: Optional[str] = None,
        model: Optional[dict] = None, system: Optional[str] = None,
    ) -> None:
        """异步发送提示词，不等待响应（返回 204 No Content）。"""
        body: dict = {"parts": [{"type": "text", "text": text}]}
        if agent:
            body["agent"] = agent
        if model:
            body["model"] = model
        if system:
            body["system"] = system
        _req("POST", f"/session/{self.id}/prompt_async", json=body)

    def send_poll(
        self,
        text: str,
        *,
        agent: Optional[str] = None,
        model: Optional[dict] = None,
        system: Optional[str] = None,
        poll_interval: float = 5.0,
        max_wait: float = 3600.0,
    ) -> dict:
        """异步发送后轮询等待完成，再取回响应文本。

        比 send() 更智能：不会傻等 HTTP 超时，而是通过 /session/status
        实时监控会话是否已完成。完成后自动拉取消息提取文本。

        poll_interval: 轮询间隔秒数，默认 5s
        max_wait:      最大等待秒数，默认 3600s（1 小时）

        返回格式与 send() 一致: {"info": Message, "parts": [Part, ...]}
        """
        from mock import MOCK_ENABLED, get_response
        if MOCK_ENABLED:
            print(f"  [MOCK] 返回预置响应: {self.title}")
            return get_response(self.title)

        import time

        self.send_async(text, agent=agent, model=model, system=system)

        deadline = time.time() + max_wait
        seen_running = False
        while time.time() < deadline:
            try:
                statuses = _req("GET", "/session/status").json()
            except Exception:
                time.sleep(poll_interval)
                continue
            if self.id not in statuses:
                if seen_running:
                    break  # 会话已完成
                # 尚未注册到 status，等一会再查
                time.sleep(poll_interval)
                continue
            seen_running = True
            time.sleep(poll_interval)
        else:
            raise TimeoutError(
                f"会话 {self.id} 在 {max_wait}s 内未完成，请检查 opencode 可视化界面"
            )

        # 拉取最新消息，提取 assistant 的回复
        # 短暂等待消息持久化（session 完成 → 消息写入有微小延迟）
        time.sleep(2)
        messages = self.get_messages(limit=20)
        for msg in reversed(messages):
            info = msg.get("info", {})
            parts = msg.get("parts", [])
            if info.get("role") == "assistant" and parts:
                # 过滤出 text 类型的 part（排除 reasoning / step-start 等）
                text_parts = [p for p in parts if p.get("type") == "text"]
                if text_parts:
                    return {"info": info, "parts": parts}
        return {"info": {}, "parts": []}

    def send_command(
        self, command: str, arguments: Optional[str] = None, *, agent: Optional[str] = None
    ) -> dict:
        """执行一条斜杠命令（如 /undo、/review 等）。

        command: 命令名，不含斜杠，如 "review"
        arguments: 命令参数，如 "--pr 42"
        """
        body: dict = {"command": command}
        if arguments:
            body["arguments"] = arguments
        if agent:
            body["agent"] = agent
        return _req("POST", f"/session/{self.id}/command", json=body).json()

    def run_shell(self, command: str, *, agent: Optional[str] = None) -> dict:
        """在会话上下文中执行 shell 命令"""
        body: dict = {"command": command}
        if agent:
            body["agent"] = agent
        return _req("POST", f"/session/{self.id}/shell", json=body).json()

    def get_messages(self, limit: int = 50) -> list[dict]:
        """获取当前会话的消息列表"""
        return _req("GET", f"/session/{self.id}/message?limit={limit}").json()

    def get_message(self, message_id: str) -> dict:
        """获取指定消息的详情"""
        return _req("GET", f"/session/{self.id}/message/{message_id}").json()

    # ── 子会话 ────────────────────────────────────────────────────────────

    def get_children(self) -> list[dict]:
        """获取当前会话的所有子会话（fork 产生）"""
        return _req("GET", f"/session/{self.id}/children").json()

    def get_todos(self) -> list[dict]:
        """获取会话的 Todo 列表"""
        return _req("GET", f"/session/{self.id}/todo").json()

    def get_diff(self, message_id: Optional[str] = None) -> list[dict]:
        """获取会话产生的文件变更（diff）。

        可指定 message_id 来获取某条消息对应的变更。
        """
        params: dict = {}
        if message_id:
            params["messageID"] = message_id
        return _req("GET", f"/session/{self.id}/diff", params=params).json()

    # ── 会话控制 ──────────────────────────────────────────────────────────

    def abort(self) -> bool:
        """中止当前正在运行的会话"""
        return _req("POST", f"/session/{self.id}/abort").json()

    def share(self) -> dict:
        """分享当前会话，返回包含分享链接的 Session 对象"""
        return _req("POST", f"/session/{self.id}/share").json()

    def unshare(self) -> dict:
        """取消分享当前会话"""
        return _req("DELETE", f"/session/{self.id}/share").json()

    def summarize(self, provider_id: Optional[str] = None, model_id: Optional[str] = None) -> bool:
        """对当前会话进行摘要总结"""
        body: dict = {}
        if provider_id:
            body["providerID"] = provider_id
        if model_id:
            body["modelID"] = model_id
        return _req("POST", f"/session/{self.id}/summarize", json=body).json()

    def init(self, provider_id: Optional[str] = None, model_id: Optional[str] = None) -> bool:
        """分析项目并生成 AGENTS.md 文件"""
        body: dict = {}
        if provider_id:
            body["providerID"] = provider_id
        if model_id:
            body["modelID"] = model_id
        return _req("POST", f"/session/{self.id}/init", json=body).json()

    def revert(self, message_id: str, part_id: Optional[str] = None) -> bool:
        """回退（撤销）指定消息。

        message_id: 要回退到的消息 ID
        part_id: 可选，仅回退某个 part
        """
        body: dict = {"messageID": message_id}
        if part_id:
            body["partID"] = part_id
        return _req("POST", f"/session/{self.id}/revert", json=body).json()

    def unrevert(self) -> bool:
        """恢复所有被回退的消息"""
        return _req("POST", f"/session/{self.id}/unrevert").json()

    def respond_permission(
        self, permission_id: str, response: str, remember: bool = False
    ) -> bool:
        """响应权限请求（允许/拒绝某次工具调用）。

        response: "allow" 或 "deny"
        remember: 是否记住选择，避免后续重复询问
        """
        body: dict = {"response": response}
        if remember:
            body["remember"] = True
        return _req(
            "POST", f"/session/{self.id}/permissions/{permission_id}", json=body
        ).json()

    def __repr__(self):
        return f"Session(id={self.id!r}, title={self.title!r})"


# ═══════════════════════════════════════════════════════════════════════════════
#  配置管理（GET /config + PATCH /config）
# ═══════════════════════════════════════════════════════════════════════════════

def get_config() -> dict:
    """读取当前生效的完整配置"""
    return _req("GET", "/config").json()


def patch_config(**kwargs) -> dict:
    """部分更新配置，传入的键会合并到现有配置中。

    示例:
      patch_config(permission="allow")                      # 全局允许
      patch_config(agent={"build": {"options": {"autoApprove": True}}})
    """
    return _req("PATCH", "/config", json=kwargs).json()


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent 管理（通过 PATCH /config 动态注册 / 删除自定义 Agent）
# ═══════════════════════════════════════════════════════════════════════════════

# Agent permission 使用对象格式（注意：和 session 权限的数组格式不同）
#   {"*": "deny", "read": "allow", "bash": {"git *": "allow", "rm *": "deny"}}
#
# Agent mode:
#   "primary"  — 顶层会话使用
#   "subagent" — 作为子任务被主 Agent 调用

def create_agent(
    name: str,
    mode: str = "primary",
    *,
    description: str = "",
    permission: Optional[dict] = None,
    prompt: Optional[str] = None,
    temperature: Optional[float] = None,
) -> dict:
    """动态注册一个自定义 Agent（通过 PATCH /config，即时生效）。

    name:        Agent 名称，用于 send(agent=...) 中引用
    mode:        "primary"（顶层）或 "subagent"（子任务）
    permission:  工具权限，对象格式 {"*": "deny", "read": "allow"}
                 不传则继承全局默认权限
    prompt:      自定义 system prompt，不传则使用模型默认
    temperature: 生成温度，None 则使用全局默认

    注意：此方法通过 PATCH /config 实现，server 重启后丢失。
         如需持久化，请写入 opencode.json 配置文件。
    """
    agent_def: dict = {"mode": mode}
    if description:
        agent_def["description"] = description
    if permission is not None:
        agent_def["permission"] = permission
    if prompt is not None:
        agent_def["prompt"] = prompt
    if temperature is not None:
        agent_def["temperature"] = temperature
    return _req("PATCH", "/config", json={"agent": {name: agent_def}}).json()


def delete_agent(name: str) -> dict:
    """删除一个自定义 Agent。

    注意：只能删除通过 create_agent 注册的非 native Agent，
         built-in Agent（如 build/plan/explore）无法删除。
    """
    return _req("PATCH", "/config", json={"agent": {name: None}}).json()


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent 与文件操作（独立函数，不依赖 Session 实例）
# ═══════════════════════════════════════════════════════════════════════════════

def list_agents() -> list[dict]:
    """获取所有可用 Agent 列表"""
    return _req("GET", "/agent").json()


def list_files(path: str = "") -> list[dict]:
    """列出指定目录下的文件"""
    return _req("GET", "/file", params={"path": path}).json()


def read_file(path: str) -> str:
    """读取文件内容（返回原始文本）"""
    return _req("GET", "/file/content", params={"path": path}).text


def find_files(query: str, file_type: Optional[str] = None, directory: Optional[str] = None, limit: Optional[int] = None) -> list[str]:
    """按名称模糊搜索文件"""
    params: dict = {"query": query}
    if file_type:
        params["type"] = file_type
    if directory:
        params["directory"] = directory
    if limit:
        params["limit"] = limit
    return _req("GET", "/find/file", params=params).json()


def search_in_files(pattern: str) -> list[dict]:
    """按内容搜索（grep）"""
    return _req("GET", "/find", params={"pattern": pattern}).json()


def server_health() -> dict:
    """获取服务器健康状态和版本信息"""
    return _req("GET", "/global/health").json()


def list_projects() -> list[dict]:
    """列出所有项目"""
    return _req("GET", "/project").json()


def get_current_project() -> dict:
    """获取当前激活的项目"""
    return _req("GET", "/project/current").json()


# ═══════════════════════════════════════════════════════════════════════════════
#  模型与提供商管理
# ═══════════════════════════════════════════════════════════════════════════════

def list_providers() -> list[dict]:
    """列出所有可用的模型提供商及其模型

    返回: {"all": [Provider, ...]}
      每个 Provider 包含 id, name, models (dict: model_id → ModelInfo)
    """
    return _req("GET", "/provider").json()


def list_all_models() -> dict:
    """列出所有提供商及其模型、env 信息。

    返回: {provider_id: {"models": [model_id, ...], "env": [env_var, ...], "name": str}}
    """
    data = _req("GET", "/provider").json()
    result = {}
    for p in data.get("all", []):
        result[p["id"]] = {
            "models": list(p.get("models", {}).keys()),
            "env": p.get("env", []),
            "name": p.get("name", p["id"]),
        }
    return result


def get_models(provider_id: str) -> dict:
    """获取指定提供商的模型列表

    返回: {model_id: ModelInfo, ...}
      ModelInfo 包含 name, cost, limit, capabilities 等字段
    """
    data = _req("GET", "/provider").json()
    for p in data.get("all", []):
        if p["id"] == provider_id:
            return p.get("models", {})
    return {}


def get_model_info(provider_id: str, model_id: str) -> Optional[dict]:
    """获取指定模型的详细信息（限额、成本、能力等）"""
    models = get_models(provider_id)
    return models.get(model_id)


def get_default_model() -> dict:
    """获取当前默认使用的模型配置

    返回: {"providerID": str, "modelID": str} 或 {} 如未设置
    """
    data = _req("GET", "/config/providers").json()
    defaults = data.get("default", {})
    if defaults:
        # 取第一个默认配置
        mode = next(iter(defaults.values()), {})
        return mode
    return {}


def set_default_model(provider_id: str, model_id: str) -> dict:
    """设置默认使用的模型（通过 PATCH /config）

    provider_id: 提供商 ID，如 "deepseek", "302ai"
    model_id:    模型 ID，如 "deepseek-chat", "qwen3-235b-a22b"
    """
    return _req("PATCH", "/config", json={
        "mode": {"default": {"providerID": provider_id, "modelID": model_id}}
    }).json()


def list_commands() -> list[dict]:
    """列出所有可用的斜杠命令"""
    return _req("GET", "/command").json()


def set_auth(provider_id: str, api_key: str) -> bool:
    """为指定提供商设置 API 密钥"""
    body = {"type": "api", "key": api_key}
    return _req("PUT", f"/auth/{provider_id}", json=body).json()


# ═══════════════════════════════════════════════════════════════════════════════
#  MCP 服务器管理（动态注册 / 删除 / 查询）
# ═══════════════════════════════════════════════════════════════════════════════

# MCP 服务器类型：
#   "local"  — 本地子进程，通过 stdio 通信，需提供 command（命令数组）
#   "remote" — 远程 HTTP/SSE 服务，需提供 url

def list_mcp_servers() -> dict:
    """列出所有 MCP 服务器及其连接状态

    返回: {"server_name": {"status": "connected"|"failed", ...}, ...}
    """
    return _req("GET", "/mcp").json()


def add_mcp_server(
    name: str,
    server_type: str,
    *,
    command: Optional[list[str]] = None,
    url: Optional[str] = None,
    headers: Optional[dict] = None,
    enabled: bool = True,
) -> dict:
    """动态注册一个 MCP 服务器（通过 POST /mcp，即时生效）。

    name:        MCP 服务器名称（唯一标识）
    server_type: "local"（本地 stdio 进程）或 "remote"（远程 HTTP/SSE）
    command:     server_type="local" 时必传，命令数组 如 ["npx", "-y", "@anthropic/mcp-server"]
    url:         server_type="remote" 时必传，远程 MCP 端点 URL
    headers:     server_type="remote" 时可选的 HTTP 头 如 {"Authorization": "Bearer xxx"}
    enabled:     是否立即启用，默认 True

    示例:
      add_mcp_server("filesystem", "local",
          command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/path"])
      add_mcp_server("remote_tools", "remote",
          url="https://my-mcp-server.com/mcp")
    """
    config: dict = {"type": server_type}
    if server_type == "local":
        if not command:
            raise ValueError("server_type='local' 时必须提供 command 参数")
        config["command"] = command
    elif server_type == "remote":
        if not url:
            raise ValueError("server_type='remote' 时必须提供 url 参数")
        config["url"] = url
        if headers:
            config["headers"] = headers
    else:
        raise ValueError(f"不支持的 server_type: {server_type}，可选: local, remote")

    if not enabled:
        config["enabled"] = False

    return _req("POST", "/mcp", json={"name": name, "config": config}).json()


def add_mcp_server_via_config(name: str, config: dict) -> dict:
    """通过 PATCH /config 注册 MCP 服务器（与 add_mcp_server 等效，走配置路径）。

    适用于批量注册多个 MCP 服务器的场景。
    """
    return _req("PATCH", "/config", json={"mcp": {name: config}}).json()


def remove_mcp_server(name: str) -> dict:
    """删除一个 MCP 服务器（通过 PATCH /config 将其设为 null）"""
    return _req("PATCH", "/config", json={"mcp": {name: None}}).json()


# ═══════════════════════════════════════════════════════════════════════════════
#  二次开发封装（基于原始 API 组合而成）
# ═══════════════════════════════════════════════════════════════════════════════

def delete_all_sessions(keep_recent: int = 0) -> dict:
    """删除所有会话。

    keep_recent: 保留最近 N 个会话（按 updated 降序），默认 0 即全部删除。

    返回: {"total": int, "deleted": int, "kept": int, "errors": [str, ...]}
    """
    result = {"total": 0, "deleted": 0, "kept": 0, "errors": []}
    try:
        sessions = _req("GET", "/session").json()
    except Exception as e:
        result["errors"].append(f"获取会话列表失败: {e}")
        return result

    result["total"] = len(sessions)
    to_delete = sessions if keep_recent <= 0 else sessions[keep_recent:]

    for s in to_delete:
        sid = s["id"]
        try:
            _req("DELETE", f"/session/{sid}")
            result["deleted"] += 1
        except Exception as e:
            result["errors"].append(f"删除 {sid} 失败: {e}")

    result["kept"] = result["total"] - result["deleted"] - len(result["errors"])
    return result
