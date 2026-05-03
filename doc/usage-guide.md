# 使用指南

## 安装

```bash
# 确保已安装 opencode CLI
opencode version

# 安装 Python 依赖（使用 uv）
uv sync
```

依赖：`requests`, `langgraph`

## 快速开始

### 1. 最简示例 —— 直接使用 client 层

```python
from opencode_workflow import Session

# 假设 opencode serve 已在 http://127.0.0.1:4096 运行
sess = Session.create(title="测试", directory="/path/to/project")
result = sess.send("解释这个项目是做什么的")
print(result["parts"][0]["text"])
sess.delete()
```

如果没有运行中的服务，可以先启动：
```bash
opencode serve --port 4096
```

### 2. 使用 task 层管理服务生命周期

```python
from opencode_workflow import open_serve, AgentConfig

with open_serve("/path/to/project") as task:
    # 动态注册一个只读 Agent
    task.create_agent(
        "reviewer",
        description="只读代码审查",
        permission=AgentConfig.readonly(),
    )

    # 创建会话并发送消息（指定 agent）
    sess = task.create_session("审查")
    result = sess.send("审查代码质量", agent="reviewer")
    print(result["parts"][0]["text"])

    # 退出 with 块自动停止服务
```

### 3. 使用编排层运行完整工作流

```python
from opencode_workflow.orchestrate import build_orchestration_graph, new_code_review_task

# 构建工作流图
graph = build_orchestration_graph()

# 准备初始状态
state = new_code_review_task("/path/to/project")

# 执行
final_state = graph.invoke(state)

# 查看报告
print(final_state["final_report"])
```

## 常见场景

### 场景 1: 代码审查 + 自动修复

编排层内置的 `new_code_review_task()` 预设了这个流程：

1. `code_reviewer`（只读）审查代码 → 输出问题列表
2. `code_fixer`（全权限）按方案修改代码
3. `code_reviewer` 复审修复结果
4. 生成最终报告，清理资源

```python
from opencode_workflow.orchestrate import build_orchestration_graph, new_code_review_task

graph = build_orchestration_graph()
state = new_code_review_task("/path/to/project")
final_state = graph.invoke(state)
```

### 场景 2: 自定义 Agent 权限

编辑 `src/opencode_workflow/agent_config/profiles.py` 或在运行时动态创建：

```python
from opencode_workflow import open_serve

with open_serve("/path/to/project") as task:
    # 自定义权限：允许编辑 Python 文件，其他只读
    task.create_agent(
        "python_editor",
        permission={
            "*": "deny",
            "read": "allow",
            "edit": {
                "*": "deny",
                "*.py": "allow",
            },
        },
    )
    sess = task.create_session("编辑任务")
    sess.send("重构所有 Python 文件的 import 顺序", agent="python_editor")
```

### 场景 3: 动态装配 MCP 服务器

```python
with open_serve("/path/to/project") as task:
    # 本地 MCP：文件系统操作
    task.add_mcp_server(
        "file_tools",
        server_type="local",
        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"],
    )

    # 远程 MCP：外部服务
    task.add_mcp_server(
        "api_tools",
        server_type="remote",
        url="https://tools.example.com/mcp",
        headers={"Authorization": "Bearer xxx"},
    )

    # 现在 Agent 可以同时使用两个 MCP 服务器的工具
    sess = task.create_session("数据处理")
    sess.send("从 /data 读取文件，通过 api_tools 上传处理结果")
```

### 场景 4: 自定义编排工作流

```python
from langgraph.graph import StateGraph, START, END
from opencode_workflow.orchestrate import OrchState, node_start_task, node_cleanup

# 基于现有节点构建自己的工作流
builder = StateGraph(OrchState)
builder.add_node("start", node_start_task)
# ... 添加自定义节点 ...
builder.add_node("cleanup", node_cleanup)
builder.add_edge(START, "start")
builder.add_edge("...", "cleanup")
builder.add_edge("cleanup", END)

my_graph = builder.compile()
```

### 场景 5: 多任务并行

```python
from opencode_workflow import OpenCodeTask, open_serve

# 启动两个独立的 opencode 服务
task_a = open_serve("/project_a")
task_b = open_serve("/project_b")

# 各自独立操作
sess_a = task_a.create_session("审查项目 A")
sess_b = task_b.create_session("审查项目 B")

# 各自清理
task_a.cleanup_my_sessions()
task_b.cleanup_my_sessions()
task_a.stop()
task_b.stop()
```

### 场景 6: 批量清理 + 模型切换

```python
with open_serve("/path/to/project") as task:
    # 切换默认模型
    task.set_default_model("deepseek", "deepseek-chat")

    # 查看可用模型
    models = task.list_all_models()
    print(models)  # {"deepseek": ["deepseek-chat", "deepseek-reasoner"], ...}

    # 执行多次任务...
    for i in range(5):
        sess = task.create_session(f"任务 {i}")
        sess.send("完成某项工作")

    # 一次性清理（保留最近 2 个）
    result = task.cleanup_all_sessions(keep_recent=2)
    print(f"删除了 {result['deleted']} 个会话，保留了 {result['kept']} 个")
```

## 注意事项

1. **Session 级权限不可用**: OpenCode v1.14.30 未实现 session 级工具权限拦截。请使用 Agent 权限控制
2. **Agent 权限格式**: Agent 权限使用对象格式 `{"*": "deny", "read": "allow"}`，与 Session 权限的数组格式不同
3. **Agent 不持久化**: 通过 `create_agent()` 注册的 Agent 在服务重启后丢失。如需持久化，写入 `opencode.json`
4. **MCP 注册后立即生效**: 已在运行中的 session 也能看到新注册的 MCP 工具
5. **无法动态注册 Skill**: Skill 只能通过 UI 或写入 `.opencode/skills/` 目录来注册
6. **端口分配**: `open_serve()` 不传端口时自动在 4096-5000 范围内查找可用端口
7. **认证**: 密码可通过环境变量 `OPENCODE_SERVER_PASSWORD` 设置

## 项目结构

```
opencode-study/
├── src/
│   └── opencode_workflow/
│       ├── __init__.py          # 包入口，导出公共 API
│       ├── client.py            # API 客户端层
│       ├── task.py              # 服务管理 / 任务层
│       ├── orchestrate.py       # LangGraph 编排层
│       └── agent_config/
│           ├── __init__.py
│           └── profiles.py      # Agent 配置字典
├── doc/
│   ├── architecture.md          # 架构文档
│   ├── api-reference.md         # API 参考
│   └── usage-guide.md           # 使用指南（本文件）
├── test/                        # 测试工作目录
├── pyproject.toml
└── uv.lock
```
