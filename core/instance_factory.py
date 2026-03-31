from typing import Callable, Dict, Any

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
        # 如果导入失败（例如在测试环境中可能找不到模块），则跳过注册
        print(f"警告：导入实例模块失败，原因：{e}")
        import traceback
        traceback.print_exc()
        pass

def get_instance_from_item(item: Any):
    """
    从配置项创建实例：
    - 若为字典：读取其中的 type，走注册表创建；未指定 type 则默认 'steam'
    """
    # 尝试确保默认类型已注册
    init_defaults()

    # 字典：读取类型并分发
    if isinstance(item, dict):
        inst_type = item.get('type', 'steam')
        factory = _INSTANCE_TYPES.get(inst_type)
        if not factory:
            raise ValueError(f"未注册的实例类型: {inst_type}，可用类型: {list_instance_types()}")
        return factory(item)

    raise TypeError("instance项必须为字典（包含type）")
