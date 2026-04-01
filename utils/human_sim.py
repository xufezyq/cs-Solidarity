"""
Human-like simulation utilities
用于模拟人类操作行为，降低被检测为机器人的风险
"""
import random
import time


def human_delay(min_ms=50, max_ms=300):
    """随机延迟，模拟人类操作间隔

    Args:
        min_ms: 最小延迟毫秒数
        max_ms: 最大延迟毫秒数
    """
    # 使用正态分布，更接近人类的随机行为
    avg = (min_ms + max_ms) / 2
    std = (max_ms - min_ms) / 6  # 99.7% 的值在 min-max 范围内
    delay_ms = max(min_ms, min(max_ms, random.gauss(avg, std)))
    time.sleep(delay_ms / 1000.0)


def human_typing_delay():
    """模拟打字间隔（30-150ms），对应正常打字速度"""
    human_delay(30, 150)


def human_thinking_delay():
    """模拟阅读/思考延迟（0.5-3秒）"""
    human_delay(500, 3000)


def human_action_delay():
    """模拟操作间隔（0.2-1秒），如点击后等待"""
    human_delay(200, 1000)


def random_poll_interval(base=0.3, jitter=0.2):
    """生成随机轮询间隔，避免固定频率被检测

    Args:
        base: 基础间隔（秒）
        jitter: 抖动范围（秒），最终间隔 = base ± jitter
    """
    return base + random.uniform(-jitter, jitter)
