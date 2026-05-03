# OpenCode Workflow 架构文档

## 概述

`opencode_workflow` 是一个基于 OpenCode HTTP API 的多层编程控制框架，允许你以代码方式启动 OpenCode 服务、创建会话、注册 Agent、发送消息，以及使用 LangGraph 编排复杂的多 Agent / 多 Session 协作工作流。

## 四层架构

```
┌──────────────────────────────────────────────────────────┐
│  orchestrate.py  ← 编排层                                │
│  LangGraph StateGraph 驱动多 Agent / 多 Session 协作      │
│  定义工作流节点、条件路由、状态管理                         │
└────────────────────────┬─────────────────────────────────┘
                         │ 调用
┌────────────────────────▼─────────────────────────────────┐
│  task.py  ← 任务层                                       │
│  管理 opencode serve 生命周期（启停、健康检查）             │
│  会话追踪、批量清理、Agent/MCP/Model 动态装配               │
└────────────────────────┬─────────────────────────────────┘
                         │ 调用
┌────────────────────────▼─────────────────────────────────┐
│  agent_config/  ← 配置层（纯数据）                         │
│  profiles.py: 所有 Agent 的 mode / permission / prompt     │
│  独立模块，不依赖其他层，编排层按名字取值                     │
└────────────────────────┬─────────────────────────────────┘
                         │ 引用 AgentConfig 预设
┌────────────────────────▼─────────────────────────────────┐
│  client.py  ← 客户端层（API 封装）                         │
│  OpenCode HTTP API 的 Python 封装                         │
│  Session CRUD、消息交互、Agent/MCP/Model 管理               │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP
┌────────────────────────▼─────────────────────────────────┐
│  OpenCode HTTP Server                                    │
└──────────────────────────────────────────────────────────┘
```

## 各层职责

### client.py —— 客户端层

最底层的 HTTP API 封装，不依赖项目内任何其他模块。

- **`Session`**: 会话数据类，封装所有 session 相关 API（CRUD、消息、fork、abort、revert 等）
- **Agent 管理**: `create_agent()` / `delete_agent()` / `list_agents()`
- **MCP 管理**: `add_mcp_server()` / `remove_mcp_server()` / `list_mcp_servers()`
- **模型管理**: `list_all_models()` / `get_models()` / `get_default_model()` / `set_default_model()`
- **AgentConfig**: 权限预设构建器（`readonly()` / `full()` / `custom()`）
- **工具函数**: `delete_all_sessions()`、`server_health()`、`listen_events()` 等

特点：
- 全局 `BASE_URL` 变量，可被上层动态切换以支持多服务实例
- 所有 HTTP 请求经过 `_req()` 统一处理认证和错误

### task.py —— 任务层

以"一次 `opencode serve` 进程"作为任务单位进行封装。

- **`OpenCodeTask`**: 封装服务进程 + 会话追踪
  - 自动记录本次任务创建的所有 session ID
  - `cleanup_my_sessions()` 仅清理自己的会话
  - 支持 `with` 语句，退出时自动停止服务
- **`open_serve()`**: 工厂函数，启动子进程并等待健康检查通过

关键设计：
- 通过 `_use()` 方法动态设置 `client.BASE_URL`，支持同时运行多个任务互不干扰
- 与 `client.py` 的解耦通过模块级变量切换实现，无需传参

### agent_config/profiles.py —— 配置层

纯数据层，定义 Agent 配置字典。不包含任何业务逻辑。

- **`AGENTS`**: 字典，key 为 Agent 名称，value 为配置（mode、permission、description、prompt）
- 引用 `client.AgentConfig` 的静态方法获取权限预设（如 `readonly()`、`full()`）

内置 5 个预设 Agent：

| Agent 名称 | 权限 | 用途 |
|---|---|---|
| `code_reviewer` | 只读 + git 查看 | 代码审查 |
| `code_fixer` | 全权限 | 代码修复 |
| `readonly` | 仅读取/搜索 | 只读助手 |
| `safe_bash` | 全权限但禁 rm/sudo/chmod 777 | 安全运维 |
| `planner` | 只读 + 仅可写 `.opencode/plans/*.md` | 架构规划 |

### orchestrate.py —— 编排层

使用 LangGraph `StateGraph` 定义工作流，将多个 Agent 在多个 Session 中的协作串联起来。

- **`OrchState`**: 工作流全局状态（TypedDict），包含 directory、task、agent 配置、各阶段产出
- **工作流节点**: `start_task` → `setup_agents` → `analyze` → `plan_fix` → `execute_fix` → `verify` → `report` → `cleanup`
- **条件路由**: 分析后根据 `should_fix` 决定是否进入修复流程
- **`build_orchestration_graph()`**: 编译工作流图
- **`new_code_review_task()`**: 预设的「代码审查 + 自动修复」任务初始状态

## 数据流

```
new_code_review_task(directory)
  │  构造 OrchState，填充 agents 配置
  ▼
graph.invoke(state)
  │  LangGraph 按图结构依次执行节点
  ▼
node_start_task → open_serve() 启动 opencode 子进程
node_setup_agents → 遍历 agents 配置，调用 task.create_agent()
node_analyze → create_session + send("审查代码...", agent="code_reviewer")
  │  提取 text parts → analysis 文本
  │  判断 "无需修复" 是否在文本中 → should_fix
  ▼
route_after_analyze:
  ├── should_fix=True  → plan_fix → execute_fix → verify
  └── should_fix=False → skip_fix
  ▼
node_generate_report → 汇总所有阶段产物
node_cleanup → cleanup_my_sessions() + task.stop()
  ▼
final_state["final_report"]
```

## 设计原则

1. **层级单向依赖**: 上层调用下层，下层不感知上层。`client` 不依赖任何人，`agent_config` 只依赖 `client`，`task` 依赖 `client`，`orchestrate` 依赖 `task` + `client` + `agent_config`
2. **配置与逻辑分离**: Agent 配置（profiles.py）是纯数据，不包含任何运行逻辑
3. **多服务支持**: 通过模块级 `BASE_URL` 切换，`OpenCodeTask` 可管理独立的服务实例
4. **最小权限**: Agent 权限精确到工具级别，code_reviewer 只读，code_fixer 全权限
