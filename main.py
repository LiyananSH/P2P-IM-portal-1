from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer

from config import get_settings
from database import init_db
from auth import get_current_user
from websocket import handle_websocket

# 导入 API 路由
from api import auth, contacts, groups, messages, files, contact_requests


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
app.include_router(groups.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(contact_requests.router, prefix="/api")


@app.get("/")
async def root():
    """根路径"""
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
    """WebSocket 连接端点"""
    # 这里简化处理，实际应该验证 JWT
    # 可以通过 query param 传递 token: /ws?token=xxx
    
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return
    
    # TODO: 验证 token 获取 user_id
    # 简化处理，假设 token 就是 user_id（实际应该用 JWT 验证）
    try:
        user_id = int(token)
    except ValueError:
        await websocket.close(code=4002, reason="Invalid token")
        return
    
    await handle_websocket(websocket, user_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
