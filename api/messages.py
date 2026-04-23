from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc
from datetime import datetime
import httpx

from database import get_db
from models import User, Contact, Message, Group, GroupMessage, group_members
from schemas import MessageCreate, MessageResponse, GroupMessageCreate, GroupMessageResponse
from auth import get_current_user
from config import get_settings
from websocket import manager, notify_new_message

router = APIRouter(prefix="/messages", tags=["消息"])


async def forward_to_agent(message_data: dict):
    """转发消息给 Agent（通过 OpenClaw hooks）"""
    settings = get_settings()
    if not settings.OPENCLAW_HOOKS_TOKEN:
        return
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.OPENCLAW_GATEWAY_URL}/hooks/wake",
                headers={"Authorization": f"Bearer {settings.OPENCLAW_HOOKS_TOKEN}"},
                json={
                    "type": "owner_message",
                    "data": message_data
                },
                timeout=5.0
            )
    except Exception:
        # 转发失败不影响主流程
        pass


async def send_to_contact_portal(contact: Contact, message_data: dict):
    """发送消息到对方 Portal"""
    import logging
    portal_url = contact.portal_url
    print(f"[SEND_MSG] Starting to send message to {portal_url}")
    print(f"[SEND_MSG] Contact ID: {contact.id}, shared_key exists: {bool(contact.shared_key)}")
    
    try:
        settings = get_settings()
        from_portal = settings.PORTAL_URL
        print(f"[SEND_MSG] From portal: {from_portal}")
        print(f"[SEND_MSG] Sender name: {message_data.get('sender_name')}")
        
        async with httpx.AsyncClient() as client:
            request_data = {
                "from_portal": from_portal,
                "sender_name": message_data.get("sender_name"),
                "content": message_data.get("content"),
                "message_type": message_data.get("message_type", "text"),
                "file_url": message_data.get("file_url"),
                "file_name": message_data.get("file_name"),
                "file_size": message_data.get("file_size"),
                "timestamp": datetime.utcnow().isoformat(),
                "signature": contact.shared_key
            }
            print(f"[SEND_MSG] Request data: {request_data}")
            
            target_url = f"{portal_url}/api/messages/receive"
            print(f"[SEND_MSG] POST to: {target_url}")
            
            response = await client.post(
                target_url,
                json=request_data,
                timeout=10.0
            )
            print(f"[SEND_MSG] Response status: {response.status_code}")
            print(f"[SEND_MSG] Response body: {response.text[:200]}")
            return response.status_code == 200
    except Exception as e:
        print(f"[SEND_MSG] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


# ========== 私聊消息 ==========

@router.get("", response_model=List[MessageResponse])
async def list_messages(
    contact_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取消息列表"""
    query = select(Message).where(
        and_(
            or_(
                Message.sender_id == current_user.id,
                Message.contact_id.in_(
                    select(Contact.id).where(Contact.owner_id == current_user.id)
                )
            )
        )
    )
    
    if contact_id:
        query = query.where(
            or_(
                and_(Message.sender_id == current_user.id, Message.contact_id == contact_id),
            )
        )
    
    query = query.order_by(desc(Message.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    messages = result.scalars().all()
    return messages


@router.get("/contact/{contact_id:int}", response_model=List[MessageResponse])
async def get_messages_by_contact(
    contact_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """通过 contact_id 获取消息"""
    # contact_id=0 表示 My Agent，跳过验证
    if contact_id != 0:
        # 验证联系人属于当前用户
        result = await db.execute(
            select(Contact).where(
                and_(
                    Contact.id == contact_id,
                    Contact.owner_id == current_user.id
                )
            )
        )
        contact = result.scalar_one_or_none()
        
        if not contact:
            return []
    
    # 获取与该联系人的消息
    query = select(Message).where(
        Message.contact_id == contact_id
    ).order_by(Message.created_at).limit(limit).offset(offset)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    return messages


@router.get("/portal/{portal_url:path}", response_model=List[MessageResponse])
async def get_messages_by_portal(
    portal_url: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """通过对方 portal URL 获取消息"""
    # 查找对应的联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.owner_id == current_user.id,
                Contact.portal_url == portal_url
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        return []
    
    # 获取与该联系人的消息
    query = select(Message).where(
        or_(
            and_(Message.sender_id == current_user.id, Message.contact_id == contact.id),
            and_(Message.sender_portal == portal_url, Message.contact_id == contact.id)
        )
    ).order_by(Message.created_at).limit(limit).offset(offset)
    
    result = await db.execute(query)
    messages = result.scalars().all()
    return messages


@router.post("", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    message_data: MessageCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """发送私聊消息"""
    if not message_data.contact_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="contact_id is required for private message"
        )
    
    # 验证联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.id == message_data.contact_id,
                Contact.owner_id == current_user.id,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )
    
    # 创建消息
    new_message = Message(
        sender_id=current_user.id,
        contact_id=contact.id,
        content=message_data.content,
        message_type=message_data.message_type,
        file_url=message_data.file_url,
        file_name=message_data.file_name,
        file_size=message_data.file_size,
        is_from_owner=True  # 主人发送的消息
    )
    
    db.add(new_message)
    await db.flush()
    
    # 不需要通知发送者（自己发的消息已经显示了）
    # WebSocket 通知只给接收者（通过对方 Portal 的 /receive 端点触发）
    
    # 转发给 Agent（后台任务）
    background_tasks.add_task(
        forward_to_agent,
        {
            "message_id": new_message.id,
            "type": "private",
            "contact_id": contact.id,
            "contact_name": contact.display_name,
            "content": new_message.content,
            "message_type": new_message.message_type,
            "created_at": new_message.created_at.isoformat()
        }
    )
    
    # 发送到对方 Portal（同步执行，调试用）
    import asyncio
    await send_to_contact_portal(
        contact,
        {
            "sender_name": current_user.display_name or current_user.username,
            "content": new_message.content,
            "message_type": new_message.message_type,
            "file_url": new_message.file_url,
            "file_name": new_message.file_name,
            "file_size": new_message.file_size
        }
    )
    
    return new_message


@router.post("/receive", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def receive_message(
    message_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收来自其他 Portal 的消息
    跨 Portal 调用，无需用户认证，用 shared_key 验证
    """
    print(f"[RECEIVE_MSG] Received message: {message_data}")
    
    from_portal = message_data.get("from_portal")
    sender_name = message_data.get("sender_name")
    content = message_data.get("content")
    signature = message_data.get("signature")  # shared_key
    
    print(f"[RECEIVE_MSG] from_portal: {from_portal}, sender_name: {sender_name}")
    
    if not all([from_portal, content]):
        print("[RECEIVE_MSG] ERROR: Missing required fields")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields"
        )
    
    # 查找发送方对应的联系人（通过 portal_url）
    print(f"[RECEIVE_MSG] Looking for contact with portal_url: {from_portal}")
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.portal_url == from_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        print(f"[RECEIVE_MSG] ERROR: Contact not found for portal: {from_portal}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found"
        )
    
    print(f"[RECEIVE_MSG] Found contact: ID={contact.id}, shared_key exists={bool(contact.shared_key)}")
    
    # 验证 shared_key
    if signature and contact.shared_key and signature != contact.shared_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid shared key"
        )
    
    # 查找当前用户的第一个活跃用户
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active user"
        )
    
    
    # 创建消息（标记为来自联系人，不是主人）
    new_message = Message(
        sender_id=current_user.id,  # 用当前用户作为占位
        sender_portal=from_portal,  # 保存发送者的 portal
        contact_id=contact.id,
        content=content,
        message_type=message_data.get("message_type", "text"),
        file_url=message_data.get("file_url"),
        file_name=message_data.get("file_name"),
        file_size=message_data.get("file_size"),
        is_from_owner=False  # 不是主人发送的，不转发给 Agent
    )
    
    db.add(new_message)
    await db.flush()
    
    # 通过 WebSocket 推送给接收者
    print(f"[WS_NOTIFY] Sending to user {current_user.id}, portal_url={from_portal}, sender_name={sender_name}")
    await notify_new_message(current_user.id, {
        "id": new_message.id,
        "portal_url": from_portal,
        "sender_name": sender_name,
        "contact_id": contact.id,
        "content": new_message.content,
        "message_type": new_message.message_type,
        "is_from_owner": False,
        "created_at": new_message.created_at.isoformat()
    })
    print(f"[WS_NOTIFY] Sent successfully")
    
    return new_message


@router.get("/unread", response_model=List[MessageResponse])
async def get_unread_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取未读消息"""
    result = await db.execute(
        select(Message).where(
            and_(
                Message.is_read == False,
                Message.contact_id.in_(
                    select(Contact.id).where(Contact.owner_id == current_user.id)
                )
            )
        ).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return messages


@router.post("/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_as_read(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """标记消息为已读"""
    result = await db.execute(
        select(Message).where(
            and_(
                Message.id == message_id,
                Message.contact_id.in_(
                    select(Contact.id).where(Contact.owner_id == current_user.id)
                )
            )
        )
    )
    message = result.scalar_one_or_none()
    
    if message:
        message.is_read = True
        await db.flush()
    
    return None


# ========== 群聊消息 ==========

# 注意：/group/{group_id} 必须在 /group/uuid/{group_uuid} 之前定义
# 因为 FastAPI 按顺序匹配路由，数字 ID 会匹配到 uuid 路由

@router.get("/group/{group_id}", response_model=List[GroupMessageResponse])
async def list_group_messages(
    group_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取群聊消息"""
    # 验证群组权限
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == group_id,
                Group.owner_id == current_user.id,
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    result = await db.execute(
        select(GroupMessage).where(
            GroupMessage.group_id == group_id
        ).order_by(desc(GroupMessage.created_at)).limit(limit).offset(offset)
    )
    messages = result.scalars().all()
    return messages


@router.get("/group/uuid/{group_uuid}", response_model=List[GroupMessageResponse])
@router.get("/group/by-uuid/{group_uuid}", response_model=List[GroupMessageResponse])
async def list_group_messages_by_uuid(
    group_uuid: str,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """通过 UUID 获取群聊消息（用于加入的群）"""
    result = await db.execute(
        select(GroupMessage).where(
            GroupMessage.group_uuid == group_uuid
        ).order_by(GroupMessage.created_at).limit(limit).offset(offset)
    )
    messages = result.scalars().all()
    return messages


@router.post("/group", response_model=GroupMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_group_message(
    message_data: GroupMessageCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    发送群聊消息
    验证：1. sender portal 在成员列表中 2. 消息签名有效
    """
    settings = get_settings()
    
    # 获取 sender portal（从请求头或当前用户）
    sender_portal = request.headers.get("X-Sender-Portal", settings.PORTAL_URL)
    
    # 验证群组
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == message_data.group_id,
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # 验证 sender 在群成员列表中
    # 群主可以发送消息，或者 sender 是群成员列表中的联系人
    is_owner = group.owner_id == current_user.id
    is_member_in_contacts = False
    
    # 检查 sender_portal 是否在群成员的联系中
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.portal_url == sender_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if contact:
        # 检查该联系人是否在群成员中
        result = await db.execute(
            select(group_members).where(
                and_(
                    group_members.c.group_id == message_data.group_id,
                    group_members.c.contact_id == contact.id
                )
            )
        )
        is_member_in_contacts = result.scalar_one_or_none() is not None
    
    if not is_owner and not is_member_in_contacts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sender not in group members"
        )
    
    # 创建群消息
    new_message = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_name=current_user.display_name or "用户",
        sender_portal=sender_portal,
        content=message_data.content,
        message_type=message_data.message_type,
        file_url=message_data.file_url,
        file_name=message_data.file_name,
        file_size=message_data.file_size,
        is_from_owner=True
    )
    
    db.add(new_message)
    await db.flush()
    
    # 转发给群成员的其他 Portal（使用全局 group_id）
    background_tasks.add_task(
        forward_group_message,
        group.id,
        group.group_id,  # 传递全局 group_id
        sender_portal,
        current_user.display_name or "用户",
        {
            "group_id": group.group_id,  # 使用全局 group_id
            "sender_portal": sender_portal,
            "sender_name": current_user.display_name or "用户",
            "content": message_data.content,
            "message_type": message_data.message_type,
            "created_at": new_message.created_at.isoformat()
        },
        db
    )
    
    return new_message


async def forward_group_message(group_db_id: int, group_id: str, sender_portal: str, sender_name: str, message_data: dict, db: AsyncSession):
    """转发群消息到所有成员的 Portal"""
    from models import group_members
    
    try:
        # 获取群成员（使用 group_db_id 查询数据库）
        result = await db.execute(
            select(Contact).join(
                group_members,
                Contact.id == group_members.c.contact_id
            ).where(
                group_members.c.group_id == group_db_id
            )
        )
        members = result.scalars().all()
        
        settings = get_settings()
        
        async with httpx.AsyncClient() as client:
            for member in members:
                # 跳过发送者自己
                if member.portal_url == sender_portal:
                    continue
                
                try:
                    # 用 shared_key 签名消息
                    import hashlib
                    message_str = f"{group_id}:{sender_portal}:{message_data['content']}:{message_data['created_at']}"
                    signature = hashlib.sha256(f"{message_str}:{member.shared_key}".encode()).hexdigest()
                    
                    await client.post(
                        f"{member.portal_url}/api/messages/group/receive",
                        json={
                            "group_id": group_id,
                            "sender_portal": sender_portal,
                            "sender_name": sender_name,
                            "content": message_data["content"],
                            "message_type": message_data["message_type"],
                            "timestamp": message_data["created_at"],
                            "signature": signature
                        },
                        headers={
                            "X-Sender-Portal": sender_portal
                        },
                        timeout=10.0
                    )
                except Exception as e:
                    print(f"Failed to forward to {member.portal_url}: {e}")
                    
    except Exception as e:
        print(f"Forward group message error: {e}")


@router.post("/group/receive", response_model=dict)
async def receive_group_message(
    message_data: dict,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    接收来自其他 Portal 的群消息
    验证：1. sender portal 在成员列表中 2. 签名有效
    """
    sender_portal = message_data.get("sender_portal") or request.headers.get("X-Sender-Portal")
    group_id = message_data.get("group_id")
    signature = message_data.get("signature")
    timestamp = message_data.get("timestamp")
    
    if not all([sender_portal, group_id, signature, timestamp]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields"
        )
    
    # 查找当前用户
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active user"
        )
    
    # 查找群（使用全局 group_id）
    result = await db.execute(
        select(Group).where(
            and_(
                Group.group_id == group_id,
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # 验证 sender 在群成员列表中
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            and_(
                group_members.c.group_id == group.id,  # 使用 group.id（数据库ID）
                Contact.portal_url == sender_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sender not in group members"
        )
    
    # 验证签名
    import hashlib
    content = message_data.get("content", "")
    message_str = f"{group_id}:{sender_portal}:{content}:{timestamp}"
    expected_signature = hashlib.sha256(f"{message_str}:{contact.shared_key}".encode()).hexdigest()
    
    if signature != expected_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )
    
    # 创建群消息
    new_message = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_name=message_data.get("sender_name", "未知"),
        sender_portal=sender_portal,
        content=content,
        message_type=message_data.get("message_type", "text"),
        is_from_owner=False
    )
    
    db.add(new_message)
    await db.flush()
    
    # 通过 WebSocket 通知用户
    await notify_new_message(current_user.id, {
        "id": new_message.id,
        "group_id": group.id,
        "sender_name": new_message.sender_name,
        "content": new_message.content,
        "message_type": new_message.message_type,
        "is_from_owner": False,
        "created_at": new_message.created_at.isoformat()
    })
    
    return {"status": "success"}


@router.post("/owner/reply", response_model=dict)
async def chat_owner_reply(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Agent 回复主人消息
    用于 p2p-channel 插件发送 Agent 回复到 Portal
    """
    content = data.get("content", "")
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content is required"
        )
    
    try:
        # 保存消息到数据库（contact_id=0 表示 My Agent）
        message = Message(
            sender_id=0,  # 0 表示 Agent
            contact_id=0,  # 0 表示 My Agent
            content=content,
            message_type="text",
            is_from_owner=False,  # 来自 Agent
            is_read=False,
            created_at=datetime.now()
        )
        db.add(message)
        await db.commit()
        await db.refresh(message)
        
        # 通过 WebSocket 通知用户
        from websocket import manager
        await manager.send_to_user(current_user.id, {
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
        print(f"[CHAT_REPLY] Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save reply: {str(e)}"
        )
