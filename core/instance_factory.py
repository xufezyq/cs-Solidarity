from typing import Callable, Dict, Any
import logging

log = logging.getLogger(__name__)

# 可扩展的类型注册表，值为从配置项创建实例的函数
_INSTANCE_TYPES: Dict[str, Callable[[Any], Any]] = {}

def register_instance_type(name: str, factory: Callable[[Any], Any]):
    """注册一个实例类型"""
    _INSTANCE_TYPES[name] = factory

def list_instance_types():
    """列出所有可用的实例类型名称"""
    return list(_INSTANCE_TYPES.keys())

def init_defaults():
    """初始化默认实例类型注册"""
    # 如果已经注册过，直接返回
    required_types = ['steam', 'daily', 'chat', 'infopush', 'korichat']
    if all(t in _INSTANCE_TYPES for t in required_types):
        return

    # 局部导入避免循环依赖
    try:
        from instances.steam_auto import SteamAuto
        from instances.daily_auto import DailyAuto
        from instances.chat_auto import ChatAuto
        from instances.kori_chat import KoriChatInstance
        from instances.info_push import InfoPush

        register_instance_type('steam', lambda data: SteamAuto.create_from_config(data.get('config')))
        register_instance_type('daily', lambda data: DailyAuto.create_from_data(data))
        register_instance_type('chat', lambda data: ChatAuto.create_from_config(data.get('config') or data))
        register_instance_type('korichat', lambda data: KoriChatInstance.create_from_config(data.get('config')))
        register_instance_type('infopush', lambda data: InfoPush.create_from_data(data))
    except ImportError as e:
        log.warning(f"导入实例模块失败: {e}")
        import traceback
        log.debug(traceback.format_exc())

def get_instance_from_item(item: Any):
    """
    从配置项创建实例：
    - 若为字典：读取其中的 type，走注册表创建；未指定 type 则默认 'steam'
    """
    init_defaults()

    if isinstance(item, dict):
        inst_type = item.get('type', 'steam')
        factory = _INSTANCE_TYPES.get(inst_type)
        if not factory:
            raise ValueError(f"未注册的实例类型: {inst_type}，可用类型: {list_instance_types()}")
        return factory(item)

    raise TypeError("instance项必须为字典（包含type）")
