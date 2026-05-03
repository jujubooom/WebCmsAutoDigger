# API 参考

## client.py —— HTTP API 封装

### 全局配置

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BASE_URL` | `http://127.0.0.1:4096` | OpenCode 服务地址，可被 task 层动态切换 |
| `USERNAME` | `opencode` | HTTP Basic Auth 用户名 |
| `PASSWORD` | `""` | HTTP Basic Auth 密码 |

均可通过环境变量覆盖：
- `OPENCODE_URL` → `BASE_URL`
- `OPENCODE_USER` → `USERNAME`
- `OPENCODE_SERVER_PASSWORD` → `PASSWORD`

### Session 类

#### 创建 & 获取

```python
Session.create(title="...", directory="/path", parent_id=None)
Session.get(session_id)
Session.list_all()                    # → list[dict]
Session.get_all_status()              # → dict
Session.delete_by_id(session_id)      # 类方法，无需实例化
```

#### 实例方法

```python
sess.update_title("新标题")
sess.delete()
sess.fork(message_id=None)            # → Session
```

#### 消息操作

```python
sess.send(text, *, agent=None, model=None, no_reply=False, system=None, message_id=None)
sess.send_async(text, *, agent=None)
sess.send_command(command, arguments=None, *, agent=None)  # 如 command="review", arguments="--pr 42"
sess.run_shell(command, *, agent=None)
sess.get_messages(limit=50)
sess.get_message(message_id)
```

`send()` 返回值结构：
```json
{
  "info": {"id": "...", "role": "assistant", ...},
  "parts": [{"type": "text", "text": "..."}, {"type": "tool", ...}]
}
```

#### 子会话 & 文件

```python
sess.get_children()                   # → list[dict]
sess.get_todos()                      # → list[dict]
sess.get_diff(message_id=None)        # → list[dict]
```

#### 会话控制

```python
sess.abort()                          # 中止运行中的会话
sess.share()                          # 分享会话
sess.unshare()                        # 取消分享
sess.summarize(provider_id, model_id) # 摘要总结
sess.init(provider_id, model_id)      # 生成 AGENTS.md
sess.revert(message_id, part_id=None) # 回退到指定消息
sess.unrevert()                       # 恢复回退
sess.respond_permission(permission_id, "allow"|"deny", remember=False)
```

### Agent 管理

```python
create_agent(name, mode="primary", *,
    description="", permission=None, prompt=None, temperature=None)
delete_agent(name)
list_agents()                         # → list[dict]
```

权限格式（对象格式）：
```python
{
    "*": "deny",
    "read": "allow",
    "grep": "allow",
    "bash": {
        "git *": "allow",
        "rm *": "deny",
    }
}
```

### AgentConfig 预设

```python
from opencode_workflow import AgentConfig

AgentConfig.readonly()  # 只读权限
AgentConfig.full()      # 全权限 {"*": "allow"}
AgentConfig.custom({...})  # 自定义
```

### MCP 管理

```python
# 本地 stdio 型
add_mcp_server("name", "local", command=["npx", "-y", "..."])
# 远程 HTTP 型
add_mcp_server("name", "remote", url="https://...", headers={"Authorization": "..."})
# 查询 / 删除
list_mcp_servers()                    # → dict
remove_mcp_server("name")
```

### 模型管理

```python
list_all_models()                     # → {provider_id: [model_id, ...]}
get_models(provider_id)               # → {model_id: ModelInfo, ...}
get_model_info(provider_id, model_id) # → dict | None
get_default_model()                   # → {"providerID": ..., "modelID": ...}
set_default_model(provider_id, model_id)
```

### 批量操作

```python
delete_all_sessions(keep_recent=0)    # → {"total", "deleted", "kept", "errors"}
```

### 工具函数

```python
server_health()                       # → dict
list_projects()                       # → list[dict]
get_current_project()                 # → dict
list_files(path="")
read_file(path)                       # → str
find_files(query, file_type=None, directory=None, limit=None)
search_in_files(pattern)              # grep
list_commands()                       # 斜杠命令列表
set_auth(provider_id, api_key)        # 设置 API key
listen_events(stop_event)             # SSE 事件流监听
```

---

## task.py —— 服务生命周期

### OpenCodeTask

```python
@dataclass
class OpenCodeTask:
    directory: str                     # 工作目录
    port: int                          # 服务端口
    # _process: Popen                  # 子进程（内部）
    # _session_ids: list[str]          # 追踪的会话 ID（内部）
```

#### 属性

```python
task.base_url       # "http://127.0.0.1:{port}"
task.is_running     # 进程是否存活
```

#### 会话操作

```python
task.create_session(title="Task", **kwargs)  # → Session（自动追踪）
task.get_session(session_id)                 # → Session
task.list_all_sessions()                     # → list[dict]
task.list_my_sessions()                      # → list[dict]（仅本次任务创建的）
```

#### Agent / MCP / Model

```python
task.create_agent(name, mode="primary", **kwargs)
task.delete_agent(name)
task.add_mcp_server(name, server_type, *, command=None, url=None, headers=None, enabled=True)
task.remove_mcp_server(name)
task.list_mcp_servers()
task.list_all_models()
task.get_models(provider_id)
task.get_default_model()
task.set_default_model(provider_id, model_id)
```

#### 清理 & 控制

```python
task.cleanup_my_sessions()             # 仅删除本次任务创建的会话
task.cleanup_all_sessions(keep_recent=0)
task.stop()                            # SIGTERM → 10s → SIGKILL
task.health()                          # → dict
```

#### 上下文管理器

```python
with open_serve("/path/to/project") as task:
    sess = task.create_session("任务")
    sess.send("你好")
# 退出时自动 stop()
```

### open_serve()

```python
def open_serve(
    directory: str,
    port: int | None = None,           # None = 自动分配
    *,
    startup_timeout: float = 30.0,      # 健康检查超时
    extra_args: list[str] | None = None, # 额外 CLI 参数
) -> OpenCodeTask
```

---

## agent_config/profiles.py —— Agent 配置

```python
from opencode_workflow import AGENTS

AGENTS  # → dict[str, dict]

# 每个配置项结构:
{
    "mode": "primary" | "subagent",
    "description": "...",
    "permission": {...},       # Agent 权限对象
    "prompt": "...",           # 可选，自定义 system prompt
    "temperature": 0.5,        # 可选
}
```

内置 Agent：`code_reviewer`, `code_fixer`, `readonly`, `safe_bash`, `planner`

---

## orchestrate.py —— LangGraph 编排

### OrchState

```python
class OrchState(TypedDict, total=False):
    directory: str
    task: OpenCodeTask
    sessions: list[str]
    agents: dict[str, dict]
    analysis: str
    fix_plan: str
    fix_result: str
    review_result: str
    final_report: str
    error: str
    should_fix: bool
```

### 图构建

```python
graph = build_orchestration_graph()        # → 编译后的 StateGraph
final_state = graph.invoke(initial_state)  # 执行工作流
```

### 预设任务

```python
state = new_code_review_task("/path/to/project")
```

### 工作流节点

| 节点 | 说明 | Agent |
|---|---|---|
| `start_task` | 启动 opencode serve | - |
| `setup_agents` | 注册 Agent | - |
| `analyze` | 审查代码结构和质量 | `code_reviewer` |
| `plan_fix` | 生成修复方案 | 默认 |
| `execute_fix` | 执行代码修复 | `code_fixer` |
| `verify` | 复审修复结果 | `code_reviewer` |
| `skip_fix` | 跳过修复（无问题） | - |
| `report` | 生成最终报告 | - |
| `cleanup` | 清理会话、停止服务 | - |
