from .state import OrchState
from ..config.profiles import AGENTS


def new_audit_task(
    source_dir: str,
    workspace_dir: str,
    mock: bool = False,
    build_info: str = "",
    auto_build: bool = False,
    check_model: bool = False,
) -> OrchState:
    """创建 PHP 代码审计任务的初始状态。

    source_dir:    源码项目目录，dede.json 所在位置
    workspace_dir: 工作区目录，opencode serve 在此启动，opencode.json 写入此处
    mock:          是否启用 mock 模式（跳过 LLM 交互，使用预置响应）
    build_info:    CMS 搭建信息（markdown 文本），拼入 debuuger 验证提示词
    auto_build:    是否自动搭建 CMS 环境（启用 webcms_builder agent）

    使用 sink_reverse_digger + debuuger 完成审计；
    若 auto_build 则额外启用 webcms_builder 自动搭建 CMS。
    """
    agents = {
        "sink_reverse_digger": AGENTS["sink_reverse_digger"],
        "debuuger": AGENTS["debuuger"],
    }
    if auto_build:
        agents["webcms_builder"] = AGENTS["webcms_builder"]

    return OrchState(
        directory=workspace_dir,
        source_dir=source_dir,
        mock=mock,
        sessions=[],
        agents=agents,
        build_info=build_info,
        auto_build=auto_build,
        check_model=check_model,
        error="",
    )
