"""
OpenCode 服务管理层 —— 比 client 更高一级的封装。

核心概念：
  以每一次 opencode serve 生命周期作为一个"任务单位"(OpenCodeTask)，
  管理该任务中：服务进程启停、会话追踪、批量清理、Agent 注册。

层级关系：
  orchestrate  ← 编排层（LangGraph 工作流）
       ↓ 调用
  task         ← 你在这里：管理 serve 启停 + 会话追踪
       ↓ 调用
  client       ← 原始 API 封装
       ↓ 调用
  OpenCode HTTP Server

用法:
  with open_serve("/home/user/project") as task:
      sess = task.create_session("审查代码")
      task.create_agent("readonly", permission=AgentConfig.readonly())
      sess.send("审查所有 .py 文件", agent="readonly")
  # 退出 with 块时自动 stop serve，也可手动 task.cleanup() 清理会话
"""

import os
import subprocess
import time
import signal
import socket
from dataclasses import dataclass, field
from typing import Optional

import requests

from server import client as sdk


# ═══════════════════════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════════════════════

def _find_free_port(start: int = 4096, end: int = 5000) -> int:
    """在指定范围内查找一个可用端口"""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"在 {start}-{end} 范围内没有可用端口")


# ═══════════════════════════════════════════════════════════════════════════════
#  OpenCodeTask —— 一次 opencode serve 任务
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class OpenCodeTask:
    """封装一次 opencode serve 的完整生命周期。

    属性:
      directory  - 工作目录，所有 session 默认在此目录下操作
      port       - 服务端口
      is_running - 服务是否仍在运行
    """
    directory: str
    port: int
    _process: subprocess.Popen = field(repr=False)
    _session_ids: list[str] = field(default_factory=list, repr=False)

    @property
    def base_url(self) -> str:
        """当前任务的服务地址"""
        return f"http://127.0.0.1:{self.port}"

    @property
    def is_running(self) -> bool:
        """服务进程是否仍在运行"""
        return self._process.poll() is None

    # ── 内部：切换 SDK 目标 ──────────────────────────────────────────

    def _use(self) -> None:
        """将 client 的 BASE_URL 指向当前任务的服务。

        每次调用前都设置一次，确保多任务场景下不会串。
        """
        sdk.BASE_URL = self.base_url

    # ── 会话操作（自动追踪） ──────────────────────────────────────────

    def create_session(self, title: str = "Task", **kwargs) -> sdk.Session:
        """创建会话并自动记录到本次任务的追踪列表。

        自动注入 directory，确保 session 归属于当前工作目录。
        额外关键字参数透传给 sdk.Session.create()。
        """
        self._use()
        kwargs.setdefault("directory", self.directory)
        sess = sdk.Session.create(title=title, **kwargs)
        self._session_ids.append(sess.id)
        return sess

    def get_session(self, session_id: str) -> sdk.Session:
        """获取指定会话"""
        self._use()
        return sdk.Session.get(session_id)

    def list_all_sessions(self) -> list[dict]:
        """列出当前服务中的所有会话"""
        self._use()
        return sdk.Session.list_all()

    def list_my_sessions(self) -> list[dict]:
        """列出本次任务中创建的会话（通过 ID 追踪）"""
        all_sessions = {s["id"]: s for s in self.list_all_sessions()}
        return [all_sessions[sid] for sid in self._session_ids if sid in all_sessions]

    # ── Agent 管理 ────────────────────────────────────────────────────

    def create_agent(self, name: str, mode: str = "primary", **kwargs) -> dict:
        """在本次任务中动态注册 Agent"""
        self._use()
        return sdk.create_agent(name, mode=mode, **kwargs)

    def delete_agent(self, name: str) -> dict:
        """删除本次任务中注册的 Agent"""
        self._use()
        return sdk.delete_agent(name)

    # ── MCP 管理 ──────────────────────────────────────────────────────

    def add_mcp_server(
        self,
        name: str,
        server_type: str,
        *,
        command: Optional[list[str]] = None,
        url: Optional[str] = None,
        headers: Optional[dict] = None,
        enabled: bool = True,
    ) -> dict:
        """动态注册 MCP 服务器到本次任务"""
        self._use()
        return sdk.add_mcp_server(
            name, server_type,
            command=command, url=url, headers=headers, enabled=enabled,
        )

    def remove_mcp_server(self, name: str) -> dict:
        """删除本次任务中的 MCP 服务器"""
        self._use()
        return sdk.remove_mcp_server(name)

    def list_mcp_servers(self) -> dict:
        """列出当前所有 MCP 服务器状态"""
        self._use()
        return sdk.list_mcp_servers()

    # ── 模型管理 ──────────────────────────────────────────────────────

    def list_all_models(self) -> dict:
        """列出所有提供商的所有模型"""
        self._use()
        return sdk.list_all_models()

    def get_models(self, provider_id: str) -> dict:
        """获取指定提供商的模型列表"""
        self._use()
        return sdk.get_models(provider_id)

    def get_default_model(self) -> dict:
        """获取当前默认模型"""
        self._use()
        return sdk.get_default_model()

    def set_default_model(self, provider_id: str, model_id: str) -> dict:
        """设置本次任务使用的默认模型"""
        self._use()
        return sdk.set_default_model(provider_id, model_id)

    def set_auth(self, provider_id: str, api_key: str) -> bool:
        """注入 API key 到指定 provider"""
        self._use()
        return sdk.set_auth(provider_id, api_key)

    # ── 批量操作 ──────────────────────────────────────────────────────

    def cleanup_my_sessions(self) -> dict:
        """仅清理本次任务创建的会话"""
        self._use()
        result = {"total": len(self._session_ids), "deleted": 0, "errors": []}
        for sid in list(self._session_ids):
            try:
                sdk.Session.delete_by_id(sid)
                result["deleted"] += 1
                self._session_ids.remove(sid)
            except Exception as e:
                result["errors"].append(f"删除 {sid} 失败: {e}")
        return result

    def cleanup_all_sessions(self, keep_recent: int = 0) -> dict:
        """清理当前服务中所有会话"""
        self._use()
        return sdk.delete_all_sessions(keep_recent)

    # ── 服务控制 ──────────────────────────────────────────────────────

    def stop(self) -> None:
        """停止 opencode serve 进程（SIGTERM → 等 10s → SIGKILL 整个进程组）"""
        if not self.is_running:
            return
        try:
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return  # 进程已经不存在
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._process.wait()

    def health(self) -> dict:
        """查询服务健康状态"""
        self._use()
        return sdk.server_health()

    # ── 上下文管理器 ──────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def __repr__(self):
        status = "running" if self.is_running else "stopped"
        return (
            f"OpenCodeTask(dir={self.directory!r}, port={self.port}, "
            f"status={status}, sessions={len(self._session_ids)})"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  工厂函数
# ═══════════════════════════════════════════════════════════════════════════════

def open_serve(
    directory: str,
    port: Optional[int] = None,
    *,
    startup_timeout: float = 30.0,
    extra_args: Optional[list[str]] = None,
) -> OpenCodeTask:
    """在指定目录启动 opencode serve 并返回任务对象。

    directory:       工作目录，所有未指定 directory 的 session 将默认在此操作
    port:            服务端口，不传则自动分配可用端口
    startup_timeout: 等待服务就绪的超时秒数
    extra_args:      传给 opencode serve 的额外 CLI 参数，如 ["--cors", "http://localhost:3000"]

    返回:
      OpenCodeTask 对象，支持 with 语句，退出时自动停止服务。

    示例:
      with open_serve("/home/user/my-project") as task:
          sess = task.create_session("代码审查")
          sess.send("审查所有 .py 文件")
    """
    if port is None:
        port = _find_free_port()

    cmd = ["opencode", "serve", "--port", str(port)]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    env["OPENCODE_PERMISSION"] = '"allow"'

    proc = subprocess.Popen(
        cmd,
        cwd=directory,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 轮询等待服务就绪
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + startup_timeout
    last_error = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"opencode serve 进程异常退出，返回码: {proc.returncode}"
            )
        try:
            r = requests.get(f"{base_url}/global/health", timeout=2)
            if r.status_code == 200:
                break
        except requests.ConnectionError as e:
            last_error = e
        time.sleep(0.5)
    else:
        proc.kill()
        proc.wait()
        raise RuntimeError(
            f"opencode serve 启动超时 ({startup_timeout}s)，"
            f"最后连接错误: {last_error}"
        )

    return OpenCodeTask(directory=directory, port=port, _process=proc)
