"""Provider & 模型运行时能力 —— key 注入、模型发现、模型探测。

provider_id → env var 的映射关系从 opencode serve 的 GET /provider 动态获取，
不硬编码在代码里。"""

import os


def inject_keys(task) -> list[str]:
    """向 opencode serve 查询所有 provider，自动注入已设环境变量的 API key。

    返回成功注入的 provider_id 列表。
    """
    try:
        all_providers = task.list_all_models()
    except Exception as e:
        print(f"  [keys] 无法获取 provider 列表: {e}")
        return []

    injected = []
    for pid, info in sorted(all_providers.items()):
        for env_var in info.get("env", []):
            key = os.environ.get(env_var)
            if key:
                try:
                    task.set_auth(pid, key)
                    injected.append(pid)
                except Exception as e:
                    print(f"  [keys] {pid} 注入失败: {e}")
                break  # 只需一个 env var 匹配即可
    return injected


def disable_provider_timeout(task, provider_ids: list[str]) -> None:
    """关闭指定 provider 的超时限制，防止长时间任务被 opencode 内部截断。

    opencode 默认 provider 超时为 300s（5 分钟），设为 false 彻底关闭。
    """
    from server.client import _req

    task._use()
    for pid in provider_ids:
        try:
            _req("PATCH", "/config", json={
                "provider": {pid: {"options": {"timeout": False}}}
            })
            print(f"  [provider] {pid} 超时已关闭")
        except Exception as e:
            print(f"  [provider] {pid} 超时配置失败: {e}")


def discover_models(task) -> None:
    """列出当前环境中已配置 API key 的 provider 及其可用模型。"""
    try:
        raw = task.list_all_models()
    except Exception as e:
        print(f"  [models] 无法获取模型列表: {e}")
        return

    for pid, info in sorted(raw.items()):
        env_vars = info.get("env", [])
        if not env_vars or not any(os.environ.get(e) for e in env_vars):
            continue
        print(f"  provider_id: {pid}")
        print(f"  name:        {info['name']}")
        print(f"  env:         {', '.join(env_vars)}")
        print(f"  models:      {', '.join(info['models'])}")
        print()
