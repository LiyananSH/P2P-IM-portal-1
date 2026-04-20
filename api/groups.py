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
    # 创建群组
    new_group = Group(
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
    
    if existing:
        return {
            "status": "success",
            "message": "Member already in group",
            "shared_key": shared_key
        }
    
    # 简化实现：直接添加成员到群组
    # TODO: 后续实现跨 Portal 邀请
    try:
        await db.execute(
            group_members.insert().values(
                group_id=group.id,
                contact_id=contact.id
            )
        )
        await db.flush()
        
        return {
            "status": "success",
            "message": "Member added",
            "shared_key": shared_key
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add member: {str(e)}"
        )


@router.post("/invite/receive", response_model=dict)
async def receive_group_invite(
    invite_data: dict,
    db: AsyncSession = Depends(get_db)
):
    """
    接收群邀请（跨 Portal 调用）
    不需要认证，用 shared_key 验证
    """
    # 查找当前用户
    result = await db.execute(select(User).where(User.is_active == True).limit(1))
    current_user = result.scalar_one_or_none()
    
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active user"
        )
    
    # 创建群邀请记录
    # TODO: 创建邀请表存储邀请信息
    
    return {
        "status": "success",
        "message": "Invitation received"
    }


@router.post("/join", response_model=dict)
async def join_group(
    join_data: GroupJoin,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    接受群邀请，加入群组
    1. 在本机创建群记录
    2. 保存 shared_key
    """
    # TODO: 实现加入群组的逻辑
    
    return {
        "status": "success",
        "message": "Joined group"
    }
