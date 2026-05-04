"""编排层节点函数 —— 工作流中每个步骤的具体实现。"""

import json
import os
import shutil
import subprocess
from base64 import b64encode

from .state import OrchState
from ..server import task as task_mgr
from ..config.agent_config import TRACER_TASK, TRACER_SYSTEM, VERIFIER_SYSTEM, AGENTS
from ..server.providers import inject_keys, discover_models, disable_provider_timeout

# autobuild 使用的 skill 来源路径（项目根目录下的 skills/）
_SKILL_SOURCE = os.path.join(os.path.dirname(__file__), "..", "skills")

# sss sink 扫描二进制
_SSS_BIN = os.path.join(os.path.dirname(__file__), "..", "helper", "sss")

# 追溯可控判定
_VERDICT_PROMPT = (
    "请判定以上追溯结果中，该 sink 点的调用链是否可控（能否被攻击者利用）。\n"
    "只回复一个词：可控 或 不可控。不要输出其他内容。"
)


def _record_session(state: OrchState, task, title: str, session_id: str) -> str:
    """记录 session 对应的可视化 URL，供报告展示。返回 URL 字符串。"""
    if state.get("mock"):
        return ""
    encoded = b64encode(state["directory"].encode()).decode().rstrip("=")
    url = f"http://127.0.0.1:{task.port}/{encoded}/session/{session_id}"
    urls = state.setdefault("session_urls", [])
    urls.append({"title": title, "url": url})
    return url


def _copy_skills(workspace: str):
    """复制 webcms-installer skill 到 workspace/.opencode/skills/"""
    dst = os.path.join(workspace, ".opencode", "skills")
    if os.path.exists(dst):
        return  # 已存在，跳过
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(_SKILL_SOURCE, dst)
    names = os.listdir(_SKILL_SOURCE)
    print(f"[skills] {', '.join(names)} skill 已加载")


def node_write_agent_config(state: OrchState) -> OrchState:
    """在 workspace 目录写入 opencode.json，定义审计 Agent。mock 模式下创建假 task。"""
    workspace = state["directory"]
    os.makedirs(workspace, exist_ok=True)

    # autobuild 模式下，提前复制 skill 到 workspace（必须在 serve 启动前就位）
    if state.get("auto_build") and not state.get("mock"):
        _copy_skills(workspace)

    config = {"permission": "allow", "agent": {}}
    for name, cfg in state.get("agents", {}).items():
        config["agent"][name] = {
            "mode": cfg.get("mode", "primary"),
            "description": cfg.get("description", ""),
            "permission": cfg.get("permission", {}),
        }
        if "prompt" in cfg:
            config["agent"][name]["prompt"] = cfg["prompt"]

    path = os.path.join(workspace, "opencode.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    if state.get("mock"):
        from dataclasses import dataclass, field

        @dataclass
        class _MockTask:
            directory: str
            _session_ids: list = field(default_factory=list)

            def create_session(self, title: str = "Task", **kwargs):
                from ..server.client import Session
                kwargs.setdefault("directory", self.directory)
                sess = Session.create(title=title, **kwargs)
                self._session_ids.append(sess.id)
                return sess

            def cleanup_my_sessions(self):
                from ..server.client import Session
                for sid in list(self._session_ids):
                    try:
                        Session.delete_by_id(sid)
                    except Exception:
                        pass
                    self._session_ids.remove(sid)
                return {"total": 0, "deleted": 0, "errors": []}

            def stop(self):
                pass

            @property
            def is_running(self):
                return False

        state["task"] = _MockTask(directory=workspace)
        state.setdefault("sessions", [])
        print("[审计] Mock 模式：已创建虚拟 task")

    return state


def node_scan_sinks(state: OrchState) -> OrchState:
    """使用 sss 扫描源码目录，生成 dede.json 到工作目录。mock 模式跳过。"""
    if state.get("mock"):
        return state

    source_dir = state.get("source_dir", state["directory"])
    workspace = state["directory"]
    dede_path = os.path.join(workspace, "dede.json")

    try:
        result = subprocess.run(
            [_SSS_BIN, "-dir", source_dir, "-lang", "php", "-output", "json"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            state["error"] = f"sss 扫描失败: {result.stderr.strip()}"
            return state

        with open(dede_path, "w", encoding="utf-8") as f:
            f.write(result.stdout)

        items = json.loads(result.stdout)
        print(f"已扫描项目所有sink点，结果 {len(items)} 条")
    except FileNotFoundError:
        state["error"] = f"sss 二进制不存在: {_SSS_BIN}"
    except subprocess.TimeoutExpired:
        state["error"] = "sss 扫描超时（300s）"
    except json.JSONDecodeError as e:
        state["error"] = f"sss 输出解析失败: {e}"

    return state


def node_start_task(state: OrchState) -> OrchState:
    """在 workspace 目录启动 opencode serve"""
    task = task_mgr.open_serve(state["directory"], startup_timeout=60)
    state["task"] = task
    state.setdefault("sessions", [])
    return state


def node_inject_keys(state: OrchState) -> OrchState:
    """从环境变量注入所有 provider 的 API key 到 opencode serve，并关闭超时"""
    task = state["task"]
    injected = inject_keys(task)
    if injected:
        disable_provider_timeout(task, injected)
    return state


def node_patch_config(state: OrchState) -> OrchState:
    """通过 PATCH /config 注入 view_config.py 中定义的所有 UI / 行为选项"""
    if state.get("mock"):
        return state
    from ..config.view_config import build_runtime_patch
    from ..server.client import patch_config
    body = build_runtime_patch()
    patch_config(**body)
    print(f"[config] 已注入运行时配置: {list(body.keys())}")
    return state


def node_discover_models(state: OrchState) -> OrchState:
    """查询 opencode serve 中实际可用的模型，校验别名配置。
    仅 --checkmodel 模式下输出，正常审计时跳过。
    """
    if state.get("check_model"):
        discover_models(state["task"])
    return state


def node_autobuild(state: OrchState) -> OrchState:
    """使用 builder agent 自动搭建 CMS 环境，生成 build_info.md"""
    source_dir = state.get("source_dir", state["directory"])
    workspace = state["directory"]

    prompt = (
        f"请使用 webcms-installer skill，将以下源码目录构建为 Docker 容器并启动运行。\n\n"
        f"源码目录: {source_dir}\n\n"
        f"完成后务必在 {workspace}/build_info.md 中输出构建信息报告，"
        f"至少包含：访问 URL、后台地址、管理员账号密码、数据库连接信息。"
    )

    task = state["task"]
    sess = task.create_session("自动搭建CMS")
    state["sessions"].append(sess.id)
    url = _record_session(state, task, "自动搭建CMS", sess.id)
    print(f"项目自动构建中...... 访问 {url} 查看 agent 交互对话")

    model = state["agents"]["builder"].get("model")
    sess.send_poll(prompt, agent="builder", model=model)

    # AI 直接写入 build_info.md，此处读回供下游节点使用
    build_info_path = os.path.join(workspace, "build_info.md")
    if os.path.exists(build_info_path):
        with open(build_info_path, encoding="utf-8") as f:
            state["build_info"] = f.read()
        print(f"构建完成，报告已生成: {build_info_path}")
    else:
        print("警告: builder 未生成 build_info.md")
        state["build_info"] = ""

    return state


def node_setup_agents(state: OrchState) -> OrchState:
    """Agent 已在 opencode.json 中定义，服务启动时自动加载，此节点为空操作"""
    task = state["task"]
    for name in state.get("agents", {}):
        if name not in AGENTS:
            continue
        # opencode serve 自动从 opencode.json 加载 agent，只需验证存在
        try:
            task.create_agent(name, **state["agents"][name])
        except Exception:
            pass  # 已通过 opencode.json 加载，PATCH 可能冗余但无害
    return state


def node_probe_agents(state: OrchState) -> OrchState:
    """探测每个 agent 的 provider/model 是否能正常通信。

    对每个 agent 发送"你好"，验证模型可正常回复。
    若某 agent 无回复或异常，打印警告并建议通过 config/agent_config.py 切换 provider/model。
    """
    if state.get("mock"):
        print("[探测] Mock 模式，跳过连通性探测")
        return state

    task = state["task"]
    agents = state.get("agents", {})
    if not agents:
        return state

    failed: list[str] = []
    for name, cfg in agents.items():
        model = cfg.get("model")
        if not model:
            continue

        provider = model.get("providerID", "?")
        model_id = model.get("modelID", "?")
        try:
            sess = task.create_session(f"探测-{name}")
            state["sessions"].append(sess.id)
            result = sess.send("你好", agent=name, model=model, _timeout=15)
            text_parts = [p["text"] for p in result.get("parts", []) if p.get("type") == "text"]
            reply = "".join(text_parts).strip()
            if not reply:
                print(f"[探测] ❌ {name} ({provider}/{model_id}) 无回复")
                failed.append(name)
        except Exception as exc:
            print(f"[探测] ❌ {name} ({provider}/{model_id}) 异常: {exc}")
            failed.append(name)

    if failed:
        print("[探测] ⚠️  以下 agent 连通性探测失败: " + ", ".join(failed))
        print("[探测] 可能原因: 网络问题 或 opencode provider 兼容层问题")
        print("[探测] 建议: 通过 config/agent_config.py 切换 provider 和 model")
    else:
        print("[探测] 模型连接正常")

    return state


def node_cleanup(state: OrchState) -> OrchState:
    """停止服务"""
    task = state["task"]
    task.stop()
    print("服务已停止")
    return state


# ═══════════════════════════════════════════════════════════════════════════════
#  审计工作流节点
# ═══════════════════════════════════════════════════════════════════════════════

def node_load_dede(state: OrchState) -> OrchState:
    """加载全量 sink 点，初始化断点续跑进度。"""
    dede_path = os.path.join(state["directory"], "dede.json")
    if not os.path.exists(dede_path):
        state["error"] = f"dede.json 不存在: {dede_path}"
        return state

    with open(dede_path, encoding="utf-8") as f:
        all_items = json.load(f)

    state["dede_items"] = all_items
    state["sink_total"] = len(all_items)

    # 断点续跑：读取 progress.json，跳过已完成的
    progress_path = os.path.join(state["directory"], "progress.json")
    done: set[int] = set()
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
        done = {e["index"] for e in progress.get("sinks", []) if e.get("status") == "done"}

    # 找到第一个未完成的 sink
    idx = 0
    while idx < len(all_items) and idx in done:
        idx += 1

    if idx >= len(all_items):
        state["sink_index"] = len(all_items)  # 全部完成
        print(f"全部 {len(all_items)} 条 sink 点已完成")
    else:
        state["sink_index"] = idx
        skipped = len(done)
        if skipped:
            print(f"断点续跑: 已完成 {skipped} 条，从 #{idx + 1} 开始")
        else:
            print(f"加载 {len(all_items)} 条 sink 点，开始审计")

    return state


def node_reverse_trace(state: OrchState) -> OrchState:
    """对当前 sink 点进行反向污点追溯"""
    items = state.get("dede_items", [])
    idx = state.get("sink_index", 0)
    total = state.get("sink_total", len(items))
    if idx >= len(items):
        state["error"] = f"sink 索引越界: {idx} >= {len(items)}"
        return state

    item = items[idx]
    var_name = item["variable"]
    var_short = var_name.lstrip("$")
    prompt = (TRACER_TASK
        .replace("{FILE_PATH}",       item["file"])
        .replace("{LINE}",            str(item["line"]))
        .replace("{SINK_CODE}",       item["code"])
        .replace("{VAR_NAME}",        var_name)
        .replace("{VAR_SHORT_NAME}",  var_short))

    task = state["task"]
    title = f"追溯-#{idx + 1}"
    sess = task.create_session(title)
    state["sessions"].append(sess.id)
    url = _record_session(state, task, title, sess.id)
    print(f"[{idx + 1}/{total}] 反向污点追溯中...... 访问 {url} 查看 agent 交互对话")

    model = state["agents"]["tracer"].get("model")
    result = sess.send_poll(prompt, agent="tracer", system=TRACER_SYSTEM, model=model)
    text_parts = [p["text"] for p in result.get("parts", []) if p["type"] == "text"]
    state["trace_report"] = "\n".join(text_parts)
    print(f"[{idx + 1}/{total}] 追溯完成")

    # 判定调用链可控性
    try:
        v = sess.send(_VERDICT_PROMPT, agent="tracer", model=model, _timeout=30)
        v_text = "\n".join(p["text"] for p in v.get("parts", []) if p["type"] == "text").strip()
        verdict = "controllable" if "可控" in v_text and "不可控" not in v_text else "uncontrollable"
    except Exception:
        verdict = "controllable"  # 判定失败默认走验证
    state["trace_verdict"] = verdict
    label = "可控" if verdict == "controllable" else "不可控"
    print(f"[{idx + 1}/{total}] 判定: {label}")

    return state


def node_verify_vuln(state: OrchState) -> OrchState:
    """对当前 sink 的追溯结果进行漏洞验证"""
    trace_report = state.get("trace_report", "")
    if not trace_report:
        state["error"] = "追溯报告为空，跳过验证"
        return state

    idx = state.get("sink_index", 0)
    total = state.get("sink_total", 0)
    build_info = state.get("build_info", "")
    build_section = ""
    if build_info:
        build_section = f"## 目标环境信息\n\n{build_info}\n\n"

    user_prompt = (
        "以下是反向污点追溯的报告，请根据报告中的调用链信息，"
        "在真实环境中验证这些漏洞是否可触发。\n\n"
        f"{build_section}"
        f"# 追溯报告\n\n{trace_report}"
    )

    task = state["task"]
    title = f"验证-#{idx + 1}"
    sess = task.create_session(title)
    state["sessions"].append(sess.id)
    url = _record_session(state, task, title, sess.id)
    print(f"[{idx + 1}/{total}] 漏洞验证中...... 访问 {url} 查看 agent 交互对话")

    model = state["agents"]["verifier"].get("model")
    result = sess.send_poll(user_prompt, agent="verifier", system=VERIFIER_SYSTEM, model=model)
    text_parts = [p["text"] for p in result.get("parts", []) if p["type"] == "text"]
    state["verify_report"] = "\n".join(text_parts)
    print(f"[{idx + 1}/{total}] 验证完成")

    return state


def node_save_sink(state: OrchState) -> OrchState:
    """保存当前 sink 的追溯和验证报告，更新进度，前进到下一条。"""
    idx = state.get("sink_index", 0)
    total = state.get("sink_total", 0)
    workspace = state["directory"]

    # per-sink 目录
    sink_dir = os.path.join(workspace, "sinks", f"{idx:04d}")
    os.makedirs(sink_dir, exist_ok=True)

    trace_path = os.path.join(sink_dir, "trace_report.md")
    with open(trace_path, "w", encoding="utf-8") as f:
        f.write(state.get("trace_report", ""))

    verdict = state.get("trace_verdict", "controllable")
    verify_path = os.path.join(sink_dir, "verify_report.md")
    if verdict == "uncontrollable":
        with open(verify_path, "w", encoding="utf-8") as f:
            f.write("不可控，跳过验证\n")
    else:
        with open(verify_path, "w", encoding="utf-8") as f:
            f.write(state.get("verify_report", ""))

    # 更新 progress.json
    progress_path = os.path.join(workspace, "progress.json")
    progress: dict = {}
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
    progress.setdefault("sinks", []).append({"index": idx, "status": "done"})
    progress["total"] = total
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

    state["sink_index"] = idx + 1
    print(f"[{idx + 1}/{total}] 已保存 → {sink_dir}")
    return state


def node_generate_audit_report(state: OrchState) -> OrchState:
    """汇总所有 sink 的审计结果，生成结构化最终报告。"""
    workspace = state["directory"]
    source_dir = state.get("source_dir", workspace)
    total = state.get("sink_total", 0)
    sinks_dir = os.path.join(workspace, "sinks")

    lines = [
        "# PHP 代码审计报告",
        "",
        f"**源码目录**: {source_dir}",
        f"**Sink 总数**: {total}",
        "",
        "---",
        "",
    ]

    for i in range(total):
        sd = os.path.join(sinks_dir, f"{i:04d}")
        trace_path = os.path.join(sd, "trace_report.md")
        verify_path = os.path.join(sd, "verify_report.md")

        item = state["dede_items"][i] if i < len(state["dede_items"]) else {}
        done = os.path.exists(trace_path)
        status = "✅ 已完成" if done else "⏳ 未审计"

        lines.append(f"## Sink #{i + 1}  {status}")
        lines.append("")
        lines.append(f"- **文件**: `{item.get('file', '?')}`")
        lines.append(f"- **行号**: {item.get('line', '?')}")
        lines.append(f"- **变量**: `{item.get('variable', '?')}`")
        lines.append(f"- **代码**: `{item.get('code', '?')}`")
        lines.append("")

        if done:
            with open(trace_path, encoding="utf-8") as f:
                trace = f.read()
            lines.append("### 追溯分析")
            lines.append("")
            lines.append(trace)
            lines.append("")

            with open(verify_path, encoding="utf-8") as f:
                verify = f.read()
            lines.append("### 漏洞验证")
            lines.append("")
            lines.append(verify)
            lines.append("")

        lines.append("---")
        lines.append("")

    state["final_report"] = "\n".join(lines)

    report_path = os.path.join(workspace, "audit_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(state["final_report"])
    print(f"审计报告已生成: {report_path}")
    return state
