# 核心架构与实现细节

本文档详细介绍 cs-Solidarity 的核心架构、线程模型、消息收发机制等底层实现。

## 目录

- [线程模型](#线程模型)
- [实例体系](#实例体系)
- [消息接收流程](#消息接收流程)
- [消息发送流程](#消息发送流程)
- [@mentions 实现](#mentions-实现)
- [维护时间机制](#维护时间机制)

---

## 线程模型

```
┌─────────────────────────────────────────────────────┐
│                    主线程 (main)                      │
│                                                      │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ 闪烁检测  │  │ 消息发送/接收 │  │ 窗口控制      │  │
│  │ (轮询)   │  │ (wxauto)     │  │ 最小化/恢复   │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
│        ↓              ↑                ↑             │
│        │         ┌────┴────┐           │             │
│        │         │ 消息队列 │           │             │
│        │         └────┬────┘           │             │
│        │              ↑                │             │
├────────┼──────────────┼────────────────┼─────────────┤
│        ↓              │                │             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│  │ 实例 A   │   │ 实例 B   │   │ 实例 C   │  后台    │
│  │ (daemon) │   │ (daemon) │   │ (daemon) │  线程    │
│  └──────────┘   └──────────┘   └──────────┘         │
└─────────────────────────────────────────────────────┘
```

**核心原则：所有微信 GUI 操作只在主线程执行。**

### 主线程职责

- **闪烁检测**：以 `random_poll_interval(2.0, 1.5)` 生成的长尾随机间隔检测微信是否有新消息
- **消息收发**：处理消息队列、调用 wxauto 收发消息
- **窗口控制**：根据状态最小化/恢复微信窗口

### 后台线程职责

- **业务逻辑**：各实例运行独立业务（Steam 监控、定时任务、AI 对话）
- **消息入队**：通过 `msg_queue.put()` 将发送请求加入队列
- **消息处理**：可选实现 `handle_message()` 接收新消息

---

## 实例体系

所有功能实例继承 `BaseInstance`，实现统一接口：

```python
# core/base_instance.py
class BaseInstance(ABC):
    @abstractmethod
    def send_message(self, message: str):
        """发送消息（被主线程 hook 为入队）"""
        pass

    def send_file(self, file_path: str):
        """发送文件（可选实现，被主线程 hook 为入队）"""
        raise NotImplementedError

    @abstractmethod
    def start(self):
        """后台循环（子线程运行）"""
        pass

    def handle_message(self, chat_name, msg):
        """接收消息（可选实现）"""
        pass
```

### 实例创建

实例通过 `instance_factory` 注册和创建，`config.json` 的 `type` 字段决定实例类型：

```python
# core/instance_factory.py
_INSTANCE_TYPES = {}

def init_defaults():
    register_instance_type('steam', lambda data: SteamAuto.create_from_config(data.get('config')))
    register_instance_type('daily', lambda data: DailyAuto.create_from_data(data))
    register_instance_type('chat', lambda data: ChatAuto.create_from_config(data.get('config') or data, data.get('name')))
    register_instance_type('korichat', lambda data: KoriChatInstance.create_from_config(data.get('config')))
    register_instance_type('infopush', lambda data: InfoPush.create_from_data(data))
    register_instance_type('disaster_warning', lambda data: DisasterWarningInstance.create_from_data(data))
```

当前默认实例类型为 `steam`、`daily`、`chat`、`korichat`、`infopush`、`disaster_warning`。其中 `chat` 支持在同一个配置文件中通过实例项的 `name` 选择具体配置，例如 `openclaw`、`hermes` 或 `deepseek`。

---

## 消息接收流程

### 1. 通知检测

主循环以随机轮询间隔检测微信是否有新消息：

```python
# main.py: start_instances() 主循环
while True:
    # poll_base=2.0, poll_jitter=1.5
    current_interval = random_poll_interval(poll_base, poll_jitter)
    if now - last_poll_time < current_interval:
        time.sleep(0.1)
        continue
    last_poll_time = now
    
    # 检测闪烁
    is_flashing = detect_flash()
    if is_flashing:
        process_receive_messages(instances)
```

检测实现：

```python
# utils/flash_detector.py
def is_wechat_flashing():
    # 1. 找到微信窗口
    hwnd = FindWindowW("WeChatMainWndForPC")
    
    # 2. 必须是最小化状态
    if not IsIconic(hwnd):
        return False
    
    # 3. 连续截取任务栏 3 次
    taskbar = get_taskbar_bbox()
    screenshots = [ImageGrab.grab(bbox=taskbar) for _ in range(3)]
    
    # 4. 对比像素变化
    for i in range(len(screenshots) - 1):
        diff = ImageChops.difference(screenshots[i], screenshots[i+1])
        if diff.getbbox():
            return True  # 有变化 = 闪烁 = 有消息
    
    return False
```

**为什么用截图而不是 Win32 托盘 API？**

`notification_monitor.py` 中有另一套基于托盘图标 tooltip 的检测方案，但 `flash_detector` 更稳定：
- Windows 11 的托盘布局变化较大，ToolbarWindow32 句柄不一定能拿到
- 截图方案不依赖进程内存读取，兼容性更好

### 2. 消息获取

检测到闪烁后，主线程恢复微信窗口，调用 `get_new_messages()`：

```python
# main.py: process_receive_messages()
def process_receive_messages(instances):
    # 检查开关和维护时间
    if not ENABLE_RECEIVE or is_maintenance_time():
        return 0
    
    # 获取新消息
    new_msgs = wechat_instance.get_new_messages()
    
    # 分发给各实例
    for chat_name, msg_list in new_msgs.items():
        for msg in msg_list:
            targets = route_message_to_instances(msg.content, instances)
            for name, inst in targets:
                inst.handle_message(chat_name, msg)
```

```python
# core/wechat_instance.py
def get_new_messages():
    # 获取前随机等待（反检测）
    human_delay(500, 2000)
    
    # 调用 wxauto 获取新消息
    wx = get_wechat()
    all_new = wx.GetAllNewMessage()
    
    # 获取后随机等待
    human_delay(200, 600)
    
    return all_new
```

`wx.GetAllNewMessage()` 返回格式：
```python
{
    "群聊 A": [
        Message(content="消息 1", sender="好友 A", type="text"),
        Message(content="消息 2", sender="好友 B", type="image"),
    ],
    "好友 B": [Message(content="hi", sender="好友 B", type="text")]
}
```

### 3. 消息分发

```python
# main.py: route_message_to_instances()
def route_message_to_instances(msg_content, instances):
    """根据消息内容路由到对应的实例"""
    # 1. 优先匹配触发前缀（如 /claw）
    for name, inst in instances:
        if hasattr(inst, 'trigger_prefix') and inst.trigger_prefix in msg_content:
            return [(name, inst)]
    
    # 2. 默认实例（没有 trigger_prefix 的）
    return [(name, inst) for name, inst in instances 
            if not hasattr(inst, 'trigger_prefix')]
```

Web 聊天消息不依赖微信闪烁检测。`agent.handler` 收到 `chat.send` 后通过本地 TCP 聊天服务把消息写入 `web_msg_queue`，主循环每轮先调用 `process_web_messages()`，再按同一套路由逻辑分发给实例。`sync_to_wx=false` 时，实例回复会被 Web 拦截器捕获并返回网页，但不会实际发送到微信。

---

## 消息发送流程

### 1. 消息入队

后台实例不直接发送消息，而是加入队列：

```python
# main.py: start_instances()
def make_enqueue(n):
    def enqueue(message):
        msg_queue.put((n, "message", message))
    return enqueue

def make_file_enqueue(n):
    def enqueue_file(file_path):
        msg_queue.put((n, "file", file_path))
    return enqueue_file

inst.send_message = make_enqueue(name)
inst.send_file = make_file_enqueue(name)
```

### 2. 主线程消费队列

```python
# main.py: process_all_pending_messages()
def process_all_pending_messages(msg_queue, orig_senders, orig_file_senders, instances):
    """一次性处理队列中所有待发送消息"""
    sent_any = False
    while True:
        try:
            name, kind, payload = msg_queue.get_nowait()
            
            # 检查维护时间
            if is_maintenance_time():
                info("维护时段，跳过发送")
                msg_queue.task_done()
                continue
            
            # 发送消息或文件
            if kind == "message":
                process_send_message(name, payload, orig_senders, instances)
            elif kind == "file":
                process_send_file(name, payload, orig_file_senders)
            sent_any = True
            msg_queue.task_done()
            
            # 消息间随机延迟（反检测）
            human_delay(1000, 2000)
        except queue.Empty:
            break
```

本地 HTTP API（`bot/api_server.py`，默认 `127.0.0.1:18800`）也会把 `/send/message` 和 `/send/file` 请求写入 `api_send_queue`，由主循环统一处理，避免外部 Agent 直接抢占微信窗口。

### 3. 实际发送

```python
# main.py: process_send_message()
def process_send_message(name, message, orig_senders, instances):
    # 检查开关和维护时间
    if not ENABLE_SEND or is_maintenance_time():
        return
    
    # 获取发送者实例
    sender = orig_senders.get(name)
    if sender:
        # 发送并捕获发送期间的新消息
        caught_msgs = sender(message)
        
        # 处理捕获的新消息（分发给其他实例）
        if caught_msgs and instances:
            for msg in caught_msgs:
                targets = route_message_to_instances(msg.content, instances)
                for inst_name, inst in targets:
                    inst.handle_message(target_chat, msg)
```

```python
# core/wechat_instance.py: send_message()
def send_message(message, group, at=None, at_all=False):
    """发送消息并捕获发送期间的新消息"""
    with _send_op_lock:
        # 1. 预捕获未读消息（防止 ChatWith 清除未读状态）
        pre_caught = []
        all_new = wx.GetAllNewMessage()
        if group in all_new:
            pre_caught = [msg for msg in all_new[group] 
                         if msg.type != 'self']
        
        # 2. 切换到目标聊天
        wx.ChatWith(group)
        human_delay(400, 900)
        
        # 3. 记录发送前的消息快照
        pre_msgs = wx.GetAllMessage()
        
        # 4. 模拟输入延迟
        typing_delay = min(max(len(message) * 0.05, 0.3), 2.0)
        time.sleep(typing_delay)
        
        # 5. 处理@操作
        if at or at_all:
            # 确保窗口可见，输入 @成员 或 @所有人，回车选择，
            # 再粘贴正文并回车发送。
            pass
        else:
            wx.SendMsg(message, clear=True)
        
        # 7. 等待消息出现在聊天记录
        for _ in range(20):
            time.sleep(0.5)
            after_msgs = wx.GetAllMessage()
            if len(after_msgs) > len(pre_msgs):
                break
        
        # 8. 捕获发送期间到达的新消息
        post_caught = []
        # ...
        
        return pre_caught + post_caught
```

---

## @mentions 实现

### 1. @用户提取

```python
# KouriChat/src/handlers/message.py
def _add_at_tag_if_needed(self, reply: str, sender_name: str, is_group: bool):
    if not is_group:
        return reply, []

    if reply.startswith(f"@{sender_name} "):
        clean = reply[len(f"@{sender_name} "):]
        return clean, [sender_name]

    return reply, [sender_name]

def _send_message_with_dollar(self, reply, chat_id, at=None):
    # $ 分段时使用 send_messages 批量发送，at 只作用于第一条消息
    wechat_instance.send_messages(text_parts, chat_id, at=at)
```

### 2. @操作执行

```python
# core/wechat_instance.py: send_message()/send_messages()
if actual_at_all:
    uia.SendKeys('@所有人', waitTime=0.1)
    time.sleep(0.5)
    uia.SendKeys('{Enter}', waitTime=0.1)

for member in actual_at or []:
    uia.SendKeys(f'@{member}', waitTime=0.1)
    time.sleep(0.5)
    uia.SendKeys('{Enter}', waitTime=0.1)

SetClipboardText(actual_msg)
uia.SendKeys('{Ctrl}v', waitTime=0.1)
uia.SendKeys('{Enter}', waitTime=0.1)
```

### 3. 防止窗口最小化

```python
# core/wechat_instance.py: send_message()
def send_message(message, group, at=None, at_all=False):
    # 发送开始时增加 _sending_count，并更新 _last_send_time
    # 主循环在发送期间或发送后短时间内不会最小化窗口
    with main._send_lock:
        main._sending_count += 1
        main._last_send_time = time.time()
```

```python
# main.py
def process_receive_messages(instances):
    # 收消息后检查是否有发送任务
    if _sending_count > 0 or (time.time() - _last_send_time) < 15:
        debug("[主循环] 有发送任务正在进行，跳过最小化")
    else:
        # 切换到文件传输助手并最小化
        minimize_wechat()
```

---

## 维护时间机制

### 1. 配置加载

```python
# main.py: load_master_config()
def load_master_config(config_file):
    global DEBUG_MODE, MAINTENANCE_START, MAINTENANCE_END
    global ENABLE_SEND, ENABLE_RECEIVE, ENABLE_FLASH_DETECT, MOCK_SEND
    
    with open(config_file, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    # 加载维护时间配置
    maintenance = cfg.get('maintenance', {})
    if maintenance:
        MAINTENANCE_START = dt_time(
            maintenance.get('start_hour', 0),
            maintenance.get('start_minute', 15)
        )
        MAINTENANCE_END = dt_time(
            maintenance.get('end_hour', 8),
            maintenance.get('end_minute', 0)
        )
    
    # 加载开关配置
    ENABLE_SEND = cfg.get('enable_send', True)
    ENABLE_RECEIVE = cfg.get('enable_receive', True)
    ENABLE_FLASH_DETECT = cfg.get('enable_flash_detect', True)
    MOCK_SEND = cfg.get('mock_send', False)
```

### 2. 维护时间检查

```python
# main.py
def is_maintenance_time():
    """检查当前是否在维护时间内"""
    if DEBUG_MODE:
        return False
    
    now = datetime.now().time()
    return MAINTENANCE_START <= now < MAINTENANCE_END
```

### 3. 发送和接收检查

```python
# process_send_message()
def process_send_message(name, message, orig_senders, instances):
    # 检查是否允许发送消息
    if not ENABLE_SEND:
        debug(f"[发送] 跳过：发送功能已禁用 (name={name})")
        return
    
    # 检查是否在维护时间内
    if is_maintenance_time():
        info(f"[发送] 跳过：当前是维护时间 (name={name})")
        return
    
    # ... 实际发送逻辑
```

```python
# process_receive_messages()
def process_receive_messages(instances):
    # 检查是否允许接收消息
    if not ENABLE_RECEIVE:
        debug("[收消息] 跳过：接收功能已禁用")
        return 0
    
    # 检查是否在维护时间内
    if is_maintenance_time():
        debug("[收消息] 跳过：当前是维护时间")
        return 0
    
    # ... 实际接收逻辑
```

### 4. 闪烁检测控制

```python
# 主循环中
if not ENABLE_FLASH_DETECT:
    debug("[闪烁检测] 跳过：检测功能已禁用")
    time.sleep(0.1)
    continue

is_flashing = detect_flash()  # 截图对比像素变化
if is_flashing:
    # 检查是否允许接收消息
    if not ENABLE_RECEIVE:
        debug("[闪烁检测] 检测到新消息，但接收功能已禁用，不恢复窗口")
    elif is_maintenance_time():
        debug("[闪烁检测] 检测到新消息，但当前是维护时间，不恢复窗口")
    else:
        # 恢复窗口并处理消息
        restore_wechat()
        process_receive_messages(instances)
```

**说明**：
- `ENABLE_FLASH_DETECT = False`：完全停止闪烁检测，不截图、不对比像素，节省 CPU 和内存
- `ENABLE_RECEIVE = False`：仍然检测闪烁，但检测到后跳过消息处理且不恢复窗口
- `MOCK_SEND = True`：跳过微信 GUI 初始化，发送动作只写日志；适合调试实例后台任务和 Web 聊天链路
- 三者配合使用可实现灵活的消息控制

### 5. 配置示例

```json
{
  "debug_mode": false,
  "mock_send": false,
  "enable_send": true,
  "enable_receive": true,
  "enable_flash_detect": true,
  "maintenance": {
    "start_hour": 0,
    "start_minute": 15,
    "end_hour": 8,
    "end_minute": 0
  },
  "instances": [...]
}
```

---

## 相关文档

- [KoriChat 使用指南](../KouriChat/README.md)
- [Web 控制面板](../web/README.md)
- [主 README](../README.md)
