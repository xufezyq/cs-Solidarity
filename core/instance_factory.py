from typing import Callable, Dict, Any
from instances.steam_auto import SteamAuto
from instances.daily_auto import DailyAuto
from instances.pw_monitor_auto import PWMonitorAuto
from instances.pw_stats_auto import PWStatsAuto

# 可扩展的类型注册表，值为从配置项创建实例的函数
_INSTANCE_TYPES: Dict[str, Callable[[Any], Any]] = {}

def register_instance_type(name: str, factory: Callable[[Any], Any]):
    """注册一个实例类型"""
    _INSTANCE_TYPES[name] = factory

def list_instance_types():
    """列出所有可用的实例类型名称"""
    return list(_INSTANCE_TYPES.keys())

def get_instance_from_item(item: Any):
    """
    从配置项创建实例：
    - 若为字典：读取其中的 type，走注册表创建；未指定 type 则默认 'steam'
    """
    # 字典：读取类型并分发
    if isinstance(item, dict):
        inst_type = item.get('type', 'steam')
        factory = _INSTANCE_TYPES.get(inst_type)
        if not factory:
            raise ValueError(f"未注册的实例类型: {inst_type}，可用类型: {list_instance_types()}")
        return factory(item)

    raise TypeError("instance项必须为字典（包含type）")

# 默认注册
def _register_defaults():
    register_instance_type('steam', lambda data: SteamAuto.create_from_config(data.get('config')))
    register_instance_type('daily', lambda data: DailyAuto.create_from_data(data))
    register_instance_type('pw_monitor', lambda data: PWMonitorAuto.create_from_config(data.get('config')))
    register_instance_type('pw_stats', lambda data: PWStatsAuto.create_from_config(data.get('config')))

_register_defaults()