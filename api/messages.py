from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc
from datetime import datetime
import httpx

from database import get_db
from models import User, Contact, Message, Group, GroupMessage
from schemas import MessageCreate, MessageResponse, GroupMessageCreate, GroupMessageResponse
from auth import get_current_user
from config import get_settings

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
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{contact.portal_url}/api/messages/receive",
                json={
                    "from_portal": get_settings().PORTAL_URL,
                    "sender_name": message_data.get("sender_name"),
                    "content": message_data.get("content"),
                    "message_type": message_data.get("message_type", "text"),
                    "file_url": message_data.get("file_url"),
                    "file_name": message_data.get("file_name"),
                    "file_size": message_data.get("file_size"),
                    "timestamp": datetime.utcnow().isoformat(),
                    "signature": contact.shared_key  # 简单签名验证
                },
                timeout=10.0
            )
            return response.status_code == 200
    except Exception:
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
                # 这里简化处理，实际应该关联查询
            )
        )
    
    query = query.order_by(desc(Message.created_at)).limit(limit).offset(offset)
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
    
    # 发送到对方 Portal（后台任务）
    background_tasks.add_task(
        send_to_contact_portal,
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """接收来自其他 Portal 的消息"""
    from_portal = message_data.get("from_portal")
    sender_name = message_data.get("sender_name")
    content = message_data.get("content")
    
    if not all([from_portal, content]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields"
        )
    
    # 查找对应的联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.owner_id == current_user.id,
                Contact.portal_url == from_portal,
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
    
    # 创建消息（标记为来自联系人，不是主人）
    new_message = Message(
        sender_id=current_user.id,  # 用当前用户作为占位
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
    
    # TODO: 通过 WebSocket 推送给客户端
    
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


@router.post("/group", response_model=GroupMessageResponse, status_code=status.HTTP_201_CREATED)
async def send_group_message(
    message_data: GroupMessageCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """发送群聊消息"""
    # 验证群组
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == message_data.group_id,
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
    
    # 创建群消息
    new_message = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_name=current_user.display_name or current_user.username,
        content=message_data.content,
        message_type=message_data.message_type,
        file_url=message_data.file_url,
        file_name=message_data.file_name,
        file_size=message_data.file_size,
        is_from_owner=True
    )
    
    db.add(new_message)
    await db.flush()
    
    # 转发给 Agent（后台任务）
    background_tasks.add_task(
        forward_to_agent,
        {
            "message_id": new_message.id,
            "type": "group",
            "group_id": group.id,
            "group_name": group.name,
            "content": new_message.content,
            "message_type": new_message.message_type,
            "created_at": new_message.created_at.isoformat()
        }
    )
    
    # TODO: 转发给群成员的其他 Portal
    
    return new_message
