from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from database import get_db
from models import User, Group, Contact
from schemas import GroupCreate, GroupUpdate, GroupResponse, GroupMemberAdd
from auth import get_current_user

router = APIRouter(prefix="/groups", tags=["群组"])


@router.get("", response_model=List[GroupResponse])
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
    return groups


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
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
                new_group.members.append(contact)
        
        await db.flush()
    
    return new_group


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
