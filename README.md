# cs-Solidarity — 多功能微信机器人

[![Python 3.7+](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

基于 `wxauto` 的多功能微信机器人，适用于 Windows 环境。支持 Steam 状态监控、每日定时消息、AI 聊天、KoriChat 智能助手等多种功能。

> 🌟 **特性**：多实例并发 | 消息队列机制 | 反检测模拟 | 维护时间控制 | Web 远程管理

---

## 📋 目录

- [功能特性](#-功能特性)
- [快速开始](#-快速开始)
- [配置说明](#-配置说明)
- [核心架构](#-核心架构)
- [高级功能](#-高级功能)
- [开发指南](#-开发指南)
- [常见问题](#-常见问题)

---

## ✨ 功能特性

### 🎮 Steam 状态监控 (SteamAuto)
- 监控 Steam 好友游戏状态变化（开始/停止游戏）
- 统计好友每日游戏时长，每日 00:00 自动发送统计报告
- 支持监听全部好友或指定好友
- 可选完美平台战绩查询（CS2）

### ⏰ 每日定时消息 (DailyAuto)
- 指定时间自动发送固定消息到指定群组或好友
- 支持维护时段自动跳过
- 随机延迟反检测

### 🤖 AI 聊天机器人 (ChatAuto)
- 支持 DeepSeek 等 OpenAI 兼容 API
- 通过触发前缀（如 `/claw`）唤起对话
- 多用户上下文隔离，每人独立对话历史
- 支持 `clear` / `重置` 清除上下文

### 🧠 KoriChat 智能助手
- 多轮对话上下文 + 长期记忆
- 多种人设可选（ATRI、MONO、Nijiko 等）
- 支持图像识别、表情符号处理
- 主动消息和定时任务

> 📖 **详细文档**：[KoriChat 使用指南](./KouriChat/README.md)

### 📢 信息推送 (InfoPush)
- 定时推送金价、股票、新闻
- 支持群聊差异化配置

### 🌐 Web 控制面板
- 基于 WebSocket 的远程管理工具（Agent-Server 架构）
- 实时查看机器人状态、实例信息、日志
- 远程配置编辑、控制启停、用户管理
- Vue 3 前端 + FastAPI 后端，响应式布局

> 📖 **详细文档**：[Web 控制面板使用指南](./web/README.md)

---

## 🚀 快速开始

### 前置要求

- **操作系统**：Windows 10/11
- **微信版本**：PC 客户端 v3.9.8.15（推荐）
- **Python 版本**：3.7+

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置

主配置文件 `config.json`，各实例配置在 `instconfig/` 目录。

```json
{
  "debug_mode": false,
  "enable_send": true,
  "enable_receive": true,
  "maintenance": {
    "start_hour": 0,
    "start_minute": 15,
    "end_hour": 8,
    "end_minute": 0
  },
  "instances": [
    {
      "type": "steam",
      "config": "instconfig/steam_account.json"
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
    },
    {
      "type": "korichat",
      "config": "instconfig/korichat_config.json"
    }
  ]
}
```

### 3. 运行

```bash
python main.py
```

启动后会自动：
1. 初始化所有配置的实例
2. 启动后台线程运行业务逻辑
3. 主线程开始轮询检测消息
4. 微信窗口自动最小化到托盘

---

## ⚙️ 配置说明

### 主配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `debug_mode` | bool | `false` | 调试模式，开启后维护时间失效 |
| `enable_send` | bool | `true` | 是否允许发送消息 |
| `enable_receive` | bool | `true` | 是否允许接收消息（处理消息） |
| `enable_flash_detect` | bool | `true` | 是否检测新消息（闪烁检测） |
| `maintenance` | object | - | 维护时间配置 |
| `maintenance.start_hour` | int | `0` | 维护开始小时 |
| `maintenance.start_minute` | int | `15` | 维护开始分钟 |
| `maintenance.end_hour` | int | `8` | 维护结束小时 |
| `maintenance.end_minute` | int | `0` | 维护结束分钟 |

### 实例类型

| 类型 | 说明 | 配置文件示例 |
|------|------|--------------|
| `steam` | Steam 状态监控 | `instconfig/steam_account.json` |
| `daily` | 每日定时消息 | `instconfig/daily_morning.json` |
| `chat` | AI 聊天机器人 | `instconfig/chat_deepseek.json` |
| `korichat` | KoriChat 智能助手 | `instconfig/korichat_config.json` |
| `infopush` | 信息推送 | `instconfig/info_push_config.json` |

### 配置示例

**禁用发送功能**：
```json
{
  "enable_send": false,
  "enable_receive": true,
  "enable_flash_detect": true
}
```

**完全禁用消息处理（不检测、不发送、不接收）**：
```json
{
  "enable_send": false,
  "enable_receive": false,
  "enable_flash_detect": false
}
```

**修改维护时间**（下午 2-4 点）：
```json
{
  "maintenance": {
    "start_hour": 14,
    "start_minute": 0,
    "end_hour": 16,
    "end_minute": 0
  }
}
```

**完全禁用维护时间**（24 小时运行）：
```json
{
  "maintenance": {
    "start_hour": 0,
    "start_minute": 0,
    "end_hour": 0,
    "end_minute": 0
  }
}
```

---

## 🏗️ 核心架构

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

**核心原则**：所有微信 GUI 操作只在主线程执行。

- **主线程**：轮询检测 → 收发消息 → 控制窗口
- **后台线程**：各实例运行业务逻辑（Steam 监控、定时任务、AI 对话）
- **消息队列**：后台线程 → `msg_queue.put()` → 主线程消费发送

### 消息流程

```
用户发送消息 → 微信闪烁 → 主线程检测 → 获取消息 → 分发给实例
                                                              ↓
实例处理 ←──────────────────────────────────────────────┘
    ↓
发送响应 → 加入队列 → 主线程消费 → 实际发送 → 捕获新消息
```

详细实现细节见：[核心架构与实现细节](./docs/architecture.md)

---

## 🎯 高级功能

### @mentions 功能

支持在群聊中@特定成员：

```python
# AI 回复时自动添加@标签
self.send_message({
    "target": chat_id,
    "content": "@MONO 1 什么 1，快去休息。"
})

# 系统会自动：
# 1. 提取@用户：MONO
# 2. 从消息内容中移除@标签
# 3. 调用真正的微信@功能（输入@ → 选择成员 → 回车确认）
# 4. 发送消息："1 什么 1，快去休息。"
```

### 消息队列机制

后台实例不直接发送消息，而是加入队列由主线程统一发送：

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

### 反检测机制

- **随机延迟**：所有操作前后添加随机延迟
- **人类行为模拟**：打字延迟、操作间隔模拟真实用户
- **窗口管理**：自动最小化微信，降低被发现风险

---

## 🛠️ 开发指南

### 创建新实例

1. 在 `instances/` 目录创建新文件
2. 继承 `BaseInstance` 并实现抽象方法
3. 在 `core/instance_factory.py` 注册实例类型
4. 在 `config.json` 添加配置

详细教程见：[实例开发指南](./docs/instance-development.md)

### 项目结构

```
cs-Solidarity/
├── main.py                 # 主程序入口
├── config.json            # 主配置文件
├── core/                  # 核心模块
│   ├── base_instance.py   # 实例基类
│   ├── instance_factory.py # 实例工厂
│   └── wechat_instance.py # 微信实例
├── instances/             # 实例实现
│   ├── steam_auto.py
│   ├── daily_auto.py
│   ├── chat_auto.py
│   └── kori_chat.py
├── instconfig/            # 实例配置
├── utils/                 # 工具函数
├── wxauto/                # 微信自动化库
├── KouriChat/             # KoriChat 子项目
└── web/                   # Web 控制面板
```

### 调试技巧

1. **开启调试模式**：`config.json` 中设置 `"debug_mode": true`
2. **查看日志**：日志文件在 `logs/` 目录
3. **单实例测试**：先只配置一个实例，排除干扰

---

## ❓ 常见问题

### 1. 微信版本不兼容

**问题**：提示 `wxauto` 无法找到微信窗口

**解决**：
- 确保微信版本为 v3.9.8.15（推荐）
- 以管理员身份运行程序
- 检查微信是否已登录

### 2. 消息发送失败

**问题**：消息未发送或发送到错误聊天

**解决**：
- 检查 `enable_send` 是否为 `true`
- 检查是否在维护时间内
- 查看日志文件确认错误信息

### 3. @功能不生效

**问题**：@的是文字，没有真正@到人

**解决**：
- 确保窗口没有最小化（@操作需要窗口可见）
- 检查群聊中是否有该成员
- 查看日志中的@操作记录

### 4. 实例不响应消息

**问题**：发送消息后实例无反应

**解决**：
- 检查实例是否正常运行（查看日志）
- 确认触发前缀是否正确
- 检查群组/用户权限配置

### 5. Web 控制面板无法连接

**问题**：浏览器无法访问 Web 面板

**问题**：
- 确保 `run_config_web.py` 已启动
- 检查防火墙是否阻止端口
- 访问 `http://localhost:8000`（默认端口）

---

## 📚 相关文档

- [核心架构与实现细节](./docs/architecture.md) - 线程模型、消息收发、@实现等
- [实例开发指南](./docs/instance-development.md) - 如何开发新实例
- [KoriChat 使用指南](./KouriChat/README.md) - KoriChat 详细文档
- [Web 控制面板](./web/README.md) - Web 面板使用教程

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

## 🙏 致谢

- [wxauto](https://github.com/cluic/wxauto) - 微信自动化库
- [KouriChat](https://github.com/KouriChat/KouriChat) - 智能聊天助手

---

**Made with ❤️ by cs-Solidarity Team**

## Star History

<a href="https://www.star-history.com/?repos=xufezyq%2Fcs-Solidarity&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=xufezyq/cs-Solidarity&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=xufezyq/cs-Solidarity&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=xufezyq/cs-Solidarity&type=date&legend=top-left" />
 </picture>
</a>