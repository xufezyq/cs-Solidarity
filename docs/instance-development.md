# 实例开发指南

本文档介绍如何为 cs-Solidarity 开发新的功能实例。

## 目录

- [实例基类](#实例基类)
- [创建新实例](#创建新实例)
- [实例注册](#实例注册)
- [消息收发](#消息收发)
- [配置管理](#配置管理)
- [最佳实践](#最佳实践)

---

## 实例基类

所有实例都继承自 `BaseInstance`：

```python
# core/base_instance.py
class BaseInstance(ABC):
    def __init__(self, item):
        self.item = item  # 配置项
        self.name = item.get('name', 'unknown')
        self.msg_queue = None  # 由主线程注入
        self.wx = None  # 由主线程注入
    
    @abstractmethod
    def send_message(self, message: str):
        """发送消息（被主线程 hook 为入队）"""
        pass
    
    @abstractmethod
    def start(self):
        """后台循环（子线程运行）"""
        pass
    
    def handle_message(self, chat_name, msg):
        """接收消息（可选实现）"""
        pass
```

---

## 创建新实例

### 1. 创建实例文件

在 `instances/` 目录创建新文件，例如 `my_instance.py`：

```python
# instances/my_instance.py
from core.base_instance import BaseInstance
import time

class MyInstance(BaseInstance):
    """我的自定义实例"""
    
    def __init__(self, item):
        super().__init__(item)
        self.config = item.get('config', {})
        self.target_group = self.config.get('target_group', '文件传输助手')
    
    def send_message(self, message: str):
        """发送消息到队列"""
        if self.msg_queue:
            self.msg_queue.put((self.name, {
                "target": self.target_group,
                "content": message
            }))
    
    def start(self):
        """后台循环"""
        while True:
            try:
                # 你的业务逻辑
                # 例如：每小时发送一次问候
                self.send_message("早上好！")
                time.sleep(3600)
            except Exception as e:
                print(f"[{self.name}] 错误：{e}")
                time.sleep(60)
    
    def handle_message(self, chat_name, msg):
        """接收并处理消息"""
        content = msg.content if hasattr(msg, 'content') else str(msg)
        print(f"[{self.name}] 收到消息：{chat_name} - {content}")
```

### 2. 实现核心方法

#### `send_message(message)`

发送消息到队列，由主线程统一发送：

```python
def send_message(self, message: str):
    self.msg_queue.put((self.name, {
        "target": self.target_group,
        "content": message,
        "at": ["某人"]  # 可选：@某人
    }))
```

#### `start()`

后台循环，运行独立业务逻辑：

```python
def start(self):
    while True:
        # 业务逻辑
        time.sleep(interval)
```

#### `handle_message(chat_name, msg)` (可选)

接收并处理新消息：

```python
def handle_message(self, chat_name, msg):
    content = msg.content if hasattr(msg, 'content') else str(msg)
    
    # 检查是否触发
    if content.startswith('/trigger'):
        response = self.process(content)
        self.send_message(response)
```

---

## 实例注册

### 1. 注册到工厂

在 `core/instance_factory.py` 注册新实例类型：

```python
# core/instance_factory.py
from instances.my_instance import MyInstance

INSTANCE_TYPES = {
    'steam': SteamAuto,
    'daily': DailyAuto,
    'chat': ChatAuto,
    'korichat': KoriChat,
    'infopush': InfoPush,
    'myinstance': MyInstance,  # 新增
}
```

### 2. 配置使用

在 `config.json` 中添加配置：

```json
{
  "instances": [
    {
      "type": "myinstance",
      "name": "我的实例",
      "config": {
        "target_group": "文件传输助手",
        "interval": 3600
      }
    }
  ]
}
```

---

## 消息收发

### 发送消息

**不要直接调用 wxauto！** 使用队列机制：

```python
# ✅ 正确方式
def send_message(self, message: str):
    self.msg_queue.put((self.name, {
        "target": self.target_group,
        "content": message
    }))

# ❌ 错误方式（直接在后台线程操作微信 GUI）
def send_message(self, message: str):
    wx.SendMsg(message, who=self.target_group)  # 可能导致崩溃
```

### 接收消息

实现 `handle_message()` 接收新消息：

```python
def handle_message(self, chat_name, msg):
    content = msg.content if hasattr(msg, 'content') else str(msg)
    
    # 检查触发条件
    if self.trigger_prefix in content:
        # 处理消息
        response = self.process(content)
        self.send_message(response)
```

### 触发前缀

设置触发前缀，只有包含前缀的消息才会路由到你的实例：

```python
class MyInstance(BaseInstance):
    trigger_prefix = '/mycmd'  # 只有包含 /mycmd 的消息才会路由到这里
    
    def handle_message(self, chat_name, msg):
        # 这个方法只会在消息包含 /mycmd 时被调用
        pass
```

如果不设置 `trigger_prefix`，实例会接收所有消息（默认实例）。

---

## 配置管理

### 1. 配置文件结构

在 `instconfig/` 目录创建配置文件：

```json
{
  "target_group": "文件传输助手",
  "interval": 3600,
  "message": "早上好！",
  "enabled": true
}
```

### 2. 加载配置

在 `__init__()` 中加载配置：

```python
def __init__(self, item):
    super().__init__(item)
    
    # 从配置文件加载
    config_path = item.get('config')
    if isinstance(config_path, str):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)
    else:
        self.config = config_path or {}
    
    # 提取配置项
    self.target_group = self.config.get('target_group', '文件传输助手')
    self.interval = self.config.get('interval', 3600)
```

### 3. 配置验证

验证配置的合法性：

```python
def __init__(self, item):
    super().__init__(item)
    
    self.config = self._load_config(item)
    self._validate_config()

def _validate_config(self):
    """验证配置合法性"""
    if not isinstance(self.config.get('interval'), (int, float)):
        raise ValueError("interval 必须是数字")
    
    if self.config.get('interval', 0) < 0:
        raise ValueError("interval 不能为负数")
```

---

## 最佳实践

### 1. 线程安全

- **不要**在后台线程直接操作微信 GUI
- 使用 `msg_queue` 发送消息
- 使用锁保护共享资源

```python
# ✅ 正确方式
import threading

class MyInstance(BaseInstance):
    def __init__(self, item):
        super().__init__(item)
        self.lock = threading.Lock()
        self.counter = 0
    
    def increment_counter(self):
        with self.lock:
            self.counter += 1
```

### 2. 错误处理

捕获并记录错误，避免崩溃：

```python
def start(self):
    while True:
        try:
            # 业务逻辑
            pass
        except Exception as e:
            import logging
            logging.error(f"[{self.name}] 错误：{e}")
            import traceback
            logging.debug(traceback.format_exc())
            time.sleep(60)  # 错误后等待一段时间
```

### 3. 反检测

添加随机延迟，模拟人类行为：

```python
from utils.human_sim import human_delay

def start(self):
    while True:
        try:
            # 发送前随机等待
            human_delay(500, 2000)
            
            self.send_message("你好！")
            
            # 发送后随机等待
            human_delay(1000, 3000)
            
            time.sleep(3600)
        except Exception as e:
            # ...
```

### 4. 日志记录

使用日志记录重要事件：

```python
import logging

class MyInstance(BaseInstance):
    def start(self):
        logging.info(f"[{self.name}] 启动成功")
        
        while True:
            try:
                logging.debug(f"[{self.name}] 执行任务...")
                # ...
            except Exception as e:
                logging.error(f"[{self.name}] 错误：{e}")
```

### 5. 资源清理

在实例停止时清理资源：

```python
class MyInstance(BaseInstance):
    def __init__(self, item):
        super().__init__(item)
        self.timer = None
    
    def stop(self):
        """停止实例（可选实现）"""
        if self.timer:
            self.timer.cancel()
            self.timer = None
        logging.info(f"[{self.name}] 已停止")
```

---

## 示例：定时天气推送

```python
# instances/weather_push.py
from core.base_instance import BaseInstance
import time
import requests
from datetime import datetime

class WeatherPush(BaseInstance):
    """每日天气推送实例"""
    
    def __init__(self, item):
        super().__init__(item)
        config = item.get('config', {})
        self.target_group = config.get('target_group')
        self.push_time = config.get('push_time', '08:00')
        self.api_key = config.get('api_key')
    
    def send_message(self, message: str):
        self.msg_queue.put((self.name, {
            "target": self.target_group,
            "content": message
        }))
    
    def start(self):
        """后台循环"""
        import logging
        logging.info(f"[{self.name}] 启动成功，推送时间：{self.push_time}")
        
        while True:
            try:
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                
                # 检查是否到达推送时间
                if current_time == self.push_time:
                    weather = self._get_weather()
                    self.send_message(weather)
                    
                    # 等待 1 分钟，避免重复推送
                    time.sleep(60)
                
                # 每分钟检查一次
                time.sleep(60)
            except Exception as e:
                logging.error(f"[{self.name}] 错误：{e}")
                time.sleep(300)  # 错误后等待 5 分钟
    
    def _get_weather(self):
        """获取天气信息（示例）"""
        # 实际使用时替换为真实 API
        return f"今天天气晴朗，气温 25°C"
```

配置：

```json
{
  "type": "weather_push",
  "config": {
    "target_group": "文件传输助手",
    "push_time": "08:00",
    "api_key": "your_api_key"
  }
}
```

---

## 相关文档

- [核心架构](./architecture.md)
- [主 README](../README.md)
