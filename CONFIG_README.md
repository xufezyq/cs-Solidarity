# 配置说明

## 配置文件格式

配置文件使用 JSON 格式，位置：`config.json`

## 配置项详解

### 基础配置
- **steam_api_key**: Steam API 密钥
- **steam_id**: 你的 Steam ID
- **wechat_groups**: 接收通知的微信群名称或个人账号（支持数组，可配置多个）
- **check_interval**: 检查好友状态的间隔时间（秒），默认 60 秒

### 好友监听配置

#### 方案 1: 监听所有好友（推荐用于单实例）
```json
{
  "enable_all_friends": true,
  "monitored_friends": [],
  "wechat_groups": ["【CS】团结友爱"]
}
```

#### 方案 2: 监听指定好友（推荐用于多实例）
```json
{
  "enable_all_friends": false,
  "monitored_friends": [
    {
      "steamid": "76561198000000001",
      "nickname": "好友名字1"
    },
    {
      "steamid": "76561198000000002",
      "nickname": "好友名字2"
    }
  ],
  "wechat_groups": ["【CS】团结友爱"]
}
```

#### 方案 3: 发送到多个群聊
```json
{
  "enable_all_friends": true,
  "monitored_friends": [],
  "wechat_groups": [
    "【CS】团结友爱",
    "游戏通知组",
    "个人账号"
  ]
}
```

## 多实例运行方案

创建多个配置文件，针对不同的好友分组：

### 示例配置结构
```
├── config.json           # 默认配置
├── config_group1.json    # 分组1 - 监听特定好友
├── config_group2.json    # 分组2 - 监听其他好友
└── main.py
```

### 多实例运行命令
```bash
# 运行默认配置
python main.py

# 运行特定配置（需修改 main.py 中的 config_file 变量）
# 或使用命令行参数（如果需要可添加该功能）
```

### 改进建议 - 使用命令行参数

如果希望无需修改代码即可指定配置文件，可以修改 `main.py`：

```python
import sys

if __name__ == "__main__":
    # 从命令行参数获取配置文件，默认为 config.json
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    ...
```

然后运行：
```bash
python main.py config_group1.json
python main.py config_group2.json
```

## 完整配置示例

```json
{
  "steam_api_key": "4C858E561994F8B512A4402905DB607C",
  "steam_id": "76561198383859685",
  "wechat_groups": [
    "【CS】团结友爱",
    "游戏通知组"
  ],
  "check_interval": 60,
  "enable_all_friends": false,
  "monitored_friends": [
    {
      "steamid": "76561198000000001",
      "nickname": "PlayerOne"
    },
    {
      "steamid": "76561198000000002",
      "nickname": "PlayerTwo"
    },
    {
      "steamid": "76561198000000003",
      "nickname": "PlayerThree"
    }
  ]
}
```

## 使用步骤

1. **编辑 config.json**：
   - 填写 Steam API Key 和 Steam ID
   - 设置目标微信群名称
   - 选择监听方案（全部或指定好友）

2. **单实例运行**：
   ```bash
   python main.py
   ```

3. **多实例运行**：
   - 创建多个配置文件（config_1.json, config_2.json 等）
   - 为每个配置指定不同的好友列表
   - 分别启动多个程序实例，指定不同的配置文件

## 常见问题

### Q: 如何获取好友的 Steam ID？
A: 在 Steam 社区查看好友资料，URL 中的数字就是 Steam ID，或使用在线工具转换好友 URL。

### Q: 需要填写好友的 nickname 字段吗？
A: 不需要，该字段仅用于标识，可留空或填写便于识别的名字。

### Q: 多个实例会互相干扰吗？
A: 不会。每个实例独立运行，维护自己的状态，可同时监听不同的好友分组。

