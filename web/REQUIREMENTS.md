# cs-Solidarity Web 控制面板 — 详细需求文档

## 1. 项目概述

cs-Solidarity 是一个基于 wxauto 的微信机器人，运行在内网 Windows 机器上。Web 控制面板提供远程管理能力，通过 Agent-Server WebSocket 架构实现。

### 目标
- 通过浏览器远程管理微信机器人
- 实时查看运行状态和日志
- 在线编辑配置文件
- 用户权限管理（管理员/普通用户）

### 技术栈
- **后端**：Python 3.9+, FastAPI, WebSocket, JWT 认证
- **前端**：Vue 3 (CDN), 原生 CSS
- **Agent**：Python WebSocket 客户端
- **通信**：JSON over WebSocket

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      架构总览                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Machine A（内网 Windows）          Machine B（公网服务器）         │
│  ┌─────────────────────┐           ┌──────────────────────────┐ │
│  │  cs-Solidarity Bot  │           │  Web Server (FastAPI)    │ │
│  │  - main.py          │           │  - server.py             │ │
│  │  - wxauto           │           │  - bridge.py             │ │
│  │  - config.json      │           │  - auth.py               │ │
│  │  - logs/            │           │  - api/                  │ │
│  │  - instconfig/      │           │  - static/index.html     │ │
│  └─────────┬───────────┘           └────────────┬─────────────┘ │
│            │                                     │              │
│  ┌─────────▼───────────┐                        │              │
│  │  Agent (client.py)  │◄───── WebSocket ───────►│              │
│  │  - handler.py       │   (A 主动连接 B)         │              │
│  │  - watcher.py       │                         │              │
│  └─────────────────────┘                         │              │
│                                                  │              │
│                              ┌──────────────────▼────────────┐ │
│                              │  用户浏览器                     │ │
│                              │  - 登录认证                    │ │
│                              │  - 仪表盘/配置/日志/控制        │ │
│                              └───────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 通信流程
1. Agent（A）主动连接到 Web Server（B）的 WebSocket 端点
2. 用户通过浏览器访问 B 的 Web 面板
3. 用户操作触发 API 请求 → B 通过 WebSocket 转发给 A → A 执行并返回结果

## 3. 功能需求

### 3.1 认证与权限
- **用户角色**：admin（管理员）、user（普通用户）
- **登录方式**：用户名 + 密码，JWT token（有效期 24 小时）
- **admin 权限**：查看所有信息 + 修改配置 + 控制 bot + 管理用户
- **user 权限**：只能查看信息（仪表盘、实例状态、日志）
- **首次运行**：自动生成 admin 账户，随机密码输出到控制台

### 3.2 仪表盘
- 显示 bot 运行状态（运行中/已停止/Agent 未连接）
- 实例状态列表（每个微信实例的运行情况）
- 最近日志预览（最近 10 条）

### 3.3 实例管理
- 实例卡片列表，显示实例名称、状态、备注
- 可展开查看实例详细配置
- 从 config.json 和 instconfig/ 目录读取

### 3.4 配置编辑（仅 admin）
- JSON 编辑器，支持语法高亮
- 保存按钮（写入前自动备份）
- 备份/恢复功能
- 支持 config.json 和各实例配置

### 3.5 Steam 功能
- 好友列表表格
- 排行榜展示
- 从 bot 数据中读取

### 3.6 日志查看
- 按日期筛选
- 按日志级别筛选（INFO/WARNING/ERROR/DEBUG）
- 关键词搜索
- 实时日志推送（WebSocket）

### 3.7 控制面板（仅 admin）
- 启动/停止/重启 bot
- Debug 模式开关
- 状态指示

### 3.8 用户管理（仅 admin）
- 用户列表（用户名、角色、创建时间）
- 创建新用户
- 删除用户
- 修改用户角色

## 4. 非功能需求

### 4.1 安全性
- 密码使用 bcrypt 哈希存储
- JWT token 有效期 24 小时，支持手动登出
- HTTPS 推荐部署（Nginx 反向代理）
- Agent 连接使用 token 验证
- 输入验证和 SQL 注入防护（虽然使用 JSON 文件存储）

### 4.2 性能
- API 响应时间 < 500ms（不含 Agent 通信）
- Agent-Server 通信超时 10 秒
- 前端页面加载 < 2 秒
- 日志文件读取限制最大 1000 行

### 4.3 可用性
- 响应式布局，支持移动端
- 深色主题
- 操作反馈（成功/失败提示）
- Agent 断线检测和提示

## 5. 接口规范

### 5.1 认证 API

#### POST /api/auth/login
登录获取 JWT token

**请求：**
```json
{
  "username": "admin",
  "password": "xxx"
}
```

**响应：**
```json
{
  "success": true,
  "token": "eyJ...",
  "user": {
    "username": "admin",
    "role": "admin"
  }
}
```

#### POST /api/auth/change-password
修改密码（需登录）

**请求：**
```json
{
  "old_password": "xxx",
  "new_password": "yyy"
}
```

### 5.2 用户管理 API（仅 admin）

#### GET /api/users
获取用户列表

#### POST /api/users
创建用户

#### DELETE /api/users/{username}
删除用户

#### PUT /api/users/{username}/role
修改用户角色

### 5.3 配置 API（需通过 Agent）

#### GET /api/config
获取配置列表

#### GET /api/config/{name}
读取指定配置

#### POST /api/config/{name}
写入配置

#### POST /api/config/backup
备份配置

#### GET /api/config/backups
获取备份列表

#### POST /api/config/restore
恢复配置

### 5.4 状态 API

#### GET /api/status/overview
获取总体状态

#### GET /api/status/instances
获取实例列表

### 5.5 日志 API

#### GET /api/logs
获取日志列表

#### GET /api/logs/{date}
读取指定日期日志

### 5.6 控制 API（仅 admin）

#### POST /api/control/start
启动 bot

#### POST /api/control/stop
停止 bot

#### POST /api/control/restart
重启 bot

#### POST /api/control/debug
切换 debug 模式

### 5.7 WebSocket API

#### /ws/agent
Agent 连接端点

#### /ws/logs
日志推送端点

## 6. 数据模型

### 6.1 用户模型
```json
{
  "username": "admin",
  "password_hash": "$2b$...",
  "role": "admin",
  "created_at": "2024-01-01T00:00:00",
  "last_login": "2024-01-01T00:00:00"
}
```

### 6.2 Agent-Server 协议消息
```json
// 请求
{
  "id": "uuid",
  "type": "request",
  "action": "config.read",
  "params": {"name": "config.json"}
}

// 响应
{
  "id": "uuid",
  "type": "response",
  "success": true,
  "data": {}
}

// 推送
{
  "type": "push",
  "event": "log.new",
  "data": {"line": "...", "level": "INFO"}
}

// 心跳
{"type": "ping"}
{"type": "pong"}
```

### 6.3 配置文件结构
参考 cs-Solidarity 项目的 config.json 和 instconfig/ 目录。

## 7. 部署说明

### 7.1 Machine A（内网）
1. 安装依赖：`pip install -r agent/requirements.txt`
2. 运行 Agent：`python agent/client.py --server ws://B_IP:8000/ws/agent --token xxx --root D:\code\cs-Solidarity`

### 7.2 Machine B（公网）
1. 安装依赖：`pip install -r web/requirements.txt`
2. 运行 Server：`cd web && uvicorn server:app --host 0.0.0.0 --port 8000`
3. 首次运行会生成 admin 密码，记录并登录修改

### 7.3 生产环境
- 使用 Nginx 反向代理 + HTTPS
- 配置 systemd/supervisor 管理进程
- 定期备份 users.json

## 8. 未来扩展
- 多 Agent 支持（管理多台机器）
- 文件管理器（远程文件浏览）
- 实时聊天监控
- 告警通知（邮件/Telegram）
- 操作审计日志
