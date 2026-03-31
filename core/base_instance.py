from abc import ABC, abstractmethod

class BaseInstance(ABC):
    """所有实例必须实现的统一接口"""

    @abstractmethod
    def send_message(self, message: str):
        """向目标发送消息；由 start_instances 在主线程调用"""
        pass

    @abstractmethod
    def start(self):
        """
        启动实例的调度循环（通常在子线程运行）
        - 子类内部调用 self.send_message 时，实际会被 start_instances 替换为入队函数
        """
        pass

    def handle_message(self, chat_name: str, message: str):
        """
        处理接收到的消息（可选实现）
        :param chat_name: 消息来源（群名或好友名）
        :param message: 消息内容
        """
        pass