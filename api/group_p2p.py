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
from models import User, Group, Contact, GroupMessage, GroupMemberCache, group_members
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


# ========== 0. 获取我加入的群列表（必须在 /{group_id} 路由之前）==========

@router.get("/my-groups")
async def get_my_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取当前用户加入的所有群（从本地缓存）
    """
    import json
    
    settings = get_settings()
    
    result = await db.execute(
        select(GroupMemberCache).where(
            GroupMemberCache.owner_portal != settings.PORTAL_URL
        )
    )
    caches = result.scalars().all()
    
    my_groups = []
    for cache in caches:
        members = json.loads(cache.members_json) if cache.members_json else []
        my_groups.append({
            "group_id": cache.group_id,
            "db_id": cache.db_id,  # 数字ID
            "group_name": cache.group_name,
            "owner_portal": cache.owner_portal,
            "is_owner": False,  # 从缓存获取的都是加入的群，不是群主
            "member_count": len(members),
            "members": members,
            "version": cache.list_version,
            "updated_at": cache.updated_at.isoformat() if cache.updated_at else None
        })
    
    # 也获取我创建的群
    result = await db.execute(
        select(Group).where(
            and_(
                Group.owner_id == current_user.id,
                Group.is_active == True
            )
        )
    )
    owned_groups = result.scalars().all()
    
    for group in owned_groups:
        result = await db.execute(
            select(Contact).join(
                group_members,
                Contact.id == group_members.c.contact_id
            ).where(
                group_members.c.group_id == group.id
            )
        )
        members_result = result.scalars().all()
        members = [{"portal": m.portal_url, "display_name": m.display_name} for m in members_result]
        
        members.insert(0, {
            "portal": settings.PORTAL_URL,
            "display_name": current_user.display_name or "群主"
        })
        
        my_groups.append({
            "group_id": group.group_id,
            "db_id": group.id,  # 数字ID
            "group_name": group.name,
            "owner_portal": settings.PORTAL_URL,
            "is_owner": True,
            "member_count": len(members),
            "members": members,
            "version": group.version or 1
        })
    
    return {"groups": my_groups}


# ========== 1. 成员注册 portal ==========

@router.post("/{group_id}/register-portal")
async def register_member_portal(
    group_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    成员注册自己的 portal，用于接收群列表更新
    返回当前成员列表 + group_key（用于签名验证）
    支持外部 Portal 调用（通过 X-Sender-Portal 头）
    """
    settings = get_settings()
    
    # 获取调用者 portal（从 header 或当前用户）
    sender_portal = request.headers.get("X-Sender-Portal")
    
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
    
    # 验证调用者是否是合法的群成员
    # 注：邀请记录在对方数据库中，这里无法验证
    # 简化处理：只要有有效的 group_id 就允许注册
    # 真实的验证在对方接受邀请时完成
    if sender_portal:
        # 外部调用：检查是否已经是成员
        result = await db.execute(
            select(Contact).join(
                group_members,
                Contact.id == group_members.c.contact_id
            ).where(
                and_(
                    group_members.c.group_id == group_id,
                    Contact.portal_url == sender_portal
                )
            )
        )
        member = result.scalar_one_or_none()
        # 如果不是成员，也允许注册（可能是新成员）
        pass
    else:
        # 内部调用：需要用户认证
        from auth import get_current_user
        current_user = await get_current_user(db=db)
        is_owner = group.owner_id == current_user.id
        if not is_owner:
            raise HTTPException(status_code=403, detail="Not group owner")
    
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
    
    # 存储到本地缓存（非群主）
    if not is_owner:
        import json
        result = await db.execute(
            select(GroupMemberCache).where(
                GroupMemberCache.group_id == group.group_id
            )
        )
        cache = result.scalar_one_or_none()
        
        if cache:
            cache.owner_portal = owner.portal_url if owner else ""
            cache.group_key = group.group_key
            cache.members_json = json.dumps(member_list)
            cache.db_id = group.id  # 存储数字ID
            cache.group_name = group.name
        else:
            cache = GroupMemberCache(
                group_id=group.group_id,
                db_id=group.id,  # 存储数字ID
                group_name=group.name,
                owner_portal=owner.portal_url if owner else "",
                group_key=group.group_key,
                members_json=json.dumps(member_list),
                list_version=1
            )
            db.add(cache)
        await db.flush()
    
    return {
        "status": "success",
        "group_id": group.group_id,
        "db_id": group.id,  # 返回数字ID
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
    
    # 先存储发送者自己的消息
    new_message = GroupMessage(
        group_id=group.id,
        group_uuid=group.group_id,
        sender_id=current_user.id,
        sender_name=current_user.display_name or "用户",
        sender_portal=sender_portal,
        content=content,
        message_type=message_data.get("message_type", "text"),
        is_from_owner=True
    )
    db.add(new_message)
    await db.flush()
    message_id = new_message.id
    
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
    
    # 记录发送结果
    print(f"[P2P Send] Message sent to {success_count} members, failed: {failed_members}")
    
    return {
        "status": "success",
        "message_id": f"msg-{int(datetime.utcnow().timestamp())}",
        "sent_to": success_count,
        "failed": failed_members,
        "total_members": len(members) + (1 if owner and owner.portal_url != sender_portal else 0)
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
    # 优先从缓存获取（适用于非群主）
    result = await db.execute(
        select(GroupMemberCache).where(
            GroupMemberCache.group_id == group_id
        )
    )
    cache = result.scalar_one_or_none()
    
    # 如果没有缓存，尝试从 Group 表获取（适用于群主）
    group = None
    if not cache:
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
            raise HTTPException(status_code=404, detail="Group not found")
    
    sender_portal = message_data.get("sender_portal")
    content = message_data.get("content", "")
    timestamp = message_data.get("timestamp", "")
    signature = message_data.get("signature", "")
    
    # 确定 group_key 用于验证
    group_key = None
    if cache:
        group_key = cache.group_key
    elif group:
        group_key = group.group_key
    else:
        raise HTTPException(status_code=404, detail="Group not found")
    
    # 验证发送者在成员列表中（如果有缓存）
    if cache and cache.members_json:
        import json
        members = json.loads(cache.members_json)
        member_portals = [m.get("portal") for m in members]
        
        if sender_portal not in member_portals:
            raise HTTPException(status_code=403, detail="Sender not in group members")
    
    # 验证签名
    if not verify_signature(content, timestamp, signature, group_key):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # 获取当前用户的第一个（简化处理）
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    sender_id = current_user.id if current_user else 1
    
    # 存储消息
    # 确定 group_id (数字) 和 group_uuid (字符串)
    db_id = None
    uuid = None
    if group:
        db_id = group.id
        uuid = group.group_id
    elif cache:
        db_id = cache.db_id
        uuid = cache.group_id
    
    new_message = GroupMessage(
        group_id=db_id,  # 数字ID，可能为空
        group_uuid=uuid,  # UUID 字符串
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
    settings = get_settings()
    new_version = (group.version or 1) + 1
    
    for member in remaining_members:
        if member.portal_url == member_portal:
            continue
        
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{member.portal_url}/api/webhook/group-list-update",
                    json={
                        "group_id": group.group_id,
                        "db_id": group.id,  # 数字ID
                        "owner_portal": settings.PORTAL_URL,
                        "action": "member_removed",
                        "removed_portal": member_portal,
                        "members": member_list,
                        "group_key": group.group_key,
                        "version": new_version
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


# ========== 5b. 添加成员 ==========

@router.post("/{group_id}/members/add")
async def add_member(
    group_id: int,
    add_data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    添加成员
    群主操作，更新列表并推送新列表给所有成员（包括新添加的）
    """
    settings = get_settings()
    member_portal = add_data.get("member_portal")
    member_name = add_data.get("member_name", "成员")
    
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
        raise HTTPException(status_code=403, detail="Only owner can add members")
    
    # 查找联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.portal_url == member_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    # 检查是否已在群中
    result = await db.execute(
        select(group_members).where(
            and_(
                group_members.c.group_id == group_id,
                group_members.c.contact_id == contact.id
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Member already in group")
    
    # 添加到 group_members
    await db.execute(
        group_members.insert().values(
            group_id=group_id,
            contact_id=contact.id
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
    
    # 推送新列表给所有成员（包括新添加的）
    new_version = (group.version or 1) + 1
    all_targets = list(remaining_members)
    
    # 添加群主到推送列表
    if owner and owner.portal_url != settings.PORTAL_URL:
        all_targets = list(remaining_members)
    
    for target in remaining_members:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{target.portal_url}/api/webhook/group-list-update",
                    json={
                        "group_id": group.group_id,
                        "db_id": group.id,  # 数字ID
                        "owner_portal": settings.PORTAL_URL,
                        "action": "member_added",
                        "added_portal": member_portal,
                        "added_name": member_name,
                        "members": member_list,
                        "group_key": group.group_key,
                        "version": new_version
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"Failed to push update to {target.portal_url}: {e}")
    
    # 也推送给新添加的成员
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{member_portal}/api/webhook/group-list-update",
                json={
                    "group_id": group.group_id,
                    "db_id": group.id,  # 数字ID
                    "owner_portal": settings.PORTAL_URL,
                    "action": "member_added",
                    "added_portal": member_portal,
                    "added_name": member_name,
                    "members": member_list,
                    "group_key": group.group_key,
                    "version": new_version
                },
                timeout=10.0
            )
    except Exception as e:
        print(f"Failed to push update to new member {member_portal}: {e}")
    
    return {
        "status": "success",
        "group_id": group.group_id,
        "added": member_portal,
        "all_members": member_list
    }


# ========== 7. 接收群列表更新（Webhook）==========

@router.post("/webhook/group-list-update")
async def receive_group_list_update(
    update_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收群主推送的成员列表更新
    存储到本地缓存
    """
    import json
    
    group_id = update_data.get("group_id")
    db_id = update_data.get("db_id")  # 数字ID
    owner_portal = update_data.get("owner_portal")
    group_key = update_data.get("group_key")
    group_name = update_data.get("group_name", "群组")
    members = update_data.get("members", [])
    version = update_data.get("version", 1)
    signature = update_data.get("signature")
    
    if not all([group_id, owner_portal, group_key]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # 验证签名（用 group_key）
    # TODO: 后续升级为群主 RSA 公钥验证
    
    # 存储或更新缓存
    result = await db.execute(
        select(GroupMemberCache).where(
            GroupMemberCache.group_id == group_id
        )
    )
    cache = result.scalar_one_or_none()
    
    if cache:
        cache.owner_portal = owner_portal
        cache.group_key = group_key
        cache.group_name = group_name
        cache.db_id = db_id  # 更新数字ID
        cache.members_json = json.dumps(members)
        cache.list_version = version
        cache.list_signature = signature
    else:
        cache = GroupMemberCache(
            group_id=group_id,
            db_id=db_id,  # 存储数字ID
            owner_portal=owner_portal,
            group_key=group_key,
            group_name=group_name,
            members_json=json.dumps(members),
            list_version=version,
            list_signature=signature
        )
        db.add(cache)
    
    await db.flush()
    return {"status": "success", "version": version}


# ========== 8. 接收成员接受通知（Webhook）==========

@router.post("/group-accept")
async def receive_group_accept(
    accept_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收成员接受邀请的通知
    群主端：添加成员并广播
    """
    from models import Group, Contact, GroupInvite
    
    group_id = accept_data.get("group_id")
    invitee_portal = accept_data.get("invitee_portal")
    invitee_name = accept_data.get("invitee_name", "用户")
    
    if not all([group_id, invitee_portal]):
        raise HTTPException(status_code=400, detail="Missing required fields")
    
    # 查找群组
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
        raise HTTPException(status_code=404, detail="Group not found")
    
    # 查找或创建联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.portal_url == invitee_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        contact = Contact(
            owner_id=group.owner_id,
            display_name=invitee_name,
            portal_url=invitee_portal,
            is_active=True
        )
        db.add(contact)
        await db.flush()
    
    # 添加成员关系
    try:
        await db.execute(
            group_members.insert().values(
                group_id=group.id,
                contact_id=contact.id
            )
        )
        await db.flush()
    except Exception as e:
        print(f"Member already exists: {e}")
    
    # 获取更新后的成员列表
    result = await db.execute(
        select(Contact).join(
            group_members,
            Contact.id == group_members.c.contact_id
        ).where(
            group_members.c.group_id == group.id
        )
    )
    members_result = result.scalars().all()
    member_list = [{"portal": m.portal_url, "display_name": m.display_name} for m in members_result]
    
    # 加入群主
    result = await db.execute(select(User).where(User.id == group.owner_id))
    owner = result.scalar_one_or_none()
    member_list.insert(0, {
        "portal": owner.portal_url if owner else "",
        "display_name": owner.display_name if owner else "群主"
    })
    
    # 广播给所有成员
    settings = get_settings()
    new_version = (group.version or 1) + 1
    
    for member in members_result:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{member.portal_url}/api/webhook/group-list-update",
                    json={
                        "group_id": group.group_id,
                        "db_id": group.id,
                        "owner_portal": settings.PORTAL_URL,
                        "action": "member_added",
                        "added_portal": invitee_portal,
                        "added_name": invitee_name,
                        "members": member_list,
                        "group_key": group.group_key,
                        "version": new_version
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"Failed to broadcast to {member.portal_url}: {e}")
    
    # 推送给新成员
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{invitee_portal}/api/webhook/group-list-update",
                json={
                    "group_id": group.group_id,
                    "db_id": group.id,
                    "owner_portal": settings.PORTAL_URL,
                    "action": "member_added",
                    "added_portal": invitee_portal,
                    "added_name": invitee_name,
                    "members": member_list,
                    "group_key": group.group_key,
                    "version": new_version
                },
                timeout=10.0
            )
    except Exception as e:
        print(f"Failed to notify new member: {e}")
    
    return {
        "status": "success",
        "message": "Member added and broadcasted",
        "group_id": group.group_id,
        "db_id": group.id,
        "group_name": group.name,
        "group_key": group.group_key,
        "members": member_list
    }
