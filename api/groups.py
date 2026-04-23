from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import User, Group, Contact, group_members
from schemas import GroupCreate, GroupUpdate, GroupResponse, GroupMemberAdd, GroupInvite, GroupInviteResponse, GroupJoin
from auth import get_current_user
from config import get_settings
import httpx
import secrets
import time

router = APIRouter(prefix="/groups", tags=["群组"])


# ========== 基础群组操作 ==========

@router.get("")
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
    
    result_groups = []
    for g in groups:
        # 查询成员列表
        result = await db.execute(
            select(Contact).join(
                group_members,
                Contact.id == group_members.c.contact_id
            ).where(
                group_members.c.group_id == g.id
            )
        )
        members = result.scalars().all()
        member_list = [{"portal": m.portal_url, "display_name": m.display_name} for m in members]
        
        result_groups.append({
            "id": g.id,
            "group_id": g.group_id,
            "owner_id": g.owner_id,
            "name": g.name,
            "description": g.description,
            "avatar": g.avatar,
            "is_active": g.is_active,
            "created_at": g.created_at,
            "members": member_list,
            "member_count": len(member_list)
        })
    
    return result_groups


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_data: GroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """创建群组"""
    settings = get_settings()
    
    # 生成全局唯一 group_id: group-{timestamp}-{portal}
    timestamp = int(time.time())
    portal_domain = settings.PORTAL_URL.replace('https://', '').replace('http://', '')
    global_group_id = f"group-{timestamp}-{portal_domain}"
    
    # 生成群共享密钥
    import secrets
    group_key = f"gk_{secrets.token_hex(32)}"
    
    new_group = Group(
        group_id=global_group_id,
        group_key=group_key,
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
                await db.execute(
                    group_members.insert().values(
                        group_id=new_group.id,
                        contact_id=contact.id
                    )
                )
        await db.flush()
    
    return {
        "id": new_group.id,
        "group_id": new_group.group_id,
        "group_key": new_group.group_key,
        "owner_id": new_group.owner_id,
        "name": new_group.name,
        "description": new_group.description,
        "avatar": new_group.avatar,
        "is_active": new_group.is_active,
        "created_at": new_group.created_at,
        "members": []
    }


# ========== 群邀请功能（必须在 /{group_id} 之前）============

@router.post("/invite", response_model=dict)
async def invite_to_group(
    invite_data: GroupInvite,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """邀请联系人加入群组"""
    settings = get_settings()
    
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    
    # 生成 shared_key
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
    
    print(f"[INVITE] Sending to {contact.portal_url}")
    
    try:
        print(f"[INVITE] Sending group_db_id: {group.id}, group_id: {group.group_id}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{contact.portal_url}/api/groups/invite/receive",
                json={
                    "group_id": group.group_id,
                    "group_db_id": group.id,  # 数据库数字ID
                    "group_name": group.name,
                    "inviter_portal": settings.PORTAL_URL,
                    "invitee_portal": contact.portal_url,  # 被邀请者 Portal
                    "shared_key": shared_key,
                    "timestamp": datetime.utcnow().isoformat()
                },
                timeout=10.0
            )
            print(f"[INVITE] Response: {response.status_code}")
            
            if response.status_code == 200:
                # 对方立即接受，但成员添加在 accept 接口中处理
                return {"status": "success", "message": "Invitation sent and accepted", "shared_key": shared_key}
            else:
                return {"status": "pending", "message": "Invitation sent, waiting for acceptance"}
    except Exception as e:
        print(f"[INVITE] Failed: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to send invitation: {str(e)}")


@router.post("/invite/receive", response_model=dict)
async def receive_group_invite(
    invite_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """接收群邀请（跨 Portal 调用）"""
    from models import GroupInvite
    
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    
    if not current_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active user")
    
    group_id = invite_data.get("group_id")
    group_name = invite_data.get("group_name", f"群-{group_id}")
    inviter_portal = invite_data.get("inviter_portal")
    shared_key = invite_data.get("shared_key")
    
    if not all([group_id, inviter_portal, shared_key]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required fields")
    
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
        return {"status": "success", "message": "Invitation already exists"}
    
    # 创建待处理邀请
    invite = GroupInvite(
        owner_id=current_user.id,
        group_id=group_id,
        group_db_id=invite_data.get("group_db_id"),
        group_name=group_name,
        inviter_portal=inviter_portal,
        invitee_portal=invite_data.get("invitee_portal"),
        shared_key=shared_key,
        status="pending"
    )
    db.add(invite)
    await db.flush()
    
    return {"status": "success", "message": "Invitation received"}


@router.get("/invites")
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
    """接受群邀请 - 完整初始化 P2P 群聊机制"""
    from models import GroupInvite, GroupMemberCache
    import json
    import httpx
    from config import get_settings
    
    settings = get_settings()
    
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    
    # 检查是否是群主（邀请者是自己创建的群的邀请）
    is_owner = (invite.inviter_portal == settings.PORTAL_URL)
    
    if is_owner:
        # 我是群主，直接处理
        result = await db.execute(
            select(Contact).where(
                and_(
                    Contact.portal_url == invite.invitee_portal,
                    Contact.is_active == True
                )
            )
        )
        contact = result.scalar_one_or_none()
        
        if not contact:
            contact = Contact(
                owner_id=current_user.id,
                display_name=f"用户-{invite.invitee_portal.split('//')[1]}",
                portal_url=invite.invitee_portal,
                shared_key=invite.shared_key,
                is_active=True
            )
            db.add(contact)
            await db.flush()
        
        # 查找群组
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
            raise HTTPException(status_code=404, detail="Group not found")
        
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
            pass
        
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
        member_list.insert(0, {
            "portal": settings.PORTAL_URL,
            "display_name": current_user.display_name or "群主"
        })
        
        # 推送更新给所有成员
        new_version = (group.version or 1) + 1
        for member in members_result:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{member.portal_url}/api/groups/webhook/group-list-update",
                        json={
                            "group_id": group.group_id,
                            "db_id": group.id,
                            "owner_portal": settings.PORTAL_URL,
                            "action": "member_added",
                            "added_portal": invite.invitee_portal,
                            "added_name": current_user.display_name or "成员",
                            "members": member_list,
                            "group_key": invite.shared_key,
                            "version": new_version
                        },
                        timeout=10.0
                    )
            except Exception as e:
                print(f"Failed to push update to {member.portal_url}: {e}")
        
        # 也推送给新成员自己
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{invite.invitee_portal}/api/groups/webhook/group-list-update",
                    json={
                        "group_id": group.group_id,
                        "db_id": group.id,
                        "owner_portal": settings.PORTAL_URL,
                        "action": "member_added",
                        "added_portal": invite.invitee_portal,
                        "added_name": current_user.display_name or "成员",
                        "members": member_list,
                        "group_key": invite.shared_key,
                        "version": new_version
                    },
                    timeout=10.0
                )
        except Exception as e:
            print(f"Failed to push update to new member {invite.invitee_portal}: {e}")
        
        invite.status = "accepted"
        await db.flush()
        
        return {
            "status": "success",
            "message": "Joined group",
            "group_id": group.group_id,
            "db_id": group.id,
            "group_name": group.name,
            "is_owner": True
        }
    else:
        # 我是被邀请者，通知群主已接受邀请
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{invite.inviter_portal}/api/groups/group-accept",
                    json={
                        "group_id": invite.group_id,
                        "invitee_portal": settings.PORTAL_URL,
                        "invitee_name": current_user.display_name or "用户"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    # 获取群主返回的群信息
                    reg_data = response.json()
                    
                    # 存储到本地缓存
                    from models import GroupMemberCache
                    import json
                    
                    result = await db.execute(
                        select(GroupMemberCache).where(
                            GroupMemberCache.group_id == invite.group_id
                        )
                    )
                    cache = result.scalar_one_or_none()
                    
                    if cache:
                        cache.owner_portal = invite.inviter_portal
                        cache.group_key = reg_data.get("group_key", "")
                        cache.group_name = reg_data.get("group_name", invite.group_name)
                        cache.db_id = reg_data.get("db_id")
                        cache.members_json = json.dumps(reg_data.get("members", []))
                    else:
                        cache = GroupMemberCache(
                            group_id=invite.group_id,
                            db_id=reg_data.get("db_id"),
                            group_name=reg_data.get("group_name", invite.group_name),
                            owner_portal=invite.inviter_portal,
                            group_key=reg_data.get("group_key", ""),
                            members_json=json.dumps(reg_data.get("members", [])),
                            list_version=1
                        )
                        db.add(cache)
                    
                    await db.flush()
                    
                    invite.status = "accepted"
                    await db.flush()
                    
                    return {
                        "status": "success",
                        "message": "Joined group",
                        "group_id": invite.group_id,
                        "is_owner": False
                    }
                else:
                    raise HTTPException(status_code=502, detail="Failed to notify group owner")
                    
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Cannot connect to group owner: {str(e)}")


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    
    invite.status = "rejected"
    await db.flush()
    
    return {"status": "success", "message": "Invitation rejected"}


# ========== 群组 CRUD（/{group_id} 必须在最后）============

@router.get("/{group_id:int}", response_model=GroupResponse)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
    return group


@router.put("/{group_id:int}", response_model=GroupResponse)
async def update_group(
    group_id: int,
    group_data: GroupUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新群组"""
    result = await db.execute(
        select(Group).where(
            and_(Group.id == group_id, Group.owner_id == current_user.id)
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
    if group_data.name is not None:
        group.name = group_data.name
    if group_data.description is not None:
        group.description = group_data.description
    if group_data.avatar is not None:
        group.avatar = group_data.avatar
    
    await db.flush()
    return group


@router.post("/{group_id:int}/members", response_model=GroupResponse)
async def add_members(
    group_id: int,
    member_data: GroupMemberAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """添加群成员"""
    result = await db.execute(
        select(Group).where(
            and_(Group.id == group_id, Group.owner_id == current_user.id, Group.is_active == True)
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
    for contact_id in member_data.contact_ids:
        result = await db.execute(
            select(Contact).where(
                and_(Contact.id == contact_id, Contact.owner_id == current_user.id, Contact.is_active == True)
            )
        )
        contact = result.scalar_one_or_none()
        if contact and contact not in group.members:
            group.members.append(contact)
    
    await db.flush()
    return group


@router.delete("/{group_id:int}/members/{contact_id:int}", response_model=GroupResponse)
async def remove_member(
    group_id: int,
    contact_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """移除群成员"""
    result = await db.execute(
        select(Group).where(
            and_(Group.id == group_id, Group.owner_id == current_user.id, Group.is_active == True)
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
    result = await db.execute(
        select(Contact).where(
            and_(Contact.id == contact_id, Contact.owner_id == current_user.id)
        )
    )
    contact = result.scalar_one_or_none()
    
    if contact and contact in group.members:
        group.members.remove(contact)
        await db.flush()
    
    return group


@router.delete("/{group_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除群组（软删除）"""
    result = await db.execute(
        select(Group).where(
            and_(Group.id == group_id, Group.owner_id == current_user.id)
        )
    )
    group = result.scalar_one_or_none()
    
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    
    group.is_active = False
    await db.flush()
    
    return None
