from .human_sim import (
    human_delay,
    human_typing_delay,
    human_thinking_delay,
    human_action_delay,
    random_poll_interval,
)
from .flash_detector import has_wechat_notification, is_wechat_flashing
from .notification_monitor import has_wechat_notification as has_wechat_notification_tray
