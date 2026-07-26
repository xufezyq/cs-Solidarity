# CS2 聊天式 Demo 分析与自动视频工作流方案

## 目标

通过 `cs-Solidarity` 的微信 Bot 和 Web 聊天，用自然语言完成以下工作流：

1. 查询并选择想要的 CS2 对局。
2. 使用 `CS-Demo-Downloader` 下载对应 Demo。
3. 使用 `CS2-insight-agent` 导入并分析 Demo。
4. 根据聊天指令选择高光、残局、三杀或下饭片段。
5. 自动驱动 CS2 与 OBS 录制画面。
6. 使用 FFmpeg 自动合成视频。
7. 将成片发送回对应微信群聊，或提供给 Web 会话下载。

## 现有能力

### cs-Solidarity

当前已经具备：

- 微信消息接收、群聊路由和实例机制。
- Web 聊天入口。
- 微信文本与文件发送队列。
- 可扩展的实例工厂。
- Web、Agent、Bot 之间的消息桥接。

关键入口：`main.py`、`web/api/chat.py`、`bot/api_server.py`、`core/instance_factory.py`。

### CS2-insight-agent

当前已经具备：

- 本地 Demo 导入：`POST /api/demo/open-local`
- Demo 库、监听目录和自动入库。
- 玩家名单识别：`GET /api/demos/{id}/players`
- 高光分析：`POST /api/demos/{id}/analyze`
- CS2 + OBS 自动录制：`POST /api/recording/queue`
- 录制片段管理：`GET /api/recorded-clips`
- FFmpeg 合辑导出：`POST /api/montage/export`

关键入口：`backend/app/main.py`、`backend/app/recording/api.py`、`backend/app/recording/models.py`。

### CS-Demo-Downloader

当前已经具备：

- 查询完美平台比赛。
- 指定目标 SteamID64。
- 使用 Token 所属 `PW_UID` 查询其他玩家。
- 下载并解压 `.dem`。
- 获取比赛 metadata。

## 推荐架构

```text
微信 / Web 聊天
       |
       v
cs-Solidarity 消息路由
       |
       v
CS2 Video Orchestrator
       |
       +-- 比赛查询与选择
       +-- Demo Downloader
       +-- CS2 Insight HTTP API
       +-- 持久化任务队列
       +-- 进度通知
       |
       v
CS2 + OBS 录制 -> FFmpeg 合成 -> 微信群发送
```

编排器建议放在 `cs-Solidarity` 中，新增一个 `cs2_video` 实例，但核心工作流应实现为独立 service，不要直接塞入现有 `ChatAuto`。这样微信和 Web 聊天可以共用完全相同的任务系统。

## 聊天交互设计

建议采用“明确指令 + 自然语言解析”，不要让 LLM 直接执行任意命令。

示例：

```text
分析完美玩家 76561198383859685 最近一场
找他昨天 Mirage 的比赛
下载第 2 场
剪这场的三杀和残局
生成 60 秒高光并发到本群
任务状态
取消任务 CS2-20260726-001
```

推荐的完整交互流程：

1. 用户提出查询请求。
2. Bot 返回最近比赛列表，包括时间、地图、比分和比赛 ID。
3. 用户回复“第 2 场”进行确认。
4. Bot 创建后台任务并立即回复任务编号。
5. 后台下载和解析 Demo。
6. Bot 返回分析摘要，让用户选择三杀、残局、全部高光或下饭片段。
7. 用户确认后进入 CS2 + OBS 录制。
8. FFmpeg 自动合成。
9. 成片发送回原来的微信群或 Web 会话。

第一版不建议收到一句话后立即录制。先让用户确认比赛和片段，可以避免选错比赛后浪费录制时间。

## 需要改造的模块

### 1. 下载器增加机器接口

目前 CLI 默认偏向批量下载，需要增加面向编排器的结构化接口：

```text
list-matches(target_steamid)
get-match(match_id)
download-match(match_id, output_dir)
```

必须支持只下载用户确认的一场，并返回结构化结果：

```json
{
  "match_id": "9213135914489447564",
  "map": "de_mirage",
  "played_at": "2026-07-25T20:30:00+08:00",
  "score": "13:9",
  "demo_path": "D:\\Vulkan\\csAuto\\data\\demos\\9213135914489447564_0.dem"
}
```

### 2. CS2 Insight 增加自动化任务 API

现有分析和录制接口基本够用，但录制接口是长时间同步请求。建议增加：

```text
POST /api/automation/jobs
GET  /api/automation/jobs/{id}
POST /api/automation/jobs/{id}/cancel
GET  /api/automation/jobs/{id}/events
```

自动化任务内部复用现有 `/analyze`、`/recording/queue` 和 `/montage/export`，避免复制分析和录制逻辑。

### 3. 持久化任务状态

建议使用 SQLite，至少保存：

```text
job_id
source_channel
reply_target
requester
target_steamid
match_id
demo_path
insight_demo_id
selected_clips
status
progress
output_video
error
created_at
updated_at
```

任务状态机：

```text
awaiting_match
-> downloading
-> ingesting
-> analyzing
-> awaiting_clip_selection
-> waiting_recording
-> recording
-> composing
-> sending
-> completed / failed / cancelled
```

任务状态必须持久化，保证进程重启后不会丢失任务，也不会重复下载、录制或发送。

### 4. 新增 cs2_video 消息实例

在 `cs-Solidarity` 中负责：

- 识别 CS2 任务指令。
- 保存微信群、私聊或 Web 会话来源。
- 调用编排器。
- 接收用户对比赛和片段的二次确认。
- 查询、取消任务。
- 把后台进度发回原会话。

Web 聊天当前请求超时远短于完整视频任务耗时，因此收到请求后必须立即返回任务号，不能让聊天 HTTP 请求一直等待。

### 5. 改造大文件发送

现有 `/send/file` 会先把上传文件完整读入内存，不适合数百 MB 的视频。由于所有组件计划运行在同一台机器，应新增：

```text
POST /send/local-file
```

示例请求：

```json
{
  "target": "目标微信群",
  "path": "D:\\Vulkan\\csAuto\\data\\exports\\CS2-20260726-001.mp4"
}
```

该接口必须限制只能读取配置允许目录内的文件，防止任意路径读取。

如果成片超过微信可发送范围，应自动采取以下策略之一：

- 使用更低码率重新压缩。
- 按片段分别发送。
- 发送 Web 下载链接。

## 端到端工作流

### 比赛查询

1. 从聊天消息提取平台、目标 SteamID64、时间和地图条件。
2. 调用下载器获取结构化比赛列表。
3. 对结果按日期、地图和比分筛选。
4. 将候选比赛发给用户确认。

### Demo 下载与入库

1. 根据确认的 `match_id` 只下载一场 Demo。
2. 下载目录直接设置为 CS2 Insight 的监听目录。
3. 等待 Demo 自动入库，或调用 `/api/demo/open-local`。
4. 保存下载任务与 Insight `demo_id` 的对应关系。

推荐统一目录：

```text
D:\Vulkan\csAuto\data\demos
```

这样不需要在项目之间复制数 GB 的 Demo 文件。

### 分析与片段选择

1. 调用玩家名单接口确定目标玩家。
2. 优先使用 SteamID64 匹配，不依赖可能重复的昵称。
3. 调用 Demo 分析接口。
4. 根据用户指令筛选片段类型和标签。
5. 返回简短摘要，让用户确认最终录制集合。

### 自动录制

1. 将分析结果转换成 `RecordingRequestDTO`。
2. 检查 CS2、OBS、OBS WebSocket 和录制场景状态。
3. 获取全局录制锁。
4. 调用 `/api/recording/queue`。
5. 持续更新任务进度。
6. 记录生成的 clip ID 和文件路径。

### 视频合成与发送

1. 按聊天选择的顺序组织录制片段。
2. 应用 BGM、转场、片头、片尾和玩家名牌预设。
3. 调用 `/api/montage/export`。
4. 检查输出大小和编码格式。
5. 必要时压缩。
6. 调用本地文件发送接口，将视频发送到原会话。

## 运行和并发约束

整套系统建议运行在同一台 Windows 机器：

- 微信桌面版需要可交互桌面。
- CS2 自动播放需要桌面会话。
- OBS 必须运行且 WebSocket 可连接。
- CS2 Insight 录制期间不能同时运行另一条录制任务。
- 下载和 Demo 分析可以有限并行。
- CS2 + OBS 录制必须全局串行。
- FFmpeg 合成是否并行需要根据 CPU、GPU 和磁盘负载限制。

建议使用三类队列：

```text
download_queue: 允许少量并发
analysis_queue: 允许少量并发
recording_queue: concurrency = 1
```

## 安全与权限

需要至少实现以下控制：

- 微信群和用户白名单。
- 用户到 SteamID64 的绑定。
- 普通用户只能操作自己绑定的玩家。
- 管理员才能查询任意目标玩家。
- PWA Token 只存放在本地密钥配置，不进入日志和聊天历史。
- 所有日志中的签名参数和 Token 必须脱敏。
- 本地文件发送接口采用允许目录校验。
- 对重复消息使用幂等键，防止重复生成视频。
- 所有任务保留发起人、来源群聊和操作记录。

## 故障处理

| 阶段 | 常见问题 | 处理方式 |
| --- | --- | --- |
| 查询 | Token 过期、权限不足 | 提示管理员刷新 Token |
| 下载 | URL 过期、网络中断 | 重新生成签名并断点重试 |
| 入库 | 文件未稳定、重复文件 | 校验大小与哈希后再入库 |
| 分析 | Demo 不兼容、解析器异常 | 使用隔离解析并保存错误日志 |
| 录制 | CS2 已运行、OBS 未连接 | 进入等待或失败状态，不重复启动 |
| 合成 | FFmpeg 缺失、硬件编码失败 | 回退软件编码 |
| 发送 | 文件过大、微信窗口异常 | 压缩、拆分或提供下载链接 |

## 实施阶段

### 第一阶段：文字分析闭环

- 微信和 Web 输入目标 SteamID64。
- 返回最近比赛列表供选择。
- 单场 Demo 下载。
- 自动导入 CS2 Insight。
- 分析指定玩家。
- 在聊天中返回文字版高光结果。

这一阶段用于验证比赛识别、Demo 下载、玩家定位和分析结果是否稳定。

### 第二阶段：自动视频闭环

- 根据分析结果生成 `RecordingRequestDTO`。
- 自动调用 CS2 + OBS 录制队列。
- 使用默认模板合成视频。
- 将视频发送到原微信群或 Web 会话。

### 第三阶段：产品化

- 自然语言筛选地图、日期、比分和击杀类型。
- 用户与 SteamID64 绑定。
- 多群权限控制。
- 任务进度、取消和失败重试。
- 下载、分析、录制结果去重与缓存。
- BGM、片头、片尾和视频风格预设。
- Web 任务中心、历史记录和产物下载。
- 管理员资源监控和任务队列控制。

## 推荐的第一步

先实现下面这条最小链路：

```text
聊天查询比赛
-> 用户确认比赛
-> 单场下载
-> CS2 Insight 导入
-> 分析目标玩家
-> 聊天返回分析摘要
```

验证该链路稳定后，再接入耗时更长、桌面环境依赖更强的 CS2 + OBS 自动录制。

## 许可证注意事项

`CS2-insight-agent` 使用 PolyForm Noncommercial 许可证。如果系统用于收费代剪、商业机器人、付费服务或商业平台集成，需要先取得项目作者的商业授权。个人自用和符合许可证条款的非商业使用可以继续推进。
