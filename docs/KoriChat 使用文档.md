# KoriChat 聊天机器人完整使用文档

## 📚 目录

- [一、系统概述](#一系统概述)
- [二、核心功能列表](#二核心功能列表)
- [三、系统架构](#三系统架构)
- [四、配置指南](#四配置指南)
- [五、功能使用说明](#五功能使用说明)
- [六、人设配置](#六人设配置)
- [七、消息队列机制](#七消息队列机制)
- [八、定时任务](#八定时任务)
- [九、调试与故障排除](#九调试与故障排除)

---

## 一、系统概述

### 1.1 什么是 KoriChat？

KoriChat 是一个基于微信的 AI 聊天机器人系统，通过集成 DeepSeek 大语言模型，实现智能化的聊天回复。系统采用模块化设计，支持多角色人设、记忆管理、图像识别、自动发送等功能。

### 1.2 主要特点

- ✅ **AI 智能回复**：基于 DeepSeek LLM，生成自然流畅的回复
- ✅ **多角色人设**：支持自定义角色性格、语气、背景故事
- ✅ **记忆管理**：自动存储对话历史，提供上下文感知
- ✅ **图像处理**：支持图片识别和表情符号处理
- ✅ **自动发送**：定时主动联系用户，保持互动
- ✅ **群聊支持**：支持群聊配置和触发词设置
- ✅ **意图识别**：识别提醒、搜索等用户意图
- ✅ **维护时间**：支持设置免打扰时段

### 1.3 适用场景

- 个人微信助手
- 智能客服
- 角色扮演聊天
- 自动回复助手
- 情感陪伴机器人

---

## 二、核心功能列表

### 2.1 基础功能

| 功能 | 说明 | 状态 |
|------|------|------|
| 私聊回复 | 自动回复私聊消息（默认接收所有私聊） | ✅ 可用 |
| 群聊回复 | 根据配置回复群聊消息 | ✅ 可用 |
| 多角色切换 | 支持多个人设配置 | ✅ 可用 |
| 上下文记忆 | 记住对话历史 | ✅ 可用 |
| 表情符号处理 | 识别和发送表情 | ✅ 可用 |

### 2.2 高级功能

| 功能 | 说明 | 配置位置 |
|------|------|----------|
| **图像识别** | 识别用户发送的图片内容 | `media_settings.image_recognition` |
| **自动发送** | 定时主动给用户发消息 | `behavior_settings.auto_message` |
| **安静时间** | 设置免打扰时段 | `behavior_settings.quiet_time` |
| **意图识别** | 识别提醒、搜索等意图 | `intent_recognition_settings` |
| **网络搜索** | 联网搜索信息 | `network_search_settings` |
| **群聊配置** | 为不同群聊配置专人设 | `user_settings.group_chat_config` |
| **定时任务** | 设置定时发送任务 | `schedule_settings.tasks` |

### 2.3 系统功能

| 功能 | 说明 | 状态 |
|------|------|------|
| 消息队列 | 缓冲消息，统一处理 | ✅ 可用 |
| 维护时间检查 | 00:15-08:00 暂停发送 | ✅ 可用 |
| 日志记录 | 详细运行日志 | ✅ 可用 |
| 自动更新 | 系统自动升级 | ✅ 可用 |

---

## 三、系统架构

### 3.1 目录结构

```
KouriChat/
├── run.py                          # 程序入口
├── src/main.py                     # 主程序逻辑
├── src/handlers/                   # 消息处理器
│   ├── message.py                 # 消息处理核心
│   ├── emoji.py                   # 表情处理
│   ├── image.py                   # 图片处理
│   └── autosend.py                # 自动发送
├── src/services/ai/               # AI 服务
│   ├── llm_service.py             # 大语言模型服务
│   ├── image_recognition_service.py  # 图像识别
│   └── network_search_service.py     # 网络搜索
├── modules/memory/                # 记忆模块
│   ├── memory_service.py          # 记忆服务
│   └── content_generator.py       # 内容生成器
├── modules/recognition/           # 意图识别模块
│   ├── reminder_request_recognition/  # 提醒识别
│   └── search_request_recognition/    # 搜索识别
├── data/config/                   # 配置文件
│   └── config.json                # 主配置文件
└── data/avatars/                  # 人设目录
    ├── ATRI/                      # 角色 1
    ├── MONO/                      # 角色 2
    └── Nijiko/                    # 角色 3
```

### 3.2 消息处理流程

```
用户发送消息
    ↓
微信消息监听（主框架统一接收）
    ↓
KoriChatInstance.handle_message()
    ↓
MessageHandler.handle_user_message()
    ↓
┌─────────────────────────────────┐
│  [可选] 图像识别                │
│  [可选] 表情识别                │
│  [可选] 意图识别（提醒/搜索）   │
└─────────────────────────────────┘
    ↓
LLM 生成回复（基于人设和记忆）
    ↓
消息队列缓冲（等待更多消息）
    ↓
分批发送回复（支持$分隔符）
```

### 3.3 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| **KoriChatInstance** | `instances/kori_chat.py` | 框架适配器，集成到主框架 |
| **MessageHandler** | `src/handlers/message.py` | 消息处理核心，管理对话队列 |
| **LLMService** | `src/services/ai/llm_service.py` | 调用 AI 模型生成回复 |
| **MemoryService** | `modules/memory/memory_service.py` | 记忆管理，存储对话历史 |
| **AutoSendHandler** | `src/handlers/autosend.py` | 自动发送，定时联系用户 |

---

## 四、配置指南

### 4.1 快速开始

#### 步骤 1：复制配置文件

```bash
# 在项目根目录执行
cp KouriChat/data/config/config.json.template KouriChat/data/config/config.json
```

#### 步骤 2：编辑配置文件

打开 `KouriChat/data/config/config.json`，配置以下必填项：

```json
{
  "categories": {
    "user_settings": {
      "settings": {
        "listen_list": {
          "value": ["你的微信昵称"]
        }
      }
    },
    "llm_settings": {
      "settings": {
        "api_key": {
          "value": "你的 DeepSeek API 密钥"
        },
        "base_url": {
          "value": "https://api.kourichat.com/v1"
        },
        "model": {
          "value": "kourichat-v3"
        }
      }
    },
    "behavior_settings": {
      "settings": {
        "context": {
          "avatar_dir": {
            "value": "data/avatars/ATRI"
          }
        }
      }
    }
  }
}
```

#### 步骤 3：配置主框架

编辑项目根目录的 `config.json`：

```json
{
  "instances": [
    {
      "type": "korichat",
      "config": "instconfig/korichat_config.json"
    }
  ]
}
```

`korichat` 是当前主框架注册的实例类型名称。`instconfig/korichat_config.json` 是 cs-Solidarity 对 KoriChat 的适配配置，它会覆盖 KouriChat 内部 `KouriChat/data/config/config.json` 中的默认人设和群聊配置。

示例：

```json
{
  "config_file": "KouriChat/data/config/config.json",
  "avatar_dir": "data/avatars/MONO",
  "group_chat_config": [
    {
      "groupName": "【CS】团结友爱",
      "avatar": "data/avatars/MONO",
      "triggers": ["MONO", "mono", "Mono", "莫诺"],
      "enableAtTrigger": true,
      "replyMode": "at_only"
    }
  ],
  "private_chat_config": [
    {
      "friendName": "好友昵称",
      "avatar": "data/avatars/CALEB"
    }
  ]
}
```

#### 步骤 4：运行程序

```bash
# 使用虚拟环境运行
.\venv\Scripts\python.exe main.py
```

### 4.2 详细配置说明

#### 4.2.1 用户设置 (`user_settings`)

```json
"listen_list": {
  "value": ["用户 1", "用户 2"],
  "description": "要监听的用户列表（请使用微信昵称，不要使用备注名）"
}
```

**说明**：
- 填写要监听的微信用户昵称
- 必须是微信昵称，不是备注名
- 可以填写多个用户
- **注意**：从 v1.0.12 版本开始，私聊消息默认都会被接收，不需要在 `listen_list` 中添加用户
- `listen_list` 现在仅用于控制群聊消息的监听

**私聊消息处理逻辑**：
- ✅ **私聊**：所有私聊消息默认都会被接收和回复（无论是否在 `listen_list` 中）
- ⚠️ **群聊**：只有在 `listen_list` 中的群聊才会被处理
- 💡 **建议**：如果需要限制某些用户的私聊回复，需要通过其他方式（如黑名单）实现

#### 4.2.2 大语言模型设置 (`llm_settings`)

```json
{
  "api_key": {
    "value": "sk-xxxxxxxxxxxxxxxx",
    "description": "DeepSeek API 密钥"
  },
  "base_url": {
    "value": "https://api.kourichat.com/v1",
    "description": "API 基础 URL"
  },
  "model": {
    "value": "kourichat-v3",
    "options": [
      "kourichat-v3",
      "deepseek-ai/DeepSeek-V3",
      "Pro/deepseek-ai/DeepSeek-V3",
      "Pro/deepseek-ai/DeepSeek-R1"
    ]
  },
  "max_tokens": {
    "value": 2000,
    "description": "回复最大 token 数量"
  },
  "temperature": {
    "value": 1.1,
    "description": "AI 回复的温度值（0.0-1.7）",
    "min": 0.0,
    "max": 1.7
  },
  "auto_model_switch": {
    "value": false,
    "description": "是否使用备用模型"
  }
}
```

**参数说明**：
- **api_key**：必填，DeepSeek API 密钥
- **model**：使用的 AI 模型
  - `kourichat-v3`：官方优化模型
  - `deepseek-ai/DeepSeek-V3`：DeepSeek V3 模型
  - `Pro/deepseek-ai/DeepSeek-R1`：DeepSeek R1 模型（推理更强）
- **temperature**：控制回复的创造性
  - `0.0-0.5`：保守、逻辑性强
  - `0.5-1.0`：平衡
  - `1.0-1.7`：富有创造力、跳跃性

#### 4.2.3 行为设置 (`behavior_settings`)

```json
{
  "auto_message": {
    "content": {
      "value": "（请你模拟角色，给用户发消息想知道用户在做什么）"
    },
    "countdown": {
      "min_hours": {
        "value": 1.0,
        "description": "最小倒计时时间（小时）"
      },
      "max_hours": {
        "value": 3.0,
        "description": "最大倒计时时间（小时）"
      }
    }
  },
  "quiet_time": {
    "start": {
      "value": "22:00",
      "description": "安静时间开始"
    },
    "end": {
      "value": "08:00",
      "description": "安静时间结束"
    }
  },
  "context": {
    "max_groups": {
      "value": 15,
      "description": "最大上下文轮数"
    },
    "avatar_dir": {
      "value": "data/avatars/MONO",
      "description": "人设目录"
    }
  },
  "message_queue": {
    "timeout": {
      "value": 8,
      "description": "消息队列等待时间（秒）",
      "min": 0,
      "max": 20
    }
  }
}
```

**参数说明**：
- **auto_message**：自动发送配置
  - `content`：自动发送的内容提示词
  - `countdown`：随机间隔时间（1-3 小时）
- **quiet_time**：安静时间（22:00-08:00），此时间段内不主动发送消息
- **context.max_groups**：记忆的最大对话轮数（默认 15 轮）
- **message_queue.timeout**：消息队列缓冲时间（默认 8 秒）

#### 4.2.4 媒体设置 (`media_settings`)

```json
{
  "image_recognition": {
    "api_key": {
      "value": "你的图像识别 API 密钥"
    },
    "base_url": {
      "value": "https://api.kourichat.com/v1"
    },
    "model": {
      "value": "kourichat-vision"
    }
  },
  "text_to_speech": {
    "tts_api_key": {
      "value": "你的 Fish Audio API 密钥"
    },
    "tts_model_id": {
      "value": "TTS 模型 ID"
    }
  }
}
```

#### 4.2.5 意图识别设置 (`intent_recognition_settings`)

```json
{
  "api_key": {
    "value": ""
  },
  "base_url": {
    "value": "https://api.kourichat.com/v1"
  },
  "model": {
    "value": "kourichat-v3"
  },
  "temperature": {
    "value": 0.0,
    "min": 0.0,
    "max": 1.0
  }
}
```

**说明**：意图识别用于识别用户消息中的特定意图，如设置提醒、搜索等。

#### 4.2.6 网络搜索设置 (`network_search_settings`)

```json
{
  "search_enabled": {
    "value": false,
    "description": "启用网络搜索功能"
  },
  "weblens_enabled": {
    "value": false,
    "description": "启用网页内容提取功能"
  },
  "api_key": {
    "value": "",
    "description": "网络搜索 API 密钥（留空则使用 LLM 设置中的 API 密钥）"
  }
}
```

---

## 五、功能使用说明

### 5.1 基础聊天回复

**功能说明**：自动回复用户的私聊和群聊消息。

**配置**：
1. 在 `listen_list` 中添加用户微信昵称
2. 配置 `api_key` 和 `model`

**使用示例**：
```
用户：你好啊
KoriChat：主人，您好呀！今天有什么想和我聊的吗？(✪ω✪)
```

### 5.2 图像识别

**功能说明**：识别用户发送的图片内容，并基于图片内容进行回复。

**配置**：
```json
"media_settings": {
  "image_recognition": {
    "api_key": "你的图像识别 API 密钥",
    "model": "kourichat-vision"
  }
}
```

**使用示例**：
```
用户：[发送一张猫咪图片]
KoriChat：哇，好可爱的猫咪！它看起来好温顺呢，主人喜欢猫咪吗？
```

### 5.3 自动发送消息

**功能说明**：定时主动给用户发送消息，保持互动。

**配置**：
```json
"behavior_settings": {
  "auto_message": {
    "content": "（请你模拟角色，给用户发消息想知道用户在做什么）",
    "countdown": {
      "min_hours": 1.0,
      "max_hours": 3.0
    }
  }
}
```

**说明**：
- 每隔 1-3 小时随机时间自动发送消息
- 在安静时间（22:00-08:00）内不会发送
- 消息内容基于 `content` 提示词生成

**使用示例**：
```
[自动发送]
KoriChat：主人，您在做什么呢？我已经好久没和您聊天了~ (｡•́︿•̀｡)
```

### 5.4 安静时间/维护时间

**功能说明**：在指定时间段内不主动发送消息，避免打扰用户。

**配置**：
```json
"behavior_settings": {
  "quiet_time": {
    "start": "22:00",
    "end": "08:00"
  }
}
```

**注意**：
- KoriChat 有自己的安静时间检查（22:00-08:00）
- 主框架有维护时间检查（00:15-08:00）
- 两者都会阻止消息发送

### 5.5 群聊配置

**功能说明**：为不同群聊配置专属人设和触发词。

**配置**：
```json
"user_settings": {
  "group_chat_config": [
    {
      "groupName": "CS 团结友爱",
      "avatar": "data/avatars/ATRI",
      "triggers": ["ATRI", "亚托莉"],
      "enableAtTrigger": true,
      "replyMode": "at_only"
    }
  ]
}
```

**说明**：
- `groupName`：群聊名称
- `avatar`：该群专用的人设目录，相对于 `KouriChat/`
- `triggers`：触发词列表
- `enableAtTrigger`：是否允许通过 @ 机器人触发
- `replyMode`：`at_only` 表示仅 @ 或触发词命中时回复，`all` 表示该群所有消息都进入 KoriChat

**使用示例**：
```
群聊：CS 团结友爱
用户 A：今天天气不错
[无触发词，不回复]

用户 B：@ATRI 你觉得呢？
[包含触发词"ATRI"，触发回复]
KoriChat：哼哼，我也觉得呢！今天很适合出去玩哦~ (✪ω✪)
```

### 5.6 意图识别

**功能说明**：识别用户消息中的特定意图，如设置提醒、搜索等。

**支持的意图**：
- **提醒**：识别用户想要设置提醒的意图
- **搜索**：识别用户想要搜索信息的意图

**配置**：
```json
"intent_recognition_settings": {
  "api_key": "你的 API 密钥",
  "model": "kourichat-v3"
}
```

**使用示例**：
```
用户：提醒我明天下午 3 点开会
KoriChat：好的主人，已为您设置提醒：明天下午 3 点开会 ⏰
```

### 5.7 网络搜索

**功能说明**：联网搜索实时信息，回答最新的问题。

**配置**：
```json
"network_search_settings": {
  "search_enabled": true,
  "weblens_enabled": true,
  "api_key": "你的网络搜索 API 密钥"
}
```

**使用示例**：
```
用户：今天天气怎么样？
KoriChat：[自动搜索天气信息]
今天天气晴朗，气温 25°C，适合外出游玩哦~ ☀️
```

### 5.8 表情符号处理

**功能说明**：识别和发送表情符号，增强聊天体验。

**配置**：
- 在人设目录下创建 `emojis/` 目录
- 放置表情图片文件

**使用示例**：
```
用户：[发送动画表情]
KoriChat：[识别表情并回复]
主人是在撒娇吗？好可爱呀~ (✪ω✪)
```

---

## 六、人设配置

### 6.1 人设文件结构

```
data/avatars/{角色名}/
├── avatar.md              # 人设描述文件
└── emojis/                # 表情符号目录
    ├── happy.png
    ├── sad.png
    └── ...
```

### 6.2 avatar.md 格式

```markdown
【角色背景与定位】
- 角色的基本信息和性格特点

# 外表
- 外貌描述（身高、发型、瞳色、服装等）

# 性格
- 性格特征

【核心性格与情感特质】
1. 特质 1
2. 特质 2

【经典台词与情景示例】
- 经典台词列表
- 对话示例

【角色扮演使用说明】
1. 扮演指导 1
2. 扮演指导 2

# 备注
- 特殊说明（如：对用户的称呼、回复长度等）
```

### 6.3 示例人设：ATRI

**文件位置**：`data/avatars/ATRI/avatar.md`

**角色特点**：
- 银发红瞳的机器人少女
- 口头禅："我是高性能的嘛！"
- 性格：自信、调皮、温柔
- 对用户的称呼："主人"

**经典台词**：
```
- "哼哼，我是高性能的嘛！"
- "根据机器人保护法，主人是要被拘留的！"
- "主人，您感觉还好吗？我会一直陪在您身边。"
```

### 6.4 切换人设

**方法 1**：修改配置文件
```json
"behavior_settings": {
  "context": {
    "avatar_dir": {
      "value": "data/avatars/ATRI"
    }
  }
}
```

**方法 2**：群聊配置中指定
```json
"group_chat_config": [
  {
    "groupName": "群聊 1",
    "avatar": "data/avatars/ATRI",
    "replyMode": "at_only"
  },
  {
    "groupName": "群聊 2",
    "avatar": "data/avatars/MONO",
    "replyMode": "all"
  }
]
```

---

## 七、消息队列机制

### 7.1 消息队列的作用

**目的**：
1. 统一消息发送入口
2. 实现维护时间检查
3. 避免多个微信实例冲突
4. 支持消息缓冲

### 7.2 消息队列工作流程

```
实例调用 send_message()
    ↓
消息入队 (msg_queue.put)
    ↓
主线程从队列获取消息
    ↓
检查维护时间 (00:15-08:00)
    ↓
如果在维护时间 → 跳过发送
如果在非维护时间 → 调用原始发送方法
    ↓
微信发送消息 (wx.SendMsg)
```

### 7.3 KoriChat 内部消息拦截

当前主框架不会再通过 `set_enqueue_func()` 拦截 KoriChat 内部方法。启动时，`main.py` 会保存实例原始 `send_message()`，再把实例方法替换为入队函数：

```python
# main.py: start_instances()
orig_senders[name] = inst.send_message

def make_enqueue(n):
    def enqueue(message):
        msg_queue.put((n, "message", message))
    return enqueue

inst.send_message = make_enqueue(name)
```

KoriChat 的 `MessageHandler` 在回复时调用 `core.wechat_instance.send_message()` 或 `send_messages()`。主框架还会拦截这两个统一出口，用于 Web 聊天回复捕获、`sync_to_wx=false` 跳过微信发送，以及 Web 来源消息前缀注入。

**当前发送流程**：
```
KoriChat 处理消息
    ↓
MessageHandler 生成回复
    ↓
调用 wechat_instance.send_message/send_messages
    ↓
Web 拦截器可捕获回复
    ↓
进入微信统一发送逻辑
    ↓
发送时捕获期间新消息并防止窗口过早最小化
```

### 7.4 消息队列配置

**配置项**：
```json
"behavior_settings": {
  "message_queue": {
    "timeout": {
      "value": 8,
      "description": "消息队列等待时间（秒）"
    }
  }
}
```

**说明**：
- `timeout`：等待用户连续发送消息的时间（默认 8 秒）
- 在 timeout 时间内，消息会暂存在队列中
- timeout 后统一处理队列中的消息

---

## 八、定时任务

### 8.1 配置定时任务

**配置位置**：`schedule_settings.tasks`

**示例**：
```json
"schedule_settings": {
  "tasks": {
    "value": [
      {
        "name": "早安问候",
        "time": "08:00",
        "content": "主人，早上好！今天也是美好的一天呢~ (✪ω✪)",
        "enabled": true
      },
      {
        "name": "晚安祝福",
        "time": "22:00",
        "content": "主人，晚安~ 祝您做个好梦 (¦3[▓▓]",
        "enabled": true
      }
    ]
  }
}
```

### 8.2 定时任务参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `name` | 任务名称 | "早安问候" |
| `time` | 执行时间（HH:MM 格式） | "08:00" |
| `content` | 发送内容 | "主人，早上好！" |
| `enabled` | 是否启用 | `true` / `false` |

### 8.3 注意事项

- 定时任务会在指定时间自动发送消息
- 如果在维护时间（00:15-08:00）内，任务会跳过执行
- 可以配置多个定时任务

---

## 九、调试与故障排除

### 9.1 查看日志

**日志文件位置**：`logs/main.log`

**日志级别**：
- `DEBUG`：详细调试信息
- `INFO`：常规运行信息
- `WARNING`：警告信息
- `ERROR`：错误信息

**查看日志**：
```bash
# 使用文本编辑器打开
notepad logs/main.log

# 或在 PowerShell 中实时查看
Get-Content logs/main.log -Wait -Tail 50
```

### 9.2 常见问题

#### 问题 1：无法收到消息

**可能原因**：
1. `listen_list` 配置错误
2. 微信昵称填写的是备注名而不是昵称
3. 微信窗口未登录

**解决方法**：
```json
// 确保填写的是微信昵称，不是备注名
"listen_list": {
  "value": ["正确的微信昵称"]
}
```

#### 问题 2：AI 回复异常或不回复

**可能原因**：
1. API 密钥错误
2. 模型配置错误
3. 网络连接问题

**解决方法**：
1. 检查 `api_key` 是否正确
2. 检查 `base_url` 是否正确
3. 检查网络连接
4. 查看日志文件确认错误信息

#### 问题 3：人设不符或回复风格不对

**可能原因**：
1. `avatar_dir` 路径错误
2. `avatar.md` 文件格式错误

**解决方法**：
1. 检查 `avatar_dir` 路径是否正确
2. 检查 `avatar.md` 文件格式
3. 确保 `avatar.md` 包含必要的角色描述

#### 问题 4：消息发送失败

**可能原因**：
1. 微信实例初始化失败
2. 微信窗口未找到
3. 维护时间检查阻止发送

**解决方法**：
1. 确保微信已登录
2. 查看日志确认错误信息
3. 检查当前时间是否在维护时间外

#### 问题 5：自动发送不工作

**可能原因**：
1. 安静时间设置
2. 维护时间检查
3. 监听列表为空

**解决方法**：
1. 检查当前时间是否在安静时间外（22:00-08:00）
2. 检查当前时间是否在维护时间外（00:15-08:00）
3. 确保 `listen_list` 不为空

### 9.3 调试技巧

#### 技巧 1：启用详细日志

在配置文件中设置日志级别：
```python
import logging
logging.getLogger("main").setLevel(logging.DEBUG)
```

#### 技巧 2：测试单功能

创建测试脚本测试单个功能：
```python
from KouriChat.src.handlers.message import MessageHandler

# 测试消息处理
handler = MessageHandler(...)
handler.handle_user_message("测试消息", "测试用户", ...)
```

#### 技巧 3：监控消息队列

在主框架中添加队列监控：
```python
print(f"队列长度：{msg_queue.qsize()}")
print(f"队列内容：{list(msg_queue.queue)}")
```

### 9.4 性能优化

#### 优化 1：调整消息队列超时时间

```json
"message_queue": {
  "timeout": {
    "value": 5  // 减少等待时间，提高响应速度
  }
}
```

#### 优化 2：减少上下文轮数

```json
"context": {
  "max_groups": {
    "value": 10  // 减少记忆轮数，降低 token 消耗
  }
}
```

#### 优化 3：调整自动发送间隔

```json
"auto_message": {
  "countdown": {
    "min_hours": 2.0,  // 增加最小间隔
    "max_hours": 4.0   // 增加最大间隔
  }
}
```

---

## 十、附录

### 10.1 API 密钥获取

**DeepSeek API 密钥**：
1. 访问 DeepSeek 官网：https://www.deepseek.com/
2. 注册账号
3. 创建 API Key
4. 复制 API Key 到配置文件

### 10.2 推荐配置

**基础配置**（适合个人使用）：
```json
{
  "llm_settings": {
    "model": "kourichat-v3",
    "max_tokens": 2000,
    "temperature": 1.1
  },
  "behavior_settings": {
    "quiet_time": {
      "start": "22:00",
      "end": "08:00"
    },
    "context": {
      "max_groups": 15
    }
  }
}
```

**高性能配置**（追求更好效果）：
```json
{
  "llm_settings": {
    "model": "Pro/deepseek-ai/DeepSeek-R1",
    "max_tokens": 3000,
    "temperature": 1.3,
    "auto_model_switch": true
  },
  "media_settings": {
    "image_recognition": {
      "model": "kourichat-vision"
    }
  },
  "network_search_settings": {
    "search_enabled": true,
    "weblens_enabled": true
  }
}
```

### 10.3 资源链接

- **项目地址**：https://github.com/KouriChat/KouriChat
- **DeepSeek 官网**：https://www.deepseek.com/
- **文档更新**：查看项目 README.md

---

## 十一、更新日志

### v2.5（当前集成版本）
- ✅ 主框架实例类型统一为 `korichat`
- ✅ 适配配置统一使用 `instconfig/korichat_config.json`
- ✅ 群聊配置采用 `groupName`、`avatar`、`triggers`、`replyMode`
- ✅ Web 聊天回复捕获和 `sync_to_wx` 模式走 `wechat_instance` 统一发送出口

### v1.0.11
- ✅ 修复请求超时导致无法获取好友信息的问题
- ✅ 添加 SteamAPI 超时和代理支持
- ✅ 优化消息队列机制，确保所有消息都经过维护时间检查
- ✅ 添加 KoriChat 内部消息拦截，统一使用主框架消息队列

### v1.0.10
- ✅ 添加图像识别功能
- ✅ 添加意图识别功能
- ✅ 优化记忆管理

### v1.0.9
- ✅ 添加群聊配置支持
- ✅ 添加定时任务功能

---

**文档版本**：v2.5
**最后更新**：2026-06-02
**维护者**：cs-Solidarity 团队
