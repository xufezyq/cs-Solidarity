# CS2 平台数据存储格式文档

## 存储位置总览

| 数据 | 文件路径 | 持久化 |
|------|----------|--------|
| 好友列表 + 三个平台历史极值 + 排行榜 | `instconfig/steam_data.json` | 是 |
| 时间轴事件（对局记录、极值变化、游戏开始/结束） | `instconfig/steam_timeline.json` | 是 |
| 每日统计（daily_stats） | 仅内存 | 否，23:55 发送后清空 |
| 赛季归档 | `instconfig/steam_data_archives/season_YYYYMMDD_HHMMSS.json` | 手动归档时 |

---

## 一、steam_data.json

### 1.1 顶层结构

```
{
  "monitored_friends": [...],           // 监控好友列表
  "friend_pw_history_stats": {...},     // 完美平台历史极值
  "friend_5e_history_stats": {...},     // 5E 平台历史极值
  "friend_official_history_stats": {...}, // 官匹历史极值
  "friend_pw_leaderboard": {...},       // 完美排行榜持有者
  "cached_news_gids": {...},            // CS2 新闻缓存
  "last_update": 1780773138.76          // 最后更新时间戳
}
```

### 1.2 monitored_friends（好友列表）

每个好友条目包含 Steam 基础信息 + 各平台扩展字段：

```json
{
  "steamid": "76561199009839689",
  "personaname": "难念的经",           // Steam 昵称
  "pw_nickname": "皮张侠",             // 完美平台昵称（自动获取）
  "personastate": 1,                   // 在线状态: 0=离线, 1=在线
  "gameextrainfo": "Counter-Strike 2", // 当前游戏
  "lastlogoff": 1780416705,            // 最后离线时间戳

  // 以下为 5E 平台独有字段（由 save_5e_profiles 写入）
  "fivee_nickname": "pizhangxia",
  "fivee_domain": "pizhangxia",
  "fivee_uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "fivee_avatar": "https://avatar.5eplay.com/xxx.jpg"
}
```

> 完美和官匹不往好友条目写额外字段，昵称通过 history_stats 中的 `pw_nickname` / `official_nickname` 维护。

### 1.3 friend_pw_history_stats（完美历史极值）

以 steamid 为 key，记录每个好友的历史最佳/最差战绩：

```json
{
  "76561199009839689": {
    "pw_nickname": "皮张侠",
    "avatar": "https://avatars.steamstatic.com/xxxx_full.jpg",
    "last_match_id": "PVP@2026061312345",   // 最近一场对局 ID（用于去重）

    "max_kills": 35,     "min_kills": 8,
    "max_deaths": 22,    "min_deaths": 5,
    "max_rating": 1.52,  "min_rating": 0.65,  // Rating
    "max_pw_rating": 1.48, "min_pw_rating": 0.62, // pwRT
    "max_we": 92,        "min_we": 35,        // WE
    "max_score": 2500,   "min_score": 1800    // 完美分数
  }
}
```

### 1.4 friend_5e_history_stats（5E 历史极值）

```json
{
  "76561199009839689": {
    "fivee_nickname": "pizhangxia",
    "avatar": "https://avatar.5eplay.com/xxx.jpg",
    "last_match_id": "5e-match-20260613-001",

    "max_kills": 32,     "min_kills": 6,
    "max_deaths": 20,    "min_deaths": 4,
    "max_rating": 1.45,  "min_rating": 0.70,  // Rating
    "max_rws": 16.50,    "min_rws": 5.20,     // RWS
    "max_adr": 105.3,    "min_adr": 52.1,     // ADR
    "max_elo": 2180,     "min_elo": 1950       // ELO
  }
}
```

### 1.5 friend_official_history_stats（官匹历史极值）

结构与完美相同，昵称 key 不同：

```json
{
  "76561199009839689": {
    "official_nickname": "皮张侠",
    "avatar": "https://avatars.steamstatic.com/xxxx_full.jpg",
    "last_match_id": "PVP@2026061312400",

    "max_kills": 30,     "min_kills": 7,
    "max_deaths": 19,    "min_deaths": 4,
    "max_rating": 1.38,  "min_rating": 0.68,
    "max_pw_rating": 1.32, "min_pw_rating": 0.65,
    "max_we": 88,        "min_we": 38,
    "max_score": 1850,   "min_score": 1600
  }
}
```

### 1.6 friend_pw_leaderboard（排行榜持有者）

仅完美平台有排行榜，记录各类别的当前最佳持有者：

```json
{
  "max_kills": {
    "steamid": "76561199009839689",
    "pw_nickname": "皮张侠",
    "value": 35
  },
  "max_rating": {
    "steamid": "76561199009839689",
    "pw_nickname": "皮张侠",
    "value": 1.52
  }
}
```

排行榜类别：max_kills, min_kills, max_deaths, min_deaths, max_rating, min_rating, max_pw_rating, min_pw_rating, max_we, min_we, max_score, min_score

### 1.7 三个平台 history_stats 字段对比

| 字段 | 完美 | 5E | 官匹 | 说明 |
|------|------|-----|------|------|
| 昵称 key | `pw_nickname` | `fivee_nickname` | `official_nickname` | - |
| `last_match_id` | 有 | 有 | 有 | 去重用 |
| `max/min_kills` | 有 | 有 | 有 | - |
| `max/min_deaths` | 有 | 有 | 有 | - |
| `max/min_rating` | 有 | 有 | 有 | - |
| `max/min_pw_rating` | 有 | 无 | 有 | pwRT，完美/官匹独有 |
| `max/min_we` | 有 | 无 | 有 | WE，完美/官匹独有 |
| `max/min_score` | 有 | 无 | 有 | 完美分数，完美/官匹独有 |
| `max/min_rws` | 无 | 有 | 无 | RWS，5E 独有 |
| `max/min_adr` | 无 | 有 | 无 | ADR，5E 独有 |
| `max/min_elo` | 无 | 有 | 无 | ELO，5E 独有 |

---

## 二、steam_timeline.json

### 2.1 顶层结构

```
{
  "extreme_changes": [...],  // 历史极值变化事件
  "play_records": [...]      // 游戏事件（开始/结束/对局）
}
```

### 2.2 extreme_changes（极值变化）

当排行榜记录被刷新时生成：

```json
{
  "id": "ec0001",
  "steamid": "76561199009839689",
  "pw_nickname": "皮张侠",
  "metric": "max_kills",
  "metric_label": "击杀王",
  "metric_emoji": "🔫",
  "old_value": 32,
  "new_value": 35,
  "delta": 3,
  "is_improvement": true,
  "previous_holder": null,            // null=首次诞生, 字符串=易主
  "timestamp": "2026-06-13 14:32:18",
  "timestamp_iso": "2026-06-13T14:32:18"
}
```

### 2.3 play_records（游戏事件）

三种 kind：`start`（开始游戏）、`end`（结束游戏）、`match`（对局）

#### start / end

```json
{
  "id": "a1b2c3d4001",
  "kind": "start",
  "steamid": "76561199009839689",
  "pw_nickname": "皮张侠",
  "game_name": "CS2",
  "group_id": "g-cs2-start-1",
  "timestamp": "2026-06-13 14:00:00",
  "timestamp_iso": "2026-06-13T14:00:00"
}
```

#### match（对局记录）

通过 `platform` 和 `platform_label` 区分平台来源：

```json
{
  "id": "a1b2c3d4003",
  "kind": "match",
  "match_id": "PVP@2026061312345",
  "platform": "pw",              // pw / 5e / official
  "platform_label": "完美",       // 完美 / 5E / 官匹
  "map_name": "殒命大厦",
  "score": "13:8",
  "timestamp": "2026-06-13 14:32:18",
  "timestamp_iso": "2026-06-13T14:32:18",
  "players": [
    {
      "steamid": "76561199009839689",
      "pw_nickname": "皮张侠",
      "platform": "pw",
      "platform_label": "完美",
      "kda": "28/12/5",
      "rating": 1.35,
      "result": "胜利",
      "we": 85,
      "pvp_score_change": 25,
      "pvp_stars_change": 1
    }
  ]
}
```

---

## 三、每日统计（内存，不持久化）

每天 23:55 生成日报后清空。以下为内存中的结构：

### 3.1 friend_pw_daily_stats

```json
{
  "76561199009839689": {
    "pw_nickname": "皮张侠",
    "matches": ["PVP@xxx1", "PVP@xxx2"],
    "wins": 4,
    "losses": 1,
    "draws": 0,
    "total_score_change": 65,
    "total_stars_change": 3,
    "total_kills": 95,
    "total_deaths": 52,
    "total_assists": 28,
    "total_rating": 6.25,
    "total_pw_rating": 6.05,
    "total_we": 380,
    "match_count": 5
  }
}
```

### 3.2 friend_5e_daily_stats

```json
{
  "76561199009839689": {
    "fivee_nickname": "pizhangxia",
    "matches": ["5e-match-001", "5e-match-002"],
    "wins": 3,
    "losses": 1,
    "draws": 0,
    "total_elo_change": 45.0,
    "total_kills": 88,
    "total_deaths": 60,
    "total_assists": 25,
    "total_rating": 5.12,
    "total_rws": 54.0,
    "total_adr": 369.2,
    "match_count": 4
  }
}
```

### 3.3 friend_official_daily_stats

```json
{
  "76561199009839689": {
    "official_nickname": "皮张侠",
    "matches": ["PVP@yyy1", "PVP@yyy2"],
    "wins": 1,
    "losses": 2,
    "draws": 0,
    "total_kills": 65,
    "total_deaths": 51,
    "total_assists": 16,
    "total_rating": 3.15,
    "total_pw_rating": 3.24,
    "total_we": 174,
    "match_count": 3
  }
}
```

> 注意：官匹和完美没有 `total_score_change` / `total_stars_change` / `total_elo_change` 等字段。
