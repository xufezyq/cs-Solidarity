"""
utils 包 — 懒加载，按需导入子模块
"""

def __getattr__(name):
    if name in ("human_delay", "human_typing_delay", "human_thinking_delay",
                "human_action_delay", "random_poll_interval"):
        from .human_sim import human_delay, human_typing_delay, human_thinking_delay
        from .human_sim import human_action_delay, random_poll_interval
        return locals()[name]

    if name in ("has_wechat_notification", "is_wechat_flashing"):
        from .flash_detector import has_wechat_notification, is_wechat_flashing
        return locals()[name]

    raise AttributeError(f"module 'utils' has no attribute {name!r}")
