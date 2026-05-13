"""Mock 层：开启后不走 LLM，直接返回预置响应，方便调试验证流程。"""

import json
import os

MOCK_ENABLED = False
_MOCK_DIR = os.path.dirname(os.path.abspath(__file__))


def enable() -> None:
    global MOCK_ENABLED
    MOCK_ENABLED = True


def get_response(session_title: str) -> dict:
    """根据会话标题加载对应的 mock 响应文件。"""
    filename = session_title + ".json"
    path = os.path.join(_MOCK_DIR, filename)
    if not os.path.exists(path):
        return {
            "parts": [
                {"type": "text",
                 "text": f"[MOCK] 未找到 {filename}，请先在 mock/ 目录下创建该文件。"}
            ]
        }
    with open(path, encoding="utf-8") as f:
        return json.load(f)
