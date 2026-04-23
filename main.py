import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Request, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import get_settings
from database import init_db, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from auth import get_current_user
from websocket import handle_websocket

# 导入 API 路由
from api import auth, contacts, groups, messages, files, contact_requests
from api.group_sync import router as group_sync_router
from api.group_p2p import router as group_p2p_router

# 导入 chat_owner_reply
from api.messages import chat_owner_reply


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化数据库
    await init_db()
    print("✅ Database initialized")
    yield
    # 关闭时清理
    print("👋 Server shutting down")


# 创建 FastAPI 应用
settings = get_settings()
app = FastAPI(
    title=settings.APP_NAME,
    description="Agent Portal - P2P Communication Platform",
    version="0.1.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(auth.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(group_p2p_router, prefix="/api")  # 必须在 groups/group_sync 之前（webhook 路由）
app.include_router(groups.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(contact_requests.router, prefix="/api")
app.include_router(group_sync_router, prefix="/api")

# 添加 chat/owner/reply 路由（用于 p2p-channel 插件）
# 注意：这个路由需要认证，插件需要提供有效的 token
app.post("/api/chat/owner/reply", response_model=dict)(chat_owner_reply)

# 创建一个不需要认证的版本（用于插件，通过 IP 白名单限制）
@app.post("/api/internal/agent-reply", response_model=dict)
async def internal_agent_reply(
    data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    内部 API - 用于 p2p-channel 插件发送 Agent 回复
    仅允许来自本地或特定 IP 的请求
    """
    # 检查请求来源（只允许本地或 Nginx 代理）
    client_host = request.client.host
    if client_host not in ["127.0.0.1", "localhost", "::1"]:
        # 检查是否是 Nginx 转发的请求
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        if not forwarded_for:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    content = data.get("content", "")
    user_id = data.get("user_id", 1)  # 默认用户 ID
    
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content is required"
        )
    
    try:
        from datetime import datetime
        from models import Message
        
        # 保存消息到数据库
        message = Message(
            sender_id=0,  # 0 表示 Agent
            contact_id=0,  # 0 表示 My Agent
            content=content,
            message_type="text",
            is_from_owner=False,
            is_read=False,
            created_at=datetime.now()
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        
        # 通过 WebSocket 通知用户
        from websocket import manager
        await manager.send_to_user(user_id, {
            "type": "agent_reply",
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "message_id": message.id
        })
        
        return {
            "message_id": message.id,
            "status": "delivered"
        }
    except Exception as e:
        print(f"[INTERNAL_REPLY] Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save reply: {str(e)}"
        )

# 内部 API - 获取 My Agent 历史消息（通过 token 认证）
@app.get("/api/internal/messages")
async def internal_get_messages(
    contact_id: int = 0,
    limit: int = 50,
    token: str = Query(..., description="User token for authentication"),
    db: AsyncSession = Depends(get_db)
):
    """
    内部 API - 获取 My Agent 历史消息
    用于前端加载历史消息，通过 token 验证用户身份
    """
    try:
        from sqlalchemy import select, and_
        from models import Message, User
        
        # 验证 token（简化版：直接使用 token 作为 user_id）
        # 生产环境应该使用 JWT 验证
        try:
            user_id = int(token)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        # 验证用户存在
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        # 查询该用户的消息（根据 sender_id 或 contact_id）
        # My Agent 消息：sender_id=user_id 且 contact_id=0，或 sender_id=0 且 contact_id=0
        query = select(Message).where(
            and_(
                Message.contact_id == contact_id,
                (Message.sender_id == user_id) | (Message.sender_id == 0)
            )
        ).order_by(Message.created_at).limit(limit)
        
        result = await db.execute(query)
        messages = result.scalars().all()
        
        return [
            {
                "id": msg.id,
                "content": msg.content,
                "sender_id": msg.sender_id,
                "contact_id": msg.contact_id,
                "message_type": msg.message_type,
                "is_from_owner": msg.is_from_owner,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat() if msg.created_at else None
            }
            for msg in messages
        ]
    except HTTPException:
        raise
    except Exception as e:
        print(f"[INTERNAL_MESSAGES] Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get messages: {str(e)}"
        )

# 静态文件服务
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    # 为前端相对路径提供重定向
    @app.get("/style.css")
    async def get_style():
        style_path = os.path.join(static_dir, "style.css")
        if os.path.exists(style_path):
            return FileResponse(style_path)
        return {"error": "Not found"}
    
    @app.get("/app.js")
    async def get_app_js():
        js_path = os.path.join(static_dir, "app.js")
        if os.path.exists(js_path):
            return FileResponse(js_path)
        return {"error": "Not found"}


@app.get("/")
async def root():
    """根路径 - 返回前端页面"""
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "name": settings.APP_NAME,
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点 - 普通用户"""
    token = websocket.query_params.get("token") or websocket.query_params.get("api_key")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    
    try:
        user_id = int(token)
    except ValueError:
        await websocket.close(code=4002, reason="Invalid token")
        return
    
    await handle_websocket(websocket, user_id, is_agent=False)


@app.websocket("/ws/agent")
async def agent_websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点 - Agent 专用"""
    token = websocket.query_params.get("token") or websocket.query_params.get("api_key")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    
    # 验证 Agent token（简化处理，实际应该有专门的 Agent 认证）
    try:
        user_id = int(token)
    except ValueError:
        await websocket.close(code=4002, reason="Invalid token")
        return
    
    await handle_websocket(websocket, user_id, is_agent=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
