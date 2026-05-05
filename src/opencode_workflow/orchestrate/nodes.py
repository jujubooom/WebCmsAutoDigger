"""编排层节点函数 —— 工作流中每个步骤的具体实现。"""

import json
import os
import shutil
import subprocess
from base64 import b64encode
from collections import defaultdict

from .state import OrchState
from ..server import task as task_mgr
from ..config.agent_config import TRACER_TASK, TRACER_SYSTEM, VERIFIER_SYSTEM, AGENTS
from ..server.providers import inject_keys, discover_models, disable_provider_timeout

# autobuild 使用的 skill 来源路径（项目根目录下的 skills/）
_SKILL_SOURCE = os.path.join(os.path.dirname(__file__), "..", "skills")

# sss sink 扫描二进制
_SSS_BIN = os.path.join(os.path.dirname(__file__), "..", "helper", "sss")

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
    """加载全量 sink 点，按 (文件, 危险函数) 分组，初始化断点续跑进度。"""
    dede_path = os.path.join(state["directory"], "dede.json")
    if not os.path.exists(dede_path):
        state["error"] = f"dede.json 不存在: {dede_path}"
        return state

    with open(dede_path, encoding="utf-8") as f:
        all_items = json.load(f)

    state["dede_items"] = all_items

    # 按 (文件, 危险函数) 分组
    group_map: dict[tuple, list] = defaultdict(list)
    for item in all_items:
        key = (item["file"], item["sink"])
        group_map[key].append(item)

    groups = [
        {"file": file, "func": func, "items": items}
        for (file, func), items in group_map.items()
    ]
    # 按文件排序，同文件按函数名排序
    groups.sort(key=lambda g: (g["file"], g["func"]))

    state["groups"] = groups
    state["group_total"] = len(groups)

    # 初始化审计报告索引文件（断点续跑不覆盖）
    report_path = os.path.join(state["directory"], "audit_report.md")
    if not os.path.exists(report_path):
        source_dir = state.get("source_dir", state["directory"])
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(
                f"# 审计报告\n\n"
                f"源码目录: {source_dir}\n\n"
                f"| 漏洞类型 | 前置条件 | 详细报告路径 |\n"
                f"|---------|---------|------------|\n"
            )

    # 断点续跑：读取 progress.json，跳过已完成的组
    progress_path = os.path.join(state["directory"], "progress.json")
    done: set[int] = set()
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
        done = {e["group_index"] for e in progress.get("groups", []) if e.get("status") == "done"}

    idx = 0
    while idx < len(groups) and idx in done:
        idx += 1

    if idx >= len(groups):
        state["group_index"] = len(groups)
        print(f"全部 {len(groups)} 组已完成（共 {len(all_items)} 个 sink 点）")
    else:
        state["group_index"] = idx
        skipped = len(done)
        if skipped:
            print(f"断点续跑: 已完成 {skipped} 组，从第 #{idx + 1} 组开始")
        else:
            print(f"加载 {len(groups)} 组（共 {len(all_items)} 个 sink 点），开始审计")

    return state


def node_reverse_trace(state: OrchState) -> OrchState:
    """对当前分组进行反向污点追溯。

    拆分为两个独立对话：
      对话1 — 追溯分析 + 写入 trace_report.md + 维护 trace_kb.md
      对话2 — 读取报告，返回判定：可控 / 不可控
    """
    state.pop("error", None)
    groups = state.get("groups", [])
    idx = state.get("group_index", 0)
    total = state.get("group_total", len(groups))
    if idx >= len(groups):
        state["error"] = f"分组索引越界: {idx} >= {len(groups)}"
        return state

    group = groups[idx]
    file = group["file"]
    func = group["func"]
    items = group["items"]

    workspace = state["directory"]
    group_dir = os.path.join(workspace, "sinks", f"G{idx:04d}")
    os.makedirs(group_dir, exist_ok=True)
    trace_path = os.path.join(group_dir, "trace_report.md")

    sink_lines = []
    for item in items:
        sink_lines.append(
            f"- 行 {item['line']}, 变量 `{item['variable']}`: `{item['code']}`"
        )
    sink_list = "\n".join(sink_lines)

    task = state["task"]
    model = state["agents"]["tracer"].get("model")

    # ── 对话1: 追溯分析 + 写入报告 + 维护 trace_kb ──────────────
    trace_prompt = (TRACER_TASK
        .replace("{FILE_PATH}",  file)
        .replace("{SINK_FUNC}",  func)
        .replace("{SINK_LIST}",  sink_list)
        .replace("{TRACE_PATH}", trace_path))

    sess = task.create_session(f"追溯-G{idx + 1}")
    state["sessions"].append(sess.id)
    url = _record_session(state, task, f"追溯-G{idx + 1}", sess.id)
    print(f"[G{idx + 1}/{total}] 追溯 {func} @ {file}（{len(items)} 个 sink）→ {url}")

    sess.send_poll(trace_prompt, agent="tracer", system=TRACER_SYSTEM, model=model)
    print(f"[G{idx + 1}/{total}] 追溯完成")

    # 同一对话追加判定消息，模型有完整上下文
    verdict_prompt = "请基于以上追溯结果，判定这些 sink 点的调用链是否可控（能否被攻击者利用）。只回复一个词：可控 或 不可控。"
    try:
        v = sess.send(verdict_prompt, agent="tracer", model=model, _timeout=60)
        v_text = "\n".join(p["text"] for p in v.get("parts", []) if p["type"] == "text").strip()
        verdict = "uncontrollable" if "不可控" in v_text else "controllable"
    except Exception:
        verdict = "controllable"
    state["trace_verdict"] = verdict
    label = "可控" if verdict == "controllable" else "不可控"
    print(f"[G{idx + 1}/{total}] 判定: {label}")

    return state


def node_verify_vuln(state: OrchState) -> OrchState:
    """对当前分组的追溯结果进行漏洞验证，同 session 内追加摘要到审计报告。"""
    idx = state.get("group_index", 0)
    total = state.get("group_total", 0)
    group = state["groups"][idx]
    workspace = state["directory"]
    group_dir = os.path.join(workspace, "sinks", f"G{idx:04d}")
    trace_path = os.path.join(group_dir, "trace_report.md")
    verify_path = os.path.join(group_dir, "verify_report.md")
    audit_path = os.path.join(workspace, "audit_report.md")

    if not os.path.exists(trace_path):
        state["error"] = f"追溯报告不存在: {trace_path}"
        return state

    build_section = ""
    build_info = state.get("build_info", "")
    if build_info:
        build_section = f"## 目标环境信息\n\n{build_info}\n\n"

    task = state["task"]
    model = state["agents"]["verifier"].get("model")

    verify_prompt = (
        f"请读取 {trace_path} 中的追溯报告，在真实环境中验证这些漏洞是否可触发。\n\n"
        f"**目标文件**: {group['file']}\n"
        f"**危险函数**: {group['func']}\n"
        f"**Sink 数量**: {len(group['items'])}\n\n"
        f"{build_section}"
        f"完成后将详细验证报告写入 {verify_path}。"
    )

    sess = task.create_session(f"验证-G{idx + 1}")
    state["sessions"].append(sess.id)
    url = _record_session(state, task, f"验证-G{idx + 1}", sess.id)
    print(f"[G{idx + 1}/{total}] 漏洞验证中...... 访问 {url} 查看 agent 交互对话")

    sess.send_poll(verify_prompt, agent="verifier", system=VERIFIER_SYSTEM, model=model)
    print(f"[G{idx + 1}/{total}] 验证完成")

    # 同一对话追加摘要消息
    summary_prompt = (
        f"请基于以上验证结果，用一句话总结漏洞类型和利用前置条件。\n"
        f"然后读取 {audit_path}，在表格末尾追加一行：\n"
        f"| 漏洞类型 | 前置条件 | {group_dir}/ |\n"
        f"只写这一行，不要输出其他内容。"
    )
    try:
        sess.send(summary_prompt, agent="verifier", model=model)
    except Exception as e:
        print(f"[G{idx + 1}/{total}] 摘要写入失败: {e}")

    return state


def node_save_sink(state: OrchState) -> OrchState:
    """写入组信息和进度，前进到下一组。报告文件由 tracer/verifier 直接写入。"""
    idx = state.get("group_index", 0)
    total = state.get("group_total", 0)
    workspace = state["directory"]
    group_dir = os.path.join(workspace, "sinks", f"G{idx:04d}")

    # 写入组信息
    group = state["groups"][idx]
    with open(os.path.join(group_dir, "group_info.json"), "w", encoding="utf-8") as f:
        json.dump(group, f, ensure_ascii=False, indent=2)

    # 不可控时写入跳过标记（无需 AI）
    if state.get("trace_verdict") == "uncontrollable":
        verify_path = os.path.join(group_dir, "verify_report.md")
        with open(verify_path, "w", encoding="utf-8") as f:
            f.write("不可控，跳过验证\n")

    # 更新进度
    progress_path = os.path.join(workspace, "progress.json")
    progress: dict = {}
    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
    progress.setdefault("groups", []).append({"group_index": idx, "status": "done"})
    progress["group_total"] = total
    with open(progress_path, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

    state["group_index"] = idx + 1
    print(f"[G{idx + 1}/{total}] 已保存 → {group_dir}")
    return state


def node_generate_audit_report(state: OrchState) -> OrchState:
    """审计报告已由 verifier 逐组追加完成，此节点仅输出路径。"""
    report_path = os.path.join(state["directory"], "audit_report.md")
    print(f"审计报告: {report_path}")
    return state
