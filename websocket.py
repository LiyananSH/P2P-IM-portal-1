import json
from typing import Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from models import User, Message, GroupMessage
from database import AsyncSessionLocal

# 存储活跃连接
# user_id -> WebSocket
active_connections: Dict[int, WebSocket] = {}


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        """建立连接"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"User {user_id} connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, user_id: int):
        """断开连接"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"User {user_id} disconnected. Total: {len(self.active_connections)}")
    
    async def send_to_user(self, user_id: int, message: dict):
        """发送消息给指定用户"""
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            await websocket.send_json(message)
    
    async def broadcast(self, message: dict, exclude: int = None):
        """广播消息给所有连接（可选排除某个用户）"""
        for user_id, websocket in self.active_connections.items():
            if user_id != exclude:
                await websocket.send_json(message)


manager = ConnectionManager()


async def handle_websocket(websocket: WebSocket, user_id: int):
    """处理 WebSocket 连接"""
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
                await process_message(websocket, user_id, message_data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "Invalid JSON"}
                })
    
    except WebSocketDisconnect:
        manager.disconnect(user_id)


async def process_message(websocket: WebSocket, user_id: int, data: dict):
    """处理收到的 WebSocket 消息"""
    msg_type = data.get("type")
    
    if msg_type == "ping":
        # 心跳响应
        await websocket.send_json({"type": "pong", "data": {}})
    
    elif msg_type == "message":
        # 私聊消息（通过 WebSocket 发送）
        await handle_private_message(websocket, user_id, data.get("data", {}))
    
    elif msg_type == "group_message":
        # 群聊消息
        await handle_group_message(websocket, user_id, data.get("data", {}))
    
    elif msg_type == "typing":
        # 正在输入状态
        await handle_typing_status(user_id, data.get("data", {}))
    
    else:
        await websocket.send_json({
            "type": "error",
            "data": {"message": f"Unknown message type: {msg_type}"}
        })


async def handle_private_message(websocket: WebSocket, user_id: int, data: dict):
    """处理私聊消息"""
    # 这里只是 WebSocket 层面的处理
    # 实际的消息存储和转发在 HTTP API 中处理
    
    await websocket.send_json({
        "type": "ack",
        "data": {
            "message": "Message received, use HTTP API to send"
        }
    })


async def handle_group_message(websocket: WebSocket, user_id: int, data: dict):
    """处理群聊消息"""
    await websocket.send_json({
        "type": "ack",
        "data": {
            "message": "Group message received, use HTTP API to send"
        }
    })


async def handle_typing_status(user_id: int, data: dict):
    """处理正在输入状态"""
    contact_id = data.get("contact_id")
    group_id = data.get("group_id")
    is_typing = data.get("is_typing", False)
    
    # 可以转发给对应的联系人或群成员
    # 这里简化处理
    pass


async def notify_new_message(user_id: int, message: dict):
    """通知用户有新消息"""
    await manager.send_to_user(user_id, {
        "type": "new_message",
        "data": message
    })


async def notify_new_group_message(group_id: int, message: dict, exclude_user_id: int = None):
    """通知群成员有新消息"""
    # 这里简化处理，实际应该查询群成员并逐个通知
    await manager.broadcast({
        "type": "new_group_message",
        "data": {
            "group_id": group_id,
            "message": message
        }
    }, exclude=exclude_user_id)
