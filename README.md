# cs-Solidarity — 多功能微信机器人

一个基于 `pywechat` 与 `wxauto` 自动化库的多功能微信机器人，适用于 Windows 环境。支持 Steam 状态监控、每日定时消息、AI 聊天等多种功能。

## 功能特性

### 1. Steam 状态监控 (SteamAuto)
- 监控 Steam 好友游戏状态变化（开始/停止游戏）
- 统计好友每日游戏时长
- 每日 00:00 自动发送游玩统计报告
- 支持监听全部好友或指定好友
- 可选完美平台战绩查询（CS2）

### 2. 每日定时消息 (DailyAuto)
- 支持在指定时间自动发送固定消息到指定群组或好友
- 灵活配置发送时间和内容

### 3. AI 聊天机器人 (ChatAuto)
- 支持 DeepSeek 等大语言模型 API
- 通过触发前缀（默认 `@bot`）唤起对话
- 支持群组和私聊
- 可配置允许的用户和群组

### 4. 架构特性
- 线程安全的消息队列机制
- 多实例并行运行
- 兼容 wxauto 和 pywechat
- 消息获取频率限制（每1分钟一次）

## 快速开始

### 前置要求
- Windows 操作系统
- 微信 PC 客户端 v3.9.8.15（推荐版本）
- Python 3.7+

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

项目通过 `config.json` 配置主入口，各实例配置存放在 `instconfig/` 目录下。

#### config.json 示例
```json
{
  "instances": [
    {
      "type": "steam",
      "config": "instconfig/steam_account_bob.json"
    },
    {
      "type": "daily",
      "wechat_groups": ["文件传输助手"],
      "send_time": "08:00",
      "message": "早上好！新的一天开始了！"
    },
    {
      "type": "chat",
      "config": "instconfig/chat_deepseek.json"
    }
  ]
}
```

#### Steam 配置示例 (instconfig/steam_account_bob.json)
```json
{
  "steam_api_key": "你的Steam API Key",
  "steam_id": "你的Steam ID",
  "wechat_groups": ["【CS】团结友爱"],
  "check_interval": 60,
  "enable_all_friends": true,
  "monitored_friends": [
    {
      "steamid": "好友Steam ID",
      "nickname": "好友昵称"
    }
  ],
  "perfect_world_config": {
    "uid": "完美平台UID",
    "token": "完美平台Token"
  }
}
```

#### AI 聊天配置示例 (instconfig/chat_deepseek.json)
```json
{
  "api_key": "你的DeepSeek API Key",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "system_prompt": "你是一个友好的助手。",
  "trigger_prefix": "@bot",
  "allowed_groups": ["【CS】团结友爱"]
}
```

### 运行

```bash
python main.py
```

## 运行说明

### 消息队列架构
- **主线程**：负责所有微信 GUI 自动化操作（发送消息、获取消息）
- **后台线程**：各实例在独立线程中运行检测逻辑
- **消息队列**：后台线程将需要发送的消息放入队列，主线程从队列读取并发送

这种架构避免了多线程直接操控 UI 导致的失败问题。

### 消息获取频率限制
为防止窗口频繁打开，消息获取功能设置了时间限制，每 1 分钟获取一次新消息。

## 项目结构

```
cs-Solidarity/
├── core/                    # 核心模块
│   ├── __init__.py
│   ├── base_instance.py    # 实例基类
│   ├── instance_factory.py # 实例工厂
│   └── wechat_instance.py  # 微信实例管理
├── instances/              # 功能实例
│   ├── steam_auto.py       # Steam监控
│   ├── daily_auto.py       # 每日消息
│   └── chat_auto.py        # AI聊天
├── instconfig/             # 实例配置文件
├── pywechat/               # pywechat库
├── wxauto/                 # wxauto库
├── steam/                  # Steam API封装
├── cs2_pw/                 # 完美平台API
├── config.json             # 主配置文件
├── main.py                 # 主程序入口
├── requirements.txt        # 依赖列表
└── README.md              # 本文档
```

## 常见问题

### 为什么不能在多线程中直接发消息？
微信消息发送依赖 GUI 自动化（`pyautogui` / `pywinauto`），这些操作不是线程安全的，必须在单一主线程或专用发送进程中执行。

### 如何获取 Steam API Key？
访问 https://steamcommunity.com/dev/apikey 获取。

### 消息获取太频繁导致窗口频繁打开？
已在代码中设置每 1 分钟获取一次消息，可在 `main.py` 中调整此间隔。

## 开发说明

### 扩展新实例类型
1. 继承 `BaseInstance` 类
2. 实现 `send_message` 和 `start` 方法
3. 可选实现 `handle_message` 方法处理接收到的消息
4. 在 `instance_factory.py` 中注册新类型

### 调试提示
- 在修改自动化逻辑时，请确保微信客户端窗口能被脚本访问
- 避免在运行时手动干预鼠标/键盘
- 查看控制台输出了解运行状态

## 免责声明

代码仅供交流学习使用，请勿用于非法用途和商业用途！如因此产生任何法律纠纷，均与作者无关！

## 许可与贡献

本仓库使用现有 LICENSE（见根目录）。欢迎提交 issue / pull request。
