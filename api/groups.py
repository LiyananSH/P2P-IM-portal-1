from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import User, Group, Contact, group_members
from schemas import GroupCreate, GroupUpdate, GroupResponse, GroupMemberAdd
from auth import get_current_user

router = APIRouter(prefix="/groups", tags=["群组"])


@router.get("", response_model=List[dict])
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取群组列表"""
    result = await db.execute(
        select(Group).where(
            and_(Group.owner_id == current_user.id, Group.is_active == True)
        )
    )
    groups = result.scalars().all()
    
    # 手动构造返回数据
    return [
        {
            "id": g.id,
            "group_id": g.group_id,
            "owner_id": g.owner_id,
            "name": g.name,
            "description": g.description,
            "avatar": g.avatar,
            "is_active": g.is_active,
            "created_at": g.created_at,
            "members": []
        }
        for g in groups
    ]


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_data: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """创建群组"""
    from config import get_settings
    settings = get_settings()
    
    # 生成全局唯一 group_id
    import time
    global_group_id = f"group-{int(time.time())}-{settings.PORTAL_URL.replace('https://', '').replace('http://', '').replace('/', '_')}"
    
    # 创建群组
    new_group = Group(
        group_id=global_group_id,
        owner_id=current_user.id,
        name=group_data.name,
        description=group_data.description
    )
    
    db.add(new_group)
    await db.flush()
    
    # 添加成员
    if group_data.member_ids:
        for contact_id in group_data.member_ids:
            result = await db.execute(
                select(Contact).where(
                    and_(
                        Contact.id == contact_id,
                        Contact.owner_id == current_user.id,
                        Contact.is_active == True
                    )
                )
            )
            contact = result.scalar_one_or_none()
            if contact:
                # 使用原生 SQL 插入关联表
                await db.execute(
                    group_members.insert().values(
                        group_id=new_group.id,
                        contact_id=contact.id
                    )
                )
        
        await db.flush()
    
    # 手动构造返回数据，避免 SQLAlchemy 异步关系加载问题
    return {
        "id": new_group.id,
        "group_id": new_group.group_id,
        "owner_id": new_group.owner_id,
        "name": new_group.name,
        "description": new_group.description,
        "avatar": new_group.avatar,
        "is_active": new_group.is_active,
        "created_at": new_group.created_at,
        "members": []  # 简化处理，不加载成员详情
    }


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取群组详情"""
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
    
    return group


@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    group_data: GroupUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新群组"""
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == group_id,
                Group.owner_id == current_user.id
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    # 更新字段
    if group_data.name is not None:
        group.name = group_data.name
    if group_data.description is not None:
        group.description = group_data.description
    if group_data.avatar is not None:
        group.avatar = group_data.avatar
    
    await db.flush()
    return group


@router.post("/{group_id}/members", response_model=GroupResponse)
async def add_members(
    group_id: int,
    member_data: GroupMemberAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """添加群成员"""
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
    
    # 添加成员
    for contact_id in member_data.contact_ids:
        result = await db.execute(
            select(Contact).where(
                and_(
                    Contact.id == contact_id,
                    Contact.owner_id == current_user.id,
                    Contact.is_active == True
                )
            )
        )
        contact = result.scalar_one_or_none()
        if contact and contact not in group.members:
            group.members.append(contact)
    
    await db.flush()
    return group


@router.delete("/{group_id}/members/{contact_id}", response_model=GroupResponse)
async def remove_member(
    group_id: int,
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """移除群成员"""
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
    
    # 移除成员
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.id == contact_id,
                Contact.owner_id == current_user.id
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if contact and contact in group.members:
        group.members.remove(contact)
        await db.flush()
    
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除群组（软删除）"""
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == group_id,
                Group.owner_id == current_user.id
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found"
        )
    
    group.is_active = False
    await db.flush()
    
    return None


# ========== 群邀请功能 ==========

from schemas import GroupInvite, GroupInviteResponse, GroupJoin
from config import get_settings
import httpx


@router.post("/invite", response_model=dict)
async def invite_to_group(
    invite_data: GroupInvite,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    邀请联系人加入群组
    1. 验证群组和联系人
    2. 生成 shared_key 用于群消息验证
    3. 发送邀请到对方 Portal
    """
    # 验证群组
    result = await db.execute(
        select(Group).where(
            and_(
                Group.id == invite_data.group_id,
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
    
    # 验证联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.id == invite_data.contact_id,
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
    
    # 生成 shared_key
    import secrets
    shared_key = f"group_{secrets.token_hex(32)}"
    
    # 检查成员是否已在群组中
    result = await db.execute(
        select(group_members).where(
            and_(
                group_members.c.group_id == group.id,
                group_members.c.contact_id == contact.id
            )
        )
    )
    existing = result.scalar_one_or_none()
    
    # 跨 Portal 发送邀请（即使成员已在本地群组中，也要通知对方）
    print(f"[INVITE] Member existing check: {existing is not None}")
    settings = get_settings()
    print(f"[INVITE] Sending invite to {contact.portal_url}/api/groups/invite/receive")
    print(f"[INVITE] Group: {group.id}, Contact: {contact.id}, Portal: {contact.portal_url}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{contact.portal_url}/api/groups/invite/receive",
                json={
                    "group_id": group.group_id,  # 使用全局 group_id
                    "group_name": group.name,
                    "inviter_portal": settings.PORTAL_URL,
                    "shared_key": shared_key,
                    "timestamp": datetime.utcnow().isoformat()
                },
                timeout=10.0
            )
            print(f"[INVITE] Response status: {response.status_code}")
            print(f"[INVITE] Response body: {response.text}")
            
            if response.status_code == 200:
                # 对方接受邀请后，添加成员到群组（如果还没有）
                try:
                    await db.execute(
                        group_members.insert().values(
                            group_id=group.id,
                            contact_id=contact.id
                        )
                    )
                    await db.flush()
                except Exception as e:
                    print(f"[INVITE] Member already exists or insert error: {e}")
                
                return {
                    "status": "success",
                    "message": "Invitation sent and accepted",
                    "shared_key": shared_key
                }
            else:
                # 对方未接受，不添加成员
                return {
                    "status": "pending",
                    "message": "Invitation sent, waiting for acceptance"
                }
    except Exception as e:
        print(f"[INVITE] Failed to send invitation: {e}")
        import traceback
        traceback.print_exc()
        # 发送失败，返回错误
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send invitation: {str(e)}"
        )


@router.post("/invite/receive", response_model=dict)
async def receive_group_invite(
    invite_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收群邀请（跨 Portal 调用）
    不需要认证，创建待处理邀请
    """
    from models import GroupInvite
    
    # 查找当前用户
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active user"
        )
    
    # 获取邀请数据
    group_id = invite_data.get("group_id")
    group_name = invite_data.get("group_name", f"群-{group_id}")
    inviter_portal = invite_data.get("inviter_portal")
    shared_key = invite_data.get("shared_key")
    
    if not all([group_id, inviter_portal, shared_key]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields"
        )
    
    # 检查是否已有待处理邀请
    result = await db.execute(
        select(GroupInvite).where(
            and_(
                GroupInvite.owner_id == current_user.id,
                GroupInvite.group_id == group_id,
                GroupInvite.inviter_portal == inviter_portal,
                GroupInvite.status == "pending"
            )
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        return {
            "status": "success",
            "message": "Invitation already exists"
        }
    
    # 创建待处理邀请
    invite = GroupInvite(
        owner_id=current_user.id,
        group_id=group_id,
        group_name=group_name,
        inviter_portal=inviter_portal,
        shared_key=shared_key,
        status="pending"
    )
    db.add(invite)
    await db.flush()
    
    return {
        "status": "success",
        "message": "Invitation received"
    }


@router.get("/invites", response_model=List[dict])
async def get_group_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取收到的群邀请列表"""
    from models import GroupInvite
    
    result = await db.execute(
        select(GroupInvite).where(
            and_(
                GroupInvite.owner_id == current_user.id,
                GroupInvite.status == "pending"
            )
        ).order_by(GroupInvite.created_at.desc())
    )
    invites = result.scalars().all()
    
    return [
        {
            "id": invite.id,
            "group_id": invite.group_id,
            "group_name": invite.group_name,
            "inviter_portal": invite.inviter_portal,
            "status": invite.status,
            "created_at": invite.created_at.isoformat()
        }
        for invite in invites
    ]


@router.post("/invites/{invite_id}/accept", response_model=dict)
async def accept_group_invite(
    invite_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """接受群邀请"""
    from models import GroupInvite
    
    # 查找邀请
    result = await db.execute(
        select(GroupInvite).where(
            and_(
                GroupInvite.id == invite_id,
                GroupInvite.owner_id == current_user.id,
                GroupInvite.status == "pending"
            )
        )
    )
    invite = result.scalar_one_or_none()
    
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )
    
    # 查找或创建联系人
    result = await db.execute(
        select(Contact).where(
            and_(
                Contact.portal_url == invite.inviter_portal,
                Contact.is_active == True
            )
        )
    )
    contact = result.scalar_one_or_none()
    
    if not contact:
        contact = Contact(
            owner_id=current_user.id,
            display_name=f"用户-{invite.inviter_portal.split('//')[1]}",
            portal_url=invite.inviter_portal,
            shared_key=invite.shared_key,
            is_active=True
        )
        db.add(contact)
        await db.flush()
    
    # 查找或创建群组（使用全局 group_id）
    result = await db.execute(
        select(Group).where(
            and_(
                Group.group_id == invite.group_id,
                Group.is_active == True
            )
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        # 创建新群组，使用全局 group_id
        group = Group(
            group_id=invite.group_id,
            owner_id=current_user.id,
            name=invite.group_name,
            is_active=True
        )
        db.add(group)
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
    except Exception:
        pass  # 已存在
    
    # 更新邀请状态
    invite.status = "accepted"
    await db.flush()
    
    return {
        "status": "success",
        "message": "Joined group",
        "group_id": group.id,
        "group_name": group.name
    }


@router.post("/invites/{invite_id}/reject", response_model=dict)
async def reject_group_invite(
    invite_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """拒绝群邀请"""
    from models import GroupInvite
    
    result = await db.execute(
        select(GroupInvite).where(
            and_(
                GroupInvite.id == invite_id,
                GroupInvite.owner_id == current_user.id,
                GroupInvite.status == "pending"
            )
        )
    )
    invite = result.scalar_one_or_none()
    
    if not invite:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found"
        )
    
    invite.status = "rejected"
    await db.flush()
    
    return {
        "status": "success",
        "message": "Invitation rejected"
    }
