"""
群聊 P2P 架构实现

核心设计：
1. 群主只维护成员列表
2. 消息直接 P2P 发送给每个成员
3. 使用 shared_key 签名消息
4. 成员本地存储消息

接口：
- POST /groups/{id}/register-portal  - 成员注册自己的 portal
- GET  /groups/{id}/members         - 获取成员列表
- POST /groups/{id}/messages/p2p    - P2P 发送消息
- POST /groups/{id}/messages/receive - P2P 接收消息
- POST /groups/{id}/members/remove   - 删除成员
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from datetime import datetime
import httpx
import hashlib
import secrets

from database import get_db
from models import User, Group, Contact, GroupMessage, group_members
from auth import get_current_user
from config import get_settings

router = APIRouter(prefix="/groups", tags=["群组 P2P"])

# 生成消息签名
def sign_message(content: str, timestamp: str, shared_key: str) -> str:
    data = f"{content}:{timestamp}"
    return hashlib.sha256(f"{data}:{shared_key}".encode()).hexdigest()

# 验证消息签名
def verify_signature(content: str, timestamp: str, signature: str, shared_key: str) -> bool:
    expected = sign_message(content, timestamp, shared_key)
    return signature == expected


# ========== 1. 成员注册 portal ==========

@router.post("/{group_id}/register-portal")
async def register_member_portal(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    成员注册自己的 portal，用于接收群列表更新
    返回当前成员列表 + group_key（用于签名验证）
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
    
    # 检查是否是群主或群成员
    is_owner = group.owner_id == current_user.id
    
    # 如果不是群主，检查是否是群成员
    if not is_owner:
        result = await db.execute(
            select(Contact).where(
                and_(
                    Contact.owner_id == current_user.id,
                    Contact.is_active == True
                )
            )
        )
        contact = result.scalar_one_or_none()
        
        if not contact:
            raise HTTPException(status_code=403, detail="Not a group member")
        
        # 检查是否已在 group_members
        result = await db.execute(
            select(group_members).where(
                and_(
                    group_members.c.group_id == group_id,
                    group_members.c.contact_id == contact.id
                )
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Not in this group")
    
    # 获取成员列表
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            group_members.c.group_id == group_id
        )
    )
    members = result.scalars().all()
    
    member_list = [
        {
            "portal": m.portal_url,
            "display_name": m.display_name
        }
        for m in members
    ]
    
    # 也把群主加进去
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    if owner and owner.portal_url not in [m["portal"] for m in member_list]:
        member_list.insert(0, {
            "portal": owner.portal_url,
            "display_name": owner.display_name or "群主"
        })
    
    return {
        "status": "success",
        "group_id": group.group_id,
        "group_name": group.name,
        "group_key": group.group_key,
        "members": member_list,
        "is_owner": is_owner
    }


# ========== 2. 获取成员列表 ==========

@router.get("/{group_id}/members")
async def get_group_members(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取群成员列表"""
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
    
    # 获取成员列表
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            group_members.c.group_id == group_id
        )
    )
    members = result.scalars().all()
    
    member_list = [
        {
            "portal": m.portal_url,
            "display_name": m.display_name
        }
        for m in members
    ]
    
    # 加入群主
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    if owner:
        member_list.insert(0, {
            "portal": owner.portal_url,
            "display_name": owner.display_name or "群主"
        })
    
    return {
        "group_id": group.group_id,
        "members": member_list,
        "group_key": group.group_key
    }


# ========== 3. P2P 发送消息 ==========

@router.post("/{group_id}/messages/p2p")
async def send_group_message_p2p(
    group_id: int,
    request: Request,
    message_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    P2P 发送群消息
    发送者直接发给每个成员，不经过群主
    """
    settings = get_settings()
    sender_portal = settings.PORTAL_URL
    
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
    
    # 获取成员列表
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            group_members.c.group_id == group_id
        )
    )
    members = result.scalars().all()
    
    # 构建消息
    timestamp = datetime.utcnow().isoformat()
    content = message_data.get("content", "")
    signature = sign_message(content, timestamp, group.group_key)
    
    message_payload = {
        "group_id": group.group_id,
        "sender_portal": sender_portal,
        "sender_name": current_user.display_name or "用户",
        "content": content,
        "message_type": message_data.get("message_type", "text"),
        "timestamp": timestamp,
        "signature": signature
    }
    
    # P2P 发送给每个成员（通过他们注册的 portal）
    success_count = 0
    failed_members = []
    
    # 发送给群主
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    
    if owner and owner.portal_url != sender_portal:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{owner.portal_url}/api/groups/{group.group_id}/messages/receive",
                    json=message_payload,
                    timeout=10.0
                )
                if response.status_code == 200:
                    success_count += 1
                else:
                    failed_members.append(owner.portal_url)
        except Exception as e:
            print(f"Failed to send to {owner.portal_url}: {e}")
            failed_members.append(owner.portal_url)
    
    # 发送给每个成员
    for member in members:
        if member.portal_url == sender_portal:
            continue  # 跳过发送者自己
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{member.portal_url}/api/groups/{group.group_id}/messages/receive",
                    json=message_payload,
                    timeout=10.0
                )
                if response.status_code == 200:
                    success_count += 1
                else:
                    failed_members.append(member.portal_url)
        except Exception as e:
            print(f"Failed to send to {member.portal_url}: {e}")
            failed_members.append(member.portal_url)
    
    return {
        "status": "success",
        "message_id": f"msg-{int(datetime.utcnow().timestamp())}",
        "sent_to": success_count,
        "failed": failed_members
    }


# ========== 4. P2P 接收消息 ==========

@router.post("/{group_id}/messages/receive")
async def receive_group_message(
    group_id: str,  # 使用全局 group_id 字符串
    message_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    P2P 接收消息
    验证签名并存储
    不需要用户认证，因为这是从其他Portal后端调用的
    """
    result = await db.execute(
        select(Group).where(
            and_(
                Group.group_id == group_id,  # 使用全局 group_id 查找
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # 验证签名
    content = message_data.get("content", "")
    timestamp = message_data.get("timestamp", "")
    signature = message_data.get("signature", "")
    
    if not verify_signature(content, timestamp, signature, group.group_key):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # 获取当前用户的第一个（简化处理）
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    sender_id = current_user.id if current_user else 1
    
    # 存储消息
    new_message = GroupMessage(
        group_id=group.id,
        sender_id=sender_id,
        sender_name=message_data.get("sender_name", "未知"),
        sender_portal=message_data.get("sender_portal"),
        content=content,
        message_type=message_data.get("message_type", "text"),
        is_from_owner=False
    )
    db.add(new_message)
    await db.flush()
    
    # TODO: 通过 WebSocket 推送给前端
    
    return {"status": "success", "message_id": new_message.id}


# ========== 5. 删除成员 ==========

@router.post("/{group_id}/members/remove")
async def remove_member(
    group_id: int,
    remove_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    删除成员
    群主操作，更新列表并推送新列表给所有成员
    """
    settings = get_settings()
    member_portal = remove_data.get("member_portal")
    
    if not member_portal:
        raise HTTPException(status_code=400, detail="member_portal required")
    
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
    
    # 验证是群主
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only owner can remove members")
    
    # 查找并删除成员
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.portal_url == member_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if contact:
        # 从 group_members 删除
        await db.execute(
            delete(group_members).where(
                and_(
                    group_members.c.group_id == group_id,
                    group_members.c.contact_id == contact.id
                )
            )
        )
        await db.flush()
    
    # 获取更新后的成员列表
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            group_members.c.group_id == group_id
        )
    )
    remaining_members = result.scalars().all()
    
    member_list = []
    for m in remaining_members:
        member_list.append({
            "portal": m.portal_url,
            "display_name": m.display_name
        })
    
    # 加入群主
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    if owner:
        member_list.insert(0, {
            "portal": owner.portal_url,
            "display_name": owner.display_name or "群主"
        })
    
    # 推送新列表给所有剩余成员
    for member in remaining_members:
        if member.portal_url == member_portal:
            continue
        
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{member.portal_url}/api/webhook/group-list-update",
                    json={
                        "group_id": group.group_id,
                        "action": "member_removed",
                        "removed_portal": member_portal,
                        "members": member_list,
                        "group_key": group.group_key
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"Failed to push update to {member.portal_url}: {e}")
    
    return {
        "status": "success",
        "group_id": group.group_id,
        "removed": member_portal,
        "remaining_members": member_list
    }


# ========== 6. 接收群列表更新（Webhook）==========

@router.post("/webhook/group-list-update")
async def receive_group_list_update(
    update_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收群主推送的成员列表更新
    """
    # TODO: 实现本地存储更新
    return {"status": "received"}
