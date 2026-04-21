"""
群组同步和消息转发 API

核心逻辑：
1. 成员加入群时，成员后端与群主后端建立连接
2. 发送消息时，消息先到群主后端
3. 群主后端存储并转发给所有成员后端
4. 成员后端推送给前端
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import httpx
import asyncio
import json

from database import get_db
from models import User, Group, Contact, GroupMessage, group_members
from auth import get_current_user
from config import get_settings

router = APIRouter(prefix="/groups", tags=["群组同步"])


# 存储活跃的群成员连接（member_portal -> ws_connection）
# 实际生产环境应该用 Redis 或数据库
active_connections = {}


# ========== 1. 成员加入群 ==========

@router.post("/{group_id}/join")
async def join_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    成员后端调用此接口加入群
    1. 验证成员是否是群成员
    2. 建立与群主后端的连接
    3. 返回群信息和成员列表
    """
    settings = get_settings()
    
    # 获取群信息
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == group_id,
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # 检查是否是群主
    is_owner = group.owner_id == current_user.id
    
    # 如果不是群主，检查是否是群成员
    if not is_owner:
        # 通过 contact 查找
        result = await db.execute(
            select(Contact).where(
                and_(
                    Contact.owner_id == current_user.id,
                    Contact.portal_url == settings.PORTAL_URL,
                    Contact.is_active == True
                )
            )
        )
        contact = result.scalar_one_or_none()
        
        if contact:
            result = await db.execute(
                select(group_members).where(
                    and_(
                        group_members.c.group_id == group_id,
                        group_members.c.contact_id == contact.id
                    )
                )
            )
            if not result.scalar_one_or_none():
                raise HTTPException(status_code=403, detail="Not a group member")
    
    # 获取群主信息
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    
    if not owner:
        raise HTTPException(status_code=404, detail="Group owner not found")
    
    # 获取成员列表
    members = []
    if is_owner:
        # 群主：获取所有成员
        result = await db.execute(
            select(Contact).join(
                group_members,
                Contact.id == group_members.c.contact_id
            ).where(
                group_members.c.group_id == group_id
            )
        )
        contacts = result.scalars().all()
        for c in contacts:
            members.append({
                "portal_url": c.portal_url,
                "display_name": c.display_name
            })
    
    return {
        "status": "success",
        "group_id": group.group_id,
        "group_name": group.name,
        "is_owner": is_owner,
        "owner_portal": owner.portal_url,
        "members": members
    }


# ========== 2. 发送群消息（发送到群主后端）==========

@router.post("/{group_id}/messages")
async def send_group_message(
    group_id: int,
    request: Request,
    message_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    发送群消息
    1. 验证发送者是群成员
    2. 消息存储到群主后端
    3. 群主后端转发给所有成员
    """
    settings = get_settings()
    sender_portal = message_data.get("sender_portal", settings.PORTAL_URL)
    
    # 获取群信息
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == group_id,
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # 获取群主
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    
    # 判断是群主还是普通成员
    is_owner = group.owner_id == current_user.id
    
    if is_owner:
        # 群主直接处理消息
        return await _process_group_message(group, sender_portal, current_user, message_data, db)
    else:
        # 普通成员：消息需要发送到群主后端
        # 先获取群主的 portal_url
        owner_portal = owner.portal_url
        
        # 通过 contact 查找发送者
        result = await db.execute(
            select(Contact).where(
                and_(
                    Contact.owner_id == current_user.id,
                    Contact.portal_url == sender_portal,
                    Contact.is_active == True
                )
            )
        )
        contact = result.scalar_one_or_none()
        
        if not contact:
            raise HTTPException(status_code=403, detail="Contact not found")
        
        # 消息发送到群主后端
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{owner_portal}/api/groups/{group_id}/messages/forward",
                    json={
                        "sender_portal": sender_portal,
                        "sender_name": current_user.display_name or "用户",
                        "content": message_data.get("content"),
                        "message_type": message_data.get("message_type", "text"),
                        "timestamp": message_data.get("timestamp")
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    raise HTTPException(status_code=500, detail="Failed to forward message")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Forward error: {str(e)}")


async def _process_group_message(group, sender_portal, current_user, message_data, db):
    """处理群消息：存储并转发"""
    from datetime import datetime
    
    # 创建消息
    new_message = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_name=current_user.display_name or "用户",
        sender_portal=sender_portal,
        content=message_data.get("content"),
        message_type=message_data.get("message_type", "text"),
        is_from_owner=(group.owner_id == current_user.id)
    )
    db.add(new_message)
    await db.flush()
    
    # 获取所有成员
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            group_members.c.group_id == group.id
        )
    )
    members = result.scalars().all()
    
    # 转发给所有成员（除了发送者）
    from config import get_settings
    settings = get_settings()
    
    async with httpx.AsyncClient() as client:
        for member in members:
            if member.portal_url == sender_portal:
                continue  # 跳过发送者
            
            try:
                await client.post(
                    f"{member.portal_url}/api/groups/{group.id}/messages/receive",
                    json={
                        "group_id": group.group_id,
                        "message_id": new_message.id,
                        "sender_portal": sender_portal,
                        "sender_name": current_user.display_name or "用户",
                        "content": message_data.get("content"),
                        "message_type": message_data.get("message_type", "text"),
                        "created_at": new_message.created_at.isoformat()
                    },
                    timeout=10.0
                )
            except Exception as e:
                print(f"Failed to forward to {member.portal_url}: {e}")
    
    return {
        "status": "success",
        "message_id": new_message.id,
        "created_at": new_message.created_at.isoformat()
    }


# ========== 3. 接收转发消息（成员后端）==========

@router.post("/{group_id}/messages/receive")
async def receive_group_message(
    group_id: int,
    message_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收从群主后端转发的消息
    存储消息并推送给前端
    """
    from datetime import datetime
    
    # 查找群（使用 group_id 字符串）
    result = await db.execute(
        select(Group).where(
            and_(
                Group.group_id == message_data.get("group_id"),
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # 获取当前用户
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    
    if not current_user:
        raise HTTPException(status_code=404, detail="No active user")
    
    # 存储消息
    new_message = GroupMessage(
        group_id=group.id,
        sender_id=current_user.id,
        sender_name=message_data.get("sender_name", "未知"),
        sender_portal=message_data.get("sender_portal"),
        content=message_data.get("content"),
        message_type=message_data.get("message_type", "text"),
        is_from_owner=False
    )
    db.add(new_message)
    await db.flush()
    
    # TODO: 通过 WebSocket 推送给前端
    
    return {"status": "success"}


# ========== 4. 获取群消息历史 ==========

@router.get("/{group_id}/messages")
async def get_group_messages(
    group_id: int,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取群消息历史"""
    result = await db.execute(
        select(GroupMessage).where(
            GroupMessage.group_id == group_id
        ).order_by(
            GroupMessage.created_at.desc()
        ).limit(limit).offset(offset)
    )
    messages = result.scalars().all()
    
    return [
        {
            "id": m.id,
            "sender_portal": m.sender_portal,
            "sender_name": m.sender_name,
            "content": m.content,
            "message_type": m.message_type,
            "created_at": m.created_at.isoformat()
        }
        for m in messages
    ]
