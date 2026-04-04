"""
Human-like simulation utilities
用于模拟人类操作行为，降低被检测为机器人的风险
"""
import random
import time


# ── 内部状态：模拟人类注意力漂移 ──
_prev_delay = None  # 上一次延迟值，用于产生连续感


def human_delay(min_ms=50, max_ms=300):
    """随机延迟，模拟人类操作间隔

    混合两种分布：
    - 70% 概率用高斯分布（集中在中间，模拟正常操作）
    - 30% 概率用重尾分布（偶尔长延迟，模拟走神/犹豫）
    """
    global _prev_delay
    avg = (min_ms + max_ms) / 2
    std = (max_ms - min_ms) / 6

    if random.random() < 0.3:
        # 重尾延迟：偶尔停顿很久（1.5x ~ 3x 上限）
        delay_ms = random.uniform(max_ms, max_ms * 3)
    else:
        # 带惯性的高斯：以上一次为锚点微调，而非每次都独立随机
        if _prev_delay and random.random() < 0.4:
            anchor = _prev_delay * random.uniform(0.7, 1.3)
            delay_ms = max(min_ms, min(max_ms, random.gauss(anchor, std)))
        else:
            delay_ms = max(min_ms, min(max_ms, random.gauss(avg, std)))

    _prev_delay = delay_ms
    time.sleep(delay_ms / 1000.0)


def human_typing_delay():
    """模拟打字间隔（30-150ms），对应正常打字速度"""
    human_delay(30, 150)


def human_thinking_delay():
    """模拟阅读/思考延迟（1-5秒）"""
    human_delay(1000, 5000)


def human_action_delay():
    """模拟操作间隔（0.3-1.5秒），如点击后等待"""
    human_delay(300, 1500)


def random_poll_interval(base=2.0, jitter=1.5):
    """生成随机轮询间隔，模拟人类注意力节奏

    使用对数正态分布：大部分间隔在 base 附近，
    但偶尔会出现 3-5 倍的长间隔（模拟走神/做别的事）。

    Args:
        base: 基础间隔（秒），默认2秒
        jitter: 抖动幅度（秒）
    """
    # 对数正态分布：长尾特性，更像人类的不均匀注意力
    mu = base
    sigma = jitter * 0.5
    interval = random.lognormvariate(
        0, sigma / mu if mu > 0 else 0.5
    ) + mu * 0.5
    # 钳制在合理范围：最短0.8秒，最长 base*5
    return max(0.8, min(interval, base * 5))


def random_human_pause():
    """模拟人类自然停顿（发呆、看手机、喝水等），2-8秒"""
    time.sleep(random.uniform(2, 8))
