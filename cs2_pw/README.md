# CS2 Perfect World API Standalone

这是一个从 CS2UID 插件中独立出来的完美平台 (Perfect World) API 模块。它可以独立运行，无需依赖整个 CS2UID 项目。

## 功能

- 获取用户信息
- 获取比赛列表
- 获取比赛详情
- 获取掉落信息
- 搜索玩家

## 安装

1. 确保已安装 Python 3.8+。
2. 安装依赖：

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 配置

你需要获取你的完美平台 Steam ID (UID) 和 Token。你可以通过抓包完美平台 App 来获取这些信息。

### 2. 运行示例

修改 `main.py` 中的 `uid` 和 `token` 变量，或者设置环境变量 `CS2_UID` 和 `CS2_TOKEN`。

```python
# main.py
uid = "你的UID"
token = "你的Token"
```

运行脚本：

```bash
python main.py
```

### 3. 在你的项目中使用

```python
from request import PerfectWorldApi
import asyncio

async def main():
    api = PerfectWorldApi(uid="你的UID", token="你的Token")
    user_info = await api.get_userinfo("你的UID")
    print(user_info)

if __name__ == "__main__":
    asyncio.run(main())
```

## 文件说明

- `api.py`: 定义 API 端点 URL。
- `models.py`: 定义数据模型 (TypedDict)。
- `request.py`: 核心 API 类 `PerfectWorldApi`。
- `main.py`: 使用示例。
- `requirements.txt`: 依赖列表。
