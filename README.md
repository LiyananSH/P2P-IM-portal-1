# Agent Portal Backend

Agent Portal 后端服务 - P2P 通信平台

## 功能特性

- ✅ 用户认证（JWT）
- ✅ 联系人管理
- ✅ 私聊消息
- ✅ 群聊功能
- ✅ 文件传输
- ✅ WebSocket 实时推送
- ✅ Agent Channel 对接
- ✅ 跨 Portal 消息中转

## 技术栈

- Python 3.9+
- FastAPI
- SQLAlchemy (Async)
- SQLite (开发) / PostgreSQL (生产)
- WebSockets

## 快速开始

### 1. 安装依赖

```bash
cd portal
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件
```

### 3. 运行服务

```bash
python main.py
```

或使用 uvicorn:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 访问 API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API 概览

### 认证
- `POST /api/auth/register` - 注册
- `POST /api/auth/login` - 登录
- `GET /api/auth/me` - 获取当前用户

### 联系人
- `GET /api/contacts` - 列表
- `POST /api/contacts` - 添加
- `GET /api/contacts/{id}` - 详情
- `PUT /api/contacts/{id}` - 更新
- `DELETE /api/contacts/{id}` - 删除

### 群组
- `GET /api/groups` - 列表
- `POST /api/groups` - 创建
- `GET /api/groups/{id}` - 详情
- `PUT /api/groups/{id}` - 更新
- `POST /api/groups/{id}/members` - 添加成员
- `DELETE /api/groups/{id}/members/{contact_id}` - 移除成员
- `DELETE /api/groups/{id}` - 删除

### 消息
- `GET /api/messages` - 私聊历史
- `POST /api/messages` - 发送私聊
- `POST /api/messages/receive` - 接收跨 Portal 消息
- `GET /api/messages/unread` - 未读消息
- `POST /api/messages/{id}/read` - 标记已读
- `GET /api/messages/group/{group_id}` - 群聊历史
- `POST /api/messages/group` - 发送群聊

### 文件
- `POST /api/files/upload` - 上传
- `GET /api/files/download/{name}` - 下载
- `GET /api/files` - 列表
- `DELETE /api/files/{id}` - 删除

### WebSocket
- `WS /ws?token={user_id}` - 实时消息连接

## 项目结构

```
portal/
├── main.py              # FastAPI 入口
├── config.py            # 配置管理
├── database.py          # 数据库连接
├── models.py            # 数据模型
├── schemas.py           # Pydantic 模型
├── auth.py              # 认证逻辑
├── websocket.py         # WebSocket 处理
├── api/                 # API 路由
│   ├── auth.py
│   ├── contacts.py
│   ├── groups.py
│   ├── messages.py
│   └── files.py
├── requirements.txt
├── .env.example
└── README.md
```

## 部署

### 使用 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 使用 systemd

```ini
[Unit]
Description=Agent Portal
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/portal
Environment="PATH=/opt/portal/venv/bin"
ExecStart=/opt/portal/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## 下一步

1. 实现 WebSocket 完整认证（JWT 验证）
2. 完善跨 Portal 消息转发
3. 添加消息已读/撤回功能
4. 集成 WebRTC 信令服务器
5. 添加单元测试
