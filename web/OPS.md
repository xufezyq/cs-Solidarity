# cs-Solidarity Web 控制面板 — 运维手册

## 启动服务

```bash
cd D:\code\cs-Solidarity\web
python -m uvicorn server:app --host 0.0.0.0 --port 11029
```

浏览器访问 `http://localhost:11029`

首次运行会自动生成 admin 账户，密码显示在控制台：
```
⚠️  首次运行，已创建管理员账户
   用户名: admin
   密码:   xxxxxxxxxx
   请登录后立即修改密码！
```

---

## 关闭服务

### 方法一：直接按 `Ctrl+C`（推荐）

在运行 uvicorn 的终端里按 `Ctrl+C`，进程会优雅退出。

### 方法二：按端口号精准杀进程

```bash
# 1. 查找占用 11029 端口的 PID
netstat -ano | findstr :11029 | findstr LISTENING

# 输出类似：TCP    0.0.0.0:11029    0.0.0.0:0    LISTENING    12345
#                                                ^^^^^^^ 这是 PID

# 2. 用 PID 杀进程
taskkill /F /PID 12345
```

### 方法三：杀所有 Python 进程（⚠️ 慎用）

```bash
taskkill /F /IM python.exe
```

**注意**：这会终止**所有** Python 进程，包括 bot 主进程和其他脚本。

---

## 清理 / 重新初始化

删除以下文件，下次启动会重新生成 admin 密码和 JWT 密钥：

```bash
del D:\code\cs-Solidarity\web\users.json
del D:\code\cs-Solidarity\web\.secret_key
```

可选：清理备份目录
```bash
rd /s /q D:\code\cs-Solidarity\web\backups
```

---

## 完整重启流程

```bash
# 1. 关闭旧进程（按端口查 PID）
netstat -ano | findstr :11029 | findstr LISTENING
taskkill /F /PID <PID>

# 2. 启动新进程
cd D:\code\cs-Solidarity\web
python -m uvicorn server:app --host 0.0.0.0 --port 11029

# 3. 浏览器打开 http://localhost:11029
```

---

## 安装依赖

首次使用或换机器时需要安装：

```bash
cd D:\code\cs-Solidarity\web
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

---

## Agent 端启动（内网机器）

```bash
cd D:\code\cs-Solidarity
pip install websockets -i https://mirrors.aliyun.com/pypi/simple/

python -m agent.client --server ws://<公网IP>:11029/ws/agent --token <令牌> --root D:\code\cs-Solidarity
```

Agent 连接令牌在 Web Server 启动时显示在控制台：
```
🔑 Agent 连接令牌: xxxxxxxxxxxxxxxx
```

---

## 普通用户与注册审核

### 用户自助注册

登录页支持提交注册申请。申请会写入 `web/registrations.json`，管理员登录后可在“用户管理”页面审核通过或拒绝。

也可以用 API 创建普通用户（Admin 操作），角色为 `user`：

```bash
curl -X POST http://localhost:11029/api/users \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"test\", \"password\": \"123456\", \"role\": \"user\", \"display_name\": \"测试用户\"}"
```

获取 admin_token：先用 admin 账号登录，F12 打开浏览器开发者工具 → Network → 看 `/api/auth/login` 响应里的 `token` 字段。

### 普通用户登录

浏览器打开 `http://localhost:11029`，用管理员分配的账号密码登录即可。

**普通用户权限：** 可查看仪表盘、实例、Steam、日志，使用聊天和文件管理；不能编辑配置、控制 Bot 或管理用户。普通用户只能删除自己上传的文件，管理员可删除所有文件。

### 注册审核 API

```bash
# 查看待审核注册
curl http://localhost:11029/api/auth/registrations \
  -H "Authorization: Bearer <admin_token>"

# 通过申请
curl -X POST http://localhost:11029/api/auth/registrations/test/approve \
  -H "Authorization: Bearer <admin_token>"

# 拒绝申请
curl -X POST http://localhost:11029/api/auth/registrations/test/reject \
  -H "Authorization: Bearer <admin_token>"
```

### 其他用户管理 API

```bash
# 查看所有用户
curl http://localhost:11029/api/users \
  -H "Authorization: Bearer <admin_token>"

# 修改用户角色
curl -X PUT http://localhost:11029/api/users/test/role \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d "{\"role\": \"admin\"}"

# 重置用户密码
curl -X PUT http://localhost:11029/api/users/test/password \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d "{\"new_password\": \"newpass123\"}"

# 删除用户
curl -X DELETE http://localhost:11029/api/users/test \
  -H "Authorization: Bearer <admin_token>"
```

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `users.json` | 用户数据（admin 密码等），删除后重新生成 |
| `.secret_key` | JWT 密钥，删除后所有 token 失效需重新登录 |
| `registrations.json` | 待审核注册申请 |
| `web_config.json` | Web 端配置，如文件存储模式 |
| `backups/` | 配置文件自动备份，可安全删除 |
| `shared_files/` | Web 存储模式下的上传文件 |
