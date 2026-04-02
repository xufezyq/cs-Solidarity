# cs-Solidarity — 多功能微信机器人

基于 `wxauto` 自动化库的多功能微信机器人，适用于 Windows 环境。支持 Steam 状态监控、每日定时消息、AI 聊天、KoriChat 智能助手等多种功能。

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [核心架构](#核心架构)
- [消息接收与发送](#消息接收与发送)
- [项目结构](#项目结构)
- [扩展开发](#扩展开发)
- [常见问题](#常见问题)

---

## 功能特性

### Steam 状态监控 (SteamAuto)
- 监控 Steam 好友游戏状态变化（开始/停止游戏）
- 统计好友每日游戏时长，每日 00:00 自动发送统计报告
- 支持监听全部好友或指定好友
- 可选完美平台战绩查询（CS2）

### 每日定时消息 (DailyAuto)
- 指定时间自动发送固定消息到指定群组或好友
- 支持维护时段自动跳过

### AI 聊天机器人 (ChatAuto)
- 支持 DeepSeek 等 OpenAI 兼容 API
- 通过触发前缀（如 `/claw`）唤起对话
- 多用户上下文隔离，每人独立对话历史
- 支持 `clear` / `重置` 清除上下文

### KoriChat 智能助手 (KoriChat)
- 多轮对话上下文 + 长期记忆
- 多种人设可选（ATRI、MONO、Nijiko 等）
- 支持图像识别、表情符号处理
- 主动消息和定时任务

### 信息推送 (InfoPush)
- 定时推送金价、股票、新闻
- 支持群聊差异化配置

---

## 快速开始

### 前置要求

- Windows 10/11
- 微信 PC 客户端 v3.9.8.15（推荐）
- Python 3.7+

### 安装

```bash
pip install -r requirements.txt
```

### 配置

主入口 `config.json`，各实例配置在 `instconfig/` 目录。

```json
{
  "debug_mode": false,
  "instances": [
    {
      "type": "steam",
      "config": "instconfig/steam_account_bob.json"
    },
    {
      "type": "daily",
      "wechat_groups": ["文件传输助手"],
      "time": "08:00",
      "message": "早上好！"
    },
    {
      "type": "chat",
      "config": "instconfig/chat_deepseek.json"
    }
  ]
}
```

### 运行

```bash
python main.py
```

---

## 核心架构

### 线程模型

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

- **主线程**：轮询检测 → 收发消息 → 控制窗口
- **后台线程**：各实例运行业务逻辑（Steam 监控、定时任务、AI 对话）
- **消息队列**：后台线程 → `msg_queue.put()` → 主线程消费发送

### 实例体系

所有功能实例继承 `BaseInstance`，实现统一接口：

```python
class BaseInstance(ABC):
    @abstractmethod
    def send_message(self, message: str):  # 发送消息（被主线程 hook 为入队）
        pass

    @abstractmethod
    def start(self):                        # 后台循环（子线程运行）
        pass

    def handle_message(self, chat_name, msg):  # 接收消息（可选）
        pass
```

实例通过 `instance_factory` 注册和创建，`config.json` 的 `type` 字段决定实例类型。

---

## 消息接收与发送

这是整个系统最核心的部分。下面详细说明完整流程。

### 一、消息接收

#### 1. 通知检测

主循环以 **随机轮询间隔**（0.3s ± 0.15s）检测微信是否有新消息。检测方式是通过 Win32 API 截取任务栏区域截图，对比像素变化判断微信按钮是否在闪烁：

```
main.py: start_instances() 主循环
  └→ detect_flash()
       └→ utils.flash_detector.is_wechat_flashing()
            ├→ FindWindowW("WeChatMainWndForPC")     # 找到微信窗口
            ├→ IsIconic(hwnd)                         # 必须最小化状态
            ├→ ImageGrab.grab(bbox=taskbar) × 3      # 连续截取任务栏 3 次
            └→ ImageChops.difference() 对比像素       # 有变化 = 闪烁 = 有消息
```

**为什么用截图而不是 Win32 托盘 API？**

`notification_monitor.py` 中有另一套基于托盘图标 tooltip 的检测方案（直接读取 Win32 托盘数据），但 `flash_detector` 更稳定，因为：
- Windows 11 的托盘布局变化较大，ToolbarWindow32 句柄不一定能拿到
- 截图方案不依赖进程内存读取，兼容性更好

#### 2. 消息获取

检测到闪烁后，主线程恢复微信窗口，调用 `get_new_messages()`：

```
main.py: process_receive_messages()
  └→ core.wechat_instance.get_new_messages()
       ├→ human_delay(500, 2000)           # 获取前随机等待（反检测）
       ├→ wx.GetAllNewMessage()            # wxauto 核心调用
       └→ human_delay(200, 600)            # 获取后随机等待
```

`wx.GetAllNewMessage()` 返回格式：

```python
{
    "群名A": [WXMessage, WXMessage, ...],
    "好友B": [WXMessage, ...],
}
```

每条 `WXMessage` 包含 `.sender`、`.content`、`.id`、`.type` 等属性。

#### 3. 消息分发

获取到消息后，按聊天名逐条分发给所有实例：

```python
for chat_name, msg_list in new_msgs.items():
    for msg in msg_list:
        msg_content = msg.content
        targets = route_message_to_instances(msg_content, instances)
        for name, inst in targets:
            inst.handle_message(chat_name, msg)
```

#### 4. 路由逻辑

`route_message_to_instances()` 根据消息内容决定分发目标：

```
消息内容: "/claw 珠海天气怎么样"
  ├→ 检查每个实例的 trigger_prefix
  ├→ ChatAuto.trigger_prefix = "/claw" → 匹配！
  └→ 只分发给 ChatAuto，其他实例不处理

消息内容: "今天中午吃什么"
  ├→ 没有实例的 trigger_prefix 匹配
  └→ 分发给所有没有 trigger_prefix 的实例（KoriChat、InfoPush 等）
```

**规则**：
- 有 `trigger_prefix` 的实例（如 ChatAuto）= **独占型**，匹配到就只给它
- 没有 `trigger_prefix` 的实例（如 KoriChat）= **广播型**，每条消息都收到

#### 5. 实例处理

以 ChatAuto 为例，`handle_message()` 内部流程：

```
ChatAuto.handle_message(chat_name, msg)
  ├→ 解析消息（对象/列表/字符串）
  ├→ 过滤非文本消息
  ├→ 过滤自己发送的消息 (sender == 'Self')
  ├→ 检查群组/用户权限
  ├→ 去重检查 (processed_msgs)
  ├→ 提取 user_query（去掉 trigger_prefix）
  ├→ 调用 LLM API
  └→ self.send_message({"target": chat_name, "content": f"@{sender} {reply}"})
       └→ 入队，等待主线程发送
```

#### 完整接收流程图

```
  ┌─────────────┐
  │ 主循环轮询   │  每 0.3s ± 0.15s
  └──────┬──────┘
         ↓
  ┌─────────────┐    否
  │ 有闪烁？    │────────→ 检查发送队列 → 继续轮询
  └──────┬──────┘
         │ 是
         ↓
  ┌─────────────┐
  │ 恢复微信窗口 │  human_delay(100, 500)
  └──────┬──────┘
         ↓
  ┌─────────────┐
  │ 获取新消息   │  wx.GetAllNewMessage()
  └──────┬──────┘
         ↓
  ┌─────────────┐
  │ 逐条分发     │  route_message_to_instances()
  └──────┬──────┘
         ↓
  ┌─────────────┐
  │ 实例处理     │  inst.handle_message()
  │ → 可能入队   │  inst.send_message() → msg_queue.put()
  └──────┬──────┘
         ↓
  ┌─────────────┐
  │ 切到文件传输 │
  │ 助手 → 最小化│
  └─────────────┘
```

---

### 二、消息发送

#### 1. 入队机制

实例在后台线程中调用 `self.send_message()` 时，**实际不是真正发送**，而是入队：

```python
# start_instances() 启动时对每个实例做 hook
orig_senders[name] = inst.send_message     # 保存原始方法

def make_enqueue(n):
    def enqueue(message):
        msg_queue.put((n, message))         # 入队，而非直接发送
    return enqueue
inst.send_message = make_enqueue(name)     # 替换为入队函数
```

**为什么这样做？** 微信 GUI 操作不是线程安全的。如果多个实例的后台线程同时调用 wxauto 发消息，会导致窗口焦点冲突、消息串发。入队机制保证所有发送操作由主线程串行执行。

#### 2. 主线程消费

主循环每次迭代检查队列：

```python
if not msg_queue.empty():
    if wx_is_minimized:
        human_delay(200, 800)    # "回来操作" 的随机延迟
        restore_wechat()         # 恢复窗口
    process_all_pending_messages(msg_queue, orig_senders, instances)
    minimize_wechat()            # 发完立即最小化
```

#### 3. 实际发送

`process_send_message()` 调用保存的原始发送方法：

```python
def process_send_message(name, message, orig_senders, instances):
    sender = orig_senders.get(name)
    caught_msgs = sender(message)      # 调用实例的真正 send_message
```

以 ChatAuto 为例，真正的发送逻辑在 `wechat_instance.send_message()`：

```
wechat_instance.send_message(message, group)
  ├→ human_action_delay()              # 操作前随机延迟
  ├→ wx.ChatWith(group)                # 打开目标聊天
  ├→ wx.GetAllMessage()                # 读取发送前消息列表，记录最后 ID
  ├→ human_delay(300, 600)
  ├→ wx.SendMsg(message, group)        # 发送
  ├→ human_delay(300, 800)
  ├→ wx.GetAllMessage()                # 读取发送后消息列表
  ├→ 对比 ID，过滤自己发的消息
  └→ return new_msgs                   # 返回发送期间收到的新消息
```

**关键设计：发送期间捕获新消息。**

发送消息时微信窗口已经在前台，此时如果有新消息到达，可以顺带捕获。这样：
- 不需要额外的闪烁检测来发现这些消息
- 减少一次窗口恢复/最小化的开销
- 消息处理更及时

#### 4. 批量发送

队列中可能有多个待发送消息，一次性处理完：

```python
def process_all_pending_messages(msg_queue, orig_senders, instances):
    sent_any = False
    while True:
        name, message = msg_queue.get_nowait()  # 非阻塞取出
        process_send_message(name, message, ...)
        sent_any = True
        human_delay(500, 1500)                  # 消息间随机延迟
    if sent_any:
        wx.ChatWith('文件传输助手')               # 切回中性窗口
        minimize_wechat()                        # 最小化
```

#### 完整发送流程图

```
  ┌──────────────┐
  │ 实例后台线程  │  生成消息
  │              │  self.send_message({"target": "群A", "content": "你好"})
  └──────┬───────┘
         ↓  (实际是入队)
  ┌──────────────┐
  │ msg_queue    │  Queue.put(("instance_1", {"target":...}))
  └──────┬───────┘
         ↓
  ┌──────────────┐    队列为空
  │ 主循环检查    │────────→ 跳过，继续轮询
  └──────┬───────┘
         │ 队列有消息
         ↓
  ┌──────────────┐
  │ 恢复微信窗口  │  human_delay(200, 800) + ShowWindow(SW_RESTORE)
  └──────┬──────┘
         ↓
  ┌──────────────┐
  │ 循环消费队列  │  process_all_pending_messages()
  │              │
  │  取出消息     │  msg_queue.get_nowait()
  │  打开聊天     │  wx.ChatWith(group)
  │  读取旧消息   │  wx.GetAllMessage() → 记录 last_id
  │  发送         │  wx.SendMsg(content, group)
  │  读取新消息   │  wx.GetAllMessage() → 对比 last_id
  │  捕获期间消息 │  过滤 self 类型，返回新消息
  │  消息间延迟   │  human_delay(500, 1500)
  └──────┬──────┘
         ↓
  ┌──────────────┐
  │ 切到文件传输  │  wx.ChatWith('文件传输助手')
  │ 助手 → 最小化 │  ShowWindow(SW_MINIMIZE)
  └──────────────┘
```

---

### 三、反检测策略

系统通过以下方式降低被微信识别为机器人的风险：

| 策略 | 实现 | 位置 |
|------|------|------|
| 随机轮询间隔 | 0.3s ± 0.15s 高斯分布 | `main.py` 主循环 |
| 操作前随机延迟 | 100~800ms | `main.py` 恢复窗口前 |
| 响应随机延迟 | 100~500ms | `main.py` 检测到闪烁后 |
| 消息间随机延迟 | 500~1500ms | `main.py` 批量发送时 |
| 收消息随机等待 | 500~2000ms | `wechat_instance.py` |
| 空闲超时随机化 | 10~20s（非固定 15s） | `main.py` |
| UI 操作注入抖动 | SetCursorPos ±1px | `wechat_instance.py` |
| 点击延迟注入 | 按下/释放间隔 30~120ms | `wechat_instance.py` |
| 维护时段 | 00:15 ~ 08:00 完全停止 | `main.py` |
| 窗口最小化策略 | 无操作时保持最小化 | `main.py` |

`wechat_instance.py` 在初始化时对 `uiautomation.SetCursorPos` 和 `uiautomation.Click` 做了 monkey-patch，所有 wxauto 的底层 UI 操作都会自动带上随机抖动和延迟。

---

## 项目结构

```
cs-Solidarity/
├── main.py                      # 主程序入口 + 主循环
├── config.json                  # 主配置文件
├── requirements.txt             # 依赖列表
│
├── core/                        # 核心模块
│   ├── __init__.py
│   ├── base_instance.py         # 实例基类 (ABC)
│   ├── instance_factory.py      # 实例注册 & 工厂
│   └── wechat_instance.py       # 微信实例管理 (wxauto 封装 + 反检测 patch)
│
├── utils/                       # 工具模块
│   ├── __init__.py              # 懒加载
│   ├── human_sim.py             # 人类行为模拟（随机延迟）
│   ├── flash_detector.py        # 任务栏闪烁检测（截图方案）
│   ├── notification_monitor.py  # 系统托盘检测（Win32 API 方案）
│   └── logger.py                # 日志模块（按日期切分文件）
│
├── instances/                   # 功能实例
│   ├── steam_auto.py            # Steam 好友状态监控
│   ├── daily_auto.py            # 每日定时消息
│   ├── chat_auto.py             # AI 聊天（OpenAI 兼容 API）
│   ├── kori_chat.py             # KoriChat 智能助手
│   └── info_push.py             # 信息推送（金价/股票/新闻）
│
├── instconfig/                  # 实例配置文件目录
├── logs/                        # 日志输出目录（按日期命名）
│
├── KouriChat/                   # KoriChat 项目（外部依赖）
├── steam/                       # Steam API 封装
├── cs2_pw/                      # 完美世界平台 API
├── pywechat/                    # pywechat 库
└── wxauto/                      # wxauto 库
```

---

## 扩展开发

### 添加新实例类型

1. 在 `instances/` 下创建新文件，继承 `BaseInstance`：

```python
from core.base_instance import BaseInstance

class MyInstance(BaseInstance):
    def start(self):
        """后台循环，在子线程运行"""
        while True:
            # 业务逻辑...
            self.send_message({"target": "群名", "content": "消息"})
            time.sleep(60)

    def send_message(self, message):
        """实际发送逻辑，由主线程调用"""
        from core.wechat_instance import send_message
        if isinstance(message, dict):
            send_message(message["content"], message["target"])

    def handle_message(self, chat_name, msg):
        """接收消息（可选）"""
        pass
```

2. 在 `core/instance_factory.py` 中注册：

```python
from instances.my_instance import MyInstance
register_instance_type('mytype', lambda data: MyInstance.create_from_config(data.get('config')))
```

3. 在 `config.json` 中配置：

```json
{
  "instances": [
    { "type": "mytype", "config": "instconfig/my_config.json" }
  ]
}
```

---

## 常见问题

### 为什么所有发送操作必须在主线程？
微信 GUI 自动化依赖窗口焦点和鼠标/键盘操作，多线程同时操作会导致焦点冲突、消息串发或程序崩溃。入队机制保证所有 GUI 操作串行执行。

### 维护时段是什么？
每天 00:15 ~ 08:00，系统完全停止轮询和发送，避免深夜操作引起怀疑。`debug_mode` 开启时可跳过维护时段。

### 日志在哪里？
`logs/` 目录下，按日期命名（`2026-04-02.log`），跨天自动创建新文件。

### 闪烁检测和托盘检测有什么区别？
- **闪烁检测**（`flash_detector.py`）：截图对比任务栏像素变化，兼容性好
- **托盘检测**（`notification_monitor.py`）：直接读 Win32 托盘图标 tooltip，不截图但兼容性较差（Windows 11 布局变化）

当前默认使用闪烁检测。

---

## 免责声明

代码仅供交流学习使用，请勿用于非法用途和商业用途！如因此产生任何法律纠纷，均与作者无关！
