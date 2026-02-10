# 完美世界平台集成功能使用说明

本目录包含完美世界CSGO平台相关功能的配置文件。

## 功能列表

### 1. 完美平台监控 (pw_monitor)
实时监控好友的比赛状态，当好友开始或结束比赛时自动推送通知到微信。

**功能特性**：
- 实时监控好友比赛状态
- 比赛开始通知（可选）
- 比赛结束通知，包含详细战绩
- 支持同时监控多个好友
- 可自定义检查间隔

### 2. 战绩统计推送 (pw_stats)
定时推送玩家的详细战绩统计报告到微信。

**统计内容**：
- 总体数据（Rating、K/D、胜率、场次等）
- 近期表现（最近N场比赛）
- 常用地图统计
- 常用武器统计
- 残局能力数据

## 快速开始

### 第一步：获取登录凭证

完美世界平台需要手机号和验证码登录。首次使用时需要：

1. 准备好你的手机号
2. 在配置文件中填写手机号
3. 获取短信验证码并填写到配置文件
4. 程序首次运行时会自动登录并保存token
5. 后续使用会自动加载保存的token，无需重复登录

### 第二步：配置监控实例

#### 监控好友比赛状态

复制 `pw_monitor_example.json` 为 `pw_monitor_your_name.json`：

```json
{
  "mobile_phone": "13800138000",
  "security_code": "123456",
  "token_file": "config/perfectworld/token.json",
  "wechat_groups": ["文件传输助手"],
  "monitored_friends": [
    {
      "steam_id": "76561198929215155",
      "nickname": "好友昵称"
    }
  ],
  "check_interval": 60,
  "enable_match_start_notify": true,
  "enable_match_end_notify": true,
  "startup_message": "完美平台监控已启动！"
}
```

**配置说明**：
- `mobile_phone`: 手机号（首次使用必填）
- `security_code`: 短信验证码（首次使用必填）
- `token_file`: token保存路径（默认即可）
- `wechat_groups`: 接收通知的微信群/好友列表
- `monitored_friends`: 监控的好友列表
  - `steam_id`: 好友的Steam ID（完美平台）
  - `nickname`: 自定义昵称
- `check_interval`: 检查间隔（秒），建议60秒以上
- `enable_match_start_notify`: 是否启用比赛开始通知
- `enable_match_end_notify`: 是否启用比赛结束通知
- `startup_message`: 启动时发送的消息

#### 定时推送战绩统计

复制 `pw_stats_example.json` 为 `pw_stats_your_name.json`：

```json
{
  "mobile_phone": "13800138000",
  "security_code": "123456",
  "token_file": "config/perfectworld/token.json",
  "wechat_groups": ["文件传输助手"],
  "target_players": [
    {
      "steam_id": "76561198929215155",
      "nickname": "玩家昵称"
    }
  ],
  "send_times": ["08:00", "20:00"],
  "include_recent_matches": 5,
  "include_hot_maps": true,
  "include_hot_weapons": true
}
```

**配置说明**：
- `mobile_phone`: 手机号（首次使用必填）
- `security_code`: 短信验证码（首次使用必填）
- `token_file`: token保存路径（默认即可）
- `wechat_groups`: 接收报告的微信群/好友列表
- `target_players`: 目标玩家列表
  - `steam_id`: 玩家的Steam ID
  - `nickname`: 自定义昵称
- `send_times`: 发送时间（24小时制），可设置多个
- `include_recent_matches`: 包含最近N场比赛（0表示不包含）
- `include_hot_maps`: 是否包含常用地图统计
- `include_hot_weapons`: 是否包含常用武器统计

### 第三步：添加到主配置

编辑项目根目录的 `config.json`，添加新的实例：

```json
{
  "instances": [
    {
      "type": "pw_monitor",
      "config": "config/perfectworld/pw_monitor_your_name.json"
    },
    {
      "type": "pw_stats",
      "config": "config/perfectworld/pw_stats_your_name.json"
    }
  ]
}
```

### 第四步：运行程序

```bash
python main.py
```

## 常见问题

### Q: 如何获取Steam ID？
A: 完美世界平台使用的是完美平台的Steam ID，可以通过以下方式获取：
1. 登录完美世界竞技平台
2. 查看个人主页URL，其中包含Steam ID
3. 或使用完美平台的搜索功能搜索玩家昵称

### Q: 首次登录需要验证码，如何获取？
A:
1. 在配置文件中填写手机号
2. 通过完美世界竞技平台APP或网站发送验证码
3. 将收到的验证码填写到配置文件的 `security_code` 字段
4. 运行程序，程序会自动登录并保存token

### Q: Token多久会过期？
A: Token的有效期由完美世界服务器控制。如果token过期，程序会提示需要重新登录。此时删除 `token.json` 文件，并在配置文件中重新填写验证码即可。

### Q: 如何修改监控的好友？
A: 直接编辑配置文件中的 `monitored_friends` 数组，添加或删除好友信息，然后重启程序。

### Q: 监控会影响API调用频率吗？
A: 每次检查会为每个监控的好友调用一次API，建议：
- 检查间隔不要小于60秒
- 监控的好友数量不要过多（建议10人以内）
- 避免在多个设备同时运行相同配置

### Q: 如何测试配置是否正确？
A: 可以先配置一个实例监控自己的Steam ID，打一场比赛测试是否能收到通知。

## 注意事项

1. **隐私安全**
   - `token.json` 文件包含敏感信息，请勿分享
   - 配置文件中的手机号和验证码仅在首次登录时使用
   - 已在 `.gitignore` 中排除敏感文件，但请自行检查

2. **API限制**
   - 完美世界API为非官方接口，可能随时变化
   - 避免频繁调用API，建议检查间隔60秒以上
   - 如遇API错误，请检查token是否有效

3. **使用建议**
   - 首次使用建议先测试一个实例
   - 合理设置检查间隔和推送时间
   - 定期检查程序日志，确保运行正常

## 文件说明

- `pw_monitor_example.json` - 监控实例配置示例
- `pw_stats_example.json` - 统计实例配置示例
- `token.json` - 自动生成的token文件（不要手动编辑）
- `README.md` - 本说明文档

## 更新日志

### v1.0.0 (2025-02-10)
- 初始版本
- 支持完美平台好友比赛监控
- 支持定时战绩统计推送

## 技术支持

如有问题或建议，请参考项目根目录的 README.md 或提交Issue。
