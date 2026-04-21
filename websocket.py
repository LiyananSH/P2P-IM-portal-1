import json
from typing import Dict, List, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from models import User, Message, GroupMessage, Contact
from database import AsyncSessionLocal

# 存储活跃连接
# user_id -> WebSocket (普通用户)
user_connections: Dict[int, WebSocket] = {}
# agent_user_id -> WebSocket (Agent 连接)
agent_connections: Dict[int, WebSocket] = {}


class ConnectionManager:
    """WebSocket 连接管理器 - 支持用户和 Agent"""
    
    def __init__(self):
        self.user_connections: Dict[int, WebSocket] = {}
        self.agent_connections: Dict[int, WebSocket] = {}
    
    async def connect_user(self, websocket: WebSocket, user_id: int):
        """用户建立连接"""
        await websocket.accept()
        self.user_connections[user_id] = websocket
        print(f"[WS] User {user_id} connected. Users: {len(self.user_connections)}, Agents: {len(self.agent_connections)}")
    
    async def connect_agent(self, websocket: WebSocket, user_id: int):
        """Agent 建立连接"""
        await websocket.accept()
        self.agent_connections[user_id] = websocket
        print(f"[WS] Agent {user_id} connected. Users: {len(self.user_connections)}, Agents: {len(self.agent_connections)}")
    
    def disconnect(self, user_id: int, is_agent: bool = False):
        """断开连接"""
        if is_agent and user_id in self.agent_connections:
            del self.agent_connections[user_id]
            print(f"[WS] Agent {user_id} disconnected")
        elif not is_agent and user_id in self.user_connections:
            del self.user_connections[user_id]
            print(f"[WS] User {user_id} disconnected")
    
    async def send_to_user(self, user_id: int, message: dict):
        """发送消息给指定用户"""
        if user_id in self.user_connections:
            websocket = self.user_connections[user_id]
            await websocket.send_json(message)
    
    async def send_to_agent(self, user_id: int, message: dict):
        """发送消息给指定 Agent"""
        if user_id in self.agent_connections:
            websocket = self.agent_connections[user_id]
            await websocket.send_json(message)
    
    def is_agent_online(self, user_id: int) -> bool:
        """检查 Agent 是否在线"""
        return user_id in self.agent_connections
    
    def is_user_online(self, user_id: int) -> bool:
        """检查用户是否在线"""
        return user_id in self.user_connections


manager = ConnectionManager()


async def handle_websocket(websocket: WebSocket, user_id: int, is_agent: bool = False):
    """
    处理 WebSocket 连接
    is_agent: 是否为 Agent 连接
    """
    if is_agent:
        await manager.connect_agent(websocket, user_id)
    else:
        await manager.connect_user(websocket, user_id)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
                await process_message(websocket, user_id, message_data, is_agent)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "Invalid JSON"}
                })
    
    except WebSocketDisconnect:
        manager.disconnect(user_id, is_agent)


async def process_message(websocket: WebSocket, user_id: int, data: dict, is_agent: bool = False):
    """处理收到的 WebSocket 消息"""
    msg_type = data.get("type")
    
    if msg_type == "ping":
        # 心跳响应
        await websocket.send_json({"type": "pong", "data": {}})
    
    elif msg_type == "message":
        # 私聊消息
        if is_agent:
            # Agent 发送的消息
            await handle_agent_message(websocket, user_id, data.get("data", {}))
        else:
            # 普通用户发送的消息
            await handle_user_message(websocket, user_id, data.get("data", {}))
    
    elif msg_type == "typing":
        # 正在输入状态
        await handle_typing_status(user_id, data.get("data", {}))
    
    elif msg_type == "agent_response":
        # Agent 回复消息（仅 Agent 可发送）
        if is_agent:
            await handle_agent_response(user_id, data.get("data", {}))
        else:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Only agent can send agent_response"}
            })
    
    else:
        await websocket.send_json({
            "type": "error",
            "data": {"message": f"Unknown message type: {msg_type}"}
        })


async def handle_user_message(websocket: WebSocket, user_id: int, data: dict):
    """处理用户发送的消息 - 检查是否需要转发给 Agent"""
    content = data.get("content", "")
    contact_id = data.get("contact_id")
    
    # 检查是否是发给 Agent 的消息（通过 @agent 或特定标识）
    is_agent_message = content.startswith("@agent") or content.startswith("/agent")
    
    if is_agent_message:
        # 转发给 Agent
        await forward_to_agent(user_id, contact_id, content)
        await websocket.send_json({
            "type": "ack",
            "data": {"message": "Message forwarded to agent"}
        })
    else:
        await websocket.send_json({
            "type": "ack",
            "data": {"message": "Message received"}
        })


async def handle_agent_message(websocket: WebSocket, user_id: int, data: dict):
    """处理 Agent 发送的消息"""
    await websocket.send_json({
        "type": "ack",
        "data": {"message": "Agent message received"}
    })


async def handle_agent_response(agent_user_id: int, data: dict):
    """
    处理 Agent 的回复
    将 Agent 的回复转发给目标用户
    """
    target_user_id = data.get("target_user_id")
    target_contact_id = data.get("target_contact_id")
    content = data.get("content", "")
    
    # 保存消息到数据库
    async with AsyncSessionLocal() as db:
        # 查找目标用户
        result = await db.execute(select(User).where(User.id == target_user_id))
        target_user = result.scalar_one_or_none()
        
        if target_user:
            # 查找或创建联系人（Agent 作为联系人）
            result = await db.execute(
                select(Contact).where(
                    and_(
                        Contact.owner_id == target_user_id,
                        Contact.portal_url == f"agent://{agent_user_id}"
                    )
                )
            )
            contact = result.scalar_one_or_none()
            
            if not contact:
                # 创建 Agent 联系人
                contact = Contact(
                    owner_id=target_user_id,
                    display_name="Agent",
                    portal_url=f"agent://{agent_user_id}",
                    is_active=True
                )
                db.add(contact)
                await db.flush()
            
            # 创建消息
            message = Message(
                sender_id=agent_user_id,
                contact_id=contact.id,
                content=content,
                message_type="text",
                is_from_owner=False
            )
            db.add(message)
            await db.flush()
            
            # 推送给用户
            await notify_new_message(target_user_id, {
                "id": message.id,
                "contact_id": contact.id,
                "content": content,
                "message_type": "text",
                "is_from_owner": False,
                "created_at": message.created_at.isoformat()
            })


async def forward_to_agent(user_id: int, contact_id: int, content: str):
    """
    将用户消息转发给 Agent
    """
    # 查找用户的 Agent（默认第一个在线 Agent 或特定配置）
    # 这里简化处理，假设 user_id=1 是 Agent
    agent_user_id = 1
    
    if manager.is_agent_online(agent_user_id):
        # Agent 在线，实时推送
        await manager.send_to_agent(agent_user_id, {
            "type": "user_message",
            "data": {
                "from_user_id": user_id,
                "contact_id": contact_id,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
    else:
        # Agent 离线，保存到队列（可扩展）
        print(f"[WS] Agent {agent_user_id} offline, message queued")


async def handle_typing_status(user_id: int, data: dict):
    """处理正在输入状态"""
    pass


async def notify_new_message(user_id: int, message: dict):
    """通知用户有新消息"""
    await manager.send_to_user(user_id, {
        "type": "new_message",
        "data": message
    })


async def notify_agent_message(agent_user_id: int, message: dict):
    """通知 Agent 有新消息"""
    await manager.send_to_agent(agent_user_id, {
        "type": "new_message",
        "data": message
    })
